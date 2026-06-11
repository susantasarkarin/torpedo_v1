"""
Predictions API Router
AI-driven predictions for reply probability, meeting booking, and lead prioritization
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..database import get_database
from ..ml.reply_predictor import ReplyPredictionService
from ..ml.meeting_predictor import MeetingPredictionService
from ..agents.lead_prioritizer import LeadPrioritizerService

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("/reply-probability")
async def get_reply_predictions(
    campaign_id: Optional[str] = Query(None, description="Filter by campaign ID"),
    limit: int = Query(50, ge=1, le=200),
    min_probability: float = Query(0.0, ge=0.0, le=1.0),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get AI-powered reply probability predictions for leads
    
    Returns predictions sorted by probability (highest first)
    """
    try:
        service = ReplyPredictionService(db)
        
        if campaign_id:
            predictions = await service.predict_for_campaign(campaign_id)
        else:
            predictions = await service.get_hot_leads(limit=limit, min_probability=min_probability)
        
        # Get model info
        model_info = service.predictor.get_model_performance()
        
        return {
            "predictions": predictions[:limit],
            "model_info": model_info,
            "generated_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/meeting-probability")
async def get_meeting_predictions(
    threshold: float = Query(0.3, ge=0.0, le=1.0),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get meeting booking probability predictions
    
    Returns leads segmented by readiness level
    """
    try:
        service = MeetingPredictionService(db)
        dashboard = await service.get_meeting_ready_dashboard()
        
        return {
            "predictions": [
                *[{**lead, 'readiness': 'ready_now'} for lead in dashboard['ready_now']],
                *[{**lead, 'readiness': 'almost_ready'} for lead in dashboard['almost_ready']],
                *[{**lead, 'readiness': 'warming_up'} for lead in dashboard['warming_up']]
            ],
            "summary": {
                "ready_now": len(dashboard['ready_now']),
                "almost_ready": len(dashboard['almost_ready']),
                "warming_up": len(dashboard['warming_up']),
                "total": dashboard['total_leads_analyzed']
            },
            "generated_at": dashboard['generated_at']
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hot-leads")
async def get_hot_leads(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get hottest leads with highest priority scores
    
    These are leads most likely to engage today
    """
    try:
        # Initialize services
        reply_service = ReplyPredictionService(db)
        prioritizer_service = LeadPrioritizerService(db, reply_service.predictor)
        
        # Get hot leads
        hot_leads = await prioritizer_service.prioritizer.surface_hot_leads(limit=limit)
        
        return {
            "leads": hot_leads,
            "count": len(hot_leads),
            "generated_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/priority-distribution")
async def get_priority_distribution(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get distribution of leads across priority levels
    """
    try:
        reply_service = ReplyPredictionService(db)
        prioritizer = LeadPrioritizerService(db, reply_service.predictor)
        
        distribution = await prioritizer.prioritizer.get_priority_distribution()
        
        return distribution
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-priorities")
async def update_lead_priorities(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Trigger batch update of all lead priority scores
    
    This recalculates priority scores for all active leads
    """
    try:
        reply_service = ReplyPredictionService(db)
        prioritizer = LeadPrioritizerService(db, reply_service.predictor)
        
        result = await prioritizer.prioritizer.update_lead_priorities()
        
        return {
            "status": "success",
            **result
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily-action-list")
async def get_daily_action_list(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get prioritized daily action list
    
    Returns top leads to contact today with recommended actions
    """
    try:
        reply_service = ReplyPredictionService(db)
        prioritizer = LeadPrioritizerService(db, reply_service.predictor)
        
        action_list = await prioritizer.get_daily_priority_list()
        
        return action_list
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retrain-model")
async def retrain_prediction_model(
    model_type: str = Query("reply", description="Model type: 'reply' or 'meeting'"),
    days_back: int = Query(90, ge=7, le=365),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Retrain ML prediction model with latest data
    
    This should be run periodically to keep model accurate
    """
    try:
        if model_type == "reply":
            service = ReplyPredictionService(db)
            result = await service.predictor.retrain_model(days_back=days_back)
        elif model_type == "meeting":
            service = MeetingPredictionService(db)
            # Would implement similar retrain method for meeting predictor
            result = {"status": "not_implemented", "message": "Meeting model retraining coming soon"}
        else:
            raise HTTPException(status_code=400, detail=f"Unknown model type: {model_type}")
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lead/{lead_id}/predictions")
async def get_lead_predictions(
    lead_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get all predictions for a specific lead
    """
    try:
        # Fetch lead
        lead = await db.leads.find_one({'_id': lead_id})
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        # Get predictions from both models
        reply_service = ReplyPredictionService(db)
        meeting_service = MeetingPredictionService(db)
        
        reply_prob = reply_service.predictor.predict_reply_probability(lead)
        meeting_prob = meeting_service.predictor.predict_meeting_probability(lead)
        meeting_timing = meeting_service.predictor.suggest_meeting_ask_timing(lead)
        
        # Get priority score
        prioritizer = LeadPrioritizerService(db, reply_service.predictor)
        priority_score = await prioritizer.prioritizer._calculate_priority_score(lead)
        
        return {
            "lead_id": lead_id,
            "reply_probability": reply_prob,
            "meeting_probability": meeting_prob,
            "meeting_timing": meeting_timing,
            "priority_score": priority_score,
            "predicted_at": datetime.now().isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaign/{campaign_id}/predictions")
async def get_campaign_predictions(
    campaign_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get aggregated predictions for entire campaign
    """
    try:
        reply_service = ReplyPredictionService(db)
        predictions = await reply_service.predict_for_campaign(campaign_id)
        
        # Calculate aggregates
        if predictions:
            avg_probability = sum(p['reply_probability'] for p in predictions) / len(predictions)
            high_prob_count = sum(1 for p in predictions if p['reply_probability'] >= 0.7)
            medium_prob_count = sum(1 for p in predictions if 0.4 <= p['reply_probability'] < 0.7)
            low_prob_count = sum(1 for p in predictions if p['reply_probability'] < 0.4)
        else:
            avg_probability = 0
            high_prob_count = medium_prob_count = low_prob_count = 0
        
        return {
            "campaign_id": campaign_id,
            "total_leads": len(predictions),
            "average_probability": avg_probability,
            "distribution": {
                "high": high_prob_count,
                "medium": medium_prob_count,
                "low": low_prob_count
            },
            "predictions": predictions,
            "generated_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
