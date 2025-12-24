"""
Traffic Flow API Router
Handles survey tracking and URL parameter storage
Uses traffic_flow_db database
"""
from fastapi import APIRouter, HTTPException, Request, Query, Body
from fastapi.responses import RedirectResponse
from pymongo.collection import Collection
from bson import ObjectId
from datetime import datetime
from typing import Dict, Any, Optional, List
import os

router = APIRouter(tags=["traffic-flow"])  # No prefix - routes are at root level

# Configuration for traffic flow redirects - always from environment file
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://surveyfieldwork.com")

ZOHO_COMPLETE_URL = f"{FRONTEND_URL}/thankyou"
ZOHO_TERMINATE_URL = f"{FRONTEND_URL}/nosurvey"
ZOHO_QUOTA_URL = f"{FRONTEND_URL}/nosurvey"

# This will be injected from main.py
url_parameters_collection: Optional[Collection] = None
traffic_service: Optional[Any] = None
survey_allocation_service: Optional[Any] = None
cpx_service: Optional[Any] = None


def set_url_parameters_collection(collection: Collection):
    """Set the MongoDB collection from main.py"""
    global url_parameters_collection
    url_parameters_collection = collection


def set_traffic_service(service: Any):
    """Set the traffic service instance from main.py"""
    global traffic_service
    traffic_service = service


def set_survey_allocation_service(service: Any):
    """Set the survey allocation service instance"""
    global survey_allocation_service
    survey_allocation_service = service


def set_cpx_service(service: Any):
    """Set the CPX service instance for survey allocation"""
    global cpx_service
    cpx_service = service


@router.post("/api/store")
async def store_url_params(request: Request, data: Dict[str, Any] = Body(...)):
    """
    Store URL parameters from survey tracking
    Creates a traffic record with vid, cc, rid if available
    Also attempts to allocate a survey to the respondent
    """
    try:
        if url_parameters_collection is None:
            raise HTTPException(status_code=500, detail="Database not connected")
        
        # Extract traffic parameters
        params = data.get('params', {})
        vendor_id = params.get('vid', '')
        country_code = params.get('cc', '')
        respondent_id = params.get('rid', '')
        
        traffic_id = None
        entry_link = None
        survey_id = None
        allocation_success = False
        
        # If traffic service is available and we have the required params, use it
        if traffic_service and vendor_id and country_code and respondent_id:
            try:
                traffic_id = traffic_service.create_traffic_record(
                    vendor_id=vendor_id,
                    country_code=country_code,
                    respondent_id=respondent_id,
                    url=data.get('url'),
                    user_agent=data.get('userAgent'),
                    params=params
                )
            except Exception as e:
                print(f"⚠️ Failed to create traffic record, falling back to legacy: {e}")
        
        # Legacy fallback - store as before
        if not traffic_id:
            data['timestamp'] = datetime.utcnow().isoformat()
            data['status'] = 'incomplete'
            data['redirectUrl'] = None
            result = url_parameters_collection.insert_one(data)
            traffic_id = str(result.inserted_id)
        
        # Try to allocate a survey using CPX service directly
        if cpx_service and vendor_id and country_code and respondent_id:
            try:
                # Get available CPX surveys and pick one for the respondent
                surveys_result = cpx_service.get_surveys(page=1, page_size=10)
                surveys = surveys_result.get('surveys', [])
                
                if surveys:
                    # Pick the first available survey (you can add filtering logic here)
                    selected_survey = surveys[0]
                    survey_id = selected_survey.get('survey_id') or selected_survey.get('id')
                    
                    # Get the live_link or href_new link (direct survey link)
                    base_link = selected_survey.get('live_link') or selected_survey.get('href_new') or selected_survey.get('href')
                    
                    if base_link:
                        # Generate entry link with respondent ID as ext_user_id
                        entry_link = cpx_service.generate_entry_link(
                            live_link=base_link,
                            respondent_id=respondent_id
                        )
                        allocation_success = True
                        
                        # Update the traffic record with the assigned survey
                        if traffic_service:
                            traffic_service.assign_survey_to_traffic(
                                traffic_id=traffic_id,
                                survey_id=str(survey_id),
                                redirect_url=entry_link
                            )
                        
                        print(f"✅ Allocated CPX survey {survey_id} to respondent vid={vendor_id}, rid={respondent_id}")
                else:
                    print(f"⚠️ No CPX surveys available for allocation")
                    
            except Exception as e:
                print(f"⚠️ CPX survey allocation error: {e}")
                import traceback
                traceback.print_exc()
        
        # Fallback to survey allocation service if CPX failed
        if not allocation_success and survey_allocation_service and vendor_id and country_code and respondent_id:
            try:
                from app.models.survey_allocation import AllocationRequest
                
                allocation_request = AllocationRequest(
                    vid=vendor_id,
                    cc=country_code.upper(),
                    rid=respondent_id,
                    ip_address=request.client.host if request else None,
                    user_agent=data.get('userAgent')
                )
                
                allocation_result = survey_allocation_service.allocate_respondent(allocation_request)
                
                if allocation_result.success and allocation_result.entry_link:
                    entry_link = allocation_result.entry_link
                    survey_id = allocation_result.survey_id
                    allocation_success = True
                    
                    if traffic_service:
                        traffic_service.assign_survey_to_traffic(
                            traffic_id=traffic_id,
                            survey_id=survey_id,
                            redirect_url=entry_link
                        )
                    
                    print(f"✅ Allocated survey {survey_id} via allocation service")
                else:
                    print(f"⚠️ Survey allocation service failed: {allocation_result.message}")
                    
            except Exception as e:
                print(f"⚠️ Survey allocation service error: {e}")
        
        return {
            "id": traffic_id,
            "type": "traffic_record" if traffic_service else "legacy",
            "allocation_success": allocation_success,
            "entry_link": entry_link,
            "survey_id": survey_id
        }
        
    except Exception as e:
        print(f"Error storing URL parameters: {e}")
        raise HTTPException(status_code=500, detail=f"Store error: {str(e)}")


