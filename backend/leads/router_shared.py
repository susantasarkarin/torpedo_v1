"""
leads/router_shared.py
======================
Shared state extracted from leads/router.py:
- MongoDB connections and collections
- JobStatus constants
- Global search control functions
- Rate limiting helpers
- Pydantic request models
- Job CRUD helpers
- Query generation logic
- run_web_search_job background coroutine

Kept in a separate module so router.py contains only route handlers.
main.py imports (get_incomplete_jobs, run_web_search_job, update_job,
JobStatus, get_global_search_control) continue to work because router.py
re-exports everything via `from .router_shared import *`.
"""

import asyncio
import os
import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel
from pymongo import MongoClient

from .models import LeadInput
from .service import import_leads, classify_pending_leads
from .ingestion import search_linkedin_leads

load_dotenv()

# ============== MONGODB CONNECTION FOR JOBS ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
_mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_jobs_db = _mongo_client['email_automation']
_torpedo_gmail_db = _mongo_client['torpedo_gmail']
web_search_jobs_collection = _jobs_db['web_search_jobs']
email_metadata_collection = _torpedo_gmail_db['email_metadata']

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
    API_ERROR = "api_error"


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
    set_global_search_control({
        "paused": True,
        "paused_at": datetime.utcnow().isoformat(),
        "paused_reason": reason,
    })
    return result.modified_count


# ============== RATE LIMITING (DYNAMIC FROM SETTINGS) ==============

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


# Legacy constants (fallback only)
DAILY_LIMIT = 400
LEADS_PER_MINUTE = 3
DELAY_BETWEEN_BATCHES = 20


# ============== IMPORT MODELS ==============

class GoogleSearchRequest(BaseModel):
    query: str
    num_results: int = 10


class WebSearchRequest(BaseModel):
    """Enhanced web search with filters - supports multi-select"""
    designation: str = ""
    countries: List[str] = []
    seniorities: List[str] = []
    industries: List[str] = []
    custom_query: str = ""
    icp_id: Optional[str] = None
    country: str = ""
    seniority: str = ""
    industry: str = ""


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
        "day_started": datetime.utcnow().date().isoformat(),
    }
    web_search_jobs_collection.insert_one(job)
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    return web_search_jobs_collection.find_one({"job_id": job_id})


def update_job(job_id: str, updates: dict):
    updates["last_update"] = datetime.utcnow()
    web_search_jobs_collection.update_one({"job_id": job_id}, {"$set": updates})


def add_job_error(job_id: str, error: str):
    web_search_jobs_collection.update_one(
        {"job_id": job_id},
        {
            "$push": {"errors": {"$each": [f"[{datetime.utcnow().isoformat()}] {error}"], "$slice": -50}},
            "$set": {"last_update": datetime.utcnow()},
        },
    )


def increment_job_counters(job_id: str, found: int = 0, imported: int = 0,
                           duplicates: int = 0, classified: int = 0, emails: int = 0):
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
                "queries_used": 1 if found > 0 else 0,
            },
            "$set": {"last_update": datetime.utcnow()},
        },
    )


def get_incomplete_jobs() -> List[dict]:
    return list(web_search_jobs_collection.find({
        "status": {"$in": [JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PAUSED, JobStatus.QUOTA_EXCEEDED]}
    }))


