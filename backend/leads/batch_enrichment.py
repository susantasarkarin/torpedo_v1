"""
BATCH LEAD ENRICHMENT (Phase 4)
Queues leads for enrichment and processes each job with a plain loop over
platform_core.ladder.escalate_json (Claude Haiku, then Sonnet). The old
OpenAI Batch API upload/poll/download flow is gone; a job now runs to
completion inside submit_batch_job().

How it works:
1. Queue leads for enrichment (stored in MongoDB)
2. submit_batch_job() enriches every lead in the job and upserts leads_enriched
3. Per-lead outcomes are logged in batch_enrichment_results

Constraints:
- Honours the DISABLE_AI_CALLS kill switch
- Cost is logged by the ladder (ai_governance.ladder_jobs), capped by its monthly budget
- Minimum batch size: 10 leads
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from pymongo import MongoClient
from dotenv import load_dotenv


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


load_dotenv()

# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
client = _get_pooled_client()
db = client['email_automation']

# Batch job tracking
batch_jobs = db['batch_enrichment_jobs']
batch_results = db['batch_enrichment_results']

try:
    batch_jobs.create_index("batch_id", unique=True, sparse=True)
    batch_jobs.create_index("status")
    batch_jobs.create_index("created_at")
    batch_jobs.create_index([("status", 1), ("created_at", -1)])
    
    batch_results.create_index("batch_job_id")
    batch_results.create_index("lead_id")
    batch_results.create_index("processed_at")
except Exception:
    pass


# ============== CONFIGURATION ==============

# Minimum leads per queued job
MIN_BATCH_SIZE = 10

# Maximum leads per job
MAX_BATCH_SIZE = 1000

# System prompt (same as ai_classifier.py)
BATCH_SYSTEM_PROMPT = """B2B lead enrichment expert. Respond with JSON only.

Output Schema:
{"first_name":"str","last_name":"str","predicted_email":"firstname.lastname@domain.com","seniority_level":"C-Level|VP|Director|Manager|IC|Unknown","department":"Sales|Marketing|Engineering|Operations|Finance|HR|Product|Other","persona":"Decision Maker|Influencer|Gatekeeper|Practitioner","buying_role":"Economic Buyer|Technical Buyer|User Buyer|Champion|Influencer|Unknown","gender":"Male|Female|Unknown","company_size":"Startup|SMB|Mid-Market|Enterprise","region":"US|EU|APAC|LATAM|Other","inferred_location":"str","company_name":"str","company_domain":"str","company_website":"str","company_employee_count":"str","company_employee_count_range":"1-10|11-50|51-200|201-500|501-1000|1001-5000|5001-10000|10000+","company_founded":"str","company_industry":"str","company_type":"Public|Private|Startup|Non-Profit|Government","company_headquarters":"str","company_revenue_range":"$1M-$10M|$10M-$50M|$50M-$100M|$100M-$500M|$500M-$1B|$1B+","company_linkedin_url":"str","confidence_score":0.0-1.0}

