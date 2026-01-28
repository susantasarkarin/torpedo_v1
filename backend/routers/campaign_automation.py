"""
CAMPAIGN AUTOMATION API ROUTER
===============================

REST API endpoints for automated campaign creation and management.
"""

from datetime import datetime, timedelta
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Body, Query
from pydantic import BaseModel, EmailStr, Field

from ..campaigns.automation import CampaignAutomation

logger = logging.getLogger(__name__)

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
        # Validate company (dynamically check against available companies)
        from ..campaigns.services_config import get_company_config
        try:
            get_company_config(request.company)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e)
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


# ============== RE-ENGAGEMENT ENDPOINTS ==============

@router.get("/leads/dormant", response_model=Dict[str, Any])
async def get_dormant_leads(
    inactivity_days: int = Query(30, ge=7, description="Days of inactivity threshold"),
    campaign_id: Optional[str] = Query(None, description="Filter by specific campaign"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    automation: CampaignAutomation = Depends(get_automation)
):
    """
    List leads eligible for re-engagement based on inactivity.
    
    Returns leads that have:
    - Not replied to any emails
    - No engagement (opens/clicks) in X days
    - Not already in a re-engagement campaign
    """
    try:
        from pymongo import MongoClient
        import os
        
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri)
        db = client['email_automation']
        
        # Build query for dormant leads
        query = {
            "status": {"$nin": ["replied", "bounced", "unsubscribed"]},
            "last_engagement_date": {
                "$lt": datetime.utcnow() - timedelta(days=inactivity_days)
            }
        }
        
        if campaign_id:
            query["campaign_id"] = campaign_id
        
        # Count total dormant leads
        total = db["campaign_recipients"].count_documents(query)
        
        # Paginate results
        skip = (page - 1) * page_size
        leads = list(
            db["campaign_recipients"]
            .find(query)
            .sort("last_engagement_date", 1)
            .skip(skip)
            .limit(page_size)
        )
        
        # Format leads
        for lead in leads:
            lead["id"] = str(lead.pop("_id"))
            lead["campaign_id"] = str(lead.get("campaign_id", ""))
        
        return {
            "success": True,
            "leads": leads,
            "total": total,
            "page": page,
            "page_size": page_size,
            "inactivity_threshold_days": inactivity_days
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/reengagement", response_model=Dict[str, Any])
async def create_reengagement_campaign(
    lead_ids: List[str] = Body(..., description="Lead IDs to re-engage"),
    strategy_type: str = Body("reset", description="Strategy: reset, soft_drip, trigger_based"),
    from_mailbox_id: Optional[str] = Body(None),
    analyze_first: bool = Body(True, description="Analyze leads with ReengagementAgent before creating campaign"),
    automation: CampaignAutomation = Depends(get_automation)
):
    """
    Create a re-engagement campaign for dormant leads.
    
    Optionally analyzes leads with ReengagementAgent to determine:
    - Dormancy reasons
    - Optimal re-engagement strategy
    - Fresh angles and messaging
    - Sender rotation recommendations
    """
    try:
        from pymongo import MongoClient
        import os
        
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri)
        db = client['email_automation']
        
        # Fetch lead data
        from bson import ObjectId
        leads = list(db["campaign_recipients"].find({
            "_id": {"$in": [ObjectId(lid) for lid in lead_ids]}
        }))
        
        if not leads:
            raise HTTPException(status_code=404, detail="No leads found with provided IDs")
        
        reengagement_analysis = None
        
        # Analyze with ReengagementAgent if requested
        if analyze_first:
            try:
                from ..agents.reengagement_agent import ReengagementAgent
                
                agent = ReengagementAgent()
                result = await agent.run(leads)
                reengagement_analysis = result.model_dump()
                
            except Exception as e:
                logger.warning(f"ReengagementAgent analysis failed: {e}, continuing without analysis")
        
        # Create re-engagement campaign
        campaign_name = f"Re-engagement {strategy_type.title()} - {datetime.utcnow().strftime('%Y-%m-%d')}"
        
        campaign_id = automation.create_outreach_campaign(
            company="surveyfieldwork",  # Default company
            campaign_name=campaign_name,
            recipients=[{
                "email": lead.get("email"),
                "first_name": lead.get("first_name", ""),
                "last_name": lead.get("last_name", ""),
                "company": lead.get("company_name", ""),
                "title": lead.get("title", ""),
                "custom_variables": {"reengagement_strategy": strategy_type}
            } for lead in leads],
            mailbox_id=from_mailbox_id,
            start_immediately=False
        )
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "leads_enrolled": len(leads),
            "strategy_type": strategy_type,
            "analysis": reengagement_analysis,
            "message": "Re-engagement campaign created successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/leads/{lead_id}/reengagement/enroll", response_model=Dict[str, Any])
