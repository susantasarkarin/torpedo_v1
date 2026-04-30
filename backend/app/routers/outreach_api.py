"""
Torpedo Outreach API Routes.

Main REST API for the AI-powered cold outreach system.
"""

import logging
from typing import Optional, Any
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, EmailStr
from openai import AsyncOpenAI
import os
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId

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


def get_outreach_db() -> Any:
    mongo_uri = os.getenv("MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
    mongo_db = os.getenv("OUTREACH_DB_NAME") or "email_automation"
    client = MongoClient(mongo_uri)
    return client[mongo_db]


def apply_runtime_prompt_overrides() -> None:
    """Load prompt overrides from DB and patch outreach prompt module in-memory."""
    try:
        from ..services.outreach import master_prompts

        db = get_outreach_db()
        prompt_collection = db["outreach_prompt_overrides"]
        overrides = list(prompt_collection.find({}))
        for doc in overrides:
            key = doc.get("prompt_key")
            content = doc.get("content")
            if key and isinstance(content, str) and hasattr(master_prompts, key):
                setattr(master_prompts, key, content)
    except Exception as exc:
        logger.warning("Failed applying runtime outreach prompt overrides: %s", exc)


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


class PromptUpdateRequest(BaseModel):
    content: str


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
        apply_runtime_prompt_overrides()
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
        apply_runtime_prompt_overrides()
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
        apply_runtime_prompt_overrides()
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


@router.get("/dashboard")
async def outreach_dashboard(limit: int = 100):
    """Return outreach KPIs and recent email activity for monitoring UI."""
    try:
        db = get_outreach_db()
        emails = db["outreach_emails"]
        senders = db["outreach_senders"]

        pipeline = [
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1}
                }
            }
        ]
        status_rows = list(emails.aggregate(pipeline))
        status_counts = {str(row.get("_id") or "unknown"): int(row.get("count", 0)) for row in status_rows}

        sent_total = sum(
            status_counts.get(k, 0)
            for k in ["sent", "opened", "clicked", "replied", "bounced", "complained"]
        )
        opened_total = status_counts.get("opened", 0) + status_counts.get("clicked", 0) + status_counts.get("replied", 0)
        clicked_total = status_counts.get("clicked", 0) + status_counts.get("replied", 0)
        replied_total = status_counts.get("replied", 0)
        bounced_total = status_counts.get("bounced", 0)

        open_rate = round((opened_total / sent_total * 100), 2) if sent_total else 0.0
        click_rate = round((clicked_total / sent_total * 100), 2) if sent_total else 0.0
        reply_rate = round((replied_total / sent_total * 100), 2) if sent_total else 0.0
        bounce_rate = round((bounced_total / sent_total * 100), 2) if sent_total else 0.0

        recent_docs = list(
            emails.find({})
            .sort([("updated_at", -1), ("created_at", -1), ("_id", -1)])
            .limit(max(1, min(limit, 500)))
        )

        sender_id_set = set()
        for doc in recent_docs:
            sender_id = doc.get("sender_id")
            if sender_id is None:
                continue
            if isinstance(sender_id, str) and ObjectId.is_valid(sender_id):
                sender_id_set.add(ObjectId(sender_id))
            else:
                sender_id_set.add(sender_id)
        sender_map = {}
        if sender_id_set:
            for sender_doc in senders.find({"_id": {"$in": list(sender_id_set)}}):
                sender_map[str(sender_doc.get("_id"))] = sender_doc.get("email")

        def _iso(value):
            if isinstance(value, datetime):
                return value.isoformat()
            return value

        recent = []
        for doc in recent_docs:
            sender_id = doc.get("sender_id")
            sender_id_str = str(sender_id) if sender_id is not None else None
            recent.append(
                {
                    "id": str(doc.get("_id")),
                    "to_email": doc.get("to_email") or doc.get("recipient_email") or doc.get("contact_email"),
                    "subject": doc.get("subject", ""),
                    "body": doc.get("body") or doc.get("body_text") or "",
                    "status": doc.get("status", "unknown"),
                    "sent_at": _iso(doc.get("sent_at")),
                    "scheduled_for": _iso(doc.get("scheduled_for")),
                    "updated_at": _iso(doc.get("updated_at")),
                    "open_count": int(doc.get("open_count", 0) or 0),
                    "click_count": int(doc.get("click_count", 0) or 0),
                    "sender_id": sender_id_str,
                    "sender_email": sender_map.get(sender_id_str),
                    "provider": doc.get("provider"),
                }
            )

        return {
            "success": True,
            "summary": {
                "total": sum(status_counts.values()),
                "sent": sent_total,
                "opened": opened_total,
                "clicked": clicked_total,
                "replied": replied_total,
                "bounced": bounced_total,
                "complained": status_counts.get("complained", 0),
                "queued": status_counts.get("queued", 0),
                "failed": status_counts.get("failed", 0),
                "open_rate": open_rate,
                "click_rate": click_rate,
                "reply_rate": reply_rate,
                "bounce_rate": bounce_rate,
            },
            "status_counts": status_counts,
            "recent": recent,
        }
    except Exception as e:
        logger.error(f"Error building outreach dashboard: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompts")
