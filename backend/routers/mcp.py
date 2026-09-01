# backend/routers/mcp.py
# REST API endpoints for MCP Action Router

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field
from pymongo import MongoClient
import os


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


# MCP imports
from mcp import get_action_router, MCPActionRouter, MCPAction, MCPActionCreate, MCPActionBatch, ActionStatus, ActionType, EntityType, ActionPriority
from rbac.decorators import require_permission, require_any_permission
from rbac.permissions import Permissions


router = APIRouter(
    prefix="/api/mcp",
    tags=["MCP Action Router"],
)


# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
client = _get_pooled_client()


def get_router() -> MCPActionRouter:
    """Get MCP action router instance"""
    return get_action_router(client)


def get_current_user_context():
    """Get current user from session - placeholder"""
    return {
        "user_id": "system",
        "user_name": "System User",
    }


# ==================== RESPONSE MODELS ====================

class PaginatedActions(BaseModel):
    """Paginated list of actions"""
    items: List[MCPAction]
    total: int
    skip: int
    limit: int


class ActionSubmitRequest(BaseModel):
    """Request to submit an action"""
    entity_type: str
    action_type: str
    entity_id: Optional[str] = None
    data: dict = Field(default_factory=dict)
    reason: Optional[str] = None
    priority: str = "normal"
    is_dry_run: bool = False
    skip_approval: bool = False


class BatchSubmitRequest(BaseModel):
    """Request to submit a batch of actions"""
    actions: List[ActionSubmitRequest]
    atomic: bool = True
    reason: Optional[str] = None


class RollbackRequest(BaseModel):
    """Request to rollback an action"""
    reason: Optional[str] = None


class BatchRollbackRequest(BaseModel):
    """Request to rollback multiple actions"""
    action_ids: List[str]
    reason: Optional[str] = None


# ==================== ACTION ENDPOINTS ====================

@router.post("/actions", response_model=MCPAction)
async def submit_action(request: ActionSubmitRequest):
    """
    Submit an action for execution.
    
    Actions are validated, checked for approval requirements, and executed.
    Use is_dry_run=true to preview changes without executing.
    """
    router_instance = get_router()
    user_ctx = get_current_user_context()
    
    try:
        entity_type = EntityType(request.entity_type)
        action_type = ActionType(request.action_type)
        priority = ActionPriority(request.priority)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid enum value: {e}")
    
    action_create = MCPActionCreate(
        entity_type=entity_type,
        action_type=action_type,
        entity_id=request.entity_id,
        data=request.data,
        reason=request.reason,
        priority=priority,
        is_dry_run=request.is_dry_run,
        skip_approval=request.skip_approval,
    )
    
    action = router_instance.submit_action(
        action_create,
        user_id=user_ctx["user_id"],
        user_name=user_ctx["user_name"],
    )
    
    return action


@router.post("/actions/batch")
async def submit_batch(request: BatchSubmitRequest):
    """
    Submit a batch of actions for execution.
    
    If atomic=true, all actions must succeed or all are rolled back.
    """
    router_instance = get_router()
    user_ctx = get_current_user_context()
    
    action_creates = []
    for req in request.actions:
        try:
            entity_type = EntityType(req.entity_type)
            action_type = ActionType(req.action_type)
            priority = ActionPriority(req.priority)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid enum value: {e}")
        
        action_creates.append(MCPActionCreate(
            entity_type=entity_type,
            action_type=action_type,
            entity_id=req.entity_id,
            data=req.data,
            reason=req.reason,
            priority=priority,
            is_dry_run=req.is_dry_run,
            skip_approval=req.skip_approval,
        ))
    
    batch = MCPActionBatch(
        actions=action_creates,
        atomic=request.atomic,
        reason=request.reason,
    )
    
    actions, all_succeeded = router_instance.submit_batch(
        batch,
        user_id=user_ctx["user_id"],
        user_name=user_ctx["user_name"],
    )
    
    return {
        "actions": actions,
        "all_succeeded": all_succeeded,
        "total": len(actions),
        "completed": sum(1 for a in actions if a.status == ActionStatus.COMPLETED),
        "failed": sum(1 for a in actions if a.status == ActionStatus.FAILED),
    }