@router.get("/surveycomplete")
async def survey_complete(request: Request, rid: str = Query(None)):
    """
    Survey completion callback
    Updates status to 'complete' and redirects
    """
    try:
        if rid:
            # Try traffic service first
            if traffic_service:
                traffic_service.update_traffic_status(
                    traffic_id=rid,
                    status="COMPLETE",
                    redirect_url=str(request.url)
                )
            # Fallback to direct collection update
            elif url_parameters_collection:
                url_parameters_collection.update_one(
                    {"_id": ObjectId(rid)},
                    {"$set": {"status": "complete", "redirectUrl": str(request.url)}}
                )
        return RedirectResponse(url=ZOHO_COMPLETE_URL)
    except Exception as e:
        print(f"Error in survey_complete: {e}")
        # Still redirect even if update fails
        return RedirectResponse(url=ZOHO_COMPLETE_URL)


@router.get("/surveyterminate")
async def survey_terminate(request: Request, rid: str = Query(None)):
    """
    Survey termination callback
    Updates status to 'terminated' and redirects
    """
    try:
        if rid:
            # Try traffic service first
            if traffic_service:
                traffic_service.update_traffic_status(
                    traffic_id=rid,
                    status="TERMINATED",
                    redirect_url=str(request.url)
                )
            # Fallback to direct collection update
            elif url_parameters_collection:
                url_parameters_collection.update_one(
                    {"_id": ObjectId(rid)},
                    {"$set": {"status": "terminated", "redirectUrl": str(request.url)}}
                )
        return RedirectResponse(url=ZOHO_TERMINATE_URL)
    except Exception as e:
        print(f"Error in survey_terminate: {e}")
        # Still redirect even if update fails
        return RedirectResponse(url=ZOHO_TERMINATE_URL)