Rules: C-Level=CEO/CTO/CFO/Founder. Startup=1-50,SMB=51-200,Mid-Market=201-1000,Enterprise=1000+. Use knowledge for known companies. Minimize nulls."""


# ============== BATCH JOB STATUS ==============

class BatchJobStatus:
    QUEUED = "queued"
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============== BATCH OPERATIONS ==============

def queue_leads_for_batch_enrichment(
    lead_ids: List[str],
    priority: int = 0
) -> str:
    """
    Queue leads for batch enrichment.
    
    Args:
        lead_ids: List of lead ObjectIds (from leads_raw)
        priority: Higher priority batches processed first
        
    Returns:
        Batch job ID
    """
    from bson import ObjectId
    
    # Create batch job record
    job_doc = {
        "status": BatchJobStatus.QUEUED,
        "lead_ids": lead_ids,
        "lead_count": len(lead_ids),
        "priority": priority,
        "created_at": datetime.utcnow(),
        "submitted_at": None,
        "completed_at": None,
        "batch_id": None,  # legacy field (no provider batch id any more)
        "input_file_id": None,
        "output_file_id": None,
        "error": None,
        "results_processed": 0
    }
    
    result = batch_jobs.insert_one(job_doc)
    job_id = str(result.inserted_id)
    
    print(f"[BatchAPI] Queued {len(lead_ids)} leads for enrichment (job: {job_id})")
    
    return job_id


def get_queued_batch_jobs(min_leads: int = MIN_BATCH_SIZE) -> List[Dict]:
    """Get queued batch jobs ready for submission"""
    jobs = list(batch_jobs.find({
        "status": BatchJobStatus.QUEUED,
        "lead_count": {"$gte": min_leads}
    }).sort([("priority", -1), ("created_at", 1)]))
    
    return jobs


ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
        "predicted_email": {"type": "string"},
        "seniority_level": {"type": "string"},
        "department": {"type": "string"},
        "persona": {"type": "string"},
        "buying_role": {"type": "string"},
        "gender": {"type": "string"},
        "company_size": {"type": "string"},
        "region": {"type": "string"},
        "inferred_location": {"type": "string"},
        "company_name": {"type": "string"},
        "company_domain": {"type": "string"},
        "company_website": {"type": "string"},
        "company_employee_count": {"type": "string"},
        "company_employee_count_range": {"type": "string"},
        "company_founded": {"type": "string"},
        "company_industry": {"type": "string"},
        "company_type": {"type": "string"},
        "company_headquarters": {"type": "string"},
        "company_revenue_range": {"type": "string"},
        "company_linkedin_url": {"type": "string"},
        "confidence_score": {"type": "number"},
    },
    "required": ["first_name", "last_name", "confidence_score"],
}


def _store_enriched(raw_lead: Dict[str, Any], parsed: Dict[str, Any], job_id: str) -> bool:
    """Upsert one enriched lead into leads_enriched and log the outcome. True on success."""
    from bson import ObjectId
    leads_enriched = db['leads_enriched']
    lead_id = str(raw_lead["_id"])
    try:
        enriched = {
            "raw_lead_id": lead_id,
            "linkedin_url": raw_lead.get("linkedin_url"),
            "name": raw_lead.get("name"),
            "title": raw_lead.get("title"),
            "first_name": parsed.get("first_name", ""),
            "last_name": parsed.get("last_name", ""),
            "predicted_email": parsed.get("predicted_email"),
            "seniority_level": parsed.get("seniority_level", "Unknown"),
            "department": parsed.get("department", "Other"),
            "persona": parsed.get("persona", "Practitioner"),
            "buying_role": parsed.get("buying_role", "Unknown"),
            "gender": parsed.get("gender", "Unknown"),
            "company_size": parsed.get("company_size", "SMB"),
            "region": parsed.get("region", "Other"),
            "inferred_location": parsed.get("inferred_location"),
            "company_name": parsed.get("company_name") or raw_lead.get("company_name"),
            "company_domain": parsed.get("company_domain"),
            "company_website": parsed.get("company_website"),
            "company_employee_count": parsed.get("company_employee_count"),
            "company_employee_count_range": parsed.get("company_employee_count_range"),
            "company_founded": parsed.get("company_founded"),
            "company_industry": parsed.get("company_industry"),
            "company_type": parsed.get("company_type"),
            "company_headquarters": parsed.get("company_headquarters"),
            "company_revenue_range": parsed.get("company_revenue_range"),
            "company_linkedin_url": parsed.get("company_linkedin_url"),
            "confidence_score": float(parsed.get("confidence_score", 0.5)),
            "enriched_at": datetime.utcnow(),
            "enrichment_source": "batch_api",
        }
        leads_enriched.replace_one({"linkedin_url": enriched["linkedin_url"]}, enriched, upsert=True)
        db['leads_raw'].update_one({"_id": ObjectId(lead_id)}, {"$set": {"classification_status": "completed"}})
        batch_results.insert_one({
            "batch_job_id": job_id, "lead_id": lead_id, "success": True,
            "confidence_score": enriched["confidence_score"], "processed_at": datetime.utcnow(),
        })
        return True
    except Exception as e:
        batch_results.insert_one({
            "batch_job_id": job_id, "lead_id": lead_id, "success": False,
            "error": str(e), "processed_at": datetime.utcnow(),
        })
        return False


def submit_batch_job(job_id: str) -> Tuple[bool, str]:
    """
    Run a queued batch job: enrich each lead through the escalation ladder
    (plain loop over escalate_json) and store the results. Runs to completion
    before returning.

    Args:
        job_id: MongoDB batch job ID

    Returns:
        Tuple of (success, message/error)
    """
    from bson import ObjectId
    from platform_core.ladder import escalate_json

    if os.getenv("DISABLE_AI_CALLS", "").lower() in ("1", "true", "yes"):
        return False, "AI calls disabled (DISABLE_AI_CALLS)"

    job = batch_jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        return False, "Job not found"

    if job["status"] != BatchJobStatus.QUEUED:
        return False, f"Job not in queued state: {job['status']}"

    leads_raw = db['leads_raw']
    lead_ids = [ObjectId(lid) for lid in job["lead_ids"]]
    leads = list(leads_raw.find({"_id": {"$in": lead_ids}}))

    if not leads:
        batch_jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {"status": BatchJobStatus.FAILED, "error": "No leads found"}}
        )
        return False, "No leads found"

    batch_jobs.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"status": BatchJobStatus.IN_PROGRESS, "submitted_at": datetime.utcnow()}}
    )

    success_count = 0
    failure_count = 0
    try:
        for lead in leads:
            user_prompt = f"""Enrich lead:
Name:{lead.get('name', '')} Title:{lead.get('title', '')} URL:{lead.get('linkedin_url', '')}
Context:{str(lead.get('snippet') or '-')[:200]} Location:{lead.get('location', '-')} Company:{lead.get('company_name', '-')} Email:{lead.get('email', '-')}
Return JSON."""
            data, _tier, attempts = escalate_json(
                task="lead_enrichment",
                system=BATCH_SYSTEM_PROMPT,
                user=user_prompt,
                schema=ENRICHMENT_SCHEMA,
                check=lambda d: [] if isinstance(d, dict) else ["not a JSON object"],
                max_tokens=300,
            )
            if data is None:
                failure_count += 1
                problems = [p for a in attempts for p in (a.get("problems") or [])][:3]
                batch_results.insert_one({
                    "batch_job_id": job_id, "lead_id": str(lead["_id"]), "success": False,
                    "error": "; ".join(str(p) for p in problems) or "no tier answered",
                    "processed_at": datetime.utcnow(),
                })
                continue
            if _store_enriched(lead, data, job_id):
                success_count += 1
            else:
                failure_count += 1

        batch_jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {
                "status": BatchJobStatus.COMPLETED,
                "completed_at": datetime.utcnow(),
                "results_processed": success_count + failure_count,
                "success_count": success_count,
                "failure_count": failure_count,
            }}
        )
        print(f"[BatchEnrich] Job {job_id}: {success_count} enriched, {failure_count} failed")
        return True, f"{success_count} enriched, {failure_count} failed"

    except Exception as e:
        batch_jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {"status": BatchJobStatus.FAILED, "error": str(e),
                      "success_count": success_count, "failure_count": failure_count}}
        )
        return False, str(e)


def check_batch_status(job_id: str) -> Dict[str, Any]:
    """
    Status of a batch job. Jobs run synchronously in submit_batch_job(), so this
    only reads the job record.

    Args:
        job_id: MongoDB batch job ID

    Returns:
        Dict with status info
    """
    from bson import ObjectId

    job = batch_jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        return {"error": "Job not found"}
    return {
        "status": job.get("status"),
        "lead_count": job.get("lead_count"),
        "success_count": job.get("success_count", 0),
        "failure_count": job.get("failure_count", 0),
        "submitted_at": job.get("submitted_at"),
        "completed_at": job.get("completed_at"),
        "error": job.get("error"),
    }


def process_batch_results(job_id: str) -> Tuple[int, int]:
    """
    Results are written by submit_batch_job(); returns the stored counts.

    Args:
        job_id: MongoDB batch job ID

    Returns:
        Tuple of (success_count, failure_count)
    """
    from bson import ObjectId

    job = batch_jobs.find_one({"_id": ObjectId(job_id)}) or {}
    return int(job.get("success_count") or 0), int(job.get("failure_count") or 0)


# ============== BATCH MANAGER ==============

def run_batch_enrichment_cycle() -> Dict[str, Any]:
    """
    Run a complete batch enrichment cycle:
    1. Check for completed batches and process results
    2. Check for pending batches and update status
    3. Submit queued batches if ready
    
    Returns:
        Summary of operations performed
    """
    from bson import ObjectId
    
    summary = {
        "completed_processed": 0,
        "batches_submitted": 0,
        "batches_checked": 0,
        "errors": []
    }
    
    # 1. Process completed batches
    completed_jobs = list(batch_jobs.find({
        "status": BatchJobStatus.COMPLETED,
        "results_processed": 0
    }))
    
    for job in completed_jobs:
        success, failure = process_batch_results(str(job["_id"]))
        summary["completed_processed"] += success
    
    # 2. Check in-progress batches
    in_progress_jobs = list(batch_jobs.find({
        "status": {"$in": [BatchJobStatus.SUBMITTED, BatchJobStatus.IN_PROGRESS]}
    }))
    
    for job in in_progress_jobs:
        check_batch_status(str(job["_id"]))
        summary["batches_checked"] += 1
    
    # 3. Submit queued batches
    queued_jobs = get_queued_batch_jobs(min_leads=MIN_BATCH_SIZE)
    
    for job in queued_jobs[:3]:  # Max 3 concurrent batches
        success, result = submit_batch_job(str(job["_id"]))
        if success:
            summary["batches_submitted"] += 1
        else:
            summary["errors"].append(result)
    
    return summary


# ============== STATS ==============

def get_batch_stats() -> Dict[str, Any]:
    """Get batch enrichment statistics"""
    pipeline = [
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
            "total_leads": {"$sum": "$lead_count"}
        }}
    ]
    
    by_status = list(batch_jobs.aggregate(pipeline))
    
    # Calculate cost savings
    total_enriched = batch_results.count_documents({"success": True})
    
    # Regular API: ~630 tokens * $0.00015 input + ~250 tokens * $0.0006 output = ~$0.00024 per lead
    # Batch API: 50% off = ~$0.00012 per lead
    # Savings: ~$0.00012 per lead
    estimated_savings = total_enriched * 0.00012
    
    return {
        "by_status": {r["_id"]: {"count": r["count"], "leads": r["total_leads"]} for r in by_status},
        "total_enriched_via_batch": total_enriched,
        "estimated_savings_usd": round(estimated_savings, 2),
        "pending_jobs": batch_jobs.count_documents({"status": {"$in": [BatchJobStatus.QUEUED, BatchJobStatus.SUBMITTED, BatchJobStatus.IN_PROGRESS]}}),
    }


# ============== CLI INTERFACE ==============

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Batch Lead Enrichment (escalation ladder)")
        print("\nUsage:")
        print("  python batch_enrichment.py status       # Show batch stats")
        print("  python batch_enrichment.py run          # Run enrichment cycle")
        print("  python batch_enrichment.py check <id>   # Check specific job")
    
    elif sys.argv[1] == "status":
        stats = get_batch_stats()
        print("\n=== Batch Enrichment Stats ===")
        print(f"  Total Enriched via Batch: {stats['total_enriched_via_batch']}")
        print(f"  Estimated Savings:        ${stats['estimated_savings_usd']}")
        print(f"  Pending Jobs:             {stats['pending_jobs']}")
        print("\n  By Status:")
        for status, data in stats.get("by_status", {}).items():
            print(f"    {status}: {data['count']} jobs ({data['leads']} leads)")
    
    elif sys.argv[1] == "run":
        print("\nRunning batch enrichment cycle...")
        summary = run_batch_enrichment_cycle()
        print(f"\n  Completed Processed: {summary['completed_processed']}")
        print(f"  Batches Submitted:   {summary['batches_submitted']}")
        print(f"  Batches Checked:     {summary['batches_checked']}")
        if summary["errors"]:
            print(f"  Errors: {summary['errors']}")
    
    elif sys.argv[1] == "check" and len(sys.argv) > 2:
        job_id = sys.argv[2]
        print(f"\nChecking batch job: {job_id}")
        status = check_batch_status(job_id)
        for key, value in status.items():
            print(f"  {key}: {value}")
    
    else:
        print("Unknown command. Use 'status', 'run', or 'check <id>'")
