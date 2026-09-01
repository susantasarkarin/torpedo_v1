# backend/routers/approvals.py
# REST API endpoints for approval workflow management

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

# Workflow engine imports
from workflows import ApprovalEngine, get_approval_engine, ApprovalRequest, ApprovalRequestCreate, ApprovalRule, ApprovalRuleCreate, ApprovalStatus, ApprovalActionType, ApprovalDecision, ApprovalStats
from rbac.decorators import require_permission, require_any_permission
from rbac.permissions import Permissions
from database import get_db


router = APIRouter(
    prefix="/api/approvals",
    tags=["Approvals"],
)


# ==================== RESPONSE MODELS ====================

class PaginatedApprovalRequests(BaseModel):
    """Paginated list of approval requests"""
    items: List[ApprovalRequest]
    total: int
    skip: int
    limit: int


class PaginatedApprovalRules(BaseModel):
    """Paginated list of approval rules"""
    items: List[ApprovalRule]
    total: int
    skip: int
    limit: int


class ApprovalDecisionRequest(BaseModel):
    """Request body for making an approval decision"""
    action: ApprovalActionType
    comment: Optional[str] = None
    delegated_to_user_id: Optional[str] = None


class CancelRequest(BaseModel):
    """Request body for cancelling an approval"""
    reason: Optional[str] = None


class CheckApprovalResponse(BaseModel):
    """Response for checking if approval is required"""
    requires_approval: bool
    rule: Optional[ApprovalRule] = None
    message: str


# ==================== HELPER FUNCTIONS ====================

def get_engine() -> ApprovalEngine:
    """Get the approval engine instance"""
    db = get_db()
    # get_db returns DatabaseManager, we need the torpedo_settings database
    settings_db = db.get_database("torpedo_settings")
    return get_approval_engine(settings_db)


def get_current_user_context():
    """
    Get current user from session/token.
    This is a placeholder - integrate with your auth system.
    """
    # TODO: Integrate with actual auth system
    return {
        "user_id": "system",
        "user_name": "System User",
        "roles": ["admin"],
    }


# ==================== APPROVAL REQUESTS ENDPOINTS ====================

