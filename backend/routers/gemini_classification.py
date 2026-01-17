"""
GEMINI EMAIL CLASSIFICATION API ROUTER
=======================================

REST API endpoints for Gemini-powered email classification and lead extraction.
Uses Google Gemini 1.5 Flash with multi-key rotation for free tier usage.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Query, HTTPException, BackgroundTasks
from pydantic import BaseModel
from bson import ObjectId
import os

router = APIRouter(prefix="/gemini", tags=["Gemini Email Classification"])


# ============== MODELS ==============

class ClassifyEmailRequest(BaseModel):
    """Request to classify a single email"""
    email_id: str
    subject: Optional[str] = None
    body: Optional[str] = None
    from_email: Optional[str] = None
    to_email: Optional[str] = None
    extract_leads: bool = True


class ClassifyBatchRequest(BaseModel):
    """Request to classify multiple emails"""
    limit: int = 50
    internal_domains: Optional[List[str]] = None
    extract_leads: bool = True


class ExtractLeadRequest(BaseModel):
    """Request to extract lead from email"""
    email_id: str
    email_content: str
    sender_email: str


# ============== STATUS ENDPOINT ==============

@router.get("/status", response_model=Dict[str, Any])
async def get_gemini_status():
    """
    Get Gemini API status including key availability and usage stats.
    
    Returns:
        - total_keys: Number of configured API keys
        - available_keys: Number of keys available for use
        - keys: Details of each key's usage
        - gemini_available: Whether Gemini library is installed
    """
    try:
        try:
            from ..leads.gemini_wrapper import get_gemini_status as get_status
        except ImportError:
            from leads.gemini_wrapper import get_gemini_status as get_status
        
        return get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== CLASSIFICATION ENDPOINTS ==============

@router.post("/classify", response_model=Dict[str, Any])
async def classify_single_email(request: ClassifyEmailRequest):
    """
    Classify a single email using Gemini.
    
    If subject/body not provided, fetches from database using email_id.
    Optionally extracts lead information for sales-qualified emails.
    """
    try:
        try:
            from ..leads.gemini_email_classifier import classify_email_with_gemini
            from pymongo import MongoClient
        except ImportError:
            from leads.gemini_email_classifier import classify_email_with_gemini
            from pymongo import MongoClient
        
        # If email details not provided, fetch from database
        subject = request.subject
        body = request.body
        from_email = request.from_email
        to_email = request.to_email
        
        if not subject or not body or not from_email:
            mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
            client = MongoClient(mongo_uri)
            db = client['torpedo_gmail']
            
            try:
                email = db['email_metadata'].find_one({"_id": ObjectId(request.email_id)})
            except:
                email = None
            
            if not email:
                raise HTTPException(status_code=404, detail="Email not found")
            
            subject = subject or email.get("subject", "")
            body = body or email.get("body_plain", "") or email.get("body_html", "")
            from_email = from_email or email.get("from_email", "") or email.get("sender", "")
            to_email = to_email or email.get("to_email", "")
        
        result = classify_email_with_gemini(
            email_id=request.email_id,
            subject=subject,
            body=body,
            from_email=from_email,
            to_email=to_email,
            extract_leads=request.extract_leads,
            source="api"
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/classify-batch", response_model=Dict[str, Any])
async def classify_batch_emails(
    request: ClassifyBatchRequest,
    background_tasks: BackgroundTasks
):
    """
    Start batch classification of ALL pending emails in the background.
    
    Uses OpenAI GPT-4o-mini for Tier 1 classification.
    Loops until all unclassified emails are processed.
    """
    try:
        try:
            from ..leads.email_classifier import classify_all_pending_emails
        except ImportError:
            from leads.email_classifier import classify_all_pending_emails
        
        # Run in background - will loop until all emails are classified
        background_tasks.add_task(
            classify_all_pending_emails,
            batch_size=min(request.limit, 100),  # Process in batches of up to 100
            max_batches=None,  # No limit - process ALL
            run_tier2=True,
            delay_between_batches=2.0,
            source="api"
        )
        
        return {
            "success": True,
            "message": f"Started background classification - will process ALL unclassified emails in batches of {min(request.limit, 100)}",
            "note": "Using OpenAI GPT-4o-mini for classification"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/classify-batch-sync", response_model=Dict[str, Any])
async def classify_batch_emails_sync(request: ClassifyBatchRequest):
    """
    Classify ALL pending emails synchronously (waits for completion).
    
    Uses unified GPT-4o-mini classification with summary + lead extraction.
    Loops until all unclassified emails are processed.
    
    Warning: This can take a long time for large email volumes.
    Use /classify-batch for background processing.
    """
    try:
        try:
            from ..leads.email_classifier import classify_all_pending_emails
        except ImportError:
            from leads.email_classifier import classify_all_pending_emails
        
        result = classify_all_pending_emails(
            batch_size=min(request.limit, 100),
            max_batches=None,  # Process ALL
            delay_between_batches=1.0,
            source="api"
        )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear-classifications", response_model=Dict[str, Any])
async def clear_all_classifications():
    """
    Clear ALL AI classifications from emails.
    Use before re-running classification with new settings.
    """
    try:
        try:
            from ..leads.email_classifier import clear_all_classifications
        except ImportError:
            from leads.email_classifier import clear_all_classifications
        
        count = clear_all_classifications()
        return {"success": True, "cleared_count": count}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=Dict[str, Any])
async def get_classification_stats():
    """
    Get current classification statistics.
    """
    try:
        try:
            from ..leads.email_classifier import get_classification_stats
        except ImportError:
            from leads.email_classifier import get_classification_stats
        
        return get_classification_stats()
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== LEAD EXTRACTION ENDPOINTS ==============

@router.post("/extract-lead", response_model=Dict[str, Any])
async def extract_lead_from_email(request: ExtractLeadRequest):
    """
    Extract lead information from email content using Gemini.
    Creates a lead in the Sales > Leads section.
    """
    try:
        try:
            from ..leads.gemini_wrapper import gemini_extract_lead
            from ..leads.gemini_email_classifier import create_lead_from_email, extract_name_parts, extract_domain_from_email
        except ImportError:
            from leads.gemini_wrapper import gemini_extract_lead
            from leads.gemini_email_classifier import create_lead_from_email, extract_name_parts, extract_domain_from_email
        
        # Extract using Gemini
        result = gemini_extract_lead(
            email_content=request.email_content,
            sender_email=request.sender_email,
            source="api"
        )
        
        if not result["success"]:
            return {"success": False, "error": result.get("error", "Extraction failed")}
        
        parsed = result.get("parsed", {})
        if not parsed:
            return {"success": False, "error": "No lead information extracted"}
        
        # Create lead
        full_name = parsed.get("full_name", "")
        first_name = parsed.get("first_name", "")
        last_name = parsed.get("last_name", "")
        
        if not first_name and not last_name and full_name:
            first_name, last_name = extract_name_parts(full_name)
        
        email = parsed.get("email", "") or request.sender_email
        
        lead_result = create_lead_from_email(
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            email=email,
            website=parsed.get("website", ""),
            domain=parsed.get("domain", "") or extract_domain_from_email(email),
            source_email_id=request.email_id,
            title=parsed.get("title", ""),
            company_name=parsed.get("company_name", ""),
            phone=parsed.get("phone", ""),
            linkedin_url=parsed.get("linkedin_url", ""),
            confidence=parsed.get("confidence", 0.7)
        )
        
        return {
            "success": lead_result.get("success", False),
            "action": lead_result.get("action"),
            "lead_id": lead_result.get("lead_id"),
            "extracted_info": parsed
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== STATS & LEADS ENDPOINTS ==============

@router.get("/stats", response_model=Dict[str, Any])
async def get_classification_stats():
    """
    Get email classification statistics and Gemini usage stats.
    """
    try:
        try:
            from ..leads.gemini_email_classifier import get_classification_stats
        except ImportError:
            from leads.gemini_email_classifier import get_classification_stats
        
        return get_classification_stats()
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/extracted-leads", response_model=Dict[str, Any])
async def get_extracted_leads(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = None
):
    """
    Get leads extracted from emails by Gemini.
    These leads appear in the Sales > Leads section.
    """
    try:
        try:
            from ..leads.gemini_email_classifier import get_extracted_leads
        except ImportError:
            from leads.gemini_email_classifier import get_extracted_leads
        
        return get_extracted_leads(page=page, limit=limit, status=status)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== CONFIGURATION ENDPOINTS ==============

@router.get("/config", response_model=Dict[str, Any])
async def get_gemini_config():
    """
    Get Gemini configuration including model info and rate limits.
    """
    try:
        try:
            from ..leads.gemini_wrapper import (
                DEFAULT_GEMINI_MODEL, GEMINI_FLASH_MODEL, GEMINI_PRO_MODEL,
                FREE_TIER_RPD, FREE_TIER_RPM, FREE_TIER_TPM,
                GEMINI_AVAILABLE
            )
        except ImportError:
            from leads.gemini_wrapper import (
                DEFAULT_GEMINI_MODEL, GEMINI_FLASH_MODEL, GEMINI_PRO_MODEL,
                FREE_TIER_RPD, FREE_TIER_RPM, FREE_TIER_TPM,
                GEMINI_AVAILABLE
            )
        
        return {
            "gemini_available": GEMINI_AVAILABLE,
            "default_model": DEFAULT_GEMINI_MODEL,
            "available_models": [GEMINI_FLASH_MODEL, GEMINI_PRO_MODEL],
            "free_tier_limits": {
                "requests_per_day": FREE_TIER_RPD,
                "requests_per_minute": FREE_TIER_RPM,
                "tokens_per_minute": FREE_TIER_TPM
            },
            "lead_extraction": {
                "enabled": True,
                "fields_extracted": [
                    "full_name", "first_name", "last_name",
                    "email", "website", "domain",
                    "title", "company_name", "phone", "linkedin_url"
                ]
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== USAGE LOGS ==============

@router.get("/usage-logs", response_model=Dict[str, Any])
async def get_usage_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    key_id: Optional[str] = None,
    endpoint: Optional[str] = None
):
    """
    Get Gemini API usage logs for monitoring and debugging.
    """
    try:
        from pymongo import MongoClient
        
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri)
        db = client['torpedo_gmail']
        
        query = {}
        if key_id:
            query["key_id"] = key_id
        if endpoint:
            query["endpoint"] = endpoint
        
        skip = (page - 1) * limit
        
        logs = list(
            db['gemini_usage_logs']
            .find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(limit)
        )
        
        total = db['gemini_usage_logs'].count_documents(query)
        
        # Convert ObjectId
        for log in logs:
            log["_id"] = str(log["_id"])
        
        # Get aggregated stats
        pipeline = [
            {"$match": query} if query else {"$match": {}},
            {
                "$group": {
                    "_id": "$key_id",
                    "total_requests": {"$sum": 1},
                    "total_tokens": {"$sum": "$total_tokens"},
                    "successful": {"$sum": {"$cond": ["$success", 1, 0]}},
                    "failed": {"$sum": {"$cond": ["$success", 0, 1]}}
                }
            }
        ]
        
        stats_by_key = list(db['gemini_usage_logs'].aggregate(pipeline))
        
        return {
            "logs": logs,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit,
            "stats_by_key": stats_by_key
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
