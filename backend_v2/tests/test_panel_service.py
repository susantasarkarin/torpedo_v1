"""
Slice 9 — Panel/Survey. P0/P1 regression coverage named after the register findings
each test proves cannot recur: D-08 (no signature verification on the outcome
callback), D-23 (signature validation failing open), the register §2.0/§2.2 dead
atomic-allocation-engine findings, §2.8 (no supplier reconciliation), and D-12's
clawback boundary (built in Slice 8, wired to a real caller here — but never
self-executed by a webhook, per register §5.7's "no exception").
"""

import hashlib
import hmac as hmac_module
import json
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.finance.rewards_ledger import RewardLedgerEntry, RewardLedgerService
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.panel.callback_security import SignatureConfigError, SignatureInvalid
from app.panel.inactivity import StudyInactivityService
from app.panel.models import SURVEY_PROVIDERS, Allocation, Supplier, Survey, SurveyResponse, SupplierReconciliationRecord, TrafficSource
from app.panel.providers import SurveyProjection, SurveyProviderUnavailable
from app.panel.service import AllocationService, CallbackService, SupplierReconciliationService, SupplierService, SurveyError, SurveyService

ORG = "org-A"
CURRENCY = "INR"
SECRET = "test-signing-secret"


def _sign(payload: bytes, secret: str = SECRET) -> str:
    return hmac_module.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class RecordingProvider:
    def __init__(self, fail_for_external_ids: set[str] | None = None):
        self.calls: list[str] = []
        self._fail_for = fail_for_external_ids or set()

    async def build_redirect_url(self, *, survey, respondent_ref):
        self.calls.append(survey.external_id)
        if survey.external_id in self._fail_for:
            raise SurveyProviderUnavailable("simulated timeout")
        return f"https://provider.example/{survey.external_id}/{respondent_ref}"

    async def refresh(self, *, survey):
        return SurveyProjection(quota_remaining=survey.quota_remaining, cpi_minor=survey.cpi.amount_minor, conversion_rate=survey.conversion_rate)


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def activities(db) -> CanonicalRepository[Activity]:
    return CanonicalRepository(db["activities"], Activity)


@pytest.fixture
def survey_service(db, activities) -> SurveyService:
    return SurveyService(CanonicalRepository(db["surveys"], Survey), activities)


@pytest.fixture
def allocation_service(db, activities) -> AllocationService:
    return AllocationService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), activities)


@pytest.fixture
def reward_ledger(db) -> RewardLedgerService:
    return RewardLedgerService(CanonicalRepository(db["reward_ledger_entries"], RewardLedgerEntry))


@pytest.fixture
def callback_service(db, activities, reward_ledger) -> CallbackService:
    return CallbackService(
        CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["allocations"], Allocation),
        activities, reward_ledger, signing_secret=SECRET,
    )


@pytest.fixture
def supplier_service(db) -> SupplierService:
    return SupplierService(CanonicalRepository(db["suppliers"], Supplier))


@pytest.fixture
def reconciliation_service(db) -> SupplierReconciliationService:
    return SupplierReconciliationService(CanonicalRepository(db["supplier_reconciliation_records"], SupplierReconciliationRecord), CanonicalRepository(db["survey_responses"], SurveyResponse))


@pytest.fixture
def inactivity_service(db, activities) -> StudyInactivityService:
    return StudyInactivityService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), activities)


async def _eligible_survey(survey_service: SurveyService, *, quota=1, external_id="s1", conversion_rate=0.3) -> Survey:
    survey = await survey_service.create_survey(org_id=ORG, actor="system", provider="cint", external_id=external_id, quota_remaining=quota, cpi=Money(amount_minor=500, currency=CURRENCY), conversion_rate=conversion_rate)
    return await survey_service.set_eligibility(actor="system", survey_id=survey.id, is_active_in_pool=True, activated_at=None)


# --------------------------------------------------------------------------- CPX removal (v2_locked_principles.md §1.10)


def test_cpx_is_not_a_member_of_the_closed_provider_set():
    assert "cpx" not in SURVEY_PROVIDERS
    assert SURVEY_PROVIDERS == ("cint",)


