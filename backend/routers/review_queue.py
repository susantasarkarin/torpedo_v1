"""
P1.6: Human Review Queue Router

REST API endpoints for managing low-confidence AI classifications
that require human review.
"""

import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field


router = APIRouter(
    prefix="/review-queue",
    tags=["AI Review Queue"]
)


# ============== MODELS ==============

class ReviewActionRequest(BaseModel):
    """Request model for review actions."""
    reviewed_by: str = Field(..., description="ID or email of the reviewer")
    notes: Optional[str] = Field(None, description="Optional review notes")


class ModifyClassificationRequest(ReviewActionRequest):
    """Request model for modifying a classification."""
    human_classification: Dict[str, Any] = Field(..., description="Corrected classification")


# ============== ENDPOINTS ==============

@router.get("/stats", response_model=Dict[str, Any])
async def get_queue_stats():
    """
    Get statistics about the review queue.
    
    Returns counts by status and entity type, plus average confidence scores.
    """
    from ..leads.review_queue import get_review_queue_service
    
    service = get_review_queue_service()
    return service.get_queue_stats()


@router.get("/pending", response_model=List[Dict[str, Any]])
async def get_pending_items(
    entity_type: Optional[str] = Query(None, description="Filter by entity type (lead, email, rfq)"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0)
):
    """
    Get pending review items.
    
    Items are sorted by queued_at descending (newest first).
    """
    from ..leads.review_queue import get_review_queue_service
    
    service = get_review_queue_service()
    return service.get_pending_items(
        entity_type=entity_type,
        limit=limit,
        skip=skip
    )


@router.get("/{queue_id}", response_model=Dict[str, Any])
async def get_queue_item(queue_id: str):
    """Get a single review queue item by ID."""
    from ..leads.review_queue import get_review_queue_service
    
    service = get_review_queue_service()
    item = service.get_item(queue_id)
    
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    
    return item


@router.post("/{queue_id}/approve", response_model=Dict[str, Any])
async def approve_classification(
    queue_id: str,
    request: ReviewActionRequest
):
    """
    Approve the AI classification as-is.
    
    This marks the classification as accepted without modifications.
    """
    from ..leads.review_queue import get_review_queue_service
    
    service = get_review_queue_service()
    success = service.approve(
        queue_id=queue_id,
        reviewed_by=request.reviewed_by,
        notes=request.notes
    )
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Could not approve item. It may not exist or was already reviewed."
        )
    
    return {
        "success": True,
        "message": "Classification approved",
        "queue_id": queue_id
    }


@router.post("/{queue_id}/reject", response_model=Dict[str, Any])
async def reject_classification(
    queue_id: str,
    request: ReviewActionRequest
):
    """
    Reject the AI classification.
    
    This marks the classification as incorrect and not usable.
    """
    from ..leads.review_queue import get_review_queue_service
    
    service = get_review_queue_service()
    success = service.reject(
        queue_id=queue_id,
        reviewed_by=request.reviewed_by,
        notes=request.notes
    )
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Could not reject item. It may not exist or was already reviewed."
        )
    
    return {
        "success": True,
        "message": "Classification rejected",
        "queue_id": queue_id
    }


@router.post("/{queue_id}/modify", response_model=Dict[str, Any])
async def modify_classification(
    queue_id: str,
    request: ModifyClassificationRequest
):
    """
    Modify the AI classification with human corrections.
    
    Provide the corrected classification data in the request body.
    """
    from ..leads.review_queue import get_review_queue_service
    
    service = get_review_queue_service()
    success = service.modify(
        queue_id=queue_id,
        reviewed_by=request.reviewed_by,
        human_classification=request.human_classification,
        notes=request.notes
    )
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Could not modify item. It may not exist or was already reviewed."
        )
    
    return {
        "success": True,
        "message": "Classification modified",
        "queue_id": queue_id
    }


@router.get("/config/threshold", response_model=Dict[str, Any])
async def get_confidence_threshold():
    """Get the current confidence threshold for review queue."""
    threshold = float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.7"))
    return {
        "confidence_threshold": threshold,
        "description": "Classifications below this confidence score are queued for human review"
    }
