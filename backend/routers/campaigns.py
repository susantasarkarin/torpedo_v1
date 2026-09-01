"""
CAMPAIGNS API ROUTER
====================

REST API endpoints for campaign management.
"""

from datetime import datetime
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query, HTTPException, Depends, BackgroundTasks, Body
from pydantic import BaseModel, Field
from bson import ObjectId
from pymongo import MongoClient

import os

logger = logging.getLogger(__name__)

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


# ============================================================================
# ASYNC CAMPAIGN ENDPOINTS
# ============================================================================
# These endpoints return immediately with operation_id for long-running tasks

@router.post("/{campaign_id}/async/recipients/bulk-add", response_model=Dict[str, Any])
async def start_async_bulk_add_recipients(
    campaign_id: str,
    recipients: List[Dict[str, Any]] = Body(...),
    db = Depends(get_db)
):
    """
    Start async bulk addition of recipients to campaign
    Returns operation_id immediately, poll for status
    
    Body:
    [
        {"email": "user1@example.com", "name": "User 1", "custom_fields": {...}},
        {"email": "user2@example.com", "name": "User 2", "custom_fields": {...}},
        ...
    ]
    """
    try:
        # Verify campaign exists
        campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        if not recipients or len(recipients) == 0:
            raise HTTPException(status_code=400, detail="No recipients provided")
        
        # Start async task
        try:
            from tasks.async_helpers import start_campaign_recipients_add
            operation_id = start_campaign_recipients_add(campaign_id, recipients)
            
            return {
                "status": "started",
                "operation_id": operation_id,
                "poll_url": f"/operations/async/{operation_id}/status",
                "message": f"Bulk add started for {len(recipients)} recipients"
            }
        except ImportError:
            raise HTTPException(status_code=503, detail="Async tasks not configured")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting async bulk add: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{campaign_id}/async/recipients/import-csv", response_model=Dict[str, Any])
async def start_async_import_csv(
    campaign_id: str,
    data: Dict[str, Any] = Body(...),
    db = Depends(get_db)
):
    """
    Start async CSV import of recipients
    Returns operation_id immediately, poll for status
    
    Body:
    {
        "csv_data": "base64_encoded_csv_content",
        "column_mapping": {"email_column": "email", "name_column": "name"},
        "skip_duplicates": true
    }
    """
    try:
        # Verify campaign exists
        campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        csv_data = data.get('csv_data')
        column_mapping = data.get('column_mapping', {})
        skip_duplicates = data.get('skip_duplicates', True)
        
        if not csv_data:
            raise HTTPException(status_code=400, detail="No CSV data provided")
        
        try:
            from tasks.async_helpers import start_campaign_csv_import
            operation_id = start_campaign_csv_import(
                campaign_id, 
                csv_data, 
                column_mapping,
                skip_duplicates
            )
            
            return {
                "status": "started",
                "operation_id": operation_id,
                "poll_url": f"/operations/async/{operation_id}/status",
                "message": "CSV import started"
            }
        except ImportError:
            raise HTTPException(status_code=503, detail="Async tasks not configured")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting async CSV import: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{campaign_id}/async/analytics", response_model=Dict[str, Any])
async def start_async_generate_analytics(
    campaign_id: str,
    data: Dict[str, Any] = Body(default={}),
    db = Depends(get_db)
):
    """
    Start async generation of comprehensive campaign analytics
    Returns operation_id immediately, poll for status
    
    Body (optional):
    {
        "include_recipient_details": false,
        "group_by_day": true
    }
    """
    try:
        # Verify campaign exists
        campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        include_details = data.get('include_recipient_details', False)
        group_by_day = data.get('group_by_day', True)
        
        try:
            from tasks.async_helpers import start_campaign_analytics_generation
            operation_id = start_campaign_analytics_generation(
                campaign_id,
                include_details,
                group_by_day
            )
            
            return {
                "status": "started",
                "operation_id": operation_id,
                "poll_url": f"/operations/async/{operation_id}/status",
                "message": "Analytics generation started"
            }
        except ImportError:
            raise HTTPException(status_code=503, detail="Async tasks not configured")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting async analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/async/reports/{report_id}", response_model=Dict[str, Any])
