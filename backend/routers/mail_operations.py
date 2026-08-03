"""
Mail Operations Router - Endpoints for mail segregation, summaries, and contact extraction

Provides API endpoints for:
- Mail segregation and categorization
- Mail summaries generation
- Contact information extraction
- Segregation statistics
"""

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Query, Body
from pydantic import BaseModel, Field
from datetime import datetime

from backend.agents.mail_segregation_agent import (
    get_mail_segregation_agent,
    SegmentationStrategy,
    ExtractedContact
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/mail",
    tags=["mail"]
)


# ============================================
# Pydantic Models
# ============================================

class SegregateRequest(BaseModel):
    """Request model for mail segregation"""
    strategy: str = Field(
        default="category",
        description="Segregation strategy: category, sender_domain, priority, intent, engagement, custom"
    )
    batch_size: int = Field(default=100, description="Number of emails to process per batch")
    force_rescan: bool = Field(default=False, description="Force rescan of already segregated emails")


class ContactExtractionRequest(BaseModel):
    """Request model for contact extraction"""
    email_id: Optional[str] = Field(None, description="Specific email ID to extract from")
    segment_name: Optional[str] = Field(None, description="Extract from all emails in segment")
    batch_size: int = Field(default=50, description="Batch size for processing")


class MailSummaryRequest(BaseModel):
    """Request model for mail summary"""
    segment_name: Optional[str] = Field(None, description="Segment to summarize")
    date_from: Optional[str] = Field(None, description="Start date (ISO format)")
    date_to: Optional[str] = Field(None, description="End date (ISO format)")


class SegregationResponse(BaseModel):
    """Response model for segregation"""
    success: bool
    total_emails: int
    processed: int
    failed: int
    strategy: str
    segment_summaries: List[Dict[str, Any]] = []
    timestamp: str


class ContactExtractionResponse(BaseModel):
    """Response model for contact extraction"""
    success: bool
    total_processed: int
    extracted: int
    failed: int
    timestamp: str


class MailSummaryResponse(BaseModel):
    """Response model for mail summary"""
    success: bool
    segment_id: str
    segment_name: str
    total_emails: int
    key_topics: List[str]
    sentiment_distribution: Dict[str, int]
    top_senders: List[tuple]
    action_items: List[str]
    summary_text: str
    created_at: str


# ============================================
# Endpoints
# ============================================