@router.get("/surveyquotafull")
async def survey_quotafull(request: Request, rid: str = Query(None)):
    """
    Survey quota full callback
    Updates status to 'quotafull' and redirects
    """
    try:
        if rid:
            # Try traffic service first
            if traffic_service:
                traffic_service.update_traffic_status(
                    traffic_id=rid,
                    status="QUOTAFULL",
                    redirect_url=str(request.url)
                )
            # Fallback to direct collection update
            elif url_parameters_collection:
                url_parameters_collection.update_one(
                    {"_id": ObjectId(rid)},
                    {"$set": {"status": "quotafull", "redirectUrl": str(request.url)}}
                )
        return RedirectResponse(url=ZOHO_QUOTA_URL)
    except Exception as e:
        print(f"Error in survey_quotafull: {e}")
        # Still redirect even if update fails
        return RedirectResponse(url=ZOHO_QUOTA_URL)


@router.get("/api/health")
async def health():
    """
    Health check endpoint for traffic flow API
    """
    return {"status": "ok", "service": "traffic-flow"}


@router.get("/api/traffic/stats")
async def get_traffic_stats(
    request: Request,
    survey_id: str = Query(None, description="Optional survey ID to filter stats")
):
    """
    Get traffic statistics by status, optionally filtered by survey_id
    Requires authentication
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        stats = traffic_service.get_traffic_stats(survey_id=survey_id)
        return stats
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting traffic stats: {e}")
        raise HTTPException(status_code=500, detail=f"Stats error: {str(e)}")


@router.post("/api/traffic/assign-survey")
async def assign_survey_batch(
    request: Request,
    data: Dict[str, Any] = Body(...)
):
    """
    Assign a survey to a batch of NEW traffic records
    
    Body:
    {
        "survey_id": "57572480",
        "survey_url": "https://offers.cpx-research.com/index.php",
        "client_id": "10754",
        "batch_size": 100
    }
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        # Extract parameters
        survey_id = data.get('survey_id')
        survey_url = data.get('survey_url')
        client_id = data.get('client_id')
        batch_size = data.get('batch_size', 100)
        
        if not all([survey_id, survey_url, client_id]):
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: survey_id, survey_url, client_id"
            )
        
        # Perform batch assignment
        result = traffic_service.batch_assign_surveys(
            survey_id=survey_id,
            survey_url=survey_url,
            client_id=client_id,
            batch_size=batch_size
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error assigning survey batch: {e}")
        raise HTTPException(status_code=500, detail=f"Assignment error: {str(e)}")


@router.get("/api/traffic/new-batch")
async def get_new_traffic_batch(
    request: Request,
    batch_size: int = Query(100, ge=1, le=1000, description="Batch size (1-1000)")
):
    """
    Get a batch of NEW traffic records
    Requires authentication
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        batch = traffic_service.get_new_traffic_batch(batch_size)
        
        return {
            "count": len(batch),
            "batch_size": batch_size,
            "records": batch
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting traffic batch: {e}")
        raise HTTPException(status_code=500, detail=f"Batch error: {str(e)}")


@router.get("/api/traffic/list")
async def list_traffic_records(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Records per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search term"),
    survey_id: Optional[str] = Query(None, description="Filter by survey ID"),
):
    """
    List all traffic records with pagination and optional filters
    Requires authentication
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        result = traffic_service.list_traffic_records(
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            survey_id=survey_id,
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error listing traffic records: {e}")
        raise HTTPException(status_code=500, detail=f"List error: {str(e)}")


@router.delete("/api/traffic/delete")
async def delete_traffic_records(
    request: Request,
    data: Dict[str, Any] = Body(...)
):
    """
    Delete multiple traffic records by IDs
    
    Body:
    {
        "ids": ["id1", "id2", "id3"]
    }
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        ids = data.get('ids', [])
        if not ids:
            raise HTTPException(status_code=400, detail="No IDs provided")
        
        # Convert string IDs to ObjectId and delete
        object_ids = []
        for id_str in ids:
            try:
                object_ids.append(ObjectId(id_str))
            except Exception:
                pass  # Skip invalid IDs
        
        if not object_ids:
            raise HTTPException(status_code=400, detail="No valid IDs provided")
        
        result = traffic_service.traffic_collection.delete_many({"_id": {"$in": object_ids}})
        
        return {
            "deleted_count": result.deleted_count,
            "requested_count": len(ids)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting traffic records: {e}")
        raise HTTPException(status_code=500, detail=f"Delete error: {str(e)}")

