"""
Slice 15 — AI panel allocation. Real AI ranking through the actual
`DecisionEngine`, with every hard constraint (the >20% conversion gate, quota,
eligibility) enforced by `SurveyService.list_eligible()`/`AllocationService.allocate()`
(Slice 9, unchanged) — these tests exist to prove the AI cannot bypass any of them,
not to re-prove Slice 9's own atomicity (already covered in test_panel_service.py).
"""

import json
from datetime import timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import DecisionEngine
from app.ai.llm import LLMResponse
from app.ai.tools import ToolRegistry
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.panel.ai_allocation import PanelAllocationAIError, PanelAllocationAIService
from app.panel.models import Allocation, Survey, SurveyResponse
from app.panel.providers import SurveyProjection
from app.panel.service import AllocationService, SurveyService

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


class StubProvider:
    async def build_redirect_url(self, *, survey, respondent_ref):
        return f"https://stub/{survey.external_id}/{respondent_ref}"

    async def refresh(self, *, survey):
        return SurveyProjection(quota_remaining=survey.quota_remaining, cpi_minor=survey.cpi.amount_minor, conversion_rate=survey.conversion_rate)


def _decision(**overrides) -> str:
    payload = {
        "decision": "NONE", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "LOW",
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
def allocation_service(db) -> AllocationService:
    return AllocationService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), CanonicalRepository(db["activities"], Activity))


def _service(db, llm, survey_service, allocation_service) -> PanelAllocationAIService:
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    return PanelAllocationAIService(engine, survey_service, allocation_service, CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["allocations"], Allocation))


async def _eligible_survey(svc: SurveyService, *, external_id: str, conversion_rate: float = 0.3, quota: int = 5) -> Survey:
    survey = await svc.create_survey(
        org_id=ORG, actor=ACTOR, provider="cint", external_id=external_id, quota_remaining=quota,
        cpi=Money(amount_minor=500, currency=CURRENCY), conversion_rate=conversion_rate,
        category="consumer_goods", length_minutes=12, incentive=Money(amount_minor=150, currency=CURRENCY),
    )
    return await svc.set_eligibility(actor=ACTOR, survey_id=survey.id, is_active_in_pool=True, activated_at=None)


@pytest.mark.asyncio
async def test_survey_at_or_below_conversion_threshold_is_never_offered_to_the_model(db, survey_service, allocation_service):
    ineligible = await _eligible_survey(survey_service, external_id="low", conversion_rate=0.15)
    eligible = await _eligible_survey(survey_service, external_id="high", conversion_rate=0.35)
    llm = FakeLLM(_decision(decision=eligible.id))
    svc = _service(db, llm, survey_service, allocation_service)

    await svc.evaluate_and_allocate(org_id=ORG, actor=ACTOR, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=StubProvider())

    offered_ids = {s["survey_id"] for s in llm.calls[0]["context"]["eligible_surveys"]}
    assert ineligible.id not in offered_ids
    assert eligible.id in offered_ids


@pytest.mark.asyncio
async def test_no_eligible_surveys_raises_without_ever_calling_the_model(db, survey_service, allocation_service):
    llm = FakeLLM(_decision())
    svc = _service(db, llm, survey_service, allocation_service)

    with pytest.raises(PanelAllocationAIError):
        await svc.evaluate_and_allocate(org_id=ORG, actor=ACTOR, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=StubProvider())
    assert llm.calls == []


@pytest.mark.asyncio
async def test_ai_choice_is_executed_by_the_real_allocation_service(db, survey_service, allocation_service):
    survey = await _eligible_survey(survey_service, external_id="s1")
    llm = FakeLLM(_decision(decision=survey.id, actions=["allocate"], extracted_entities={survey.id: {"score": 0.8}}))
    svc = _service(db, llm, survey_service, allocation_service)

    decision, allocation = await svc.evaluate_and_allocate(org_id=ORG, actor=ACTOR, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=StubProvider())

    assert decision.decision == survey.id
    assert allocation is not None
    assert allocation.survey_id == survey.id
    assert allocation.ai_decision_subject_id == "p1:r1"


