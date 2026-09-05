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
"""

from __future__ import annotations

from app.models.base import CanonicalDocument


class AiProposal(CanonicalDocument):
    task: str
    subject_id: str  # whatever entity this proposal is about — a LeadState, a Message, etc.
    model: str
    model_version: str
    confidence: float
    proposed_fields: dict
    status: str  # "approved" | "rejected" — never "pending" yet, no human review queue built