async def enroll_lead_in_reengagement(
    lead_id: str,
    campaign_id: str = Body(..., description="Re-engagement campaign ID"),
    custom_message: Optional[str] = Body(None, description="Custom message override"),
    automation: CampaignAutomation = Depends(get_automation)
):
    """
    Manually enroll a single lead in a re-engagement campaign.
    
    Useful for ad-hoc re-engagement of high-value leads.
    """
    try:
        from pymongo import MongoClient
        from bson import ObjectId
        import os
        
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri)
        db = client['email_automation']
        
        # Verify lead exists
        lead = db["campaign_recipients"].find_one({"_id": ObjectId(lead_id)})
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        # Verify campaign exists
        campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Add lead to campaign
        result = automation.campaign_manager.add_recipients(
            campaign_id=campaign_id,
            recipients=[{
                "email": lead.get("email"),
                "first_name": lead.get("first_name", ""),
                "last_name": lead.get("last_name", ""),
                "company": lead.get("company_name", ""),
                "custom_variables": {"custom_message": custom_message} if custom_message else {}
            }],
            deduplicate=True
        )
        
        return {
            "success": True,
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "enrolled": True,
            "message": "Lead enrolled in re-engagement campaign"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns/{campaign_id}/reengagement/timeline", response_model=Dict[str, Any])
async def get_reengagement_timeline(
    campaign_id: str,
    automation: CampaignAutomation = Depends(get_automation)
):
    """
    Get timeline view of re-engagement campaign progress.
    
    Shows:
    - Leads by engagement stage
    - Response rate over time
    - Strategy effectiveness
    """
    try:
        from pymongo import MongoClient
        from bson import ObjectId
        import os
        
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri)
        db = client['email_automation']
        
        # Verify campaign exists
        campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Get all recipients in this campaign
        recipients = list(db["campaign_recipients"].find({"campaign_id": ObjectId(campaign_id)}))
        
        # Build timeline
        timeline = []
        stage_counts = {
            "dormant": 0,
            "re_engaged": 0,
            "opened": 0,
            "clicked": 0,
            "replied": 0
        }
        
        for recipient in recipients:
            status = recipient.get("status", "dormant")
            stage_counts[status] = stage_counts.get(status, 0) + 1
            
            timeline.append({
                "lead_id": str(recipient["_id"]),
                "email": recipient.get("email"),
                "name": recipient.get("first_name", ""),
                "enrolled_date": recipient.get("added_at"),
                "current_stage": status,
                "last_activity": recipient.get("last_engagement_date"),
                "opens": recipient.get("open_count", 0),
                "clicks": recipient.get("click_count", 0)
            })
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name"),
            "total_enrolled": len(recipients),
            "stage_distribution": stage_counts,
            "timeline": sorted(timeline, key=lambda x: x.get("enrolled_date") or datetime.min, reverse=True)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== ANALYTICS ENDPOINTS (Agent 11) ==============

