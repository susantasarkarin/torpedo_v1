"""
AGENT 4 — BACKEND API ENGINEER
FastAPI Router for Lead Management
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, UploadFile, File, Form, Body
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel
import asyncio
import random
import os
import uuid
from pymongo import MongoClient
from dotenv import load_dotenv

from .models import (
    LeadInput, LeadImportRequest, LeadImportResponse,
    LeadClassifyRequest, LeadClassifyResponse, LeadFilterParams,
    AttachLeadsRequest, SeniorityLevel, Department, Persona,
    CompanySize, Region, ClassificationStatus
)
from .service import (
    import_leads, classify_pending_leads, classify_single_lead,
    get_leads, get_raw_leads_with_status, attach_leads_to_campaign,
    get_lead_statistics, delete_leads_by_source, delete_all_leads,
    get_enriched_lead_by_id, find_duplicate_emails, delete_duplicate_emails,
    leads_enriched_collection
)
from .ingestion import (
    search_linkedin_leads, parse_csv_leads, import_from_google_sheet,
    import_leads_from_source
)
from .imap_leads_service import (
    import_leads_from_emails, get_email_leads, get_segment_statistics,
    get_imap_accounts, add_imap_account, remove_imap_account,
    test_imap_connection, EmailSegment, imap_accounts_collection,
    detect_aliases_from_sent, add_detected_aliases
)
from .scheduler import (
    start_scheduler, stop_scheduler, get_scheduler_status,
    get_scheduler_logs, update_scheduler_config
)

load_dotenv()

router = APIRouter(prefix="/leads", tags=["Leads"])


# ============== MONGODB CONNECTION FOR JOBS ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
_mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_jobs_db = _mongo_client['email_automation']
_torpedo_gmail_db = _mongo_client['torpedo_gmail']  # Gmail OAuth emails database
web_search_jobs_collection = _jobs_db['web_search_jobs']
email_metadata_collection = _torpedo_gmail_db['email_metadata']

# Create indexes for jobs
try:
    web_search_jobs_collection.create_index("job_id", unique=True)
    web_search_jobs_collection.create_index("status")
    web_search_jobs_collection.create_index("created_at")
except Exception as e:
    print(f"Warning: Could not create job indexes: {e}")

# ============== AI COMPANY DATABASE ==============
ai_companies_collection = _jobs_db['ai_discovered_companies']

try:
    ai_companies_collection.create_index("domain", unique=True)
    ai_companies_collection.create_index("status")
    ai_companies_collection.create_index("discovered_at")
    ai_companies_collection.create_index("last_searched")
    ai_companies_collection.create_index([("industry", 1), ("status", 1)])
    print("✅ AI Company Database indexes created")
except Exception as e:
    print(f"Warning: Could not create AI company indexes: {e}")


# ============== JOB STATUS CONSTANTS ==============

class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    QUOTA_EXCEEDED = "quota_exceeded"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    API_ERROR = "api_error"  # New status for API credential errors


# ============== GLOBAL SEARCH CONTROL ==============

def get_global_search_control() -> dict:
    """Get global search control settings (pause all jobs, circuit breaker state)"""
    try:
        settings_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        settings_db = settings_client['torpedo_settings']
        app_settings = settings_db['app_settings']
        control = app_settings.find_one({"_id": "search_control"})
        if control:
            return {
                "paused": control.get("paused", False),
                "paused_at": control.get("paused_at"),
                "paused_reason": control.get("paused_reason", ""),
                "consecutive_errors": control.get("consecutive_errors", 0),
                "circuit_breaker_open": control.get("circuit_breaker_open", False),
                "last_error": control.get("last_error"),
                "auto_resume_disabled": control.get("auto_resume_disabled", False),
            }
    except Exception as e:
        print(f"Error reading search control: {e}")
    return {
        "paused": False,
        "paused_at": None,
        "paused_reason": "",
        "consecutive_errors": 0,
        "circuit_breaker_open": False,
        "last_error": None,
        "auto_resume_disabled": False,
    }


def set_global_search_control(updates: dict):
    """Update global search control settings"""
    try:
        settings_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        settings_db = settings_client['torpedo_settings']
        app_settings = settings_db['app_settings']
        app_settings.update_one(
            {"_id": "search_control"},
            {"$set": updates},
            upsert=True
        )
    except Exception as e:
        print(f"Error updating search control: {e}")


def increment_error_count(error_msg: str):
    """Increment consecutive error count and trip circuit breaker if needed"""
    control = get_global_search_control()
    new_count = control.get("consecutive_errors", 0) + 1
    
    # Circuit breaker: trips after 5 consecutive errors
    circuit_open = new_count >= 5
    
    set_global_search_control({
        "consecutive_errors": new_count,
        "last_error": {"message": error_msg, "timestamp": datetime.utcnow().isoformat()},
        "circuit_breaker_open": circuit_open,
    })
    
    if circuit_open:
        print(f"⚠️ Circuit breaker TRIPPED after {new_count} consecutive errors: {error_msg}")
    
    return circuit_open


def reset_error_count():
    """Reset error count on successful operation"""
    set_global_search_control({
        "consecutive_errors": 0,
        "circuit_breaker_open": False,
    })


def stop_all_jobs(reason: str = "Emergency stop") -> int:
    """Stop ALL running/pending web search jobs immediately"""
    result = web_search_jobs_collection.update_many(
        {"status": {"$in": [JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PAUSED, JobStatus.QUOTA_EXCEEDED]}},
        {"$set": {"status": JobStatus.STOPPED, "last_update": datetime.utcnow()}}
    )
    
    # Also set global pause flag
    set_global_search_control({
        "paused": True,
        "paused_at": datetime.utcnow().isoformat(),
        "paused_reason": reason,
    })
    
    return result.modified_count


# ============== RATE LIMITING (DYNAMIC FROM SETTINGS) ==============

# MongoDB connection for settings
_settings_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_settings_db = _settings_client['torpedo_settings']
_app_settings_collection = _settings_db['app_settings']

def get_rate_limit_settings() -> dict:
    """Get rate limiting settings (legacy - returns defaults only)"""
    return {"daily_limit": 400, "hourly_limit": 50, "query_delay": 3, "monthly_budget": 50.0, "enabled": True}

# Legacy constants (used as fallback only)
DAILY_LIMIT = 400  # Conservative default for $50/month
LEADS_PER_MINUTE = 3  # Reduced rate
DELAY_BETWEEN_BATCHES = 20  # Increased delay


# ============== IMPORT MODELS ==============

class GoogleSearchRequest(BaseModel):
    query: str
    num_results: int = 10


class WebSearchRequest(BaseModel):
    """Enhanced web search with filters - supports multi-select"""
    designation: str = ""  # e.g., "CEO", "VP Sales" - comma separated for multiple
    countries: List[str] = []  # Multiple countries supported
    seniorities: List[str] = []  # Multiple seniority levels supported
    custom_query: str = ""  # Additional search terms
    # Note: No target_count - job runs indefinitely until stopped, controlled by rate limits
    # Legacy single-value fields for backward compatibility
    country: str = ""
    seniority: str = ""


class GoogleSheetRequest(BaseModel):
    spreadsheet_id: str
    sheet_name: str = "Sheet1"
    range_notation: str = "A:Z"


# ============== JOB HELPER FUNCTIONS ==============

def create_job(config: dict, target_count: int) -> str:
    """Create a new web search job in MongoDB"""
    job_id = str(uuid.uuid4())[:8]
    job = {
        "job_id": job_id,
        "status": JobStatus.PENDING,
        "config": config,
        "target_count": target_count,
        "total_found": 0,
        "total_imported": 0,
        "total_duplicates": 0,
        "total_classified": 0,
        "emails_found": 0,
        "leads_today": 0,
        "queries_used": 0,
        "current_query": "",
        "query_combinations": [],
        "seen_urls": [],
        "errors": [],
        "created_at": datetime.utcnow(),
        "started_at": None,
        "last_update": None,
        "completed_at": None,
        "day_started": datetime.utcnow().date().isoformat()
    }
    web_search_jobs_collection.insert_one(job)
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    """Get job by ID"""
    return web_search_jobs_collection.find_one({"job_id": job_id})


def update_job(job_id: str, updates: dict):
    """Update job fields"""
    updates["last_update"] = datetime.utcnow()
    web_search_jobs_collection.update_one(
        {"job_id": job_id},
        {"$set": updates}
    )


def add_job_error(job_id: str, error: str):
    """Add error to job's error list"""
    web_search_jobs_collection.update_one(
        {"job_id": job_id},
        {
            "$push": {"errors": {"$each": [f"[{datetime.utcnow().isoformat()}] {error}"], "$slice": -50}},
            "$set": {"last_update": datetime.utcnow()}
        }
    )


def increment_job_counters(job_id: str, found: int = 0, imported: int = 0, 
                           duplicates: int = 0, classified: int = 0, emails: int = 0):
    """Increment job counters atomically"""
    web_search_jobs_collection.update_one(
        {"job_id": job_id},
        {
            "$inc": {
                "total_found": found,
                "total_imported": imported,
                "total_duplicates": duplicates,
                "total_classified": classified,
                "emails_found": emails,
                "leads_today": imported,
                "queries_used": 1 if found > 0 else 0
            },
            "$set": {"last_update": datetime.utcnow()}
        }
    )


def get_incomplete_jobs() -> List[dict]:
    """Get jobs that need to be resumed"""
    return list(web_search_jobs_collection.find({
        "status": {"$in": [JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PAUSED, JobStatus.QUOTA_EXCEEDED]}
    }))


def check_and_reset_daily_limit(job_id: str) -> bool:
    """Check if daily limit should be reset (new day). Returns True if reset happened."""
    job = get_job(job_id)
    if not job:
        return False
    
    current_day = datetime.utcnow().date().isoformat()
    if job.get("day_started") != current_day:
        update_job(job_id, {
            "leads_today": 0,
            "day_started": current_day
        })
        return True
    return False


# ============== QUERY GENERATOR ==============

def generate_query_combinations(designations: List[str], countries: List[str], 
                                 seniorities: List[str], custom_query: str) -> List[str]:
    """Generate diverse search query combinations"""
    
    seniority_variations = {
        "Owner": ["Owner", "Business Owner", "Proprietor", "Entrepreneur"],
        "Founder": ["Founder", "Co-Founder", "Cofounder", "Founding Partner"],
        "CXO": ["CEO", "CTO", "CFO", "COO", "CMO", "CRO", "CIO", "CHRO", "CPO", "Chief Executive", "Chief Technology", "Chief Financial", "Chief Operating", "Chief Marketing"],
        "Partner": ["Partner", "Managing Partner", "General Partner", "Senior Partner"],
        "VP": ["VP", "Vice President", "SVP", "EVP", "AVP", "Senior Vice President", "Executive Vice President"],
        "Director": ["Director", "Head of", "Group Director", "Regional Director", "Managing Director", "Associate Director"],
        "Manager": ["Manager", "Team Lead", "Supervisor", "Project Manager", "Program Manager", "General Manager"],
        "Senior": ["Senior", "Sr.", "Lead", "Principal", "Staff", "Senior Associate"],
        "Entry": ["Associate", "Junior", "Entry Level", "Analyst", "Specialist", "Coordinator"],
        "Training": ["Intern", "Trainee", "Apprentice", "Graduate"],
        "Unpaid": ["Volunteer", "Board Member", "Advisory Board"]
    }
    
    industry_modifiers = [
        "", "Technology", "Software", "IT", "Finance", "Banking", "Healthcare",
        "Manufacturing", "Retail", "E-commerce", "Marketing", "Consulting",
        "Telecommunications", "Insurance", "Real Estate", "Pharmaceuticals",
        "Automotive", "Energy", "Education", "Media", "Entertainment",
        "Logistics", "Supply Chain", "FMCG", "Consumer Goods", "B2B", "SaaS"
    ]
    
    query_combinations = []
    
    for designation in (designations if designations else [""]):
        for country in (countries if countries else [""]):
            for seniority in (seniorities if seniorities else [""]):
                sen_variations = seniority_variations.get(seniority, [seniority]) if seniority else [""]
                
                for sen_var in sen_variations:
                    for industry in industry_modifiers:
                        query_parts = []
                        
                        if designation:
                            query_parts.append(f'"{designation}"')
                        if sen_var:
                            query_parts.append(f'"{sen_var}"')
                        if industry:
                            query_parts.append(industry)
                        if country:
                            query_parts.append(country)
                        if custom_query:
                            query_parts.append(custom_query)
                        
                        if query_parts:
                            query_combinations.append(" ".join(query_parts))
    
    query_combinations = list(set(query_combinations)) if query_combinations else [custom_query]
    random.shuffle(query_combinations)
    
    return query_combinations


