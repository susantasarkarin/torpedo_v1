"""
Lead generation entities and the qualification state machine.

**Architectural gate for this whole module** (stated once, enforced by construction):
every write in `app/leadgen/` terminates at `LeadGenService`, which itself only ever
writes through `CanonicalRepository`/`IdentityService`/`FacetService`. Source
adapters, the AI classifier, and enrichment providers are pure functions that return
data to `LeadGenService` — none of them holds a database handle. There is no
`db["..."]` anywhere in this package outside the repository wiring in `routers.py`'s
provider function. This is I-6 (no write path may persist data outside a canonical
model) applied to the first real vertical, and the point of building this slice is to
find out whether that discipline actually survives contact with one.

Lead progress reuses the `LeadState` facet from Slice 5 rather than introducing a
parallel `LeadRelationship` entity — the qualification state machine
(lead_generation_specification.md §7) is the missing piece Slice 5 deliberately left
for this slice, not a reason to duplicate the facet that already exists.
"""

from __future__ import annotations

from app.models.base import CanonicalDocument

# Persisted states on LeadState.state (Slice 5's facet, extended here with the
# transitions the qualification pipeline actually drives). CONTACTABLE is
# deliberately absent — see lead_generation_specification.md §7/§9 and
# test_lead_state_has_no_stored_contactability_field (Slice 5).
DISCOVERED = "discovered"
ENRICHING = "enriching"
QUALIFIED = "qualified"
DISQUALIFIED = "disqualified"
ASSIGNED = "assigned"
ENROLLED = "enrolled"
CONVERTED = "converted"

VALID_TRANSITIONS: dict[str, set[str]] = {
    DISCOVERED: {ENRICHING},
    ENRICHING: {QUALIFIED, DISQUALIFIED},
    QUALIFIED: {ASSIGNED, DISQUALIFIED},
    DISQUALIFIED: set(),  # terminal — re-entry requires a new DISCOVERED event, not a status flip
    ASSIGNED: {ENROLLED, DISQUALIFIED},
    ENROLLED: set(),  # additional brand enrollments don't re-transition state — see LeadEnrollment
    CONVERTED: set(),
}


class RawLeadEvent(CanonicalDocument):
    """
    Staging record for one ingested event. lead_generation_specification.md §2:
    "staging, not a persisted entity" for the *content*, but the event record itself
    must persist for idempotency — `(source_type, source_record_id)` is checked
    before any identity resolution happens, so a replayed webhook or a retried
    import can never produce a second Person or a second LeadState.
    """

    source_type: str
    source_record_id: str
    payload: dict
    resolved_person_id: str | None = None
    resolved_lead_state_id: str | None = None


class LeadEnrollment(CanonicalDocument):
    """
    One row per (lead, brand) — NOT a field on LeadState. Locked principle 5 (no
    "first brand wins") applies to lead enrollment exactly as it applies to
    AccountBrandRelationship: a lead can be enrolled into multiple brands
    independently, so enrollment can't be a single scalar on the lead record.
    """

    lead_state_id: str
    person_id: str
    account_id: str | None = None
    brand_id: str
    # AI-driven outreach-sequence state (Slice 14) — deliberately a *different*
    # state machine from LeadState.state above: that one tracks qualification
    # (DISCOVERED->...->CONVERTED), this one tracks engagement within outreach
    # once enrolled (OUTREACH_READY->CONTACTED->...). See app.leadgen.ai_outreach
    # for the closed set and why the AI decides transitions rather than a fixed
    # per-state rule.
    sequence_state: str = "OUTREACH_READY"
    ai_decision_subject_id: str | None = None  # traces back to the AiProposal that last decided this enrollment's sequence_state


class DeadLetterEvent(CanonicalDocument):
    """spec §35: ingestion failures land here, explicitly, rather than being
    swallowed or crashing the caller. Minimal for this slice — retry/backoff
    scheduling is not built; the point proven here is that a failure is never
    silently dropped."""

    source_type: str
    source_record_id: str | None = None
    error: str
    payload: dict
