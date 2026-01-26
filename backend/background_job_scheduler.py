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
from pymongo import MongoClient
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client["email_automation"]
settings_db = client["torpedo_settings"]

web_search_jobs_collection = db["web_search_jobs"]
scheduler_config_collection = settings_db["scheduler_config"]
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
                    "status": JobStatus.RUNNING,
                    "leads_today": 0,
                    "day_started": current_day
                }}
            )
            logger.info(f"[{job_id}] ✅ Resumed after daily quota reset")
    
    elif current_status == JobStatus.PAUSED:
        # Check global search control
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
        web_search_jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {"status": JobStatus.RUNNING}}
        )
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
        
        # Start scheduler
        if not scheduler.running:
            if loop:
                scheduler.start()
            else:
                # If no loop provided, assume running in asyncio context
                asyncio.create_task(scheduler.start())
            
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
