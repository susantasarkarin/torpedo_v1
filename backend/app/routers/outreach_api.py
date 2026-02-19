"""
Torpedo Outreach API Routes.

Main REST API for the AI-powered cold outreach system.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, EmailStr
from openai import AsyncOpenAI
import os

from ..services.outreach import (
    OutreachOrchestrator,
    CompanyData,
    LeadIntelligenceService,
    EmailGeneratorService,
    ReplyHandlerService,
    EmailGenerationRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/outreach", tags=["Outreach"])


# =============================================================================
# Request Models
# =============================================================================

class ProcessLeadRequest(BaseModel):
    """Request to process a new lead."""
    company_name: str
    contact_name: str
    contact_email: EmailStr
    contact_role: str = ""
    website_text: str = ""
    industry: str = ""
    company_size: str = ""
    trigger_event: str = ""
    campaign_positioning: str = "Sales automation and outreach optimization"
    cta_style: str = "soft"


class ProcessReplyRequest(BaseModel):
    """Request to process an incoming reply."""
    from_email: EmailStr
    contact_name: str
    company_name: str
    subject: str
    body: str


class GenerateFollowUpRequest(BaseModel):
    """Request to generate a follow-up email."""
    contact_email: EmailStr
    contact_name: str
    company_name: str
    days_since_sent: int
    open_count: int = 0


# =============================================================================
# Dependencies
# =============================================================================

async def get_ai_client():
    """Get OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")
    return AsyncOpenAI(api_key=api_key)


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/process-lead")
async def process_lead(
    request: ProcessLeadRequest,
    background_tasks: BackgroundTasks,
    ai_client = Depends(get_ai_client)
):
    """
    Process a new lead through the complete outreach pipeline.
    
    Steps:
    1. Extract AI intelligence
    2. Score the lead
    3. Generate personalized email
    4. Check for spam
    5. Return result
    """
    try:
        logger.info(f"Processing lead: {request.contact_email}")
        
        # Build company data
        company_data = CompanyData(
            company_name=request.company_name,
            website_text=request.website_text,
            industry=request.industry,
            company_size=request.company_size,
            trigger_event=request.trigger_event
        )
        
        # Initialize services
        intelligence_service = LeadIntelligenceService(ai_client)
        email_service = EmailGeneratorService(ai_client)
        
        # Extract intelligence
        logger.info(f"Extracting intelligence for {request.company_name}...")
        intelligence, score = await intelligence_service.extract_and_score(company_data)
        
        logger.info(f"Lead score: {score.lead_score} ({score.priority_tier})")
        
        # Check if lead is worth pursuing
        if not score.should_outreach:
            return {
                "success": False,
                "reason": f"Lead score {score.lead_score} below threshold",
                "lead_score": score.lead_score,
                "priority_tier": score.priority_tier
            }
        
        # Generate email
        logger.info("Generating personalized email...")
        email_request = EmailGenerationRequest(
            contact_name=request.contact_name,
            contact_role=request.contact_role,
            company_name=request.company_name,
            intelligence=intelligence,
            trigger_event=request.trigger_event,
            campaign_positioning=request.campaign_positioning,
            cta_style=request.cta_style
        )
        
        email, spam_result = await email_service.generate_and_validate(email_request)
        
        logger.info(f"Email generated - Spam score: {spam_result.spam_score}")
        
        if not spam_result.is_safe_to_send:
            return {
                "success": False,
                "reason": "Email flagged as potential spam",
                "spam_score": spam_result.spam_score,
                "issues": spam_result.issues_found
            }
        
        return {
            "success": True,
            "email": {
                "subject": email.subject,
                "body": email.body,
                "word_count": email.word_count
            },
            "lead_score": score.lead_score,
            "priority_tier": score.priority_tier,
            "spam_score": spam_result.spam_score,
            "intelligence": {
                "growth_stage": intelligence.growth_stage,
                "urgency_score": intelligence.urgency_score,
                "personalization_hooks": intelligence.personalization_hooks
            }
        }
        
    except Exception as e:
        logger.error(f"Error processing lead: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-reply")
async def process_reply(
    request: ProcessReplyRequest,
    background_tasks: BackgroundTasks,
    ai_client = Depends(get_ai_client)
):
    """
    Process an incoming email reply.
    
    Classifies the reply intent and generates appropriate action.
    """
    try:
        logger.info(f"Processing reply from {request.from_email}")
        
        # Initialize reply handler
        from ..services.outreach import ReplyContext
        reply_service = ReplyHandlerService(ai_client)
        
        context = ReplyContext(
            reply_text=request.body,
            original_email_subject="[Subject not provided]",
            original_email_body="[Original email not provided]",
            contact_name=request.contact_name,
            company_name=request.company_name
        )
        
        # Classify reply
        classification = await reply_service.classify_reply(context)
        
        return {
            "success": True,
            "classification": classification.classification,
            "confidence": classification.confidence,
            "sentiment": classification.sentiment,
            "recommended_action": classification.recommended_action,
            "needs_review": classification.needs_human_review
        }
        
    except Exception as e:
        logger.error(f"Error processing reply: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-followup")
async def generate_followup(
    request: GenerateFollowUpRequest,
    ai_client = Depends(get_ai_client)
):
    """
    Generate a follow-up email for a lead that hasn't replied.
    """
    try:
        logger.info(f"Generating follow-up for {request.contact_email}")
        
        from ..services.outreach import FollowUpRequest, GeneratedEmail
        email_service = EmailGeneratorService(ai_client)
        
        # Create stub original email (in production, fetch from database)
        original_email = GeneratedEmail(
            subject="[Previous subject]",
            body="[Previous body]"
        )
        
        followup_request = FollowUpRequest(
            original_email=original_email,
            days_since_sent=request.days_since_sent,
            open_count=request.open_count,
            contact_name=request.contact_name,
            company_name=request.company_name
        )
        
        followup = await email_service.generate_followup(followup_request)
        
        return {
            "success": True,
            "email": {
                "subject": followup.subject,
                "body": followup.body,
                "strategy_used": followup.strategy_used,
                "word_count": followup.word_count
            }
        }
        
    except Exception as e:
        logger.error(f"Error generating follow-up: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Torpedo Outreach API",
        "version": "1.0.0"
    }


@router.post("/test-ai-connection")
async def test_ai_connection(ai_client = Depends(get_ai_client)):
    """Test connection to OpenAI API."""
    try:
        response = await ai_client.models.list()
        return {
            "success": True,
            "message": "Connected to OpenAI API",
            "models_available": len(list(response.data))
        }
    except Exception as e:
        logger.error(f"AI connection test failed: {e}")
        raise HTTPException(status_code=500, detail=f"AI connection failed: {str(e)}")
