"""
CAMPAIGNS API ROUTER
====================

REST API endpoints for campaign management.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from bson import ObjectId
from pymongo import MongoClient

import os


router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


# ============== MODELS ==============

class CreateTemplateRequest(BaseModel):
    name: str
    subject: str
    body_html: str
    body_plain: Optional[str] = None
    category: str = "outreach"
    tags: List[str] = []


class SequenceStepRequest(BaseModel):
    template_id: str
    delay_days: int = 0
    delay_hours: int = 0
    condition: str = "always"


class CreateCampaignRequest(BaseModel):
    name: str
    from_mailbox_id: str
    from_email: str
    from_name: Optional[str] = None
    description: Optional[str] = None
    sequence_steps: List[SequenceStepRequest]
    settings: Optional[Dict[str, Any]] = None


class AddRecipientsRequest(BaseModel):
    recipients: List[Dict[str, Any]]
    deduplicate: bool = True


class CampaignActionRequest(BaseModel):
    action: str  # start, pause, resume, complete


# ============== DATABASE ==============

def get_db():
    """Get MongoDB database instance"""
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri)
    return client['email_automation']


def get_campaign_manager(db = Depends(get_db)):
    """Get campaign manager instance"""
    from ..campaigns.models import CampaignManager
    return CampaignManager(db)


# ============== TEMPLATE ENDPOINTS ==============

@router.post("/templates", response_model=Dict[str, Any])
async def create_template(
    request: CreateTemplateRequest,
    manager = Depends(get_campaign_manager)
):
    """Create a new email template"""
    template_id = manager.create_template(
        name=request.name,
        subject=request.subject,
        body_html=request.body_html,
        body_plain=request.body_plain,
        category=request.category,
        tags=request.tags
    )
    
    return {"success": True, "template_id": template_id}


@router.get("/templates", response_model=Dict[str, Any])
async def list_templates(
    category: Optional[str] = None,
    is_active: bool = True,
    db = Depends(get_db)
):
    """List email templates"""
    query = {"is_active": is_active}
    if category:
        query["category"] = category
    
    templates = list(db["email_templates"].find(query).sort("created_at", -1))
    
    for t in templates:
        t["id"] = str(t.pop("_id"))
    
    return {"templates": templates, "total": len(templates)}


@router.get("/templates/{template_id}", response_model=Dict[str, Any])
async def get_template(
    template_id: str,
    manager = Depends(get_campaign_manager)
):
    """Get a template by ID"""
    template = manager.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    template["id"] = str(template.pop("_id"))
    return template


@router.post("/templates/{template_id}/preview", response_model=Dict[str, Any])
async def preview_template(
    template_id: str,
    variables: Dict[str, Any],
    manager = Depends(get_campaign_manager)
):
    """Preview a template with variables"""
    try:
        rendered = manager.render_template(template_id, variables)
        return {"success": True, **rendered}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============== CAMPAIGN ENDPOINTS ==============

@router.post("", response_model=Dict[str, Any])
async def create_campaign(
    request: CreateCampaignRequest,
    manager = Depends(get_campaign_manager)
):
    """Create a new campaign"""
    steps = [step.model_dump() for step in request.sequence_steps]
    
    campaign_id = manager.create_campaign(
        name=request.name,
        from_mailbox_id=request.from_mailbox_id,
        from_email=request.from_email,
        from_name=request.from_name,
        description=request.description,
        sequence_steps=steps,
        settings=request.settings
    )
    
    return {"success": True, "campaign_id": campaign_id}


@router.get("", response_model=Dict[str, Any])
async def list_campaigns(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db = Depends(get_db)
):
    """List campaigns"""
    query = {}
    if status:
        query["status"] = status
    
    total = db["campaigns"].count_documents(query)
    skip = (page - 1) * page_size
    
    campaigns = list(db["campaigns"].find(query).sort("created_at", -1).skip(skip).limit(page_size))
    
    for c in campaigns:
        c["id"] = str(c.pop("_id"))
    
    return {
        "campaigns": campaigns,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/{campaign_id}", response_model=Dict[str, Any])
async def get_campaign(
    campaign_id: str,
    manager = Depends(get_campaign_manager)
):
    """Get a campaign by ID"""
    campaign = manager.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign["id"] = str(campaign.pop("_id"))
    return campaign


@router.post("/{campaign_id}/action", response_model=Dict[str, Any])
async def campaign_action(
    campaign_id: str,
    request: CampaignActionRequest,
    manager = Depends(get_campaign_manager)
):
    """Perform action on campaign (start, pause, resume, complete)"""
    from ..campaigns.models import CampaignStatus
    
    status_map = {
        "start": CampaignStatus.ACTIVE,
        "pause": CampaignStatus.PAUSED,
        "resume": CampaignStatus.ACTIVE,
        "complete": CampaignStatus.COMPLETED
    }
    
    new_status = status_map.get(request.action)
    if not new_status:
        raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")
    
    success = manager.update_campaign_status(campaign_id, new_status)
    
    if not success:
        raise HTTPException(status_code=404, detail="Campaign not found or status unchanged")
    
    return {"success": True, "new_status": new_status.value}


@router.get("/{campaign_id}/analytics", response_model=Dict[str, Any])
async def get_campaign_analytics(
    campaign_id: str,
    manager = Depends(get_campaign_manager)
):
    """Get campaign analytics"""
    analytics = manager.get_campaign_analytics(campaign_id)
    if not analytics:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    return analytics


# ============== RECIPIENT ENDPOINTS ==============

@router.post("/{campaign_id}/recipients", response_model=Dict[str, Any])
async def add_recipients(
    campaign_id: str,
    request: AddRecipientsRequest,
    manager = Depends(get_campaign_manager)
):
    """Add recipients to a campaign"""
    result = manager.add_recipients(
        campaign_id=campaign_id,
        recipients=request.recipients,
        deduplicate=request.deduplicate
    )
    
    return {"success": True, **result}


@router.get("/{campaign_id}/recipients", response_model=Dict[str, Any])
async def list_recipients(
    campaign_id: str,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db = Depends(get_db)
):
    """List recipients for a campaign"""
    query = {"campaign_id": campaign_id}
    if status:
        query["status"] = status
    
    total = db["campaign_recipients"].count_documents(query)
    skip = (page - 1) * page_size
    
    recipients = list(db["campaign_recipients"].find(query).sort("added_at", -1).skip(skip).limit(page_size))
    
    for r in recipients:
        r["id"] = str(r.pop("_id"))
    
    return {
        "recipients": recipients,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.post("/{campaign_id}/recipients/import-csv", response_model=Dict[str, Any])
async def import_recipients_csv(
    campaign_id: str,
    # File upload handling would go here
    db = Depends(get_db)
):
    """Import recipients from CSV"""
    # This would handle file upload and parsing
    raise HTTPException(status_code=501, detail="CSV import not yet implemented")


# ============== UNSUBSCRIBE ENDPOINT ==============

@router.get("/unsubscribe/{campaign_id}/{recipient_id}")
async def unsubscribe(
    campaign_id: str,
    recipient_id: str,
    db = Depends(get_db)
):
    """Handle unsubscribe request"""
    from ..campaigns.models import RecipientStatus
    
    result = db["campaign_recipients"].update_one(
        {"_id": ObjectId(recipient_id), "campaign_id": campaign_id},
        {
            "$set": {
                "status": RecipientStatus.UNSUBSCRIBED.value,
                "unsubscribed_at": datetime.utcnow()
            }
        }
    )
    
    if result.modified_count == 0:
        return {"message": "Already unsubscribed or recipient not found"}
    
    return {"message": "Successfully unsubscribed"}
