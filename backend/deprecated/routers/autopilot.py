"""
Campaign Autopilot API Router
Autonomous campaign management and optimization
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Optional, Dict
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..database import get_database
from ..agents.campaign_autopilot import CampaignAutopilot, AutopilotService

router = APIRouter(prefix="/api/autopilot", tags=["autopilot"])


@router.post("/campaigns/{campaign_id}/optimize")
async def optimize_campaign(
    campaign_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Run autonomous optimization for specific campaign
    
    Analyzes performance and applies safe improvements automatically
    """
    try:
        autopilot = CampaignAutopilot(db)
        result = await autopilot.auto_optimize_campaign(campaign_id)
        
        return {
            "status": "success",
            **result
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns/{campaign_id}/suggestions")
async def get_optimization_suggestions(
    campaign_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get improvement suggestions without applying them
    
    Returns list of recommended actions for campaign
    """
    try:
        autopilot = CampaignAutopilot(db)
        suggestions = await autopilot.suggest_improvements(campaign_id)
        
        return {
            "campaign_id": campaign_id,
            "suggestions": suggestions,
            "generated_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/{campaign_id}/enable")
async def enable_autopilot(
    campaign_id: str,
    settings: Dict = Body(default={}),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Enable autopilot for campaign
    
    Campaign will be automatically optimized on each cycle
    """
    try:
        service = AutopilotService(db)
        result = await service.enable_autopilot(campaign_id, settings)
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/{campaign_id}/disable")
async def disable_autopilot(
    campaign_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Disable autopilot for campaign
    
    Manual optimization will be required
    """
    try:
        service = AutopilotService(db)
        result = await service.disable_autopilot(campaign_id)
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns/{campaign_id}/history")
async def get_optimization_history(
    campaign_id: str,
    days: int = Query(30, ge=1, le=365),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get optimization history for campaign
    
    Shows all autopilot actions taken over time
    """
    try:
        autopilot = CampaignAutopilot(db)
        history = await autopilot.get_optimization_history(campaign_id, days)
        
        return {
            "campaign_id": campaign_id,
            "history": history,
            "total_optimizations": len(history),
            "days_back": days
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pause-underperformers")
async def pause_underperforming_campaigns(
    threshold: float = Query(0.05, ge=0.0, le=1.0, description="Minimum engagement threshold"),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Automatically pause campaigns performing below threshold
    
    Protects sender reputation by stopping low-performing campaigns
    """
    try:
        autopilot = CampaignAutopilot(db)
        paused = await autopilot.pause_underperformers(threshold)
        
        return {
            "status": "success",
            "paused_campaigns": paused,
            "count": len(paused),
            "threshold": threshold,
            "paused_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run-cycle")
async def run_autopilot_cycle(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Run complete autopilot optimization cycle
    
    Optimizes all eligible campaigns with autopilot enabled
    """
    try:
        autopilot = CampaignAutopilot(db)
        result = await autopilot.run_autopilot_cycle()
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_autopilot_status(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get overall autopilot system status
    
    Shows how many campaigns have autopilot enabled
    """
    try:
        service = AutopilotService(db)
        status = await service.get_autopilot_status()
        
        return {
            "status": "operational",
            **status,
            "checked_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns")
async def get_autopilot_campaigns(
    status: Optional[str] = Query(None, description="Filter by status (enabled/disabled)"),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get list of campaigns with autopilot status
    """
    try:
        query = {}
        if status == "enabled":
            query['autopilot_enabled'] = True
        elif status == "disabled":
            query['autopilot_enabled'] = False
        
        campaigns = await db.campaigns.find(query).to_list(length=None)
        
        campaign_list = []
        for campaign in campaigns:
            campaign_list.append({
                "campaign_id": str(campaign['_id']),
                "name": campaign.get('name', 'Unnamed'),
                "autopilot_enabled": campaign.get('autopilot_enabled', False),
                "last_optimization": campaign.get('last_optimization_date'),
                "performance_score": campaign.get('performance_score', 0)
            })
        
        return {
            "campaigns": campaign_list,
            "count": len(campaign_list),
            "filter": status or "all"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
