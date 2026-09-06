"""
SurveyService / AllocationService / CallbackService / SupplierReconciliationService —
the panel domain's orchestrators. Every write terminates here, through
`CanonicalRepository`/`RewardLedgerService`; no `db["..."]` appears anywhere in this
package outside `routers.py`'s provider functions (same architectural gate as every
prior slice).

**`AllocationService.allocate()`'s atomicity needs no raw-Motor exception**, unlike
`app.outreach.budget.BudgetService`/`app.finance.sequence.SequenceService`.
`CanonicalRepository.update()`'s own version-guard is sufficient: decrementing
`quota_remaining` is attempted with the version last read, and a `VersionConflict`
(another caller won the race) is retried against a fresh read, bounded by
`MAX_ALLOCATION_RETRIES`. A racer who loses simply sees the *already-decremented*
document on retry and correctly determines whether quota remains — this is
invariant I-3 ("no read-then-write gap on any counter that gates money, inventory,
or outbound volume"), and it directly replaces v1's actual production behavior
(register §2.2: "no atomic counter for CINT — only a soft pacing check reading a
cache up to 5-10 minutes stale") and its dead-but-correct twin that was never wired
(§2.0: "`SurveyAllocationService` is atomic and race-safe... but `traffic.py` never
calls any method on it").

**A duplicate `respondent_ref`+`survey_id` allocation is rejected, not replayed** —
deliberately different from Slice 7/8's idempotent-replay-returns-the-same-record
pattern. The endpoint catalogue is explicit here: "a duplicate `respondent_ref`
within the dedup window is rejected, not re-allocated" — this is a fraud guard
(the same respondent should not win a second slot by resubmitting), not a
retry-safety mechanism.

**`CallbackService` never claws back points itself, even for a `"reversed"` signal**
— register §5.7: "clawback always requires approval, no exception," and
`RBACService.can_approve()` refuses any non-`"user"` principal unconditionally
(I-4's "no agent may modify money," applied to a webhook the same way it's applied
to AI). A reversal callback records the `SurveyResponse` and raises a
`reward_clawback_needed` Activity naming the exact amount to claw back — a human
still has to call the already-built, approval-gated `POST /rewards/clawback`
(Slice 8) to actually do it. The external signal proposes; a human decides — the
same I-4 shape as AI proposing enrichment fields, applied to a supplier's webhook.
"""

from __future__ import annotations

from app.finance.rewards_ledger import RewardLedgerService
from app.models.activity import Activity
from app.models.base import CanonicalRepository, VersionConflict
from app.models.money import Money
from app.panel.callback_security import verify_hmac_signature
from app.panel.models import Allocation, SURVEY_PROVIDERS, Supplier, Survey, SurveyResponse, SupplierReconciliationRecord, TrafficSource
from app.panel.providers import SurveyProvider, SurveyProviderUnavailable

MAX_ALLOCATION_RETRIES = 5

TERMINAL_NO_CREDIT_STATUSES = ("terminated", "overquota", "quality_term")

# A survey receives panel traffic only when its conversion rate clears this hard
# eligibility boundary — deliberately deterministic, not an AI decision. Below/at
# threshold, no ranking, no allocation, full stop; above it, which survey and how
# much traffic still needs the AI-ranking layer (checklist: NOT_STARTED, needs the
# AI gateway) but the eligibility gate itself doesn't wait on that.
CONVERSION_ELIGIBILITY_THRESHOLD = 0.20


class SurveyError(Exception):
    """Invalid request, no eligible survey, or a state a survey/allocation isn't in.
    Same discipline as FinanceError/OutreachError/LeadGenError."""