@pytest.mark.asyncio
async def test_creating_a_survey_with_cpx_provider_is_rejected(survey_service: SurveyService):
    with pytest.raises(SurveyError):
        await survey_service.create_survey(org_id=ORG, actor="system", provider="cpx", external_id="x", quota_remaining=10, cpi=Money(amount_minor=100, currency=CURRENCY), conversion_rate=0.1)


@pytest.mark.asyncio
async def test_creating_a_supplier_with_cpx_provider_is_rejected(supplier_service: SupplierService):
    with pytest.raises(SurveyError):
        await supplier_service.create_supplier(org_id=ORG, actor="system", name="Old CPX Vendor", provider="cpx")


# --------------------------------------------------------------------------- atomic allocation (register §2.0/§2.2)


@pytest.mark.asyncio
async def test_allocation_atomically_decrements_quota_and_never_oversells(survey_service: SurveyService, allocation_service: AllocationService):
    survey = await _eligible_survey(survey_service, quota=1)
    provider = RecordingProvider()

    first = await allocation_service.allocate(org_id=ORG, actor="system", candidate_survey_ids=[survey.id], person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=provider)
    assert first.survey_id == survey.id

    with pytest.raises(SurveyError):
        await allocation_service.allocate(org_id=ORG, actor="system", candidate_survey_ids=[survey.id], person_id="p2", vendor_id="v1", country_code="IN", respondent_ref="r2", provider=provider)

    updated_survey = await survey_service._surveys.get(survey.id)
    assert updated_survey.quota_remaining == 0


@pytest.mark.asyncio
async def test_ineligible_survey_is_never_allocated_even_with_quota(survey_service: SurveyService, allocation_service: AllocationService):
    survey = await survey_service.create_survey(org_id=ORG, actor="system", provider="cint", external_id="s1", quota_remaining=5, cpi=Money(amount_minor=500, currency=CURRENCY), conversion_rate=0.3)
    # deliberately never call set_eligibility — is_active_in_pool defaults False
    provider = RecordingProvider()

    with pytest.raises(SurveyError):
        await allocation_service.allocate(org_id=ORG, actor="system", candidate_survey_ids=[survey.id], person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=provider)
    assert provider.calls == []


@pytest.mark.asyncio
async def test_survey_at_or_below_conversion_threshold_never_gets_traffic(survey_service: SurveyService, allocation_service: AllocationService):
    """The hard eligibility boundary: conversion <= 20% -> no panel traffic at all,
    regardless of quota/eligibility otherwise being fine. Deterministic, not an AI
    ranking decision."""
    for rate, ref in [(0.20, "r-exactly-20"), (0.19, "r-below-20")]:
        survey = await _eligible_survey(survey_service, quota=5, external_id=f"low-{ref}", conversion_rate=rate)
        provider = RecordingProvider()
        with pytest.raises(SurveyError):
            await allocation_service.allocate(org_id=ORG, actor="system", candidate_survey_ids=[survey.id], person_id="p1", vendor_id="v1", country_code="IN", respondent_ref=ref, provider=provider)
        assert provider.calls == []


@pytest.mark.asyncio
async def test_survey_above_conversion_threshold_is_eligible(survey_service: SurveyService, allocation_service: AllocationService):
    survey = await _eligible_survey(survey_service, quota=5, conversion_rate=0.21)
    provider = RecordingProvider()
    allocation = await allocation_service.allocate(org_id=ORG, actor="system", candidate_survey_ids=[survey.id], person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=provider)
    assert allocation.survey_id == survey.id


@pytest.mark.asyncio
async def test_duplicate_respondent_ref_is_rejected_not_replayed(survey_service: SurveyService, allocation_service: AllocationService):
    survey = await _eligible_survey(survey_service, quota=5)
    provider = RecordingProvider()

    await allocation_service.allocate(org_id=ORG, actor="system", candidate_survey_ids=[survey.id], person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="same-ref", provider=provider)
    with pytest.raises(SurveyError):
        await allocation_service.allocate(org_id=ORG, actor="system", candidate_survey_ids=[survey.id], person_id="p2", vendor_id="v1", country_code="IN", respondent_ref="same-ref", provider=provider)

    updated_survey = await survey_service._surveys.get(survey.id)
    assert updated_survey.quota_remaining == 4  # only the first, successful allocation consumed a slot


