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
    """Get rate limiting settings from app_settings with safe fallbacks."""
    defaults = {
        "daily_limit": 400,
        "hourly_limit": 50,
        "query_delay": 3,
        "monthly_budget": 50.0,
        "enabled": True,
    }

    def _as_int(value, fallback):
        try:
            return int(value)
        except Exception:
            return fallback

    def _as_float(value, fallback):
        try:
            return float(value)
        except Exception:
            return fallback

    def _as_bool(value, fallback):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if value is None:
            return fallback
        return bool(value)

    # Priority:
    # 1) app_settings/_id=web_search_rate_limits (if present)
    # 2) app_settings/_id=app_config Google CSE keys
    # 3) env vars
    # 4) defaults
    try:
        doc = _app_settings_collection.find_one({"_id": "web_search_rate_limits"}) or {}
        app_cfg = _app_settings_collection.find_one({"_id": "app_config"}) or {}

        daily = (
            doc.get("daily_limit")
            if doc.get("daily_limit") is not None
            else app_cfg.get("google_cse_daily_limit", os.getenv("GOOGLE_CSE_DAILY_LIMIT", defaults["daily_limit"]))
        )
        hourly = (
            doc.get("hourly_limit")
            if doc.get("hourly_limit") is not None
            else app_cfg.get("google_cse_hourly_limit", os.getenv("GOOGLE_CSE_HOURLY_LIMIT", defaults["hourly_limit"]))
        )
        query_delay = (
            doc.get("query_delay")
            if doc.get("query_delay") is not None
            else app_cfg.get("google_cse_query_delay", os.getenv("GOOGLE_CSE_QUERY_DELAY", defaults["query_delay"]))
        )
        monthly_budget = (
            doc.get("monthly_budget")
            if doc.get("monthly_budget") is not None
            else app_cfg.get("google_cse_monthly_budget", os.getenv("GOOGLE_CSE_MONTHLY_BUDGET", defaults["monthly_budget"]))
        )
        enabled = (
            doc.get("enabled")
            if doc.get("enabled") is not None
            else app_cfg.get("google_cse_rate_limit_enabled", os.getenv("GOOGLE_CSE_RATE_LIMIT_ENABLED", defaults["enabled"]))
        )

        return {
            "daily_limit": max(1, _as_int(daily, defaults["daily_limit"])),
            "hourly_limit": max(1, _as_int(hourly, defaults["hourly_limit"])),
            "query_delay": max(1, _as_int(query_delay, defaults["query_delay"])),
            "monthly_budget": max(0.0, _as_float(monthly_budget, defaults["monthly_budget"])),
            "enabled": _as_bool(enabled, defaults["enabled"]),
        }
    except Exception:
        return defaults

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
    industries: List[str] = []  # Industry/vertical filters (e.g., "SaaS", "fintech")
    custom_query: str = ""  # Additional search terms
    icp_id: Optional[str] = None  # ICP slug to tag imported leads (e.g. 'bimwave')
    # Note: No target_count - job runs indefinitely until stopped, controlled by rate limits
    # Legacy single-value fields for backward compatibility
    country: str = ""
    seniority: str = ""
    industry: str = ""  # Single industry for backward compatibility


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
                                 seniorities: List[str], custom_query: str,
                                 industries: List[str] = None) -> List[str]:
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
    
    # Use user-provided industries, or default to common ones for broader search
    default_industry_modifiers = [
        "", "Technology", "Software", "IT", "Finance", "Banking", "Healthcare",
        "Manufacturing", "Retail", "E-commerce", "Marketing", "Consulting",
        "Telecommunications", "Insurance", "Real Estate", "Pharmaceuticals",
        "Automotive", "Energy", "Education", "Media", "Entertainment",
        "Logistics", "Supply Chain", "FMCG", "Consumer Goods", "B2B", "SaaS"
    ]
    
    # If user specified industries, use those (with empty string for flexibility)
    industry_modifiers = [""] + industries if industries else default_industry_modifiers

    # Country-specific LinkedIn subdomains to surface profiles not indexed on www
    # These reach regional LinkedIn caches that Google may surface differently
    COUNTRY_SITE_PREFIXES = {
        "India": "in.linkedin.com/in/",
        "United Kingdom": "uk.linkedin.com/in/",
        "Australia": "au.linkedin.com/in/",
        "Canada": "ca.linkedin.com/in/",
        "Germany": "de.linkedin.com/in/",
        "France": "fr.linkedin.com/in/",
        "Singapore": "sg.linkedin.com/in/",
        "UAE": "ae.linkedin.com/in/",
        "South Africa": "za.linkedin.com/in/",
    }

    # SFW / consumer-insights anchor terms that produce domain-specific results
    SFW_ANCHOR_TERMS = [
        "market research", "consumer insights", "survey research",
        "quantitative research", "qualitative research", "panel research",
        "insights manager", "research manager", "data collection",
        "fieldwork", "CAPI CATI", "online surveys",
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

                    # Extra pass: use country-specific LinkedIn subdomain site: operator
                    site_prefix = COUNTRY_SITE_PREFIXES.get(country)
                    if site_prefix and designation:
                        for anchor in SFW_ANCHOR_TERMS[:4]:  # top 4 anchors to avoid explosion
                            q_parts = [f'"{designation}"', anchor]
                            if sen_var:
                                q_parts.append(f'"{sen_var}"')
                            q_parts.append(f"site:{site_prefix}")
                            query_combinations.append(" ".join(q_parts))

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
    icp_id = config.get("icp_id")  # ICP slug for tagging imported leads
    
    # Generate queries if not already stored
    query_combinations = job.get("query_combinations", [])
    if not query_combinations:
        query_combinations = generate_query_combinations(
            config.get("designations", []),
            config.get("countries", []),
            config.get("seniorities", []),
            config.get("custom_query", ""),
            config.get("industries", [])
        )
        update_job(job_id, {"query_combinations": query_combinations})
    
    seen_urls = set(job.get("seen_urls", []))
    batch_size = 10
    query_index = 0
    # Track queries that consistently return 0 new leads (all duplicates)
    # key=query, value=consecutive all-dupe count; reset when new leads found
    exhausted_queries: dict = {}
    EXHAUSTED_THRESHOLD = 3  # skip a query after this many all-dupe runs

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
        
        # Get next query — skip exhausted ones
        if query_index >= len(query_combinations):
            query_index = 0
            random.shuffle(query_combinations)
            # Reset exhausted state at the start of each full cycle
            exhausted_queries.clear()
        
        query = query_combinations[query_index]
        query_index += 1

        # Skip queries that consistently return only duplicates this cycle
        if exhausted_queries.get(query, 0) >= EXHAUSTED_THRESHOLD:
            print(f"[WebSearch:{job_id}] Skipping exhausted query: '{query[:60]}'")
            await asyncio.sleep(0.2)
            continue
        
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
                    start=start_index,
                    skip_cache=True,   # Always fetch fresh results; cached ones are already imported
                    deduplicate=False  # Dedup handled by ingest_lead; skip_cache makes cache useless here
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
                result = import_leads(lead_inputs, icp_segment=icp_id)
                
                increment_job_counters(
                    job_id,
                    found=len(batch_leads),
                    imported=result.imported,
                    duplicates=result.duplicates
                )
                
                print(f"[WebSearch:{job_id}] Query: '{query[:40]}...' - Found: {len(batch_leads)}, Imported: {result.imported}")
                
                # Track queries that yield no new leads
                if result.imported == 0:
                    exhausted_queries[query] = exhausted_queries.get(query, 0) + 1
                    if exhausted_queries[query] >= EXHAUSTED_THRESHOLD:
                        print(f"[WebSearch:{job_id}] Query marked exhausted (all dupes): '{query[:60]}'")
                else:
                    exhausted_queries.pop(query, None)  # Reset on any new import

                # Save seen URLs periodically (every 100 new ones)
                if len(seen_urls) % 100 < batch_size:
                    update_job(job_id, {"seen_urls": list(seen_urls)})
                
            except Exception as e:
                add_job_error(job_id, f"Import error: {str(e)}")
        else:
            # batch_leads empty → CSE returned nothing new → mark query as exhausted faster
            exhausted_queries[query] = exhausted_queries.get(query, 0) + 1
        
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
        # Starting a fresh job should clear stale global pause/circuit flags.
        control = get_global_search_control()
        if (
            control.get("paused")
            or control.get("circuit_breaker_open")
            or control.get("consecutive_errors", 0) > 0
        ):
            set_global_search_control({
                "paused": False,
                "paused_at": None,
                "paused_reason": "",
                "circuit_breaker_open": False,
                "consecutive_errors": 0,
            })

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
        industries = request.industries if request.industries else ([request.industry] if request.industry else [])
        
        if not designations and not countries and not seniorities and not request.custom_query and not industries:
            raise ValueError("At least one search filter (designation, country, seniority, industry, or custom_query) is required")
        
        # No target limit - job runs continuously until stopped (controlled by rate limits)
        target_count = 999999999  # Effectively unlimited
        
        # Create job config
        config = {
            "designations": designations,
            "countries": countries,
            "seniorities": seniorities,
            "industries": industries,
            "custom_query": request.custom_query,
            "icp_id": request.icp_id or None,
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
            target_count = job.get("target_count", 0) or 0
            total_imported = job.get("total_imported", 0) or 0
            progress_percent = 0
            if target_count > 0:
                progress_percent = round((total_imported / target_count) * 100, 1)
            
            result.append({
                "job_id": job.get("job_id"),
                "status": job.get("status", "unknown"),
                "target_count": target_count,
                "total_imported": total_imported,
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
        max_upload_bytes = 500 * 1024 * 1024
        if len(content) > max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail="CSV file is too large. Max allowed size is 500MB."
            )
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
    fit_tier: Optional[int] = None,
    basket: Optional[str] = None,
    bounce_recovery_status: Optional[str] = None,
    qualified_only: bool = Query(False, description="If true, show only Gmail contacts + outreach-replied leads"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    """
    GET /leads
    Retrieve enriched leads with filtering and pagination.
    
    Args:
        source: Filter by source (google_search, csv_import, gmail, etc.). 
                Supports comma-separated values for multiple sources.
        qualified_only: When true, restrict results to Gmail contacts and
                        outreach-replied leads (used by the Sales Leads page).
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
        fit_tier=fit_tier,
        basket=basket,
        bounce_recovery_status=bounce_recovery_status,
        qualified_only=qualified_only,
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


@router.post("/bulk-classify")
async def bulk_classify_leads_endpoint(background_tasks: BackgroundTasks):
    """
    POST /leads/bulk-classify
    1. Auto-sync any leads_raw docs missing from leads_enriched.
    2. Apply rule-based ICP basket classification to ALL leads in leads_enriched.
    Runs in background so the HTTP response returns immediately.
    """
    from .canonical_ingestion import compute_icp_basket, sync_to_enriched

    GMAIL_SOURCES = [
        "gmail", "gmail_workspace", "email_sync", "email_import",
        "email_classification", "gmail_api", "gmail_archive", "classified_gmail",
    ]

    FIELDS = {
        "_id": 1, "title": 1, "department": 1, "seniority_level": 1,
        "buying_role": 1, "persona": 1, "company_industry": 1, "industry": 1,
        "icp_segment": 1, "company_employee_count_range": 1, "company_size": 1,
        "company_revenue_range": 1, "location": 1, "company_headquarters": 1,
        "email_status": 1, "confidence_score": 1, "intent_score": 1,
        "company": 1, "company_name": 1, "source": 1,
    }

    raw_col = _jobs_db["leads_raw"]
    raw_total = raw_col.count_documents({})
    enriched_total = leads_enriched_collection.count_documents({})

    def _run_classification():
        import logging
        _log = logging.getLogger("leads.bulk_classify")

        # ── Phase 0: sync leads_raw → leads_enriched for any missing docs ──
        synced = 0
        existing_emails = set()
        existing_linkedin = set()

        # Gather existing dedup keys from leads_enriched
        for doc in leads_enriched_collection.find({}, {"email": 1, "linkedin_url": 1}):
            if doc.get("email"):
                existing_emails.add(doc["email"].lower().strip())
            if doc.get("linkedin_url"):
                existing_linkedin.add(doc["linkedin_url"].strip())

        # Iterate leads_raw and sync any not already in leads_enriched
        skip_raw = 0
        batch_size = 500
        while True:
            raw_batch = list(raw_col.find({}).skip(skip_raw).limit(batch_size))
            if not raw_batch:
                break
            for raw_doc in raw_batch:
                raw_email = (raw_doc.get("email") or "").lower().strip()
                raw_linkedin = (raw_doc.get("linkedin_url") or "").strip()
                if raw_email and raw_email in existing_emails:
                    continue
                if not raw_email and raw_linkedin and raw_linkedin in existing_linkedin:
                    continue
                # Sync this lead
                result = sync_to_enriched(raw_doc, str(raw_doc["_id"]))
                if result:
                    synced += 1
                    if raw_email:
                        existing_emails.add(raw_email)
                    if raw_linkedin:
                        existing_linkedin.add(raw_linkedin)
            skip_raw += batch_size

        _log.info(f"Bulk-classify: synced {synced} new leads from leads_raw → leads_enriched")

        # ── Phase 1: classify all leads_enriched ───────────────────────────
        skip = 0
        classified = 0
        while True:
            batch = list(leads_enriched_collection.find({}, FIELDS).skip(skip).limit(batch_size))
            if not batch:
                break
            for doc in batch:
                basket_fields = compute_icp_basket(doc)
                update_data = {**basket_fields}
                if doc.get("source") in GMAIL_SOURCES:
                    update_data["stage"] = "already_contacted"
                leads_enriched_collection.update_one({"_id": doc["_id"]}, {"$set": update_data})
                classified += 1
            skip += batch_size

        # Stamp stage on gmail leads missing stage field
        leads_enriched_collection.update_many(
            {"source": {"$in": GMAIL_SOURCES}, "stage": {"$exists": False}},
            {"$set": {"stage": "already_contacted"}}
        )
        _log.info(f"Bulk-classify: classified {classified} leads, synced {synced} new from raw")

    background_tasks.add_task(_run_classification)

    return {
        "queued": raw_total + enriched_total,
        "synced_from_raw": max(0, raw_total - enriched_total),
        "message": f"ICP classification started in background — syncing {raw_total} raw + classifying all enriched leads",
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
    # Route-order safeguard: allow static /leads/icps endpoint to work
    # even if this dynamic route is matched first.
    if lead_id == "icps":
        return await list_icps(active_only=False)

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


@router.post("/{lead_id}/move-to-contacts")
async def move_lead_to_contacts_endpoint(lead_id: str, payload: dict = Body(None)):
    """
    POST /leads/{lead_id}/move-to-contacts
    Moves an enriched lead into the Contacts pipeline by setting its stage.
    Also creates/links a Sales Account when transitioning into contact stages.
    """
    import re
    from bson import ObjectId
    from database import get_client

    CONTACT_STAGES = ["discovery_call", "presentation", "rfq_pricing", "negotiation",
                      "won", "lost", "onboarding", "project_execution", "payment", "retention"]

    # Validate lead_id
    try:
        obj_id = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lead ID format")

    stage = (payload or {}).get("stage") or "discovery_call"

    existing_lead = leads_enriched_collection.find_one({"_id": obj_id})
    if not existing_lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    old_stage = existing_lead.get("stage")
    account_created = None
    update_data = {
        "stage": stage,
        "updated_at": datetime.utcnow().isoformat(),
    }

    if stage in CONTACT_STAGES and old_stage not in CONTACT_STAGES:
        company_name = existing_lead.get("company_name") or existing_lead.get("companyName")
        company_domain = existing_lead.get("company_domain") or existing_lead.get("companyDomain")

        if company_name or company_domain:
            mongo_client = get_client()
            accounts_collection = mongo_client["email_automation"]["sales_accounts"]

            account_conditions = []
            if company_domain:
                account_conditions.append({"website": {"$regex": re.escape(company_domain), "$options": "i"}})
            if company_name:
                account_conditions.append({"company_name": {"$regex": f"^{re.escape(company_name)}$", "$options": "i"}})

            if len(account_conditions) == 1:
                account_query = account_conditions[0]
            elif len(account_conditions) > 1:
                account_query = {"$or": account_conditions}
            else:
                account_query = None

            existing_account = accounts_collection.find_one(account_query) if account_query else None

            if not existing_account:
                account_data = {
                    "account_name": company_name or company_domain,
                    "company_name": company_name,
                    "industry": existing_lead.get("company_industry") or existing_lead.get("companyIndustry"),
                    "website": existing_lead.get("company_website") or existing_lead.get("companyWebsite") or (f"https://{company_domain}" if company_domain else None),
                    "address": existing_lead.get("company_headquarters") or existing_lead.get("companyHeadquarters"),
                    "status": "prospect",
                    "employee_count": existing_lead.get("company_employee_count") or existing_lead.get("companyEmployeeCount"),
                    "employee_count_range": existing_lead.get("company_employee_count_range") or existing_lead.get("companyEmployeeCountRange"),
                    "revenue_range": existing_lead.get("company_revenue_range") or existing_lead.get("companyRevenueRange"),
                    "company_type": existing_lead.get("company_type") or existing_lead.get("companyType"),
                    "company_linkedin_url": existing_lead.get("company_linkedin_url") or existing_lead.get("companyLinkedinUrl"),
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "created_from_lead_id": lead_id,
                    "contact_ids": [lead_id],
                }
                result = accounts_collection.insert_one(account_data)
                account_data["_id"] = str(result.inserted_id)
                account_created = account_data
                update_data["account_id"] = str(result.inserted_id)
            else:
                account_id = str(existing_account["_id"])
                update_data["account_id"] = account_id
                if lead_id not in existing_account.get("contact_ids", []):
                    accounts_collection.update_one(
                        {"_id": existing_account["_id"]},
                        {"$addToSet": {"contact_ids": lead_id}, "$set": {"updated_at": datetime.utcnow()}},
                    )

    leads_enriched_collection.update_one({"_id": obj_id}, {"$set": update_data})
    updated = get_enriched_lead_by_id(lead_id)
    response = {"success": True, "lead": updated, "message": "Lead moved to Contacts successfully"}
    if account_created:
        response["account_created"] = account_created
        response["message"] = "Lead moved to Contacts and Sales Account created successfully"
    return response


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
    Check if Google CSE discovery is enabled and configured.
    """
    try:
        from .ingestion_vm import get_google_api_credentials
        from .google_rate_limit import get_usage_stats, can_make_query
        
        api_key, cse_id = get_google_api_credentials()
        configured = bool(api_key and cse_id)
        
        # Get rate limit status
        usage_stats = get_usage_stats()
        rate_allowed, rate_message = can_make_query()
        
        return {
            "enabled": configured,
            "configured": configured,
            "provider": "google_cse",
            "settings": {
                "hourly_limit": usage_stats.get("hourly_limit", 50),
                "daily_limit": usage_stats.get("daily_limit", 100),
            },
            "usage": {
                "today_queries": usage_stats.get("today_queries", 0),
                "daily_remaining": usage_stats.get("daily_remaining", 0),
                "hourly_queries": usage_stats.get("hourly_queries", 0),
                "hourly_remaining": usage_stats.get("hourly_remaining", 0),
            },
            "rate_limit": {
                "allowed": rate_allowed,
                "message": rate_message
            }
        }
    except Exception as e:
        return {
            "enabled": False,
            "configured": False,
            "error": str(e)
        }


# NOTE: Company discovery via Perplexity has been removed.
# Use POST /leads/discover/contacts directly with company list,
# or POST /leads/discover/companies (Phase 1) which uses discover_top_companies.


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
        from .ingestion_vm import get_google_api_credentials
        from .google_rate_limit import get_usage_stats
        
        # Check if Google CSE is configured
        api_key, cse_id = get_google_api_credentials()
        google_cse_configured = bool(api_key and cse_id)
        
        # Get Google CSE usage stats
        usage_stats = get_usage_stats()
        
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
            "google_cse_configured": google_cse_configured,
            "google_cse_usage": {
                "today_queries": usage_stats.get("today_queries", 0),
                "daily_limit": usage_stats.get("daily_limit", 100),
                "daily_remaining": usage_stats.get("daily_remaining", 100),
            },
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
    """Request model for direct contact discovery using Google CSE + OpenAI"""
    designation: str = "Manager"
    industry: str = "technology"
    location: str = "United States"
    count: int = 10
    criteria: str = ""


@router.post("/ai-database/discover-leads")
async def discover_leads_direct(request: DirectDiscoveryRequest):
    """
    POST /leads/ai-database/discover-leads
    Lead discovery using Google Custom Search + OpenAI enrichment.
    
    Flow:
    1. Build search query from parameters
    2. Google CSE finds LinkedIn profiles
    3. OpenAI extracts/enriches lead data
    4. Import to database with auto-classification
    
    Cost: ~$0.005 per search (free tier: 100/day)
    """
    try:
        from .ingestion_vm import search_linkedin_leads, get_google_api_credentials
        from .google_rate_limit import can_make_query, record_query, get_usage_stats
        from .service import import_leads
        from .models import LeadRaw
        
        # Check if Google CSE is configured
        api_key, cse_id = get_google_api_credentials()
        if not api_key or not cse_id:
            raise HTTPException(
                status_code=400,
                detail="Google CSE not configured. Add GOOGLE_API_KEY and GOOGLE_CSE_ID in Settings."
            )
        
        # Check rate limit
        allowed, message = can_make_query()
        if not allowed:
            usage = get_usage_stats()
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {message}. Today: {usage['today_queries']}/{usage['daily_limit']}"
            )
        
        # Build search query
        # Format: "designation" industry location site:linkedin.com/in/
        query_parts = []
        if request.designation:
            query_parts.append(f'"{request.designation}"')
        if request.industry:
            query_parts.append(request.industry)
        if request.location:
            query_parts.append(request.location)
        if request.criteria:
            query_parts.append(request.criteria)
        
        query = " ".join(query_parts)
        
        # Search for LinkedIn profiles
        leads_data = await search_linkedin_leads(
            query=query,
            num_results=min(request.count, 10),  # Google CSE max 10 per query
            deduplicate=True
        )
        
        # Record the API usage
        record_query(1)
        
        if not leads_data:
            return {
                "success": True,
                "message": "No contacts found matching criteria. Try different search terms.",
                "leads_imported": 0,
                "query_used": query
            }
        
        # Convert to LeadRaw and import
        leads = []
        for data in leads_data:
            linkedin_url = data.get("linkedin_url", "")
            if linkedin_url and not linkedin_url.startswith("http"):
                linkedin_url = f"https://{linkedin_url}"
            
            lead = LeadRaw(
                name=data.get("name", "Unknown"),
                title=data.get("title", request.designation),
                company_name=data.get("company_name", ""),
                linkedin_url=linkedin_url,
                snippet=data.get("snippet", f"AI Discovery: {request.designation} at {request.industry}"),
                location=data.get("location", request.location),
                email=data.get("email", ""),
                source="google_cse_discovery",
                import_batch_id=f"discovery_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            )
            leads.append(lead)
        
        # Import with auto-classification
        import_result = import_leads(leads, auto_classify=True)
        
        return {
            "success": True,
            "contacts_found": len(leads_data),
            "leads_imported": import_result.get("imported", 0),
            "duplicates": import_result.get("duplicates", 0),
            "method": "google_cse_openai",
            "query_used": query,
            "cost_estimate": "$0.00 (free tier)" if get_usage_stats()["today_queries"] <= 100 else f"${0.005:.4f}",
            "contacts": leads_data[:5]  # Return sample for UI display
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Discovery error: {str(e)}")


# NOTE: /ai-database/refill endpoint removed - was using Perplexity which is no longer supported.
# Use /ai-database/discover-leads with Google CSE instead.


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


# NOTE: /ai-database/process-batch endpoint removed - was using Perplexity which is no longer supported.
# Use /ai-database/discover-leads with Google CSE instead.


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


# NOTE: The following Perplexity-dependent endpoints have been removed:
# - POST /ai-database/discover-companies
# - POST /ai-database/discover-jobs
# - POST /ai-database/discover-local
# Use POST /ai-database/discover-leads with Google CSE + OpenAI instead.


# ============== GOOGLE CSE HEALTH & USAGE ENDPOINTS ==============

@router.get("/ai-database/google-health")
async def get_google_cse_health():
    """
    GET /leads/ai-database/google-health
    Check if Google CSE API is properly configured and working.
    """
    try:
        from .ingestion_vm import get_google_api_credentials, perform_google_search
        
        api_key, cse_id = get_google_api_credentials()
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "GOOGLE_API_KEY not set. Add it in Settings or .env file.",
                "setup_url": "https://console.cloud.google.com/apis/credentials"
            }
        
        if not cse_id:
            return {
                "status": "not_configured",
                "message": "GOOGLE_CSE_ID not set. Create a Custom Search Engine and add the ID.",
                "setup_url": "https://programmablesearchengine.google.com/"
            }
        
        # Test the API with a simple query
        try:
            test_results = await perform_google_search("test site:linkedin.com", num_results=1)
            
            if test_results is not None:
                return {
                    "status": "valid",
                    "message": "Google CSE is configured and working correctly.",
                    "api_key_prefix": api_key[:8] + "...",
                    "cse_id_prefix": cse_id[:8] + "..."
                }
            else:
                return {
                    "status": "error",
                    "message": "API responded but returned no results. Check CSE configuration."
                }
        except Exception as api_error:
            error_msg = str(api_error)
            if "403" in error_msg or "forbidden" in error_msg.lower():
                return {
                    "status": "invalid_key",
                    "message": "API key is invalid or Custom Search API is not enabled.",
                    "setup_url": "https://console.cloud.google.com/apis/library/customsearch.googleapis.com"
                }
            elif "429" in error_msg:
                return {
                    "status": "quota_exceeded",
                    "message": "Daily quota exceeded. Free tier: 100 queries/day."
                }
            else:
                return {
                    "status": "error",
                    "message": f"API test failed: {error_msg}"
                }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Health check failed: {str(e)}"
        }


@router.get("/ai-database/google-usage")
async def get_google_cse_usage():
    """
    GET /leads/ai-database/google-usage
    Get Google CSE usage statistics and rate limit status.
    """
    try:
        from .google_rate_limit import get_usage_stats, estimate_monthly_cost, get_historical_usage
        
        stats = get_usage_stats()
        cost_estimate = estimate_monthly_cost()
        history = get_historical_usage(7)
        
        return {
            "success": True,
            "today": {
                "queries": stats["today_queries"],
                "limit": stats["daily_limit"],
                "remaining": stats["daily_remaining"],
                "percentage_used": round((stats["today_queries"] / stats["daily_limit"]) * 100, 1) if stats["daily_limit"] > 0 else 0
            },
            "hourly": {
                "queries": stats["hourly_queries"],
                "limit": stats["hourly_limit"],
                "remaining": stats["hourly_remaining"]
            },
            "monthly_estimate": cost_estimate,
            "rate_limit_enabled": stats["rate_limit_enabled"],
            "history": history
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/ai-database/google-usage/reset")
async def reset_google_cse_usage():
    """
    POST /leads/ai-database/google-usage/reset
    Reset today's Google CSE usage counter (admin function).
    """
    try:
        from .google_rate_limit import reset_daily_counter
        
        stats = reset_daily_counter()
        
        return {
            "success": True,
            "message": "Usage counter reset successfully",
            "stats": stats
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== BULK SERVICE TYPE TAGGING ==============

class BulkServiceTypeRequest(BaseModel):
    lead_ids: List[str]
    service_type: str

@router.post("/bulk-service-type")
async def bulk_update_service_type(request: BulkServiceTypeRequest):
    """
    POST /leads/bulk-service-type
    Bulk update service_type for selected leads.
    Valid types: Data Services, Insights Services, Error
    """
    valid_types = ["Data Services", "Insights Services", "Error"]
    if request.service_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid service_type. Must be one of: {valid_types}")
    
    from bson import ObjectId
    object_ids = []
    for lid in request.lead_ids:
        try:
            object_ids.append(ObjectId(lid))
        except Exception:
            pass
    
    if not object_ids:
        raise HTTPException(status_code=400, detail="No valid lead IDs provided")
    
    result = leads_enriched_collection.update_many(
        {"_id": {"$in": object_ids}},
        {"$set": {"service_type": request.service_type}}
    )
    
    return {
        "success": True,
        "updated_count": result.modified_count,
        "message": f"Tagged {result.modified_count} lead(s) as '{request.service_type}'"
    }


# ============== ICP CONFIGURATION ENDPOINTS ==============

@router.get("/icps")
async def list_icps(active_only: bool = False):
    """
    GET /leads/icps
    List all ICP configurations.
    Use ?active_only=true to return only active ICPs.
    """
    from .icp_config import get_active_icps, get_all_icps
    icps = get_active_icps() if active_only else get_all_icps()
    return {"icps": icps, "count": len(icps)}


@router.post("/icps")
async def create_icp_config(data: Dict[str, Any] = Body(...)):
    """
    POST /leads/icps
    Create a new ICP configuration.
    Required: slug, name
    Optional: designations, industries, countries, seniority_levels, custom_context, daily_budget, is_active
    """
    from .icp_config import create_icp
    try:
        icp = create_icp(data)
        return {"success": True, "icp": icp}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/icps/{slug}")
async def update_icp_config(slug: str, data: Dict[str, Any] = Body(...)):
    """
    PUT /leads/icps/{slug}
    Update an existing ICP configuration.
    slug and created_at are protected and cannot be changed.
    """
    from .icp_config import update_icp
    updated = update_icp(slug, data)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"ICP '{slug}' not found")
    return {"success": True, "icp": updated}


@router.delete("/icps/{slug}")
async def delete_icp_config(slug: str):
    """
    DELETE /leads/icps/{slug}
    Soft-delete an ICP (sets is_active=False). Does not remove the record.
    """
    from .icp_config import soft_delete_icp
    found = soft_delete_icp(slug)
    if not found:
        raise HTTPException(status_code=404, detail=f"ICP '{slug}' not found")
    return {"success": True, "message": f"ICP '{slug}' deactivated"}


# ============== BULK ICP TAG ==============

class BulkIcpTagRequest(BaseModel):
    lead_ids: List[str]
    icp_segment: str


@router.post("/bulk-icp-tag")
async def bulk_tag_icp_segment(request: BulkIcpTagRequest):
    """
    POST /leads/bulk-icp-tag
    Bulk assign icp_segment to selected leads in both leads_raw and leads_enriched.
    Validates icp_segment against active ICP slugs (or allows 'unknown').
    """
    from .icp_config import get_all_icps
    from bson import ObjectId

    # Validate slug
    valid_slugs = {icp["slug"] for icp in get_all_icps()} | {"unknown"}
    if request.icp_segment not in valid_slugs:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid icp_segment '{request.icp_segment}'. Valid values: {sorted(valid_slugs)}"
        )

    object_ids = []
    for lid in request.lead_ids:
        try:
            object_ids.append(ObjectId(lid))
        except Exception:
            pass

    if not object_ids:
        raise HTTPException(status_code=400, detail="No valid lead IDs provided")

    enriched_result = leads_enriched_collection.update_many(
        {"_id": {"$in": object_ids}},
        {"$set": {"icp_segment": request.icp_segment, "updated_at": datetime.utcnow()}}
    )
    raw_result = _jobs_db["leads_raw"].update_many(
        {"enriched_lead_id": {"$in": [str(oid) for oid in object_ids]}},
        {"$set": {"icp_segment": request.icp_segment, "updated_at": datetime.utcnow()}}
    )

    return {
        "success": True,
        "enriched_updated": enriched_result.modified_count,
        "raw_updated": raw_result.modified_count,
        "message": f"Tagged {enriched_result.modified_count} lead(s) as ICP '{request.icp_segment}'",
    }


# ============== BULK BASKET RECLASSIFICATION ==============

@router.post("/reclassify-baskets")
async def reclassify_baskets_all(background_tasks: BackgroundTasks):
    """
    POST /leads/reclassify-baskets
    Runs compute_icp_basket() on ALL leads_enriched docs that are missing
    classification_basket (or have basket=null). No AI calls — pure rule-based.
    After updating, also triggers cold-outreach enrollment catch-up.
    """
    background_tasks.add_task(_run_reclassify_baskets_job)
    total = leads_enriched_collection.count_documents(
        {"classification_basket": {"$in": [None, ""]}}
    )
    return {
        "success": True,
        "message": f"Basket reclassification started for ~{total} leads without a basket.",
        "leads_to_process": total,
    }


async def _run_reclassify_baskets_job():
    """
    Background: assign classification_basket to every leads_enriched doc missing it.
    Processes in bulk batches; after completion triggers enrollment sync.
    """
    from .canonical_ingestion import compute_icp_basket
    from pymongo import UpdateOne

    batch_size = 500
    updated = 0
    processed = 0
    last_id = None

    print("[ReclassifyBaskets] Starting basket reclassification...")
    try:
        while True:
            query = {"classification_basket": {"$in": [None, ""]}}
            if last_id is not None:
                query["_id"] = {"$gt": last_id}

            batch = list(leads_enriched_collection.find(query).sort("_id", 1).limit(batch_size))
            if not batch:
                break

            bulk_ops = []
            for lead in batch:
                basket_data = compute_icp_basket(lead)
                bulk_ops.append(UpdateOne(
                    {"_id": lead["_id"]},
                    {"$set": {**basket_data, "updated_at": datetime.utcnow()}},
                ))

            if bulk_ops:
                result = leads_enriched_collection.bulk_write(bulk_ops, ordered=False)
                updated += result.modified_count

            last_id = batch[-1]["_id"]
            processed += len(batch)
            print(f"[ReclassifyBaskets] Processed {processed}, updated {updated}")

        print(f"[ReclassifyBaskets] Done — {updated}/{processed} leads updated with basket")

        # Trigger cold outreach enrollment catch-up
        try:
            from ..routers.cold_outreach_router import _sync_active_campaign_enrollment, get_db
            _sync_active_campaign_enrollment(get_db())
            print("[ReclassifyBaskets] Triggered cold outreach enrollment sync")
        except Exception as enroll_err:
            print(f"[ReclassifyBaskets] Enrollment sync skipped: {enroll_err}")

    except Exception as e:
        import traceback
        print(f"[ReclassifyBaskets] Error: {e}")
        traceback.print_exc()


@router.get("/reclassify-baskets/stats")
async def reclassify_baskets_stats():
    """
    GET /leads/reclassify-baskets/stats
    Returns count of leads missing classification_basket (to check if re-run is needed).
    """
    missing = leads_enriched_collection.count_documents(
        {"classification_basket": {"$in": [None, ""]}}
    )
    total = leads_enriched_collection.count_documents({})
    pipeline = [
        {"$group": {"_id": "$classification_basket", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    dist = list(leads_enriched_collection.aggregate(pipeline))
    return {
        "total_leads": total,
        "missing_basket": missing,
        "basket_distribution": [{"basket": d["_id"], "count": d["count"]} for d in dist],
    }


@router.post("/backfill-emails-from-raw")
async def backfill_emails_from_raw(background_tasks: BackgroundTasks):
    """
    POST /leads/backfill-emails-from-raw
    One-time backfill: for every leads_enriched record missing an email,
    look up its linked leads_raw record (via raw_lead_id) and copy the email
    + company_domain over if present.  Then triggers cold outreach enrollment.
    """
    no_email_count = leads_enriched_collection.count_documents(
        {"$or": [{"email": None}, {"email": ""}, {"email": {"$exists": False}}]}
    )
    background_tasks.add_task(_run_backfill_emails_job)
    return {
        "success": True,
        "message": f"Email backfill started for ~{no_email_count} leads_enriched records without email.",
        "leads_to_process": no_email_count,
    }


async def _run_backfill_emails_job():
    """
    Background: copy email + company_domain from leads_raw → leads_enriched
    for records that are missing email.
    """
    from pymongo import UpdateOne as _UpdateOne
    from bson import ObjectId as _ObjId

    _raw_col = leads_enriched_collection.database["leads_raw"]

    batch_size = 500
    processed = 0
    updated = 0
    last_id = None

    print("[BackfillEmails] Starting email backfill from leads_raw → leads_enriched...")
    try:
        while True:
            query: dict = {
                "$or": [{"email": None}, {"email": ""}, {"email": {"$exists": False}}],
                "raw_lead_id": {"$exists": True},
            }
            if last_id is not None:
                query["_id"] = {"$gt": last_id}

            batch = list(leads_enriched_collection.find(query).sort("_id", 1).limit(batch_size))
            if not batch:
                break

            bulk_ops = []
            for enriched_doc in batch:
                raw_id_str = enriched_doc.get("raw_lead_id")
                if not raw_id_str:
                    continue
                try:
                    raw_doc = _raw_col.find_one({"_id": _ObjId(str(raw_id_str))})
                except Exception:
                    raw_doc = _raw_col.find_one({"_id": raw_id_str})

                if not raw_doc:
                    continue

                raw_email = (raw_doc.get("email") or "").strip()
                if not raw_email:
                    continue

                set_fields: dict = {"email": raw_email, "updated_at": datetime.utcnow()}
                for _f in ("email_status", "email_source", "email_pattern_confidence",
                           "company_domain", "company_name", "company_industry",
                           "company_revenue_range", "company_headquarters"):
                    val = raw_doc.get(_f)
                    if val and not enriched_doc.get(_f):
                        set_fields[_f] = val

                bulk_ops.append(_UpdateOne({"_id": enriched_doc["_id"]}, {"$set": set_fields}))

            if bulk_ops:
                result = leads_enriched_collection.bulk_write(bulk_ops, ordered=False)
                updated += result.modified_count

            last_id = batch[-1]["_id"]
            processed += len(batch)
            print(f"[BackfillEmails] Processed {processed}, updated {updated}")

        print(f"[BackfillEmails] Done — {updated}/{processed} leads updated with email")

        # Trigger cold outreach enrollment for newly-emailed leads
        try:
            from ..routers.cold_outreach_router import _sync_active_campaign_enrollment, get_db as _co_db
            _sync_active_campaign_enrollment(_co_db())
            print("[BackfillEmails] Triggered cold outreach enrollment sync")
        except Exception as enroll_err:
            print(f"[BackfillEmails] Enrollment sync skipped: {enroll_err}")

    except Exception as e:
        import traceback
        print(f"[BackfillEmails] Error: {e}")
        traceback.print_exc()


@router.post("/backfill-emails-from-name-domain")
async def backfill_emails_from_name_domain(background_tasks: BackgroundTasks):
    """
    POST /leads/backfill-emails-from-name-domain
    For every leads_enriched record that has first_name + company_domain but
    no email, construct a guessed email (firstname.lastname@domain) and store
    it with email_status='predicted'.  Runs in background.
    """
    no_email_count = leads_enriched_collection.count_documents({
        "$or": [{"email": None}, {"email": ""}, {"email": {"$exists": False}}],
        "first_name": {"$nin": [None, ""]},
        "company_domain": {"$nin": [None, ""]},
    })
    background_tasks.add_task(_run_backfill_name_domain_job)
    return {
        "success": True,
        "message": f"Name+domain email backfill started for ~{no_email_count} leads.",
        "leads_to_process": no_email_count,
    }


async def _run_backfill_name_domain_job():
    """
    Background: for leads_enriched records missing email but with first_name +
    company_domain, call _discover_and_apply_email_pattern (which now includes a
    name+domain guess fallback).  Write the derived email back to both collections.
    """
    import re as _re
    from .canonical_ingestion import _discover_and_apply_email_pattern
    from bson import ObjectId as _ObjId

    _raw_col = leads_enriched_collection.database["leads_raw"]
    PERSONAL_DOMAINS = {
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
        "aol.com", "icloud.com", "live.com", "protonmail.com",
    }

    batch_size = 200
    processed = 0
    updated = 0
    last_id = None

    print("[BackfillNameDomain] Starting guessed-email backfill...")
    try:
        while True:
            query: dict = {
                "$or": [{"email": None}, {"email": ""}, {"email": {"$exists": False}}],
                "first_name": {"$nin": [None, ""]},
                "company_domain": {"$nin": [None, ""]},
            }
            if last_id is not None:
                query["_id"] = {"$gt": last_id}

            batch = list(leads_enriched_collection.find(query).sort("_id", 1).limit(batch_size))
            if not batch:
                break

            for doc in batch:
                domain = (doc.get("company_domain") or "").lower().strip()
                if not domain or domain in PERSONAL_DOMAINS:
                    continue

                stub = {
                    "email": None,
                    "first_name": doc.get("first_name", ""),
                    "last_name": doc.get("last_name", ""),
                    "company_domain": domain,
                    "email_status": "Unknown",
                }
                try:
                    _discover_and_apply_email_pattern(stub)
                except Exception:
                    pass

                guessed = (stub.get("email") or "").strip()
                if not guessed or "@" not in guessed:
                    continue

                try:
                    leads_enriched_collection.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {
                            "email": guessed,
                            "email_status": stub.get("email_status", "predicted"),
                            "email_source": stub.get("email_source", "name_domain_guess"),
                            "updated_at": datetime.utcnow(),
                        }},
                    )
                except Exception as _dup_err:
                    # E11000 duplicate key — another lead already has this email, skip
                    print(f"[BackfillNameDomain] Skip dup email {guessed}: {_dup_err}")
                    continue
                # Mirror to leads_raw if linked
                raw_id = doc.get("raw_lead_id")
                if raw_id:
                    try:
                        _raw_col.update_one(
                            {"_id": _ObjId(str(raw_id))},
                            {"$set": {"email": guessed}},
                        )
                    except Exception:
                        pass
                updated += 1

            last_id = batch[-1]["_id"]
            processed += len(batch)
            print(f"[BackfillNameDomain] Processed {processed}, updated {updated}")

        print(f"[BackfillNameDomain] Done — {updated}/{processed} leads now have guessed email")
    except Exception as e:
        import traceback
        print(f"[BackfillNameDomain] Error: {e}")
        traceback.print_exc()


# ============== GEMINI DOMAIN BACKFILL ==============

@router.post("/backfill-company-domain-gemini")
async def backfill_company_domain_gemini(background_tasks: BackgroundTasks):
    """
    POST /leads/backfill-company-domain-gemini
    For leads_enriched records that have company_name but no company_domain,
    use Gemini to infer the company domain, then generate a guessed email.
    """
    count = leads_enriched_collection.count_documents({
        "$or": [{"email": None}, {"email": {"$exists": False}}],
        "company_name": {"$nin": [None, ""]},
        "$or": [{"company_domain": None}, {"company_domain": ""}, {"company_domain": {"$exists": False}}],
    })
    background_tasks.add_task(_run_gemini_domain_backfill)
    return {"message": "Gemini domain backfill started", "leads_to_process": count}


async def _run_gemini_domain_backfill():
    """
    Background: infer company_domain from company_name using _infer_company_domain(),
    then generate a guessed email from first_name + last_name + domain.
    Falls back to Gemini only if string inference fails.
    """
    import re as _re
    from .canonical_ingestion import _discover_and_apply_email_pattern
    from .ingestion import _infer_company_domain
    from bson import ObjectId as _ObjId

    EMAIL_RE = _re.compile(r'^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$')
    PERSONAL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com"}
    SKIP_NAMES = {"not specified", "unknown", "n/a", ""}

    _raw_col = leads_enriched_collection.database["leads_raw"]

    query = {
        "$and": [
            {"$or": [{"email": None}, {"email": {"$exists": False}}]},
            {"company_name": {"$nin": [None, "", "Not specified", "not specified", "Unknown", "N/A"]}},
            {"$or": [{"company_domain": None}, {"company_domain": ""}, {"company_domain": {"$exists": False}}]},
            {"first_name": {"$nin": [None, ""]}},
        ]
    }

    leads = list(leads_enriched_collection.find(query).limit(500))
    print(f"[GeminiDomainBackfill] Found {len(leads)} leads to process")

    processed = 0
    domain_found = 0
    email_found = 0

    for doc in leads:
        company_name = (doc.get("company_name") or "").strip()
        if not company_name or company_name.lower() in SKIP_NAMES:
            processed += 1
            continue

        # Try string-based inference first (free, no API call)
        snippet = doc.get("snippet") or doc.get("source_detail") or ""
        domain = _infer_company_domain(company_name, snippet if isinstance(snippet, str) else "")
        # Guard against junk domains derived from placeholder company names
        if not domain or domain in PERSONAL_DOMAINS or domain == "notspecified.com":
            domain = None

        if not domain:
            processed += 1
            continue

        domain_found += 1

        # Now try to build email from first_name + last_name + domain
        stub = {
            "email": None,
            "first_name": doc.get("first_name", ""),
            "last_name": doc.get("last_name", ""),
            "company_domain": domain,
            "email_status": "Unknown",
        }
        try:
            _discover_and_apply_email_pattern(stub)
        except Exception:
            pass

        update_fields: dict = {"company_domain": domain, "updated_at": datetime.utcnow()}
        guessed_email = (stub.get("email") or "").strip()
        if guessed_email and "@" in guessed_email and EMAIL_RE.match(guessed_email):
            update_fields["email"] = guessed_email
            update_fields["email_status"] = stub.get("email_status", "predicted")
            update_fields["email_source"] = "name_domain_inferred"
            email_found += 1

        try:
            leads_enriched_collection.update_one({"_id": doc["_id"]}, {"$set": update_fields})
        except Exception as _dup:
            print(f"[GeminiDomainBackfill] Dup skip {guessed_email}: {_dup}")

        # Mirror domain to leads_raw
        raw_id = doc.get("raw_lead_id")
        if raw_id:
            try:
                _raw_col.update_one(
                    {"_id": _ObjId(str(raw_id))},
                    {"$set": {"company_domain": domain}},
                )
            except Exception:
                pass

        processed += 1

    print(f"[GeminiDomainBackfill] Done — {processed} processed, {domain_found} domains inferred, {email_found} emails generated")


# ============== BULK ICP RECLASSIFICATION ==============

@router.post("/reclassify-icp")
async def reclassify_icp_all(background_tasks: BackgroundTasks):
    """
    POST /leads/reclassify-icp
    Filter-based ICP reclassification of ALL leads in leads_enriched.
    No AI calls — pure string matching against ICP designation/industry/country/seniority.
    Force-all: processes every lead regardless of current icp_segment.
    Returns a job_id to poll for progress.
    """
    job_id = str(uuid.uuid4())[:8]
    web_search_jobs_collection.insert_one({
        "job_id": job_id,
        "type": "reclassify_icp",
        "status": "pending",
        "processed": 0,
        "total": 0,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    })
    background_tasks.add_task(_run_reclassify_icp_job, job_id)
    return {
        "success": True,
        "job_id": job_id,
        "message": "ICP reclassification started for all leads.",
        "status_url": f"/leads/reclassify-icp/status/{job_id}",
    }


@router.get("/reclassify-icp/status/{job_id}")
async def reclassify_icp_status(job_id: str):
    """
    GET /leads/reclassify-icp/status/{job_id}
    Poll the progress of a reclassify-icp job.
    """
    job = web_search_jobs_collection.find_one({"job_id": job_id, "type": "reclassify_icp"})
    if not job:
        raise HTTPException(status_code=404, detail="Reclassify job not found")
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "processed": job.get("processed", 0),
        "total": job.get("total", 0),
        "updated": job.get("updated", 0),
        "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
        "completed_at": job["completed_at"].isoformat() if job.get("completed_at") else None,
        "error": job.get("error"),
    }


async def _run_reclassify_icp_job(job_id: str):
    """
    Background task: filter-based ICP assignment for ALL leads.
    Phase 1: processes leads_enriched (5k) and mirrors back to leads_raw via enriched_lead_id.
    Phase 2: processes remaining leads_raw docs that have no enriched counterpart.
    """
    from .icp_config import get_active_icps, classify_lead_by_icp

    try:
        active_icps = get_active_icps()
        raw_col = _jobs_db["leads_raw"]

        enriched_total = leads_enriched_collection.count_documents({})
        raw_only_total = raw_col.count_documents({"enriched_lead_id": {"$in": [None, ""]}})
        total = enriched_total + raw_only_total

        web_search_jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "running",
                "total": total,
                "enriched_total": enriched_total,
                "raw_only_total": raw_only_total,
                "updated_at": datetime.utcnow(),
            }},
        )

        processed = 0
        updated = 0
        batch_size = 500

        # ── Phase 1: leads_enriched (and mirror to leads_raw) ──────────────────
        skip = 0
        while skip < enriched_total:
            batch = list(leads_enriched_collection.find({}, {
                "_id": 1, "title": 1, "company_industry": 1, "location": 1,
                "seniority_level": 1, "country": 1, "inferred_location": 1,
                "company_headquarters": 1,
            }).skip(skip).limit(batch_size))

            if not batch:
                break

            for lead in batch:
                segment = classify_lead_by_icp(lead, active_icps)
                oid = lead["_id"]
                r = leads_enriched_collection.update_one(
                    {"_id": oid},
                    {"$set": {"icp_segment": segment, "updated_at": datetime.utcnow()}},
                )
                raw_col.update_many(
                    {"enriched_lead_id": str(oid)},
                    {"$set": {"icp_segment": segment, "updated_at": datetime.utcnow()}},
                )
                if r.modified_count:
                    updated += 1

            skip += len(batch)
            processed += len(batch)
            web_search_jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {"processed": processed, "updated": updated, "updated_at": datetime.utcnow()}},
            )

        # ── Phase 2: raw leads still untagged after Phase 1 ──────────────────
        # Catches raw-only leads (no enriched counterpart) AND raw leads whose
        # enriched_lead_id points to a deleted/non-existent enriched doc.
        FIELDS = {"_id": 1, "title": 1, "company_industry": 1, "location": 1,
                  "seniority_level": 1, "country": 1}
        last_id = None
        while True:
            query = {"icp_segment": None}
            if last_id is not None:
                query["_id"] = {"$gt": last_id}
            batch = list(raw_col.find(query, FIELDS).sort("_id", 1).limit(batch_size))

            if not batch:
                break

            bulk_ops = []
            from pymongo import UpdateOne
            for lead in batch:
                segment = classify_lead_by_icp(lead, active_icps)
                bulk_ops.append(UpdateOne(
                    {"_id": lead["_id"]},
                    {"$set": {"icp_segment": segment, "updated_at": datetime.utcnow()}},
                ))

            if bulk_ops:
                result = raw_col.bulk_write(bulk_ops, ordered=False)
                updated += result.modified_count

            last_id = batch[-1]["_id"]
            processed += len(batch)
            web_search_jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {"processed": processed, "updated": updated, "updated_at": datetime.utcnow()}},
            )

        web_search_jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "done",
                "processed": processed,
                "updated": updated,
                "completed_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }},
        )
        print(f"[ReclassifyICP:{job_id}] Done — {updated}/{processed} leads tagged")

    except Exception as e:
        import traceback
        web_search_jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {"status": "error", "error": str(e), "updated_at": datetime.utcnow()}},
        )
        print(f"[ReclassifyICP:{job_id}] Error: {e}")
        traceback.print_exc()