async def list_outreach_prompts():
    """List editable outreach prompt templates."""
    try:
        apply_runtime_prompt_overrides()
        from ..services.outreach import master_prompts

        db = get_outreach_db()
        prompt_collection = db["outreach_prompt_overrides"]

        default_prompts = {
            "MASTER_SYSTEM_PROMPT": master_prompts.MASTER_SYSTEM_PROMPT,
            "LEAD_INTELLIGENCE_PROMPT": master_prompts.LEAD_INTELLIGENCE_PROMPT,
            "LEAD_SCORING_PROMPT": master_prompts.LEAD_SCORING_PROMPT,
            "EMAIL_GENERATION_PROMPT": master_prompts.EMAIL_GENERATION_PROMPT,
            "FOLLOWUP_GENERATION_PROMPT": master_prompts.FOLLOWUP_GENERATION_PROMPT,
            "REPLY_CLASSIFIER_PROMPT": master_prompts.REPLY_CLASSIFIER_PROMPT,
            "AUTO_RESPONSE_PROMPT": master_prompts.AUTO_RESPONSE_PROMPT,
            "SPAM_CHECK_PROMPT": master_prompts.SPAM_CHECK_PROMPT,
        }

        overrides = {
            doc.get("prompt_key"): doc
            for doc in prompt_collection.find({})
        }

        prompts = []
        for key, default_value in default_prompts.items():
            override_doc = overrides.get(key)
            prompts.append(
                {
                    "prompt_key": key,
                    "content": override_doc.get("content") if override_doc else default_value,
                    "default_content": default_value,
                    "is_overridden": bool(override_doc),
                    "updated_at": override_doc.get("updated_at") if override_doc else None,
                }
            )

        return {"success": True, "prompts": prompts}
    except Exception as e:
        logger.error(f"Error loading outreach prompts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/prompts/{prompt_key}")