@router.get("/requests", response_model=PaginatedApprovalRequests)
async def list_approval_requests(
    status: Optional[str] = Query(None, description="Filter by status"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    requested_by: Optional[str] = Query(None, description="Filter by requester user ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """
    List approval requests with optional filtering.
    Returns paginated results.
    """
    engine = get_engine()
    
    status_enum = None
    if status:
        try:
            status_enum = ApprovalStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    requests, total = engine.list_requests(
        status=status_enum,
        entity_type=entity_type,
        entity_id=entity_id,
        requested_by=requested_by,
        skip=skip,
        limit=limit,
    )
    
    return PaginatedApprovalRequests(
        items=requests,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/requests/pending", response_model=PaginatedApprovalRequests)
async def get_pending_approvals_for_current_user(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Get pending approval requests that the current user can act on.
    Based on user's direct assignment or role membership.
    """
    engine = get_engine()
    user_ctx = get_current_user_context()
    
    requests, total = engine.get_pending_for_user(
        user_id=user_ctx["user_id"],
        user_roles=user_ctx["roles"],
        skip=skip,
        limit=limit,
    )
    
    return PaginatedApprovalRequests(
        items=requests,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/requests/{request_id}", response_model=ApprovalRequest)
async def get_approval_request(request_id: str):
    """Get a specific approval request by ID"""
    engine = get_engine()
    request = engine.get_request(request_id)
    
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    
    return request


@router.post("/requests", response_model=ApprovalRequest)
async def create_approval_request(request_data: ApprovalRequestCreate):
    """
    Create a new approval request.
    If rule_id is not provided, the system will find a matching rule.
    """
    engine = get_engine()
    user_ctx = get_current_user_context()
    
    try:
        request = engine.create_request(
            request_data=request_data,
            requested_by=user_ctx["user_id"],
            requested_by_name=user_ctx["user_name"],
        )
        return request
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/requests/{request_id}/decide", response_model=ApprovalRequest)
async def make_approval_decision(
    request_id: str,
    decision: ApprovalDecisionRequest,
):
    """
    Make a decision on an approval request.
    Actions: approve, reject, escalate, delegate, comment, request_info
    """
    engine = get_engine()
    user_ctx = get_current_user_context()
    
    try:
        approval_decision = ApprovalDecision(
            action=decision.action,
            comment=decision.comment,
            delegated_to_user_id=decision.delegated_to_user_id,
        )
        
        updated_request = engine.make_decision(
            request_id=request_id,
            decision=approval_decision,
            user_id=user_ctx["user_id"],
            user_name=user_ctx["user_name"],
        )
        return updated_request
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/requests/{request_id}/cancel", response_model=ApprovalRequest)
async def cancel_approval_request(
    request_id: str,
    cancel_data: CancelRequest,
):
    """
    Cancel a pending approval request.
    Only the requester or an admin can cancel.
    """
    engine = get_engine()
    user_ctx = get_current_user_context()
    
    try:
        cancelled_request = engine.cancel_request(
            request_id=request_id,
            user_id=user_ctx["user_id"],
            reason=cancel_data.reason,
        )
        return cancelled_request
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/check", response_model=CheckApprovalResponse)
async def check_if_approval_required(
    entity_type: str = Query(..., description="Type of entity (e.g., invoice, purchase_order)"),
    action: str = Query(..., description="Action being performed (e.g., approve, create, delete)"),
    entity_data: dict = None,
):
    """
    Check if an action on an entity requires approval.
    Returns the matching rule if approval is required.
    """
    engine = get_engine()
    
    requires_approval, rule = engine.requires_approval(
        entity_type=entity_type,
        action=action,
        entity=entity_data or {},
    )
    
    if requires_approval:
        return CheckApprovalResponse(
            requires_approval=True,
            rule=rule,
            message=f"Approval required: {rule.name}" if rule else "Approval required",
        )
    else:
        return CheckApprovalResponse(
            requires_approval=False,
            rule=None,
            message="No approval required for this action",
        )


# ==================== APPROVAL RULES ENDPOINTS ====================

@router.get("/rules", response_model=PaginatedApprovalRules)
@require_any_permission(Permissions.SETTINGS_APPROVAL_VIEW, Permissions.ADMIN_ALL)
async def list_approval_rules(
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    action: Optional[str] = Query(None, description="Filter by action"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """
    List approval rules with optional filtering.
    Requires SETTINGS_APPROVAL_VIEW or ADMIN permission.
    """
    engine = get_engine()
    
    rules, total = engine.list_rules(
        entity_type=entity_type,
        action=action,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )
    
    return PaginatedApprovalRules(
        items=rules,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/rules/{rule_id}", response_model=ApprovalRule)
@require_any_permission(Permissions.SETTINGS_APPROVAL_VIEW, Permissions.ADMIN_ALL)
async def get_approval_rule(rule_id: str):
    """Get a specific approval rule by ID"""
    engine = get_engine()
    rule = engine.get_rule(rule_id)
    
    if not rule:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    
    return rule


@router.post("/rules", response_model=ApprovalRule)
@require_any_permission(Permissions.SETTINGS_APPROVAL_CREATE, Permissions.ADMIN_ALL)
async def create_approval_rule(rule_data: ApprovalRuleCreate):
    """
    Create a new approval rule.
    Requires SETTINGS_APPROVAL_CREATE or ADMIN permission.
    """
    engine = get_engine()
    user_ctx = get_current_user_context()
    
    rule = engine.create_rule(
        rule_data=rule_data,
        created_by=user_ctx["user_id"],
    )
    
    return rule


@router.put("/rules/{rule_id}", response_model=ApprovalRule)
@require_any_permission(Permissions.SETTINGS_APPROVAL_UPDATE, Permissions.ADMIN_ALL)
async def update_approval_rule(
    rule_id: str,
    updates: dict,
):
    """
    Update an approval rule.
    Requires SETTINGS_APPROVAL_UPDATE or ADMIN permission.
    """
    engine = get_engine()
    
    # Filter allowed update fields
    allowed_fields = {
        "name", "description", "conditions", "approver_roles",
        "approver_user_ids", "require_all_approvers", "min_approvals",
        "escalation", "priority", "is_active"
    }
    filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}
    
    if not filtered_updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    
    updated_rule = engine.update_rule(rule_id, filtered_updates)
    
    if not updated_rule:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    
    return updated_rule


@router.delete("/rules/{rule_id}")
@require_any_permission(Permissions.SETTINGS_APPROVAL_DELETE, Permissions.ADMIN_ALL)
async def delete_approval_rule(rule_id: str):
    """
    Delete (deactivate) an approval rule.
    Rules are soft-deleted to preserve audit history.
    Requires SETTINGS_APPROVAL_DELETE or ADMIN permission.
    """
    engine = get_engine()
    
    success = engine.delete_rule(rule_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    
    return {"status": "success", "message": "Approval rule deactivated"}


# ==================== STATS & ADMIN ENDPOINTS ====================

@router.get("/stats", response_model=ApprovalStats)
async def get_approval_stats(
    days: int = Query(30, ge=1, le=365, description="Number of days to include"),
):
    """
    Get approval statistics for the specified period.
    Includes counts by status, entity type, and average resolution time.
    """
    engine = get_engine()
    return engine.get_stats(days=days)


@router.post("/maintenance/expire")
@require_any_permission(Permissions.ADMIN_ALL)
async def run_expiration_check():
    """
    Manually run the expiration check for pending requests.
    Marks requests past their expiration date as expired.
    Requires ADMIN permission.
    """
    engine = get_engine()
    expired_count = engine.expire_old_requests()
    
    return {
        "status": "success",
        "expired_count": expired_count,
        "message": f"Marked {expired_count} request(s) as expired",
    }


@router.post("/maintenance/escalate")
@require_any_permission(Permissions.ADMIN_ALL)
async def run_escalation_check():
    """
    Manually run the escalation check for pending requests.
    Escalates requests that have exceeded their escalation threshold.
    Requires ADMIN permission.
    """
    engine = get_engine()
    escalated_ids = engine.check_and_escalate_expired()
    
    return {
        "status": "success",
        "escalated_count": len(escalated_ids),
        "escalated_ids": escalated_ids,
        "message": f"Escalated {len(escalated_ids)} request(s)",
    }


# ==================== ENTITY TYPE REFERENCE ====================

@router.get("/entity-types")
async def list_supported_entity_types():
    """
    List entity types that can have approval rules.
    This is a reference endpoint for building approval rules.
    """
    return {
        "entity_types": [
            {"value": "invoice", "label": "Invoice", "actions": ["create", "approve", "delete", "void"]},
            {"value": "purchase_order", "label": "Purchase Order", "actions": ["create", "approve", "delete"]},
            {"value": "payment", "label": "Payment", "actions": ["create", "approve"]},
            {"value": "lead", "label": "Lead", "actions": ["convert", "delete", "reassign"]},
            {"value": "deal", "label": "Deal", "actions": ["create", "close_won", "close_lost", "delete"]},
            {"value": "rfq", "label": "RFQ", "actions": ["submit", "approve", "reject"]},
            {"value": "vendor", "label": "Vendor", "actions": ["create", "approve", "deactivate"]},
            {"value": "user", "label": "User", "actions": ["create", "deactivate", "role_change"]},
            {"value": "expense", "label": "Expense", "actions": ["submit", "approve", "reject"]},
        ],
    }