@router.post("/segregate")
async def segregate_emails(
    request: Request,
    payload: SegregateRequest
) -> Dict[str, Any]:
    """
    Segregate all emails in mail_pool using specified strategy
    
    Strategies:
    - category: Categorize by business type (sales, support, etc.)
    - sender_domain: Group by sender company domain
    - priority: Classify by priority level
    - intent: Determine business intent
    - engagement: Analyze engagement level
    - custom: Custom Gemini-based segmentation
    
    Returns: Segregation statistics and summaries
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        agent = get_mail_segregation_agent()
        
        # Validate strategy
        try:
            strategy = SegmentationStrategy(payload.strategy)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid strategy. Must be one of: {[s.value for s in SegmentationStrategy]}"
            )
        
        # Run segregation (sync, rule-based)
        result = agent.segregate_all_emails(
            strategy=strategy,
            batch_size=payload.batch_size,
            force_rescan=payload.force_rescan
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error segregating emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/segregation-stats")
async def get_segregation_stats(request: Request) -> Dict[str, Any]:
    """
    Get statistics about email segregation progress
    
    Returns:
    - total_emails: Total emails in pool
    - segregated_emails: Number of segregated emails
    - pending_emails: Remaining to segregate
    - segregation_percentage: Progress percentage
    - segment_breakdown: Count per segment
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        agent = get_mail_segregation_agent()
        stats = agent.get_segregation_stats()
        
        return stats
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting segregation stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract-contacts")
async def extract_contacts(
    request: Request,
    payload: ContactExtractionRequest
) -> Dict[str, Any]:
    """
    Extract contact information from emails using Gemini
    
    Can extract:
    - Name and email address
    - Phone number
    - Company and job title
    - LinkedIn profile
    - Website and social media handles
    - Physical address
    
    Either provide email_id for single email or segment_name for batch extraction
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        agent = get_mail_segregation_agent()
        
        if payload.email_id:
            # Extract from single email
            contact = agent.extract_contact_information(payload.email_id)
            
            if contact:
                return {
                    "success": True,
                    "contact": {
                        "name": contact.name,
                        "email": contact.email,
                        "phone": contact.phone,
                        "company": contact.company,
                        "title": contact.title,
                        "linkedin": contact.linkedin,
                        "website": contact.website,
                        "address": contact.address,
                        "social_handles": contact.social_handles,
                        "extracted_at": contact.extracted_at
                    }
                }
            else:
                return {"success": False, "error": "Email not found"}
        else:
            # Extract from all emails
            result = agent.extract_all_contacts(payload.batch_size)
            return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting contacts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/summary")
async def generate_mail_summary(
    request: Request,
    payload: MailSummaryRequest
) -> Dict[str, Any]:
    """
    Generate AI-powered summary of email segment
    
    Provides:
    - Key topics and themes
    - Sentiment distribution
    - Top senders
    - Action items
    - Professional summary text
    
    Filter by segment_name, date range, or get overall summary
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        agent = get_mail_segregation_agent()
        
        summary = agent.generate_mail_summary(
            segment_name=payload.segment_name,
            date_from=payload.date_from,
            date_to=payload.date_to
        )
        
        if summary:
            return {
                "success": True,
                "segment_id": summary.segment_id,
                "segment_name": summary.segment_name,
                "total_emails": summary.total_emails,
                "key_topics": summary.key_topics,
                "sentiment_distribution": summary.sentiment_distribution,
                "top_senders": summary.top_senders,
                "action_items": summary.action_items,
                "summary_text": summary.summary_text,
                "created_at": summary.created_at
            }
        else:
            return {"success": False, "error": "No emails found for summary"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/extracted-contacts")
async def get_extracted_contacts(
    request: Request,
    limit: int = Query(50, description="Limit number of contacts returned"),
    skip: int = Query(0, description="Skip N contacts"),
    company: Optional[str] = Query(None, description="Filter by company")
) -> Dict[str, Any]:
    """
    Get extracted contacts with optional filtering
    
    Can filter by:
    - Company name
    - Pagination (limit, skip)
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        from backend.agents.mail_segregation_agent import email_leads
        
        # Build query
        query = {}
        if company:
            query["company"] = {"$regex": company, "$options": "i"}
        
        # Get contacts
        contacts = list(email_leads.find(query).skip(skip).limit(limit))
        total = email_leads.count_documents(query)
        
        return {
            "success": True,
            "total": total,
            "contacts": [
                {
                    "id": str(c.get("_id", "")),
                    "name": c.get("name", ""),
                    "email": c.get("email", ""),
                    "phone": c.get("phone", ""),
                    "company": c.get("company", ""),
                    "title": c.get("title", ""),
                    "linkedin": c.get("linkedin", ""),
                    "website": c.get("website", ""),
                    "address": c.get("address", ""),
                    "social_handles": c.get("social_handles", {}),
                    "extracted_at": c.get("extracted_at", "")
                }
                for c in contacts
            ]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting contacts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# AI Mail Desk (Claude-backed pipeline)
# ============================================

class AIProcessRequest(BaseModel):
    """Request model for on-demand AI mail processing"""
    email_id: Optional[str] = Field(None, description="Process one specific email")
    limit: int = Field(default=50, ge=1, le=200, description="Batch size when no email_id given")


@router.post("/ai-process")
async def ai_process_mail(request: Request, body: AIProcessRequest = Body(default=AIProcessRequest())) -> Dict[str, Any]:
    """
    Run the AI mail-desk pipeline (summary, classification, contact
    extraction, RFQ -> CRM spine + draft finance estimate, follow-up draft).

    - With email_id: process that email synchronously and return its analysis.
    - Without: enqueue a background batch over unanalyzed emails.
    """
    try:
        from bson import ObjectId
        try:
            from sales.mail_pool_ai import process_email, MAIL_DB, MAIL_COLLECTION
            from db_pools import get_db
        except ImportError:
            from backend.sales.mail_pool_ai import process_email, MAIL_DB, MAIL_COLLECTION
            from backend.db_pools import get_db

        if body.email_id:
            col = get_db(MAIL_DB)[MAIL_COLLECTION]
            try:
                doc = col.find_one({"_id": ObjectId(body.email_id)})
            except Exception:
                doc = col.find_one({"_id": body.email_id})
            if not doc:
                raise HTTPException(status_code=404, detail="Email not found in mail pool")
            result = process_email(doc)
            if not result.get("success"):
                raise HTTPException(status_code=502, detail=result.get("error", "AI analysis failed"))
            return {"success": True, "mode": "single", "analysis": result["analysis"]}

        try:
            from tasks.mail_pool_ai_tasks import process_mail_pool_batch
        except ImportError:
            from backend.tasks.mail_pool_ai_tasks import process_mail_pool_batch
        task = process_mail_pool_batch.delay(limit=body.limit)
        return {"success": True, "mode": "batch", "task_id": task.id,
                "message": f"AI processing enqueued for up to {body.limit} emails"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI mail processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/followup-drafts")
async def get_followup_drafts(
    status: Optional[str] = Query("draft", description="Filter by status: draft|sent|dismissed"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """List AI-generated follow-up drafts awaiting human review."""
    try:
        try:
            from db_pools import get_db
            from sales.mail_pool_ai import FOLLOWUP_COLLECTION
        except ImportError:
            from backend.db_pools import get_db
            from backend.sales.mail_pool_ai import FOLLOWUP_COLLECTION
        col = get_db("email_automation")[FOLLOWUP_COLLECTION]
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        drafts = []
        for d in col.find(query).sort("created_at", -1).skip(skip).limit(limit):
            d["_id"] = str(d["_id"])
            drafts.append(d)
        return {"success": True, "total": col.count_documents(query), "drafts": drafts}
    except Exception as e:
        logger.error(f"Error listing follow-up drafts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-stats")
async def get_mail_ai_stats() -> Dict[str, Any]:
    """
    Mail-desk operational stats: processed / prefiltered / pending counts, the
    rule-vs-AI prefilter disagreement rate (last 7 days), and cumulative
    Bedrock token usage by model (last 7 days) for cost auditing.
    """
    try:
        try:
            from sales.mail_pool_ai import ai_stats
        except ImportError:
            from backend.sales.mail_pool_ai import ai_stats
        return {"success": True, **ai_stats()}
    except Exception as e:
        logger.error(f"Error computing mail AI stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