@pytest.mark.asyncio
async def test_provider_failure_falls_back_to_next_candidate_and_releases_the_reserved_slot(survey_service: SurveyService, allocation_service: AllocationService):
    """endpoint_catalogue.md: 'a provider timeout falls back to the next-best
    eligible survey, never a hardcoded default survey.'"""
    failing_survey = await _eligible_survey(survey_service, quota=3, external_id="failing")
    good_survey = await _eligible_survey(survey_service, quota=3, external_id="good")
    provider = RecordingProvider(fail_for_external_ids={"failing"})

    allocation = await allocation_service.allocate(
        org_id=ORG, actor="system", candidate_survey_ids=[failing_survey.id, good_survey.id],
        person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=provider,
    )

    assert allocation.survey_id == good_survey.id
    assert provider.calls == ["failing", "good"]

    updated_failing = await survey_service._surveys.get(failing_survey.id)
    updated_good = await survey_service._surveys.get(good_survey.id)
    assert updated_failing.quota_remaining == 3  # released back — never a hardcoded default, never a lost slot
    assert updated_good.quota_remaining == 2


@pytest.mark.asyncio
async def test_refresh_projection_never_touches_eligibility_fields(survey_service: SurveyService):
    survey = await _eligible_survey(survey_service, quota=5)
    provider = RecordingProvider()
    updated = await survey_service.refresh_projection(actor="system", survey_id=survey.id, provider=provider)
    assert updated.eligibility_is_active_in_pool is True  # untouched by the projection writer


@pytest.mark.asyncio
async def test_set_eligibility_never_touches_projection_fields(survey_service: SurveyService):
    survey = await survey_service.create_survey(org_id=ORG, actor="system", provider="cint", external_id="s1", quota_remaining=7, cpi=Money(amount_minor=500, currency=CURRENCY), conversion_rate=0.3)
    updated = await survey_service.set_eligibility(actor="system", survey_id=survey.id, is_active_in_pool=True, activated_at=None)
    assert updated.quota_remaining == 7  # untouched by the eligibility writer


# --------------------------------------------------------------------------- callback signature (D-08/D-23)


@pytest.mark.asyncio
async def test_callback_with_no_configured_secret_fails_closed(db, activities, reward_ledger):
    """D-23's exact failure mode (fail-open on a missing secret) refused here."""
    svc = CallbackService(CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["allocations"], Allocation), activities, reward_ledger, signing_secret=None)
    body = json.dumps({"org_id": ORG, "allocation_id": "a1", "provider": "cint", "external_event_id": "e1", "final_status": "complete", "payout": {"amount_minor": 100, "currency": CURRENCY}}).encode()

    with pytest.raises(SignatureConfigError):
        await svc.handle_callback(org_id=ORG, raw_payload=body, signature_hex="whatever", allocation_id="a1", provider="cint", external_event_id="e1", final_status="complete", payout=Money(amount_minor=100, currency=CURRENCY))


@pytest.mark.asyncio
async def test_callback_with_wrong_signature_is_rejected_and_nothing_recorded(callback_service: CallbackService, db):
    body = b'{"anything": "here"}'
    with pytest.raises(SignatureInvalid):
        await callback_service.handle_callback(org_id=ORG, raw_payload=body, signature_hex="0" * 64, allocation_id="a1", provider="cint", external_event_id="e1", final_status="complete", payout=Money(amount_minor=100, currency=CURRENCY))

    responses = await CanonicalRepository(db["survey_responses"], SurveyResponse).find_all({})
    assert responses == []


# --------------------------------------------------------------------------- callback outcomes + reward integration


async def _allocated(survey_service, allocation_service, provider, *, quota=5, respondent_ref="r1", person_id="p1") -> tuple[Survey, Allocation]:
    survey = await _eligible_survey(survey_service, quota=quota)
    allocation = await allocation_service.allocate(org_id=ORG, actor="system", candidate_survey_ids=[survey.id], person_id=person_id, vendor_id="v1", country_code="IN", respondent_ref=respondent_ref, provider=provider)
    return survey, allocation


