"""
Slice 13 — GSC lead generation + ICP evaluation, both routed through the real
`DecisionEngine`. Every created lead reuses Slice 6's `LeadGenService.ingest()`
(identity resolution, dedup, provenance) unchanged — these tests prove the AI
layer's composition and its guardrails, not re-prove Slice 6's own pipeline.
"""

import json
from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import DecisionEngine, LLMUnavailable
from app.ai.llm import LLMResponse
from app.ai.tools import ToolRegistry
from app.identity.facet_service import FacetService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.leadgen.ai_leadgen import LeadGenAIError, LeadGenAIService
from app.leadgen.gsc import GSCProviderUnavailable, SearchSignal
from app.leadgen.models import DeadLetterEvent, LeadEnrollment, RawLeadEvent
from app.leadgen.service import LeadGenService
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.outreach.suppression import Suppression, SuppressionService

ORG = "org-A"
ACTOR = "system"
SITE = "https://torpedo.example"


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


class FakeGSC:
    def __init__(self, signals: list[SearchSignal] | None = None, raises: Exception | None = None):
        self._signals = signals or []
        self._raises = raises

    async def get_search_analytics(self, *, site_url: str, days: int = 28):
        if self._raises:
            raise self._raises
        return self._signals


_SIGNAL = SearchSignal(query="ai survey panel provider", page="/services/panel", impressions=500, clicks=40, ctr=0.08, position=3.2, country="IN")


def _leads_decision(candidates: list[dict]) -> str:
    return json.dumps({
        "decision": "generate_leads", "reasoning_summary": "high commercial intent queries found", "confidence": 0.85,
        "priority": "MEDIUM", "entities": [], "actions": [], "follow_up_at": None, "requires_human_approval": False,
        "extracted_entities": {"candidates": candidates},
    })


def _icp_decision(*, recommended_action="OUTREACH", score=80, classification="A", confidence=0.88) -> str:
    return json.dumps({
        "decision": recommended_action, "reasoning_summary": "strong fit with existing customer base", "confidence": confidence,
        "priority": "MEDIUM", "entities": [], "actions": [], "follow_up_at": None, "requires_human_approval": False,
        "extracted_entities": {"score": score, "classification": classification, "fit_reasons": ["similar industry to top accounts"], "risks": []},
    })


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
def leadgen(db, identity, facets) -> LeadGenService:
    suppression = SuppressionService(CanonicalRepository(db["suppressions"], Suppression))
    return LeadGenService(identity, facets, suppression, raw_events=CanonicalRepository(db["raw_lead_events"], RawLeadEvent), ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal), enrollments=CanonicalRepository(db["lead_enrollments"], LeadEnrollment), dead_letters=CanonicalRepository(db["dead_letters"], DeadLetterEvent), activities=CanonicalRepository(db["activities"], Activity))


def _service(db, llm, leadgen) -> LeadGenAIService:
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    return LeadGenAIService(engine, leadgen)


# --------------------------------------------------------------------------- generate_leads


@pytest.mark.asyncio
async def test_high_intent_gsc_signal_produces_a_real_lead_with_provenance(db, leadgen, identity):
    llm = FakeLLM(content=_leads_decision([{"company_domain": "acme.com", "company_name": "Acme Research", "contact_email": "ops@acme.com", "contact_name": "Jordan Lee", "title": "Head of Insights", "evidence": "query='ai survey panel provider', position=3.2"}]))
    svc = _service(db, llm, leadgen)

    results = await svc.generate_leads(org_id=ORG, actor=ACTOR, site_url=SITE, gsc=FakeGSC(signals=[_SIGNAL]))

    assert len(results) == 1
    person = await identity.get_person(results[0].person_id)
    assert person.primary_email == "ops@acme.com"

    event = await CanonicalRepository(db["raw_lead_events"], RawLeadEvent).find_one({"source_type": "gsc_ai", "source_record_id": "gsc:https://torpedo.example:acme.com:ops@acme.com"})
    assert event is not None
    assert "position=3.2" in event.payload["gsc_evidence"]  # real provenance, not a claim


@pytest.mark.asyncio
async def test_low_intent_scenario_can_produce_zero_candidates(db, leadgen):
    """The model deciding 'nothing here is worth a lead' is a legitimate outcome,
    not an error — no candidates means no leads created, not a forced one."""
    llm = FakeLLM(content=_leads_decision([]))
    svc = _service(db, llm, leadgen)

    results = await svc.generate_leads(org_id=ORG, actor=ACTOR, site_url=SITE, gsc=FakeGSC(signals=[]))
    assert results == []


@pytest.mark.asyncio
async def test_candidate_without_company_domain_is_skipped_not_fabricated(db, leadgen):
    """Direct master-prompt §12 regression: 'do not generate fictional companies.'"""
    llm = FakeLLM(content=_leads_decision([{"contact_email": "someone@nowhere.example", "contact_name": "No Domain Given"}]))
    svc = _service(db, llm, leadgen)

    results = await svc.generate_leads(org_id=ORG, actor=ACTOR, site_url=SITE, gsc=FakeGSC(signals=[_SIGNAL]))
    assert results == []

    events = await CanonicalRepository(db["raw_lead_events"], RawLeadEvent).find_all({})
    assert events == []


