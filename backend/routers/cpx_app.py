import os
import json
import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Body, WebSocket, WebSocketDisconnect
from typing import Optional, Dict, Any
from app.services.cpx_service import CPXService

# Import WebSocket manager
try:
    from websocket_manager import connection_manager
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    connection_manager = None

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
    page_size: int = Query(20, ge=1, le=1000, description="Items per page (max 1000 for show_all)"),
    active_only: bool = Query(False, description="Only return surveys active in the pool (for traffic routing)"),
    show_all: bool = Query(False, description="Show ALL surveys without applying default filters"),
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
    - active_only: If true, only return surveys that are active in the pool (default: false)
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
            active_only=active_only,
            apply_default_filters=not show_all,  # Bypass default filters when show_all=true
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


@router.post("/sync-active-status")
async def sync_active_status(request: Request = None) -> Dict[str, Any]:
    """
    Apply filter settings to ALL surveys and mark them as active/inactive.
    Surveys that pass the filter criteria get is_active_in_pool=true,
    others get is_active_in_pool=false.
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        service = get_cpx_service()
        result = service.sync_active_status_by_filters()
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error syncing active status: {str(e)}")


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
        
        # Get the href from survey data (prioritize click.cpx-research.com href over template live_link)
        # href contains the CPX click-tracking URL which is required for proper postback callbacks
        survey_href = (
            survey.get("href") or 
            survey.get("raw_data", {}).get("href") or 
            survey.get("href_new") or 
            survey.get("raw_data", {}).get("href_new") or 
            ""
        )
        
        # Perform batch assignment with CPX service for entry link generation
        result = traffic_service.batch_assign_surveys_with_entry_links(
            survey_id=survey_id,
            cpx_service=service,
            client_id=client_id,
            batch_size=batch_size,
            href=survey_href
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error assigning traffic to survey: {e}")
        raise HTTPException(status_code=500, detail=f"Assignment error: {str(e)}")


# ============================================
# WebSocket - Real-time Survey Updates
# ============================================

@router.websocket("/ws/surveys")
async def cpx_surveys_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time CPX survey updates.
    
    Clients connect to receive instant notifications when:
    - New surveys are fetched via background task
    - Survey data is refreshed
    
    Messages sent to client:
    - connected: Connection confirmation
    - surveys_update: New/updated surveys data
    - heartbeat: Keep-alive ping every 30 seconds
    
    Example client usage (JavaScript):
    ```javascript
    const ws = new WebSocket('ws://localhost:8000/api/cpx/ws/surveys');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'surveys_update') {
            // Handle new surveys
            console.log('New surveys:', data.surveys);
        }
    };
    ```
    """
    if not WEBSOCKET_AVAILABLE or not connection_manager:
        await websocket.close(code=1011, reason="WebSocket manager not available")
        return
    
    try:
        # Connect to the cpx_surveys channel
        connected = await connection_manager.connect(
            websocket, 
            channel="cpx_surveys",
            metadata={"connected_from": "cpx_router"}
        )
        
        if not connected:
            return
        
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages from client (with timeout for heartbeat)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=35.0  # Slightly longer than heartbeat interval
                )
                
                # Handle client messages if needed
                try:
                    message = json.loads(data)
                    if message.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": datetime.utcnow().isoformat()
                        })
                except json.JSONDecodeError:
                    pass
                    
            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                except Exception:
                    break
                    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"CPX WebSocket error: {e}")
    finally:
        connection_manager.disconnect(websocket, "cpx_surveys")


@router.get("/ws/status")
async def get_websocket_status():
    """
    Get WebSocket connection status for CPX surveys.
    
    Returns:
        {
            "available": true,
            "connected_clients": 5,
            "channel": "cpx_surveys"
        }
    """
    if not WEBSOCKET_AVAILABLE or not connection_manager:
        return {
            "available": False,
            "connected_clients": 0,
            "channel": "cpx_surveys",
            "message": "WebSocket manager not initialized"
        }
    
    return {
        "available": True,
        "connected_clients": connection_manager.get_connection_count("cpx_surveys"),
        "channel": "cpx_surveys"
    }


async def broadcast_cpx_surveys(surveys: list):
    """
    Helper function to broadcast CPX surveys to WebSocket clients.
    Call this from CPX service or Celery task after fetching new surveys.
    """
    if WEBSOCKET_AVAILABLE and connection_manager:
        try:
            await connection_manager.broadcast(
                "cpx_surveys",
                {
                    "type": "surveys_update",
                    "surveys": surveys,
                    "count": len(surveys),
                    "source": "fetch"
                }
            )
        except Exception as e:
            print(f"Failed to broadcast CPX surveys: {e}")
