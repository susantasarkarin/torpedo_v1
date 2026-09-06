"""
AiProposal — spec §28's pipeline (`Prompt -> Model -> raw output -> ... -> Proposal
-> human approval or approved auto-apply -> write`), minimally implemented. AI output
never writes a business decision directly — this is the record of what AI proposed
and whether it was applied. A deterministic decision-maker downstream (e.g.
`app.leadgen.scoring`'s canonical ICP scorer) is what actually decides, unconditionally,
regardless of this proposal's outcome.

**Relocated here from `app/leadgen/models.py` during Slice 7** (Outreach): schema_catalogue.md
§7.1 always specified this as a Governance/AI-domain entity, not a lead-generation-specific
one. Building Slice 7's AI-drafting path made the cost of leaving it under `leadgen`
concrete — `app.outreach` would have needed to import a leadgen-owned model, or (worse)
build a second `AiProposal`-shaped record of its own, which is exactly the I-1
violation this move exists to prevent. `app.leadgen` now imports from here.

**Human review queue, Slice 22.** `status` stays exactly what it always was — the
*system's* own auto-apply verdict (`DecisionEngine.is_auto_appliable()` at the moment
the decision was made), never touched by a human review. `reviewed_by`/`reviewed_at`/
`review_action`/`review_notes` are a completely separate, additive concept: whether a
*human* has since looked at this proposal and recorded a verdict, independent of
whether the system executed anything. This is the real answer to the docstring note
this field used to carry ("never 'pending' yet, no human review queue built") — see
`app.governance.approvals.ApprovalService`.
"""

from __future__ import annotations

from datetime import datetime

from app.models.base import CanonicalDocument

REVIEW_ACTIONS = frozenset({"APPROVE", "REJECT", "MODIFY", "DEFER", "ESCALATE"})


class AiProposal(CanonicalDocument):
    task: str
    subject_id: str  # whatever entity this proposal is about — a LeadState, a Message, etc.
    model: str
    model_version: str
    confidence: float
    proposed_fields: dict
    status: str  # "approved" | "rejected" — the system's own auto-apply verdict, set once, never changed by a human review
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_action: str | None = None  # one of REVIEW_ACTIONS, once reviewed
    review_notes: str | None = None
