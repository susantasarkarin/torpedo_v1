"""
Facets — the composable-roles layer (locked principle 4, schema_catalogue.md §1.2-1.6).

The one invariant every model in this file exists to enforce: **a facet is never
another person or account store.** Every facet references its parent by id
(`person_id` and/or `account_id`) and carries no independent name/email/domain field
of its own — there is nothing here a resolution algorithm could match on, because
matching on facet data is exactly how v1 grew ~15 partial person stores in the first
place (entity_map.md §0.1). `FacetService` (facet_service.py) is the only thing that
constructs these, and it always validates the parent exists first.

Deliberately absent from every facet below: business logic. `LeadState` has no
scoring, `PanelistProfile` has no reward balance, `CustomerBilling` has no invoice
totals, `VendorProfile` has no payment terms. This slice proves attachment and
identity semantics; the business logic each facet eventually carries is its own
vertical's problem (Slice 6+), not this one's.
"""

from __future__ import annotations

from app.models.base import CanonicalDocument


class LeadState(CanonicalDocument):
    """
    The persisted half of lead_generation_specification.md's state machine — the
    other half (`CONTACTABLE`) is deliberately NOT a field here. See
    lead_generation_specification.md §7's own corrected diagram: contactability is
    evaluated live against the suppression layer, never stored, and this model must
    stay that way or it reopens the exact incident (41,746 enrollments, register
    §4.5) the corrected design fixed.
    """

    person_id: str
    account_id: str | None = None
    source_type: str
    state: str = "discovered"  # discovered|enriching|qualified|disqualified|assigned|enrolled|converted
    disqualify_reason: str | None = None
    owner: str | None = None
    team: str | None = None
    icp_score: int | None = None  # set by app.leadgen.scoring's canonical scorer — never any other
    ai_decision_subject_id: str | None = None  # traces back to the AiProposal from the last evaluate_icp() call — a *different* signal from icp_score, never written by the scorer


class PanelistProfile(CanonicalDocument):
    """Status here is deliberately independent of `Person.status` — a panelist can be
    suspended without the underlying person record changing at all, and vice versa
    (a person merge must never silently alter panel standing)."""

    person_id: str
    country: str | None = None
    language: str | None = None
    status: str = "active"  # independent of Person.status — see class docstring


class CustomerBilling(CanonicalDocument):
    account_id: str
    gst_treatment: str = "unregistered"


class VendorProfile(CanonicalDocument):
    """
    Attaches to EITHER a person (an individual/freelancer vendor) or an account (a
    company vendor) — never both, and never neither. v1 modeled this exact duality
    with a `customer_type: "individual"` fallback flag on what was otherwise an
    account-shaped collection (data_lineage_map.md §2); here it's two explicit,
    mutually-exclusive reference fields instead of a type flag layered over one
    ambiguous shape.
    """

    person_id: str | None = None
    account_id: str | None = None
    status: str = "active"


class EmployeeRecord(CanonicalDocument):
    person_id: str
    department: str | None = None
    manager_id: str | None = None
    employment_status: str = "active"


class AuthIdentity(CanonicalDocument):
    """
    Links a Person to the login identity `app.auth` already tracks. Slices 2-3 were
    built before Person existed and correctly did not invent a second identity
    concept to fill that gap (`Session`/`Credential` key on an opaque `user_id`
    string) — this facet is the link, added now that there's a Person to link to,
    not a retrofit of the auth layer itself.
    """

    person_id: str
    username: str  # matches the user_id Credential/Session/UserRole already key on
