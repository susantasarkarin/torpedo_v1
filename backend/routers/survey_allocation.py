"""
Survey Allocation API Router

Provides endpoints for:
- Survey allocation (respondent entry point)
- Callback handling (complete, terminate, etc.)
- Survey management (CRUD, pause/resume)
- Metrics and dashboard
- Settings management
"""
from fastapi import APIRouter, Body, HTTPException, Request, Query, Path
from fastapi.responses import RedirectResponse
from typing import Dict, Any, List, Optional
from datetime import datetime
from bson import ObjectId

# Import service and models
from app.services.survey_allocation_service import get_survey_allocation_service
from app.models.survey_allocation import (
    AllocationRequest, AllocationResponse,
    CallbackEvent, CallbackResponse,
    SurveyCreate, SurveyUpdate, SurveyStatus,
    AllocationSettings, RespondentStatus
)


router = APIRouter(
    prefix="/survey-allocation",
    tags=["survey-allocation"]
)


# ============================================
# Allocation Endpoints
# ============================================

@router.get("/entry")
async def allocate_survey_get(
    vid: str = Query(..., description="Vendor ID"),
    cc: str = Query(..., description="Country Code"),
    rid: str = Query(..., description="Respondent ID"),
    request: Request = None
) -> Dict[str, Any]:
    """
    Main entry point for respondent allocation (GET method).
    
    Query Parameters:
    - vid: Vendor ID
    - cc: Country Code (ISO 2-letter)
    - rid: Respondent ID (unique per vendor)
    
    Returns allocation details or redirects to survey.
    """
    service = get_survey_allocation_service()
    
    allocation_request = AllocationRequest(
        vid=vid,
        cc=cc.upper(),
        rid=rid,
        ip_address=request.client.host if request else None,
        user_agent=request.headers.get("user-agent") if request else None
    )
    
    result = service.allocate_respondent(allocation_request)
    
    if result.success and result.entry_link:
        # Option 1: Redirect to survey
        # return RedirectResponse(url=result.entry_link, status_code=302)
        
        # Option 2: Return JSON with entry link
        return {
            "success": True,
            "message": result.message,
            "respondent_id": result.respondent_id,
            "survey_id": result.survey_id,
            "survey_name": result.survey_name,
            "entry_link": result.entry_link,
            "allocation_id": result.allocation_id
        }
    else:
        return {
            "success": False,
            "message": result.message,
            "respondent_id": result.respondent_id
        }


@router.post("/entry")
async def allocate_survey_post(
    body: AllocationRequest,
    request: Request = None
) -> Dict[str, Any]:
    """
    Main entry point for respondent allocation (POST method).
    
    Body:
    {
        "vid": "vendor123",
        "cc": "US",
        "rid": "respondent456"
    }
    """
    service = get_survey_allocation_service()
    
    # Enrich with request metadata
    body.ip_address = request.client.host if request else body.ip_address
    body.user_agent = request.headers.get("user-agent") if request else body.user_agent
    body.cc = body.cc.upper()
    
    result = service.allocate_respondent(body)
    
    return {
        "success": result.success,
        "message": result.message,
        "respondent_id": result.respondent_id,
        "survey_id": result.survey_id,
        "survey_name": result.survey_name,
        "entry_link": result.entry_link,
        "allocation_id": result.allocation_id
    }


# ============================================
# Callback Endpoints
# ============================================

@router.get("/callback/{event_type}")
async def handle_callback_get(
    event_type: str = Path(..., description="Event type: start, complete, incomplete, terminate, quota_full"),
    resp_id: str = Query(..., description="Respondent ID"),
    survey_id: str = Query(..., description="Survey ID"),
    request: Request = None
) -> Dict[str, Any]:
    """
    Handle survey callback events (GET method - for redirect callbacks).
    
    Path: /callback/{event_type}
    Query params: resp_id, survey_id
    """
    valid_events = ["start", "complete", "incomplete", "terminate", "quota_full"]
    if event_type not in valid_events:
        raise HTTPException(status_code=400, detail=f"Invalid event type. Must be one of: {valid_events}")
    
    service = get_survey_allocation_service()
    
    event = CallbackEvent(
        event_type=event_type,
        respondent_id=resp_id,
        survey_id=survey_id,
        timestamp=datetime.utcnow()
    )
    
    result = service.handle_callback(event)
    
    if result.redirect_url:
        return RedirectResponse(url=result.redirect_url, status_code=302)
    
    return {
        "success": result.success,
        "message": result.message
    }