# ============== BACKGROUND SEARCH LOOP ==============

async def run_web_search_job(job_id: str):
    """
    Background task that continuously searches until target_count is reached.
    - Rate limits to ~7 leads/min (10,000/day)
    - Auto-classifies after each batch with email prediction
    - Persists state to MongoDB for resume
    - Pauses on quota exceeded, resumes at midnight UTC
    - Respects global pause and circuit breaker
    """
    job = get_job(job_id)
    if not job:
        print(f"[WebSearch:{job_id}] Job not found")
        return
    
    # Check global control before starting
    control = get_global_search_control()
    if control.get("paused"):
        print(f"[WebSearch:{job_id}] Global search is paused: {control.get('paused_reason')}")
        update_job(job_id, {"status": JobStatus.PAUSED})
        return
    
    if control.get("circuit_breaker_open"):
        print(f"[WebSearch:{job_id}] Circuit breaker is open - too many errors")
        update_job(job_id, {"status": JobStatus.API_ERROR})
        return
    
    update_job(job_id, {
        "status": JobStatus.RUNNING,
        "started_at": datetime.utcnow()
    })
    
    config = job["config"]
    target_count = job["target_count"]
    
    # Generate queries if not already stored
    query_combinations = job.get("query_combinations", [])
    if not query_combinations:
        query_combinations = generate_query_combinations(
            config.get("designations", []),
            config.get("countries", []),
            config.get("seniorities", []),
            config.get("custom_query", "")
        )
        update_job(job_id, {"query_combinations": query_combinations})
    
    seen_urls = set(job.get("seen_urls", []))
    batch_size = 10
    query_index = 0
    
    print(f"[WebSearch:{job_id}] Starting job - Target: {target_count}, Queries: {len(query_combinations)}")
    
    while True:
        # Refresh job state
        job = get_job(job_id)
        if not job:
            break
        
        # Check if stopped
        if job["status"] == JobStatus.STOPPED:
            print(f"[WebSearch:{job_id}] Job stopped by user")
            break
        
        # Check global control flags (allows emergency stop)
        control = get_global_search_control()
        if control.get("paused"):
            print(f"[WebSearch:{job_id}] Global search paused: {control.get('paused_reason')}")
            update_job(job_id, {"status": JobStatus.PAUSED})
            break
        
        if control.get("circuit_breaker_open"):
            print(f"[WebSearch:{job_id}] Circuit breaker open - stopping due to API errors")
            update_job(job_id, {"status": JobStatus.API_ERROR})
            break
        
        # Note: No target limit - job runs indefinitely until manually stopped
        # Rate limiting controls daily usage within budget
        
        # Check and reset daily limit if new day
        check_and_reset_daily_limit(job_id)
        job = get_job(job_id)  # Refresh after potential reset
        
        # Check daily limit (dynamic from settings)
        rate_limits = get_rate_limit_settings()
        daily_limit = rate_limits["daily_limit"] if rate_limits["enabled"] else 100000
        
        if job["leads_today"] >= daily_limit:
            # Calculate time until midnight UTC
            now = datetime.utcnow()
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            wait_seconds = (tomorrow - now).total_seconds()
            
            update_job(job_id, {"status": JobStatus.QUOTA_EXCEEDED})
            print(f"[WebSearch:{job_id}] Daily limit reached ({daily_limit}). Waiting until midnight UTC ({int(wait_seconds)}s)")
            
            # Wait in chunks to allow stopping
            while wait_seconds > 0:
                job = get_job(job_id)
                if not job or job["status"] == JobStatus.STOPPED:
                    return
                await asyncio.sleep(min(60, wait_seconds))
                wait_seconds -= 60
            
            # Reset for new day
            update_job(job_id, {
                "status": JobStatus.RUNNING,
                "leads_today": 0,
                "day_started": datetime.utcnow().date().isoformat()
            })
            continue
        
        # Get next query
        if query_index >= len(query_combinations):
            query_index = 0
            random.shuffle(query_combinations)
        
        query = query_combinations[query_index]
        query_index += 1
        
        update_job(job_id, {"current_query": query[:100]})
        
        # Search with pagination
        start_index = 1
        consecutive_empty = 0
        batch_leads = []
        
        while consecutive_empty < 3 and start_index <= 100:
            job = get_job(job_id)
            if not job or job["status"] == JobStatus.STOPPED:
                return
            
            try:
                results = await search_linkedin_leads(
                    query=query,
                    num_results=batch_size,
                    start=start_index
                )
                
                if not results:
                    consecutive_empty += 1
                    start_index += batch_size
                    continue
                
                consecutive_empty = 0
                
                # Deduplicate
                for lead in results:
                    url = lead.get("linkedin_url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        batch_leads.append(lead)
                
                start_index += len(results)
                await asyncio.sleep(1)  # Small delay between pagination
                
            except Exception as e:
                error_msg = str(e)
                add_job_error(job_id, f"Search error: {error_msg}")
                print(f"[WebSearch:{job_id}] Error: {error_msg}")
                
                # Check for API credential errors (these should trip the circuit breaker)
                is_credential_error = any(x in error_msg.lower() for x in [
                    "api key", "invalid", "denied", "unauthorized", "forbidden", "aiza"
                ])
                
                if is_credential_error:
                    # Trip circuit breaker immediately for credential errors
                    circuit_tripped = increment_error_count(error_msg)
                    if circuit_tripped:
                        update_job(job_id, {"status": JobStatus.API_ERROR})
                        print(f"[WebSearch:{job_id}] API credential error - job stopped")
                        return
                elif "quota" in error_msg.lower() or "limit" in error_msg.lower():
                    update_job(job_id, {"status": JobStatus.QUOTA_EXCEEDED})
                    print(f"[WebSearch:{job_id}] API quota exceeded, waiting until midnight...")
                    
                    # Wait until midnight UTC
                    now = datetime.utcnow()
                    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    wait_seconds = (tomorrow - now).total_seconds()
                    
                    while wait_seconds > 0:
                        job = get_job(job_id)
                        if not job or job["status"] == JobStatus.STOPPED:
                            return
                        # Also check global pause during wait
                        control = get_global_search_control()
                        if control.get("paused"):
                            update_job(job_id, {"status": JobStatus.PAUSED})
                            return
                        await asyncio.sleep(min(60, wait_seconds))
                        wait_seconds -= 60
                    
                    update_job(job_id, {"status": JobStatus.RUNNING})
                else:
                    # Track consecutive errors for circuit breaker
                    increment_error_count(error_msg)
                break
        
        # Reset error count on successful batch
        if batch_leads:
            reset_error_count()
        
        # Import batch leads
        if batch_leads:
            try:
                lead_inputs = [LeadInput(**lead) for lead in batch_leads]
                result = import_leads(lead_inputs)
                
                increment_job_counters(
                    job_id,
                    found=len(batch_leads),
                    imported=result.imported,
                    duplicates=result.duplicates
                )
                
                print(f"[WebSearch:{job_id}] Query: '{query[:40]}...' - Found: {len(batch_leads)}, Imported: {result.imported}")
                
                # Save seen URLs periodically (every 100 new ones)
                if len(seen_urls) % 100 < batch_size:
                    update_job(job_id, {"seen_urls": list(seen_urls)})
                
            except Exception as e:
                add_job_error(job_id, f"Import error: {str(e)}")
        
        # Auto-classify after each batch
        try:
            success, failure = classify_pending_leads(50)
            if success > 0:
                # Count emails found (leads with predicted_email)
                from .service import leads_enriched_collection
                emails_count = leads_enriched_collection.count_documents({
                    "email": {"$ne": None, "$ne": ""},
                    "classified_at": {"$gte": datetime.utcnow() - timedelta(minutes=5)}
                })
                
                increment_job_counters(job_id, classified=success, emails=emails_count)
                print(f"[WebSearch:{job_id}] Classified: {success}, Emails found: {emails_count}")
        except Exception as e:
            add_job_error(job_id, f"Classification error: {str(e)}")
        
        # Rate limiting delay (dynamic from settings)
        delay = get_rate_limit_settings()["query_delay"]
        await asyncio.sleep(max(delay, DELAY_BETWEEN_BATCHES))
    
    # Final cleanup
    job = get_job(job_id)
    if job and job["status"] == JobStatus.RUNNING:
        update_job(job_id, {
            "status": JobStatus.COMPLETED,
            "completed_at": datetime.utcnow()
        })
    
    print(f"[WebSearch:{job_id}] Job finished")


# ============== WEB SEARCH ENDPOINT (BACKGROUND) ==============

@router.post("/import/web-search")
async def import_from_web_search(
    request: WebSearchRequest,
    background_tasks: BackgroundTasks
):
    """
    POST /leads/import/web-search
    Start background web search job that runs until target_count is reached.
    
    Features:
    - Runs in background, returns job_id immediately
    - Rate limits to ~7 leads/min (10,000/day max)
    - Auto-classifies leads with email prediction
    - Pauses on quota exceeded, auto-resumes at midnight UTC
    - Persists to MongoDB for resume on restart
    
    Use GET /leads/import/web-search/status/{job_id} to check progress.
    Use POST /leads/import/web-search/stop/{job_id} to stop.
    """
    try:
        # Check for already running job
        running_jobs = list(web_search_jobs_collection.find({
            "status": {"$in": [JobStatus.RUNNING, JobStatus.PENDING]}
        }))
        if running_jobs:
            return {
                "success": False,
                "message": "A search job is already running",
                "job_id": running_jobs[0]["job_id"],
                "status": running_jobs[0]["status"]
            }
        
        # Parse inputs
        countries = request.countries if request.countries else ([request.country] if request.country else [])
        seniorities = request.seniorities if request.seniorities else ([request.seniority] if request.seniority else [])
        designations = [d.strip() for d in request.designation.split(",")] if request.designation else []
        
        if not designations and not countries and not seniorities and not request.custom_query:
            raise ValueError("At least one search filter (designation, country, seniority, or custom_query) is required")
        
        # No target limit - job runs continuously until stopped (controlled by rate limits)
        target_count = 999999999  # Effectively unlimited
        
        # Create job config
        config = {
            "designations": designations,
            "countries": countries,
            "seniorities": seniorities,
            "custom_query": request.custom_query
        }
        
        # Create job in MongoDB
        job_id = create_job(config, target_count)
        
        # Start background task
        background_tasks.add_task(run_web_search_job, job_id)
        
        return {
            "success": True,
            "job_id": job_id,
            "message": "Search job started in continuous mode. Stop manually when done.",
            "status_url": f"/leads/import/web-search/status/{job_id}",
            "stop_url": f"/leads/import/web-search/stop/{job_id}"
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/import/web-search/status/{job_id}")
async def get_web_search_status(job_id: str):
    """
    GET /leads/import/web-search/status/{job_id}
    Get real-time status of a web search job.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Calculate progress
    progress_percent = 0
    if job["target_count"] > 0:
        progress_percent = round((job["total_imported"] / job["target_count"]) * 100, 1)
    
    # Calculate ETA
    eta_minutes = None
    if job["status"] == JobStatus.RUNNING and job["total_imported"] > 0:
        remaining = job["target_count"] - job["total_imported"]
        eta_minutes = int(remaining / LEADS_PER_MINUTE)
    
    # Get dynamic rate limits for response
    rate_limits = get_rate_limit_settings()
    
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "target_count": job["target_count"],
        "total_found": job["total_found"],
        "total_imported": job["total_imported"],
        "total_duplicates": job["total_duplicates"],
        "total_classified": job["total_classified"],
        "emails_found": job["emails_found"],
        "leads_today": job["leads_today"],
        "daily_limit": rate_limits["daily_limit"],
        "rate_limit_enabled": rate_limits["enabled"],
        "queries_used": job["queries_used"],
        "current_query": job.get("current_query", ""),
        "progress_percent": progress_percent,
        "eta_minutes": eta_minutes,
        "errors": job.get("errors", [])[-5:],
        "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
        "started_at": job["started_at"].isoformat() if job.get("started_at") else None,
        "last_update": job["last_update"].isoformat() if job.get("last_update") else None,
        "completed_at": job["completed_at"].isoformat() if job.get("completed_at") else None,
        "config": job.get("config", {})
    }


@router.post("/import/web-search/stop/{job_id}")
async def stop_web_search(job_id: str):
    """
    POST /leads/import/web-search/stop/{job_id}
    Stop a running web search job.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] not in [JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PAUSED, JobStatus.QUOTA_EXCEEDED, JobStatus.API_ERROR]:
        return {
            "success": False,
            "message": f"Job is not running (status: {job['status']})"
        }
    
    update_job(job_id, {"status": JobStatus.STOPPED})
    
    return {
        "success": True,
        "message": "Stop signal sent. Job will stop after current operation.",
        "job_id": job_id,
        "total_imported": job["total_imported"]
    }


@router.post("/import/web-search/stop-all")
async def stop_all_web_searches():
    """
    POST /leads/import/web-search/stop-all
    EMERGENCY STOP: Stop ALL running web search jobs immediately.
    Also pauses the global search system to prevent auto-resume.
    """
    stopped_count = stop_all_jobs("Emergency stop - all jobs stopped")
    
    return {
        "success": True,
        "message": f"Emergency stop executed. {stopped_count} jobs stopped.",
        "jobs_stopped": stopped_count,
        "global_search_paused": True,
        "note": "Use /leads/import/web-search/control to resume search capability"
    }


@router.get("/import/web-search/control")
async def get_search_control():
    """
    GET /leads/import/web-search/control
    Get global search control status (pause state, circuit breaker, errors).
    """
    control = get_global_search_control()
    
    # Get count of active jobs
    active_jobs = web_search_jobs_collection.count_documents({
        "status": {"$in": [JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PAUSED, JobStatus.QUOTA_EXCEEDED]}
    })
    
    return {
        "global_paused": control.get("paused", False),
        "paused_at": control.get("paused_at"),
        "paused_reason": control.get("paused_reason", ""),
        "circuit_breaker_open": control.get("circuit_breaker_open", False),
        "consecutive_errors": control.get("consecutive_errors", 0),
        "last_error": control.get("last_error"),
        "auto_resume_disabled": control.get("auto_resume_disabled", False),
        "active_jobs_count": active_jobs
    }


@router.post("/import/web-search/control/resume")
async def resume_search_control():
    """
    POST /leads/import/web-search/control/resume
    Resume global search capability (un-pause, reset circuit breaker).
    Does NOT auto-start any jobs - they must be resumed manually.
    """
    set_global_search_control({
        "paused": False,
        "paused_at": None,
        "paused_reason": "",
        "circuit_breaker_open": False,
        "consecutive_errors": 0,
    })
    
    return {
        "success": True,
        "message": "Global search resumed. Use /resume/{job_id} to restart individual jobs.",
        "global_paused": False,
        "circuit_breaker_open": False
    }


@router.post("/import/web-search/control/pause")
async def pause_search_control(reason: str = "Manual pause"):
    """
    POST /leads/import/web-search/control/pause
    Pause global search capability. Running jobs will stop at next check.
    """
    set_global_search_control({
        "paused": True,
        "paused_at": datetime.utcnow().isoformat(),
        "paused_reason": reason,
    })
    
    return {
        "success": True,
        "message": f"Global search paused: {reason}",
        "global_paused": True
    }


@router.post("/import/web-search/control/disable-auto-resume")
async def disable_auto_resume():
    """
    POST /leads/import/web-search/control/disable-auto-resume
    Disable auto-resume of jobs on server restart.
    """
    set_global_search_control({
        "auto_resume_disabled": True,
    })
    
    return {
        "success": True,
        "message": "Auto-resume on startup disabled. Jobs will not restart automatically.",
        "auto_resume_disabled": True
    }


@router.post("/import/web-search/control/enable-auto-resume")
async def enable_auto_resume():
    """
    POST /leads/import/web-search/control/enable-auto-resume  
    Enable auto-resume of jobs on server restart.
    """
    set_global_search_control({
        "auto_resume_disabled": False,
    })
    
    return {
        "success": True,
        "message": "Auto-resume on startup enabled.",
        "auto_resume_disabled": False
    }


@router.get("/import/web-search/jobs")
async def list_web_search_jobs(
    status: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100)
):
    """
    GET /leads/import/web-search/jobs
    List all web search jobs, optionally filtered by status.
    """
    try:
        query = {}
        if status:
            query["status"] = status
        
        jobs = list(web_search_jobs_collection.find(query)
                    .sort("created_at", -1)
                    .limit(limit))
        
        result = []
        for job in jobs:
            progress_percent = 0
            if job["target_count"] > 0:
                progress_percent = round((job["total_imported"] / job["target_count"]) * 100, 1)
            
            result.append({
                "job_id": job["job_id"],
                "status": job["status"],
                "target_count": job["target_count"],
                "total_imported": job["total_imported"],
                "progress_percent": progress_percent,
                "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
                "config": job.get("config", {})
            })
        
        return {"jobs": result, "count": len(result)}
    except Exception as e:
        print(f"❌ Error listing web search jobs: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to fetch jobs: {str(e)}")