@pytest.mark.asyncio
async def test_duplicate_company_across_two_generation_runs_resolves_to_the_same_account(db, leadgen, identity):
    """'Existing customer'/'duplicate company' scenario (master-prompt §26) —
    reuses Slice 4's identity resolution, not re-tested here, just proven composed."""
    candidate = {"company_domain": "acme.com", "company_name": "Acme Research", "contact_email": "ops@acme.com", "contact_name": "Jordan Lee"}
    llm = FakeLLM(content=_leads_decision([candidate]))
    svc = _service(db, llm, leadgen)

    first = await svc.generate_leads(org_id=ORG, actor=ACTOR, site_url=SITE, gsc=FakeGSC(signals=[_SIGNAL]))
    # A second run naming a different contact at the same company must resolve to
    # the same Account (domain-based resolution), not create a duplicate one.
    llm2 = FakeLLM(content=_leads_decision([{**candidate, "contact_email": "finance@acme.com", "contact_name": "Sam Rivera"}]))
    svc2 = _service(db, llm2, leadgen)
    second = await svc2.generate_leads(org_id=ORG, actor=ACTOR, site_url=SITE, gsc=FakeGSC(signals=[_SIGNAL]))

    first_person = await identity.get_person(first[0].person_id)
    second_person = await identity.get_person(second[0].person_id)
    assert first_person.id != second_person.id  # two different people
    accounts = await CanonicalRepository(db["accounts"], Account).find_all({"domain": "acme.com"})
    assert len(accounts) == 1  # but exactly one Acme account, not two


@pytest.mark.asyncio
async def test_gsc_unavailable_raises_and_creates_no_leads(db, leadgen):
    llm = FakeLLM(content=_leads_decision([{"company_domain": "acme.com"}]))
    svc = _service(db, llm, leadgen)

    with pytest.raises(LeadGenAIError):
        await svc.generate_leads(org_id=ORG, actor=ACTOR, site_url=SITE, gsc=FakeGSC(raises=GSCProviderUnavailable("no credentials")))

    assert llm.calls == []  # never even asked the model — failed before that


@pytest.mark.asyncio
async def test_model_outage_during_lead_generation_is_raised_not_silently_empty(db, leadgen):
    llm = FakeLLM(raises=LLMUnavailable("GPU node cold-starting"))
    svc = _service(db, llm, leadgen)

    with pytest.raises(LLMUnavailable):
        await svc.generate_leads(org_id=ORG, actor=ACTOR, site_url=SITE, gsc=FakeGSC(signals=[_SIGNAL]))


# --------------------------------------------------------------------------- evaluate_icp


@pytest.mark.asyncio
async def test_excellent_icp_recommends_outreach(db, leadgen):
    llm = FakeLLM(content=_icp_decision(recommended_action="OUTREACH", score=92, classification="A"))
    svc = _service(db, llm, leadgen)

    decision = await svc.evaluate_icp(org_id=ORG, actor=ACTOR, lead_state_id="lead-1", prospect_context={"industry": "market research", "country": "IN"})
    assert decision.decision == "OUTREACH"
    assert decision.extracted_entities["classification"] == "A"
    assert decision.extracted_entities["score"] == 92


@pytest.mark.asyncio
async def test_poor_icp_recommends_reject(db, leadgen):
    llm = FakeLLM(content=_icp_decision(recommended_action="REJECT", score=12, classification="D", confidence=0.7))
    svc = _service(db, llm, leadgen)

    decision = await svc.evaluate_icp(org_id=ORG, actor=ACTOR, lead_state_id="lead-2", prospect_context={"industry": "unrelated retail", "country": "XX"})
    assert decision.decision == "REJECT"
    assert decision.extracted_entities["classification"] == "D"


@pytest.mark.asyncio
async def test_unrecognized_icp_recommendation_is_rejected(db, leadgen):
    llm = FakeLLM(content=_icp_decision(recommended_action="MAYBE_LATER"))
    svc = _service(db, llm, leadgen)

    with pytest.raises(LeadGenAIError):
        await svc.evaluate_icp(org_id=ORG, actor=ACTOR, lead_state_id="lead-3", prospect_context={})


@pytest.mark.asyncio
async def test_evaluate_icp_traces_back_to_the_ai_proposal_without_touching_the_locked_scorer_field(db, identity, facets, leadgen):
    """ai_decision_subject_id is a different signal from icp_score — icp_score
    stays owned exclusively by app.leadgen.scoring's canonical scorer, per the
    field's own locked-invariant comment in app.identity.facets."""
    person = await identity.create_person(org_id=ORG, actor=ACTOR, primary_email="lead@example.com")
    lead = await facets.attach_lead_state(actor=ACTOR, person_id=person.id, source_type="gsc_ai")
    llm = FakeLLM(content=_icp_decision(recommended_action="OUTREACH"))
    svc = _service(db, llm, leadgen)

    await svc.evaluate_icp(org_id=ORG, actor=ACTOR, lead_state_id=lead.id, prospect_context={"industry": "market research"})

    lead_after = await facets.get_lead_state(lead.id)
    assert lead_after.ai_decision_subject_id == lead.id
    assert lead_after.icp_score is None  # untouched — only app.leadgen.scoring may ever set this
