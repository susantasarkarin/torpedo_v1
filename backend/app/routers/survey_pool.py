"""
Survey Pool API Router

Provides endpoints for:
- Syncing surveys from CPX/CINT to the pool
- Activating/deactivating surveys based on filters
- Getting pool statistics
- Manual survey activation/deactivation
"""
from fastapi import APIRouter, Body, HTTPException, Query
from typing import Dict, Any, Optional
import logging

from ..services.activation_service import get_activation_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/survey-pool",
    tags=["survey-pool"]
)


@router.get("/stats")
async def get_pool_stats() -> Dict[str, Any]:
    """
    Get statistics about the survey pool.
    
    Returns counts of total, active, and inactive surveys for each provider.
    """
    try:
        service = get_activation_service()
        stats = service.get_pool_stats()
        return {
            "success": True,
            "data": stats
        }
    except Exception as e:
        logger.error(f"Error getting pool stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def sync_surveys(
    filters: Optional[Dict[str, Any]] = Body(None, description="Optional filter overrides")
) -> Dict[str, Any]:
    """
    Sync and activate surveys from CPX/CINT pools.
    
    This endpoint:
    1. Iterates through all downloaded surveys in CPX and CINT collections
    2. Evaluates each survey against filter criteria (LOI, CPI, IR)
    3. Marks matching surveys as is_active_in_pool=True
    4. Marks non-matching surveys as is_active_in_pool=False
    5. Updates the allocation engine accordingly
    
    Optional body:
    {
        "max_loi": 30,      // Maximum length of interview in minutes
        "min_cpi": 0.5,     // Minimum cost per interview in USD
        "min_ir": 5         // Minimum incidence rate percentage
    }
    
    If no filters provided, uses saved settings from database.
    """
    try:
        service = get_activation_service()
        stats = service.sync_and_activate_surveys(filters)
        
        return {
            "success": True,
            "message": "Survey sync completed successfully",
            "stats": stats,
            "pool_stats": service.get_pool_stats()
        }
    except Exception as e:
        logger.error(f"Error syncing surveys: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active")
async def get_active_surveys(
    provider: Optional[str] = Query(None, description="Filter by provider: CPX or CINT"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum surveys to return")
) -> Dict[str, Any]:
    """
    Get all surveys currently active in the pool.
    
    These are the surveys that traffic can be routed to.
    """
    try:
        service = get_activation_service()
        surveys = service.get_active_surveys_from_pool(provider=provider, limit=limit)
        
        return {
            "success": True,
            "count": len(surveys),
            "surveys": surveys
        }
    except Exception as e:
        logger.error(f"Error getting active surveys: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/toggle/{provider}/{survey_id}")
async def toggle_survey_activation(
    provider: str,
    survey_id: str,
    activate: bool = Body(..., embed=True, description="True to activate, False to deactivate")
) -> Dict[str, Any]:
    """
    Manually activate or deactivate a specific survey.
    
    This overrides the automatic filter-based activation.
    
    Path:
    - provider: "CPX" or "CINT"
    - survey_id: The survey ID
    
    Body:
    {
        "activate": true/false
    }
    """
    try:
        if provider.upper() not in ["CPX", "CINT"]:
            raise HTTPException(status_code=400, detail="Provider must be CPX or CINT")
        
        service = get_activation_service()
        result = service.toggle_survey_activation(survey_id, provider, activate)
        
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["message"])
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling survey: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/filters")
async def get_filter_settings() -> Dict[str, Any]:
    """
    Get the current survey filter settings.
    """
    try:
        service = get_activation_service()
        filters = service._get_default_filters()
        return {
            "success": True,
            "filters": filters
        }
    except Exception as e:
        logger.error(f"Error getting filters: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/filters")
async def save_filter_settings(
    filters: Dict[str, Any] = Body(..., description="Filter settings to save")
) -> Dict[str, Any]:
    """
    Save survey filter settings.
    
    Body:
    {
        "max_loi": 30,      // Maximum length of interview in minutes
        "min_cpi": 0.5,     // Minimum cost per interview in USD  
        "min_ir": 5         // Minimum incidence rate percentage
    }
    
    After saving, triggers a re-sync to apply new filters.
    """
    try:
        service = get_activation_service()
        
        # Save to settings collection
        service.settings_collection.update_one(
            {"_id": "survey_filters"},
            {"$set": filters},
            upsert=True
        )
        
        # Re-sync with new filters
        stats = service.sync_and_activate_surveys(filters)
        
        return {
            "success": True,
            "message": "Filters saved and surveys re-synced",
            "filters": filters,
            "sync_stats": stats
        }
    except Exception as e:
        logger.error(f"Error saving filters: {e}")
        raise HTTPException(status_code=500, detail=str(e))
