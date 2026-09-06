"""
Slice 14 — AI outreach, the ICP→outreach flow (master-prompt §15-19), routed
through the real `DecisionEngine` and reusing Slice 6's contactability check and
Slice 7's `MessagingFacade` governance wholesale — these tests prove the
composition and its guardrails, not re-prove either underlying service.
"""

import json
from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import DecisionEngine
from app.ai.llm import LLMResponse
from app.ai.tools import ToolRegistry
from app.emailai.drafting import EmailMessageDrafter
from app.identity.facet_service import FacetService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.leadgen.ai_outreach import OutreachAIError, OutreachAIService
from app.leadgen.models import DeadLetterEvent, LeadEnrollment, RawLeadEvent
from app.leadgen.service import LeadGenService
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.outreach.budget import BudgetService
from app.outreach.kill_switch import KillSwitch, KillSwitchService
from app.outreach.models import Mailbox, Message, SendLogEntry
from app.outreach.providers import ProviderSendResult
from app.outreach.service import MessagingFacade
from app.outreach.suppression import Suppression, SuppressionService

ORG = "org-A"
ACTOR = "alice"
MAILBOX_ID = "mailbox-1"


class FakeLLM:
    def __init__(self, content: str):
        self._content = content
        self.calls: list[list[dict]] = []

    async def chat(self, *, messages, response_format=None):
        self.calls.append(messages)
        if any("draft business email" in str(m.get("content", "")).lower() for m in messages):
            return LLMResponse(content=json.dumps({"subject": "Quick question", "body": "Hi — thought this might help. Unsubscribe any time at https://example.com/u"}), model="fake-model")
        return LLMResponse(content=self._content, model="fake-model")


class RecordingSendProvider:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    async def send(self, *, mailbox_credentials_id, to_email, subject, body):
        self.calls.append((to_email, subject, body))
        return ProviderSendResult(provider_message_id=f"pm-{len(self.calls)}")


def _decision(**overrides) -> str:
    payload = {"decision": "OUTREACH_READY", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "LOW", "entities": [], "actions": [], "follow_up_at": None, "requires_human_approval": False, "extracted_entities": {}}
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
def suppression(db) -> SuppressionService:
    return SuppressionService(CanonicalRepository(db["suppressions"], Suppression))


@pytest.fixture
def leadgen(db, identity, facets, suppression) -> LeadGenService:
    return LeadGenService(identity, facets, suppression, raw_events=CanonicalRepository(db["raw_lead_events"], RawLeadEvent), ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal), enrollments=CanonicalRepository(db["lead_enrollments"], LeadEnrollment), dead_letters=CanonicalRepository(db["dead_letters"], DeadLetterEvent), activities=CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def send_provider() -> RecordingSendProvider:
    return RecordingSendProvider()


@pytest.fixture
def outreach(db, suppression, send_provider) -> MessagingFacade:
    return MessagingFacade(mailboxes=CanonicalRepository(db["mailboxes"], Mailbox), messages=CanonicalRepository(db["messages"], Message), send_logs=CanonicalRepository(db["send_log_entries"], SendLogEntry), ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal), activities=CanonicalRepository(db["activities"], Activity), suppression=suppression, kill_switch=KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch)), budget=BudgetService(db["budget_counters"]), provider=send_provider)


async def _setup_enrollment(db, identity, *, email="prospect@acme.com") -> tuple[LeadEnrollment, Person]:
    person = await identity.create_person(org_id=ORG, actor=ACTOR, primary_email=email, given_name="Jordan", family_name="Lee", title="VP Insights")
    lead_state = await CanonicalRepository(db["lead_states"], LeadState).insert(LeadState(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, person_id=person.id, source_type="test", state="assigned", icp_score=8))
    enrollment = await CanonicalRepository(db["lead_enrollments"], LeadEnrollment).insert(LeadEnrollment(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, lead_state_id=lead_state.id, person_id=person.id, brand_id="brand-1"))
    await KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch)).resume(org_id=ORG, actor="system")
    await CanonicalRepository(db["mailboxes"], Mailbox).insert(Mailbox(id=MAILBOX_ID, org_id=ORG, created_by="system", updated_by="system", email_address="sales@torpedo.example", provider="smtp", credentials_id="cred-1"))
    return enrollment, person


def _service(db, llm, leadgen, outreach, shadow_mode=False) -> OutreachAIService:
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    return OutreachAIService(engine, leadgen, outreach, EmailMessageDrafter(llm), CanonicalRepository(db["lead_enrollments"], LeadEnrollment), shadow_mode=shadow_mode)