@router.get("/actions", response_model=PaginatedActions)
async def list_actions(
    status: Optional[str] = Query(None, description="Filter by status"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    initiated_by: Optional[str] = Query(None, description="Filter by initiator"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """List actions with optional filtering"""
    router_instance = get_router()
    
    status_enum = None
    if status:
        try:
            status_enum = ActionStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    entity_type_enum = None
    if entity_type:
        try:
            entity_type_enum = EntityType(entity_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}")
    
    actions, total = router_instance.list_actions(
        status=status_enum,
        entity_type=entity_type_enum,
        initiated_by=initiated_by,
        skip=skip,
        limit=limit,
    )
    
    return PaginatedActions(
        items=actions,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/actions/{action_id}", response_model=MCPAction)
async def get_action(action_id: str):
    """Get a specific action by ID"""
    router_instance = get_router()
    action = router_instance.get_action(action_id)
    
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    
    return action


@router.post("/actions/{action_id}/execute", response_model=MCPAction)
@require_any_permission(Permissions.SYSTEM_APPROVAL_MANAGE, Permissions.ADMIN_ALL)
async def execute_approved_action(action_id: str):
    """
    Execute an action that was awaiting approval.
    Requires SYSTEM_APPROVAL_MANAGE or ADMIN permission.
    """
    router_instance = get_router()
    user_ctx = get_current_user_context()
    
    try:
        action = router_instance.execute_approved_action(
            action_id,
            approver_id=user_ctx["user_id"],
        )
        return action
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/actions/{action_id}/cancel", response_model=MCPAction)
async def cancel_action(action_id: str):
    """Cancel a pending or awaiting approval action"""
    router_instance = get_router()
    user_ctx = get_current_user_context()
    
    try:
        action = router_instance.cancel_action(
            action_id,
            user_id=user_ctx["user_id"],
        )
        return action
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== ROLLBACK ENDPOINTS ====================

@router.post("/actions/{action_id}/rollback", response_model=MCPAction)
async def rollback_action(action_id: str, request: RollbackRequest = Body(default={})):
    """
    Rollback a completed action.
    
    Rollback is only available for:
    - Completed actions
    - Actions within 24 hour window
    - Actions without dependent changes
    """
    router_instance = get_router()
    user_ctx = get_current_user_context()
    
    try:
        action = router_instance.rollback_action(
            action_id,
            user_id=user_ctx["user_id"],
        )
        return action
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actions/batch-rollback")
async def batch_rollback(request: BatchRollbackRequest):
    """
    Rollback multiple actions in reverse order.
    """
    router_instance = get_router()
    user_ctx = get_current_user_context()
    
    rolled_back = []
    failed = []
    
    for action_id in request.action_ids:
        try:
            action = router_instance.rollback_action(
                action_id,
                user_id=user_ctx["user_id"],
            )
            rolled_back.append(action)
        except Exception as e:
            failed.append({"action_id": action_id, "error": str(e)})
    
    return {
        "rolled_back": rolled_back,
        "failed": failed,
        "total_rolled_back": len(rolled_back),
        "total_failed": len(failed),
    }


# ==================== REFERENCE ENDPOINTS ====================

@router.get("/entity-types")
async def list_entity_types():
    """List all supported entity types"""
    return {
        "entity_types": [
            {"value": e.value, "label": e.value.replace("_", " ").title()}
            for e in EntityType
        ]
    }


@router.get("/action-types")
async def list_action_types():
    """List all supported action types"""
    return {
        "action_types": [
            {"value": a.value, "label": a.value.replace("_", " ").title()}
            for a in ActionType
        ]
    }


@router.get("/statuses")
async def list_statuses():
    """List all action statuses"""
    return {
        "statuses": [
            {"value": s.value, "label": s.value.replace("_", " ").title()}
            for s in ActionStatus
        ]
    }


@router.get("/schemas/{entity_type}/{action_type}")
async def get_action_schema(entity_type: str, action_type: str):
    """
    Get the validation schema for a specific entity/action combination.
    Useful for building dynamic forms.
    """
    from mcp.validators import get_validator
    
    try:
        entity_enum = EntityType(entity_type)
        action_enum = ActionType(action_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    validator = get_validator()
    schema = validator.get_schema(entity_enum, action_enum)
    
    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"No schema found for {entity_type}/{action_type}"
        )
    
    return schema