# ============== SKRAPP USAGE STATS ==============

@router.get("/skrapp/usage")
async def get_skrapp_usage():
    """
    GET /leads/skrapp/usage
    Returns monthly usage stats for all 3 Skrapp accounts.
    """
    month = datetime.utcnow().strftime("%Y-%m")
    settings_db = _mongo_client["torpedo_settings"]
    app_settings = settings_db["app_settings"].find_one({"_id": "app_config"}) or {}

    key_count = 0
    for i in range(1, 4):
        if app_settings.get(f"skrapp_api_key_{i}") or os.getenv(f"SKRAPP_API_KEY_{i}"):
            key_count += 1

    usage_col = _jobs_db["skrapp_usage"]
    stats = []
    for i in range(1, 4):
        doc = usage_col.find_one({"account_id": str(i), "month": month}) or {}
        used = doc.get("searches_used", 0)
        limit = doc.get("searches_limit", 150)
        stats.append({
            "account": i,
            "month": month,
            "searches_used": used,
            "searches_limit": limit,
            "remaining": max(limit - used, 0),
            "key_configured": i <= key_count,
        })

    return {"accounts": stats}


# ============== IMPORT FROM RFQS / CONTACTS ==============

_rfqs_col = _jobs_db["rfqs"]
_torpedo_gmail_col = _mongo_client["torpedo_gmail"]["email_metadata"]


