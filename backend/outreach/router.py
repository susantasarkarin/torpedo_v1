"""
OUTREACH API ROUTER
==================

FastAPI router for AI cold outreach and re-engagement endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime
from bson import ObjectId

from ..database import get_database
from .models import (
    OutreachLead,
    OutreachSequence,
    LeadEnrollmentRequest,
    LeadEnrollmentResponse,
    SequenceAnalyticsResponse,
    LeadStatusUpdate,
    PersonalizationLevel,
    EngagementStatus,
    SequenceStage,
    EmailEventType
)
from .sequence_engine import SequenceEngine, create_default_sequence
from .personalization import PersonalizationEngine
from .automation_rules import AutomationRulesEngine
from .tracking import EmailTrackingService
from .reengagement import ReengagementEngine
from .templates import seed_templates


router = APIRouter(prefix="/api/outreach", tags=["AI Cold Outreach"])


# ============== LEAD MANAGEMENT ==============

@router.post("/leads/enroll", response_model=LeadEnrollmentResponse)
async def enroll_leads(
    request: LeadEnrollmentRequest,
    db=Depends(get_database)
):
    """
    Enroll leads in an outreach sequence.
    """
    engine = SequenceEngine(db)
    leads_collection = db["outreach_leads"]
    
    enrolled = 0
    duplicates = 0
    errors = 0
    lead_ids = []
    
    for lead_data in request.leads:
        try:
            # Check for duplicate
            existing = leads_collection.find_one({"email": lead_data.email})
            
            if existing:
                duplicates += 1
                continue
            
            # Create lead
            lead = OutreachLead(
                **lead_data.model_dump(),
                assigned_sequence_id=request.sequence_id,
                personalization_level=request.personalization_level or lead_data.personalization_level
            )
            
            doc = lead.model_dump()
            result = leads_collection.insert_one(doc)
            lead_id = str(result.inserted_id)
            lead_ids.append(lead_id)
            
            # Enroll in sequence
            if request.start_immediately:
                engine.enroll_lead(lead_id, request.sequence_id, start_immediately=True)
            
            enrolled += 1
            
        except Exception as e:
            errors += 1
            import logging
            logging.error(f"Error enrolling lead: {e}")
    
    return LeadEnrollmentResponse(
        enrolled=enrolled,
        duplicates=duplicates,
        errors=errors,
        lead_ids=lead_ids
    )


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: str, db=Depends(get_database)):
    """Get lead details."""
    leads_collection = db["outreach_leads"]
    
    lead = leads_collection.find_one({"_id": ObjectId(lead_id)})
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    lead["_id"] = str(lead["_id"])
    return lead


@router.patch("/leads/{lead_id}/status")
async def update_lead_status(
    lead_id: str,
    update: LeadStatusUpdate,
    db=Depends(get_database)
):
    """Update lead status and metadata."""
    leads_collection = db["outreach_leads"]
    
    update_data = {"updated_at": datetime.utcnow()}
    
    if update.engagement_status:
        update_data["engagement_status"] = update.engagement_status.value
    
    if update.sequence_stage:
        update_data["sequence_stage"] = update.sequence_stage.value
    
    if update.tags is not None:
        update_data["tags"] = update.tags
    
    if update.custom_fields:
        update_data["custom_fields"] = update.custom_fields
    
    result = leads_collection.update_one(
        {"_id": ObjectId(lead_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    return {"success": True, "updated": result.modified_count > 0}


@router.get("/leads")
async def list_leads(
    sequence_id: Optional[str] = None,
    engagement_status: Optional[EngagementStatus] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db=Depends(get_database)
):
    """List leads with filtering."""
    leads_collection = db["outreach_leads"]
    
    query = {}
    
    if sequence_id:
        query["assigned_sequence_id"] = sequence_id
    
    if engagement_status:
        query["engagement_status"] = engagement_status.value
    
    leads = list(leads_collection.find(query).skip(skip).limit(limit))
    
    for lead in leads:
        lead["_id"] = str(lead["_id"])
    
    return {
        "leads": leads,
        "total": leads_collection.count_documents(query),
        "skip": skip,
        "limit": limit
    }


# ============== SEQUENCE MANAGEMENT ==============

@router.post("/sequences")
async def create_sequence(
    name: str,
    steps: List[Dict[str, Any]],
    description: Optional[str] = None,
    personalization_level: PersonalizationLevel = PersonalizationLevel.ROLE_BASED,
    duration_days: int = 14,
    db=Depends(get_database)
):
    """Create a new outreach sequence."""
    engine = SequenceEngine(db)
    
    sequence_id = engine.create_sequence(
        name=name,
        steps=steps,
        description=description,
        personalization_level=personalization_level,
        duration_days=duration_days
    )
    
    return {"sequence_id": sequence_id, "name": name}


@router.post("/sequences/default")
async def create_default(db=Depends(get_database)):
    """Create the default 4-step cold outreach sequence."""
    # First, seed templates
    template_ids = seed_templates(db)
    
    # Create sequence with template IDs
    engine = SequenceEngine(db)
    
    steps = [
        {
            "step_number": 0,
            "day_offset": 0,
            "name": "Introduction",
            "description": "Soft introduction with one clear pain point",
            "template_id": template_ids["email_1_introduction"],
            "send_if_not_replied": True
        },
        {
            "step_number": 1,
            "day_offset": 4,
            "name": "Value Follow-Up",
            "description": "Different angle with use case and social proof",
            "template_id": template_ids["email_2_value_followup"],
            "send_if_not_replied": True,
            "subject_variants": ["Quick follow-up for {{company}}"]
        },
        {
            "step_number": 2,
            "day_offset": 7,
            "name": "Direct / Break-Up",
            "description": "Concise with simple yes/no CTA",
            "template_id": template_ids["email_3_direct"],
            "send_if_not_replied": True,
            "subject_variants": ["Last check-in, {{first_name}}"]
        },
        {
            "step_number": 3,
            "day_offset": 12,
            "name": "Final Touch",
            "description": "Polite close-the-loop message",
            "template_id": template_ids["email_4_final_touch"],
            "send_if_not_replied": True
        }
    ]
    
    sequence_id = engine.create_sequence(
        name="Default Cold Outreach (14 days)",
        steps=steps,
        description="Standard 4-step B2B cold outreach sequence",
        duration_days=14
    )
    
    return {
        "sequence_id": sequence_id,
        "name": "Default Cold Outreach (14 days)",
        "template_ids": template_ids
    }


@router.get("/sequences/{sequence_id}")
async def get_sequence(sequence_id: str, db=Depends(get_database)):
    """Get sequence details."""
    sequences_collection = db["outreach_sequences"]
    
    sequence = sequences_collection.find_one({"_id": ObjectId(sequence_id)})
    
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")
    
    sequence["_id"] = str(sequence["_id"])
    return sequence


@router.get("/sequences/{sequence_id}/analytics", response_model=SequenceAnalyticsResponse)
async def get_sequence_analytics(sequence_id: str, db=Depends(get_database)):
    """Get analytics for a sequence."""
    leads_collection = db["outreach_leads"]
    emails_collection = db["outreach_emails"]
    events_collection = db["outreach_events"]
    sequences_collection = db["outreach_sequences"]
    
    # Get sequence
    sequence = sequences_collection.find_one({"_id": ObjectId(sequence_id)})
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")
    
    # Count leads
    total_leads = leads_collection.count_documents({"assigned_sequence_id": sequence_id})
    
    # Count emails
    emails_sent = emails_collection.count_documents({
        "sequence_id": sequence_id,
        "status": {"$in": ["sent", "delivered", "opened", "clicked", "replied"]}
    })
    
    emails_delivered = emails_collection.count_documents({
        "sequence_id": sequence_id,
        "status": {"$in": ["delivered", "opened", "clicked", "replied"]}
    })
    
    emails_opened = emails_collection.count_documents({
        "sequence_id": sequence_id,
        "opened_at": {"$exists": True}
    })
    
    emails_clicked = emails_collection.count_documents({
        "sequence_id": sequence_id,
        "clicked_at": {"$exists": True}
    })
    
    emails_replied = emails_collection.count_documents({
        "sequence_id": sequence_id,
        "replied_at": {"$exists": True}
    })
    
    emails_bounced = events_collection.count_documents({
        "sequence_id": sequence_id,
        "event_type": EmailEventType.BOUNCED.value
    })
    
    # Calculate rates
    open_rate = (emails_opened / emails_delivered * 100) if emails_delivered > 0 else 0
    click_rate = (emails_clicked / emails_delivered * 100) if emails_delivered > 0 else 0
    reply_rate = (emails_replied / emails_delivered * 100) if emails_delivered > 0 else 0
    bounce_rate = (emails_bounced / emails_sent * 100) if emails_sent > 0 else 0
    
    # Get positive reply rate (placeholder - would need reply sentiment analysis)
    positive_reply_rate = reply_rate * 0.6  # Placeholder: assume 60% positive
    
    # Re-engagement stats
    reengagement_collection = db["reengagement_pool"]
    reengagement_eligible = reengagement_collection.count_documents({
        "original_sequence_id": sequence_id
    })
    reengagement_converted = reengagement_collection.count_documents({
        "original_sequence_id": sequence_id,
        "converted_to_active": True
    })
    reengagement_conversion_rate = (
        (reengagement_converted / reengagement_eligible * 100)
        if reengagement_eligible > 0 else 0
    )
    
    return SequenceAnalyticsResponse(
        sequence_id=sequence_id,
        sequence_name=sequence.get("name", ""),
        total_leads=total_leads,
        emails_sent=emails_sent,
        emails_delivered=emails_delivered,
        emails_opened=emails_opened,
        emails_clicked=emails_clicked,
        emails_replied=emails_replied,
        emails_bounced=emails_bounced,
        open_rate=round(open_rate, 2),
        click_rate=round(click_rate, 2),
        reply_rate=round(reply_rate, 2),
        positive_reply_rate=round(positive_reply_rate, 2),
        bounce_rate=round(bounce_rate, 2),
        reengagement_eligible=reengagement_eligible,
        reengagement_converted=reengagement_converted,
        reengagement_conversion_rate=round(reengagement_conversion_rate, 2)
    )


# ============== EMAIL TRACKING ==============

@router.post("/tracking/sent/{email_id}")
async def track_sent(email_id: str, provider_message_id: Optional[str] = None, db=Depends(get_database)):
    """Track email sent event."""
    service = EmailTrackingService(db)
    success = service.track_sent(email_id, provider_message_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Email not found")
    
    return {"success": True}


@router.post("/tracking/opened/{email_id}")
async def track_opened(
    email_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    db=Depends(get_database)
):
    """Track email opened event."""
    service = EmailTrackingService(db)
    success = service.track_opened(email_id, ip_address, user_agent)
    
    if not success:
        raise HTTPException(status_code=404, detail="Email not found")
    
    return {"success": True}


@router.post("/tracking/clicked/{email_id}")
async def track_clicked(
    email_id: str,
    clicked_url: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    db=Depends(get_database)
):
    """Track email link clicked event."""
    service = EmailTrackingService(db)
    success = service.track_clicked(email_id, clicked_url, ip_address, user_agent)
    
    if not success:
        raise HTTPException(status_code=404, detail="Email not found")
    
    return {"success": True}


@router.post("/tracking/replied/{email_id}")
async def track_replied(
    email_id: str,
    reply_message_id: Optional[str] = None,
    db=Depends(get_database)
):
    """Track email replied event."""
    service = EmailTrackingService(db)
    success = service.track_replied(email_id, reply_message_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Email not found")
    
    return {"success": True}


@router.post("/tracking/bounced/{email_id}")
async def track_bounced(
    email_id: str,
    bounce_reason: Optional[str] = None,
    db=Depends(get_database)
):
    """Track email bounced event."""
    service = EmailTrackingService(db)
    success = service.track_bounced(email_id, bounce_reason)
    
    if not success:
        raise HTTPException(status_code=404, detail="Email not found")
    
    return {"success": True}


@router.get("/tracking/email/{email_id}/activity")
async def get_email_activity(email_id: str, db=Depends(get_database)):
    """Get complete activity history for an email."""
    service = EmailTrackingService(db)
    activity = service.get_email_activity(email_id)
    
    if not activity:
        raise HTTPException(status_code=404, detail="Email not found")
    
    return activity


# ============== RE-ENGAGEMENT ==============

@router.post("/reengagement/enroll")
async def enroll_reengagement(db=Depends(get_database)):
    """Enroll eligible leads in re-engagement pool."""
    engine = ReengagementEngine(db)
    enrolled = engine.enroll_eligible_leads()
    
    return {"enrolled": enrolled}


@router.get("/reengagement/stats")
async def get_reengagement_stats(db=Depends(get_database)):
    """Get re-engagement pool statistics."""
    engine = ReengagementEngine(db)
    stats = engine.get_pool_stats()
    
    return stats


@router.post("/reengagement/process")
async def process_reengagement(limit: int = Query(50, ge=1, le=100), db=Depends(get_database)):
    """Process due re-engagement actions."""
    engine = ReengagementEngine(db)
    processed = engine.process_due_actions(limit)
    
    return {"processed": processed}


# ============== AUTOMATION RULES ==============

@router.get("/automation/rules")
async def list_automation_rules(db=Depends(get_database)):
    """List all automation rules."""
    rules_collection = db["automation_rules"]
    rules = list(rules_collection.find({"is_active": True}))
    
    for rule in rules:
        rule["_id"] = str(rule["_id"])
    
    return {"rules": rules}


@router.get("/automation/stats")
async def get_automation_stats(db=Depends(get_database)):
    """Get automation rule execution statistics."""
    engine = AutomationRulesEngine(db)
    stats = engine.get_rule_stats()
    
    return {"stats": stats}


@router.post("/automation/evaluate/{lead_id}")
async def evaluate_lead_rules(lead_id: str, db=Depends(get_database)):
    """Evaluate all automation rules for a lead."""
    engine = AutomationRulesEngine(db)
    executed = engine.evaluate_lead(lead_id)
    
    return {"executed_rules": executed}


# ============== TEMPLATES ==============

@router.post("/templates/seed")
async def seed_email_templates(db=Depends(get_database)):
    """Seed database with default email templates."""
    template_ids = seed_templates(db)
    
    return {
        "success": True,
        "templates_created": len(template_ids),
        "template_ids": template_ids
    }


@router.get("/templates")
async def list_templates(
    category: Optional[str] = None,
    db=Depends(get_database)
):
    """List email templates."""
    templates_collection = db["outreach_templates"]
    
    query = {"is_active": True}
    if category:
        query["category"] = category
    
    templates = list(templates_collection.find(query))
    
    for template in templates:
        template["_id"] = str(template["_id"])
    
    return {"templates": templates}


# ============== UTILITY ENDPOINTS ==============

@router.post("/process/scheduled-emails")
async def process_scheduled_emails(limit: int = Query(100, ge=1, le=500), db=Depends(get_database)):
    """Process emails scheduled for sending."""
    engine = SequenceEngine(db)
    processed = engine.process_scheduled_emails(limit)
    
    return {"processed": processed}


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "AI Cold Outreach"}
