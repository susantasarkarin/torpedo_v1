"""
OPENAI BATCH API ENRICHMENT (Phase 4)
Uses OpenAI's Batch API for 50% cost reduction on lead enrichment.

How it works:
1. Queue leads for enrichment (stored in MongoDB)
2. Submit batch to OpenAI Batch API
3. Poll for completion (can take up to 24h, usually <1h)
4. Process results and update leads_enriched

Cost savings:
- Regular API: $0.15/$0.60 per 1M tokens (gpt-4o-mini)
- Batch API:   $0.075/$0.30 per 1M tokens (50% off)

Constraints:
- Batch results available within 24 hours
- Best for non-urgent enrichment
- Minimum batch size: 10 leads (to justify overhead)
"""

import os
import json
import time
import tempfile
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from pymongo import MongoClient
from dotenv import load_dotenv


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
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

# Minimum leads to justify batch API overhead
MIN_BATCH_SIZE = 10

# Maximum leads per batch (OpenAI limit is ~50k requests)
MAX_BATCH_SIZE = 1000

# Batch API model
BATCH_MODEL = "gpt-4o-mini"

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
        "batch_id": None,  # OpenAI batch ID
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


def submit_batch_job(job_id: str) -> Tuple[bool, str]:
    """
    Submit a queued batch job to OpenAI Batch API.
    
    Args:
        job_id: MongoDB batch job ID
        
    Returns:
        Tuple of (success, message/error)
    """
    from bson import ObjectId
    from .openai_wrapper import get_openai_client
    
    # Get job
    job = batch_jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        return False, "Job not found"
    
    if job["status"] != BatchJobStatus.QUEUED:
        return False, f"Job not in queued state: {job['status']}"
    
    # Get leads
    leads_raw = db['leads_raw']
    lead_ids = [ObjectId(lid) for lid in job["lead_ids"]]
    leads = list(leads_raw.find({"_id": {"$in": lead_ids}}))
    
    if not leads:
        batch_jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {"status": BatchJobStatus.FAILED, "error": "No leads found"}}
        )
        return False, "No leads found"
    
    # Create JSONL file for batch
    try:
        openai_client = get_openai_client()
        
        # Build batch requests
        batch_requests = []
        for lead in leads:
            user_prompt = f"""Enrich lead:
Name:{lead.get('name', '')} Title:{lead.get('title', '')} URL:{lead.get('linkedin_url', '')}
Context:{lead.get('snippet', '-')[:200]} Location:{lead.get('location', '-')} Company:{lead.get('company_name', '-')} Email:{lead.get('email', '-')}
Return JSON."""
            
            request = {
                "custom_id": str(lead["_id"]),
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": BATCH_MODEL,
                    "messages": [
                        {"role": "system", "content": BATCH_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 300,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }
            }
            batch_requests.append(request)
        
        # Write to temp JSONL file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            for req in batch_requests:
                f.write(json.dumps(req) + '\n')
            temp_path = f.name
        
        # Upload file to OpenAI
        with open(temp_path, 'rb') as f:
            file_response = openai_client.files.create(
                file=f,
                purpose="batch"
            )
        
        input_file_id = file_response.id
        
        # Clean up temp file
        os.unlink(temp_path)
        
        # Create batch
        batch_response = openai_client.batches.create(
            input_file_id=input_file_id,
            endpoint="/v1/chat/completions",
            completion_window="24h"
        )
        
        openai_batch_id = batch_response.id
        
        # Update job record
        batch_jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {
                "status": BatchJobStatus.SUBMITTED,
                "submitted_at": datetime.utcnow(),
                "batch_id": openai_batch_id,
                "input_file_id": input_file_id
            }}
        )
        
        print(f"[BatchAPI] Submitted batch {openai_batch_id} with {len(leads)} leads")
        return True, openai_batch_id
        
    except Exception as e:
        batch_jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {"status": BatchJobStatus.FAILED, "error": str(e)}}
        )
        return False, str(e)


