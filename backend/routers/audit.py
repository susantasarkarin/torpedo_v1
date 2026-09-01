"""
API endpoints for querying the audit trail.
Provides access to entity history, user activity, and recent changes.
"""
from fastapi import APIRouter, Query
from typing import Optional, List

from audit import get_audit_logger, AuditEntry
from database import get_database

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/{entity_type}/{entity_id}", response_model=dict)
def get_entity_audit_history(
    entity_type: str,
    entity_id: str,
    limit: int = Query(100, le=1000, description="Maximum number of entries to return")
):
    """
    Get audit history for a specific entity.
    
    Returns all audit entries for the given entity type and ID,
    sorted by timestamp in descending order (most recent first).
    
    - **entity_type**: Type of entity (e.g., invoice, vendor, project, lead)
    - **entity_id**: Unique identifier of the entity
    - **limit**: Maximum number of entries to return (default: 100, max: 1000)
    """
    db = get_database("email_automation")
    audit_logger = get_audit_logger(db)
    history = audit_logger.get_history(entity_type, entity_id, limit)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "history": [entry.model_dump() for entry in history],
        "count": len(history)
    }


@router.get("/user/{user_id}", response_model=dict)
def get_user_audit_history(
    user_id: str,
    limit: int = Query(100, le=1000, description="Maximum number of entries to return")
):
    """
    Get all activity by a specific user.
    
    Returns all audit entries for actions performed by the given user,
    sorted by timestamp in descending order (most recent first).
    
    - **user_id**: Unique identifier of the user
    - **limit**: Maximum number of entries to return (default: 100, max: 1000)
    """
    db = get_database("email_automation")
    audit_logger = get_audit_logger(db)
    activity = audit_logger.get_user_activity(user_id, limit)
    return {
        "user_id": user_id,
        "activity": [entry.model_dump() for entry in activity],
        "count": len(activity)
    }


@router.get("/recent", response_model=dict)
def get_recent_audit_entries(
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(100, le=1000, description="Maximum number of entries to return")
):
    """
    Get recent audit entries with optional filters.
    
    Returns recent audit entries across all entities and users,
    sorted by timestamp in descending order (most recent first).
    
    - **entity_type**: Optional filter by entity type (e.g., invoice, vendor)
    - **action**: Optional filter by action type (create, update, delete, restore, send, classify)
    - **limit**: Maximum number of entries to return (default: 100, max: 1000)
    """
    db = get_database("email_automation")
    audit_logger = get_audit_logger(db)
    entries = audit_logger.get_recent(entity_type, action, limit)
    return {
        "entries": [entry.model_dump() for entry in entries],
        "count": len(entries),
        "filters": {
            "entity_type": entity_type,
            "action": action
        }
    }

