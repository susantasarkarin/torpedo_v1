"""
EMAIL CLASSIFICATION API ROUTER
================================

REST API endpoints for email classification operations.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Query, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from bson import ObjectId
from pymongo import MongoClient

import os


router = APIRouter(prefix="/classification", tags=["Email Classification"])


# ============== MODELS ==============

class CreateJobRequest(BaseModel):
    batch_size: int = 100
    max_emails: Optional[int] = None
    use_escalation: bool = True
    cost_limit_usd: Optional[float] = None


class RunJobRequest(BaseModel):
    job_id: Optional[str] = None
    resume: bool = True
    dry_run: bool = False


# ============== DATABASE ==============

def get_db():
    """Get MongoDB database instance"""
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri)
    return client['email_automation']


def get_classifier(db = Depends(get_db)):
    """Get historical classifier instance"""
    from ..email_sync.historical_classifier import HistoricalClassifier
    return HistoricalClassifier(db)


# ============== ENDPOINTS ==============

@router.get("/estimate", response_model=Dict[str, Any])
async def estimate_classification_cost(
    classifier = Depends(get_classifier)
):
    """
    Estimate the cost to classify all unclassified emails.
    
    Returns counts and cost estimates based on a sample analysis.
    """
    estimate = classifier.estimate_classification_cost()
    return estimate


@router.post("/jobs", response_model=Dict[str, Any])
async def create_classification_job(
    request: CreateJobRequest,
    classifier = Depends(get_classifier)
):
    """
    Create a new classification job.
    
    The job can be run immediately or later via the run endpoint.
    """
    job_id = classifier.create_job(
        batch_size=request.batch_size,
        max_emails=request.max_emails,
        use_escalation=request.use_escalation,
        cost_limit_usd=request.cost_limit_usd
    )
    
    return {"success": True, "job_id": job_id}


@router.post("/jobs/run", response_model=Dict[str, Any])
async def run_classification_job(
    request: RunJobRequest,
    background_tasks: BackgroundTasks,
    classifier = Depends(get_classifier),
    db = Depends(get_db)
):
    """
    Run a classification job in the background.
    
    If job_id is provided, resumes that job. Otherwise creates a new one.
    """
    def run_job():
        # Need to recreate classifier in background thread
        from ..email_sync.historical_classifier import HistoricalClassifier
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri)
        bg_classifier = HistoricalClassifier(client['email_automation'])
        
        try:
            bg_classifier.run(
                job_id=request.job_id,
                resume=request.resume,
                dry_run=request.dry_run
            )
        except Exception as e:
            import logging
            logging.error(f"Classification job failed: {e}")
    
    background_tasks.add_task(run_job)
    
    return {
        "success": True,
        "message": "Job started in background",
        "job_id": request.job_id
    }


@router.get("/jobs", response_model=Dict[str, Any])
async def list_classification_jobs(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db = Depends(get_db)
):
    """List classification jobs"""
    query = {}
    if status:
        query["status"] = status
    
    total = db["classification_jobs"].count_documents(query)
    skip = (page - 1) * page_size
    
    jobs = list(db["classification_jobs"].find(query).sort("created_at", -1).skip(skip).limit(page_size))
    
    for j in jobs:
        j["id"] = str(j.pop("_id"))
    
    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/jobs/{job_id}", response_model=Dict[str, Any])
async def get_job_status(
    job_id: str,
    classifier = Depends(get_classifier)
):
    """Get status of a classification job"""
    status = classifier.get_job_status(job_id)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
    return status


@router.post("/jobs/{job_id}/pause", response_model=Dict[str, Any])
async def pause_job(
    job_id: str,
    classifier = Depends(get_classifier)
):
    """Pause a running classification job"""
    success = classifier.pause_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Job not found or not running")
    return {"success": True, "message": "Job paused"}


@router.get("/stats", response_model=Dict[str, Any])
async def get_classification_stats(
    classifier = Depends(get_classifier)
):
    """Get overall classification statistics"""
    return classifier.get_classification_stats()


@router.post("/route-emails", response_model=Dict[str, Any])
async def route_classified_emails(
    limit: int = Query(100, ge=1, le=1000),
    db = Depends(get_db)
):
    """Route classified but unrouted emails to departments"""
    from ..email_sync.department_router import DepartmentRouter
    
    router = DepartmentRouter(db)
    result = router.route_unrouted_emails(limit=limit)
    
    return result


@router.get("/categories", response_model=Dict[str, Any])
async def list_categories():
    """List all available email categories"""
    from ..email_sync.historical_classifier import B2BEmailCategory
    
    categories = {
        "sales": [
            "inbound_lead", "meeting_request", "demo_request", "pricing_inquiry",
            "interested", "not_interested"
        ],
        "operations": [
            "rfq_request", "quote_response", "negotiation", "contract_discussion",
            "purchase_order", "delivery_update", "vendor_communication"
        ],
        "finance": [
            "invoice", "payment_confirmation", "payment_reminder", "billing_dispute"
        ],
        "support": [
            "support_request", "complaint", "feedback", "onboarding"
        ],
        "low_priority": [
            "newsletter", "promotional", "spam", "social_notification",
            "out_of_office", "bounce", "unsubscribe", "auto_reply"
        ],
        "other": ["internal", "other", "uncategorized"]
    }
    
    return {"categories": categories}


# P0.19: AI Status Endpoint
@router.get("/ai/status", response_model=Dict[str, Any])
async def get_ai_status():
    """
    Get current AI classification status and kill switch state.
    P0.19: Provides visibility into AI system status.
    """
    disable_ai = os.getenv("DISABLE_AI_CALLS", "").lower() in ("true", "1", "yes")
    disable_openai = os.getenv("DISABLE_OPENAI_CALLS", "").lower() in ("true", "1", "yes")
    
    # Get usage stats from the last 24 hours if available
    usage_stats = {}
    try:
        from ..leads.openai_wrapper import token_logger
        usage_stats = token_logger.get_usage_summary(hours=24)
    except Exception as e:
        usage_stats = {"error": str(e)}
    
    return {
        "ai_enabled": not (disable_ai or disable_openai),
        "kill_switch_active": disable_ai or disable_openai,
        "environment": {
            "DISABLE_AI_CALLS": os.getenv("DISABLE_AI_CALLS", "false"),
            "DISABLE_OPENAI_CALLS": os.getenv("DISABLE_OPENAI_CALLS", "false")
        },
        "usage_stats_24h": usage_stats
    }
