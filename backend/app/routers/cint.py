"""
Cint API Integration - Router

Endpoints for:
- Webhook callbacks (opportunities, respondent outcomes)
- Entry link CRUD operations
- Settings management
- Subscription management
- WebSocket for real-time survey updates
"""
from fastapi import APIRouter, HTTPException, Header, Body, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import os
import json
import hmac
import hashlib
import asyncio

from app.models.cint import (
    CintOpportunity,
    SupplierLink,
    SupplierLinkCreate,
    SupplierLinkUpdate,
    OpportunitiesSubscriptionConfig,
    OutcomeSubscriptionConfig,
    CintSettings,
    WebhookValidationRequest,
    EntryLinkResponse,
    OpportunitiesListResponse,
    SettingsResponse,
    RespondentOutcome,
)

# Import WebSocket manager
try:
    from websocket_manager import connection_manager
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    connection_manager = None

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cint"])

# Global service instances (set by main.py)
_cint_service = None
_cint_allocation_ext = None

def set_cint_service(service):
    """Set CintService instance"""
    global _cint_service
    _cint_service = service

def set_cint_allocation_ext(ext):
    """Set CintAllocationExtension instance"""
    global _cint_allocation_ext
    _cint_allocation_ext = ext

async def get_cint_service():
    """Dependency to get CintService"""
    if not _cint_service:
        raise HTTPException(status_code=500, detail="Cint service not initialized")
    return _cint_service

async def get_cint_allocation_ext():
    """Dependency to get CintAllocationExtension"""
    if not _cint_allocation_ext:
        raise HTTPException(status_code=500, detail="Cint allocation service not initialized")
    return _cint_allocation_ext



# ============================================
# Webhook Callbacks
# ============================================

