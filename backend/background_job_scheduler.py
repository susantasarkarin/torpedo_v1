"""
Background Job Scheduler for Continuous Lead Generation
==========================================================

This module manages:
1. Automatic resume of paused web search jobs
2. Continuous lead generation monitoring
3. Daily limit resets at midnight UTC
4. Error recovery and circuit breaker management

Usage:
    - Automatically started by the main FastAPI app
    - Configure via Settings UI
    - Monitor via /leads/import/web-search/status/{job_id}

"""

import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============

try:
    from .database import get_database
except ImportError:
    from database import get_database

db = get_database("email_automation")
settings_db = get_database("torpedo_settings")

web_search_jobs_collection = db["web_search_jobs"]
scheduler_config_collection = settings_db["scheduler_config"]
app_settings_collection = settings_db["app_settings"]
error_tracking_collection = db["error_tracking"]

# ============== JOB STATUS CONSTANTS ==============

class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    QUOTA_EXCEEDED = "quota_exceeded"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    API_ERROR = "api_error"


# ============== GLOBAL SCHEDULER ==============

_scheduler = None
_scheduler_initialized = False


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the global scheduler instance"""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def is_scheduler_running() -> bool:
    """Check if scheduler is running"""
    global _scheduler
    return _scheduler is not None and _scheduler.running


# ============== JOB RECOVERY ==============

async def check_and_resume_paused_jobs():
    """
    Check for paused jobs and resume them if conditions are met.
    Called automatically at configured intervals.
    """
    try:
        logger.info("[Scheduler] Checking for paused jobs to resume...")
        
        # Find paused jobs
        paused_jobs = list(web_search_jobs_collection.find({
            "status": {"$in": [JobStatus.PAUSED, JobStatus.QUOTA_EXCEEDED]}
        }))
        
        for job in paused_jobs:
            job_id = job.get("job_id")
            status = job.get("status")
            
            # Skip jobs paused manually
            if job.get("manually_paused"):
                logger.debug(f"[{job_id}] Skipping manually paused job")
                continue
            
            try:
                await attempt_job_resume(job_id, status)
            except Exception as e:
                logger.error(f"[{job_id}] Error attempting resume: {e}")
        
        logger.info(f"[Scheduler] Checked {len(paused_jobs)} paused jobs")
        
    except Exception as e:
        logger.error(f"[Scheduler] Error in check_and_resume_paused_jobs: {e}")


async def attempt_job_resume(job_id: str, current_status: str):
    """
    Attempt to resume a paused job
    
    Resumes if:
    - Status is PAUSED (user pause lifted or manual intervention)
    - Status is QUOTA_EXCEEDED (new day)
    - No recent API errors
    """
    logger.info(f"[{job_id}] Attempting to resume (status: {current_status})")

    async def _restart_job_execution(resume_reason: str):
        """Set status to pending and start the async job loop again."""
        web_search_jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": JobStatus.PENDING,
                "last_update": datetime.utcnow(),
                "resume_reason": resume_reason,
            }}
        )
        try:
            try:
                from .leads.router import run_web_search_job
            except Exception:
                from leads.router import run_web_search_job

            asyncio.create_task(run_web_search_job(job_id))
            logger.info(f"[{job_id}] ▶️ Relaunch task queued ({resume_reason})")
        except Exception as relaunch_err:
            logger.error(f"[{job_id}] Failed to relaunch job task: {relaunch_err}")
            web_search_jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {
                    "status": JobStatus.FAILED,
                    "last_update": datetime.utcnow(),
                    "last_error": f"Scheduler relaunch failed: {str(relaunch_err)[:200]}",
                }}
            )
    
    if current_status == JobStatus.QUOTA_EXCEEDED:
        # Check if it's a new day
        job = web_search_jobs_collection.find_one({"job_id": job_id})
        if not job:
            return
        
        current_day = datetime.utcnow().date().isoformat()
        job_day = job.get("day_started")
        
        if current_day != job_day:
            # New day - reset daily limit and resume
            logger.info(f"[{job_id}] New day detected, resetting daily limit")
            web_search_jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {
                    "leads_today": 0,
                    "day_started": current_day
                }}
            )
            await _restart_job_execution("quota_reset")
            logger.info(f"[{job_id}] ✅ Resumed after daily quota reset")
    
    elif current_status == JobStatus.PAUSED:
        # Check global search control (primary source: app_settings.search_control)
        global_config = app_settings_collection.find_one({"_id": "search_control"})
        if not global_config:
            # Backward compatibility with older scheduler config document
            global_config = scheduler_config_collection.find_one({"_id": "global_search_control"})
        
        if global_config and global_config.get("paused"):
            logger.debug(f"[{job_id}] Global search still paused: {global_config.get('paused_reason')}")
            return
        
        # Check if too many recent errors
        recent_errors = error_tracking_collection.find_one({
            "job_id": job_id,
            "timestamp": {"$gte": datetime.utcnow() - timedelta(hours=1)}
        })
        
        if recent_errors and recent_errors.get("error_count", 0) > 10:
            logger.warning(f"[{job_id}] Too many recent errors, not resuming yet")
            return
        
        # Resume paused job
        logger.info(f"[{job_id}] Resuming paused job")
        await _restart_job_execution("scheduler_resume")
        logger.info(f"[{job_id}] ✅ Resumed successfully")


async def cleanup_stale_jobs():
    """
    Clean up jobs that:
    - Completed more than 7 days ago
    - Failed with no recovery attempts
    - Have been paused for more than 30 days
    """
    try:
        logger.info("[Scheduler] Cleaning up stale jobs...")
        
        one_week_ago = datetime.utcnow() - timedelta(days=7)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        # Archive completed jobs
        completed_jobs = web_search_jobs_collection.find({
            "status": JobStatus.COMPLETED,
            "completed_at": {"$lt": one_week_ago}
        })
        
        completed_count = 0
        for job in completed_jobs:
            # Archive to history collection
            try:
                db["web_search_jobs_archive"].insert_one(job)
                web_search_jobs_collection.delete_one({"job_id": job["job_id"]})
                completed_count += 1
            except Exception as e:
                logger.error(f"Error archiving job {job.get('job_id')}: {e}")
        
        if completed_count > 0:
            logger.info(f"[Scheduler] Archived {completed_count} completed jobs")
        
        # Remove stale paused jobs
        stale_paused = web_search_jobs_collection.find({
            "status": JobStatus.PAUSED,
            "last_update": {"$lt": thirty_days_ago}
        })
        
        stale_count = 0
        for job in stale_paused:
            web_search_jobs_collection.delete_one({"job_id": job["job_id"]})
            stale_count += 1
        
        if stale_count > 0:
            logger.info(f"[Scheduler] Removed {stale_count} stale paused jobs")
        
    except Exception as e:
        logger.error(f"[Scheduler] Error in cleanup_stale_jobs: {e}")


async def monitor_active_jobs():
    """
    Monitor active jobs and log health status
    """
    try:
        active_jobs = list(web_search_jobs_collection.find({
            "status": {"$in": [JobStatus.RUNNING, JobStatus.PENDING]}
        }))
        
        running_count = sum(1 for j in active_jobs if j["status"] == JobStatus.RUNNING)
        pending_count = sum(1 for j in active_jobs if j["status"] == JobStatus.PENDING)
        
        if running_count > 0 or pending_count > 0:
            total_leads = sum(j.get("total_imported", 0) for j in active_jobs)
            logger.info(f"[Scheduler] Active jobs: {running_count} running, {pending_count} pending, "
                       f"Total leads: {total_leads}")
            
            # Log individual job status
            for job in active_jobs:
                job_id = job["job_id"]
                status = job["status"]
                imported = job.get("total_imported", 0)
                today = job.get("leads_today", 0)
                
                logger.debug(f"  [{job_id}] {status} - Imported: {imported}, Today: {today}")
        
    except Exception as e:
        logger.error(f"[Scheduler] Error in monitor_active_jobs: {e}")


async def reset_error_tracking():
    """Reset error tracking counters daily"""
    try:
        # Reset all job error counters
        error_tracking_collection.update_many(
            {"timestamp": {"$lt": datetime.utcnow() - timedelta(days=1)}},
            {"$set": {"error_count": 0}}
        )
        
        logger.info("[Scheduler] Reset daily error counters")
        
    except Exception as e:
        logger.error(f"[Scheduler] Error in reset_error_tracking: {e}")


async def background_enrich_leads():
    """
    Low-priority background job to enrich leads that need enrichment.
    Runs every 30 minutes, processes a small batch (10 leads) to avoid
    competing with higher-priority real-time operations.
    """
    try:
        leads_raw = db["leads_raw"]
        
        # Find leads that need enrichment, oldest first
        pending_leads = list(leads_raw.find(
            {
                "enrichment_status": {"$in": ["needed", "pending"]},
                # Don't re-process recently failed ones
                "$or": [
                    {"last_enrichment_attempt": {"$exists": False}},
                    {"last_enrichment_attempt": {"$lt": datetime.utcnow() - timedelta(hours=6)}}
                ]
            }
        ).sort("created_at", 1).limit(50))  # Increased from 10 → 50 for faster catch-up
        
        if not pending_leads:
            logger.debug("[Enrichment] No leads pending enrichment")
            return
        
        logger.info(f"[Enrichment] Processing {len(pending_leads)} leads for low-priority enrichment")
        
        enriched_count = 0
        error_count = 0
        
        for lead in pending_leads:
            try:
                lead_id = str(lead['_id'])
                email = lead.get('email', 'unknown')
                
                # Try to enrich using web search
                try:
                    from leads.web_search_enrichment import enrich_company_with_websearch

                    # Build context from available lead data
                    # Use company_domain as a fallback when company name is absent —
                    # this allows enrichment of AI-discovered leads that only have a domain.
                    company = (
                        lead.get('company') or lead.get('company_name')
                        or lead.get('company_domain', '')
                    )
                    if not company:
                        # Still nothing — skip this lead
                        leads_raw.update_one(
                            {'_id': lead['_id']},
                            {'$set': {
                                'enrichment_status': 'skipped',
                                'last_enrichment_attempt': datetime.utcnow()
                            }}
                        )
                        continue
                    
                    context = f"Contact: {lead.get('name', '')} | Title: {lead.get('title', '')} | Email: {email}"
                    result = await asyncio.to_thread(
                        enrich_company_with_websearch,
                        company,
                        additional_context=context
                    )
                    
                    if result:
                        # Merge enrichment results back to the lead
                        update_fields = {
                            'enrichment_status': 'enriched',
                            'enriched_at': datetime.utcnow(),
                            'enrichment_source': 'openai_websearch',
                            'last_enrichment_attempt': datetime.utcnow(),
                        }
                        
                        # Copy enrichment fields
                        enrichment_fields = [
                            'company_name', 'company_domain', 'company_website',
                            'company_employee_count', 'company_industry', 'company_type',
                            'company_headquarters', 'company_revenue_range',
                            'title', 'linkedin_url', 'location', 'phone'
                        ]
                        for field in enrichment_fields:
                            if result.get(field) and not lead.get(field):
                                update_fields[field] = result[field]
                        
                        # Recalculate lead bracket after enrichment
                        merged = {**lead, **update_fields}
                        from leads.canonical_ingestion import determine_lead_bracket
                        update_fields['lead_bracket'] = determine_lead_bracket(merged)

                        # Generate email from pattern if still missing
                        if not merged.get('email'):
                            try:
                                from leads.email_pattern_system import EmailPatternSystem
                                domain = merged.get('company_domain', '')
                                first = merged.get('first_name', '')
                                last = merged.get('last_name', '')
                                if domain and first:
                                    ps = EmailPatternSystem()
                                    built = ps.build_email(domain, first, last)
                                    if built:
                                        update_fields['email'] = built
                                        update_fields['email_source'] = 'pattern_applied'
                            except Exception as _ep:
                                logger.debug(f"[Enrichment] Email pattern generation skipped: {_ep}")
                        
                        leads_raw.update_one(
                            {'_id': lead['_id']},
                            {'$set': update_fields}
                        )
                        enriched_count += 1
                    else:
                        # Mark as attempted so we don't retry too soon
                        leads_raw.update_one(
                            {'_id': lead['_id']},
                            {'$set': {
                                'last_enrichment_attempt': datetime.utcnow(),
                                'enrichment_status': 'no_data'
                            }}
                        )
                except ImportError:
                    logger.warning("[Enrichment] web_search_enrichment module not available")
                    return
                    
            except Exception as e:
                error_count += 1
                logger.error(f"[Enrichment] Error enriching lead {lead.get('email', '?')}: {e}")
                # Mark the attempt
                leads_raw.update_one(
                    {'_id': lead['_id']},
                    {'$set': {
                        'last_enrichment_attempt': datetime.utcnow(),
                        'enrichment_status': 'error'
                    }}
                )
            
            # Throttle between leads (2 second delay for low-priority)
            await asyncio.sleep(2)
        
        logger.info(f"[Enrichment] Completed batch: {enriched_count} enriched, {error_count} errors")
        
    except Exception as e:
        logger.error(f"[Enrichment] Error in background_enrich_leads: {e}")


# ============== SCHEDULER INITIALIZATION ==============

def initialize_scheduler(loop=None):
    """
    Initialize and start the background scheduler
    
    Call this once when the FastAPI app starts
    """
    global _scheduler_initialized
    
    if _scheduler_initialized:
        logger.info("[Scheduler] Already initialized")
        return
    
    try:
        scheduler = get_scheduler()
        
        # Add jobs
        # Check for jobs to resume every 5 minutes
        scheduler.add_job(
            check_and_resume_paused_jobs,
            CronTrigger(minute="*/5"),
            id="check_resume_jobs",
            name="Check and Resume Paused Jobs",
            max_instances=1
        )
        
        # Monitor active jobs every 10 minutes
        scheduler.add_job(
            monitor_active_jobs,
            CronTrigger(minute="*/10"),
            id="monitor_jobs",
            name="Monitor Active Jobs",
            max_instances=1
        )
        
        # Cleanup stale jobs daily at 2 AM UTC
        scheduler.add_job(
            cleanup_stale_jobs,
            CronTrigger(hour=2, minute=0, timezone=pytz.UTC),
            id="cleanup_jobs",
            name="Cleanup Stale Jobs",
            max_instances=1
        )
        
        # Reset error tracking daily at 1 AM UTC
        scheduler.add_job(
            reset_error_tracking,
            CronTrigger(hour=1, minute=0, timezone=pytz.UTC),
            id="reset_errors",
            name="Reset Error Tracking",
            max_instances=1
        )
        
        # CINT survey pool cleanup every 5 minutes
        # Refreshes offerwall cache + marks stale surveys inactive in DB
        try:
            try:
                from .tasks.cint_survey_cleanup import async_cint_survey_cleanup
            except ImportError:
                from tasks.cint_survey_cleanup import async_cint_survey_cleanup
            
            scheduler.add_job(
                async_cint_survey_cleanup,
                CronTrigger(minute="*/5"),
                id="cint_survey_cleanup",
                name="CINT Survey Pool Cleanup",
                max_instances=1
            )
            logger.info("[Scheduler] Added CINT survey pool cleanup (every 5 min)")
        except Exception as e:
            logger.warning(f"[Scheduler] Could not add CINT cleanup job: {e}")
        
        # Low-priority lead enrichment every 30 minutes
        scheduler.add_job(
            background_enrich_leads,
            CronTrigger(minute="*/30"),
            id="background_enrichment",
            name="Low-Priority Lead Enrichment",
            max_instances=1
        )
        logger.info("[Scheduler] Added low-priority lead enrichment (every 30 min)")

        # Email metadata classification — classify inbound Gmail Workspace emails
        # via AI and auto-move CLIENT/VENDOR leads to sales leads every 2 hours.
        # Supersedes the old mail_pool_extraction (regex-only) job.
        try:
            from leads.email_processor import EmailProcessor

            async def _run_email_metadata_classification():
                try:
                    processor = EmailProcessor()
                    result = processor.process_batch_from_metadata(limit=100, since_hours=2)
                    logger.info(
                        f"[Scheduler/EmailClassifier] processed={result.get('total_processed', 0)} "
                        f"auto_moved={result.get('auto_moved_to_leads', 0)} "
                        f"errors={len(result.get('errors', []))}"
                    )
                except Exception as _e:
                    logger.error(f"[Scheduler/EmailClassifier] Error: {_e}")

            scheduler.add_job(
                _run_email_metadata_classification,
                "interval",
                hours=2,
                id="email_metadata_classification",
                name="Gmail Email Classification & Lead Extraction",
                max_instances=1,
            )
            logger.info("[Scheduler] Added Gmail email classification job (every 2h)")
        except Exception as e:
            logger.warning(f"[Scheduler] Could not add email classification job: {e}")

        # Rule-based ICP lead classification — process Pending leads_raw every 5 minutes
        try:
            from leads.canonical_ingestion import sync_to_enriched, compute_icp_basket
            from database import get_async_collection

            async def _run_lead_classification():
                try:
                    import pymongo as _pymongo
                    import datetime as _dt
                    _client = _pymongo.MongoClient("mongodb://localhost:27017/")
                    _col_raw = _client["email_automation"]["leads_raw"]
                    _col_enriched = _client["email_automation"]["leads_enriched"]

                    query = {"classification_status": {"$in": ["Pending", "pending"]}}
                    total = _col_raw.count_documents(query)
                    if total == 0:
                        return

                    classified = 0
                    failed = 0
                    BATCH = 500
                    skip = 0
                    while True:
                        batch = list(_col_raw.find(query).skip(skip).limit(BATCH))
                        if not batch:
                            break
                        for doc in batch:
                            lead_id = str(doc["_id"])
                            try:
                                sync_to_enriched(doc, lead_id)
                                _col_raw.update_one(
                                    {"_id": doc["_id"]},
                                    {"$set": {
                                        "classification_status": "Classified",
                                        "classified_at": _dt.datetime.utcnow(),
                                        "classification_attempts": doc.get("classification_attempts", 0) + 1,
                                        "last_error": None,
                                    }}
                                )
                                classified += 1
                            except Exception as _le:
                                attempts = doc.get("classification_attempts", 0) + 1
                                _col_raw.update_one(
                                    {"_id": doc["_id"]},
                                    {"$set": {
                                        "classification_status": "Failed" if attempts >= 3 else "Pending",
                                        "classification_attempts": attempts,
                                        "last_error": str(_le),
                                        "last_attempt_at": _dt.datetime.utcnow(),
                                    }}
                                )
                                failed += 1
                        skip += BATCH

                    logger.info(
                        f"[Scheduler/LeadClassifier] classified={classified} failed={failed} "
                        f"(of {total} pending)"
                    )
                except Exception as _e:
                    logger.error(f"[Scheduler/LeadClassifier] Error: {_e}")

            scheduler.add_job(
                _run_lead_classification,
                "interval",
                minutes=5,
                id="rule_based_lead_classification",
                name="Rule-Based ICP Lead Classification",
                max_instances=1,
            )
            logger.info("[Scheduler] Added rule-based lead classification job (every 5 min)")
        except Exception as e:
            logger.warning(f"[Scheduler] Could not add lead classification job: {e}")

        # Mail pool stats cache — pre-compute stats every 15 minutes (lightweight background job)
        try:
            from routers.gmail import _compute_and_persist_mail_pool_stats

            async def _run_mail_pool_stats():
                try:
                    import threading
                    threading.Thread(target=_compute_and_persist_mail_pool_stats, daemon=True).start()
                except Exception as _e:
                    logger.error(f"[Scheduler/MailPoolStats] Error: {_e}")

            scheduler.add_job(
                _run_mail_pool_stats,
                "interval",
                minutes=15,
                id="mail_pool_stats_cache",
                name="Mail Pool Stats Cache Refresh",
                max_instances=1,
            )
            logger.info("[Scheduler] Added mail pool stats cache refresh (every 15 min)")
        except Exception as e:
            logger.warning(f"[Scheduler] Could not add mail pool stats job: {e}")
        
        # Start scheduler
        if not scheduler.running:
            # scheduler.start() is synchronous in APScheduler
            scheduler.start()
            
            logger.info("[Scheduler] ✅ Background scheduler started successfully")
            logger.info("[Scheduler] Jobs scheduled:")
            for job in scheduler.get_jobs():
                logger.info(f"  - {job.name} ({job.id})")
        
        _scheduler_initialized = True
        
    except Exception as e:
        logger.error(f"[Scheduler] Error initializing scheduler: {e}")
        raise


def shutdown_scheduler():
    """Shutdown the scheduler gracefully"""
    global _scheduler
    
    if _scheduler and _scheduler.running:
        try:
            _scheduler.shutdown()
            logger.info("[Scheduler] ✅ Scheduler shutdown complete")
        except Exception as e:
            logger.error(f"[Scheduler] Error shutting down: {e}")


def get_scheduler_status() -> Dict[str, any]:
    """Get current scheduler status"""
    try:
        scheduler = get_scheduler()
        
        running_jobs = list(web_search_jobs_collection.find({
            "status": JobStatus.RUNNING
        }))
        
        paused_jobs = list(web_search_jobs_collection.find({
            "status": {"$in": [JobStatus.PAUSED, JobStatus.QUOTA_EXCEEDED]}
        }))
        
        return {
            "scheduler_running": scheduler.running if scheduler else False,
            "active_jobs": len(running_jobs),
            "paused_jobs": len(paused_jobs),
            "scheduled_jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None
                }
                for job in (scheduler.get_jobs() if scheduler else [])
            ],
            "last_check": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"[Scheduler] Error getting status: {e}")
        return {
            "error": str(e),
            "scheduler_running": False
        }


# ============== ERROR TRACKING ==============

def track_job_error(job_id: str, error: str, error_type: str = "api"):
    """Track an error for a job"""
    try:
        error_tracking_collection.update_one(
            {"job_id": job_id},
            {
                "$inc": {"error_count": 1},
                "$set": {
                    "last_error": error,
                    "last_error_type": error_type,
                    "timestamp": datetime.utcnow()
                }
            },
            upsert=True
        )
    except Exception as e:
        logger.error(f"[Scheduler] Error tracking error for {job_id}: {e}")


def clear_job_errors(job_id: str):
    """Clear error tracking for a job"""
    try:
        error_tracking_collection.update_one(
            {"job_id": job_id},
            {"$set": {"error_count": 0}}
        )
    except Exception as e:
        logger.error(f"[Scheduler] Error clearing errors for {job_id}: {e}")


if __name__ == "__main__":
    # For testing
    print("Background Job Scheduler Module")
    print("================================")
    print("\nThis module is meant to be imported and used by the FastAPI app.")
    print("It provides automatic job recovery, monitoring, and cleanup.")
    print("\nUsage:")
    print("  from background_job_scheduler import initialize_scheduler, shutdown_scheduler")
    print("  ")
    print("  # In FastAPI startup event:")
    print("  initialize_scheduler()")
    print("  ")
    print("  # In FastAPI shutdown event:")
    print("  shutdown_scheduler()")