class SurveyService:
    def __init__(self, surveys: CanonicalRepository[Survey], activities: CanonicalRepository[Activity]):
        self._surveys = surveys
        self._activities = activities

    async def create_survey(
        self, *, org_id: str, actor: str, provider: str, external_id: str, quota_remaining: int, cpi: Money, conversion_rate: float,
        category: str | None = None, length_minutes: int | None = None, incentive: Money | None = None,
        opportunity_id: str | None = None, client_rate: Money | None = None,
    ) -> Survey:
        if provider not in SURVEY_PROVIDERS:
            raise SurveyError(f"unsupported provider {provider!r} — only {SURVEY_PROVIDERS} exist in v2, CPX was removed entirely")
        return await self._surveys.insert(
            Survey(
                org_id=org_id, created_by=actor, updated_by=actor, provider=provider, external_id=external_id,
                quota_remaining=quota_remaining, cpi=cpi, conversion_rate=conversion_rate,
                category=category, length_minutes=length_minutes, incentive=incentive,
                opportunity_id=opportunity_id, client_rate=client_rate,
            )
        )

    async def set_commercial_linkage(self, *, actor: str, survey_id: str, opportunity_id: str | None = None, client_rate: Money | None = None) -> Survey:
        """A survey's commercial linkage can be configured after creation too —
        e.g. an existing study getting its client/rate assigned once the
        opportunity closes. Only touches these two fields, same "one writer per
        concern" discipline as `set_eligibility()`/`refresh_projection()`."""
        survey = await self._get_or_raise(survey_id)
        changes: dict = {}
        if opportunity_id is not None:
            changes["opportunity_id"] = opportunity_id
        if client_rate is not None:
            changes["client_rate"] = client_rate
        if not changes:
            return survey
        return await self._surveys.update(survey.id, survey.version, changes, updated_by=actor)

    async def set_eligibility(self, *, actor: str, survey_id: str, is_active_in_pool: bool, activated_at) -> Survey:
        """The one writer for the AUTHORITATIVE eligibility fields — Torpedo's own
        decision, never re-fetched from the provider (data_lineage_map.md §4.2)."""
        survey = await self._get_or_raise(survey_id)
        return await self._surveys.update(survey.id, survey.version, {"eligibility_is_active_in_pool": is_active_in_pool, "eligibility_activated_at": activated_at}, updated_by=actor)

    async def refresh_projection(self, *, actor: str, survey_id: str, provider: SurveyProvider) -> Survey:
        """The one writer for the PROJECTION fields — re-fetched from the provider,
        never computed locally. May raise SurveyProviderUnavailable."""
        survey = await self._get_or_raise(survey_id)
        snapshot = await provider.refresh(survey=survey)
        return await self._surveys.update(
            survey.id, survey.version,
            {"quota_remaining": snapshot.quota_remaining, "cpi": Money(amount_minor=snapshot.cpi_minor, currency=survey.cpi.currency), "conversion_rate": snapshot.conversion_rate},
            updated_by=actor,
        )

    async def list_eligible(self, *, org_id: str) -> list[Survey]:
        """The deterministic gate, run *before* any AI ranking ever sees a
        candidate list — a survey at or below `CONVERSION_ELIGIBILITY_THRESHOLD`,
        not accepting pool traffic, or out of quota is never offered to the AI as
        a choice at all (Slice 15: 'AI must not be allowed to bypass ... the >20%
        conversion gate' — the gate is enforced by never presenting the option,
        not by trusting the AI to decline it)."""
        surveys = await self._surveys.find_all({"org_id": org_id, "eligibility_is_active_in_pool": True})
        return [s for s in surveys if s.quota_remaining > 0 and s.conversion_rate > CONVERSION_ELIGIBILITY_THRESHOLD]

    async def _get_or_raise(self, survey_id: str) -> Survey:
        survey = await self._surveys.get(survey_id)
        if survey is None:
            raise SurveyError(f"survey {survey_id} does not exist")
        return survey