@router.post("/import/web-search/resume/{job_id}")
async def resume_web_search(job_id: str, background_tasks: BackgroundTasks):
    """
    POST /leads/import/web-search/resume/{job_id}
    Resume a paused or stopped job.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] in [JobStatus.RUNNING, JobStatus.PENDING]:
        return {
            "success": False,
            "message": "Job is already running"
        }
    
    if job["status"] == JobStatus.COMPLETED:
        return {
            "success": False,
            "message": "Job is already completed"
        }
    
    # Reset status and start
    update_job(job_id, {"status": JobStatus.PENDING})
    background_tasks.add_task(run_web_search_job, job_id)
    
    return {
        "success": True,
        "message": "Job resumed",
        "job_id": job_id
    }


# ============== GOOGLE SEARCH ENDPOINT (LEGACY) ==============

@router.post("/import/google-search")
async def import_from_google_search(
    request: GoogleSearchRequest,
    background_tasks: BackgroundTasks
):
    """
    POST /leads/import/google-search
    Search LinkedIn profiles via Google Custom Search and import results.
    """
    try:
        leads = await search_linkedin_leads(
            query=request.query,
            num_results=request.num_results
        )
        
        if not leads:
            return {"imported": 0, "message": "No LinkedIn profiles found for this query"}
        
        # Convert to LeadInput format and import
        lead_inputs = [LeadInput(**lead) for lead in leads]
        result = import_leads(lead_inputs)
        
        return {
            "found": len(leads),
            "imported": result.imported,
            "duplicates": result.duplicates,
            "message": f"Found {len(leads)} leads, imported {result.imported}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== CSV UPLOAD ENDPOINT ==============

# Collection for storing CSV column mappings
csv_mappings_collection = _jobs_db['csv_column_mappings']
try:
    csv_mappings_collection.create_index("columns_hash", unique=True)
except Exception as e:
    print(f"Warning: Could not create csv mappings index: {e}")


class CSVMappingSaveRequest(BaseModel):
    """Request to save a CSV column mapping"""
    filename: Optional[str] = None
    mapping: dict
    columns: List[str]


@router.post("/import/csv/mapping")
async def save_csv_mapping(request: CSVMappingSaveRequest):
    """
    POST /leads/import/csv/mapping
    Save a CSV column mapping for future use.
    The mapping is keyed by a hash of the sorted column names.
    """
    try:
        # Create a unique key based on sorted column names
        sorted_columns = sorted([c.lower().strip() for c in request.columns])
        columns_hash = hash(tuple(sorted_columns))
        
        mapping_doc = {
            "columns_hash": str(columns_hash),
            "columns": request.columns,
            "mapping": request.mapping,
            "filename": request.filename,
            "updated_at": datetime.utcnow()
        }
        
        csv_mappings_collection.update_one(
            {"columns_hash": str(columns_hash)},
            {"$set": mapping_doc},
            upsert=True
        )
        
        return {"success": True, "message": "Mapping saved for future use"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/import/csv/mapping")
async def get_csv_mapping(columns: str = Query(..., description="Comma-separated list of CSV columns")):
    """
    GET /leads/import/csv/mapping?columns=col1,col2,col3
    Get a saved CSV column mapping based on the column names.
    Returns the best matching saved mapping.
    """
    try:
        column_list = [c.strip() for c in columns.split(",") if c.strip()]
        sorted_columns = sorted([c.lower() for c in column_list])
        columns_hash = hash(tuple(sorted_columns))
        
        # Try exact match first
        mapping = csv_mappings_collection.find_one({"columns_hash": str(columns_hash)})
        
        if mapping:
            return {
                "found": True,
                "mapping": mapping.get("mapping", {}),
                "filename": mapping.get("filename"),
                "updated_at": mapping.get("updated_at")
            }
        
        # If no exact match, try to find a partial match
        # (columns that overlap significantly)
        all_mappings = list(csv_mappings_collection.find().sort("updated_at", -1).limit(10))
        
        best_match = None
        best_score = 0
        
        for m in all_mappings:
            saved_cols = set([c.lower() for c in m.get("columns", [])])
            current_cols = set(sorted_columns)
            overlap = len(saved_cols.intersection(current_cols))
            score = overlap / max(len(saved_cols), len(current_cols), 1)
            
            if score > 0.5 and score > best_score:  # At least 50% overlap
                best_match = m
                best_score = score
        
        if best_match:
            return {
                "found": True,
                "mapping": best_match.get("mapping", {}),
                "filename": best_match.get("filename"),
                "partial_match": True,
                "match_score": best_score
            }
        
        return {"found": False, "mapping": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/csv")
async def import_from_csv(
    file: UploadFile = File(...),
    delimiter: str = Form(",")
):
    """
    POST /leads/import/csv
    Upload a CSV file containing leads.
    Expected columns: name, title, linkedin_url, snippet
    """
    try:
        # Read file content
        content = await file.read()
        csv_content = content.decode("utf-8")
        
        # Parse CSV
        leads = parse_csv_leads(csv_content, delimiter)
        
        if not leads:
            return {"imported": 0, "message": "No valid leads found in CSV"}
        
        # Convert to LeadInput and import
        lead_inputs = [LeadInput(**lead) for lead in leads]
        result = import_leads(lead_inputs)
        
        return {
            "parsed": len(leads),
            "imported": result.imported,
            "duplicates": result.duplicates,
            "errors": result.errors,
            "message": f"Parsed {len(leads)} leads from CSV, imported {result.imported}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== GOOGLE SHEETS ENDPOINT ==============

@router.post("/import/google-sheets")
async def import_from_google_sheets(request: GoogleSheetRequest):
    """
    POST /leads/import/google-sheets
    Import leads from a public Google Sheet.
    Sheet must be set to "Anyone with link can view".
    """
    try:
        leads = await import_from_google_sheet(
            spreadsheet_id=request.spreadsheet_id,
            sheet_name=request.sheet_name,
            range_notation=request.range_notation
        )
        
        if not leads:
            return {"imported": 0, "message": "No valid leads found in sheet"}
        
        # Convert to LeadInput and import
        lead_inputs = [LeadInput(**lead) for lead in leads]
        result = import_leads(lead_inputs)
        
        return {
            "parsed": len(leads),
            "imported": result.imported,
            "duplicates": result.duplicates,
            "message": f"Imported {result.imported} leads from Google Sheet"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== JSON IMPORT ENDPOINT ==============

@router.post("/import", response_model=LeadImportResponse)
async def import_leads_endpoint(request: LeadImportRequest):
    """
    POST /leads/import
    Import LinkedIn leads with idempotent behavior.
    Duplicates are detected by linkedin_url and skipped.
    """
    try:
        result = import_leads(request.leads)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== CLASSIFICATION ENDPOINTS ==============

@router.post("/classify", response_model=LeadClassifyResponse)
async def classify_leads_endpoint(
    request: LeadClassifyRequest,
    background_tasks: BackgroundTasks
):
    """
    POST /leads/classify
    Queue leads for AI classification (async).
    If lead_ids not provided, classifies all pending leads.
    If batch_size is None, classifies ALL pending leads.
    """
    if request.lead_ids:
        # Classify specific leads in background
        for lead_id in request.lead_ids:
            background_tasks.add_task(classify_single_lead, lead_id)
        return LeadClassifyResponse(
            queued=len(request.lead_ids),
            message=f"Queued {len(request.lead_ids)} leads for classification"
        )
    else:
        # Classify all pending leads in background (None means ALL)
        background_tasks.add_task(classify_pending_leads, request.batch_size)
        if request.batch_size:
            return LeadClassifyResponse(
                queued=request.batch_size,
                message=f"Queued up to {request.batch_size} pending leads for classification"
            )
        else:
            return LeadClassifyResponse(
                queued=0,  # Unknown count, will process all
                message="Queued ALL pending leads for classification"
            )


@router.post("/classify/{lead_id}")
async def classify_single_lead_endpoint(lead_id: str):
    """
    POST /leads/classify/{lead_id}
    Classify a single lead synchronously.
    """
    success, error = classify_single_lead(lead_id)
    if success:
        return {"status": "classified", "lead_id": lead_id}
    else:
        raise HTTPException(status_code=400, detail=error or "Classification failed")


# ============== GET LEADS ENDPOINT ==============

@router.get("")
async def get_leads_endpoint(
    seniority_level: Optional[SeniorityLevel] = None,
    department: Optional[Department] = None,
    persona: Optional[Persona] = None,
    company_size: Optional[CompanySize] = None,
    industry: Optional[str] = None,
    region: Optional[Region] = None,
    min_confidence: Optional[float] = None,
    lead_stage: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    """
    GET /leads
    Retrieve enriched leads with filtering and pagination.
    
    Args:
        source: Filter by source (google_search, csv_import, gmail, etc.). 
                Supports comma-separated values for multiple sources.
    """
    filters = LeadFilterParams(
        seniority_level=seniority_level,
        department=department,
        persona=persona,
        company_size=company_size,
        industry=industry,
        region=region,
        min_confidence=min_confidence,
        lead_stage=lead_stage,
        source=source,
        search=search,
        page=page,
        limit=limit
    )
    
    leads, total = get_leads(filters)
    
    return {
        "leads": leads,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }


@router.get("/raw")
async def get_raw_leads_endpoint(
    limit: int = Query(100, ge=1, le=500, description="Max leads to return"),
    skip: int = Query(0, ge=0, description="Number of leads to skip")
):
    """
    GET /leads/raw
    Get raw leads with their classification status (paginated for performance).
    """
    leads = get_raw_leads_with_status(limit=limit, skip=skip)
    return {"leads": leads, "total": len(leads)}


@router.get("/statistics")
async def get_statistics_endpoint():
    """
    GET /leads/statistics
    Get lead statistics for dashboard.
    """
    return get_lead_statistics()


# ============== CAMPAIGN ATTACHMENT ENDPOINT ==============

@router.post("/campaigns/{campaign_id}/attach")
async def attach_leads_to_campaign_endpoint(
    campaign_id: str,
    request: AttachLeadsRequest
):
    """
    POST /campaigns/{campaign_id}/attach-leads
    Attach selected leads to a campaign.
    """
    count, message = attach_leads_to_campaign(campaign_id, request.lead_ids)
    return {"attached": count, "message": message}


# ============== DELETE LEADS BY SOURCE ==============

@router.delete("/by-source/{source}")
async def delete_leads_by_source_endpoint(source: str):
    """
    DELETE /leads/by-source/{source}
    Delete all leads from a specific source (e.g., 'web_search', 'csv', 'google_search').
    """
    valid_sources = ["web_search", "google_search", "csv", "csv_import", "google_sheets", "json_import", "linkedin", "email_import"]
    
    if source not in valid_sources:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid source. Valid sources are: {', '.join(valid_sources)}"
        )
    
    try:
        result = delete_leads_by_source(source)
        return {
            "success": True,
            "source": source,
            "raw_deleted": result["raw_deleted"],
            "enriched_deleted": result["enriched_deleted"],
            "total_deleted": result["total_deleted"],
            "message": f"Deleted {result['total_deleted']} leads from source '{source}'"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/all")
async def delete_all_leads_endpoint():
    """
    DELETE /leads/all
    Delete ALL leads from both raw and enriched collections.
    Use with caution!
    """
    try:
        result = delete_all_leads()
        return {
            "success": True,
            "raw_deleted": result["raw_deleted"],
            "enriched_deleted": result["enriched_deleted"],
            "total_deleted": result["total_deleted"],
            "message": f"Deleted all {result['total_deleted']} leads"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== EMAIL/IMAP LEADS ENDPOINTS (Issue 7 - IMAP/SMTP) ==============

class EmailImportRequest(BaseModel):
    """Request model for email leads import via IMAP"""
    account_emails: Optional[List[str]] = None  # None = all accounts
    max_emails: int = 500
    since_days: int = 30
    segments: Optional[List[str]] = None  # Filter by segment


class IMAPAccountCreate(BaseModel):
    """Request model for adding IMAP account"""
    email: str
    password: str  # App password for Gmail
    display_name: str = ""
    imap_server: Optional[str] = None  # Auto-detected from email domain
    imap_port: Optional[int] = None  # Default 993 if not specified
    smtp_server: Optional[str] = None  # Auto-detected from email domain
    smtp_port: Optional[int] = None  # Default 587 if not specified
    use_ssl: bool = True
    is_default: bool = False
    skip_validation: bool = False  # Skip IMAP connection test if True


def get_mailboxes_from_stored_emails() -> List[Dict[str, Any]]:
    """
    Get mailbox accounts from stored emails in torpedo_gmail.email_metadata.
    Discovers mailboxes by analyzing sent emails (outbound direction).
    """
    pipeline = [
        {"$match": {"direction": "outbound"}},
        {"$group": {
            "_id": "$mailbox_id",
            "from_email": {"$first": "$from_email"},
            "from_name": {"$first": "$from_name"},
            "email_count": {"$sum": 1},
            "last_email": {"$max": "$timestamp"}
        }},
        {"$sort": {"email_count": -1}}
    ]
    
    results = list(email_metadata_collection.aggregate(pipeline))
    
    mailboxes = []
    for r in results:
        # Get total email count (inbound + outbound)
        total_count = email_metadata_collection.count_documents({"mailbox_id": r["_id"]})
        
        mailboxes.append({
            "email": r["from_email"],
            "display_name": r.get("from_name") or r["from_email"].split("@")[0],
            "mailbox_id": r["_id"],
            "email_count": total_count,
            "sent_count": r["email_count"],
            "last_email": r.get("last_email"),
            "source": "stored_emails"
        })
    
    return mailboxes


@router.get("/gmail/accounts")
async def get_email_accounts_endpoint():
    """
    GET /leads/gmail/accounts
    Get all available email accounts (IMAP + stored emails).
    """
    # Get IMAP accounts
    imap_accounts = get_imap_accounts()
    
    # Get mailboxes from stored emails
    stored_mailboxes = get_mailboxes_from_stored_emails()
    
    # Merge accounts, preferring IMAP if both exist
    imap_emails = {a["email"].lower() for a in imap_accounts}
    
    all_accounts = imap_accounts.copy()
    for mailbox in stored_mailboxes:
        if mailbox["email"].lower() not in imap_emails:
            all_accounts.append(mailbox)
    
    return {"accounts": all_accounts, "total": len(all_accounts)}


@router.post("/gmail/accounts")
async def add_email_account_endpoint(request: IMAPAccountCreate):
    """
    POST /leads/gmail/accounts
    Add a new IMAP email account.
    For Gmail, use an App Password (not your regular password).
    """
    result = add_imap_account(
        email_address=request.email,
        password=request.password,
        display_name=request.display_name,
        imap_server=request.imap_server,
        imap_port=request.imap_port,
        smtp_server=request.smtp_server,
        smtp_port=request.smtp_port,
        use_ssl=request.use_ssl,
        is_default=request.is_default,
        skip_validation=request.skip_validation
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result


@router.delete("/gmail/accounts/{email}")
async def remove_email_account_endpoint(email: str):
    """
    DELETE /leads/gmail/accounts/{email}
    Remove an IMAP email account.
    """
    result = remove_imap_account(email)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/gmail/accounts/{email}/test")
async def test_email_account_endpoint(email: str):
    """
    POST /leads/gmail/accounts/{email}/test
    Test IMAP connection for an account.
    """
    result = test_imap_connection(email)
    return result


@router.post("/gmail/import")
async def import_email_leads_endpoint(
    request: EmailImportRequest,
    background_tasks: BackgroundTasks
):
    """
    POST /leads/gmail/import
    Import leads from email accounts via IMAP.
    Extracts contacts from emails and categorizes by segment.
    """
    try:
        result = import_leads_from_emails(
            account_emails=request.account_emails,
            max_emails=request.max_emails,
            since_days=request.since_days,
            segments=request.segments
        )
        
        return {
            "success": result.get("success", True),
            "emails_processed": result.get("emails_processed", 0),
            "leads_imported": result.get("leads_imported", 0),
            "duplicates": result.get("duplicates", 0),
            "errors": result.get("errors"),
            "message": result.get("message", "Import completed")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== EMAIL EXTRACTION FROM MONGODB ==============

class EmailExtractRequest(BaseModel):
    """Request to extract leads from stored emails in MongoDB"""
    account_emails: Optional[List[str]] = None
    max_emails: int = 100
    segments: Optional[List[str]] = None
    enrichment_phases: Optional[dict] = None  # {basic, names, company, domain}


def extract_domain_from_email(email: str) -> Optional[str]:
    """Extract domain from email address"""
    if not email or "@" not in email:
        return None
    return email.split("@")[1].lower()


def extract_company_from_domain(domain: str) -> Optional[str]:
    """Try to extract company name from domain"""
    if not domain:
        return None
    # Remove common TLDs and clean up
    common_tlds = ['.com', '.net', '.org', '.io', '.co', '.ai', '.tech', '.dev']
    company = domain
    for tld in common_tlds:
        if company.endswith(tld):
            company = company[:-len(tld)]
            break
    # Handle subdomains
    if '.' in company:
        parts = company.split('.')
        company = parts[-1] if len(parts[-1]) > 2 else parts[0]
    # Capitalize
    return company.title() if company else None


def split_name(full_name: str) -> tuple:
    """Split full name into first and last name"""
    if not full_name:
        return None, None
    parts = full_name.strip().split()
    if len(parts) == 0:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def extract_name_from_email_header(from_header: str) -> tuple:
    """Extract name and email from 'Name <email@domain.com>' format"""
    import re
    if not from_header:
        return None, None
    
    # Pattern: "Name <email@domain.com>" or just "email@domain.com"
    match = re.match(r'^"?([^"<]+)"?\s*<?([^>]+@[^>]+)>?$', from_header.strip())
    if match:
        name = match.group(1).strip().strip('"')
        email = match.group(2).strip()
        # Clean up name - remove email if it's the same as email
        if '@' in name or name.lower() == email.lower():
            name = None
        return name, email
    
    # Just email
    if '@' in from_header:
        return None, from_header.strip()
    
    return None, None


@router.post("/emails/extract")
async def extract_leads_from_stored_emails(request: EmailExtractRequest):
    """
    DEPRECATED: Manual lead extraction is no longer needed.
    
    Leads are now automatically extracted during Gmail sync.
    See: gmail_workspace_service_vm.py -> _save_email_metadata()
    
    This endpoint now triggers a backfill for any emails that weren't
    processed by the automatic ingestion.
    """
    from .canonical_ingestion import ingest_lead, extract_lead_from_email
    
    try:
        # Build query for unprocessed emails
        query = {
            "direction": "inbound",
            "$or": [
                {"lead_extracted": {"$exists": False}},
                {"lead_extracted": False}
            ]
        }
        
        if request.account_emails:
            query["to_email"] = {"$in": [e.lower() for e in request.account_emails]}
        
        if request.segments:
            query["ai_category"] = {"$in": request.segments}
        
        # Fetch unprocessed emails
        emails = list(email_metadata_collection.find(query).limit(request.max_emails))
        
        extracted = 0
        duplicates = 0
        errors = 0
        
        for email_doc in emails:
            try:
                # Use canonical extraction
                payload = extract_lead_from_email(email_doc)
                if not payload:
                    continue
                
                # Use canonical ingestion
                result = ingest_lead(
                    payload=payload,
                    source='gmail',
                    source_detail='backfill_extraction',
                    skip_classification=False
                )
                
                if result['success']:
                    if result['action'] == 'inserted':
                        extracted += 1
                    elif result['action'] in ('skipped', 'updated'):
                        duplicates += 1
                    
                    # Mark as processed
                    email_metadata_collection.update_one(
                        {"_id": email_doc["_id"]},
                        {"$set": {"lead_extracted": True, "lead_id": result.get('lead_id')}}
                    )
                else:
                    errors += 1
                    
            except Exception as e:
                errors += 1
                continue
        
        return {
            "success": True,
            "message": "DEPRECATED: Use automatic ingestion. This endpoint backfills missed emails.",
            "emails_processed": len(emails),
            "leads_extracted": extracted,
            "duplicates": duplicates,
            "errors": errors
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail/leads")
async def get_email_leads_endpoint(
    segment: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    """
    GET /leads/gmail/leads
    Get leads extracted from emails with filtering.
    """
    skip = (page - 1) * limit
    leads = get_email_leads(
        segment=segment,
        limit=limit,
        skip=skip
    )
    
    return {
        "leads": leads,
        "total": len(leads),
        "page": page,
        "limit": limit
    }


@router.get("/gmail/segments")
async def get_email_segments_endpoint():
    """
    GET /leads/gmail/segments
    Get available segments and their lead counts.
    """
    stats = get_segment_statistics()
    segments = [
        {"id": s.value, "name": s.value.replace("_", " ").title(), "count": stats.get(s.value, 0)}
        for s in EmailSegment
    ]
    return {"segments": segments}


# ============== LEAD SCHEDULER ENDPOINTS ==============

class SchedulerConfigRequest(BaseModel):
    """Request model for scheduler configuration"""
    designations: Optional[List[str]] = None
    countries: Optional[List[str]] = None
    seniorities: Optional[List[str]] = None
    custom_query: Optional[str] = None


@router.post("/scheduler/start")
async def start_scheduler_endpoint(config: Optional[SchedulerConfigRequest] = None):
    """
    POST /leads/scheduler/start
    Start the lead ingestion scheduler.
    
    Optional body:
    {
        "designations": ["CEO", "CTO"],
        "countries": ["United States", "Canada"],
        "seniorities": ["CXO", "VP"],
        "custom_query": "technology startup"
    }
    """
    try:
        config_dict = config.model_dump() if config else None
        result = start_scheduler(config_dict)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/stop")
async def stop_scheduler_endpoint():
    """
    POST /leads/scheduler/stop
    Stop the lead ingestion scheduler.
    """
    try:
        result = stop_scheduler()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scheduler/status")
async def get_scheduler_status_endpoint():
    """
    GET /leads/scheduler/status
    Get current scheduler status including:
    - Running state
    - Leads today/this hour
    - Progress percentages
    - Error count
    """
    try:
        status = get_scheduler_status()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scheduler/logs")
async def get_scheduler_logs_endpoint(limit: int = Query(100, ge=1, le=500)):
    """
    GET /leads/scheduler/logs
    Get recent scheduler activity logs.
    """
    try:
        logs = get_scheduler_logs(limit)
        return {"logs": logs, "count": len(logs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/scheduler/config")
async def update_scheduler_config_endpoint(config: SchedulerConfigRequest):
    """
    PUT /leads/scheduler/config
    Update scheduler search configuration.
    """
    try:
        result = update_scheduler_config(config.model_dump())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== EMAIL ALIASES ENDPOINTS ==============

class AliasCreate(BaseModel):
    """Request model for adding an alias"""
    email: str
    name: Optional[str] = ""


@router.get("/gmail/accounts/{account_email}/aliases")
async def get_account_aliases(account_email: str):
    """
    GET /leads/gmail/accounts/{account_email}/aliases
    Get all aliases for an IMAP account.
    """
    account = imap_accounts_collection.find_one({"email": account_email})
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    return {"aliases": account.get("aliases", [])}


@router.post("/gmail/accounts/{account_email}/aliases")
async def add_account_alias(account_email: str, alias: AliasCreate):
    """
    POST /leads/gmail/accounts/{account_email}/aliases
    Add an alias to an IMAP account.
    """
    account = imap_accounts_collection.find_one({"email": account_email})
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    aliases = account.get("aliases", [])
    
    # Check if alias already exists
    if any(a["email"].lower() == alias.email.lower() for a in aliases):
        raise HTTPException(status_code=400, detail="Alias already exists")
    
    new_alias = {
        "email": alias.email,
        "name": alias.name or "",
        "is_primary": False,
        "added_at": datetime.utcnow().isoformat()
    }
    
    aliases.append(new_alias)
    
    imap_accounts_collection.update_one(
        {"email": account_email},
        {"$set": {"aliases": aliases}}
    )
    
    return {"success": True, "alias": new_alias, "message": "Alias added successfully"}


@router.delete("/gmail/accounts/{account_email}/aliases/{alias_email}")
async def remove_account_alias(account_email: str, alias_email: str):
    """
    DELETE /leads/gmail/accounts/{account_email}/aliases/{alias_email}
    Remove an alias from an IMAP account.
    """
    account = imap_accounts_collection.find_one({"email": account_email})
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    aliases = account.get("aliases", [])
    original_count = len(aliases)
    
    aliases = [a for a in aliases if a["email"].lower() != alias_email.lower()]
    
    if len(aliases) == original_count:
        raise HTTPException(status_code=404, detail="Alias not found")
    
    imap_accounts_collection.update_one(
        {"email": account_email},
        {"$set": {"aliases": aliases}}
    )
    
    return {"success": True, "message": "Alias removed"}


@router.post("/gmail/accounts/{account_email}/aliases/detect")
async def detect_account_aliases(account_email: str):
    """
    POST /leads/gmail/accounts/{account_email}/aliases/detect
    Auto-detect aliases by scanning sent emails.
    Returns detected aliases without adding them.
    """
    result = detect_aliases_from_sent(account_email)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/gmail/accounts/{account_email}/aliases/sync")
async def sync_account_aliases(account_email: str):
    """
    POST /leads/gmail/accounts/{account_email}/aliases/sync
    Auto-detect and add aliases from sent emails.
    Scans sent folder for unique From addresses and adds them as aliases.
    """
    result = add_detected_aliases(account_email)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ============== ENRICHED LEAD DETAIL ==============

@router.get("/{lead_id}")
async def get_lead_by_id_endpoint(lead_id: str):
    """
    GET /leads/{lead_id}
    Get a single enriched lead by ID with all details.
    """
    lead = get_enriched_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"lead": lead}


@router.put("/{lead_id}")
async def update_lead_by_id_endpoint(lead_id: str, data: dict = Body(...)):
    """
    PUT /leads/{lead_id}
    Update an enriched lead by ID. Handles stage changes for pipeline management.
    When moving to contacts (discovery_call+), automatically creates a Sales Account if needed.
    """
    from bson import ObjectId
    from database import get_client
    
    # Contact stages that trigger account creation
    CONTACT_STAGES = ["discovery_call", "presentation", "rfq_pricing", "negotiation", 
                      "won", "lost", "onboarding", "project_execution", "payment", "retention"]
    
    # Validate lead_id
    try:
        obj_id = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lead ID format")
    
    # Check if lead exists in enriched collection
    existing_lead = leads_enriched_collection.find_one({"_id": obj_id})
    if not existing_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Remove _id from update data if present
    if "_id" in data:
        del data["_id"]
    
    # Add updated timestamp
    data["updated_at"] = datetime.utcnow().isoformat()
    
    # Check if we're moving to a contact stage (create account if so)
    new_stage = data.get("stage")
    old_stage = existing_lead.get("stage")
    account_created = None
    
    if new_stage and new_stage in CONTACT_STAGES and old_stage not in CONTACT_STAGES:
        # Moving from leads to contacts - create Sales Account if company doesn't have one
        company_name = existing_lead.get("company_name")
        company_domain = existing_lead.get("company_domain")
        
        if company_name or company_domain:
            mongo_client = get_client()
            accounts_collection = mongo_client["email_automation"]["sales_accounts"]
            
            # Check if account already exists for this company
            account_query = {}
            if company_domain:
                account_query = {"$or": [
                    {"website": {"$regex": company_domain, "$options": "i"}},
                    {"company_name": {"$regex": f"^{company_name}$", "$options": "i"}} if company_name else {}
                ]}
            elif company_name:
                account_query = {"company_name": {"$regex": f"^{company_name}$", "$options": "i"}}
            
            existing_account = accounts_collection.find_one(account_query) if account_query else None
            
            if not existing_account:
                # Create new Sales Account from lead's company data
                account_data = {
                    "account_name": company_name or company_domain,
                    "company_name": company_name,
                    "industry": existing_lead.get("company_industry"),
                    "website": existing_lead.get("company_website") or (f"https://{company_domain}" if company_domain else None),
                    "address": existing_lead.get("company_headquarters"),
                    "status": "prospect",
                    "employee_count": existing_lead.get("company_employee_count"),
                    "employee_count_range": existing_lead.get("company_employee_count_range"),
                    "revenue_range": existing_lead.get("company_revenue_range"),
                    "company_type": existing_lead.get("company_type"),
                    "company_linkedin_url": existing_lead.get("company_linkedin_url"),
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "created_from_lead_id": lead_id,
                    "contact_ids": [lead_id]  # Link this contact to the account
                }
                
                result = accounts_collection.insert_one(account_data)
                account_data["_id"] = str(result.inserted_id)
                account_created = account_data
                
                # Store account_id in lead data
                data["account_id"] = str(result.inserted_id)
            else:
                # Link contact to existing account
                account_id = str(existing_account["_id"])
                data["account_id"] = account_id
                
                # Add this contact to the account's contact_ids if not already there
                if lead_id not in existing_account.get("contact_ids", []):
                    accounts_collection.update_one(
                        {"_id": existing_account["_id"]},
                        {"$addToSet": {"contact_ids": lead_id}, "$set": {"updated_at": datetime.utcnow()}}
                    )
    
    # Update the lead
    result = leads_enriched_collection.update_one(
        {"_id": obj_id},
        {"$set": data}
    )
    
    if result.modified_count > 0:
        # Fetch and return updated lead
        updated_lead = get_enriched_lead_by_id(lead_id)
        response = {"success": True, "lead": updated_lead, "message": "Lead updated successfully"}
        if account_created:
            response["account_created"] = account_created
            response["message"] = "Lead updated and Sales Account created successfully"
        return response
    else:
        return {"success": True, "lead": get_enriched_lead_by_id(lead_id), "message": "No changes made"}


@router.delete("/{lead_id}")
async def delete_lead_by_id_endpoint(lead_id: str):
    """
    DELETE /leads/{lead_id}
    Delete an enriched lead by ID.
    """
    from bson import ObjectId
    
    # Validate lead_id
    try:
        obj_id = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lead ID format")
    
    # Check if lead exists
    existing_lead = leads_enriched_collection.find_one({"_id": obj_id})
    if not existing_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Delete the lead
    result = leads_enriched_collection.delete_one({"_id": obj_id})
    
    if result.deleted_count > 0:
        return {"success": True, "message": "Lead deleted successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete lead")


@router.get("/enriched/{lead_id}")
async def get_enriched_lead_endpoint(lead_id: str):
    """
    GET /leads/enriched/{lead_id}
    Get a single enriched lead by ID with all details.
    """
    lead = get_enriched_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"lead": lead}


@router.put("/enriched/{lead_id}")
async def update_enriched_lead_endpoint(lead_id: str, data: dict = Body(...)):
    """
    PUT /leads/enriched/{lead_id}
    Update an enriched lead by ID.
    """
    from bson import ObjectId
    
    # Validate lead_id
    try:
        obj_id = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lead ID format")
    
    # Check if lead exists
    existing_lead = leads_enriched_collection.find_one({"_id": obj_id})
    if not existing_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Remove _id from update data if present
    if "_id" in data:
        del data["_id"]
    
    # Add updated timestamp
    data["updated_at"] = datetime.utcnow().isoformat()
    
    # Update the lead
    result = leads_enriched_collection.update_one(
        {"_id": obj_id},
        {"$set": data}
    )
    
    if result.modified_count > 0:
        # Fetch and return updated lead
        updated_lead = get_enriched_lead_by_id(lead_id)
        return {"success": True, "lead": updated_lead, "message": "Lead updated successfully"}
    else:
        return {"success": True, "lead": get_enriched_lead_by_id(lead_id), "message": "No changes made"}


# ============== DUPLICATE EMAIL HANDLING ==============

@router.get("/duplicates/emails")
async def get_duplicate_emails_endpoint():
    """
    GET /leads/duplicates/emails
    Find all leads with duplicate email addresses.
    """
    return find_duplicate_emails()


@router.delete("/duplicates/emails")
async def delete_duplicate_emails_endpoint():
    """
    DELETE /leads/duplicates/emails
    Delete duplicate leads, keeping only the oldest per email.
    """
    result = delete_duplicate_emails()
    return result


# ============== HEALTH CHECK ==============

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ============== AI DISCOVERY ENDPOINTS ==============
# Perplexity for company discovery → Google CSE for contact search

class DiscoverCompaniesRequest(BaseModel):
    """Request model for company discovery via Perplexity"""
    industry: str
    location: str = ""
    count: int = 20
    criteria: str = ""  # e.g., "funded startups", "enterprise"


class DiscoverContactsRequest(BaseModel):
    """Request model for finding contacts at discovered companies"""
    companies: List[Dict[str, str]]  # [{name, description}]
    designation: str  # Target job title (e.g., "CEO", "VP Sales")
    limit_per_company: int = 5


class ImportDiscoveredContactsRequest(BaseModel):
    """Request model for importing selected contacts"""
    contacts: List[Dict[str, Any]]  # Selected contacts from preview


@router.get("/discover/status")
async def get_discovery_status():
    """
    GET /leads/discover/status
    Check if Perplexity discovery is enabled and configured.
    """
    try:
        from .perplexity_client import (
            is_perplexity_enabled, get_perplexity_settings, check_rate_limit
        )
        
        enabled = is_perplexity_enabled()
        settings = get_perplexity_settings()
        rate_allowed, rate_message = check_rate_limit()
        
        return {
            "enabled": enabled,
            "configured": enabled,  # API key exists and enabled
            "settings": {
                "hourly_limit": settings.get("hourly_limit", 50),
                "daily_limit": settings.get("daily_limit", 200),
                "default_model": settings.get("default_model", "sonar"),
            },
            "rate_limit": {
                "allowed": rate_allowed,
                "message": rate_message
            }
        }
    except ImportError:
        return {
            "enabled": False,
            "configured": False,
            "error": "Perplexity client not available"
        }
    except Exception as e:
        return {
            "enabled": False,
            "configured": False,
            "error": str(e)
        }


@router.post("/discover/companies")
async def discover_companies_endpoint(request: DiscoverCompaniesRequest):
    """
    POST /leads/discover/companies
    Discover companies using Perplexity AI.
    
    Returns list of companies for user selection (checkbox selection in UI).
    Next step: User selects companies → POST /leads/discover/contacts
    """
    try:
        from .perplexity_client import (
            is_perplexity_enabled, discover_companies, check_rate_limit
        )
        
        if not is_perplexity_enabled():
            raise HTTPException(
                status_code=400, 
                detail="Perplexity discovery is not enabled. Configure API key in Settings."
            )
        
        rate_allowed, rate_message = check_rate_limit()
        if not rate_allowed:
            raise HTTPException(status_code=429, detail=rate_message)
        
        result = await discover_companies(
            industry=request.industry,
            location=request.location,
            count=request.count,
            criteria=request.criteria
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500, 
                detail=result.get("error", "Discovery failed")
            )
        
        # Parse the content to extract company list
        content = result.get("content", "")
        companies = _parse_company_list(content)
        
        return {
            "success": True,
            "companies": companies,
            "total_found": len(companies),
            "query": f"{request.criteria} {request.industry} in {request.location}".strip(),
            "from_cache": result.get("from_cache", False),
            "raw_content": content  # For debugging
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Discovery error: {str(e)}")


def _parse_company_list(content: str) -> List[Dict[str, str]]:
    """
    Parse Perplexity response to extract company list.
    Handles various formats (numbered lists, bullet points, etc.)
    """
    companies = []
    lines = content.split('\n')
    
    current_company = {}
    
    for line in lines:
        line = line.strip()
        if not line:
            if current_company:
                companies.append(current_company)
                current_company = {}
            continue
        
        # Try to extract company info from numbered/bulleted lists
        # Patterns: "1. Company Name - description" or "• Company Name: description"
        import re
        
        # Pattern: numbered or bulleted list item with company name
        match = re.match(r'^[\d\.\)\-\•\*]+\s*\**([^:\-\n]+?)(?:\**)?[\:\-\–]?\s*(.*)$', line)
        if match:
            name = match.group(1).strip().strip('*').strip()
            description = match.group(2).strip() if match.group(2) else ""
            
            if name and len(name) > 1 and len(name) < 100:
                companies.append({
                    "name": name,
                    "description": description[:200] if description else "",
                    "selected": False
                })
                continue
        
        # If line looks like a continuation/description, append to last company
        if companies and not any(c in line[:3] for c in '0123456789.•*-'):
            if len(companies[-1].get("description", "")) < 200:
                companies[-1]["description"] = (
                    companies[-1].get("description", "") + " " + line
                ).strip()[:200]
    
    # Add last company if pending
    if current_company:
        companies.append(current_company)
    
    return companies[:50]  # Limit to 50 companies


@router.post("/discover/contacts")
async def discover_contacts_endpoint(request: DiscoverContactsRequest):
    """
    POST /leads/discover/contacts
    Find contacts at selected companies using Google CSE.
    
    Search template: site:linkedin.com "{designation}" "{company_name}"
    No /in/ prefix (broader search), no designation blocklist (per user request).
    
    Returns contacts for preview (checkbox selection) before import.
    """
    try:
        from .ingestion import search_linkedin_leads_discovery
        from .search_cache import get_cached_search, cache_search_result
        
        all_contacts = []
        errors = []
        cache_hits = 0
        api_calls = 0
        
        for company in request.companies:
            company_name = company.get("name", "")
            if not company_name:
                continue
            
            # Build discovery search query - no /in/ for broader results
            # Format: site:linkedin.com "{designation}" "{company_name}"
            search_query = f'site:linkedin.com "{request.designation}" "{company_name}"'
            
            try:
                # Check cache first
                cached = get_cached_search(search_query)
                if cached:
                    cache_hits += 1
                    contacts = cached.get("results", [])
                else:
                    # Call Google CSE
                    api_calls += 1
                    contacts = await search_linkedin_leads_discovery(
                        query=search_query,
                        num_results=request.limit_per_company
                    )
                    # Cache results
                    cache_search_result(search_query, contacts)
                
                # Add company context to each contact
                for contact in contacts[:request.limit_per_company]:
                    contact["discovered_company"] = company_name
                    contact["search_query"] = search_query
                    contact["selected"] = False  # For UI checkbox
                    all_contacts.append(contact)
                    
            except Exception as e:
                errors.append(f"{company_name}: {str(e)}")
        
        return {
            "success": True,
            "contacts": all_contacts,
            "total_found": len(all_contacts),
            "companies_searched": len(request.companies),
            "cache_hits": cache_hits,
            "api_calls": api_calls,
            "errors": errors if errors else None
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contact search error: {str(e)}")


@router.post("/discover/import")
async def import_discovered_contacts_endpoint(request: ImportDiscoveredContactsRequest):
    """
    POST /leads/discover/import
    Import selected contacts from discovery preview.
    
    Converts discovered contacts to LeadRaw format and processes through
    the standard import → classify pipeline.
    """
    try:
        from .models import LeadRaw
        from .service import import_leads
        
        if not request.contacts:
            raise HTTPException(status_code=400, detail="No contacts provided")
        
        # Convert to LeadRaw format
        leads_to_import = []
        for contact in request.contacts:
            lead = LeadRaw(
                name=contact.get("name", contact.get("title", "Unknown")),
                title=contact.get("title", contact.get("snippet", "")),
                company_name=contact.get("discovered_company", contact.get("company_name", "")),
                linkedin_url=contact.get("linkedin_url", contact.get("url", "")),
                snippet=contact.get("snippet", ""),
                location=contact.get("location", ""),
                email=contact.get("email", ""),
                source="ai_discovery",
                import_batch_id=f"discovery_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            )
            leads_to_import.append(lead)
        
        # Import leads
        result = import_leads(leads_to_import, auto_classify=True)
        
        return {
            "success": True,
            "imported": result.get("imported", len(leads_to_import)),
            "duplicates": result.get("duplicates", 0),
            "classified": result.get("classified", 0),
            "batch_id": leads_to_import[0].import_batch_id if leads_to_import else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import error: {str(e)}")


# ============== TWO-PHASE COMPANY DISCOVERY ENDPOINTS ==============

class CompanyDiscoveryRequest(BaseModel):
    """Request for Phase 1: Company Discovery"""
    industries: Optional[List[str]] = None  # None = all industries
    regions: Optional[List[str]] = None  # None = all regions
    companies_per_segment: int = 50


class ContactDiscoveryRequest(BaseModel):
    """Request for Phase 2: Contact Discovery"""
    companies: List[dict]  # Companies from Phase 1
    contacts_per_company: int = 5


class FullDiscoveryRequest(BaseModel):
    """Request for full two-phase discovery"""
    industries: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    companies_per_segment: int = 50
    contacts_per_company: int = 5
    skip_cache: bool = False


@router.get("/discover/industries")
async def get_target_industries():
    """
    GET /leads/discover/industries
    Get list of target industries for company discovery.
    """
    from .ingestion import TARGET_INDUSTRIES
    return {
        "industries": TARGET_INDUSTRIES,
        "total": len(TARGET_INDUSTRIES)
    }


@router.get("/discover/regions")
async def get_target_regions():
    """
    GET /leads/discover/regions
    Get list of target regions for company discovery.
    """
    from .ingestion import TARGET_REGIONS
    return {
        "regions": TARGET_REGIONS,
        "total": len(TARGET_REGIONS)
    }


@router.post("/discover/companies")
async def discover_companies_endpoint(request: CompanyDiscoveryRequest):
    """
    POST /leads/discover/companies
    Phase 1: Discover top companies in specified industries and regions.
    
    This finds top 50 companies per industry/region segment.
    Returns companies for selection before Phase 2 (contact discovery).
    """
    try:
        from .ingestion import discover_top_companies, TARGET_INDUSTRIES, TARGET_REGIONS
        
        industries = request.industries or TARGET_INDUSTRIES
        regions = request.regions or list(TARGET_REGIONS.keys())
        
        all_companies = []
        stats = {
            "industries_searched": len(industries),
            "regions_searched": len(regions),
            "total_companies": 0,
            "research_companies": 0,
            "end_client_companies": 0,
            "errors": []
        }
        
        for industry in industries:
            for region in regions:
                try:
                    companies = await discover_top_companies(
                        industry=industry,
                        region=region,
                        num_companies=request.companies_per_segment
                    )
                    
                    # Add selection flag for UI
                    for company in companies:
                        company["selected"] = True  # Default selected
                        company["industry_segment"] = industry
                        if company.get("is_research_company"):
                            stats["research_companies"] += 1
                        else:
                            stats["end_client_companies"] += 1
                    
                    all_companies.extend(companies)
                    stats["total_companies"] += len(companies)
                    
                except Exception as e:
                    stats["errors"].append(f"{industry} - {region}: {str(e)}")
        
        return {
            "success": True,
            "companies": all_companies,
            "stats": stats,
            "message": f"Found {stats['total_companies']} companies ({stats['research_companies']} research/panel, {stats['end_client_companies']} end-clients)"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Company discovery error: {str(e)}")


@router.post("/discover/company-contacts")
async def discover_company_contacts_endpoint(request: ContactDiscoveryRequest):
    """
    POST /leads/discover/company-contacts
    Phase 2: Find decision makers in selected companies.
    
    For end-client companies: Finds Consumer Insights/Market Research buyers
    For research companies: Finds Operations/Field managers (pitch panel + scripting)
    """
    try:
        from .ingestion import find_decision_makers_in_company
        
        all_leads = []
        stats = {
            "companies_searched": 0,
            "total_contacts": 0,
            "errors": []
        }
        
        for company in request.companies:
            if not company.get("company_name"):
                continue
                
            stats["companies_searched"] += 1
            
            try:
                leads = await find_decision_makers_in_company(
                    company=company,
                    num_contacts=request.contacts_per_company
                )
                
                # Add selection flag for UI
                for lead in leads:
                    lead["selected"] = True
                
                all_leads.extend(leads)
                stats["total_contacts"] += len(leads)
                
            except Exception as e:
                stats["errors"].append(f"{company.get('company_name')}: {str(e)}")
        
        return {
            "success": True,
            "leads": all_leads,
            "stats": stats,
            "message": f"Found {stats['total_contacts']} decision makers across {stats['companies_searched']} companies"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contact discovery error: {str(e)}")


@router.post("/discover/full-discovery")
async def run_full_discovery_endpoint(request: FullDiscoveryRequest):
    """
    POST /leads/discover/full-discovery
    Run complete two-phase discovery:
    1. Find top companies per industry/region
    2. Find decision makers in each company
    
    This is the automated version that runs both phases.
    """
    try:
        from .ingestion import run_full_company_discovery
        
        leads, stats = await run_full_company_discovery(
            industries=request.industries,
            regions=request.regions,
            companies_per_segment=request.companies_per_segment,
            contacts_per_company=request.contacts_per_company,
            skip_cache=request.skip_cache
        )
        
        return {
            "success": True,
            "leads": leads,
            "total_leads": len(leads),
            "stats": stats,
            "message": f"Discovery complete: {stats.get('total_companies_found', 0)} companies, {len(leads)} decision makers"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Full discovery error: {str(e)}")


@router.post("/discover/import-leads")
async def import_discovered_leads_endpoint(request: dict):
    """
    POST /leads/discover/import-leads
    Import leads from two-phase discovery into the database.
    """
    try:
        from .models import LeadRaw
        from .service import import_leads
        
        leads_data = request.get("leads", [])
        if not leads_data:
            raise HTTPException(status_code=400, detail="No leads provided")
        
        batch_id = f"company_discovery_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        # Convert to LeadRaw format
        leads_to_import = []
        for lead in leads_data:
            lead_raw = LeadRaw(
                name=lead.get("name", ""),
                title=lead.get("title", ""),
                company_name=lead.get("company_name", ""),
                linkedin_url=lead.get("linkedin_url", ""),
                email=lead.get("email", ""),
                location=lead.get("location", ""),
                snippet=lead.get("snippet", ""),
                source="openai_company_search",
                import_batch_id=batch_id,
                # Additional enrichment fields
                seniority_level=lead.get("seniority_level", ""),
                department=lead.get("department", ""),
                buying_role=lead.get("buying_role", ""),
                company_industry=lead.get("company_industry", ""),
                company_size=lead.get("company_size", ""),
                company_domain=lead.get("company_domain", ""),
                company_linkedin_url=lead.get("company_linkedin_url", ""),
                company_headquarters=lead.get("company_headquarters", ""),
                # Service pitch context
                is_research_company=lead.get("is_research_company", False),
                service_pitch=lead.get("service_pitch", ""),
                region=lead.get("region", "")
            )
            leads_to_import.append(lead_raw)
        
        # Import leads
        result = import_leads(leads_to_import, auto_classify=True)
        
        return {
            "success": True,
            "imported": result.get("imported", len(leads_to_import)),
            "duplicates": result.get("duplicates", 0),
            "classified": result.get("classified", 0),
            "batch_id": batch_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import error: {str(e)}")


# ============== AI COMPANY DATABASE ENDPOINTS ==============

class CompanyStatus:
    """Status of a company in the AI database"""
    PENDING = "pending"      # Discovered, not yet searched for contacts
    SEARCHING = "searching"  # Currently being searched
    COMPLETED = "completed"  # Contacts found and imported
    NO_RESULTS = "no_results"  # Searched but no contacts found
    ERROR = "error"          # Search failed


@router.get("/ai-database/status")
async def get_ai_database_status():
    """
    GET /leads/ai-database/status
    Get status of the AI Company Database.
    Returns counts by status and whether refill is needed.
    """
    try:
        from .perplexity_client import is_perplexity_enabled
        
        # Count companies by status
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]
        status_counts = {doc["_id"]: doc["count"] for doc in ai_companies_collection.aggregate(pipeline)}
        
        total = sum(status_counts.values())
        pending = status_counts.get(CompanyStatus.PENDING, 0)
        completed = status_counts.get(CompanyStatus.COMPLETED, 0)
        
        # Check if refill is needed (below 100 pending companies)
        needs_refill = pending < 100
        perplexity_enabled = is_perplexity_enabled()
        
        # Get recent companies for display
        recent_companies = list(ai_companies_collection.find(
            {},
            {"_id": 0, "name": 1, "domain": 1, "industry": 1, "status": 1, "discovered_at": 1}
        ).sort("discovered_at", -1).limit(20))
        
        # Convert datetime to string for JSON serialization
        for company in recent_companies:
            if company.get("discovered_at"):
                company["discovered_at"] = company["discovered_at"].isoformat()
        
        return {
            "success": True,
            "total_companies": total,
            "by_status": {
                "pending": pending,
                "searching": status_counts.get(CompanyStatus.SEARCHING, 0),
                "completed": completed,
                "no_results": status_counts.get(CompanyStatus.NO_RESULTS, 0),
                "error": status_counts.get(CompanyStatus.ERROR, 0)
            },
            "needs_refill": needs_refill,
            "refill_threshold": 100,
            "perplexity_enabled": perplexity_enabled,
            "recent_companies": recent_companies
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "total_companies": 0,
            "needs_refill": True
        }


class RefillCompaniesRequest(BaseModel):
    """Request model for refilling the company database"""
    industry: str = "technology"
    location: str = "United States"
    count: int = 100
    criteria: str = ""


class DirectDiscoveryRequest(BaseModel):
    """Request model for direct contact discovery (Option 1 - no Google CSE)"""
    designation: str = "Manager"
    industry: str = "technology"
    location: str = "United States"
    count: int = 10
    criteria: str = ""


@router.post("/ai-database/discover-leads")
async def discover_leads_direct(request: DirectDiscoveryRequest):
    """
    POST /leads/ai-database/discover-leads
    OPTIMIZED: Direct lead discovery using Perplexity + OpenAI only.
    
    This is the recommended approach - bypasses Google CSE entirely.
    Cost: ~$0.0013/lead vs ~$0.006/lead with Google CSE
    
    Flow:
    1. Perplexity discovers contacts with LinkedIn patterns
    2. OpenAI enriches/classifies leads
    """
    try:
        from .perplexity_client import discover_contacts_direct, is_perplexity_enabled
        from .service import import_leads
        from .models import LeadRaw
        
        if not is_perplexity_enabled():
            raise HTTPException(
                status_code=400,
                detail="Perplexity API not configured. Add API key in Settings."
            )
        
        # Direct contact discovery
        result = await discover_contacts_direct(
            designation=request.designation,
            industry=request.industry,
            location=request.location,
            count=request.count,
            criteria=request.criteria
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Discovery failed")
            )
        
        contacts = result.get("contacts", [])
        
        if not contacts:
            return {
                "success": True,
                "message": "No contacts found matching criteria",
                "leads_imported": 0,
                "raw_response": result.get("content", "")[:500]
            }
        
        # Convert to leads and import with auto-classification
        leads = []
        for contact in contacts:
            linkedin_url = contact.get("linkedin_url", "")
            if linkedin_url and not linkedin_url.startswith("http"):
                linkedin_url = f"https://{linkedin_url}"
            
            lead = LeadRaw(
                name=contact.get("name", "Unknown"),
                title=contact.get("title", request.designation),
                company_name=contact.get("company", ""),
                linkedin_url=linkedin_url,
                snippet=f"AI Discovery: {request.designation} at {request.industry} companies",
                location=contact.get("location", request.location),
                email="",
                source="ai_direct_discovery",
                import_batch_id=f"direct_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            )
            leads.append(lead)
        
        # Import with auto-classification
        import_result = import_leads(leads, auto_classify=True)
        
        return {
            "success": True,
            "contacts_found": len(contacts),
            "leads_imported": import_result.get("imported", 0),
            "duplicates": import_result.get("duplicates", 0),
            "method": "perplexity_direct",
            "cost_estimate": f"${len(contacts) * 0.0013:.4f}",
            "contacts": contacts[:5]  # Return sample for UI display
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Discovery error: {str(e)}")


@router.post("/ai-database/refill")
async def refill_ai_database(request: RefillCompaniesRequest, background_tasks: BackgroundTasks):
    """
    POST /leads/ai-database/refill
    LEGACY: Discover companies for the company database.
    
    NOTE: For direct lead generation, use /ai-database/discover-leads instead.
    This endpoint is kept for backward compatibility with the company-first workflow.
    """
    try:
        from .perplexity_client import (
            is_perplexity_enabled, discover_companies, check_rate_limit
        )
        
        if not is_perplexity_enabled():
            raise HTTPException(
                status_code=400, 
                detail="Perplexity discovery is not enabled. Configure API key in Settings."
            )
        
        rate_allowed, rate_message = check_rate_limit()
        if not rate_allowed:
            raise HTTPException(status_code=429, detail=rate_message)
        
        # Check current pending count
        pending_count = ai_companies_collection.count_documents({"status": CompanyStatus.PENDING})
        
        if pending_count >= 100 and request.count <= 100:
            return {
                "success": True,
                "message": f"Database already has {pending_count} pending companies. No refill needed.",
                "added": 0
            }
        
        # Discover companies via Perplexity
        result = await discover_companies(
            industry=request.industry,
            location=request.location,
            count=request.count,
            criteria=request.criteria
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500, 
                detail=result.get("error", "Discovery failed")
            )
        
        # Parse and insert companies
        content = result.get("content", "")
        companies = _parse_company_list(content)
        
        added = 0
        duplicates = 0
        
        for company in companies:
            try:
                domain = company.get("domain", "").lower().strip()
                if not domain:
                    # Try to extract from name
                    name = company.get("name", "")
                    domain = name.lower().replace(" ", "").replace(",", "")[:30] + ".com"
                
                doc = {
                    "name": company.get("name", "Unknown"),
                    "domain": domain,
                    "industry": company.get("industry", request.industry),
                    "size": company.get("size", "Unknown"),
                    "headquarters": company.get("headquarters", request.location),
                    "description": company.get("description", ""),
                    "status": CompanyStatus.PENDING,
                    "discovered_at": datetime.utcnow(),
                    "discovery_query": f"{request.criteria} {request.industry} in {request.location}".strip(),
                    "last_searched": None,
                    "leads_found": 0
                }
                
                ai_companies_collection.insert_one(doc)
                added += 1
                
            except Exception as e:
                if "duplicate key" in str(e).lower():
                    duplicates += 1
                else:
                    print(f"Error adding company: {e}")
        
        return {
            "success": True,
            "message": f"Added {added} new companies to AI database",
            "added": added,
            "duplicates": duplicates,
            "total_parsed": len(companies),
            "query": f"{request.criteria} {request.industry} in {request.location}".strip()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Refill error: {str(e)}")


@router.get("/ai-database/companies")
async def get_ai_database_companies(
    status: Optional[str] = None,
    industry: Optional[str] = None,
    limit: int = 50,
    skip: int = 0
):
    """
    GET /leads/ai-database/companies
    Get companies from the AI database with optional filtering.
    """
    try:
        query = {}
        if status:
            query["status"] = status
        if industry:
            query["industry"] = {"$regex": industry, "$options": "i"}
        
        companies = list(ai_companies_collection.find(
            query,
            {"_id": 0}
        ).sort("discovered_at", -1).skip(skip).limit(limit))
        
        total = ai_companies_collection.count_documents(query)
        
        # Convert datetime to string for JSON serialization
        for company in companies:
            if company.get("discovered_at"):
                company["discovered_at"] = company["discovered_at"].isoformat()
            if company.get("last_searched"):
                company["last_searched"] = company["last_searched"].isoformat()
        
        return {
            "success": True,
            "companies": companies,
            "total": total,
            "limit": limit,
            "skip": skip
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-database/process-batch")
async def process_ai_database_batch(
    batch_size: int = 10,
    designation: str = "Manager",
    industry: str = "technology",
    location: str = "United States",
    background_tasks: BackgroundTasks = None
):
    """
    POST /leads/ai-database/process-batch
    OPTIMIZED: Direct contact discovery using Perplexity only (no Google CSE).
    
    New flow (2 APIs instead of 3):
    1. Perplexity discovers contacts directly with LinkedIn patterns
    2. OpenAI enriches/classifies leads
    
    Cost savings: ~76% reduction (eliminates $0.005 × 5 Google CSE calls per company)
    """
    try:
        from .perplexity_client import discover_contacts_direct, is_perplexity_enabled
        from .service import import_leads
        from .models import LeadRaw
        
        if not is_perplexity_enabled():
            raise HTTPException(
                status_code=400,
                detail="Perplexity API not configured. Add API key in Settings."
            )
        
        total_leads = 0
        processed = 0
        errors = []
        
        # Process in batches - each Perplexity call returns multiple contacts
        contacts_per_request = 10
        num_requests = max(1, batch_size // contacts_per_request)
        
        for i in range(num_requests):
            try:
                # Direct contact discovery - NO Google CSE needed
                result = await discover_contacts_direct(
                    designation=designation,
                    industry=industry,
                    location=location,
                    count=contacts_per_request,
                    criteria=""
                )
                
                if not result.get("success"):
                    errors.append(f"Request {i+1}: {result.get('error', 'Unknown error')}")
                    continue
                
                contacts = result.get("contacts", [])
                
                if contacts:
                    # Convert to LeadRaw and import with auto-classification
                    leads = []
                    for contact in contacts:
                        linkedin_url = contact.get("linkedin_url", "")
                        if linkedin_url and not linkedin_url.startswith("http"):
                            linkedin_url = f"https://{linkedin_url}"
                        
                        lead = LeadRaw(
                            name=contact.get("name", "Unknown"),
                            title=contact.get("title", designation),
                            company_name=contact.get("company", ""),
                            linkedin_url=linkedin_url,
                            snippet=f"Discovered via AI pipeline - {industry}",
                            location=contact.get("location", location),
                            email="",  # Will be enriched by OpenAI
                            source="ai_pipeline_v2",
                            import_batch_id=f"ai_direct_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{i}"
                        )
                        leads.append(lead)
                    
                    if leads:
                        import_result = import_leads(leads, auto_classify=True)
                        leads_found = import_result.get("imported", 0)
                        total_leads += leads_found
                
                processed += 1
                
            except Exception as e:
                errors.append(f"Request {i+1}: {str(e)}")
        
        return {
            "success": True,
            "processed": processed,
            "leads_found": total_leads,
            "batch_size": batch_size,
            "method": "perplexity_direct",
            "cost_per_lead": "$0.0013 (vs $0.006 with Google CSE)",
            "errors": errors if errors else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch processing error: {str(e)}")


@router.delete("/ai-database/clear")
async def clear_ai_database(status: Optional[str] = None):
    """
    DELETE /leads/ai-database/clear
    Clear companies from AI database.
    Optional: filter by status to only clear certain records.
    """
    try:
        query = {}
        if status:
            query["status"] = status
        
        result = ai_companies_collection.delete_many(query)
        
        return {
            "success": True,
            "deleted": result.deleted_count,
            "filter": status or "all"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== AI DATABASE WORKBOOKS (Clay-style) ==============

class CompanyDiscoveryRequest(BaseModel):
    """Request model for company discovery"""
    industry: str = "technology"
    location: str = "United States"
    count: int = 20


class JobDiscoveryRequest(BaseModel):
    """Request model for job discovery"""
    job_title: str = "Software Engineer"
    location: str = "United States"
    count: int = 20


class LocalBusinessDiscoveryRequest(BaseModel):
    """Request model for local business discovery"""
    business_type: str = "restaurant"
    location: str = "New York"
    count: int = 20


@router.get("/ai-database/workbooks")
async def get_workbooks():
    """
    GET /leads/ai-database/workbooks
    Get list of discovery workbooks (saved searches/results).
    """
    try:
        # Use existing companies as workbooks or create a workbooks collection
        workbooks_collection = db.get_collection("ai_workbooks")
        
        workbooks = list(workbooks_collection.find(
            {},
            {"_id": 1, "name": 1, "tags": 1, "created_at": 1, "last_opened": 1, "owner": 1, "access": 1, "is_favorite": 1, "leads_count": 1, "discovery_type": 1}
        ).sort("created_at", -1).limit(50))
        
        # Convert ObjectId to string
        for wb in workbooks:
            wb["_id"] = str(wb["_id"])
        
        return {"success": True, "workbooks": workbooks}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-database/workbooks")
async def create_workbook(request: dict = Body(...)):
    """
    POST /leads/ai-database/workbooks
    Create a new workbook.
    """
    try:
        workbooks_collection = db.get_collection("ai_workbooks")
        
        workbook = {
            "name": request.get("name", "Untitled workbook"),
            "tags": request.get("tags", []),
            "created_at": datetime.utcnow(),
            "last_opened": datetime.utcnow(),
            "owner": "You",
            "access": "Edit",
            "is_favorite": False,
            "leads_count": 0,
            "discovery_type": request.get("discovery_type", "manual")
        }
        
        result = workbooks_collection.insert_one(workbook)
        workbook["_id"] = str(result.inserted_id)
        
        return {"success": True, "workbook": workbook}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-database/discover-companies")
async def discover_companies_direct(request: CompanyDiscoveryRequest):
    """
    POST /leads/ai-database/discover-companies
    Discover companies using Perplexity AI.
    """
    try:
        from .perplexity_client import is_perplexity_enabled
        
        if not is_perplexity_enabled():
            raise HTTPException(
                status_code=400,
                detail="Perplexity API not configured. Add API key in Settings."
            )
        
        # Use existing refill logic but return companies directly
        from .perplexity_client import discover_companies
        
        result = await discover_companies(
            industry=request.industry,
            count=request.count
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Company discovery failed")
            )
        
        companies = result.get("companies", [])
        
        # Create a workbook for this discovery
        workbooks_collection = db.get_collection("ai_workbooks")
        workbook = {
            "name": f"Companies in {request.industry}",
            "tags": [request.industry, request.location],
            "created_at": datetime.utcnow(),
            "last_opened": datetime.utcnow(),
            "owner": "You",
            "access": "Edit",
            "is_favorite": False,
            "leads_count": len(companies),
            "discovery_type": "companies"
        }
        workbooks_collection.insert_one(workbook)
        
        return {
            "success": True,
            "count": len(companies),
            "companies": companies[:10],
            "cost_estimate": f"${len(companies) * 0.001:.4f}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Company discovery error: {str(e)}")


@router.post("/ai-database/discover-jobs")
async def discover_jobs(request: JobDiscoveryRequest):
    """
    POST /leads/ai-database/discover-jobs
    Discover job postings using Perplexity AI.
    """
    try:
        from .perplexity_client import is_perplexity_enabled, call_perplexity
        
        if not is_perplexity_enabled():
            raise HTTPException(
                status_code=400,
                detail="Perplexity API not configured. Add API key in Settings."
            )
        
        prompt = f"""Find {request.count} current job postings for "{request.job_title}" positions in {request.location}.

