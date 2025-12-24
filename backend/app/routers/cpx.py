import os
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Body
from typing import Optional, Dict, Any
from app.services.cpx_service import CPXService

router = APIRouter(prefix="/cpx", tags=["cpx"])

# CPX Service instance (will be initialized in main.py)
cpx_service: Optional[CPXService] = None


def set_cpx_service(service: CPXService):
    """Set the CPX service instance"""
    global cpx_service
    cpx_service = service


def get_cpx_service() -> CPXService:
    """Get the CPX service instance"""
    if cpx_service is None:
        raise HTTPException(status_code=500, detail="CPX service not initialized")
    return cpx_service


@router.get("/surveys")
async def get_surveys(
    min_loi: Optional[int] = Query(None, description="Minimum LOI"),
    max_loi: Optional[int] = Query(None, description="Maximum LOI"),
    min_payout: Optional[float] = Query(None, description="Minimum payout"),
    country: Optional[str] = Query(None, description="Country filter"),
    category: Optional[str] = Query(None, description="Category filter"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    request: Request = None,
) -> Dict[str, Any]:
    """
    Get CPX surveys with optional filters and pagination
    
    Query Parameters:
    - min_loi: Minimum length of interview
    - max_loi: Maximum length of interview
    - min_payout: Minimum payout amount
    - country: Filter by country
    - category: Filter by category
    - page: Page number (default: 1)
    - page_size: Items per page (default: 20, max: 100)
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        service = get_cpx_service()
        
        result = service.get_surveys(
            min_loi=min_loi,
            max_loi=max_loi,
            min_payout=min_payout,
            country=country,
            category=category,
            page=page,
            page_size=page_size,
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching surveys: {str(e)}")


@router.post("/filter-settings")
async def save_filter_settings(
    filters: Dict[str, Any] = Body(...),
    request: Request = None,
) -> Dict[str, Any]:
    """
    Save filter settings for the user
    
    Body:
    {
        "min_loi": 5,
        "max_loi": 15,
        "min_payout": 2.5,
        "country": "US",
        "category": "Technology",
        "auto_refresh": true
    }
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        service = get_cpx_service()
        
        success = service.save_filter_settings(filters)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save filter settings")
        
        return {"message": "Filter settings saved successfully", "filters": filters}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving filter settings: {str(e)}")


@router.post("/refresh")
async def refresh_cpx_inventory(request: Request = None) -> Dict[str, Any]:
    """
    Manually trigger CPX survey inventory refresh
    
    This will fetch the latest surveys from CPX API and update the database
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        service = get_cpx_service()
        
        # Fetch and upsert surveys
        surveys = service.fetch_cpx_surveys()
        count = service.upsert_surveys(surveys)
        
        return {
            "message": "CPX inventory refreshed",
            "surveys_fetched": len(surveys),
            "surveys_upserted": count,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing CPX inventory: {str(e)}")


@router.get("/filter-settings")
async def get_filter_settings(request: Request = None) -> Dict[str, Any]:
    """Get saved filter settings"""
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        service = get_cpx_service()
        settings = service.get_filter_settings()
        
        return {"filters": settings}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching filter settings: {str(e)}")


@router.post("/assign-traffic")
async def assign_traffic_to_survey(
    request: Request,
    data: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    """
    Assign traffic to a specific survey
    
    Body:
    {
        "survey_id": "57572480",
        "batch_size": 100
    }
    
    This will:
    1. Get the survey details from CPX
    2. Get NEW traffic records
    3. Build redirect URLs with traffic ObjectId
    4. Update traffic status to INCOMPLETE
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Import here to avoid circular dependency
        from routers.traffic import traffic_service
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        service = get_cpx_service()
        
        # Extract parameters
        survey_id = data.get('survey_id')
        batch_size = data.get('batch_size', 100)
        
        if not survey_id:
            raise HTTPException(status_code=400, detail="Missing survey_id")
        
        # Get survey details from database
        survey = service.cpx_surveys_collection.find_one({"survey_id": survey_id})
        
        if not survey:
            raise HTTPException(status_code=404, detail=f"Survey {survey_id} not found")
        
        client_id = os.getenv("CPX_APP_ID", "10754")
        
        # Get the live_link from survey data
        live_link = survey.get("live_link", "") or survey.get("raw_data", {}).get("href", "") or survey.get("raw_data", {}).get("href_new", "")
        
        # Perform batch assignment with CPX service for entry link generation
        result = traffic_service.batch_assign_surveys_with_entry_links(
            survey_id=survey_id,
            cpx_service=service,
            client_id=client_id,
            batch_size=batch_size,
            live_link=live_link
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error assigning traffic to survey: {e}")
        raise HTTPException(status_code=500, detail=f"Assignment error: {str(e)}")
