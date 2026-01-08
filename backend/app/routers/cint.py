"""
Cint API Integration - Router

Endpoints for:
- Webhook callbacks (opportunities, respondent outcomes)
- Entry link CRUD operations
- Settings management
- Subscription management
"""
from fastapi import APIRouter, HTTPException, Header, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import os
import json
import hmac
import hashlib

from app.models.cint import (
    CintOpportunity,
    SupplierLink,
    SupplierLinkCreate,
    SupplierLinkUpdate,
    OpportunitiesSubscriptionConfig,
    CintSettings,
    WebhookValidationRequest,
    EntryLinkResponse,
    OpportunitiesListResponse,
    SettingsResponse,
    RespondentOutcome,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cint", tags=["cint"])

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
        
        # Process through CintService
        processed = await cint_service.process_opportunity_webhook(request_body)
        
        # Update allocation metrics if extension available
        if cint_allocation and processed:
            for opp in processed:
                await cint_allocation.update_opportunity_from_webhook(
                    opp.survey_id,
                    opp.dict()
                )
        
        return {
            "success": True,
            "message": "Opportunities processed",
            "count": len(opportunities)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing opportunities webhook: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }



@router.post("/webhooks/respondent-outcomes")
async def handle_respondent_outcomes_webhook(
    request_body: dict = Body(...),
    x_cint_signature: Optional[str] = Header(None),
):
    """
    Receive respondent outcome webhook from Cint
    
    This endpoint is called by Cint when respondent sessions complete/terminate
    with status information (completed, terminated, quota_full, etc.)
    
    Args:
        request_body: Webhook payload with respondent outcome data
        x_cint_signature: HMAC-SHA256 signature for validation
    
    Returns:
        {
            "success": true,
            "message": "Outcomes processed",
            "respondent_id": "xxx"
        }
    """
    try:
        # TODO: Implement webhook signature validation
        # if x_cint_signature:
        #     if not validate_signature(request_body, x_cint_signature, webhook_secret):
        #         raise HTTPException(status_code=401, detail="Invalid signature")
        
        logger.info(f"Received respondent outcome webhook")
        logger.debug(f"Outcome: {request_body}")
        
        # TODO: Process through CintService and update respondent status
        # outcome = RespondentOutcome(**request_body)
        # await cint_service.process_respondent_outcome(outcome)
        
        return {
            "success": True,
            "message": "Outcome processed",
            "respondent_id": request_body.get("respondent_id")
        }
    
    except Exception as e:
        logger.error(f"Error processing respondent outcome: {str(e)}")
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
        
        if not result:
            raise HTTPException(status_code=404, detail=f"Failed to create entry link for survey {survey_id}")
        
        return EntryLinkResponse(
            success=True,
            message="Entry link created successfully",
            data=result
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
        
        if not result:
            raise HTTPException(status_code=404, detail=f"Entry link not found for survey {survey_id}")
        
        return EntryLinkResponse(
            success=True,
            message="Entry link updated successfully",
            data=result
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating entry link: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



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
        
        if not result:
            raise HTTPException(status_code=404, detail=f"Entry link not found for survey {survey_id}")
        
        return EntryLinkResponse(
            success=True,
            message="Entry link retrieved successfully",
            data=result
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
) -> dict:
    """
    Build complete entry link URL with respondent parameters
    
    Args:
        survey_id: Cint survey ID
        respondent_id: Unique respondent ID
        country_code: ISO country code
        pid: Panelist ID (optional)
        mid: Session/Market ID (optional)
    
    Returns:
        {
            "success": true,
            "entry_link": "https://samplicio.us/s/...?rid=...&cc=...&pid=...&mid=..."
        }
    """
    try:
        # TODO: Get CintService from dependency injection
        # entry_link = cint_service.build_entry_link(
        #     live_link=link.live_link,
        #     respondent_id=respondent_id,
        #     country_code=country_code,
        #     pid=pid,
        #     mid=mid,
        # )
        
        logger.info(f"Building entry link for survey {survey_id}")
        
        return {
            "success": False,
            "message": "Not yet implemented",
        }
    
    except Exception as e:
        logger.error(f"Error building entry link: {str(e)}")
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
        # TODO: Get CintService from dependency injection
        # result = await cint_service.create_opportunities_subscription(config)
        
        logger.info(f"Creating opportunities subscription")
        
        return {
            "success": False,
            "message": "Not yet implemented",
        }
    
    except Exception as e:
        logger.error(f"Error creating subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subscription/opportunities")
async def get_opportunities_subscription():
    """
    Get current opportunities subscription status
    
    Returns:
        Current subscription configuration
    """
    try:
        # TODO: Get CintService from dependency injection
        # result = await cint_service.get_opportunities_subscription()
        
        logger.info("Retrieving opportunities subscription")
        
        return {
            "success": False,
            "message": "Not yet implemented",
        }
    
    except Exception as e:
        logger.error(f"Error retrieving subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/subscription/opportunities")
async def delete_opportunities_subscription():
    """
    Delete opportunities subscription
    
    Returns:
        {
            "success": true,
            "message": "Subscription deleted"
        }
    """
    try:
        # TODO: Get CintService from dependency injection
        # result = await cint_service.delete_opportunities_subscription()
        
        logger.info("Deleting opportunities subscription")
        
        return {
            "success": False,
            "message": "Not yet implemented",
        }
    
    except Exception as e:
        logger.error(f"Error deleting subscription: {str(e)}")
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
# Survey Pool - Filtered Surveys
# ============================================

@router.get("/surveys")
async def get_surveys(
    min_loi: Optional[int] = Query(None, ge=1, le=60, description="Minimum LOI in minutes"),
    max_loi: Optional[int] = Query(None, ge=1, le=120, description="Maximum LOI in minutes"),
    min_cpi: Optional[float] = Query(None, ge=0, description="Minimum CPI in USD"),
    country: Optional[str] = Query(None, description="Filter by country code (e.g., US, CA, GB)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
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
        logger.info(f"Fetching Cint surveys - page {page}, filters: LOI={min_loi}-{max_loi}, CPI={min_cpi}, Country={country}")
        
        result = cint_service.get_surveys(
            min_loi=min_loi,
            max_loi=max_loi,
            min_cpi=min_cpi,
            country=country,
            page=page,
            page_size=page_size,
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Error fetching surveys: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
