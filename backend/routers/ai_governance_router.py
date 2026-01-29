"""
AI GOVERNANCE API ROUTES
========================
FastAPI routes for AI operations with strict governance enforcement.

All AI operations go through this router, ensuring:
- Gemini: Only for email classification/summarization/lead extraction
- OpenAI: Only for web search and external lead discovery
- No DeepSeek (completely removed)
- Daily limits enforced
- One classification per email
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from backend.ai_governance import (
    classify_email,
    summarize_email,
    extract_leads_from_email,
    web_search,
    discover_leads_external,
    get_gemini_gateway,
    get_openai_gateway,
    GeminiDailyLimitExceeded,
    EmailAlreadyClassified,
    OpenAIWebSearchOnly,
)
from backend.ai_governance.governance_checks import (
    get_governance_status,
    get_gemini_daily_usage,
    check_gemini_daily_limit,
    validate_no_deepseek,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/ai", tags=["AI Governance"])


# ============== REQUEST/RESPONSE MODELS ==============

class ClassifyEmailRequest(BaseModel):
    email_id: str = Field(..., description="Unique email identifier")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body content", max_length=10000)
    from_email: str = Field(..., description="Sender email address")


class SummarizeEmailRequest(BaseModel):
    email_id: str = Field(..., description="Unique email identifier")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body content", max_length=10000)
    max_length: int = Field(200, description="Maximum summary length", ge=50, le=500)


class ExtractLeadsRequest(BaseModel):
    email_id: str = Field(..., description="Unique email identifier")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body content", max_length=10000)
    from_email: str = Field(..., description="Sender email address")


class WebSearchRequest(BaseModel):
    query: str = Field(..., description="Search query")
    num_results: int = Field(10, description="Maximum results", ge=1, le=50)


class ExternalLeadDiscoveryRequest(BaseModel):
    company_name: Optional[str] = Field(None, description="Target company name")
    industry: Optional[str] = Field(None, description="Target industry")
    location: Optional[str] = Field(None, description="Geographic location")
    job_titles: Optional[List[str]] = Field(None, description="Target job titles")


class GovernanceStatusResponse(BaseModel):
    date: str
    gemini: Dict[str, Any]
    deepseek: Dict[str, str]
    openai: Dict[str, Any]
    enforcement: Dict[str, bool]


# ============== GOVERNANCE STATUS ENDPOINTS ==============

@router.get("/status", response_model=GovernanceStatusResponse)
async def get_ai_governance_status():
    """
    Get current AI governance status.
    
    Returns:
        - Gemini usage (current/remaining/limit)
        - DeepSeek status (REMOVED)
        - OpenAI allowed uses
        - Enforcement rules
    """
    return get_governance_status()


@router.get("/gemini/usage")
async def get_gemini_usage():
    """
    Get current Gemini daily usage statistics.
    
    Returns:
        - current_usage: Requests made today
        - remaining: Requests remaining today
        - daily_limit: Hard limit (7000)
    """
    current, remaining = get_gemini_daily_usage()
    return {
        "current_usage": current,
        "remaining": remaining,
        "daily_limit": 7000,
        "percentage_used": round((current / 7000) * 100, 2),
        "date": datetime.utcnow().date().isoformat()
    }


@router.get("/health")
async def ai_health_check():
    """
    Health check for AI services.
    
    Validates:
    - No DeepSeek references
    - Gemini daily limit not exceeded
    """
    try:
        validate_no_deepseek()
        gemini_ok = check_gemini_daily_limit()
        
        return {
            "status": "healthy" if gemini_ok else "degraded",
            "gemini_available": gemini_ok,
            "deepseek_removed": True,
            "openai_available": True,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


# ============== GEMINI ENDPOINTS (Email Intelligence) ==============

@router.post("/gemini/classify")
async def classify_email_endpoint(request: ClassifyEmailRequest):
    """
    Classify an email using Gemini.
    
    GOVERNANCE ENFORCED:
    - Email can only be classified ONCE
    - Daily limit (7000) checked
    - No retries on failure
    
    Allowed for: Email classification ONLY
    """
    try:
        result = classify_email(
            email_id=request.email_id,
            subject=request.subject,
            body=request.body[:3000],  # Limit body size
            from_email=request.from_email,
            source="api"
        )
        
        return {
            "email_id": result.email_id,
            "category": result.category,
            "confidence": result.confidence,
            "summary": result.summary,
            "intent": result.intent,
            "priority": result.priority,
            "action_required": result.action_required,
            "classified_at": result.classified_at,
            "success": result.success
        }
        
    except EmailAlreadyClassified as e:
        raise HTTPException(
            status_code=409,
            detail=str(e)
        )
    except GeminiDailyLimitExceeded as e:
        raise HTTPException(
            status_code=429,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Classification failed: {str(e)}"
        )


@router.post("/gemini/summarize")
async def summarize_email_endpoint(request: SummarizeEmailRequest):
    """
    Summarize an email using Gemini.
    
    Allowed for: Email summarization ONLY
    """
    try:
        result = summarize_email(
            email_id=request.email_id,
            subject=request.subject,
            body=request.body[:3000],
            max_length=request.max_length
        )
        
        return result
        
    except GeminiDailyLimitExceeded as e:
        raise HTTPException(
            status_code=429,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Summarization failed: {str(e)}"
        )


@router.post("/gemini/extract-leads")
async def extract_leads_endpoint(request: ExtractLeadsRequest):
    """
    Extract leads from an email using Gemini.
    
    NOTE: This is for leads FROM existing email threads only.
    For external lead discovery, use /openai/discover-leads
    
    Allowed for: Lead extraction from emails ONLY
    """
    try:
        result = extract_leads_from_email(
            email_id=request.email_id,
            subject=request.subject,
            body=request.body[:3000],
            from_email=request.from_email
        )
        
        return {
            "email_id": result.email_id,
            "leads": result.leads,
            "extracted_at": result.extracted_at,
            "success": result.success,
            "error": result.error
        }
        
    except GeminiDailyLimitExceeded as e:
        raise HTTPException(
            status_code=429,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Lead extraction failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Lead extraction failed: {str(e)}"
        )


# ============== OPENAI ENDPOINTS (Web Search Only) ==============

@router.post("/openai/web-search")
async def web_search_endpoint(request: WebSearchRequest):
    """
    Perform web search using OpenAI.
    
    This is one of the ONLY allowed uses of OpenAI.
    
    FORBIDDEN: Using OpenAI for email classification/summarization
    """
    try:
        result = web_search(
            query=request.query,
            num_results=request.num_results
        )
        
        return result
        
    except OpenAIWebSearchOnly as e:
        raise HTTPException(
            status_code=403,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Web search failed: {str(e)}"
        )


@router.post("/openai/discover-leads")
async def discover_leads_endpoint(request: ExternalLeadDiscoveryRequest):
    """
    Discover leads from external sources using OpenAI.
    
    This is for EXTERNAL lead generation (not from emails).
    For leads from emails, use /gemini/extract-leads
    
    FORBIDDEN: Using this for email-based operations
    """
    try:
        result = discover_leads_external(
            company_name=request.company_name,
            industry=request.industry,
            location=request.location,
            job_titles=request.job_titles
        )
        
        return result
        
    except OpenAIWebSearchOnly as e:
        raise HTTPException(
            status_code=403,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Lead discovery failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Lead discovery failed: {str(e)}"
        )


# ============== FORBIDDEN OPERATIONS ==============

@router.post("/openai/classify")
async def forbidden_openai_classify():
    """
    FORBIDDEN: OpenAI cannot be used for email classification.
    
    Use /gemini/classify instead.
    """
    raise HTTPException(
        status_code=403,
        detail="FORBIDDEN: OpenAI cannot be used for email classification. "
               "Use /api/v2/ai/gemini/classify instead."
    )


@router.post("/openai/summarize")
async def forbidden_openai_summarize():
    """
    FORBIDDEN: OpenAI cannot be used for email summarization.
    
    Use /gemini/summarize instead.
    """
    raise HTTPException(
        status_code=403,
        detail="FORBIDDEN: OpenAI cannot be used for email summarization. "
               "Use /api/v2/ai/gemini/summarize instead."
    )


@router.post("/deepseek/{path:path}")
async def forbidden_deepseek(path: str):
    """
    FORBIDDEN: DeepSeek has been completely removed.
    """
    raise HTTPException(
        status_code=410,  # Gone
        detail="DeepSeek has been COMPLETELY REMOVED from this codebase. "
               "Use /api/v2/ai/gemini/* for email operations or "
               "/api/v2/ai/openai/* for web search."
    )