@pytest.mark.asyncio
async def test_complete_callback_credits_the_reward_ledger(survey_service, allocation_service, callback_service, reward_ledger):
    _, allocation = await _allocated(survey_service, allocation_service, RecordingProvider())
    body = b'{"complete": true}'
    signature = _sign(body)

    response = await callback_service.handle_callback(org_id=ORG, raw_payload=body, signature_hex=signature, allocation_id=allocation.id, provider="cint", external_event_id="evt-1", final_status="complete", payout=Money(amount_minor=250, currency=CURRENCY))

    assert response.final_status == "complete"
    assert response.credited_amount.amount_minor == 250
    balance = await reward_ledger.get_balance("p1", currency=CURRENCY)
    assert balance.amount_minor == 250


@pytest.mark.asyncio
async def test_callback_idempotent_replay_never_double_credits(survey_service, allocation_service, callback_service, reward_ledger):
    _, allocation = await _allocated(survey_service, allocation_service, RecordingProvider())
    body = b'{"complete": true}'
    signature = _sign(body)

    first = await callback_service.handle_callback(org_id=ORG, raw_payload=body, signature_hex=signature, allocation_id=allocation.id, provider="cint", external_event_id="evt-1", final_status="complete", payout=Money(amount_minor=250, currency=CURRENCY))
    second = await callback_service.handle_callback(org_id=ORG, raw_payload=body, signature_hex=signature, allocation_id=allocation.id, provider="cint", external_event_id="evt-1", final_status="complete", payout=Money(amount_minor=250, currency=CURRENCY))

    assert first.id == second.id
    balance = await reward_ledger.get_balance("p1", currency=CURRENCY)
    assert balance.amount_minor == 250  # not 500


@pytest.mark.asyncio
async def test_terminal_non_complete_statuses_never_credit(survey_service, allocation_service, callback_service, reward_ledger):
    for status_value, event_id, respondent_ref in [("terminated", "evt-t", "r-t"), ("overquota", "evt-o", "r-o"), ("quality_term", "evt-q", "r-q")]:
        _, allocation = await _allocated(survey_service, allocation_service, RecordingProvider(), respondent_ref=respondent_ref)
        body = str(status_value).encode()
        response = await callback_service.handle_callback(org_id=ORG, raw_payload=body, signature_hex=_sign(body), allocation_id=allocation.id, provider="cint", external_event_id=event_id, final_status=status_value, payout=None)
        assert response.credited_amount is None

    balance = await reward_ledger.get_balance("p1", currency=CURRENCY)
    assert balance.amount_minor == 0


@pytest.mark.asyncio
async def test_reversed_callback_never_directly_claws_back_only_flags_for_human_approval(survey_service, allocation_service, callback_service, reward_ledger, activities):
    """The direct D-12-boundary regression: a reversal signal must not itself move
    the ledger — register §5.7 gives clawback no exception, and a webhook can never
    be the 'user' can_approve() requires."""
    _, allocation = await _allocated(survey_service, allocation_service, RecordingProvider())
    complete_body = b"complete-payload"
    await callback_service.handle_callback(org_id=ORG, raw_payload=complete_body, signature_hex=_sign(complete_body), allocation_id=allocation.id, provider="cint", external_event_id="evt-1", final_status="complete", payout=Money(amount_minor=250, currency=CURRENCY))

    reversal_body = b"reversal-payload"
    reversal_response = await callback_service.handle_callback(
        org_id=ORG, raw_payload=reversal_body, signature_hex=_sign(reversal_body), allocation_id=allocation.id, provider="cint",
        external_event_id="evt-1-reversal", final_status="reversed", payout=None, reverses_external_event_id="evt-1",
    )

    assert reversal_response.final_status == "reversed"
    balance = await reward_ledger.get_balance("p1", currency=CURRENCY)
    assert balance.amount_minor == 250  # UNCHANGED — no automatic clawback

    flags = await activities.find_all({"type": "reward_clawback_needed"})
    assert len(flags) == 1
    assert flags[0].payload["amount_minor"] == 250


@pytest.mark.asyncio
async def test_reversing_a_never_credited_event_is_rejected(survey_service, allocation_service, callback_service):
    _, allocation = await _allocated(survey_service, allocation_service, RecordingProvider())
    body = b"reversal-of-nothing"
    with pytest.raises(SurveyError):
        await callback_service.handle_callback(org_id=ORG, raw_payload=body, signature_hex=_sign(body), allocation_id=allocation.id, provider="cint", external_event_id="evt-x", final_status="reversed", payout=None, reverses_external_event_id="never-happened")


# --------------------------------------------------------------------------- supplier reconciliation (register §2.8, I-5)