@router.post("/import/from-rfqs")
async def import_leads_from_rfqs(payload: Dict[str, Any] = Body(default={})):
    """
    POST /leads/import/from-rfqs
    Scans email_automation.rfqs for unique contacts and creates leads.
    For each unique email found in RFQs it records:
      - name, email, company (from the RFQ)
      - rfq_ids: list of linked RFQ IDs
      - last_email_date: last inbound/outbound email timestamp (from torpedo_gmail)
      - conversation_summary: latest RFQ subject/description as AI summary placeholder
    Returns import stats.
    """
    from .canonical_ingestion import ingest_lead

    skip_classification: bool = payload.get("skip_classification", True)

    # 1. Aggregate unique contacts from RFQs
    pipeline = [
        {"$match": {"contact_email": {"$exists": True, "$ne": None, "$ne": ""}}},
        {"$group": {
            "_id": {"$toLower": "$contact_email"},
            "name": {"$first": "$contact_name"},
            "company": {"$first": "$company_name"},
            "rfq_ids": {"$push": {"$ifNull": ["$rfq_id", {"$toString": "$_id"}]}},
            "latest_subject": {"$last": "$subject"},
            "latest_description": {"$last": "$description"},
            "latest_date": {"$max": "$created_at"},
        }},
        {"$limit": 2000},
    ]
    rfq_contacts = list(_rfqs_col.aggregate(pipeline))

    # 2. Build email → last_email_date map from torpedo_gmail
    all_emails = [c["_id"] for c in rfq_contacts if c["_id"]]
    email_dates: Dict[str, Any] = {}
    if all_emails:
        gmail_pipeline = [
            {"$match": {"from_email": {"$in": all_emails}}},
            {"$group": {
                "_id": "$from_email",
                "last_date": {"$max": "$date"},
            }},
        ]
        for row in _torpedo_gmail_col.aggregate(gmail_pipeline):
            email_dates[row["_id"]] = row["last_date"]

    # 3. Ingest each unique contact
    inserted = 0
    updated = 0
    skipped = 0
    errors = 0

    for contact in rfq_contacts:
        email = contact["_id"]
        if not email or "@" not in email:
            skipped += 1
            continue

        last_date = email_dates.get(email) or contact.get("latest_date")
        days_since: Optional[int] = None
        if last_date:
            try:
                if isinstance(last_date, str):
                    from dateutil import parser as _dateparser
                    last_date = _dateparser.parse(last_date)
                delta = datetime.utcnow() - last_date.replace(tzinfo=None) if hasattr(last_date, "replace") else None
                if delta:
                    days_since = delta.days
            except Exception:
                pass

        lead_payload = {
            "email": email,
            "name": contact.get("name") or "",
            "company": contact.get("company") or "",
            "company_name": contact.get("company") or "",
            "source": "rfq",
            "source_detail": "import_from_rfqs",
            "rfq_ids": contact.get("rfq_ids", [])[:20],
            "last_email_date": last_date.isoformat() if hasattr(last_date, "isoformat") else str(last_date) if last_date else None,
            "days_since_last_contact": days_since,
            "conversation_summary": contact.get("latest_subject") or contact.get("latest_description") or "",
        }

        try:
            result = ingest_lead(
                payload=lead_payload,
                source="rfq",
                source_detail="import_from_rfqs",
                skip_classification=skip_classification,
            )
            if result["success"]:
                if result["action"] == "inserted":
                    inserted += 1
                else:
                    updated += 1
            else:
                skipped += 1
        except Exception:
            errors += 1

    return {
        "success": True,
        "total_rfq_contacts": len(rfq_contacts),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


# ── Retry failed leads ──────────────────────────────────────────────────────

@router.post("/retry-failed", summary="Reset failed leads back to pending for retry")
async def retry_failed_leads(limit: int = Query(10000, ge=1, le=50000)):
    """
    Reset all leads with classification_status='Failed' back to Pending
    and clear classification_attempts so they get picked up by the next
    background classification run.
    """
    try:
        result = leads_raw_collection.update_many(
            {"classification_status": "Failed"},
            {
                "$set": {
                    "classification_status": "Pending",
                    "classification_attempts": 0,
                    "last_error": None,
                    "retry_queued_at": datetime.utcnow(),
                },
                "$unset": {"last_attempt_at": ""}
            }
        )
        return {
            "success": True,
            "reset_count": result.modified_count,
            "message": f"Reset {result.modified_count} failed leads to Pending. They will be classified in the next background run.",
        }
    except Exception as e:
        logger.error(f"[retry-failed] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Clean names/titles in leads_enriched ────────────────────────────────────

@router.post("/clean-enriched-names", summary="Strip LinkedIn suffix from names and titles in leads_enriched")
async def clean_enriched_names():
    """
    Strip ' | ...' LinkedIn/title suffixes from name and title fields in leads_enriched.
    Also strips them from first_name/last_name where applicable.
    """
    try:
        import re
        updated = 0
        skipped = 0

        for doc in leads_enriched_collection.find(
            {"$or": [
                {"name": {"$regex": r"\s*\|", "$options": "i"}},
                {"title": {"$regex": r"\s*\|", "$options": "i"}},
                {"first_name": {"$regex": r"\s*\|", "$options": "i"}},
            ]},
            {"_id": 1, "name": 1, "title": 1, "first_name": 1, "last_name": 1}
        ):
            updates = {}

            name = doc.get("name", "") or ""
            if " | " in name:
                clean_name = name.split(" | ")[0].strip()
                updates["name"] = clean_name
                # Re-split first/last if first_name not set
                if not doc.get("first_name") and clean_name:
                    parts = clean_name.strip().split(" ", 1)
                    updates["first_name"] = parts[0]
                    updates["last_name"] = parts[1] if len(parts) > 1 else ""

            title = doc.get("title", "") or ""
            if " | " in title:
                updates["title"] = title.split(" | ")[0].strip()

            first_name = doc.get("first_name", "") or ""
            if " | " in first_name:
                updates["first_name"] = first_name.split(" | ")[0].strip()

            if updates:
                leads_enriched_collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": updates}
                )
                updated += 1
            else:
                skipped += 1

        # Also clean leads_raw names
        raw_updated = 0
        for doc in leads_raw_collection.find(
            {"name": {"$regex": r"\s*\|", "$options": "i"}},
            {"_id": 1, "name": 1}
        ):
            name = doc.get("name", "") or ""
            if " | " in name:
                leads_raw_collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"name": name.split(" | ")[0].strip()}}
                )
                raw_updated += 1

        return {
            "success": True,
            "enriched_updated": updated,
            "raw_updated": raw_updated,
            "message": f"Cleaned {updated} enriched leads and {raw_updated} raw leads",
        }
    except Exception as e:
        logger.error(f"[clean-enriched-names] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


