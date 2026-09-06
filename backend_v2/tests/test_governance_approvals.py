"""
Slice 22 — the human review queue. `AiProposal.status` is the system's own
auto-apply verdict, set once at decision time (Slice 11) — these tests prove
`review()` is a completely separate, additive concept that never touches it.
"""

from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.governance.approvals import ApprovalError, ApprovalService
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository

ORG = "org-A"


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def proposals(db) -> CanonicalRepository[AiProposal]:
    return CanonicalRepository(db["ai_proposals"], AiProposal)


@pytest.fixture
def svc(proposals) -> ApprovalService:
    return ApprovalService(proposals)


async def _proposal(proposals, *, task="evaluate_panel_allocation", org_id=ORG, status="approved") -> AiProposal:
    return await proposals.insert(AiProposal(org_id=org_id, created_by="system", updated_by="system", task=task, subject_id="subj-1", model="m", model_version="v1", confidence=0.9, proposed_fields={}, status=status))


@pytest.mark.asyncio
async def test_list_pending_returns_unreviewed_proposals_only(db, proposals, svc):
    unreviewed = await _proposal(proposals)
    reviewed = await _proposal(proposals)
    await svc.review(proposal_id=reviewed.id, actor="alice", action="APPROVE")

    pending = await svc.list_pending(org_id=ORG)
    ids = {p.id for p in pending}
    assert ids == {unreviewed.id}


@pytest.mark.asyncio
async def test_list_pending_can_be_narrowed_to_one_task(db, proposals, svc):
    await _proposal(proposals, task="evaluate_panel_allocation")
    await _proposal(proposals, task="match_payment_to_invoice")

    pending = await svc.list_pending(org_id=ORG, task="match_payment_to_invoice")
    assert len(pending) == 1
    assert pending[0].task == "match_payment_to_invoice"


@pytest.mark.asyncio
async def test_list_pending_never_crosses_orgs(db, proposals, svc):
    await _proposal(proposals, org_id=ORG)
    await _proposal(proposals, org_id="org-B")

    pending = await svc.list_pending(org_id=ORG)
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_review_records_reviewer_timestamp_action_and_notes(db, proposals, svc):
    proposal = await _proposal(proposals)
    reviewed = await svc.review(proposal_id=proposal.id, actor="alice", action="APPROVE", notes="looks right, matches expected candidate")

    assert reviewed.reviewed_by == "alice"
    assert reviewed.reviewed_at is not None
    assert reviewed.review_action == "APPROVE"
    assert reviewed.review_notes == "looks right, matches expected candidate"


@pytest.mark.asyncio
async def test_review_never_touches_the_systems_own_status_verdict(db, proposals, svc):
    """status is the AI/DecisionEngine's own auto-apply verdict, computed once
    at decision time — a human REJECTing a proposal after the fact must not
    silently rewrite history by flipping it."""
    proposal = await _proposal(proposals, status="approved")
    reviewed = await svc.review(proposal_id=proposal.id, actor="alice", action="REJECT", notes="disagree with this allocation")

    assert reviewed.status == "approved"  # unchanged — the system's own verdict, not overwritten
    assert reviewed.review_action == "REJECT"  # the human's separate, independent verdict


@pytest.mark.asyncio
async def test_unrecognized_review_action_is_rejected(db, proposals, svc):
    proposal = await _proposal(proposals)
    with pytest.raises(ApprovalError):
        await svc.review(proposal_id=proposal.id, actor="alice", action="MAYBE_LATER")


@pytest.mark.asyncio
async def test_reviewing_a_missing_proposal_raises(db, proposals, svc):
    with pytest.raises(ApprovalError):
        await svc.review(proposal_id="does-not-exist", actor="alice", action="APPROVE")


@pytest.mark.asyncio
async def test_a_proposal_cannot_be_reviewed_twice(db, proposals, svc):
    proposal = await _proposal(proposals)
    await svc.review(proposal_id=proposal.id, actor="alice", action="APPROVE")

    with pytest.raises(ApprovalError):
        await svc.review(proposal_id=proposal.id, actor="bob", action="REJECT")
