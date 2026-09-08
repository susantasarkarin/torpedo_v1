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

from datetime import datetime, timedelta, timezone

from app.models.ai_proposal import REVIEW_ACTIONS, AiProposal
from app.models.base import CanonicalRepository

# Phase 11 (human governance) — an operational cadence choice (like Slice 10's
# 7-day inactivity window), not a locked business rule: a proposal still
# unreviewed after this long is "stale" for observability purposes.
STALE_REVIEW_THRESHOLD = timedelta(hours=24)


class ApprovalError(Exception):
    """Proposal missing, review action outside the closed set, a proposal
    reviewed twice, or `modified_fields` supplied for a non-MODIFY action.
    Same discipline as every other domain's single error type."""


class ApprovalService:
    def __init__(self, proposals: CanonicalRepository[AiProposal]):
        self._proposals = proposals

    async def list_pending(self, *, org_id: str, task: str | None = None, older_than: timedelta | None = None) -> list[AiProposal]:
        """The deterministic candidate set a human review UI would page
        through — proposals nobody has recorded a verdict on yet, in this
        org, optionally narrowed to one task and/or to only the stale ones
        (created more than `older_than` ago) — real staleness protection
        using `AiProposal.created_at`, which every proposal already carries,
        rather than a new field invented for this purpose."""
        query: dict = {"org_id": org_id, "reviewed_by": None}
        if task:
            query["task"] = task
        if older_than is not None:
            query["created_at"] = {"$lt": datetime.now(timezone.utc) - older_than}
        return await self._proposals.find_all(query)

    async def review(self, *, proposal_id: str, actor: str, action: str, notes: str | None = None, modified_fields: dict | None = None) -> AiProposal:
        if action not in REVIEW_ACTIONS:
            raise ApprovalError(f"unrecognized review action {action!r} — must be one of {sorted(REVIEW_ACTIONS)}")
        if modified_fields is not None and action != "MODIFY":
            raise ApprovalError(f"modified_fields was supplied for action {action!r} — only MODIFY carries a structured change")
        proposal = await self._proposals.get(proposal_id)
        if proposal is None:
            raise ApprovalError(f"proposal {proposal_id} does not exist")
        if proposal.reviewed_by is not None:
            raise ApprovalError(f"proposal {proposal_id} was already reviewed by {proposal.reviewed_by} — review is one-time, not a running commentary")

        return await self._proposals.update(
            proposal.id, proposal.version,
            {"reviewed_by": actor, "reviewed_at": datetime.now(timezone.utc), "review_action": action, "review_notes": notes, "modified_fields": modified_fields},
            updated_by=actor,
        )