@router.post("/callback")
async def handle_callback_post(
    event: CallbackEvent
) -> Dict[str, Any]:
    """
    Handle survey callback events (POST method).
    
    Body:
    {
        "event_type": "complete",
        "respondent_id": "...",
        "survey_id": "...",
        "metadata": {}
    }
    """
    service = get_survey_allocation_service()
    result = service.handle_callback(event)
    
    return {
        "success": result.success,
        "message": result.message,
        "redirect_url": result.redirect_url
    }


# ============================================
# Survey Management Endpoints
# ============================================

@router.get("/surveys")
async def list_surveys(
    status: Optional[str] = Query(None, description="Filter by status: active, paused"),
    country: Optional[str] = Query(None, description="Filter by country code"),
    with_metrics: bool = Query(True, description="Include performance metrics")
) -> Dict[str, Any]:
    """Get all surveys with optional filtering"""
    service = get_survey_allocation_service()
    
    if with_metrics:
        surveys = service.get_surveys_with_metrics(status)
    else:
        if status:
            surveys = list(service.surveys.find({"status": status}))
        else:
            surveys = list(service.surveys.find())
        
        for s in surveys:
            s["_id"] = str(s["_id"])
    
    if country:
        surveys = [s for s in surveys if country.upper() in s.get("country_codes", [])]
    
    return {
        "surveys": surveys,
        "total": len(surveys)
    }


