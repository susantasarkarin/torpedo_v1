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
web_search_jobs_collection = _jobs_db['web_search_jobs']

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


# ============== RATE LIMITING (DYNAMIC FROM SETTINGS) ==============

# MongoDB connection for settings
_settings_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_settings_db = _settings_client['torpedo_settings']
_app_settings_collection = _settings_db['app_settings']

def get_rate_limit_settings() -> dict:
    """Get rate limiting settings from MongoDB (for $50/month budget control)"""
    try:
        settings = _app_settings_collection.find_one({"_id": "app_config"})
        if settings:
            return {
                "daily_limit": settings.get("google_cse_daily_limit", 400),
                "hourly_limit": settings.get("google_cse_hourly_limit", 50),
                "query_delay": settings.get("google_cse_query_delay", 3),
                "monthly_budget": settings.get("google_cse_monthly_budget", 50.0),
                "enabled": settings.get("google_cse_rate_limit_enabled", True),
            }
    except Exception as e:
        print(f"Error loading rate limits: {e}")
    # Default conservative limits for $50/month budget
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
    """
    job = get_job(job_id)
    if not job:
        print(f"[WebSearch:{job_id}] Job not found")
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
                
                if "quota" in error_msg.lower() or "limit" in error_msg.lower():
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
                        await asyncio.sleep(min(60, wait_seconds))
                        wait_seconds -= 60
                    
                    update_job(job_id, {"status": JobStatus.RUNNING})
                break
        
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
    
    if job["status"] not in [JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PAUSED, JobStatus.QUOTA_EXCEEDED]:
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


@router.get("/import/web-search/jobs")
async def list_web_search_jobs(
    status: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100)
):
    """
    GET /leads/import/web-search/jobs
    List all web search jobs, optionally filtered by status.
    """
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
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    """
    GET /leads
    Retrieve enriched leads with filtering and pagination.
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


