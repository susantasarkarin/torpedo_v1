"""
Phase 3 — AI-driven Lead -> Opportunity conversion, the gap this rebuild has
explicitly, honestly documented as manual since Slice 18's end-to-end test.
Same discipline as every other AI slice: deterministic eligibility gate, real
DecisionEngine call, governed execution through the unchanged Slice 10
OpportunityService — these tests prove the composition and its guardrails,
not re-prove OpportunityService's own mechanics (test_crm_service.py).
"""

import json
from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import DecisionEngine
from app.ai.llm import LLMResponse
from app.ai.tools import ToolRegistry
from app.crm.models import Opportunity
from app.crm.service import OpportunityService
from app.finance.models import Invoice
from app.finance.sequence import SequenceService
from app.finance.service import InvoiceService
from app.identity.facet_service import FacetService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.leadgen.ai_conversion import LeadConversionAIError, LeadConversionAIService
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository

ORG = "org-A"
ACTOR = "system"


class FakeLLM:
    def __init__(self, content: str):
        self._content = content
        self.calls: list[dict] = []

    async def chat(self, *, messages, response_format=None):
        self.calls.append(json.loads(messages[1]["content"]))
        return LLMResponse(content=self._content, model="fake-model")


def _decision(**overrides) -> str:
    payload = {
        "decision": "HOLD", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "MEDIUM",
        "entities": [], "actions": [], "follow_up_at": None, "requires_human_approval": False, "extracted_entities": {},
    }
    payload.update(overrides)
    return json.dumps(payload)


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def identity(db) -> IdentityService:
    return IdentityService(people=CanonicalRepository(db["people"], Person), accounts=CanonicalRepository(db["accounts"], Account), brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship), activities=CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def facets(db) -> FacetService:
    return FacetService(people=CanonicalRepository(db["people"], Person), accounts=CanonicalRepository(db["accounts"], Account), activities=CanonicalRepository(db["activities"], Activity), lead_states=CanonicalRepository(db["lead_states"], LeadState), panelist_profiles=CanonicalRepository(db["panelist_profiles"], PanelistProfile), customer_billing=CanonicalRepository(db["customer_billing"], CustomerBilling), vendor_profiles=CanonicalRepository(db["vendor_profiles"], VendorProfile), employee_records=CanonicalRepository(db["employee_records"], EmployeeRecord), auth_identities=CanonicalRepository(db["auth_identities"], AuthIdentity))


