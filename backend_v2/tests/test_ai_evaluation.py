"""
Phase 2 — the DecisionEvaluator harness itself. Proves the harness correctly
detects a passing case, a hallucinated-candidate case, and a failed
acceptance check — against FakeLLM today. The exact same `EvalCase` fixtures
below are the reusable baseline to point at a real model once
`RUNPOD_API_KEY` is configured (see docs/GPU_ACTIVATION_RUNBOOK.md Phase C).
"""

import json
from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import DecisionEngine
from app.ai.evaluation import EvalCase, run_evaluation, summarize
from app.ai.llm import LLMResponse
from app.ai.tools import ToolRegistry
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository

ORG = "org-A"


class ScriptedLLM:
    """Returns the next response in a fixed sequence, one per call — the
    fixtures below always call decide() in a known order."""

    def __init__(self, contents: list[str]):
        self._contents = list(contents)

    async def chat(self, *, messages, response_format=None):
        content = self._contents.pop(0)
        return LLMResponse(content=content, model="fake-model")


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
def ai_proposals(db) -> CanonicalRepository[AiProposal]:
    return CanonicalRepository(db["ai_proposals"], AiProposal)


@pytest.mark.asyncio
async def test_a_correct_in_candidate_decision_passes(db, ai_proposals):
    llm = ScriptedLLM([_decision(decision="survey-1", confidence=0.9)])
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)
    cases = [
        EvalCase(
            name="allocate_to_the_only_eligible_survey", task="evaluate_panel_allocation", subject_id="eval-1",
            context={"eligible_surveys": [{"survey_id": "survey-1"}]},
            check=lambda d: d.is_auto_appliable(),
            candidate_ids=frozenset({"survey-1"}),
        )
    ]
    results = await run_evaluation(engine, org_id=ORG, cases=cases)
    assert results[0].passed is True
    assert summarize(results) == {"total": 1, "passed": 1, "failed": 0, "pass_rate": 1.0, "hallucinated_candidate_count": 0, "engine_errored_count": 0}


@pytest.mark.asyncio
async def test_a_hallucinated_candidate_is_caught_and_reported_distinctly(db, ai_proposals):
    llm = ScriptedLLM([_decision(decision="survey-does-not-exist", confidence=0.9)])
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)
    cases = [
        EvalCase(
            name="model_invents_a_survey_id", task="evaluate_panel_allocation", subject_id="eval-2",
            context={"eligible_surveys": [{"survey_id": "survey-1"}]},
            check=lambda d: True, candidate_ids=frozenset({"survey-1"}),
        )
    ]
    results = await run_evaluation(engine, org_id=ORG, cases=cases)
    assert results[0].passed is False
    assert "candidate set" in results[0].error
    assert summarize(results)["hallucinated_candidate_count"] == 1


@pytest.mark.asyncio
async def test_a_business_acceptance_check_can_fail_independently_of_candidate_validity(db, ai_proposals):
    """A model choosing a *valid* candidate can still be judged wrong for
    this specific fixture — e.g. recommending NO_ACTION on a 60-day-overdue
    invoice. This is the harness's honest scope: fixture-specific acceptance,
    not general business correctness (that needs Phase 12's real outcome
    data, not a fixed test set)."""
    llm = ScriptedLLM([_decision(decision="NO_ACTION", confidence=0.9)])
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)
    cases = [
        EvalCase(
            name="should_not_recommend_no_action_on_a_severely_overdue_invoice", task="evaluate_ar_followup", subject_id="eval-3",
            context={"evidence": {"days_overdue": 60}},
            check=lambda d: d.decision != "NO_ACTION",
        )
    ]
    results = await run_evaluation(engine, org_id=ORG, cases=cases)
    assert results[0].passed is False
    assert results[0].error == "acceptance check failed"


@pytest.mark.asyncio
async def test_a_model_outage_mid_evaluation_is_recorded_not_raised(db, ai_proposals):
    """One bad fixture (a real model outage, a malformed response) must not
    crash the whole evaluation run — it's recorded as a failed case with a
    real error message, and the run continues."""
    llm = ScriptedLLM(["not valid json at all", _decision(decision="survey-1")])
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)
    cases = [
        EvalCase(name="malformed_response", task="t", subject_id="eval-4", context={}, check=lambda d: True),
        EvalCase(name="then_a_valid_one", task="t", subject_id="eval-5", context={}, check=lambda d: True),
    ]
    results = await run_evaluation(engine, org_id=ORG, cases=cases)
    assert results[0].passed is False
    assert results[0].decision is None
    assert results[0].error is not None
    assert results[1].passed is True  # the run continued past the failure
