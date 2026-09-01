"""
AI ENGINE ROUTER  (/api/ai/*)

Surfaces the AI decision engine: agent registry, decision log, action queue, and
the human approval gate. Distinct from /api/approvals (generic business approvals).
"""

from fastapi import APIRouter, HTTPException, Body, Query, Depends
from typing import Optional, Dict, Any

from app.services import ai_engine
from app.security import require

router = APIRouter(prefix="/api/ai", tags=["AI Engine"])

# Coarse capability gates (enforced only when RBAC_ENABLED=true).
# Approving/rejecting AI actions requires the elevated 'approve' capability.
require_read = require("read")
require_write = require("write")
require_approve = require("approve")


@router.get("/agents")
async def list_agents(_user: str = Depends(require_read)):
    """Registered agents with their default autonomy mode and low-risk actions."""
    return {"agents": ai_engine.get_agents(), "available_actions": ai_engine.available_actions()}


@router.get("/decisions")
async def list_decisions(
    status: Optional[str] = Query(None),
    agent_name: Optional[str] = Query(None),
    limit: int = Query(200, le=1000),
    _user: str = Depends(require_read),
):
    return ai_engine.list_decisions(status=status, agent_name=agent_name, limit=limit)


@router.post("/decisions")
async def submit_decision(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_write)):
    """Submit an agent decision (logs it and routes by autonomy mode)."""
    agent_name = payload.pop("agent_name", None)
    decision = payload.pop("decision", None)
    if not agent_name or not decision:
        raise HTTPException(status_code=422, detail="agent_name and decision are required")
    try:
        return ai_engine.submit_decision(agent_name, decision=decision, **payload)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/queue")
async def list_queue(
    status: Optional[str] = Query(None, description="pending/approved/rejected/executed/failed"),
    limit: int = Query(200, le=1000),
    _user: str = Depends(require_read),
):
    return ai_engine.list_queue(status=status, limit=limit)


@router.get("/queue/{queue_id}")
async def get_queue_item(queue_id: str, _user: str = Depends(require_read)):
    try:
        item = ai_engine.get_queue_item(queue_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return item


@router.post("/queue/{queue_id}/approve")
async def approve(queue_id: str, user: str = Depends(require_approve)):
    """Approve a pending AI action -> executes it."""
    try:
        return ai_engine.approve_action(queue_id, user=user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/queue/{queue_id}/reject")
async def reject(queue_id: str, payload: Dict[str, Any] = Body(default={}), user: str = Depends(require_approve)):
    """Reject a pending AI action."""
    try:
        return ai_engine.reject_action(queue_id, user=user, reason=payload.get("reason"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