@pytest.mark.asyncio
async def test_reconciliation_flags_disagreement_without_correcting_either_count(survey_service, allocation_service, callback_service, reconciliation_service, db):
    for i in range(2):
        _, allocation = await _allocated(survey_service, allocation_service, RecordingProvider(), respondent_ref=f"r{i}")
        body = f"payload-{i}".encode()
        await callback_service.handle_callback(org_id=ORG, raw_payload=body, signature_hex=_sign(body), allocation_id=allocation.id, provider="cint", external_event_id=f"evt-{i}", final_status="complete", payout=Money(amount_minor=100, currency=CURRENCY))

    record = await reconciliation_service.reconcile(org_id=ORG, actor="system", supplier_id="sup-1", survey_id=None, supplier_reported_count=5)

    assert record.torpedo_count == 2
    assert record.supplier_reported_count == 5
    assert record.discrepancy == -3
    assert record.status == "disagreement_flagged"

    responses = await CanonicalRepository(db["survey_responses"], SurveyResponse).find_all({})
    assert len(responses) == 2  # untouched — reconciliation never corrects the underlying records


@pytest.mark.asyncio
async def test_reconciliation_matching_counts_is_not_flagged(reconciliation_service):
    record = await reconciliation_service.reconcile(org_id=ORG, actor="system", supplier_id="sup-1", survey_id=None, supplier_reported_count=0)
    assert record.discrepancy == 0
    assert record.status == "recorded"


# --------------------------------------------------------------------------- study inactivity detection (Phase 11 trigger)


@pytest.mark.asyncio
async def test_survey_never_allocated_is_flagged_inactive(survey_service, inactivity_service, activities):
    survey = await _eligible_survey(survey_service, quota=5)
    now = datetime.now(timezone.utc)

    flagged = await inactivity_service.detect_and_flag(org_id=ORG, as_of=now)
    assert [s.id for s in flagged] == [survey.id]

    flags = await activities.find_all({"type": "study_inactive_detected", "subject_id": survey.id})
    assert len(flags) == 1


@pytest.mark.asyncio
async def test_survey_with_recent_allocation_is_not_flagged(survey_service, allocation_service, inactivity_service):
    survey, _ = await _allocated(survey_service, allocation_service, RecordingProvider())
    now = datetime.now(timezone.utc)

    flagged = await inactivity_service.detect_and_flag(org_id=ORG, as_of=now)
    assert flagged == []


@pytest.mark.asyncio
async def test_survey_with_only_stale_allocation_beyond_window_is_flagged(survey_service, db):
    survey = await _eligible_survey(survey_service, quota=5)
    stale_allocation = Allocation(
        org_id=ORG, created_by="system", updated_by="system", survey_id=survey.id, person_id="p1", vendor_id="v1",
        country_code="IN", respondent_ref="old-ref", redirect_url="https://x", created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    await CanonicalRepository(db["allocations"], Allocation).insert(stale_allocation)

    inactivity_service = StudyInactivityService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), CanonicalRepository(db["activities"], Activity))
    flagged = await inactivity_service.detect_and_flag(org_id=ORG, as_of=datetime.now(timezone.utc))
    assert [s.id for s in flagged] == [survey.id]


@pytest.mark.asyncio
async def test_repeated_scans_within_the_same_window_do_not_spam_duplicate_flags(survey_service, inactivity_service, activities):
    await _eligible_survey(survey_service, quota=5)
    now = datetime.now(timezone.utc)

    await inactivity_service.detect_and_flag(org_id=ORG, as_of=now)
    await inactivity_service.detect_and_flag(org_id=ORG, as_of=now + timedelta(hours=1))

    flags = await activities.find_all({"type": "study_inactive_detected"})
    assert len(flags) == 1


@pytest.mark.asyncio
async def test_ineligible_survey_is_never_flagged(survey_service, inactivity_service, activities):
    await survey_service.create_survey(org_id=ORG, actor="system", provider="cint", external_id="s1", quota_remaining=5, cpi=Money(amount_minor=500, currency=CURRENCY), conversion_rate=0.3)
    # deliberately never call set_eligibility

    flagged = await inactivity_service.detect_and_flag(org_id=ORG, as_of=datetime.now(timezone.utc))
    assert flagged == []