@router.post("/webhooks/opportunities")
async def handle_opportunities_webhook(
    request: Request,
    x_cint_signature: Optional[str] = Header(None),
    cint_service = Depends(get_cint_service),
    cint_allocation = Depends(get_cint_allocation_ext),
):
    """
    Receive opportunity webhook from Cint
    
    This endpoint is called by Cint every 15 seconds (configurable) with:
    - New survey opportunities
    - Updates to existing surveys (quota changes, status changes)
    - Deactivated surveys
    
    Args:
        request: FastAPI request object
        x_cint_signature: HMAC-SHA256 signature for validation
        cint_service: CintService instance
        cint_allocation: CintAllocationExtension instance
    
    Returns:
        {
            "success": true,
            "message": "Opportunities processed",
            "count": 5
        }
    """
    try:
        # Get raw body for signature validation
        body = await request.body()
        
        # Validate webhook signature if present
        if x_cint_signature:
            webhook_secret = os.getenv("CINT_WEBHOOK_SECRET", "")
            expected_sig = hmac.new(
                webhook_secret.encode(),
                body,
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(x_cint_signature, expected_sig):
                logger.warning(f"Invalid webhook signature: {x_cint_signature[:20]}...")
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        # Parse JSON payload
        request_body = json.loads(body.decode())
        opportunities = request_body if isinstance(request_body, list) else [request_body]
        
        logger.info(f"Received opportunities webhook with {len(opportunities)} surveys")
        # DEBUG: Log raw payload structure
        logger.info(f"CINT WEBHOOK DEBUG - Raw payload keys: {list(request_body.keys()) if isinstance(request_body, dict) else 'list'}")
        logger.info(f"CINT WEBHOOK DEBUG - Payload sample: {str(request_body)[:500]}")
        
        # Process through CintService
        processed = await cint_service.process_opportunity_webhook(request_body)
        
        # Update allocation metrics if extension available
        if cint_allocation is not None and processed:
            for opp in processed:
                await cint_allocation.update_opportunity_from_webhook(
                    opp.survey_id,
                    opp.dict()
                )
        
        # Broadcast to WebSocket clients
        if WEBSOCKET_AVAILABLE and connection_manager and processed:
            try:
                # Convert processed opportunities to serializable format
                surveys_data = []
                for opp in processed:
                    opp_dict = opp.dict() if hasattr(opp, 'dict') else opp
                    surveys_data.append(opp_dict)
                
                await connection_manager.broadcast(
                    "cint_surveys",
                    {
                        "type": "surveys_update",
                        "surveys": surveys_data,
                        "count": len(surveys_data),
                        "source": "webhook"
                    }
                )
                logger.info(f"Broadcast {len(surveys_data)} surveys to WebSocket clients")
            except Exception as ws_err:
                logger.warning(f"Failed to broadcast to WebSocket: {ws_err}")
        
        return {
            "success": True,
            "message": "Opportunities processed",
            "count": len(opportunities)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing opportunities webhook: {str(e)}")
        import traceback
        traceback.print_exc()
        # Return 500 to trigger Cint retry logic
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process webhook: {str(e)}"
        )



@router.post("/webhooks/respondent-outcomes")
async def handle_respondent_outcomes_webhook(
    request: Request,
    x_cint_signature: Optional[str] = Header(None),
    x_cint_timestamp: Optional[str] = Header(None),
    cint_service = Depends(get_cint_service),
):
    """
    Receive respondent outcome webhook from Cint
    
    This endpoint is called by Cint when respondent sessions complete/terminate
    with status information (completed, terminated, quota_full, etc.)
    
    Features:
    - HMAC-SHA256 signature verification
    - Replay protection (rejects timestamps > 5 minutes old)
    - Stores latest outcome per session_id
    
    Args:
        request: FastAPI request object
        x_cint_signature: HMAC-SHA256 signature for validation
        x_cint_timestamp: Webhook timestamp for replay protection
        cint_service: CintService instance
    
    Returns:
        {
            "success": true,
            "message": "Outcomes processed",
            "count": 5
        }
    """
    from datetime import timezone
    
    try:
        # Get raw body for signature validation
        body = await request.body()
        
        # Validate webhook signature if present
        if x_cint_signature:
            webhook_secret = os.getenv("CINT_OUTCOMES_WEBHOOK_SECRET", os.getenv("CINT_WEBHOOK_SECRET", ""))
            expected_sig = hmac.new(
                webhook_secret.encode(),
                body,
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(x_cint_signature, expected_sig):
                logger.warning(f"Invalid outcomes webhook signature: {x_cint_signature[:20]}...")
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        # Replay protection - reject old timestamps (> 5 minutes)
        if x_cint_timestamp:
            try:
                timestamp = datetime.fromisoformat(x_cint_timestamp.replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()
                if age_seconds > 300:  # 5 minutes
                    logger.warning(f"Rejecting stale outcomes webhook (age: {age_seconds:.0f}s)")
                    raise HTTPException(status_code=401, detail="Webhook timestamp too old (replay protection)")
            except ValueError:
                logger.warning(f"Invalid timestamp format in header: {x_cint_timestamp}")
        
        # Parse JSON payload
        request_body = json.loads(body.decode())
        outcomes = request_body if isinstance(request_body, list) else [request_body]
        
        logger.info(f"Received outcomes webhook with {len(outcomes)} outcomes")
        
        # Process each outcome through CintService
        processed_count = 0
        for outcome_data in outcomes:
            result = await cint_service.process_respondent_outcome(outcome_data)
            if result.get("success"):
                processed_count += 1
        
        # Broadcast to WebSocket clients if available
        if WEBSOCKET_AVAILABLE and connection_manager:
            try:
                await connection_manager.broadcast(
                    "cint_outcomes",
                    {
                        "type": "outcomes_update",
                        "count": processed_count,
                        "source": "webhook"
                    }
                )
                logger.debug(f"Broadcast {processed_count} outcomes to WebSocket clients")
            except Exception as ws_err:
                logger.warning(f"Failed to broadcast outcomes to WebSocket: {ws_err}")
        
        return {
            "success": True,
            "message": "Outcomes processed",
            "count": processed_count
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing respondent outcomes webhook: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


# ============================================
# Entry Link Management
# ============================================

@router.post("/entry-links/{survey_id}")
async def create_entry_link(
    survey_id: int,
    link_config: SupplierLinkCreate,
    cint_service = Depends(get_cint_service),
) -> EntryLinkResponse:
    """
    Create entry link for a survey
    
    Args:
        survey_id: Cint survey ID
        link_config: Link configuration with redirect URLs
    
    Returns:
        Entry link with live_link and test_link
    """
    try:
        logger.info(f"Creating entry link for survey {survey_id}")

        # Call CintService to create entry link via API
        result = await cint_service.create_entry_link(survey_id, link_config)

        # Check if result indicates failure
        if not result or not result.get("success"):
            error_msg = result.get("error", "Unknown error") if result else "No response"
            status_code = result.get("status_code", 500) if result else 500

            # If survey doesn't exist (404), provide clear message
            if status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Survey {survey_id} not found or no longer active. Cannot create entry link."
                )

            raise HTTPException(
                status_code=status_code,
                detail=f"Failed to create entry link for survey {survey_id}: {error_msg}"
            )

        return EntryLinkResponse(
            success=True,
            message="Entry link created successfully",
            link=result.get("link"),
            data={"link": result.get("link")}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating entry link: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



@router.put("/entry-links/{survey_id}")
async def update_entry_link(
    survey_id: int,
    link_config: SupplierLinkUpdate,
    cint_service = Depends(get_cint_service),
) -> EntryLinkResponse:
    """
    Update entry link for a survey
    
    Args:
        survey_id: Cint survey ID
        link_config: Updated link configuration (all fields required)
    
    Returns:
        Updated entry link
    """
    try:
        logger.info(f"Updating entry link for survey {survey_id}")

        # Call CintService to update entry link
        result = await cint_service.update_entry_link(survey_id, link_config)

        # Check if result indicates failure
        if not result or not result.get("success"):
            error_msg = result.get("error", "Unknown error") if result else "No response"
            status_code = result.get("status_code", 500) if result else 500

            # If survey doesn't exist (404), provide clear message
            if status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Entry link not found for survey {survey_id}. Survey may no longer be active."
                )

            raise HTTPException(
                status_code=status_code,
                detail=f"Failed to update entry link for survey {survey_id}: {error_msg}"
            )

        return EntryLinkResponse(
            success=True,
            message="Entry link updated successfully",
            link=result.get("link"),
            data={"link": result.get("link")}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating entry link: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auto-create-entry-links")
async def auto_create_entry_links_for_all(
    limit: int = Query(100, ge=0, description="Max surveys to process (0 = no limit)"),
    cint_service = Depends(get_cint_service)
):
    """Auto-create entry links for active surveys that don't have one."""
    if cint_service is None:
        raise HTTPException(status_code=503, detail="Cint service not initialized")
    
    # Get active surveys without entry links
    query = {
        "is_active": True,
        "is_live": True  # Only process live surveys
    }
    if cint_service.cint_entry_links_collection is not None:
        existing_ids = cint_service.cint_entry_links_collection.distinct("survey_id")
        if existing_ids:
            query["survey_id"] = {"$nin": existing_ids}
    projection = {"survey_id": 1, "is_live": 1}
    cursor = cint_service.cint_surveys_collection.find(query, projection)
    if limit > 0:
        cursor = cursor.limit(limit)
    surveys = list(cursor)

    created = 0
    skipped = 0
    errors = []

    for survey in surveys:
        survey_id = survey["survey_id"]

        # Double-check survey is still live before creating entry link
        if not survey.get("is_live", False):
            logger.info(f"Skipping survey {survey_id} - not live")
            skipped += 1
            continue

        try:
            existing_cached = await cint_service.get_entry_link_by_survey_id(survey_id)
            if existing_cached:
                skipped += 1
                continue
            existing = await cint_service.get_entry_link(survey_id)
            if existing.get("success") and existing.get("link"):
                skipped += 1
                continue
            
            result = await cint_service._auto_create_entry_link(survey_id)
            if result.get("success"):
                created += 1
            else:
                errors.append({"survey_id": survey_id, "error": result.get("message")})
        except Exception as e:
            errors.append({"survey_id": survey_id, "error": str(e)})
    
    return {
        "success": True,
        "created": created,
        "skipped": skipped,
        "errors": errors[:10] if errors else []
    }


@router.get("/entry-links/{survey_id}")
async def get_entry_link(
    survey_id: int,
    cint_service = Depends(get_cint_service),
) -> EntryLinkResponse:
    """
    Get entry link for a survey
    
    Args:
        survey_id: Cint survey ID
    
    Returns:
        Entry link details
    """
    try:
        logger.info(f"Retrieving entry link for survey {survey_id}")
        
        # Call CintService to get entry link
        result = await cint_service.get_entry_link(survey_id)
        
        if not result or not result.get("success"):
            raise HTTPException(status_code=404, detail=f"Entry link not found for survey {survey_id}")
        
        return EntryLinkResponse(
            success=True,
            message="Entry link retrieved successfully",
            link=result.get("link"),
            data={"link": result.get("link")}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving entry link: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



# ============================================
# Entry Link URL Builder
# ============================================

@router.post("/build-entry-link/{survey_id}")
async def build_entry_link_url(
    survey_id: int,
    respondent_id: str = Query(..., description="Respondent ID"),
    country_code: str = Query(..., description="ISO country code"),
    pid: Optional[str] = Query(None, description="Panelist ID"),
    mid: Optional[str] = Query(None, description="Session/Market ID"),
    cint_service = Depends(get_cint_service),
) -> dict:
    """
    Build complete entry link URL with respondent parameters
    
    Per Lucid documentation (https://developer.lucidhq.com/#entry-links):
    - Entry links use format: https://samplicio.us/s/default.aspx?SID={SurveyID}&PID={PanelistID}
    - PID: Panelist ID (your unique respondent identifier)
    - MID: Session ID (unique session identifier)
    
    Args:
        survey_id: Cint survey ID
        respondent_id: Unique respondent ID
        country_code: ISO country code
        pid: Panelist ID (optional, defaults to respondent_id)
        mid: Session/Market ID (optional)
    
    Returns:
        {
            "success": true,
            "entry_link": "https://samplicio.us/s/...?rid=...&cc=...&pid=...&mid=..."
        }
    """
    try:
        logger.info(f"Building entry link for survey {survey_id}")
        
        # Get cached entry link from MongoDB or fetch from API
        link_result = await cint_service.get_entry_link(survey_id)
        
        if link_result.get("success") and link_result.get("link"):
            live_link = link_result["link"].LiveLink if hasattr(link_result["link"], 'LiveLink') else link_result["link"].get("LiveLink", "")
            
            if live_link:
                # Build entry link with respondent parameters
                entry_link = cint_service.build_entry_link(
                    live_link=live_link,
                    respondent_id=respondent_id,
                    country_code=country_code,
                    pid=pid or respondent_id,
                    mid=mid,
                )
                
                return {
                    "success": True,
                    "entry_link": entry_link,
                    "survey_id": survey_id,
                }
        
        # If no entry link exists, return template with instructions
        return {
            "success": False,
            "message": "Entry link not found. Create one first via POST /cint/entry-links/{survey_id}",
            "survey_id": survey_id,
            "template": f"https://samplicio.us/s/default.aspx?SID={survey_id}&PID={respondent_id}",
        }
    
    except Exception as e:
        logger.error(f"Error building entry link: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entry-link-template/{survey_id}")
async def get_entry_link_template(
    survey_id: int,
    cint_service = Depends(get_cint_service),
) -> dict:
    """
    Get entry link template for a survey (with placeholders)
    
    Per Lucid documentation:
    - [%MID%]: Macro for session ID in redirect URLs  
    - [%REVENUE%]: Macro for payout amount in success redirects
    - PID: Your panelist/respondent ID
    
    Args:
        survey_id: Cint survey ID
    
    Returns:
        Entry link template with placeholders
    """
    try:
        logger.info(f"Getting entry link template for survey {survey_id}")
        
        # Check if entry link exists in cache
        link_result = await cint_service.get_entry_link(survey_id)
        
        if link_result.get("success") and link_result.get("link"):
            link = link_result["link"]
            live_link = link.LiveLink if hasattr(link, 'LiveLink') else link.get("LiveLink", "")
            test_link = link.TestLink if hasattr(link, 'TestLink') else link.get("TestLink", "")
            
            return {
                "success": True,
                "survey_id": survey_id,
                "live_link_template": f"{live_link}&PID={{panelist_id}}" if live_link else None,
                "test_link": test_link,
                "placeholders": {
                    "{{panelist_id}}": "Your unique panelist/respondent ID",
                    "[%MID%]": "Session ID (auto-replaced by Cint)",
                    "[%REVENUE%]": "Payout amount (auto-replaced by Cint in success redirect)",
                },
            }
        
        # Return default template if no entry link configured
        return {
            "success": True,
            "survey_id": survey_id,
            "live_link_template": f"https://samplicio.us/s/default.aspx?SID={survey_id}&PID={{panelist_id}}",
            "test_link": None,
            "message": "No entry link configured. This is the default Samplicio format.",
            "placeholders": {
                "{{panelist_id}}": "Your unique panelist/respondent ID",
            },
        }
    
    except Exception as e:
        logger.error(f"Error getting entry link template: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Opportunities Management
# ============================================

@router.get("/opportunities", response_model=OpportunitiesListResponse)
async def list_opportunities(
    active_only: bool = Query(True, description="Only return active opportunities"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
):
    """
    List active opportunities from webhook cache
    
    Args:
        active_only: If true, only return active opportunities
        limit: Maximum number to return
    
    Returns:
        List of opportunities
    """
    try:
        # TODO: Get CintService from dependency injection
        # opportunities = await cint_service.get_active_opportunities(limit)
        
        logger.info(f"Listing opportunities (active_only={active_only}, limit={limit})")
        
        return OpportunitiesListResponse(
            success=False,
            count=0,
            opportunities=[]
        )
    
    except Exception as e:
        logger.error(f"Error listing opportunities: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/opportunities/{survey_id}")
async def get_opportunity(survey_id: int):
    """
    Get specific opportunity by survey ID
    
    Args:
        survey_id: Cint survey ID
    
    Returns:
        Opportunity details
    """
    try:
        # TODO: Get CintService from dependency injection
        # opportunity = await cint_service.get_opportunity_by_survey_id(survey_id)
        
        logger.info(f"Retrieving opportunity for survey {survey_id}")
        
        return {
            "success": False,
            "message": "Not yet implemented",
        }
    
    except Exception as e:
        logger.error(f"Error retrieving opportunity: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Subscription Management
# ============================================

@router.post("/subscription/opportunities")
async def create_opportunities_subscription(
    config: OpportunitiesSubscriptionConfig,
    cint_service = Depends(get_cint_service),
):
    """
    Create or update opportunities subscription
    
    Args:
        config: Subscription configuration with callback URL and filters
    
    Returns:
        {
            "success": true,
            "message": "Subscription created",
            "callback_url": "https://..."
        }
    """
    try:
        logger.info(f"Creating opportunities subscription with callback: {config.callback_url}")
        result = await cint_service.create_opportunities_subscription(config)
        
        if result.get("success"):
            logger.info("✓ Subscription created successfully")
            return {
                "success": True,
                "message": "Subscription created/updated",
                "callback_url": config.callback_url,
                "data": result.get("data"),
            }
        else:
            logger.error(f"Subscription creation failed: {result.get('error')}")
            raise HTTPException(
                status_code=result.get("status_code", 500),
                detail=result.get("error", "Failed to create subscription"),
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subscription/opportunities")
async def get_opportunities_subscription(
    cint_service = Depends(get_cint_service),
):
    """
    Get current opportunities subscription status
    
    Returns:
        Current subscription configuration
    """
    try:
        logger.info("Retrieving opportunities subscription status")
        result = await cint_service.get_opportunities_subscription()
        
        if result.get("success"):
            logger.info("✓ Subscription status retrieved")
            return {
                "success": True,
                "data": result.get("data"),
            }
        else:
            logger.warning(f"Could not retrieve subscription: {result.get('error')}")
            return {
                "success": False,
                "error": result.get("error"),
                "status_code": result.get("status_code", 500),
            }
    
    except Exception as e:
        logger.error(f"Error retrieving subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subscription/resubscribe")
async def resubscribe_with_correct_url(
    cint_service = Depends(get_cint_service),
):
    """
    Re-subscribe to opportunities webhook with the correct public callback URL.
    
    This endpoint uses the production domain (torpedo.cogentixresearch.com)
    to ensure CINT servers can reach the webhook endpoint.
    
    Returns:
        {
            "success": true,
            "message": "Subscription updated",
            "callback_url": "https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities"
        }
    """
    try:
        # Use the production callback URL
        callback_url = os.getenv(
            "CINT_WEBHOOK_CALLBACK_URL", 
            "https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities"
        )
        
        logger.info(f"Re-subscribing with correct callback URL: {callback_url}")
        
        config = OpportunitiesSubscriptionConfig(
            callback_url=callback_url,
            include_quotas=True,
            payload_max_size_mb=10,
            payload_max_survey_count=1000,
            send_interval_seconds=30,
            opportunities_filters=[],  # Default filters for English locales
        )
        
        result = await cint_service.create_opportunities_subscription(config)
        
        if result.get("success"):
            logger.info("✓ Subscription updated with correct URL")
            return {
                "success": True,
                "message": "Subscription updated with correct callback URL",
                "callback_url": callback_url,
                "data": result.get("data"),
            }
        else:
            logger.error(f"Resubscription failed: {result.get('error')}")
            raise HTTPException(
                status_code=result.get("status_code", 500),
                detail=result.get("error", "Failed to resubscribe"),
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resubscribing: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/subscription/opportunities")
async def delete_opportunities_subscription(
    cint_service = Depends(get_cint_service),
):
    """
    Delete opportunities subscription
    
    Returns:
        {
            "success": true,
            "message": "Subscription deleted"
        }
    """
    try:
        logger.info("Deleting opportunities subscription")
        result = await cint_service.delete_opportunities_subscription()

        if result.get("success"):
            logger.info("✓ Subscription deleted")
            return {
                "success": True,
                "message": "Subscription deleted",
            }
        else:
            logger.error(f"Subscription deletion failed: {result.get('error')}")
            raise HTTPException(
                status_code=result.get("status_code", 500),
                detail=result.get("error", "Failed to delete subscription"),
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# Respondent Outcomes Subscription
# ============================================

@router.post("/subscription/outcomes")
async def create_outcomes_subscription(
    config: OutcomeSubscriptionConfig,
    cint_service = Depends(get_cint_service),
):
    """
    Create or update respondent outcomes subscription.
    
    Cint will send outcome webhooks when respondent sessions complete/terminate.
    
    Args:
        config: Subscription configuration with callback URL and outcome filters
            - callback_url: Webhook URL for receiving outcomes
            - outcome_filters: Optional filters for marketplace_status/client_status
    
    Returns:
        {
            "success": true,
            "message": "Outcomes subscription created",
            "callback_url": "https://..."
        }
    """
    try:
        logger.info(f"Creating outcomes subscription with callback: {config.callback_url}")
        result = await cint_service.create_outcomes_subscription(config)
        
        if result.get("success"):
            logger.info("✓ Outcomes subscription created successfully")
            return {
                "success": True,
                "message": "Outcomes subscription created/updated",
                "callback_url": config.callback_url,
                "data": result.get("data"),
            }
        else:
            logger.error(f"Outcomes subscription creation failed: {result.get('error')}")
            raise HTTPException(
                status_code=result.get("status_code", 500),
                detail=result.get("error", "Failed to create outcomes subscription"),
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating outcomes subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subscription/outcomes")
async def get_outcomes_subscription(
    cint_service = Depends(get_cint_service),
):
    """
    Get current respondent outcomes subscription status.
    
    Returns:
        Current subscription configuration or error if not found
    """
    try:
        logger.info("Retrieving outcomes subscription status")
        result = await cint_service.get_outcomes_subscription()
        
        if result.get("success"):
            logger.info("✓ Outcomes subscription status retrieved")
            return {
                "success": True,
                "data": result.get("data"),
            }
        else:
            return {
                "success": False,
                "error": result.get("error"),
                "status_code": result.get("status_code", 404),
            }
    
    except Exception as e:
        logger.error(f"Error retrieving outcomes subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/subscription/outcomes")
async def delete_outcomes_subscription(
    cint_service = Depends(get_cint_service),
):
    """
    Delete respondent outcomes subscription.
    
    Returns:
        {
            "success": true,
            "message": "Outcomes subscription deleted"
        }
    """
    try:
        logger.info("Deleting outcomes subscription")
        result = await cint_service.delete_outcomes_subscription()
        
        if result.get("success"):
            logger.info("✓ Outcomes subscription deleted")
            return {
                "success": True,
                "message": "Outcomes subscription deleted",
            }
        else:
            logger.error(f"Outcomes subscription deletion failed: {result.get('error')}")
            raise HTTPException(
                status_code=result.get("status_code", 500),
                detail=result.get("error", "Failed to delete outcomes subscription"),
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting outcomes subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Settings Management
# ============================================

@router.post("/settings", response_model=SettingsResponse)
async def update_cint_settings(
    settings: CintSettings,
):
    """
    Update Cint integration settings
    
    Args:
        settings: Cint settings (API key, supplier code, webhook URLs, etc.)
    
    Returns:
        Updated settings
    """
    try:
        # TODO: Validate API key by making test API call
        # TODO: Save to MongoDB
        
        logger.info(f"Updating Cint settings for supplier {settings.supplier_code}")
        
        return SettingsResponse(
            success=False,
            settings=settings
        )
    
    except Exception as e:
        logger.error(f"Error updating settings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/settings", response_model=SettingsResponse)
async def get_cint_settings():
    """
    Get current Cint integration settings
    
    Returns:
        Current settings (API key hidden)
    """
    try:
        # TODO: Get settings from MongoDB
        
        logger.info("Retrieving Cint settings")
        
        return SettingsResponse(
            success=False,
            settings=None
        )
    
    except Exception as e:
        logger.error(f"Error retrieving settings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Health Check
# ============================================

@router.get("/health")
async def health_check():
    """
    Health check endpoint for Cint integration
    
    Returns:
        {
            "status": "ok",
            "timestamp": "2026-01-08T12:34:56Z"
        }
    """
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": "cint-integration"
    }


# ============================================
# Legacy Fulcrum API - Survey Sync
# ============================================

@router.post("/sync-offerwall")
async def sync_surveys_from_offerwall(
    apply_filters: bool = Query(True, description="Apply filter criteria to surveys"),
    cint_service = Depends(get_cint_service),
):
    """
    Sync surveys from legacy Fulcrum/Samplicio AllOfferwall API.
    
    Use this endpoint when webhooks are not available (legacy accounts).
    This fetches all available surveys and stores them in MongoDB.
    
    Args:
        apply_filters: If True, only store surveys passing filter criteria
        
    Returns:
        {
            "success": true,
            "stats": {"fetched": 1000, "stored": 500, "filtered_out": 500}
        }
    """
    try:
        logger.info("Starting Fulcrum offerwall sync...")
        result = await cint_service.sync_surveys_from_offerwall(apply_filters=apply_filters)
        return result
    except Exception as e:
        logger.error(f"Fulcrum sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fetch-offerwall")
async def fetch_surveys_from_offerwall(
    cint_service = Depends(get_cint_service),
):
    """
    Fetch surveys from legacy Fulcrum API without storing (preview only).
    
    Returns:
        {
            "success": true,
            "surveys": [...],
            "total": 1000
        }
    """
    try:
        result = await cint_service.fetch_surveys_from_offerwall()
        # Limit response size for preview
        if result.get("success") and len(result.get("surveys", [])) > 10:
            result["surveys"] = result["surveys"][:10]
            result["note"] = "Showing first 10 surveys only. Use /sync-offerwall to store all."
        return result
    except Exception as e:
        logger.error(f"Fulcrum fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Survey Pool - Filtered Surveys
# ============================================

@router.post("/sync-active")
@router.post("/sync-active-status")  # Alias for frontend compatibility (matches CPX endpoint name)
async def sync_active_status(
    cint_service = Depends(get_cint_service),
) -> Dict[str, Any]:
    """
    Sync active status for all CINT surveys based on filter criteria.
    
    This endpoint applies the configured filter settings (max_loi, min_cpi, min_incidence)
    to all surveys in the pool and marks them as:
    - is_active_in_pool=True: Surveys that match the filter criteria
    - is_active_in_pool=False: Surveys that don't match
    
    Similar to CPX's sync_active_status_by_filters functionality.
    
    Returns:
        {
            "success": true,
            "message": "Synced active status for 47000 surveys",
            "total": 47000,
            "active": 12500,
            "inactive": 34500,
            "filters_applied": {
                "max_loi": 20,
                "min_cpi": 1.0,
                "min_incidence": 60
            }
        }
    """
    try:
        logger.info("Syncing CINT survey active status by filter criteria")
        result = cint_service.sync_active_status_by_filters()
        return result
    except Exception as e:
        logger.error(f"Error syncing active status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Rate Card Endpoint - Aggregated CPI Matrix
# ============================================

# Define IR ranges (rows)
IR_RANGES = [
    {"label": "<5%", "min": 0, "max": 5},
    {"label": "6-10%", "min": 6, "max": 10},
    {"label": "11-20%", "min": 11, "max": 20},
    {"label": "21-30%", "min": 21, "max": 30},
    {"label": "31-40%", "min": 31, "max": 40},
    {"label": "41-50%", "min": 41, "max": 50},
    {"label": "51-60%", "min": 51, "max": 60},
    {"label": "61-70%", "min": 61, "max": 70},
    {"label": "71-80%", "min": 71, "max": 80},
    {"label": "81-90%", "min": 81, "max": 90},
    {"label": "91-100%", "min": 91, "max": 100},
]

# Define LOI ranges (columns)
LOI_RANGES = [
    {"label": "<5 min", "min": 0, "max": 4},
    {"label": "5-10 min", "min": 5, "max": 10},
    {"label": "10-15 min", "min": 11, "max": 15},
    {"label": "15-20 min", "min": 16, "max": 20},
    {"label": "20-30 min", "min": 21, "max": 30},
    {"label": ">30 min", "min": 31, "max": 9999},
]

@router.get("/surveys/rate-card")
async def get_rate_card(
    country: Optional[str] = Query(None, description="Filter by country code (e.g., US, CA, GB, AU)"),
    cint_service = Depends(get_cint_service),
) -> Dict[str, Any]:
    """
    Get rate card matrix - aggregated CPI by IR and LOI ranges
    
    Returns a matrix of average CPI rates organized by:
    - Rows: Incidence Rate (IR) ranges
    - Columns: Length of Interview (LOI) ranges
    
    Args:
        country: Country code to filter (extracted from country_language like "eng_us" -> "US")
        cint_service: CintService instance
    
    Returns:
        {
            "success": true,
            "country": "US",
            "countries": ["US", "CA", "GB", "AU"],
            "ir_ranges": [...],
            "loi_ranges": [...],
            "matrix": [[{avg, min, max, count}, ...], ...],
            "total_surveys": 8500,
            "filtered_surveys": 5200
        }
    """
    try:
        logger.info(f"Building rate card matrix for country: {country}")
        
        # Get all surveys (no pagination limit for internal use)
        all_surveys = cint_service.get_all_surveys_for_rate_card()
        total_surveys = len(all_surveys)
        
        # Extract country from country_language (e.g., "eng_us" -> "US")
        def extract_country(survey):
            cl = survey.get("country_language", "")
            if isinstance(cl, str) and "_" in cl:
                return cl.split("_")[-1].upper()
            return None
        
        # Get unique countries
        countries = sorted(set(filter(None, [extract_country(s) for s in all_surveys])))
        
        # Filter by country if specified
        if country:
            country_upper = country.upper()
            all_surveys = [s for s in all_surveys if extract_country(s) == country_upper]
        
        filtered_surveys = len(all_surveys)
        
        # Initialize matrix with empty cells
        matrix = []
        for ir_range in IR_RANGES:
            row = []
            for loi_range in LOI_RANGES:
                row.append({
                    "avg": None,
                    "min": None,
                    "max": None,
                    "count": 0,
                    "surveys": []
                })
            matrix.append(row)
        
        # Populate matrix with survey data
        for survey in all_surveys:
            ir = survey.get("bid_incidence")
            loi = survey.get("length_of_interview") or survey.get("bid_length_of_interview")
            
            # Extract CPI from revenue_per_interview
            rpi = survey.get("revenue_per_interview")
            cpi = None
            if rpi:
                if isinstance(rpi, dict):
                    cpi = float(rpi.get("value", 0))
                elif isinstance(rpi, (int, float)):
                    cpi = float(rpi)
            
            if ir is None or loi is None or cpi is None or cpi <= 0:
                continue
            
            # Find IR range index
            ir_idx = None
            for i, r in enumerate(IR_RANGES):
                if r["min"] <= ir <= r["max"]:
                    ir_idx = i
                    break
            
            # Find LOI range index
            loi_idx = None
            for j, r in enumerate(LOI_RANGES):
                if r["min"] <= loi <= r["max"]:
                    loi_idx = j
                    break
            
            if ir_idx is not None and loi_idx is not None:
                cell = matrix[ir_idx][loi_idx]
                cell["surveys"].append(cpi)
                cell["count"] += 1
        
        # Calculate averages, min, max for each cell
        for row in matrix:
            for cell in row:
                if cell["count"] > 0:
                    surveys = cell["surveys"]
                    cell["avg"] = round(sum(surveys) / len(surveys), 2)
                    cell["min"] = round(min(surveys), 2)
                    cell["max"] = round(max(surveys), 2)
                del cell["surveys"]  # Don't send raw data to frontend
        
        return {
            "success": True,
            "country": country.upper() if country else None,
            "countries": countries,
            "ir_ranges": [r["label"] for r in IR_RANGES],
            "loi_ranges": [r["label"] for r in LOI_RANGES],
            "matrix": matrix,
            "total_surveys": total_surveys,
            "filtered_surveys": filtered_surveys,
        }
    
    except Exception as e:
        logger.error(f"Error building rate card: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/surveys")
async def get_surveys(
    min_loi: Optional[int] = Query(None, ge=1, le=60, description="Minimum LOI in minutes"),
    max_loi: Optional[int] = Query(None, ge=1, le=120, description="Maximum LOI in minutes"),
    min_cpi: Optional[float] = Query(None, ge=0, description="Minimum CPI in USD"),
    country: Optional[str] = Query(None, description="Filter by country code (e.g., US, CA, GB)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=1000, description="Items per page (max 1000)"),
    active_only: bool = Query(False, description="Only return surveys active in the pool (for traffic routing)"),
    show_all: bool = Query(False, description="Show ALL surveys without applying default filters"),
    cint_service = Depends(get_cint_service),
) -> Dict[str, Any]:
    """
    Get filtered Cint surveys from survey pool
    
    This endpoint returns cached surveys from MongoDB that match the filter criteria.
    Surveys are updated via webhook every 15 seconds from Cint.
    
    Args:
        min_loi: Minimum Length of Interview (minutes)
        max_loi: Maximum Length of Interview (minutes)
        min_cpi: Minimum Cost Per Completion (USD)
        country: Country code filter (e.g., "US")
        page: Page number (1-indexed)
        page_size: Results per page (max 100)
        active_only: If true, only return surveys that are active in the pool
        show_all: If true, bypass default filters and show all surveys
        cint_service: CintService instance
    
    Returns:
        {
            "success": true,
            "surveys": [
                {
                    "survey_id": 12345,
                    "country_language": "US-EN",
                    "length_of_interview": 15,
                    "payout": 1.50,
                    "conversion_rate": 0.45,
                    "is_active": true,
                    "is_active_in_pool": true,
                    ...
                }
            ],
            "total": 245,
            "page": 1,
            "page_size": 20,
            "filtered": true
        }
    """
    try:
        logger.info(f"Fetching Cint surveys - page {page}, filters: LOI={min_loi}-{max_loi}, CPI={min_cpi}, Country={country}, active_only={active_only}, show_all={show_all}")
        
        result = cint_service.get_surveys(
            min_loi=min_loi,
            max_loi=max_loi,
            min_cpi=min_cpi,
            country=country,
            page=page,
            page_size=page_size,
            active_only=active_only,
            apply_default_filters=not show_all,  # Bypass default filters when show_all=true
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Error fetching surveys: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# WebSocket - Real-time Survey Updates
# ============================================

@router.websocket("/ws/surveys")
async def cint_surveys_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time CINT survey updates.
    
    Clients connect to receive instant notifications when:
    - New surveys are received via webhook
    - Survey quotas or status change
    - Surveys are deactivated
    
    Messages sent to client:
    - connected: Connection confirmation
    - surveys_update: New/updated surveys data
    - heartbeat: Keep-alive ping every 30 seconds
    
    Example client usage (JavaScript):
    ```javascript
    const ws = new WebSocket('ws://localhost:8000/api/cint/ws/surveys');
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
        # Connect to the cint_surveys channel
        connected = await connection_manager.connect(
            websocket, 
            channel="cint_surveys",
            metadata={"connected_from": "cint_router"}
        )
        
        if not connected:
            return
        
        logger.info("CINT WebSocket client connected")
        
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
                except:
                    break
                    
    except WebSocketDisconnect:
        logger.info("CINT WebSocket client disconnected")
    except Exception as e:
        logger.error(f"CINT WebSocket error: {e}")
    finally:
        connection_manager.disconnect(websocket, "cint_surveys")


@router.get("/ws/status")
async def get_websocket_status():
    """
    Get WebSocket connection status for CINT surveys.
    
    Returns:
        {
            "available": true,
            "connected_clients": 5,
            "channel": "cint_surveys"
        }
    """
    if not WEBSOCKET_AVAILABLE or not connection_manager:
        return {
            "available": False,
            "connected_clients": 0,
            "channel": "cint_surveys",
            "message": "WebSocket manager not initialized"
        }
    
    return {
        "available": True,
        "connected_clients": connection_manager.get_connection_count("cint_surveys"),
        "channel": "cint_surveys"
    }


@router.get("/diagnostic")
async def diagnostic_check(cint_service = Depends(get_cint_service)):
    """
    Diagnostic endpoint to check Cint integration status.

    Checks:
    1. Are inventories being downloaded?
    2. Are entry links being created?
    3. Do entry links have live_link populated?

    Returns:
        Diagnostic information about surveys and entry links
    """
    if cint_service is None:
        raise HTTPException(status_code=503, detail="Cint service not initialized")

    diagnostics = {
        "timestamp": datetime.utcnow().isoformat(),
        "surveys": {},
        "entry_links": {},
        "issues": [],
        "recommendations": []
    }

    try:
        # Check surveys collection
        if cint_service.cint_surveys_collection is not None:
            total_surveys = cint_service.cint_surveys_collection.count_documents({})
            active_surveys = cint_service.cint_surveys_collection.count_documents({"is_active": True})
            live_surveys = cint_service.cint_surveys_collection.count_documents({"is_live": True})

            diagnostics["surveys"] = {
                "total": total_surveys,
                "active": active_surveys,
                "live": live_surveys,
                "collection_name": "cint_surveys"
            }

            # Get sample surveys
            sample_surveys = list(cint_service.cint_surveys_collection.find(
                {},
                {
                    "survey_id": 1,
                    "survey_name": 1,
                    "is_live": 1,
                    "is_active": 1,
                    "message_reason": 1,
                    "total_remaining": 1,
                    "received_at": 1,
                    "created_at": 1
                }
            ).sort("created_at", -1).limit(5))

            # Convert ObjectId to string
            for survey in sample_surveys:
                if "_id" in survey:
                    survey["_id"] = str(survey["_id"])
                if "created_at" in survey and hasattr(survey["created_at"], "isoformat"):
                    survey["created_at"] = survey["created_at"].isoformat()
                if "received_at" in survey and hasattr(survey["received_at"], "isoformat"):
                    survey["received_at"] = survey["received_at"].isoformat()

            diagnostics["surveys"]["samples"] = sample_surveys

            # Check if surveys are being received
            if total_surveys == 0:
                diagnostics["issues"].append("No surveys found in database")
                diagnostics["recommendations"].append("Check if webhook subscription is active")
                diagnostics["recommendations"].append("Verify CINT_WEBHOOK_CALLBACK_URL is correct")

        # Check entry links collection
        if cint_service.cint_entry_links_collection is not None:
            total_links = cint_service.cint_entry_links_collection.count_documents({})
            links_with_live = cint_service.cint_entry_links_collection.count_documents(
                {"live_link": {"$exists": True, "$ne": None}}
            )
            links_without_live = total_links - links_with_live

            diagnostics["entry_links"] = {
                "total": total_links,
                "with_live_link": links_with_live,
                "without_live_link": links_without_live,
                "collection_name": "cint_entry_links"
            }

            # Get sample entry links
            sample_links = list(cint_service.cint_entry_links_collection.find(
                {},
                {
                    "survey_id": 1,
                    "live_link": 1,
                    "test_link": 1,
                    "supplier_link_type_code": 1,
                    "created_at": 1
                }
            ).sort("created_at", -1).limit(5))

            # Convert ObjectId to string
            for link in sample_links:
                if "_id" in link:
                    link["_id"] = str(link["_id"])
                if "created_at" in link and hasattr(link["created_at"], "isoformat"):
                    link["created_at"] = link["created_at"].isoformat()

            diagnostics["entry_links"]["samples"] = sample_links

            # Check for issues
            if total_links == 0 and total_surveys > 0:
                diagnostics["issues"].append("No entry links found despite having surveys")
                diagnostics["recommendations"].append("Run POST /api/cint/auto-create-entry-links to create entry links")

            if links_without_live > 0:
                diagnostics["issues"].append(f"{links_without_live} entry links missing live_link field")
                diagnostics["recommendations"].append("Check Cint API response format - may have changed structure")
                diagnostics["recommendations"].append("Verify API credentials have permission to create entry links")

        # Check webhook subscription status
        try:
            sub_result = await cint_service.get_opportunities_subscription()
            diagnostics["subscription"] = {
                "status": "active" if sub_result.get("success") else "inactive",
                "details": sub_result
            }

            if not sub_result.get("success"):
                diagnostics["issues"].append("Webhook subscription is not active")
                diagnostics["recommendations"].append("Create webhook subscription via POST /api/cint/subscription/opportunities")
        except Exception as sub_err:
            diagnostics["subscription"] = {
                "status": "error",
                "error": str(sub_err)
            }

        # Overall health check
        if not diagnostics["issues"]:
            diagnostics["status"] = "healthy"
            diagnostics["message"] = "All checks passed"
        else:
            diagnostics["status"] = "issues_found"
            diagnostics["message"] = f"Found {len(diagnostics['issues'])} issues"

        return diagnostics

    except Exception as e:
        logger.error(f"Diagnostic check failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Diagnostic failed: {str(e)}")