class AllocationService:
    def __init__(self, surveys: CanonicalRepository[Survey], allocations: CanonicalRepository[Allocation], activities: CanonicalRepository[Activity]):
        self._surveys = surveys
        self._allocations = allocations
        self._activities = activities

    async def allocate(
        self, *, org_id: str, actor: str, candidate_survey_ids: list[str], person_id: str, vendor_id: str, country_code: str,
        respondent_ref: str, provider: SurveyProvider, ai_decision_subject_id: str | None = None,
    ) -> Allocation:
        existing = await self._allocations.find_one({"respondent_ref": respondent_ref})
        if existing:
            raise SurveyError(f"respondent_ref {respondent_ref!r} was already allocated — duplicate allocations are rejected, not replayed")

        last_error: Exception | None = None
        for survey_id in candidate_survey_ids:
            try:
                survey = await self._reserve_quota(survey_id=survey_id, actor=actor)
            except SurveyError as exc:
                last_error = exc
                continue  # this candidate had no room or wasn't eligible — try the next

            try:
                redirect_url = await provider.build_redirect_url(survey=survey, respondent_ref=respondent_ref)
            except SurveyProviderUnavailable as exc:
                # The endpoint catalogue's exact rule: a provider timeout falls back
                # to the next-best eligible survey, never a hardcoded default. Give
                # back the slot we just reserved before trying the next candidate.
                await self._release_quota(survey_id=survey.id, actor=actor)
                last_error = exc
                continue

            allocation = await self._allocations.insert(
                Allocation(
                    org_id=org_id, created_by=actor, updated_by=actor,
                    survey_id=survey.id, person_id=person_id, vendor_id=vendor_id, country_code=country_code,
                    respondent_ref=respondent_ref, redirect_url=redirect_url, ai_decision_subject_id=ai_decision_subject_id,
                )
            )
            await self._activities.insert(
                Activity(org_id=org_id, created_by=actor, updated_by=actor, type="respondent_allocated", subject_type="allocation", subject_id=allocation.id, actor_type="system", actor_id=actor, payload={"survey_id": survey.id})
            )
            return allocation

        raise SurveyError(f"no eligible survey among candidates (last error: {last_error})")

    async def _reserve_quota(self, *, survey_id: str, actor: str) -> Survey:
        for _ in range(MAX_ALLOCATION_RETRIES):
            survey = await self._surveys.get(survey_id)
            if survey is None:
                raise SurveyError(f"survey {survey_id} does not exist")
            if not survey.eligibility_is_active_in_pool or survey.quota_remaining <= 0:
                raise SurveyError(f"survey {survey_id} has no eligible quota")
            if survey.conversion_rate <= CONVERSION_ELIGIBILITY_THRESHOLD:
                raise SurveyError(f"survey {survey_id} conversion rate {survey.conversion_rate} is at or below the {CONVERSION_ELIGIBILITY_THRESHOLD} eligibility threshold")
            try:
                return await self._surveys.update(survey.id, survey.version, {"quota_remaining": survey.quota_remaining - 1}, updated_by=actor)
            except VersionConflict:
                continue  # another allocation won the race — re-read and retry against the fresh count
        raise SurveyError(f"survey {survey_id} quota exhausted (race lost after {MAX_ALLOCATION_RETRIES} retries)")

    async def _release_quota(self, *, survey_id: str, actor: str) -> None:
        for _ in range(MAX_ALLOCATION_RETRIES):
            survey = await self._surveys.get(survey_id)
            if survey is None:
                return
            try:
                await self._surveys.update(survey.id, survey.version, {"quota_remaining": survey.quota_remaining + 1}, updated_by=actor)
                return
            except VersionConflict:
                continue