@router.get("/surveys/{survey_id}")
async def get_survey(
    survey_id: str = Path(..., description="Survey ID")
) -> Dict[str, Any]:
    """Get a specific survey with metrics"""
    service = get_survey_allocation_service()
    
    survey = service.get_survey(survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    
    survey["_id"] = str(survey["_id"])
    metrics = service.get_survey_metrics(survey_id)
    if metrics:
        metrics.pop("_id", None)
        survey["metrics"] = metrics
    
    return {"survey": survey}


@router.post("/surveys")
async def create_survey(
    survey: SurveyCreate,
    request: Request = None
) -> Dict[str, Any]:
    """
    Create or update a survey (upsert based on external_id + provider).
    
    Body: SurveyCreate model
    """
    # Optional: Verify session for protected endpoint
    # session_id = request.headers.get("Authorization")
    # if not session_id:
    #     raise HTTPException(status_code=401, detail="Missing session token")
    
    service = get_survey_allocation_service()
    result = service.upsert_survey(survey)
    
    return {
        "message": "Survey created/updated successfully",
        "survey_id": str(result["_id"]),
        "external_id": result.get("external_id")
    }


@router.post("/surveys/bulk")
async def create_surveys_bulk(
    surveys: List[SurveyCreate],
    request: Request = None
) -> Dict[str, Any]:
    """Bulk import surveys from provider"""
    service = get_survey_allocation_service()
    
    created = 0
    errors = []
    
    for survey in surveys:
        try:
            service.upsert_survey(survey)
            created += 1
        except Exception as e:
            errors.append({
                "external_id": survey.external_id,
                "error": str(e)
            })
    
    return {
        "message": f"Imported {created} surveys",
        "created": created,
        "errors": errors
    }


@router.patch("/surveys/{survey_id}")
async def update_survey(
    survey_id: str = Path(..., description="Survey ID"),
    updates: SurveyUpdate = Body(...),
    request: Request = None
) -> Dict[str, Any]:
    """Update survey fields"""
    service = get_survey_allocation_service()
    
    update_dict = {k: v for k, v in updates.model_dump().items() if v is not None}
    if not update_dict:
        raise HTTPException(status_code=400, detail="No valid updates provided")
    
    update_dict["updated_at"] = datetime.utcnow()
    
    try:
        result = service.surveys.find_one_and_update(
            {"_id": ObjectId(survey_id)},
            {"$set": update_dict},
            return_document=True
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Survey not found")
        
        return {"message": "Survey updated", "survey_id": survey_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/surveys/{survey_id}/pause")
async def pause_survey(
    survey_id: str = Path(..., description="Survey ID"),
    reason: str = Body("Manual pause", embed=True),
    request: Request = None
) -> Dict[str, Any]:
    """Manually pause a survey"""
    service = get_survey_allocation_service()
    
    result = service.update_survey_status(survey_id, SurveyStatus.PAUSED, reason)
    if not result:
        raise HTTPException(status_code=404, detail="Survey not found")
    
    return {"message": "Survey paused", "survey_id": survey_id}


@router.post("/surveys/{survey_id}/resume")
async def resume_survey(
    survey_id: str = Path(..., description="Survey ID"),
    request: Request = None
) -> Dict[str, Any]:
    """Resume a paused survey"""
    service = get_survey_allocation_service()
    
    success = service.manually_resume_survey(survey_id)
    if not success:
        raise HTTPException(status_code=404, detail="Survey not found or not paused")
    
    return {"message": "Survey resumed", "survey_id": survey_id}


@router.post("/surveys/{survey_id}/reset-batch")
async def reset_survey_batch(
    survey_id: str = Path(..., description="Survey ID"),
    request: Request = None
) -> Dict[str, Any]:
    """Reset the batch counter for a survey (start new batch)"""
    service = get_survey_allocation_service()
    
    success = service.reset_batch(survey_id)
    if not success:
        raise HTTPException(status_code=404, detail="Survey not found")
    
    return {"message": "Batch reset", "survey_id": survey_id}


@router.delete("/surveys/{survey_id}")
async def delete_survey(
    survey_id: str = Path(..., description="Survey ID"),
    request: Request = None
) -> Dict[str, Any]:
    """Delete a survey"""
    service = get_survey_allocation_service()
    
    try:
        result = service.surveys.delete_one({"_id": ObjectId(survey_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Survey not found")
        
        # Also delete metrics
        service.metrics.delete_one({"survey_id": survey_id})
        
        return {"message": "Survey deleted", "survey_id": survey_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Metrics & Dashboard Endpoints
# ============================================

@router.get("/metrics")
async def get_all_metrics() -> Dict[str, Any]:
    """Get performance metrics for all surveys"""
    service = get_survey_allocation_service()
    
    metrics = service.get_all_metrics()
    for m in metrics:
        m.pop("_id", None)
    
    return {"metrics": metrics}


@router.get("/metrics/{survey_id}")
async def get_survey_metrics(
    survey_id: str = Path(..., description="Survey ID")
) -> Dict[str, Any]:
    """Get performance metrics for a specific survey"""
    service = get_survey_allocation_service()
    
    metrics = service.get_survey_metrics(survey_id)
    if not metrics:
        raise HTTPException(status_code=404, detail="Metrics not found")
    
    metrics.pop("_id", None)
    return {"metrics": metrics}


@router.get("/dashboard")
async def get_dashboard() -> Dict[str, Any]:
    """Get dashboard summary statistics"""
    service = get_survey_allocation_service()
    return service.get_dashboard_stats()


# ============================================
# Respondent Endpoints
# ============================================

@router.get("/respondents")
async def list_respondents(
    status: Optional[str] = Query(None, description="Filter by status"),
    survey_id: Optional[str] = Query(None, description="Filter by survey"),
    vid: Optional[str] = Query(None, description="Filter by vendor"),
    limit: int = Query(100, le=1000),
    skip: int = Query(0)
) -> Dict[str, Any]:
    """List respondents with filtering"""
    service = get_survey_allocation_service()
    
    query = {}
    if status:
        query["status"] = status
    if survey_id:
        query["survey_id"] = survey_id
    if vid:
        query["vid"] = vid
    
    respondents = list(
        service.respondents.find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    
    for r in respondents:
        r["_id"] = str(r["_id"])
    
    total = service.respondents.count_documents(query)
    
    return {
        "respondents": respondents,
        "total": total,
        "limit": limit,
        "skip": skip
    }


@router.get("/respondents/{respondent_id}")
async def get_respondent(
    respondent_id: str = Path(..., description="Respondent ID")
) -> Dict[str, Any]:
    """Get a specific respondent"""
    service = get_survey_allocation_service()
    
    respondent = service.get_respondent(respondent_id)
    if not respondent:
        raise HTTPException(status_code=404, detail="Respondent not found")
    
    respondent["_id"] = str(respondent["_id"])
    return {"respondent": respondent}


# ============================================
# Settings Endpoints
# ============================================

@router.get("/settings")
async def get_allocation_settings(request: Request = None) -> Dict[str, Any]:
    """Get allocation settings"""
    # Optional: Verify session
    session_id = request.headers.get("Authorization") if request else None
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing session token")
    
    service = get_survey_allocation_service()
    settings = service.get_allocation_settings()
    
    return {
        "settings": settings.model_dump(),
        "defaults": AllocationSettings().model_dump()
    }


@router.post("/settings")
async def save_allocation_settings(
    settings: Dict[str, Any] = Body(...),
    request: Request = None
) -> Dict[str, Any]:
    """Save allocation settings"""
    session_id = request.headers.get("Authorization") if request else None
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing session token")
    
    service = get_survey_allocation_service()
    
    # Validate and create settings object
    try:
        # Get existing settings and merge
        existing = service.get_allocation_settings()
        merged = existing.model_dump()
        merged.update(settings)
        
        new_settings = AllocationSettings(**merged)
        success = service.save_allocation_settings(new_settings)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save settings")
        
        return {
            "message": "Settings saved successfully",
            "settings": new_settings.model_dump()
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid settings: {str(e)}")