@router.get("/gmail/accounts")
async def get_email_accounts_endpoint():
    """
    GET /leads/gmail/accounts
    Get all configured IMAP email accounts.
    """
    accounts = get_imap_accounts()
    return {"accounts": accounts, "total": len(accounts)}


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
    POST /leads/emails/extract
    Extract leads from emails already stored in MongoDB.
    Performs phased enrichment:
    - Basic: Email, Full Name
    - Names: First Name, Last Name (split from full name)
    - Company: Company name from signature/domain
    - Domain: Domain extracted from email
    """
    try:
        # Get emails collection
        emails_collection = _jobs_db['emails']
        leads_collection = _jobs_db['leads_raw']
        
        # Build query
        query = {}
        if request.account_emails:
            query["$or"] = [
                {"mailbox_email": {"$in": request.account_emails}},
                {"account_email": {"$in": request.account_emails}}
            ]
        if request.segments:
            query["category"] = {"$in": request.segments}
        
        # Only get inbound emails (from external contacts)
        query["direction"] = "inbound"
        
        # Fetch emails
        emails = list(emails_collection.find(query).limit(request.max_emails))
        
        phases = request.enrichment_phases or {
            "basic": True,
            "names": True,
            "company": True,
            "domain": True
        }
        
        extracted = 0
        enriched = 0
        duplicates = 0
        
        for email_doc in emails:
            try:
                # Get from address
                from_addr = email_doc.get("from_address") or email_doc.get("from") or {}
                if isinstance(from_addr, dict):
                    email_addr = from_addr.get("email", "")
                    name = from_addr.get("name", "")
                elif isinstance(from_addr, str):
                    name, email_addr = extract_name_from_email_header(from_addr)
                else:
                    continue
                
                if not email_addr or "@" not in email_addr:
                    continue
                
                # Skip internal emails (same domain as account)
                account_email = email_doc.get("mailbox_email", "")
                if account_email:
                    account_domain = extract_domain_from_email(account_email)
                    sender_domain = extract_domain_from_email(email_addr)
                    if account_domain and sender_domain and account_domain == sender_domain:
                        continue
                
                # Check for duplicate
                existing = leads_collection.find_one({"email": email_addr.lower()})
                if existing:
                    duplicates += 1
                    continue
                
                # Build lead document with phased enrichment
                lead_doc = {
                    "email": email_addr.lower(),
                    "source": "email_extraction",
                    "created_at": datetime.utcnow(),
                    "source_email_id": str(email_doc.get("_id", "")),
                    "segment": email_doc.get("category"),
                }
                
                # Phase 1: Basic info
                if phases.get("basic", True):
                    lead_doc["name"] = name if name else None
                    extracted += 1
                
                # Phase 2: Split names
                if phases.get("names", True) and name:
                    first_name, last_name = split_name(name)
                    lead_doc["first_name"] = first_name
                    lead_doc["last_name"] = last_name
                
                # Phase 3: Domain
                if phases.get("domain", True):
                    domain = extract_domain_from_email(email_addr)
                    lead_doc["company_domain"] = domain
                
                # Phase 4: Company (from domain or signature)
                if phases.get("company", True):
                    domain = lead_doc.get("company_domain") or extract_domain_from_email(email_addr)
                    company = extract_company_from_domain(domain)
                    lead_doc["company_name"] = company
                    
                    # Try to extract from email body signature (basic extraction)
                    body = email_doc.get("body_plain", "") or email_doc.get("body", "")
                    if body and not company:
                        # Simple signature detection - look for company patterns
                        import re
                        lines = body.split('\n')[-20:]  # Last 20 lines
                        for line in lines:
                            # Look for patterns like "Company Name" or "| Company"
                            company_match = re.search(r'(?:^|\|)\s*([A-Z][A-Za-z0-9\s&]+(?:Inc|LLC|Ltd|Corp|Co)\.?)\s*(?:\||$)', line)
                            if company_match:
                                lead_doc["company_name"] = company_match.group(1).strip()
                                break
                
                enriched += 1
                
                # Insert lead
                leads_collection.insert_one(lead_doc)
                
            except Exception as e:
                print(f"Error processing email: {e}")
                continue
        
        return {
            "success": True,
            "emails_processed": len(emails),
            "leads_extracted": extracted,
            "leads_enriched": enriched,
            "duplicates": duplicates,
            "message": f"Extracted {extracted} leads from {len(emails)} emails"
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


@router.post("/ai-database/refill")
async def refill_ai_database(request: RefillCompaniesRequest, background_tasks: BackgroundTasks):
    """
    POST /leads/ai-database/refill
    Trigger Perplexity to discover new companies and add to database.
    Only triggers if count drops below threshold (100).
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
    background_tasks: BackgroundTasks = None
):
    """
    POST /leads/ai-database/process-batch
    Process a batch of pending companies:
    1. Pick N pending companies
    2. Search Google CSE for leads at each company
    3. Enrich with OpenAI
    4. Update company status
    
    This is the automated pipeline: Perplexity → Google CSE → OpenAI
    """
    try:
        from .ingestion import search_linkedin_leads
        from .service import import_leads
        
        # Get pending companies
        pending = list(ai_companies_collection.find(
            {"status": CompanyStatus.PENDING}
        ).limit(batch_size))
        
        if not pending:
            return {
                "success": True,
                "message": "No pending companies to process",
                "processed": 0,
                "leads_found": 0
            }
        
        total_leads = 0
        processed = 0
        errors = []
        
        for company in pending:
            company_name = company.get("name", "")
            domain = company.get("domain", "")
            
            try:
                # Mark as searching
                ai_companies_collection.update_one(
                    {"domain": domain},
                    {"$set": {"status": CompanyStatus.SEARCHING, "last_searched": datetime.utcnow()}}
                )
                
                # Search for leads using Google CSE
                search_results = search_linkedin_leads(
                    designation=designation,
                    company=company_name,
                    location="",  # Use company headquarters if needed
                    count=5  # Limit per company
                )
                
                if search_results and len(search_results) > 0:
                    # Import leads with auto-classification
                    from .models import LeadRaw
                    
                    leads = []
                    for result in search_results:
                        lead = LeadRaw(
                            name=result.get("name", result.get("title", "Unknown")),
                            title=result.get("title", result.get("snippet", "")),
                            company_name=company_name,
                            linkedin_url=result.get("linkedin_url", result.get("url", "")),
                            snippet=result.get("snippet", ""),
                            location=result.get("location", ""),
                            email=result.get("email", ""),
                            source="ai_pipeline",
                            import_batch_id=f"ai_batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
                        )
                        leads.append(lead)
                    
                    if leads:
                        import_result = import_leads(leads, auto_classify=True)
                        leads_found = import_result.get("imported", 0)
                        total_leads += leads_found
                        
                        # Update company status
                        ai_companies_collection.update_one(
                            {"domain": domain},
                            {"$set": {
                                "status": CompanyStatus.COMPLETED,
                                "leads_found": leads_found
                            }}
                        )
                    else:
                        ai_companies_collection.update_one(
                            {"domain": domain},
                            {"$set": {"status": CompanyStatus.NO_RESULTS}}
                        )
                else:
                    ai_companies_collection.update_one(
                        {"domain": domain},
                        {"$set": {"status": CompanyStatus.NO_RESULTS}}
                    )
                
                processed += 1
                
            except Exception as e:
                errors.append(f"{company_name}: {str(e)}")
                ai_companies_collection.update_one(
                    {"domain": domain},
                    {"$set": {"status": CompanyStatus.ERROR, "error": str(e)}}
                )
        
        return {
            "success": True,
            "processed": processed,
            "leads_found": total_leads,
            "batch_size": batch_size,
            "errors": errors if errors else None
        }
        
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
