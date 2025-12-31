"""
AGENT 4 — BACKEND API ENGINEER
FastAPI Router for Lead Management
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, UploadFile, File, Form
from typing import Optional, List
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
    get_lead_statistics, delete_leads_by_source, delete_all_leads
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


# ============== JOB STATUS CONSTANTS ==============

class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    QUOTA_EXCEEDED = "quota_exceeded"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


# ============== RATE LIMITING CONSTANTS ==============

# Target: 10,000 leads/day = ~7 leads/minute
DAILY_LIMIT = 10000
LEADS_PER_MINUTE = 7  # ~7 leads per minute = 420/hour = 10,080/day
DELAY_BETWEEN_BATCHES = 60 / LEADS_PER_MINUTE  # ~8.5 seconds between batches


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
    target_count: int = 10000  # Target number of leads (now 10000)
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
        
        # Check if target reached
        if job["total_imported"] >= target_count:
            update_job(job_id, {
                "status": JobStatus.COMPLETED,
                "completed_at": datetime.utcnow()
            })
            print(f"[WebSearch:{job_id}] Target reached! Imported {job['total_imported']} leads")
            break
        
        # Check and reset daily limit if new day
        check_and_reset_daily_limit(job_id)
        job = get_job(job_id)  # Refresh after potential reset
        
        # Check daily limit
        if job["leads_today"] >= DAILY_LIMIT:
            # Calculate time until midnight UTC
            now = datetime.utcnow()
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            wait_seconds = (tomorrow - now).total_seconds()
            
            update_job(job_id, {"status": JobStatus.QUOTA_EXCEEDED})
            print(f"[WebSearch:{job_id}] Daily limit reached ({DAILY_LIMIT}). Waiting until midnight UTC ({int(wait_seconds)}s)")
            
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
        
        # Rate limiting delay
        await asyncio.sleep(DELAY_BETWEEN_BATCHES)
    
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
        
        target_count = min(request.target_count, 50000)
        
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
            "message": f"Search job started. Target: {target_count} leads",
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
        "daily_limit": DAILY_LIMIT,
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


# ============== HEALTH CHECK ==============

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