@pytest.mark.asyncio
async def test_first_contact_decision_sends_and_updates_sequence_state(db, identity, leadgen, outreach, send_provider):
    enrollment, person = await _setup_enrollment(db, identity)
    llm = FakeLLM(_decision(decision="CONTACTED", confidence=0.9, actions=["send_message"]))
    svc = _service(db, llm, leadgen, outreach)

    decision = await svc.decide_and_act(org_id=ORG, actor=ACTOR, enrollment_id=enrollment.id, mailbox_id=MAILBOX_ID)

    assert decision.decision == "CONTACTED"
    assert len(send_provider.calls) == 1
    assert send_provider.calls[0][0] == person.primary_email

    updated = await CanonicalRepository(db["lead_enrollments"], LeadEnrollment).get(enrollment.id)
    assert updated.sequence_state == "CONTACTED"
    assert updated.ai_decision_subject_id == enrollment.id
    proposal = await CanonicalRepository(db["ai_proposals"], AiProposal).find_one({"subject_id": updated.ai_decision_subject_id, "task": "evaluate_outreach"})
    assert proposal is not None


@pytest.mark.asyncio
async def test_shadow_mode_records_the_decision_but_never_sends(db, identity, leadgen, outreach, send_provider):
    """Phase 14 continued — same shadow-mode discipline as the other four
    gated services. sequence_state still updates (an informational label,
    not the consequential action shadow mode holds back) — only the send is
    suppressed."""
    enrollment, person = await _setup_enrollment(db, identity)
    llm = FakeLLM(_decision(decision="CONTACTED", confidence=0.9, actions=["send_message"]))
    svc = _service(db, llm, leadgen, outreach, shadow_mode=True)

    decision = await svc.decide_and_act(org_id=ORG, actor=ACTOR, enrollment_id=enrollment.id, mailbox_id=MAILBOX_ID)
    assert decision.decision == "CONTACTED"
    assert send_provider.calls == []

    updated = await CanonicalRepository(db["lead_enrollments"], LeadEnrollment).get(enrollment.id)
    assert updated.sequence_state == "CONTACTED"


@pytest.mark.asyncio
async def test_low_confidence_never_sends(db, identity, leadgen, outreach, send_provider):
    enrollment, _ = await _setup_enrollment(db, identity)
    llm = FakeLLM(_decision(decision="CONTACTED", confidence=0.2, actions=["send_message"]))
    svc = _service(db, llm, leadgen, outreach)

    await svc.decide_and_act(org_id=ORG, actor=ACTOR, enrollment_id=enrollment.id, mailbox_id=MAILBOX_ID)
    assert send_provider.calls == []


@pytest.mark.asyncio
async def test_suppressed_contact_is_never_sent_to_even_if_ai_says_contacted(db, identity, leadgen, outreach, suppression, send_provider):
    """Direct master-prompt §10 regression, applied to outreach: contactability
    (built on suppression, Slice 6) is a hard boundary the AI cannot override."""
    enrollment, person = await _setup_enrollment(db, identity)
    await suppression.suppress(org_id=ORG, actor="system", email=person.primary_email, reason="prior unsubscribe", source="manual")
    llm = FakeLLM(_decision(decision="CONTACTED", confidence=0.95, actions=["send_message"]))
    svc = _service(db, llm, leadgen, outreach)

    await svc.decide_and_act(org_id=ORG, actor=ACTOR, enrollment_id=enrollment.id, mailbox_id=MAILBOX_ID)
    assert send_provider.calls == []


@pytest.mark.asyncio
async def test_stop_decision_updates_state_without_sending(db, identity, leadgen, outreach, send_provider):
    enrollment, _ = await _setup_enrollment(db, identity)
    llm = FakeLLM(_decision(decision="STOPPED", confidence=0.9, actions=[]))
    svc = _service(db, llm, leadgen, outreach)

    decision = await svc.decide_and_act(org_id=ORG, actor=ACTOR, enrollment_id=enrollment.id, mailbox_id=MAILBOX_ID)

    assert decision.decision == "STOPPED"
    assert send_provider.calls == []
    updated = await CanonicalRepository(db["lead_enrollments"], LeadEnrollment).get(enrollment.id)
    assert updated.sequence_state == "STOPPED"


@pytest.mark.asyncio
async def test_unrecognized_sequence_state_is_rejected(db, identity, leadgen, outreach):
    enrollment, _ = await _setup_enrollment(db, identity)
    llm = FakeLLM(_decision(decision="NOT_A_REAL_STATE"))
    svc = _service(db, llm, leadgen, outreach)

    with pytest.raises(OutreachAIError):
        await svc.decide_and_act(org_id=ORG, actor=ACTOR, enrollment_id=enrollment.id, mailbox_id=MAILBOX_ID)


@pytest.mark.asyncio
async def test_outreach_is_idempotent_across_a_simulated_worker_restart(db, identity, leadgen, outreach, send_provider):
    enrollment, _ = await _setup_enrollment(db, identity)
    llm = FakeLLM(_decision(decision="CONTACTED", confidence=0.9, actions=["send_message"]))
    svc = _service(db, llm, leadgen, outreach)

    await svc.decide_and_act(org_id=ORG, actor=ACTOR, enrollment_id=enrollment.id, mailbox_id=MAILBOX_ID)
    await svc.decide_and_act(org_id=ORG, actor=ACTOR, enrollment_id=enrollment.id, mailbox_id=MAILBOX_ID)  # simulated restart, re-decided

    assert len(send_provider.calls) == 1  # MessagingFacade's idempotency_key deduped the second attempt
