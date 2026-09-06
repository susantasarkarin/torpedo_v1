"""
ApprovalService — the human review queue `AiProposal`'s own docstring flagged
as missing since Slice 6/7 ("never 'pending' yet, no human review queue
built"). Every AI decision this codebase makes already becomes exactly one
`AiProposal` (`DecisionEngine.decide()`, unconditionally) — this module is the
first place a human actually *reviews* one through a real API, rather than
inspecting Mongo directly.

**Deliberately does not re-execute anything.** `status` (the system's own
auto-apply verdict, computed once, at decision time) and `review_action` (a
human's verdict, recorded independently, whenever they get to it) are two
separate fields answering two separate questions — reviewing a proposal never
changes what already happened, and never triggers a new write. Wiring a human
`APPROVE` to actually re-run the suppressed action from AI Shadow Mode (Slice
20) is the deliberate next increment, not built here: each of the five gated
services (`PanelAllocationAIService`, `OperationsAIService`, `AIFinanceService`,
`EmailAIService`, `OutreachAIService`) has its own idempotency/candidate-set
discipline around its one governed write path, and short-circuiting that
through a generic review-triggered re-execution, before the shadow-mode
validation program itself has run, would be exactly the kind of half-correct
shortcut this rebuild's discipline exists to avoid. This module's honest scope
is real: it gives a human a real, audited place to record "I looked at this
AI decision and I agree/disagree/want it changed/need more time/this needs
escalation" — which is precisely what the shadow-mode runbook's Phase D
("compare AI proposals against expected/governed outcomes") needs to not be a
manual Mongo query.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.ai_proposal import REVIEW_ACTIONS, AiProposal
from app.models.base import CanonicalRepository


class ApprovalError(Exception):
    """Proposal missing, review action outside the closed set, or a proposal
    reviewed twice. Same discipline as every other domain's single error type."""


class ApprovalService:
    def __init__(self, proposals: CanonicalRepository[AiProposal]):
        self._proposals = proposals

    async def list_pending(self, *, org_id: str, task: str | None = None) -> list[AiProposal]:
        """The deterministic candidate set a human review UI would page
        through — proposals nobody has recorded a verdict on yet, in this
        org, optionally narrowed to one task."""
        query: dict = {"org_id": org_id, "reviewed_by": None}
        if task:
            query["task"] = task
        return await self._proposals.find_all(query)

    async def review(self, *, proposal_id: str, actor: str, action: str, notes: str | None = None) -> AiProposal:
        if action not in REVIEW_ACTIONS:
            raise ApprovalError(f"unrecognized review action {action!r} — must be one of {sorted(REVIEW_ACTIONS)}")
        proposal = await self._proposals.get(proposal_id)
        if proposal is None:
            raise ApprovalError(f"proposal {proposal_id} does not exist")
        if proposal.reviewed_by is not None:
            raise ApprovalError(f"proposal {proposal_id} was already reviewed by {proposal.reviewed_by} — review is one-time, not a running commentary")

        return await self._proposals.update(
            proposal.id, proposal.version,
            {"reviewed_by": actor, "reviewed_at": datetime.now(timezone.utc), "review_action": action, "review_notes": notes},
            updated_by=actor,
        )