@pytest.fixture
def invoice_service(db) -> InvoiceService:
    return InvoiceService(CanonicalRepository(db["invoices"], Invoice), SequenceService(db["finance_sequences"]), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def opportunity_service(db, invoice_service) -> OpportunityService:
    return OpportunityService(CanonicalRepository(db["opportunities"], Opportunity), CanonicalRepository(db["activities"], Activity), invoice_service)


def _service(db, llm, facets, opportunity_service, shadow_mode=False) -> LeadConversionAIService:
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    return LeadConversionAIService(engine, facets, opportunity_service, CanonicalRepository(db["accounts"], Account), shadow_mode=shadow_mode)


async def _qualified_lead_with_account(db, identity, facets, *, state="qualified") -> LeadState:
    account = await identity.resolve_account(org_id=ORG, actor=ACTOR, domain="acme.example", name="Acme")
    person = await identity.create_person(org_id=ORG, actor=ACTOR, primary_email="lead@acme.example")
    lead = await facets.attach_lead_state(actor=ACTOR, person_id=person.id, source_type="gsc_ai", account_id=account.account_id)
    return await facets.update_lead_state(lead.id, lead.version, {"state": state}, updated_by=ACTOR)


# --------------------------------------------------------------------------- list_conversion_eligible


@pytest.mark.asyncio
async def test_only_qualified_leads_with_a_real_account_are_eligible(db, identity, facets):
    eligible = await _qualified_lead_with_account(db, identity, facets, state="qualified")
    lead_states = CanonicalRepository(db["lead_states"], LeadState)
    await lead_states.insert(LeadState(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, person_id="p2", source_type="gsc_ai", state="discovered", account_id="acct-x"))  # not yet qualified
    await lead_states.insert(LeadState(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, person_id="p3", source_type="gsc_ai", state="qualified", account_id=None))  # no account

    svc = _service(db, FakeLLM(_decision()), facets, None)
    result = await svc.list_conversion_eligible(org_id=ORG)
    assert [lead.id for lead in result] == [eligible.id]


# --------------------------------------------------------------------------- evaluate_and_convert


@pytest.mark.asyncio
async def test_convert_at_high_confidence_creates_a_real_opportunity_and_marks_the_lead_converted(db, identity, facets, opportunity_service):
    lead = await _qualified_lead_with_account(db, identity, facets)
    llm = FakeLLM(_decision(decision="CONVERT", confidence=0.9))
    svc = _service(db, llm, facets, opportunity_service)

    decision, opportunity = await svc.evaluate_and_convert(org_id=ORG, actor=ACTOR, lead_state_id=lead.id)
    assert decision.decision == "CONVERT"
    assert opportunity is not None
    assert opportunity.account_id == lead.account_id

    updated_lead = await facets.get_lead_state(lead.id)
    assert updated_lead.state == "converted"
    assert updated_lead.ai_conversion_decision_subject_id == lead.id


@pytest.mark.asyncio
async def test_hold_creates_no_opportunity_but_still_traces_the_decision(db, identity, facets, opportunity_service):
    lead = await _qualified_lead_with_account(db, identity, facets)
    llm = FakeLLM(_decision(decision="HOLD", confidence=0.9))
    svc = _service(db, llm, facets, opportunity_service)

    decision, opportunity = await svc.evaluate_and_convert(org_id=ORG, actor=ACTOR, lead_state_id=lead.id)
    assert decision.decision == "HOLD"
    assert opportunity is None

    updated_lead = await facets.get_lead_state(lead.id)
    assert updated_lead.state == "qualified"  # unchanged — HOLD never touches state
    assert updated_lead.ai_conversion_decision_subject_id == lead.id  # traced anyway, so the scheduler doesn't re-offer it every tick

    opportunities = await CanonicalRepository(db["opportunities"], Opportunity).find_all({})
    assert opportunities == []


@pytest.mark.asyncio
async def test_low_confidence_convert_is_never_auto_applied(db, identity, facets, opportunity_service):
    lead = await _qualified_lead_with_account(db, identity, facets)
    llm = FakeLLM(_decision(decision="CONVERT", confidence=0.2))
    svc = _service(db, llm, facets, opportunity_service)

    decision, opportunity = await svc.evaluate_and_convert(org_id=ORG, actor=ACTOR, lead_state_id=lead.id)
    assert opportunity is None
    opportunities = await CanonicalRepository(db["opportunities"], Opportunity).find_all({})
    assert opportunities == []


@pytest.mark.asyncio
async def test_shadow_mode_records_the_decision_but_never_converts(db, identity, facets, opportunity_service):
    lead = await _qualified_lead_with_account(db, identity, facets)
    llm = FakeLLM(_decision(decision="CONVERT", confidence=0.95))
    svc = _service(db, llm, facets, opportunity_service, shadow_mode=True)

    decision, opportunity = await svc.evaluate_and_convert(org_id=ORG, actor=ACTOR, lead_state_id=lead.id)
    assert decision.decision == "CONVERT"
    assert opportunity is None

    updated_lead = await facets.get_lead_state(lead.id)
    assert updated_lead.state == "qualified"  # never converted
    opportunities = await CanonicalRepository(db["opportunities"], Opportunity).find_all({})
    assert opportunities == []

    proposal = await CanonicalRepository(db["ai_proposals"], AiProposal).find_one({"task": "evaluate_lead_conversion"})
    assert proposal is not None
    assert proposal.status == "approved"  # would have auto-applied, had shadow mode not held it back


@pytest.mark.asyncio
async def test_a_lead_with_no_account_is_rejected_outright(db, facets, opportunity_service):
    person = await IdentityService(people=CanonicalRepository(db["people"], Person), accounts=CanonicalRepository(db["accounts"], Account), brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship), activities=CanonicalRepository(db["activities"], Activity)).create_person(org_id=ORG, actor=ACTOR, primary_email="lead@example.com")
    lead = await facets.attach_lead_state(actor=ACTOR, person_id=person.id, source_type="gsc_ai")
    lead = await facets.update_lead_state(lead.id, lead.version, {"state": "qualified"}, updated_by=ACTOR)

    svc = _service(db, FakeLLM(_decision()), facets, opportunity_service)
    with pytest.raises(LeadConversionAIError):
        await svc.evaluate_and_convert(org_id=ORG, actor=ACTOR, lead_state_id=lead.id)


@pytest.mark.asyncio
async def test_a_lead_not_yet_qualified_is_rejected_outright(db, identity, facets, opportunity_service):
    lead = await _qualified_lead_with_account(db, identity, facets, state="discovered")
    svc = _service(db, FakeLLM(_decision()), facets, opportunity_service)
    with pytest.raises(LeadConversionAIError):
        await svc.evaluate_and_convert(org_id=ORG, actor=ACTOR, lead_state_id=lead.id)


@pytest.mark.asyncio
async def test_unrecognized_conversion_action_is_rejected(db, identity, facets, opportunity_service):
    lead = await _qualified_lead_with_account(db, identity, facets)
    llm = FakeLLM(_decision(decision="MAYBE_LATER"))
    svc = _service(db, llm, facets, opportunity_service)
    with pytest.raises(LeadConversionAIError):
        await svc.evaluate_and_convert(org_id=ORG, actor=ACTOR, lead_state_id=lead.id)


@pytest.mark.asyncio
async def test_missing_lead_raises(db, facets, opportunity_service):
    svc = _service(db, FakeLLM(_decision()), facets, opportunity_service)
    with pytest.raises(LeadConversionAIError):
        await svc.evaluate_and_convert(org_id=ORG, actor=ACTOR, lead_state_id="does-not-exist")
