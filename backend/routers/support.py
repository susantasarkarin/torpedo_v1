# backend/routers/support.py
# REST API endpoints for Support/Tickets Module

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from datetime import datetime

from database import get_db
from support.models import (
    TicketCreate, TicketUpdate, TicketResolve, TicketEscalate,
    TicketStatus, TicketPriority, TicketCategory,
    EscalationLevel
)
from support.service import TicketService
from rbac.decorators import require_permission
from rbac.permissions import Permissions
from auth import get_current_user

router = APIRouter(prefix="/api/support", tags=["Support"])


def get_ticket_service():
    """Get ticket service instance"""
    db = get_db()
    return TicketService(db)


# ==================== TICKETS ====================

@router.post("/tickets")
@require_permission(Permissions.OPS_TICKET_CREATE)
def create_ticket(data: TicketCreate, current_user: dict = Depends(get_current_user)):
    """Create a new ticket"""
    service = get_ticket_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    ticket = service.create_ticket(data, created_by=user_id)
    return {"success": True, "data": ticket}


@router.get("/tickets")
@require_permission(Permissions.OPS_TICKET_READ)
def list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    assigned_to: Optional[str] = None,
    team_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    account_id: Optional[str] = None,
    sla_breached: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    sort_by: str = "created_at",
    sort_order: int = -1
):
    """List tickets with filters"""
    service = get_ticket_service()
    result = service.list_tickets(
        status=status,
        priority=priority,
        category=category,
        assigned_to=assigned_to,
        team_id=team_id,
        contact_id=contact_id,
        account_id=account_id,
        sla_breached=sla_breached,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order
    )
    return {"success": True, **result}


@router.get("/tickets/stats")
@require_permission(Permissions.OPS_TICKET_READ)
def get_ticket_stats(
    assigned_to: Optional[str] = None,
    team_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
):
    """Get ticket statistics"""
    service = get_ticket_service()
    stats = service.get_stats(
        assigned_to=assigned_to,
        team_id=team_id,
        start_date=start_date,
        end_date=end_date
    )
    return {"success": True, "data": stats.model_dump()}


@router.get("/tickets/my-tickets")
def get_my_tickets(
    include_closed: bool = False,
    current_user: dict = Depends(get_current_user)
):
    """Get tickets assigned to current user"""
    service = get_ticket_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    tickets = service.get_my_tickets(user_id, include_closed=include_closed)
    return {"success": True, "data": tickets}


@router.get("/tickets/sla-at-risk")
@require_permission(Permissions.OPS_TICKET_READ)
def get_sla_at_risk_tickets(threshold_hours: float = 2):
    """Get tickets at risk of SLA breach"""
    service = get_ticket_service()
    tickets = service.sla_manager.get_sla_at_risk_tickets(threshold_hours=threshold_hours)
    return {"success": True, "data": tickets}


@router.get("/tickets/{ticket_id}")
@require_permission(Permissions.OPS_TICKET_READ)
def get_ticket(ticket_id: str):
    """Get a ticket by ID"""
    service = get_ticket_service()
    ticket = service.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"success": True, "data": ticket}


@router.get("/tickets/by-number/{ticket_number}")
@require_permission(Permissions.OPS_TICKET_READ)
def get_ticket_by_number(ticket_number: str):
    """Get a ticket by ticket number"""
    service = get_ticket_service()
    ticket = service.get_ticket_by_number(ticket_number)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"success": True, "data": ticket}


@router.put("/tickets/{ticket_id}")
@require_permission(Permissions.OPS_TICKET_UPDATE)
def update_ticket(ticket_id: str, data: TicketUpdate, current_user: dict = Depends(get_current_user)):
    """Update a ticket"""
    service = get_ticket_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    ticket = service.update_ticket(ticket_id, data, updated_by=user_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"success": True, "data": ticket}


@router.post("/tickets/{ticket_id}/resolve")
@require_permission(Permissions.OPS_TICKET_UPDATE)
def resolve_ticket(
    ticket_id: str,
    data: TicketResolve,
    current_user: dict = Depends(get_current_user)
):
    """Resolve a ticket"""
    service = get_ticket_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    ticket = service.resolve_ticket(
        ticket_id=ticket_id,
        resolution=data.resolution,
        close_ticket=data.close_ticket,
        resolved_by=user_id
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"success": True, "data": ticket}


@router.post("/tickets/{ticket_id}/close")
@require_permission(Permissions.OPS_TICKET_CLOSE)
def close_ticket(ticket_id: str, current_user: dict = Depends(get_current_user)):
    """Close a ticket"""
    service = get_ticket_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    ticket = service.close_ticket(ticket_id, closed_by=user_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"success": True, "data": ticket}