def check_batch_status(job_id: str) -> Dict[str, Any]:
    """
    Check status of a submitted batch job.
    
    Args:
        job_id: MongoDB batch job ID
        
    Returns:
        Dict with status info
    """
    from bson import ObjectId
    from .openai_wrapper import get_openai_client
    
    job = batch_jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        return {"error": "Job not found"}
    
    if job["status"] == BatchJobStatus.QUEUED:
        return {"status": "queued", "message": "Batch not yet submitted"}
    
    if not job.get("batch_id"):
        return {"status": job["status"], "message": "No OpenAI batch ID"}
    
    try:
        openai_client = get_openai_client()
        batch = openai_client.batches.retrieve(job["batch_id"])
        
        status_map = {
            "validating": BatchJobStatus.SUBMITTED,
            "in_progress": BatchJobStatus.IN_PROGRESS,
            "completed": BatchJobStatus.COMPLETED,
            "failed": BatchJobStatus.FAILED,
            "cancelled": BatchJobStatus.CANCELLED,
            "expired": BatchJobStatus.FAILED,
        }
        
        new_status = status_map.get(batch.status, job["status"])
        
        # Update our record
        update = {"status": new_status}
        
        if batch.status == "completed" and batch.output_file_id:
            update["output_file_id"] = batch.output_file_id
            update["completed_at"] = datetime.utcnow()
        
        if batch.status == "failed":
            update["error"] = getattr(batch, 'errors', 'Unknown error')
        
        batch_jobs.update_one({"_id": ObjectId(job_id)}, {"$set": update})
        
        return {
            "status": new_status,
            "openai_status": batch.status,
            "request_counts": {
                "total": batch.request_counts.total if batch.request_counts else 0,
                "completed": batch.request_counts.completed if batch.request_counts else 0,
                "failed": batch.request_counts.failed if batch.request_counts else 0
            },
            "output_file_id": batch.output_file_id,
            "created_at": job.get("created_at"),
            "submitted_at": job.get("submitted_at")
        }
        
    except Exception as e:
        return {"status": job["status"], "error": str(e)}


def process_batch_results(job_id: str) -> Tuple[int, int]:
    """
    Process completed batch results and update leads_enriched.
    
    Args:
        job_id: MongoDB batch job ID
        
    Returns:
        Tuple of (success_count, failure_count)
    """
    from bson import ObjectId
    from .openai_wrapper import get_openai_client
    from .models import AIClassificationOutput, SeniorityLevel, Department, Persona, CompanySize, Region, BuyingRole, Gender
    
    job = batch_jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        return 0, 0
    
    if job["status"] != BatchJobStatus.COMPLETED:
        return 0, 0
    
    if not job.get("output_file_id"):
        return 0, 0
    
    try:
        openai_client = get_openai_client()
        
        # Download results file
        file_response = openai_client.files.content(job["output_file_id"])
        content = file_response.read().decode('utf-8')
        
        leads_raw = db['leads_raw']
        leads_enriched = db['leads_enriched']
        
        success_count = 0
        failure_count = 0
        
        for line in content.strip().split('\n'):
            if not line:
                continue
            
            result = json.loads(line)
            custom_id = result.get("custom_id")  # This is our lead_id
            
            if not custom_id:
                failure_count += 1
                continue
            
            response = result.get("response", {})
            
            if response.get("status_code") != 200:
                failure_count += 1
                # Log failure
                batch_results.insert_one({
                    "batch_job_id": job_id,
                    "lead_id": custom_id,
                    "success": False,
                    "error": response.get("error", {}).get("message", "Unknown error"),
                    "processed_at": datetime.utcnow()
                })
                continue
            
            # Parse response
            try:
                body = response.get("body", {})
                content = body.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                parsed = json.loads(content)
                
                # Get raw lead
                raw_lead = leads_raw.find_one({"_id": ObjectId(custom_id)})
                if not raw_lead:
                    failure_count += 1
                    continue
                
                # Create enriched lead
                enriched = {
                    "raw_lead_id": custom_id,
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
                    "enrichment_source": "batch_api"
                }
                
                # Upsert to leads_enriched
                leads_enriched.replace_one(
                    {"linkedin_url": enriched["linkedin_url"]},
                    enriched,
                    upsert=True
                )
                
                # Update raw lead status
                leads_raw.update_one(
                    {"_id": ObjectId(custom_id)},
                    {"$set": {"classification_status": "completed"}}
                )
                
                success_count += 1
                
                # Log success
                batch_results.insert_one({
                    "batch_job_id": job_id,
                    "lead_id": custom_id,
                    "success": True,
                    "confidence_score": enriched["confidence_score"],
                    "processed_at": datetime.utcnow()
                })
                
            except Exception as e:
                failure_count += 1
                batch_results.insert_one({
                    "batch_job_id": job_id,
                    "lead_id": custom_id,
                    "success": False,
                    "error": str(e),
                    "processed_at": datetime.utcnow()
                })
        
        # Update job with results
        batch_jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {
                "results_processed": success_count + failure_count,
                "success_count": success_count,
                "failure_count": failure_count
            }}
        )
        
        print(f"[BatchAPI] Processed batch {job_id}: {success_count} success, {failure_count} failed")
        return success_count, failure_count
        
    except Exception as e:
        print(f"[BatchAPI] Error processing batch {job_id}: {e}")
        return 0, 0


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
        print("OpenAI Batch API Enrichment")
        print("\nUsage:")
        print("  python batch_enrichment.py status       # Show batch stats")
        print("  python batch_enrichment.py run          # Run enrichment cycle")
        print("  python batch_enrichment.py check <id>   # Check specific job")
        print("\nCost savings: 50% vs regular API")
    
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
