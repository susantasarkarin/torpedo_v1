"""
Slice 11 — `app.ai.decision_engine.DecisionEngine`: the structured decision contract
(master-prompt §7), I-4 applied to the model boundary (a model outage is raised,
never a fabricated decision), and `AiProposal` reused as the audit log rather than a
second decision-log entity invented for this engine.
"""

import json
from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError

from app.ai.decision_engine import Decision, DecisionEngine, DecisionEngineError
from app.ai.llm import LLMResponse, LLMUnavailable
from app.ai.tools import ToolRegistry, ToolSpec
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository

ORG = "org-A"


class FakeLLM:
    def __init__(self, content: str | None = None, raises: Exception | None = None):
        self._content = content
        self._raises = raises
        self.calls: list[list[dict]] = []

    async def chat(self, *, messages, response_format=None):
        self.calls.append(messages)
        if self._raises:
            raise self._raises
        return LLMResponse(content=self._content, model="fake-model")


def _valid_decision_json(**overrides) -> str:
    payload = {
        "decision": "send_followup_email", "reasoning_summary": "invoice is 10 days overdue", "confidence": 0.9,
        "priority": "MEDIUM", "entities": ["invoice-1"], "actions": ["draft_email"], "follow_up_at": None,
        "requires_human_approval": False,
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
async def test_decide_returns_a_validated_decision(ai_proposals):
    llm = FakeLLM(content=_valid_decision_json())
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)

    decision = await engine.decide(org_id=ORG, task="ar_followup", subject_id="invoice-1", context={"days_overdue": 10})

    assert decision.decision == "send_followup_email"
    assert decision.priority == "MEDIUM"
    assert decision.requires_human_approval is False


@pytest.mark.asyncio
async def test_decide_persists_an_ai_proposal_as_the_audit_log(ai_proposals):
    llm = FakeLLM(content=_valid_decision_json())
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)

    await engine.decide(org_id=ORG, task="ar_followup", subject_id="invoice-1", context={})

    proposal = await ai_proposals.find_one({"subject_id": "invoice-1"})
    assert proposal is not None
    assert proposal.task == "ar_followup"
    assert proposal.status == "approved"  # high confidence, no human-approval flag


@pytest.mark.asyncio
async def test_low_confidence_decision_is_never_auto_appliable(ai_proposals):
    llm = FakeLLM(content=_valid_decision_json(confidence=0.2))
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)

    decision = await engine.decide(org_id=ORG, task="ar_followup", subject_id="invoice-2", context={})
    assert decision.is_auto_appliable() is False

    proposal = await ai_proposals.find_one({"subject_id": "invoice-2"})
    assert proposal.status == "rejected"


@pytest.mark.asyncio
async def test_requires_human_approval_is_never_auto_appliable_even_at_high_confidence(ai_proposals):
    """A confident model is not the same thing as an authorized one — mirrors
    RBACService.can_approve()'s refusal to let a wildcard or a system principal
    stand in for real approval authority."""
    llm = FakeLLM(content=_valid_decision_json(confidence=0.99, requires_human_approval=True))
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)

    decision = await engine.decide(org_id=ORG, task="finance_adjustment", subject_id="inv-3", context={})
    assert decision.is_auto_appliable() is False

    proposal = await ai_proposals.find_one({"subject_id": "inv-3"})
    assert proposal.status == "rejected"
    assert proposal.proposed_fields["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_model_outage_is_raised_never_a_fabricated_decision(ai_proposals):
    llm = FakeLLM(raises=LLMUnavailable("GPU node is cold-starting"))
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)

    with pytest.raises(LLMUnavailable):
        await engine.decide(org_id=ORG, task="ar_followup", subject_id="invoice-1", context={})

    assert await ai_proposals.find_one({"subject_id": "invoice-1"}) is None  # nothing recorded — no decision was made


@pytest.mark.asyncio
async def test_malformed_model_output_raises_decision_engine_error_not_a_default_decision(ai_proposals):
    llm = FakeLLM(content="this is not json")
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)

    with pytest.raises(DecisionEngineError):
        await engine.decide(org_id=ORG, task="ar_followup", subject_id="invoice-1", context={})


@pytest.mark.asyncio
async def test_unrecognized_priority_is_rejected(ai_proposals):
    llm = FakeLLM(content=_valid_decision_json(priority="SUPER_URGENT"))
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)

    with pytest.raises(DecisionEngineError):
        await engine.decide(org_id=ORG, task="ar_followup", subject_id="invoice-1", context={})


def test_decision_schema_rejects_confidence_outside_valid_range():
    with pytest.raises(ValidationError):
        Decision(decision="x", reasoning_summary="y", confidence=1.5, priority="LOW")


@pytest.mark.asyncio
async def test_tool_registry_is_described_to_the_model_but_never_auto_invoked():
    calls = []

    async def fake_tool(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(ToolSpec(name="get_invoice", description="fetch an invoice by id", handler=fake_tool))

    llm = FakeLLM(content=_valid_decision_json())
    engine = DecisionEngine(llm, registry, CanonicalRepository(AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]["ai_proposals"], AiProposal))

    await engine.decide(org_id=ORG, task="ar_followup", subject_id="invoice-1", context={})

    assert calls == []  # the engine never calls a tool on its own
    sent_context = json.loads(llm.calls[0][1]["content"])
    assert sent_context["available_tools"] == [{"name": "get_invoice", "description": "fetch an invoice by id"}]
