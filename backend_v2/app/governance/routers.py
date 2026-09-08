"""HTTP surface for the human approval/review queue (Slice 22, extended Phase 11)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import require_permission
from app.db import get_database
from app.governance.approvals import ApprovalError, ApprovalService
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import GOVERNANCE_READ, GOVERNANCE_REVIEW

router = APIRouter()


def get_approval_service() -> ApprovalService:
    return ApprovalService(CanonicalRepository(get_database()["ai_proposals"], AiProposal))


class ReviewRequest(BaseModel):
    action: str
    notes: str | None = None
    modified_fields: dict | None = None


@router.get("/governance/proposals", response_model=list[AiProposal])
async def list_pending_proposals(
    task: str | None = None,
    stale_only: bool = False,
    identity: ResolvedIdentity = Depends(require_permission(GOVERNANCE_READ)),
    svc: ApprovalService = Depends(get_approval_service),
) -> list[AiProposal]:
    from app.governance.approvals import STALE_REVIEW_THRESHOLD

    return await svc.list_pending(org_id=identity.org_id, task=task, older_than=STALE_REVIEW_THRESHOLD if stale_only else None)


@router.post("/governance/proposals/{proposal_id}/review", response_model=AiProposal)
async def review_proposal(
    proposal_id: str, body: ReviewRequest,
    identity: ResolvedIdentity = Depends(require_permission(GOVERNANCE_REVIEW)),
    svc: ApprovalService = Depends(get_approval_service),
) -> AiProposal:
    try:
        return await svc.review(org_id=identity.org_id, proposal_id=proposal_id, actor=identity.user_id, action=body.action, notes=body.notes, modified_fields=body.modified_fields)
    except ApprovalError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
