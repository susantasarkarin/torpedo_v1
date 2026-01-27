"""
CAMPAIGN AUTOMATION API ROUTER
===============================

REST API endpoints for automated campaign creation and management.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, EmailStr, Field

from ..campaigns.automation import CampaignAutomation


router = APIRouter(prefix="/campaigns/automation", tags=["Campaign Automation"])


# ============== REQUEST MODELS ==============

class RecipientData(BaseModel):
    """Recipient data model"""
    email: EmailStr
    first_name: str
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    custom_variables: Dict[str, Any] = Field(default_factory=dict)


class CreateAutomatedCampaignRequest(BaseModel):
    """Request to create automated campaign"""
    company: str = Field(..., description="Company identifier: 'surveyfieldwork' or 'cogentixresearch'")
    campaign_name: str
    recipients: List[RecipientData]
    mailbox_id: Optional[str] = None
    start_immediately: bool = False


class TrackingEventRequest(BaseModel):
    """Email tracking event"""
    email: EmailStr
    campaign_id: str
    event: str = Field(..., description="Event type: 'opened', 'bounced', 'clicked'")
    timestamp: Optional[datetime] = None
    send_id: Optional[str] = None


class BulkTrackingRequest(BaseModel):
    """Bulk tracking updates"""
    events: List[TrackingEventRequest]


# ============== DEPENDENCY ==============

def get_automation():
    """Get campaign automation instance"""
    return CampaignAutomation()


# ============== ENDPOINTS ==============

@router.get("/services", response_model=Dict[str, Any])
async def list_services(automation: CampaignAutomation = Depends(get_automation)):
    """
    List all services offered by surveyfieldwork and cogentixresearch.
    
    Returns a comprehensive list of services with descriptions.
    """
    try:
        services = automation.list_services()
        return {
            "success": True,
            "services": services
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/services/{company}/{service_id}", response_model=Dict[str, Any])
async def get_service_details(
    company: str,
    service_id: str,
    automation: CampaignAutomation = Depends(get_automation)
):
    """
    Get detailed information about a specific service.
    
    Args:
        company: Company identifier ('surveyfieldwork' or 'cogentixresearch')
        service_id: Service identifier
    """
    try:
        service = automation.get_service_details(company, service_id)
        return {
            "success": True,
            "service": service
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns", response_model=Dict[str, Any])
async def create_automated_campaign(
    request: CreateAutomatedCampaignRequest,
    automation: CampaignAutomation = Depends(get_automation)
):
    """
    Create an automated outreach campaign with weekly follow-ups.
    
    Features:
    - Highly personalized emails with appropriate sender (indira@ or meera@)
    - Email signatures for each company
    - Weekly follow-up sequence (3 follow-ups)
    - Automatic tracking setup for opens, bounces, clicks
    - Stops sequence on reply or bounce
    
    The campaign includes:
    1. Initial outreach (Day 0)
    2. Follow-up Week 1 (Day 7) - if no reply
    3. Follow-up Week 2 (Day 14) - if no reply
    4. Follow-up Week 3 (Day 21) - if no reply
    """
    try:
        # Validate company
        if request.company.lower() not in ['surveyfieldwork', 'cogentixresearch']:
            raise HTTPException(
                status_code=400,
                detail="Company must be 'surveyfieldwork' or 'cogentixresearch'"
            )
        
        # Convert recipients to dict format
        recipients_data = [r.model_dump() for r in request.recipients]
        
        # Create campaign
        campaign_id = automation.create_outreach_campaign(
            company=request.company,
            campaign_name=request.campaign_name,
            recipients=recipients_data,
            mailbox_id=request.mailbox_id,
            start_immediately=request.start_immediately
        )
        
        # Get campaign details
        campaign = automation.campaign_manager.get_campaign(campaign_id)
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "campaign_name": request.campaign_name,
            "company": request.company,
            "from_email": campaign.get("from_email"),
            "from_name": campaign.get("from_name"),
            "recipients_added": len(recipients_data),
            "sequence_steps": len(campaign.get("sequence_steps", [])),
            "status": campaign.get("status"),
            "message": "Campaign created successfully with weekly follow-up sequence"
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tracking/events", response_model=Dict[str, Any])
async def process_tracking_events(
    request: BulkTrackingRequest,
    automation: CampaignAutomation = Depends(get_automation)
):
    """
    Process email tracking events (opens, bounces, clicks).
    
    This endpoint updates campaign recipient and send status based on tracking events.
    
    Supported events:
    - 'opened': Email was opened
    - 'bounced': Email bounced (automatically sets recipient status to BOUNCED)
    - 'clicked': Link in email was clicked
    
    For bounce events, the recipient status is automatically updated to "BOUNCED".
    """
    try:
        # Convert to dict format
        events_data = [e.model_dump() for e in request.events]
        
        # Process events
        automation.process_email_tracking_updates(events_data)
        
        # Count events by type
        event_counts = {}
        for event in events_data:
            event_type = event.get("event", "unknown")
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        
        return {
            "success": True,
            "processed": len(events_data),
            "event_counts": event_counts,
            "message": "Tracking events processed successfully"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tracking/bounce/{campaign_id}/{email}", response_model=Dict[str, Any])
async def mark_as_bounced(
    campaign_id: str,
    email: str,
    automation: CampaignAutomation = Depends(get_automation)
):
    """
    Mark a specific recipient as bounced.
    
    This updates the recipient status to "BOUNCED" and stops the campaign sequence
    for this recipient.
    
    Args:
        campaign_id: Campaign ID
        email: Recipient email address
    """
    try:
        # Create bounce event
        bounce_event = {
            "email": email,
            "campaign_id": campaign_id,
            "event": "bounced",
            "timestamp": datetime.utcnow()
        }
        
        automation.process_email_tracking_updates([bounce_event])
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "email": email,
            "status": "bounced",
            "message": f"Recipient {email} marked as bounced"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns/{campaign_id}/report", response_model=Dict[str, Any])
async def get_campaign_report(
    campaign_id: str,
    automation: CampaignAutomation = Depends(get_automation)
):
    """
    Get comprehensive campaign status report.
    
    Returns detailed information including:
    - Recipient status breakdown (pending, bounced, replied, etc.)
    - Send status breakdown (sent, opened, not opened, bounced, etc.)
    - Engagement rates (open rate, click rate, bounce rate, reply rate)
    - Campaign metadata
    """
    try:
        report = automation.get_campaign_status_report(campaign_id)
        
        if "error" in report:
            raise HTTPException(status_code=404, detail=report["error"])
        
        return {
            "success": True,
            "report": report
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/templates/{company}", response_model=Dict[str, Any])
async def list_company_templates(
    company: str,
    automation: CampaignAutomation = Depends(get_automation)
):
    """
    List email templates for a specific company.
    
    Args:
        company: Company identifier ('surveyfieldwork' or 'cogentixresearch')
    """
    try:
        from ..campaigns.email_templates import list_templates
        
        templates = list_templates(company)
        
        return {
            "success": True,
            "company": company,
            "templates": templates
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-email-render", response_model=Dict[str, Any])
async def test_email_rendering(
    company: str = Body(...),
    template_name: str = Body(...),
    variables: Dict[str, Any] = Body(...)
):
    """
    Test email template rendering with sample variables.
    
    This is useful for previewing how emails will look with personalization.
    
    Args:
        company: Company identifier
        template_name: Template name (e.g., 'initial_outreach', 'follow_up_week1')
        variables: Dictionary of variables to substitute
    """
    try:
        from ..campaigns.email_templates import get_template_config, render_template
        
        # Get template config
        template_config = get_template_config(company, template_name)
        
        # Render with variables
        rendered = render_template(template_config, variables)
        
        return {
            "success": True,
            "company": company,
            "template_name": template_name,
            "rendered": rendered,
            "template_info": {
                "name": template_config.get("name"),
                "category": template_config.get("category"),
                "required_variables": template_config.get("variables", [])
            }
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