async def get_campaign_report(
    report_id: str,
    db = Depends(get_db)
):
    """
    Retrieve a generated campaign report by ID
    """
    try:
        report = db["campaign_reports"].find_one({"_id": ObjectId(report_id)})
        
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        # Convert ObjectId to string
        report["_id"] = str(report["_id"])
        if "campaign_id" in report:
            report["campaign_id"] = str(report["campaign_id"])
        
        return report
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving campaign report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== A/B TESTING ENDPOINTS ==============

@router.post("/{campaign_id}/ab-test/setup", response_model=Dict[str, Any])
async def setup_ab_test(
    campaign_id: str,
    test_name: str = Body(..., description="Name for this A/B test"),
    variants: List[Dict[str, Any]] = Body(..., description="List of test variants"),
    focus_metric: str = Body("open_rate", description="Primary metric to optimize"),
    auto_select_winner: bool = Body(False, description="Auto-select winner when significant"),
    db = Depends(get_db)
):
    """
    Configure A/B test for a campaign.
    
    Example variants:
    [
        {
            "variant_id": "A",
            "name": "Short Subject",
            "subject_line": "Quick question",
            "template_id": "template_abc"
        },
        {
            "variant_id": "B", 
            "name": "Long Subject",
            "subject_line": "I noticed your company does X - can we help?",
            "template_id": "template_xyz"
        }
    ]
    """
    try:
        # Verify campaign exists
        campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Create A/B test configuration
        ab_test = {
            "campaign_id": ObjectId(campaign_id),
            "test_name": test_name,
            "variants": variants,
            "focus_metric": focus_metric,
            "auto_select_winner": auto_select_winner,
            "status": "active",
            "winner_declared": False,
            "created_at": datetime.utcnow()
        }
        
        # Insert into ab_tests collection
        result = db["ab_tests"].insert_one(ab_test)
        test_id = str(result.inserted_id)
        
        # Update campaign with A/B test flag
        db["campaigns"].update_one(
            {"_id": ObjectId(campaign_id)},
            {"$set": {
                "ab_test_enabled": True,
                "ab_test_id": ObjectId(test_id)
            }}
        )
        
        return {
            "success": True,
            "test_id": test_id,
            "campaign_id": campaign_id,
            "test_name": test_name,
            "variants": len(variants),
            "message": "A/B test configured successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{campaign_id}/ab-test/results", response_model=Dict[str, Any])