For each job, provide:
1. Job title
2. Company name
3. Location
4. Job posting URL (if available)
5. Brief description

Format as a JSON array with keys: title, company, location, url, description"""

        result = await call_perplexity(prompt, model="llama-3.1-sonar-small-128k-online")
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Job discovery failed")
            )
        
        # Create a workbook for this discovery
        workbooks_collection = db.get_collection("ai_workbooks")
        workbook = {
            "name": f"{request.job_title} Jobs - {request.location}",
            "tags": ["jobs", request.job_title, request.location],
            "created_at": datetime.utcnow(),
            "last_opened": datetime.utcnow(),
            "owner": "You",
            "access": "Edit",
            "is_favorite": False,
            "leads_count": request.count,
            "discovery_type": "jobs"
        }
        workbooks_collection.insert_one(workbook)
        
        return {
            "success": True,
            "count": request.count,
            "content": result.get("content", ""),
            "cost_estimate": f"${0.001:.4f}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Job discovery error: {str(e)}")


@router.post("/ai-database/discover-local")
async def discover_local_businesses(request: LocalBusinessDiscoveryRequest):
    """
    POST /leads/ai-database/discover-local
    Discover local businesses using Perplexity AI.
    """
    try:
        from .perplexity_client import is_perplexity_enabled, call_perplexity
        
        if not is_perplexity_enabled():
            raise HTTPException(
                status_code=400,
                detail="Perplexity API not configured. Add API key in Settings."
            )
        
        prompt = f"""Find {request.count} {request.business_type} businesses in {request.location}.

For each business, provide:
1. Business name
2. Address
3. Phone number (if available)
4. Website (if available)
5. Brief description or specialty

Format as a JSON array with keys: name, address, phone, website, description"""

        result = await call_perplexity(prompt, model="llama-3.1-sonar-small-128k-online")
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Local business discovery failed")
            )
        
        # Create a workbook for this discovery
        workbooks_collection = db.get_collection("ai_workbooks")
        workbook = {
            "name": f"{request.business_type.title()}s in {request.location}",
            "tags": ["local", request.business_type, request.location],
            "created_at": datetime.utcnow(),
            "last_opened": datetime.utcnow(),
            "owner": "You",
            "access": "Edit",
            "is_favorite": False,
            "leads_count": request.count,
            "discovery_type": "local"
        }
        workbooks_collection.insert_one(workbook)
        
        return {
            "success": True,
            "count": request.count,
            "content": result.get("content", ""),
            "cost_estimate": f"${0.001:.4f}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Local business discovery error: {str(e)}")