@pytest.mark.asyncio
async def test_model_choosing_a_survey_outside_the_eligible_set_is_rejected(db, survey_service, allocation_service):
    await _eligible_survey(survey_service, external_id="s1")
    llm = FakeLLM(_decision(decision="fabricated-survey-id-not-real"))
    svc = _service(db, llm, survey_service, allocation_service)

    with pytest.raises(PanelAllocationAIError):
        await svc.evaluate_and_allocate(org_id=ORG, actor=ACTOR, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=StubProvider())

    allocations = await CanonicalRepository(db["allocations"], Allocation).find_all({})
    assert allocations == []


@pytest.mark.asyncio
async def test_model_recommending_none_creates_no_allocation(db, survey_service, allocation_service):
    await _eligible_survey(survey_service, external_id="s1")
    llm = FakeLLM(_decision(decision="NONE"))
    svc = _service(db, llm, survey_service, allocation_service)

    decision, allocation = await svc.evaluate_and_allocate(org_id=ORG, actor=ACTOR, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=StubProvider())
    assert decision.decision == "NONE"
    assert allocation is None


@pytest.mark.asyncio
async def test_low_confidence_recommendation_is_never_auto_applied(db, survey_service, allocation_service):
    survey = await _eligible_survey(survey_service, external_id="s1")
    llm = FakeLLM(_decision(decision=survey.id, confidence=0.2))
    svc = _service(db, llm, survey_service, allocation_service)

    decision, allocation = await svc.evaluate_and_allocate(org_id=ORG, actor=ACTOR, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=StubProvider())
    assert allocation is None

    survey_after = await survey_service._surveys.get(survey.id)
    assert survey_after.quota_remaining == 5  # never reserved


@pytest.mark.asyncio
async def test_context_carries_real_historical_completion_and_dropout_rates(db, survey_service, allocation_service):
    survey = await _eligible_survey(survey_service, external_id="s1")
    responses = CanonicalRepository(db["survey_responses"], SurveyResponse)
    await responses.insert(SurveyResponse(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, allocation_id="a1", survey_id="other-survey", person_id="p1", respondent_ref="rr1", provider="cint", external_event_id="e1", final_status="complete"))
    await responses.insert(SurveyResponse(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, allocation_id="a2", survey_id="other-survey", person_id="p1", respondent_ref="rr2", provider="cint", external_event_id="e2", final_status="terminated"))

    llm = FakeLLM(_decision(decision=survey.id))
    svc = _service(db, llm, survey_service, allocation_service)
    await svc.evaluate_and_allocate(org_id=ORG, actor=ACTOR, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=StubProvider())

    history = llm.calls[0]["context"]["panelist_history_by_survey"][survey.id]
    assert history["historical_completion_rate"] == 0.5
    assert history["historical_dropout_rate"] == 0.5
    assert history["total_prior_responses"] == 2
    assert history["previously_exposed_to_this_survey"] is False


@pytest.mark.asyncio
async def test_previous_exposure_to_the_same_survey_is_detected(db, survey_service, allocation_service):
    survey = await _eligible_survey(survey_service, external_id="s1", quota=5)
    await CanonicalRepository(db["allocations"], Allocation).insert(Allocation(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, survey_id=survey.id, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="prior-ref", redirect_url="https://x"))

    llm = FakeLLM(_decision(decision="NONE"))
    svc = _service(db, llm, survey_service, allocation_service)
    await svc.evaluate_and_allocate(org_id=ORG, actor=ACTOR, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="new-ref", provider=StubProvider())

    history = llm.calls[0]["context"]["panelist_history_by_survey"][survey.id]
    assert history["previously_exposed_to_this_survey"] is True
    assert history["days_since_last_allocation"] is not None


@pytest.mark.asyncio
async def test_allocation_is_traceable_to_the_ai_decision_that_made_it(db, survey_service, allocation_service):
    survey = await _eligible_survey(survey_service, external_id="s1")
    llm = FakeLLM(_decision(decision=survey.id))
    svc = _service(db, llm, survey_service, allocation_service)

    _, allocation = await svc.evaluate_and_allocate(org_id=ORG, actor=ACTOR, person_id="p1", vendor_id="v1", country_code="IN", respondent_ref="r1", provider=StubProvider())

    proposal = await CanonicalRepository(db["ai_proposals"], AiProposal).find_one({"subject_id": allocation.ai_decision_subject_id})
    assert proposal is not None
    assert proposal.task == "evaluate_panel_allocation"
