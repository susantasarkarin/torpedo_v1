"""
Survey / Allocation / SurveyResponse / Supplier / TrafficSource — the panel domain's
persisted shapes, built directly against schema_catalogue.md §5.1-5.3 rather than
reinvented.

**CPX does not exist here, structurally, not just by omission.** v2_locked_principles.md
§1.10: every CPX database, adapter, callback, and allocation branch is `REMOVE`, not
migrated. `Survey.provider` only accepts `"cint"` in this slice — there is no second
value a CPX code path could have used, and `test_survey_provider_field_cannot_be_cpx`
guards this as a model-shape invariant.

**`quota_remaining`/`cpi`/`conversion_rate` are `PROJECTION` fields** (schema_catalogue.md
§5.1): provider-owned, re-fetched via `SurveyProvider.refresh()`, never derived or
computed by Torpedo. **`eligibility_is_active_in_pool`/`eligibility_activated_at`
are `AUTHORITATIVE`**: Torpedo's own decision, never re-fetched from the provider —
the exact distinction data_lineage_map.md §4.2 draws, kept as two different write
paths (`SurveyService.refresh_projection()` vs `SurveyService.set_eligibility()`).
"""

from __future__ import annotations

from datetime import datetime

from app.models.base import CanonicalDocument
from app.models.money import Money

SURVEY_PROVIDERS = ("cint",)  # closed set — CPX removed, not a member (v2_locked_principles.md §1.10)


class Survey(CanonicalDocument):
    provider: str  # must be a member of SURVEY_PROVIDERS — enforced in SurveyService, not the model alone
    external_id: str  # one name, one type — v1 had `survey_id` as both int and str, plus an alias
    quota_remaining: int  # PROJECTION — provider-owned, see module docstring
    cpi: Money  # PROJECTION
    conversion_rate: float  # PROJECTION
    eligibility_is_active_in_pool: bool = False  # AUTHORITATIVE — Torpedo's own decision
    eligibility_activated_at: datetime | None = None  # AUTHORITATIVE
    # Real, ordinary survey attributes (Slice 15) — not fabricated, just fields
    # every panel survey actually has, needed as genuine AI-allocation context
    # (app.panel.ai_allocation). Demographic profile-fit and fraud/risk signals are
    # deliberately NOT added here — those need a consent-gated profile system and a
    # fraud-detection pipeline neither of which exists yet; see that module's
    # docstring for the honest accounting of what's real context vs. not yet built.
    category: str | None = None
    length_minutes: int | None = None
    incentive: Money | None = None
    # AI-driven operations state (Slice 16) — see app.panel.ai_operations for the
    # closed set and the state-validity guard. Distinct from
    # eligibility_is_active_in_pool: that field gates ALLOCATION specifically;
    # this one is the human-facing operational lifecycle (a paused/closed survey
    # also has eligibility_is_active_in_pool=False, but the reverse isn't
    # true — a survey can be temporarily ineligible for allocation, e.g. quota
    # exhausted, while still operationally ACTIVE).
    operational_status: str = "ACTIVE"
    # Traces the *last* AI decision made about this survey back to its AiProposal
    # — the same AiProposal -> business transaction -> transaction.ai_decision_subject_id
    # chain `Allocation.ai_decision_subject_id` (Slice 15) established, generalized
    # here per explicit user instruction to use it "throughout the rest of Torpedo."
    ai_decision_subject_id: str | None = None
    # The commercial linkage (Slice 18) — real, optional fields, not fabricated.
    # `opportunity_id` names which won `app.crm.Opportunity` this survey/study is
    # delivering for (so its client Account is reachable via
    # Opportunity.account_id); `client_rate` is what's charged to that client per
    # completed interview, deliberately distinct from `cpi` (what's owed to the
    # supplier for the same complete) — the whole point of Slice 18 is that these
    # two numbers are never the same field.
    opportunity_id: str | None = None
    client_rate: Money | None = None


class Allocation(CanonicalDocument):
    """One row per successful `AllocationService.allocate()` call. `respondent_ref` is
    Torpedo-generated (never provider-supplied) specifically so the outcome callback
    can reference it unambiguously — see `service.py`'s module docstring for why."""

    survey_id: str
    person_id: str  # the panelist being routed — resolved by the caller before allocate()
    vendor_id: str
    country_code: str
    respondent_ref: str
    redirect_url: str
    status: str = "allocated"  # allocated -> resolved (a SurveyResponse now exists for it)
    ai_decision_subject_id: str | None = None  # links back to the AiProposal that chose this
    # survey for this panelist (Slice 15's "decision memory") — None for allocations
    # made outside the AI ranking path (e.g. a direct manual/API allocation)


class SurveyResponse(CanonicalDocument):
    """Replaces `cint_research.cint_respondent_outcomes` — this is Torpedo's only
    copy (Cint's outcomes subscription is push-only, no history endpoint)."""

    allocation_id: str
    survey_id: str
    person_id: str
    respondent_ref: str
    provider: str
    external_event_id: str  # idempotency key, paired with `provider` — see CallbackService
    final_status: str  # complete | terminated | overquota | quality_term | reversed
    payout: Money | None = None  # present only for "complete"
    credited_amount: Money | None = None  # what was actually credited to the reward ledger,
    # if anything — stored explicitly so a later "reversed" callback claws back exactly
    # what was credited, never a value re-derived from payout at reversal time
    reverses_response_id: str | None = None  # set on a "reversed" SurveyResponse, pointing at the original
    # Billing (Slice 18) — set once, idempotently, by app.panel.billing.SurveyBillingService,
    # never by CallbackService itself (the raw completion fact and its billing
    # status are deliberately separate steps, the same "record now, reconcile
    # later" separation Slice 8 already uses for payments vs. reconciliation).
    billable: bool = False  # a "complete" that hasn't been reversed — set explicitly, never inferred at read time so a later reversal can't silently un-bill something already invoiced
    supplier_cost: Money | None = None  # snapshot of Survey.cpi at the moment this was marked billable — deterministic, never AI-computed
    client_invoice_id: str | None = None  # set once this complete is included on a client invoice — the guard against double-billing the same complete
    supplier_bill_id: str | None = None  # same guard, supplier side


class Supplier(CanonicalDocument):
    name: str
    provider: str  # must be a member of SURVEY_PROVIDERS
    is_active: bool = True


class TrafficSource(CanonicalDocument):
    """Replaces `traffic_flow_db.url_parameters` — the three type/casing
    inconsistencies data_lineage_map.md's D2 finding named are normalized at the
    schema level here (one `status` enum, one type per field), not left to
    application discipline the way v1's were."""

    vendor_id: str
    country_code: str
    campaign_ref: str
    status: str = "active"  # active | exhausted | paused


class SupplierReconciliationRecord(CanonicalDocument):
    """The I-5 fix for register §2.8 ('no reconciliation module, job, or function
    exists anywhere'). Surfaces disagreement — never auto-corrects a count."""

    supplier_id: str
    survey_id: str | None = None
    torpedo_count: int
    supplier_reported_count: int
    discrepancy: int  # torpedo_count - supplier_reported_count, stored so a read never re-derives it differently
    status: str = "recorded"  # recorded | disagreement_flagged | acknowledged