async def update_outreach_prompt(prompt_key: str, request: PromptUpdateRequest):
    """Update an outreach prompt override used by the monitoring UI."""
    try:
        if not request.content or not request.content.strip():
            raise HTTPException(status_code=400, detail="Prompt content cannot be empty")

        db = get_outreach_db()
        prompt_collection = db["outreach_prompt_overrides"]

        now = datetime.utcnow()
        prompt_collection.update_one(
            {"prompt_key": prompt_key},
            {
                "$set": {
                    "prompt_key": prompt_key,
                    "content": request.content,
                    "updated_at": now,
                }
            },
            upsert=True,
        )

        from ..services.outreach import master_prompts
        if hasattr(master_prompts, prompt_key):
            setattr(master_prompts, prompt_key, request.content)

        return {
            "success": True,
            "prompt_key": prompt_key,
            "updated_at": now.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating outreach prompt {prompt_key}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Webhook Endpoints for Email Provider Events
# =============================================================================

class WebhookOpenEvent(BaseModel):
    """Open event from email provider."""
    tracking_id: str


class WebhookClickEvent(BaseModel):
    """Click event from email provider."""
    tracking_id: str
    url: str


class WebhookBounceEvent(BaseModel):
    """Bounce event from email provider."""
    message_id: str
    reason: str = "unknown"


class WebhookComplaintEvent(BaseModel):
    """Complaint/spam event from email provider."""
    message_id: str
    reason: str = "unknown"


class WebhookReplyEvent(BaseModel):
    """Reply event from email provider."""
    message_id: str
    from_email: EmailStr
    body_text: str


@router.post("/webhook/open")
async def webhook_open_event(event: WebhookOpenEvent, background_tasks: BackgroundTasks):
    """
    Webhook endpoint for email open events.
    
    Expected from: SES, SendGrid, Mailgun, or other email provider.
    """
    try:
        logger.info(f"Received open event for tracking_id: {event.tracking_id}")
        
        # Import here to avoid circular imports
        from tasks.outreach_tasks import process_webhook_event_task
        
        # Queue for async processing
        process_webhook_event_task.delay('open', {'tracking_id': event.tracking_id})
        
        return {"status": "accepted", "event_type": "open"}
        
    except Exception as e:
        logger.error(f"Error processing open webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook/click")
async def webhook_click_event(event: WebhookClickEvent, background_tasks: BackgroundTasks):
    """
    Webhook endpoint for email link click events.
    """
    try:
        logger.info(f"Received click event for tracking_id: {event.tracking_id} on {event.url}")
        
        # Import here to avoid circular imports
        from tasks.outreach_tasks import process_webhook_event_task
        
        # Queue for async processing
        process_webhook_event_task.delay('click', {'tracking_id': event.tracking_id, 'url': event.url})
        
        return {"status": "accepted", "event_type": "click"}
        
    except Exception as e:
        logger.error(f"Error processing click webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook/bounce")
async def webhook_bounce_event(event: WebhookBounceEvent, background_tasks: BackgroundTasks):
    """
    Webhook endpoint for email bounce events.
    
    Bounces mark a lead as undeliverable and signal sender reputation issues.
    """
    try:
        logger.info(f"Received bounce event for message_id: {event.message_id} ({event.reason})")
        
        # Import here to avoid circular imports
        from tasks.outreach_tasks import process_webhook_event_task
        
        # Queue for async processing
        process_webhook_event_task.delay('bounce', {'message_id': event.message_id, 'reason': event.reason})
        
        return {"status": "accepted", "event_type": "bounce"}
        
    except Exception as e:
        logger.error(f"Error processing bounce webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook/complaint")
async def webhook_complaint_event(event: WebhookComplaintEvent, background_tasks: BackgroundTasks):
    """
    Webhook endpoint for spam complaint events.
    
    Complaints damage sender reputation and should trigger immediate lead unsubscribe.
    """
    try:
        logger.info(f"Received complaint event for message_id: {event.message_id} ({event.reason})")
        
        # Import here to avoid circular imports
        from tasks.outreach_tasks import process_webhook_event_task
        
        # Queue for async processing
        process_webhook_event_task.delay('complaint', {'message_id': event.message_id, 'reason': event.reason})
        
        return {"status": "accepted", "event_type": "complaint"}
        
    except Exception as e:
        logger.error(f"Error processing complaint webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook/reply")
async def webhook_reply_event(event: WebhookReplyEvent, background_tasks: BackgroundTasks):
    """
    Webhook endpoint for reply events.
    
    Replies indicate engagement and can be processed for auto-respond or manual review.
    """
    try:
        logger.info(f"Received reply event for message_id: {event.message_id} from {event.from_email}")
        
        # Import here to avoid circular imports
        from tasks.outreach_tasks import process_webhook_event_task
        
        # Queue for async processing
        process_webhook_event_task.delay(
            'reply',
            {
                'message_id': event.message_id,
                'from_email': event.from_email,
                'body_text': event.body_text
            }
        )
        
        return {"status": "accepted", "event_type": "reply"}
        
    except Exception as e:
        logger.error(f"Error processing reply webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