@router.get("/campaigns/{campaign_id}/analytics/timeseries", response_model=Dict[str, Any])
async def get_campaign_timeseries(
    campaign_id: str,
    interval: str = Query("day", description="Time interval: 'hour', 'day', or 'week'")
):
    """
    Get time series analytics for campaign performance.
    
    Returns daily/hourly/weekly breakdown of:
    - Sent emails
    - Opened emails
    - Clicked links
    - Replied emails
    - Bounced emails
    
    Useful for charting campaign performance over time.
    """
    try:
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri)
        db = client['email_automation']
        
        from bson import ObjectId
        
        # Verify campaign exists
        campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Get all sends for this campaign
        sends = list(db["campaign_sends"].find({"campaign_id": ObjectId(campaign_id)}))
        
        # Group by time interval
        timeseries_data = {}
        
        for send in sends:
            sent_at = send.get("sent_at")
            if not sent_at:
                continue
            
            # Determine time bucket based on interval
            if interval == "hour":
                bucket = sent_at.replace(minute=0, second=0, microsecond=0)
                bucket_key = bucket.strftime("%Y-%m-%d %H:00")
            elif interval == "week":
                # Start of week (Monday)
                days_since_monday = sent_at.weekday()
                week_start = sent_at - timedelta(days=days_since_monday)
                bucket = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
                bucket_key = bucket.strftime("%Y-%m-%d")
            else:  # day (default)
                bucket = sent_at.replace(hour=0, minute=0, second=0, microsecond=0)
                bucket_key = bucket.strftime("%Y-%m-%d")
            
            if bucket_key not in timeseries_data:
                timeseries_data[bucket_key] = {
                    "date": bucket_key,
                    "sent": 0,
                    "delivered": 0,
                    "opened": 0,
                    "clicked": 0,
                    "replied": 0,
                    "bounced": 0
                }
            
            # Count metrics
            timeseries_data[bucket_key]["sent"] += 1
            
            status = send.get("status", "")
            if status == "delivered" or status == "sent":
                timeseries_data[bucket_key]["delivered"] += 1
            elif status == "bounced":
                timeseries_data[bucket_key]["bounced"] += 1
            
            if send.get("opened", False):
                timeseries_data[bucket_key]["opened"] += 1
            if send.get("clicked", False):
                timeseries_data[bucket_key]["clicked"] += 1
            if send.get("replied", False):
                timeseries_data[bucket_key]["replied"] += 1
        
        # Convert to sorted list
        timeseries_list = sorted(timeseries_data.values(), key=lambda x: x["date"])
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "interval": interval,
            "data": timeseries_list
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns/{campaign_id}/analytics/funnel", response_model=Dict[str, Any])
async def get_campaign_funnel(campaign_id: str):
    """
    Get campaign conversion funnel.
    
    Returns funnel stages:
    - Sent: Total emails sent
    - Delivered: Successfully delivered (not bounced)
    - Opened: Unique opens
    - Clicked: Link clicks
    - Replied: Responses received
    
    Includes counts and conversion rates at each stage.
    """
    try:
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri)
        db = client['email_automation']
        
        from bson import ObjectId
        
        # Verify campaign exists
        campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Get all sends
        sends = list(db["campaign_sends"].find({"campaign_id": ObjectId(campaign_id)}))
        
        # Calculate funnel metrics
        total_sent = len(sends)
        delivered = sum(1 for s in sends if s.get("status") in ["delivered", "sent"])
        opened = sum(1 for s in sends if s.get("opened", False))
        clicked = sum(1 for s in sends if s.get("clicked", False))
        replied = sum(1 for s in sends if s.get("replied", False))
        bounced = sum(1 for s in sends if s.get("status") == "bounced")
        
        # Calculate rates
        def calc_rate(numerator, denominator):
            return round((numerator / denominator * 100), 2) if denominator > 0 else 0.0
        
        funnel_data = {
            "stages": ["Sent", "Delivered", "Opened", "Clicked", "Replied"],
            "counts": [total_sent, delivered, opened, clicked, replied],
            "rates": [
                100.0,  # Sent is baseline
                calc_rate(delivered, total_sent),
                calc_rate(opened, delivered),
                calc_rate(clicked, opened),
                calc_rate(replied, clicked)
            ]
        }
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "funnel": funnel_data,
            "summary": {
                "total_sent": total_sent,
                "delivered": delivered,
                "opened": opened,
                "clicked": clicked,
                "replied": replied,
                "bounced": bounced,
                "delivery_rate": calc_rate(delivered, total_sent),
                "open_rate": calc_rate(opened, delivered),
                "click_rate": calc_rate(clicked, opened),
                "reply_rate": calc_rate(replied, clicked),
                "bounce_rate": calc_rate(bounced, total_sent)
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns/{campaign_id}/analytics/by-segment", response_model=Dict[str, Any])
async def get_campaign_by_segment(
    campaign_id: str,
    segment_by: str = Query("industry", description="Segment by: 'industry', 'seniority', 'company_size', 'title'")
):
    """
    Get campaign performance broken down by audience segment.
    
    Analyze performance by:
    - Industry (Tech, Healthcare, Finance, etc.)
    - Seniority (C-Level, VP, Director, Manager, etc.)
    - Company size (Enterprise, Mid-market, SMB)
    - Job title
    
    Returns engagement metrics for each segment.
    """
    try:
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri)
        db = client['email_automation']
        
        from bson import ObjectId
        
        # Verify campaign exists
        campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Get recipients with their metadata
        recipients = list(db["campaign_recipients"].find({"campaign_id": ObjectId(campaign_id)}))
        
        # Group by segment
        segments = {}
        
        for recipient in recipients:
            # Determine segment value
            if segment_by == "industry":
                segment_value = recipient.get("industry", "Unknown")
            elif segment_by == "seniority":
                segment_value = recipient.get("seniority", "Unknown")
            elif segment_by == "company_size":
                segment_value = recipient.get("company_size", "Unknown")
            elif segment_by == "title":
                segment_value = recipient.get("title", "Unknown")
            else:
                segment_value = "Unknown"
            
            if segment_value not in segments:
                segments[segment_value] = {
                    "segment": segment_value,
                    "total": 0,
                    "sent": 0,
                    "delivered": 0,
                    "opened": 0,
                    "clicked": 0,
                    "replied": 0,
                    "bounced": 0
                }
            
            segments[segment_value]["total"] += 1
            
            # Get send data for this recipient
            recipient_id = recipient["_id"]
            sends = list(db["campaign_sends"].find({
                "campaign_id": ObjectId(campaign_id),
                "recipient_id": recipient_id
            }))
            
            for send in sends:
                segments[segment_value]["sent"] += 1
                
                status = send.get("status", "")
                if status in ["delivered", "sent"]:
                    segments[segment_value]["delivered"] += 1
                elif status == "bounced":
                    segments[segment_value]["bounced"] += 1
                
                if send.get("opened", False):
                    segments[segment_value]["opened"] += 1
                if send.get("clicked", False):
                    segments[segment_value]["clicked"] += 1
                if send.get("replied", False):
                    segments[segment_value]["replied"] += 1
        
        # Calculate rates for each segment
        for segment_data in segments.values():
            sent = segment_data["sent"]
            if sent > 0:
                segment_data["delivery_rate"] = round((segment_data["delivered"] / sent) * 100, 2)
                segment_data["open_rate"] = round((segment_data["opened"] / sent) * 100, 2)
                segment_data["click_rate"] = round((segment_data["clicked"] / sent) * 100, 2)
                segment_data["reply_rate"] = round((segment_data["replied"] / sent) * 100, 2)
                segment_data["bounce_rate"] = round((segment_data["bounced"] / sent) * 100, 2)
            else:
                segment_data["delivery_rate"] = 0.0
                segment_data["open_rate"] = 0.0
                segment_data["click_rate"] = 0.0
                segment_data["reply_rate"] = 0.0
                segment_data["bounce_rate"] = 0.0
        
        # Sort by total count descending
        segments_list = sorted(segments.values(), key=lambda x: x["total"], reverse=True)
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "segment_by": segment_by,
            "segments": segments_list
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns/{campaign_id}/analytics/engagement-heatmap", response_model=Dict[str, Any])
async def get_engagement_heatmap(campaign_id: str):
    """
    Get engagement heatmap data showing opens/clicks by day of week and hour.
    
    Returns a matrix showing when recipients are most engaged:
    - Rows: Days of week (Monday - Sunday)
    - Columns: Hours of day (0-23)
    - Values: Open/click counts
    
    Useful for optimizing send times.
    """
    try:
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri)
        db = client['email_automation']
        
        from bson import ObjectId
        
        # Verify campaign exists
        campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Get all sends with tracking data
        sends = list(db["campaign_sends"].find({"campaign_id": ObjectId(campaign_id)}))
        
        # Initialize heatmap matrix
        # 7 days x 24 hours
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        heatmap_opens = {day: {hour: 0 for hour in range(24)} for day in days}
        heatmap_clicks = {day: {hour: 0 for hour in range(24)} for day in days}
        
        for send in sends:
            # Track opens
            if send.get("opened", False):
                opened_at = send.get("opened_at")
                if opened_at:
                    day_of_week = days[opened_at.weekday()]
                    hour_of_day = opened_at.hour
                    heatmap_opens[day_of_week][hour_of_day] += 1
            
            # Track clicks
            if send.get("clicked", False):
                clicked_at = send.get("clicked_at")
                if clicked_at:
                    day_of_week = days[clicked_at.weekday()]
                    hour_of_day = clicked_at.hour
                    heatmap_clicks[day_of_week][hour_of_day] += 1
        
        # Convert to format suitable for frontend
        opens_matrix = []
        clicks_matrix = []
        
        for day in days:
            opens_row = [heatmap_opens[day][hour] for hour in range(24)]
            clicks_row = [heatmap_clicks[day][hour] for hour in range(24)]
            opens_matrix.append({"day": day, "hours": opens_row})
            clicks_matrix.append({"day": day, "hours": clicks_row})
        
        # Find peak engagement times
        max_opens = 0
        max_clicks = 0
        peak_open_time = {"day": "", "hour": 0}
        peak_click_time = {"day": "", "hour": 0}
        
        for day in days:
            for hour in range(24):
                if heatmap_opens[day][hour] > max_opens:
                    max_opens = heatmap_opens[day][hour]
                    peak_open_time = {"day": day, "hour": hour}
                if heatmap_clicks[day][hour] > max_clicks:
                    max_clicks = heatmap_clicks[day][hour]
                    peak_click_time = {"day": day, "hour": hour}
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "heatmap": {
                "opens": opens_matrix,
                "clicks": clicks_matrix
            },
            "insights": {
                "peak_open_time": peak_open_time,
                "peak_click_time": peak_click_time,
                "max_opens": max_opens,
                "max_clicks": max_clicks
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
