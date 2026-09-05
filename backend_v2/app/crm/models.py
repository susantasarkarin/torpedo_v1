"""
Opportunity — schema_catalogue.md §2.2, built to that locked shape rather than
reinvented. Replaces v1's `crm_db.opportunities` and `email_automation.rfqs`
(entity_map.md §2.9: v1's own code comments already declared `crm_db.opportunities`
the single source — this is that consolidation actually happening).

**`contact_id` in the original schema catalogue is `person_id` here** — the register
already settled "Person, not Contact" as v2's identity-spine naming
(memory: "Person [not 'Contact' — settled naming]"), and an Opportunity's other side
is always a `Person` from Slice 4's identity layer, never a second contact record.

**`loss_reason`'s `UNSET` sentinel semantics (schema_catalogue.md, fixing v1's TOR-16)
don't need a PATCH endpoint's null-means-clear ambiguity here** — this codebase has
deferred generic `PATCH` since Slice 4 (same reasoning: `CanonicalRepository.update()`
already needs an explicit field list, not a client-supplied partial document).
`loss_reason` is only ever set by `OpportunityService.close_lost()`, one explicit
action, so there's no ambiguity between "never touched" and "explicitly cleared" to
resolve — the field is `None` until the one method that ever writes it runs.
"""

from __future__ import annotations

from pydantic import field_validator

from app.models.base import CanonicalDocument
from app.models.money import Money

NEW = "new"
RFQ = "rfq"
QUALIFIED = "qualified"
PROPOSAL = "proposal"
NEGOTIATION = "negotiation"
WON = "won"
LOST = "lost"

ACTIVE_STAGES = (NEW, RFQ, QUALIFIED, PROPOSAL, NEGOTIATION)
TERMINAL_STAGES = (WON, LOST)
ALL_STAGES = ACTIVE_STAGES + TERMINAL_STAGES


def is_valid_transition(current: str, target: str) -> bool:
    """Any active stage can move to any other active stage, or close `won`/`lost`.
    Once `won`/`lost`, no further transition is valid — closed means closed, the
    same "terminal means terminal" discipline as `app.leadgen.models`'s
    DISQUALIFIED/CONVERTED states."""
    if current in TERMINAL_STAGES:
        return False
    if target in TERMINAL_STAGES:
        return True
    return target in ACTIVE_STAGES and target != current


class Opportunity(CanonicalDocument):
    account_id: str | None = None
    person_id: str | None = None  # schema catalogue's `contact_id`, renamed per the settled Person naming
    stage: str = NEW
    amount: Money | None = None
    probability: float | None = None  # 0-1, constrained — v1's version was an unconstrained float
    loss_reason: str | None = None
    converted_invoice_id: str | None = None  # set exactly once by convert_to_invoice()

    @field_validator("probability")
    @classmethod
    def _probability_in_unit_interval(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"probability must be between 0 and 1, got {v!r}")
        return v