def check_and_reset_daily_limit(job_id: str) -> bool:
    job = get_job(job_id)
    if not job:
        return False
    current_day = datetime.utcnow().date().isoformat()
    if job.get("day_started") != current_day:
        update_job(job_id, {"leads_today": 0, "day_started": current_day})
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
        "CXO": ["CEO", "CTO", "CFO", "COO", "CMO", "CRO", "CIO", "CHRO", "CPO",
                "Chief Executive", "Chief Technology", "Chief Financial",
                "Chief Operating", "Chief Marketing"],
        "Partner": ["Partner", "Managing Partner", "General Partner", "Senior Partner"],
        "VP": ["VP", "Vice President", "SVP", "EVP", "AVP",
               "Senior Vice President", "Executive Vice President"],
        "Director": ["Director", "Head of", "Group Director", "Regional Director",
                     "Managing Director", "Associate Director"],
        "Manager": ["Manager", "Team Lead", "Supervisor", "Project Manager",
                    "Program Manager", "General Manager"],
        "Senior": ["Senior", "Sr.", "Lead", "Principal", "Staff", "Senior Associate"],
        "Entry": ["Associate", "Junior", "Entry Level", "Analyst", "Specialist", "Coordinator"],
        "Training": ["Intern", "Trainee", "Apprentice", "Graduate"],
        "Unpaid": ["Volunteer", "Board Member", "Advisory Board"],
    }

    default_industry_modifiers = [
        "", "Technology", "Software", "IT", "Finance", "Banking", "Healthcare",
        "Manufacturing", "Retail", "E-commerce", "Marketing", "Consulting",
        "Telecommunications", "Insurance", "Real Estate", "Pharmaceuticals",
        "Automotive", "Energy", "Education", "Media", "Entertainment",
        "Logistics", "Supply Chain", "FMCG", "Consumer Goods", "B2B", "SaaS",
    ]
    industry_modifiers = [""] + industries if industries else default_industry_modifiers

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

                    site_prefix = COUNTRY_SITE_PREFIXES.get(country)
                    if site_prefix and designation:
                        for anchor in SFW_ANCHOR_TERMS[:4]:
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
    Background task that continuously searches until stopped.
    Rate-limited, auto-classifies, persists state to MongoDB for resume.
    Respects global pause and circuit breaker.
    """
    job = get_job(job_id)
    if not job:
        print(f"[WebSearch:{job_id}] Job not found")
        return

    control = get_global_search_control()
    if control.get("paused"):
        print(f"[WebSearch:{job_id}] Global search is paused: {control.get('paused_reason')}")
        update_job(job_id, {"status": JobStatus.PAUSED})
        return

    if control.get("circuit_breaker_open"):
        print(f"[WebSearch:{job_id}] Circuit breaker is open - too many errors")
        update_job(job_id, {"status": JobStatus.API_ERROR})
        return

    update_job(job_id, {"status": JobStatus.RUNNING, "started_at": datetime.utcnow()})

    config = job["config"]
    target_count = job["target_count"]
    icp_id = config.get("icp_id")

    query_combinations = job.get("query_combinations", [])
    if not query_combinations:
        query_combinations = generate_query_combinations(
            config.get("designations", []),
            config.get("countries", []),
            config.get("seniorities", []),
            config.get("custom_query", ""),
            config.get("industries", []),
        )
        update_job(job_id, {"query_combinations": query_combinations})

    seen_urls = set(job.get("seen_urls", []))
    batch_size = 10
    query_index = 0
    exhausted_queries: dict = {}
    EXHAUSTED_THRESHOLD = 3

    print(f"[WebSearch:{job_id}] Starting job - Target: {target_count}, Queries: {len(query_combinations)}")

    while True:
        job = get_job(job_id)
        if not job:
            break

        if job["status"] == JobStatus.STOPPED:
            print(f"[WebSearch:{job_id}] Job stopped by user")
            break

        control = get_global_search_control()
        if control.get("paused"):
            print(f"[WebSearch:{job_id}] Global search paused: {control.get('paused_reason')}")
            update_job(job_id, {"status": JobStatus.PAUSED})
            break

        if control.get("circuit_breaker_open"):
            print(f"[WebSearch:{job_id}] Circuit breaker open - stopping due to API errors")
            update_job(job_id, {"status": JobStatus.API_ERROR})
            break

        check_and_reset_daily_limit(job_id)
        job = get_job(job_id)

        rate_limits = get_rate_limit_settings()
        daily_limit = rate_limits["daily_limit"] if rate_limits["enabled"] else 100000

        if job["leads_today"] >= daily_limit:
            now = datetime.utcnow()
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            wait_seconds = (tomorrow - now).total_seconds()

            update_job(job_id, {"status": JobStatus.QUOTA_EXCEEDED})
            print(f"[WebSearch:{job_id}] Daily limit reached ({daily_limit}). Waiting until midnight UTC ({int(wait_seconds)}s)")

            while wait_seconds > 0:
                job = get_job(job_id)
                if not job or job["status"] == JobStatus.STOPPED:
                    return
                await asyncio.sleep(min(60, wait_seconds))
                wait_seconds -= 60

            update_job(job_id, {
                "status": JobStatus.RUNNING,
                "leads_today": 0,
                "day_started": datetime.utcnow().date().isoformat(),
            })
            continue

        if query_index >= len(query_combinations):
            query_index = 0
            random.shuffle(query_combinations)
            exhausted_queries.clear()

        query = query_combinations[query_index]
        query_index += 1

        if exhausted_queries.get(query, 0) >= EXHAUSTED_THRESHOLD:
            print(f"[WebSearch:{job_id}] Skipping exhausted query: '{query[:60]}'")
            await asyncio.sleep(0.2)
            continue

        update_job(job_id, {"current_query": query[:100]})

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
                    skip_cache=True,
                    deduplicate=False,
                )

                if not results:
                    consecutive_empty += 1
                    start_index += batch_size
                    continue

                consecutive_empty = 0

                for lead in results:
                    url = lead.get("linkedin_url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        batch_leads.append(lead)

                start_index += len(results)
                await asyncio.sleep(1)

            except Exception as e:
                error_msg = str(e)
                add_job_error(job_id, f"Search error: {error_msg}")
                print(f"[WebSearch:{job_id}] Error: {error_msg}")

                is_credential_error = any(x in error_msg.lower() for x in [
                    "api key", "invalid", "denied", "unauthorized", "forbidden", "aiza"
                ])

                if is_credential_error:
                    circuit_tripped = increment_error_count(error_msg)
                    if circuit_tripped:
                        update_job(job_id, {"status": JobStatus.API_ERROR})
                        print(f"[WebSearch:{job_id}] API credential error - job stopped")
                        return
                elif "quota" in error_msg.lower() or "limit" in error_msg.lower():
                    update_job(job_id, {"status": JobStatus.QUOTA_EXCEEDED})
                    print(f"[WebSearch:{job_id}] API quota exceeded, waiting until midnight...")

                    now = datetime.utcnow()
                    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    wait_seconds = (tomorrow - now).total_seconds()

                    while wait_seconds > 0:
                        job = get_job(job_id)
                        if not job or job["status"] == JobStatus.STOPPED:
                            return
                        control = get_global_search_control()
                        if control.get("paused"):
                            update_job(job_id, {"status": JobStatus.PAUSED})
                            return
                        await asyncio.sleep(min(60, wait_seconds))
                        wait_seconds -= 60

                    update_job(job_id, {"status": JobStatus.RUNNING})
                else:
                    increment_error_count(error_msg)
                break

        if batch_leads:
            reset_error_count()

        if batch_leads:
            try:
                lead_inputs = [LeadInput(**lead) for lead in batch_leads]
                result = import_leads(lead_inputs, icp_segment=icp_id)

                increment_job_counters(
                    job_id,
                    found=len(batch_leads),
                    imported=result.imported,
                    duplicates=result.duplicates,
                )
                print(f"[WebSearch:{job_id}] Query: '{query[:40]}...' - Found: {len(batch_leads)}, Imported: {result.imported}")

                if result.imported == 0:
                    exhausted_queries[query] = exhausted_queries.get(query, 0) + 1
                    if exhausted_queries[query] >= EXHAUSTED_THRESHOLD:
                        print(f"[WebSearch:{job_id}] Query marked exhausted (all dupes): '{query[:60]}'")
                else:
                    exhausted_queries.pop(query, None)

                if len(seen_urls) % 100 < batch_size:
                    update_job(job_id, {"seen_urls": list(seen_urls)})

            except Exception as e:
                add_job_error(job_id, f"Import error: {str(e)}")
        else:
            exhausted_queries[query] = exhausted_queries.get(query, 0) + 1

        try:
            success, failure = classify_pending_leads(50)
            if success > 0:
                from .service import leads_enriched_collection
                emails_count = leads_enriched_collection.count_documents({
                    "email": {"$ne": None, "$ne": ""},
                    "classified_at": {"$gte": datetime.utcnow() - timedelta(minutes=5)},
                })
                increment_job_counters(job_id, classified=success, emails=emails_count)
                print(f"[WebSearch:{job_id}] Classified: {success}, Emails found: {emails_count}")
        except Exception as e:
            add_job_error(job_id, f"Classification error: {str(e)}")

        delay = get_rate_limit_settings()["query_delay"]
        await asyncio.sleep(max(delay, DELAY_BETWEEN_BATCHES))

    job = get_job(job_id)
    if job and job["status"] == JobStatus.RUNNING:
        update_job(job_id, {"status": JobStatus.COMPLETED, "completed_at": datetime.utcnow()})

    print(f"[WebSearch:{job_id}] Job finished")
