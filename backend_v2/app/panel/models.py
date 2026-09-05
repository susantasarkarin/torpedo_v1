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