async def get_ab_test_results(
    campaign_id: str,
    analyze_with_agent: bool = Query(False, description="Use ABTestAnalyzerAgent for deep analysis"),
    db = Depends(get_db)
):
    """
    Get A/B test results with variant performance and statistical significance.
    
    Optionally analyzes with ABTestAnalyzerAgent to get:
    - Winner identification
    - Why the winner won
    - Next variant suggestions
    """
    try:
        # Get A/B test configuration
        ab_test = db["ab_tests"].find_one({"campaign_id": ObjectId(campaign_id)})
        if not ab_test:
            raise HTTPException(status_code=404, detail="No A/B test found for this campaign")
        
        # Get recipient performance by variant
        variants_performance = []
        
        for variant in ab_test.get("variants", []):
            variant_id = variant.get("variant_id")
            
            # Query campaign sends for this variant
            sends = list(db["campaign_sends"].find({
                "campaign_id": ObjectId(campaign_id),
                "variant_id": variant_id
            }))
            
            emails_sent = len(sends)
            opens = sum(1 for s in sends if s.get("opened"))
            clicks = sum(1 for s in sends if s.get("clicked"))
            replies = sum(1 for s in sends if s.get("replied"))
            conversions = sum(1 for s in sends if s.get("converted"))
            
            variants_performance.append({
                "variant_id": variant_id,
                "variant_name": variant.get("name", variant_id),
                "emails_sent": emails_sent,
                "opens": opens,
                "clicks": clicks,
                "replies": replies,
                "conversions": conversions,
                "open_rate": opens / emails_sent if emails_sent > 0 else 0,
                "click_rate": clicks / emails_sent if emails_sent > 0 else 0,
                "reply_rate": replies / emails_sent if emails_sent > 0 else 0,
                "conversion_rate": conversions / emails_sent if emails_sent > 0 else 0,
                "subject_line": variant.get("subject_line", ""),
                "cta_text": variant.get("cta_text", ""),
                "email_length": variant.get("email_length", "medium")
            })
        
        # Calculate statistical significance (simple z-test)
        winner = None
        is_significant = False
        
        if len(variants_performance) >= 2:
            focus_metric = ab_test.get("focus_metric", "open_rate")
            sorted_variants = sorted(
                variants_performance,
                key=lambda v: v.get(focus_metric, 0),
                reverse=True
            )
            
            winner = sorted_variants[0]
            
            # Simple significance check (sample size > 100 and >10% improvement)
            if winner["emails_sent"] >= 100:
                control = sorted_variants[1]
                improvement = (winner[focus_metric] - control[focus_metric]) / max(control[focus_metric], 0.001)
                is_significant = improvement > 0.10
        
        agent_analysis = None
        
        # Analyze with ABTestAnalyzerAgent if requested
        if analyze_with_agent:
            try:
                from ..agents.ab_test_agent import ABTestAnalyzerAgent
                
                agent = ABTestAnalyzerAgent()
                
                # Format test data for agent
                test_data = {
                    "test_name": ab_test.get("test_name"),
                    "control_variant": variants_performance[0] if variants_performance else {},
                    "test_variants": variants_performance[1:] if len(variants_performance) > 1 else []
                }
                
                result = await agent.run([test_data])
                agent_analysis = result.model_dump()
                
            except Exception as e:
                logger.warning(f"ABTestAnalyzerAgent analysis failed: {e}")
        
        return {
            "success": True,
            "test_id": str(ab_test["_id"]),
            "test_name": ab_test.get("test_name"),
            "campaign_id": campaign_id,
            "variants": variants_performance,
            "winner": winner,
            "is_statistically_significant": is_significant,
            "focus_metric": ab_test.get("focus_metric"),
            "agent_analysis": agent_analysis
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{campaign_id}/ab-test/declare-winner", response_model=Dict[str, Any])
async def declare_ab_test_winner(
    campaign_id: str,
    winner_variant_id: str = Body(..., description="Variant ID to declare as winner"),
    reason: Optional[str] = Body(None, description="Reason for declaring this winner"),
    db = Depends(get_db)
):
    """
    Manually declare an A/B test winner.
    
    This stops the test and routes all future sends to the winning variant.
    """
    try:
        # Get A/B test
        ab_test = db["ab_tests"].find_one({"campaign_id": ObjectId(campaign_id)})
        if not ab_test:
            raise HTTPException(status_code=404, detail="No A/B test found for this campaign")
        
        # Verify variant exists
        variant_ids = [v["variant_id"] for v in ab_test.get("variants", [])]
        if winner_variant_id not in variant_ids:
            raise HTTPException(status_code=400, detail=f"Invalid variant ID: {winner_variant_id}")
        
        # Update A/B test
        db["ab_tests"].update_one(
            {"_id": ab_test["_id"]},
            {"$set": {
                "status": "completed",
                "winner_declared": True,
                "winner_variant_id": winner_variant_id,
                "winner_reason": reason,
                "completed_at": datetime.utcnow()
            }}
        )
        
        # Update campaign to use winning variant only
        db["campaigns"].update_one(
            {"_id": ObjectId(campaign_id)},
            {"$set": {
                "ab_test_enabled": False,
                "winning_variant_id": winner_variant_id
            }}
        )
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "winner_variant_id": winner_variant_id,
            "reason": reason,
            "message": f"Winner declared: Variant {winner_variant_id}"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{campaign_id}/ab-test/auto-select", response_model=Dict[str, Any])
async def auto_select_ab_winner(
    campaign_id: str,
    minimum_sample_size: int = Body(100, description="Minimum sends per variant"),
    significance_threshold: float = Body(0.95, description="Confidence threshold"),
    db = Depends(get_db)
):
    """
    Trigger automatic winner selection based on statistical significance.
    
    Only selects a winner if:
    - All variants have minimum sample size
    - Winner has significantly better performance
    """
    try:
        # Get results
        results = await get_ab_test_results(campaign_id, analyze_with_agent=False, db=db)
        
        variants = results.get("variants", [])
        
        # Check if we have enough data
        insufficient_data = [v for v in variants if v["emails_sent"] < minimum_sample_size]
        if insufficient_data:
            return {
                "success": False,
                "message": f"Insufficient data: {len(insufficient_data)} variants need more samples",
                "minimum_required": minimum_sample_size,
                "variants_pending": [v["variant_id"] for v in insufficient_data]
            }
        
        # Check if already significant
        if not results.get("is_statistically_significant"):
            return {
                "success": False,
                "message": "No statistically significant winner yet",
                "continue_testing": True
            }
        
        # Auto-declare winner
        winner = results.get("winner")
        if winner:
            await declare_ab_test_winner(
                campaign_id,
                winner_variant_id=winner["variant_id"],
                reason=f"Auto-selected: {winner['variant_name']} had {winner.get(results['focus_metric'], 0):.2%} {results['focus_metric']}",
                db=db
            )
            
            return {
                "success": True,
                "winner_variant_id": winner["variant_id"],
                "winner_name": winner["variant_name"],
                "winning_metric_value": winner.get(results["focus_metric"]),
                "message": "Winner automatically selected"
            }
        
        return {
            "success": False,
            "message": "Could not determine winner"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== PHASE 2: ML-BASED SEND TIME OPTIMIZATION ==============

@router.get("/leads/{lead_id}/optimal-send-time", response_model=Dict[str, Any])
async def get_lead_optimal_send_time(
    lead_id: str,
    db = Depends(get_db)
):
    """
    Get predicted optimal send time for a specific lead.
    
    Uses historical engagement data to predict best day/hour for sending emails.
    
    Args:
        lead_id: Lead/recipient ID
    
    Returns:
        Optimal send time prediction with confidence score
    """
    try:
        from ..campaigns.send_time_optimizer import SendTimeOptimizer
        
        optimizer = SendTimeOptimizer(db)
        optimal_time = optimizer.predict_optimal_send_time(lead_id)
        
        return {
            "success": True,
            "lead_id": lead_id,
            "optimal_send_time": optimal_time
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing send time: {str(e)}")


@router.get("/{campaign_id}/send-time-analysis", response_model=Dict[str, Any])
async def get_campaign_send_time_analysis(
    campaign_id: str,
    db = Depends(get_db)
):
    """
    Analyze send time patterns for all recipients in a campaign.
    
    Returns optimal send times and engagement patterns by hour/day.
    
    Args:
        campaign_id: Campaign ID
    
    Returns:
        Send time analysis and recommendations
    """
    try:
        from ..campaigns.send_time_optimizer import SendTimeOptimizer
        from ..analytics.engagement_patterns import EngagementPatternAnalyzer
        
        # Get campaign
        db_obj = db
        campaign = db_obj.campaigns.find_one({"_id": ObjectId(campaign_id) if isinstance(campaign_id, str) else campaign_id})
        
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Analyze send times
        optimizer = SendTimeOptimizer(db_obj)
        schedule = optimizer.batch_optimize_schedule(campaign_id)
        
        # Get segment performance
        analyzer = EngagementPatternAnalyzer(db_obj)
        recipients = list(db_obj.campaign_recipients.find(
            {"campaign_id": ObjectId(campaign_id) if isinstance(campaign_id, str) else campaign_id}
        ).limit(1000))
        
        segment_analysis = analyzer.analyze_segment_performance({
            "_id": {"$in": [r.get("lead_id") for r in recipients]}
        })
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name"),
            "send_time_analysis": schedule,
            "segment_analysis": segment_analysis,
            "summary": {
                "total_recipients": len(recipients),
                "optimized_recipients": len(schedule.get("optimized_recipients", [])),
                "avg_confidence": sum(r.get("confidence", 0) for r in schedule.get("optimized_recipients", [])) / max(1, len(schedule.get("optimized_recipients", [])))
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing send times: {str(e)}")


@router.post("/{campaign_id}/optimize-schedule", response_model=Dict[str, Any])
async def optimize_campaign_schedule(
    campaign_id: str,
    db = Depends(get_db)
):
    """
    Optimize campaign schedule by reordering recipients based on optimal send times.
    
    Reorders recipients to group by optimal send hour/day for efficient batch sending.
    
    Args:
        campaign_id: Campaign ID to optimize
    
    Returns:
        Optimized schedule with recipient order and send time recommendations
    """
    try:
        from ..campaigns.send_time_optimizer import SendTimeOptimizer
        
        db_obj = db
        
        # Verify campaign exists
        campaign = db_obj.campaigns.find_one({
            "_id": ObjectId(campaign_id) if isinstance(campaign_id, str) else campaign_id
        })
        
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Optimize schedule
        optimizer = SendTimeOptimizer(db_obj)
        optimized = optimizer.batch_optimize_schedule(campaign_id)
        
        # Store optimization in campaign metadata
        db_obj.campaigns.update_one(
            {"_id": ObjectId(campaign_id) if isinstance(campaign_id, str) else campaign_id},
            {
                "$set": {
                    "schedule_optimization": {
                        "optimized_at": datetime.utcnow(),
                        "metrics": optimized.get("metrics", {}),
                        "optimization_status": "completed"
                    }
                }
            }
        )
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "message": "Campaign schedule optimized successfully",
            "optimization": optimized,
            "action_items": [
                f"Send to {optimized['metrics']['with_predictions']} recipients with ML predictions",
                f"Use fallback defaults for {optimized['metrics']['fallback_defaults']} recipients",
                "Group sends by optimal hour for efficiency",
                f"High confidence predictions: {optimized['metrics']['confidence_high']} recipients"
            ]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error optimizing schedule: {str(e)}")


# ============== PHASE 2: ENGAGEMENT PATTERNS & ANALYSIS ==============

@router.get("/leads/{lead_id}/engagement-patterns", response_model=Dict[str, Any])
async def get_lead_engagement_patterns(
    lead_id: str,
    db = Depends(get_db)
):
    """
    Detect and analyze engagement patterns for a lead.
    
    Returns:
    - Response latency (how quickly they open/click)
    - Preferred days of week
    - Engagement momentum (trending up/down)
    - Reply likelihood
    
    Args:
        lead_id: Lead/recipient ID
    
    Returns:
        Engagement patterns and behavior analysis
    """
    try:
        from ..analytics.engagement_patterns import EngagementPatternAnalyzer
        
        analyzer = EngagementPatternAnalyzer(db)
        patterns = analyzer.detect_patterns(lead_id)
        
        return {
            "success": True,
            "lead_id": lead_id,
            "patterns": patterns
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error detecting patterns: {str(e)}")


@router.get("/{campaign_id}/segment-performance", response_model=Dict[str, Any])
async def analyze_campaign_segment_performance(
    campaign_id: str,
    industry: Optional[str] = Query(None),
    seniority: Optional[str] = Query(None),
    db = Depends(get_db)
):
    """
    Analyze performance metrics for a campaign segment.
    
    Groups recipients by industry/seniority and calculates aggregate metrics.
    
    Args:
        campaign_id: Campaign ID
        industry: Optional industry filter
        seniority: Optional seniority level filter
    
    Returns:
        Segment performance analysis and recommendations
    """
    try:
        from ..analytics.engagement_patterns import EngagementPatternAnalyzer
        
        # Get campaign recipients
        campaign_obj_id = ObjectId(campaign_id) if isinstance(campaign_id, str) else campaign_id
        recipients = list(db.campaign_recipients.find(
            {"campaign_id": campaign_obj_id}
        ).limit(1000))
        
        if not recipients:
            raise HTTPException(status_code=404, detail="No recipients found for campaign")
        
        # Build filter
        segment_filter = {"_id": {"$in": [r.get("lead_id") for r in recipients]}}
        if industry:
            segment_filter["industry"] = industry
        if seniority:
            segment_filter["seniority_level"] = seniority
        
        # Analyze segment
        analyzer = EngagementPatternAnalyzer(db)
        analysis = analyzer.analyze_segment_performance(segment_filter)
        
        # Get frequency recommendations
        if industry and seniority:
            frequency = analyzer.suggest_contact_frequency(industry, seniority)
        else:
            frequency = {}
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "segment_filter": {
                "industry": industry,
                "seniority": seniority
            },
            "performance_analysis": analysis,
            "frequency_recommendations": frequency
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing segment: {str(e)}")


# ============== PHASE 2: ML-BASED LEAD SCORING ==============

@router.get("/leads/{lead_id}/reply-score", response_model=Dict[str, Any])
async def get_lead_reply_score(
    lead_id: str,
    db = Depends(get_db)
):
    """
    Get ML-predicted reply probability for a lead.
    
    Predicts likelihood of reply based on historical engagement and profile.
    
    Args:
        lead_id: Lead/recipient ID
    
    Returns:
        Reply probability score with factors and recommendation
    """
    try:
        from ..agents.ml_lead_scorer import MLLeadScorer
        
        # Get lead
        lead = db.leads.find_one({
            "_id": ObjectId(lead_id) if isinstance(lead_id, str) else lead_id
        })
        
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        # Score lead
        scorer = MLLeadScorer(db)
        score = scorer.score_lead_for_reply(lead)
        
        return {
            "success": True,
            "lead_id": lead_id,
            "reply_score": score
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scoring lead: {str(e)}")


@router.post("/{campaign_id}/prioritize-leads", response_model=Dict[str, Any])
async def prioritize_campaign_leads(
    campaign_id: str,
    limit: Optional[int] = Query(None, ge=1, le=1000),
    db = Depends(get_db)
):
    """
    Prioritize campaign recipients by reply probability using ML scoring.
    
    Scores all recipients and returns them ranked by predicted reply likelihood.
    
    Args:
        campaign_id: Campaign ID
        limit: Optional limit on results (default: return all)
    
    Returns:
        Prioritized leads sorted by reply probability
    """
    try:
        from ..agents.ml_lead_scorer import MLLeadScorer
        
        campaign_obj_id = ObjectId(campaign_id) if isinstance(campaign_id, str) else campaign_id
        
        # Get campaign recipients
        recipients = list(db.campaign_recipients.find(
            {"campaign_id": campaign_obj_id}
        ))
        
        if not recipients:
            raise HTTPException(status_code=404, detail="No recipients found")
        
        lead_ids = [str(r.get("lead_id")) for r in recipients]
        
        # Score and prioritize
        scorer = MLLeadScorer(db)
        prioritized = scorer.prioritize_leads(lead_ids, limit=limit)
        
        # Calculate statistics
        reply_probs = [p.get("probability", 0) for p in prioritized]
        high_probability_count = sum(1 for p in reply_probs if p >= 0.6)
        medium_probability_count = sum(1 for p in reply_probs if 0.4 <= p < 0.6)
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "total_scored": len(prioritized),
            "prioritized_leads": prioritized,
            "statistics": {
                "avg_probability": round(sum(reply_probs) / len(reply_probs), 3) if reply_probs else 0,
                "high_probability_count": high_probability_count,
                "medium_probability_count": medium_probability_count,
                "low_probability_count": len(reply_probs) - high_probability_count - medium_probability_count
            },
            "recommendations": [
                f"Focus heavy outreach on {high_probability_count} high-probability leads",
                f"Use nurture sequences for {medium_probability_count} medium-probability leads",
                "Schedule optimization by optimal send times for all leads"
            ]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error prioritizing leads: {str(e)}")