@router.post("/tickets/{ticket_id}/reopen")
@require_permission(Permissions.OPS_TICKET_UPDATE)
def reopen_ticket(
    ticket_id: str,
    reason: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Reopen a closed ticket"""
    service = get_ticket_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    ticket = service.reopen_ticket(ticket_id, reason=reason, reopened_by=user_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"success": True, "data": ticket}


@router.post("/tickets/{ticket_id}/escalate")
@require_permission(Permissions.OPS_TICKET_UPDATE)
def escalate_ticket(
    ticket_id: str,
    data: TicketEscalate,
    current_user: dict = Depends(get_current_user)
):
    """Escalate a ticket"""
    service = get_ticket_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    ticket = service.escalate_ticket(
        ticket_id=ticket_id,
        level=data.level,
        reason=data.reason,
        assign_to=data.assign_to,
        escalated_by=user_id
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"success": True, "data": ticket}


@router.delete("/tickets/{ticket_id}")
@require_permission(Permissions.OPS_TICKET_DELETE)
def delete_ticket(ticket_id: str):
    """Delete a ticket"""
    service = get_ticket_service()
    success = service.delete_ticket(ticket_id)
    if not success:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"success": True, "message": "Ticket deleted"}


# ==================== COMMENTS ====================

@router.post("/tickets/{ticket_id}/comments")
@require_permission(Permissions.OPS_TICKET_UPDATE)
def add_comment(
    ticket_id: str,
    content: str,
    is_internal: bool = False,
    attachments: Optional[List[dict]] = None,
    current_user: dict = Depends(get_current_user)
):
    """Add a comment to a ticket"""
    service = get_ticket_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    user_name = current_user.get("name", current_user.get("email", ""))
    
    comment = service.add_comment(
        ticket_id=ticket_id,
        content=content,
        author_id=user_id,
        author_name=user_name,
        author_type="agent",
        is_internal=is_internal,
        attachments=attachments
    )
    return {"success": True, "data": comment}


@router.get("/tickets/{ticket_id}/comments")
@require_permission(Permissions.OPS_TICKET_READ)
def get_comments(ticket_id: str, include_internal: bool = True):
    """Get comments for a ticket"""
    service = get_ticket_service()
    comments = service.get_comments(ticket_id, include_internal=include_internal)
    return {"success": True, "data": comments}


# ==================== ACTIVITIES ====================

@router.get("/tickets/{ticket_id}/activities")
@require_permission(Permissions.OPS_TICKET_READ)
def get_activities(ticket_id: str, limit: int = Query(50, ge=1, le=200)):
    """Get activity log for a ticket"""
    service = get_ticket_service()
    activities = service.get_activities(ticket_id, limit=limit)
    return {"success": True, "data": activities}


# ==================== TEAMS ====================

@router.post("/teams")
@require_permission(Permissions.OPS_SLA_MANAGE)
def create_team(
    name: str,
    description: Optional[str] = None,
    member_ids: Optional[List[str]] = None,
    manager_ids: Optional[List[str]] = None,
    default_sla_policy_id: Optional[str] = None,
    categories: Optional[List[str]] = None
):
    """Create a support team"""
    service = get_ticket_service()
    team = service.create_team(
        name=name,
        description=description,
        member_ids=member_ids,
        manager_ids=manager_ids,
        default_sla_policy_id=default_sla_policy_id,
        categories=categories
    )
    return {"success": True, "data": team}


@router.get("/teams")
@require_permission(Permissions.OPS_TICKET_READ)
def list_teams(active_only: bool = True):
    """List support teams"""
    service = get_ticket_service()
    teams = service.list_teams(active_only=active_only)
    return {"success": True, "data": teams}


# ==================== SLA POLICIES ====================

@router.post("/sla-policies")
@require_permission(Permissions.OPS_SLA_MANAGE)
def create_sla_policy(
    name: str,
    description: Optional[str] = None,
    response_time: Optional[dict] = None,
    resolution_time: Optional[dict] = None,
    business_hours_only: bool = True
):
    """Create an SLA policy"""
    service = get_ticket_service()
    policy = service.sla_manager.create_policy(
        name=name,
        description=description,
        response_time=response_time,
        resolution_time=resolution_time,
        business_hours_only=business_hours_only
    )
    return {"success": True, "data": policy}


@router.get("/sla-policies")
@require_permission(Permissions.OPS_TICKET_READ)
def list_sla_policies(active_only: bool = True):
    """List SLA policies"""
    service = get_ticket_service()
    policies = service.sla_manager.list_policies(active_only=active_only)
    return {"success": True, "data": policies}


@router.get("/sla-policies/{policy_id}")
@require_permission(Permissions.OPS_TICKET_READ)
def get_sla_policy(policy_id: str):
    """Get an SLA policy"""
    service = get_ticket_service()
    policy = service.sla_manager.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="SLA policy not found")
    return {"success": True, "data": policy.model_dump()}


# ==================== SLA MONITORING ====================

@router.post("/sla/check-breaches")
@require_permission(Permissions.OPS_SLA_MANAGE)
def check_sla_breaches():
    """Check for SLA breaches and return breached tickets"""
    service = get_ticket_service()
    breached = service.sla_manager.check_sla_breaches()
    return {
        "success": True,
        "data": {
            "breached_count": len(breached),
            "tickets": [{"id": str(t["_id"]), "ticket_number": t.get("ticket_number"), "breach_type": t.get("breach_type")} for t in breached]
        }
    }