class CallbackService:
    def __init__(
        self,
        responses: CanonicalRepository[SurveyResponse],
        allocations: CanonicalRepository[Allocation],
        activities: CanonicalRepository[Activity],
        reward_ledger: RewardLedgerService,
        *,
        signing_secret: str | None,
    ):
        self._responses = responses
        self._allocations = allocations
        self._activities = activities
        self._reward_ledger = reward_ledger
        self._signing_secret = signing_secret

    async def handle_callback(
        self,
        *,
        org_id: str,
        raw_payload: bytes,
        signature_hex: str,
        allocation_id: str,
        provider: str,
        external_event_id: str,
        final_status: str,
        payout: Money | None,
        reverses_external_event_id: str | None = None,
    ) -> SurveyResponse:
        # D-08/D-23, unconditionally, before anything else in this method runs.
        verify_hmac_signature(payload=raw_payload, secret=self._signing_secret, signature_hex=signature_hex)

        existing = await self._responses.find_one({"provider": provider, "external_event_id": external_event_id})
        if existing:
            return existing  # idempotent replay — webhook redelivery, not a duplicate signal

        allocation = await self._allocations.get(allocation_id)
        if allocation is None:
            raise SurveyError(f"allocation {allocation_id} does not exist")

        credited_amount: Money | None = None
        reverses_response_id: str | None = None

        if final_status == "complete":
            if payout is None:
                raise SurveyError("a 'complete' callback must carry a payout amount")
            await self._reward_ledger.credit(
                org_id=org_id, actor="system", panelist_person_id=allocation.person_id, amount=payout,
                reference_type="survey_completion", reference_id=allocation.id,
            )
            credited_amount = payout
        elif final_status == "reversed":
            if reverses_external_event_id is None:
                raise SurveyError("a 'reversed' callback must name the external_event_id it reverses")
            original = await self._responses.find_one({"provider": provider, "external_event_id": reverses_external_event_id})
            if original is None or original.credited_amount is None:
                raise SurveyError("cannot reverse a response that was never credited")
            reverses_response_id = original.id
            # D-12's fix stops here, deliberately — see module docstring. The signal
            # is recorded and flagged; a human still has to call the approval-gated
            # POST /rewards/clawback to actually move the ledger.
            await self._activities.insert(
                Activity(
                    org_id=org_id, created_by="system", updated_by="system", type="reward_clawback_needed",
                    subject_type="survey_response", subject_id=original.id, actor_type="system", actor_id="system",
                    payload={"panelist_person_id": allocation.person_id, "amount_minor": original.credited_amount.amount_minor, "currency": original.credited_amount.currency},
                )
            )
        elif final_status not in TERMINAL_NO_CREDIT_STATUSES:
            raise SurveyError(f"unknown final_status {final_status!r}")

        response = await self._responses.insert(
            SurveyResponse(
                org_id=org_id, created_by="system", updated_by="system",
                allocation_id=allocation.id, survey_id=allocation.survey_id, person_id=allocation.person_id,
                respondent_ref=allocation.respondent_ref, provider=provider, external_event_id=external_event_id,
                final_status=final_status, payout=payout, credited_amount=credited_amount, reverses_response_id=reverses_response_id,
            )
        )
        await self._allocations.update(allocation.id, allocation.version, {"status": "resolved"}, updated_by="system")
        await self._activities.insert(
            Activity(org_id=org_id, created_by="system", updated_by="system", type="survey_response_recorded", subject_type="survey_response", subject_id=response.id, actor_type="system", actor_id="system", payload={"final_status": final_status})
        )
        return response


class SupplierService:
    def __init__(self, suppliers: CanonicalRepository[Supplier]):
        self._suppliers = suppliers

    async def create_supplier(self, *, org_id: str, actor: str, name: str, provider: str) -> Supplier:
        if provider not in SURVEY_PROVIDERS:
            raise SurveyError(f"unsupported provider {provider!r} — only {SURVEY_PROVIDERS} exist in v2, CPX was removed entirely")
        return await self._suppliers.insert(Supplier(org_id=org_id, created_by=actor, updated_by=actor, name=name, provider=provider))


class TrafficSourceService:
    def __init__(self, traffic_sources: CanonicalRepository[TrafficSource]):
        self._traffic_sources = traffic_sources

    async def create_traffic_source(self, *, org_id: str, actor: str, vendor_id: str, country_code: str, campaign_ref: str) -> TrafficSource:
        return await self._traffic_sources.insert(TrafficSource(org_id=org_id, created_by=actor, updated_by=actor, vendor_id=vendor_id, country_code=country_code, campaign_ref=campaign_ref))


class SupplierReconciliationService:
    def __init__(self, records: CanonicalRepository[SupplierReconciliationRecord], responses: CanonicalRepository[SurveyResponse]):
        self._records = records
        self._responses = responses

    async def reconcile(self, *, org_id: str, actor: str, supplier_id: str, survey_id: str | None, supplier_reported_count: int) -> SupplierReconciliationRecord:
        """Surfaces disagreement — never silently corrects Torpedo's own count or
        the supplier's. I-5: 'explicit discrepancy policy, surfacing disagreement,
        never silently correcting it.'"""
        query: dict = {"final_status": "complete"}
        if survey_id:
            query["survey_id"] = survey_id
        torpedo_responses = await self._responses.find_all(query)
        torpedo_count = len(torpedo_responses)
        discrepancy = torpedo_count - supplier_reported_count

        return await self._records.insert(
            SupplierReconciliationRecord(
                org_id=org_id, created_by=actor, updated_by=actor,
                supplier_id=supplier_id, survey_id=survey_id, torpedo_count=torpedo_count,
                supplier_reported_count=supplier_reported_count, discrepancy=discrepancy,
                status="disagreement_flagged" if discrepancy != 0 else "recorded",
            )
        )
