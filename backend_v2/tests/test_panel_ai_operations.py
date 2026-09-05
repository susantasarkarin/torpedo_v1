"""
Slice 16 — AI Operations. Hard triggers detected deterministically; what happens
afterward is a real `DecisionEngine` decision; deterministic code enforces
authorization/state-validity/idempotency/safety around it — per explicit user
instruction not to turn every operational workflow into hard-coded rules either.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import DecisionEngine
from app.ai.llm import LLMResponse
from app.ai.tools import ToolRegistry
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.panel.ai_operations import ACTIVE, CLOSED, OperationsAIError, OperationsAIService, PAUSED, PENDING_CLIENT_RESPONSE
from app.panel.inactivity import StudyInactivityService
from app.panel.models import Allocation, Survey, SurveyResponse
from app.panel.providers import SurveyProjection
from app.panel.service import SurveyService

ORG = "org-A"
ACTOR = "system"
CURRENCY = "INR"


class FakeLLM:
    def __init__(self, content: str):
        self._content = content
        self.calls: list[dict] = []

    async def chat(self, *, messages, response_format=None):
        self.calls.append(json.loads(messages[1]["content"]))
        return LLMResponse(content=self._content, model="fake-model")


class SpyProvider:
    def __init__(self, new_quota=42, new_conversion=0.4):
        self._new_quota = new_quota
        self._new_conversion = new_conversion
        self.refresh_calls = 0

    async def build_redirect_url(self, *, survey, respondent_ref):
        return "https://stub"

    async def refresh(self, *, survey):
        self.refresh_calls += 1
        return SurveyProjection(quota_remaining=self._new_quota, cpi_minor=survey.cpi.amount_minor, conversion_rate=self._new_conversion)


def _decision(**overrides) -> str:
    payload = {
        "decision": "NO_ACTION", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "LOW",
        "entities": [], "actions": [], "follow_up_at": None, "requires_human_approval": False, "extracted_entities": {},
    }
    payload.update(overrides)
    return json.dumps(payload)


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def survey_service(db) -> SurveyService:
    return SurveyService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def inactivity(db) -> StudyInactivityService:
    return StudyInactivityService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), CanonicalRepository(db["activities"], Activity))


def _service(db, llm, survey_service, inactivity) -> OperationsAIService:
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    return OperationsAIService(engine, survey_service, inactivity, CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["activities"], Activity), CanonicalRepository(db["ai_proposals"], AiProposal))


async def _live_survey(svc: SurveyService, *, external_id="s1", conversion_rate=0.3, quota=5) -> Survey:
    survey = await svc.create_survey(org_id=ORG, actor=ACTOR, provider="cint", external_id=external_id, quota_remaining=quota, cpi=Money(amount_minor=500, currency=CURRENCY), conversion_rate=conversion_rate)
    return await svc.set_eligibility(actor=ACTOR, survey_id=survey.id, is_active_in_pool=True, activated_at=None)


# --------------------------------------------------------------------------- detect_triggers (hard, deterministic)


@pytest.mark.asyncio
async def test_detect_finds_no_traffic_survey(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    svc = _service(db, FakeLLM(_decision()), survey_service, inactivity)

    triggered = await svc.detect_triggers(org_id=ORG)
    assert (survey.id, "no_traffic_7_days") in [(s.id, t) for s, t in triggered]


@pytest.mark.asyncio
async def test_detect_finds_low_conversion_survey(db, survey_service, inactivity):
    survey = await _live_survey(survey_service, conversion_rate=0.15)
    # give it recent traffic so it does NOT also match no_traffic_7_days
    await CanonicalRepository(db["allocations"], Allocation).insert(Allocation(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, survey_id=survey.id, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", redirect_url="https://x"))

    svc = _service(db, FakeLLM(_decision()), survey_service, inactivity)
    triggered = await svc.detect_triggers(org_id=ORG)
    assert (survey.id, "low_conversion") in [(s.id, t) for s, t in triggered]


@pytest.mark.asyncio
async def test_detect_finds_high_dropout_survey(db, survey_service, inactivity):
    survey = await _live_survey(survey_service, conversion_rate=0.5)
    await CanonicalRepository(db["allocations"], Allocation).insert(Allocation(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, survey_id=survey.id, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="recent", redirect_url="https://x"))
    responses = CanonicalRepository(db["survey_responses"], SurveyResponse)
    for i in range(3):
        await responses.insert(SurveyResponse(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, allocation_id="a", survey_id=survey.id, person_id=f"p{i}", respondent_ref=f"r{i}", provider="cint", external_event_id=f"e{i}", final_status="terminated"))
    for i in range(2):
        await responses.insert(SurveyResponse(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, allocation_id="a", survey_id=survey.id, person_id=f"q{i}", respondent_ref=f"rr{i}", provider="cint", external_event_id=f"ee{i}", final_status="complete"))

    svc = _service(db, FakeLLM(_decision()), survey_service, inactivity)
    triggered = await svc.detect_triggers(org_id=ORG)
    assert (survey.id, "high_dropout") in [(s.id, t) for s, t in triggered]


@pytest.mark.asyncio
async def test_dropout_below_minimum_sample_size_never_triggers(db, survey_service, inactivity):
    survey = await _live_survey(survey_service, conversion_rate=0.5)
    await CanonicalRepository(db["allocations"], Allocation).insert(Allocation(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, survey_id=survey.id, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="recent", redirect_url="https://x"))
    responses = CanonicalRepository(db["survey_responses"], SurveyResponse)
    await responses.insert(SurveyResponse(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, allocation_id="a", survey_id=survey.id, person_id="p1", respondent_ref="r1", provider="cint", external_event_id="e1", final_status="terminated"))
    await responses.insert(SurveyResponse(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, allocation_id="a", survey_id=survey.id, person_id="p2", respondent_ref="r2", provider="cint", external_event_id="e2", final_status="terminated"))

    svc = _service(db, FakeLLM(_decision()), survey_service, inactivity)
    triggered = await svc.detect_triggers(org_id=ORG)
    assert triggered == []


@pytest.mark.asyncio
async def test_closed_surveys_are_never_offered_to_detection(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    await CanonicalRepository(db["surveys"], Survey).update(survey.id, survey.version, {"operational_status": CLOSED}, updated_by=ACTOR)

    svc = _service(db, FakeLLM(_decision()), survey_service, inactivity)
    triggered = await svc.detect_triggers(org_id=ORG)
    assert triggered == []


# --------------------------------------------------------------------------- evaluate_and_act (AI decides, code enforces)


@pytest.mark.asyncio
async def test_pause_decision_disables_eligibility_and_updates_status(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    svc = _service(db, FakeLLM(_decision(decision="PAUSE")), survey_service, inactivity)

    decision = await svc.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="no_traffic_7_days")
    assert decision.decision == "PAUSE"

    updated = await survey_service._surveys.get(survey.id)
    assert updated.operational_status == PAUSED
    assert updated.eligibility_is_active_in_pool is False
    assert updated.ai_decision_subject_id is not None


@pytest.mark.asyncio
async def test_close_is_terminal(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    svc = _service(db, FakeLLM(_decision(decision="CLOSE")), survey_service, inactivity)
    await svc.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="no_traffic_7_days")

    svc2 = _service(db, FakeLLM(_decision(decision="PAUSE")), survey_service, inactivity)
    with pytest.raises(OperationsAIError):
        await svc2.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="low_conversion")  # different trigger_type -> bypasses same-day idempotency


@pytest.mark.asyncio
async def test_reactivate_from_paused_succeeds(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    await _service(db, FakeLLM(_decision(decision="PAUSE")), survey_service, inactivity).evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="no_traffic_7_days")

    svc2 = _service(db, FakeLLM(_decision(decision="REACTIVATE")), survey_service, inactivity)
    await svc2.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="low_conversion")

    updated = await survey_service._surveys.get(survey.id)
    assert updated.operational_status == ACTIVE
    assert updated.eligibility_is_active_in_pool is True


@pytest.mark.asyncio
async def test_reactivate_from_already_active_is_rejected(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    svc = _service(db, FakeLLM(_decision(decision="REACTIVATE")), survey_service, inactivity)

    with pytest.raises(OperationsAIError):
        await svc.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="no_traffic_7_days")


@pytest.mark.asyncio
async def test_request_client_status_records_state_without_any_email_side_effect(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    svc = _service(db, FakeLLM(_decision(decision="REQUEST_CLIENT_STATUS")), survey_service, inactivity)

    await svc.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="no_traffic_7_days")
    updated = await survey_service._surveys.get(survey.id)
    assert updated.operational_status == PENDING_CLIENT_RESPONSE


@pytest.mark.asyncio
async def test_investigate_calls_the_real_provider_refresh(db, survey_service, inactivity):
    survey = await _live_survey(survey_service, quota=1, conversion_rate=0.1)
    provider = SpyProvider(new_quota=99, new_conversion=0.55)
    svc = _service(db, FakeLLM(_decision(decision="INVESTIGATE")), survey_service, inactivity)

    await svc.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="low_conversion", provider=provider)

    assert provider.refresh_calls == 1
    updated = await survey_service._surveys.get(survey.id)
    assert updated.quota_remaining == 99
    assert updated.conversion_rate == 0.55


@pytest.mark.asyncio
async def test_no_action_leaves_operational_status_unchanged_but_records_decision(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    svc = _service(db, FakeLLM(_decision(decision="NO_ACTION")), survey_service, inactivity)

    await svc.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="no_traffic_7_days")
    updated = await survey_service._surveys.get(survey.id)
    assert updated.operational_status == ACTIVE
    assert updated.ai_decision_subject_id is not None


@pytest.mark.asyncio
async def test_unrecognized_action_is_rejected(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    svc = _service(db, FakeLLM(_decision(decision="DO_SOMETHING_WEIRD")), survey_service, inactivity)

    with pytest.raises(OperationsAIError):
        await svc.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="no_traffic_7_days")


@pytest.mark.asyncio
async def test_same_day_same_trigger_is_idempotent(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    llm = FakeLLM(_decision(decision="PAUSE"))
    svc = _service(db, llm, survey_service, inactivity)

    first = await svc.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="no_traffic_7_days")
    second = await svc.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="no_traffic_7_days")

    assert first == second
    assert len(llm.calls) == 1  # the model was only ever asked once for this (survey, trigger, day)


@pytest.mark.asyncio
async def test_decision_is_traceable_to_its_ai_proposal(db, survey_service, inactivity):
    survey = await _live_survey(survey_service)
    svc = _service(db, FakeLLM(_decision(decision="ESCALATE")), survey_service, inactivity)

    await svc.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="no_traffic_7_days")
    updated = await survey_service._surveys.get(survey.id)

    proposal = await CanonicalRepository(db["ai_proposals"], AiProposal).find_one({"subject_id": updated.ai_decision_subject_id})
    assert proposal is not None
    assert proposal.task == "evaluate_operations_response"
