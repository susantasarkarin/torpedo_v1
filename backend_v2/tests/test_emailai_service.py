"""
Slice 12 — Email AI. Real AI-driven classification/routing/follow-up, tested
against a `FakeLLM` through the actual `DecisionEngine` — never a hard-coded
if/else standing in for the model's job. Every routed action reuses an existing,
already-governed service (Slice 6's leadgen ingest, Slice 7's suppression/send,
Slice 8's reconciliation) — these tests prove the composition, not re-prove the
underlying service (already exhaustively covered in their own test files).
"""

import json
from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import DecisionEngine, DecisionEngineError
from app.ai.llm import LLMResponse
from app.ai.tools import ToolRegistry
from app.emailai.drafting import EmailMessageDrafter
from app.emailai.models import InboundEmail
from app.emailai.service import EmailAIError, EmailAIService
from app.finance.models import Bill, BankAccount, CreditNote, Expense, Invoice, Payment, ReconciliationRecord
from app.finance.sequence import SequenceService
from app.finance.service import ReconciliationService
from app.identity.facet_service import FacetService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.leadgen.models import DeadLetterEvent, LeadEnrollment, RawLeadEvent
from app.leadgen.service import LeadGenService
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.outreach.kill_switch import KillSwitch, KillSwitchService
from app.outreach.models import Mailbox, Message, SendLogEntry
from app.outreach.providers import ProviderSendResult
from app.outreach.service import MessagingFacade
from app.outreach.suppression import Suppression, SuppressionService
from app.panel.models import Allocation, Supplier, Survey, SurveyResponse, SupplierReconciliationRecord, TrafficSource  # noqa: F401 (keeps mongomock db namespace consistent with other suites)

ORG = "org-A"
ACTOR = "alice"
MAILBOX_ID = "mailbox-1"

BODY_OK = "Thanks for reaching out — unsubscribe any time at https://example.com/u"


class FakeLLM:
    """Returns the same fixed response to every call by default. Tests that need
    to distinguish a decision-engine call from a drafter call (both go through the
    same `LLMProvider`) override `.chat` directly with a small routing function —
    simpler than a response queue for the handful of tests that need it."""

    def __init__(self, content: str = "{}"):
        self._content = content
        self.calls: list[list[dict]] = []

    async def chat(self, *, messages, response_format=None):
        self.calls.append(messages)
        return LLMResponse(content=self._content, model="fake-model")


class RecordingSendProvider:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    async def send(self, *, mailbox_credentials_id, to_email, subject, body):
        self.calls.append((to_email, subject, body))
        return ProviderSendResult(provider_message_id=f"pm-{len(self.calls)}")


def _classification(**overrides) -> str:
    payload = {
        "decision": "OTHER", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "LOW",
        "entities": [], "actions": [], "follow_up_at": None, "requires_human_approval": False, "extracted_entities": {},
    }
    payload.update(overrides)
    return json.dumps(payload)


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def identity(db) -> IdentityService:
    return IdentityService(
        people=CanonicalRepository(db["people"], Person), accounts=CanonicalRepository(db["accounts"], Account),
        brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship),
        activities=CanonicalRepository(db["activities"], Activity),
    )


@pytest.fixture
def facets(db) -> FacetService:
    return FacetService(
        people=CanonicalRepository(db["people"], Person), accounts=CanonicalRepository(db["accounts"], Account),
        activities=CanonicalRepository(db["activities"], Activity), lead_states=CanonicalRepository(db["lead_states"], LeadState),
        panelist_profiles=CanonicalRepository(db["panelist_profiles"], PanelistProfile), customer_billing=CanonicalRepository(db["customer_billing"], CustomerBilling),
        vendor_profiles=CanonicalRepository(db["vendor_profiles"], VendorProfile), employee_records=CanonicalRepository(db["employee_records"], EmployeeRecord),
        auth_identities=CanonicalRepository(db["auth_identities"], AuthIdentity),
    )


@pytest.fixture
def suppression(db) -> SuppressionService:
    return SuppressionService(CanonicalRepository(db["suppressions"], Suppression))


@pytest.fixture
def leadgen(db, identity, facets, suppression) -> LeadGenService:
    return LeadGenService(
        identity, facets, suppression, raw_events=CanonicalRepository(db["raw_lead_events"], RawLeadEvent),
        ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal), enrollments=CanonicalRepository(db["lead_enrollments"], LeadEnrollment),
        dead_letters=CanonicalRepository(db["dead_letters"], DeadLetterEvent), activities=CanonicalRepository(db["activities"], Activity),
    )


@pytest.fixture
def reconciliation(db) -> ReconciliationService:
    return ReconciliationService(CanonicalRepository(db["reconciliation_records"], ReconciliationRecord), CanonicalRepository(db["payments"], Payment))


@pytest.fixture
def send_provider() -> RecordingSendProvider:
    return RecordingSendProvider()


@pytest.fixture
def outreach(db, suppression, send_provider) -> MessagingFacade:
    return MessagingFacade(
        mailboxes=CanonicalRepository(db["mailboxes"], Mailbox), messages=CanonicalRepository(db["messages"], Message),
        send_logs=CanonicalRepository(db["send_log_entries"], SendLogEntry), ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal),
        activities=CanonicalRepository(db["activities"], Activity), suppression=suppression,
        kill_switch=KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch)), budget=_budget(db), provider=send_provider,
    )


def _budget(db):
    from app.outreach.budget import BudgetService
    return BudgetService(db["budget_counters"])


@pytest.fixture
def ai_proposals(db) -> CanonicalRepository[AiProposal]:
    return CanonicalRepository(db["ai_proposals"], AiProposal)


def _service(db, llm, leadgen, suppression, reconciliation, outreach, shadow_mode=False) -> EmailAIService:
    ai_proposals = CanonicalRepository(db["ai_proposals"], AiProposal)
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)
    return EmailAIService(
        emails=CanonicalRepository(db["inbound_emails"], InboundEmail), ai_proposals=ai_proposals,
        activities=CanonicalRepository(db["activities"], Activity), decision_engine=engine, leadgen=leadgen,
        suppression=suppression, reconciliation=reconciliation, outreach=outreach, drafter=EmailMessageDrafter(llm),
        shadow_mode=shadow_mode,
    )


async def _ingested_email(svc: EmailAIService, *, from_address="prospect@acme.com") -> InboundEmail:
    return await svc.ingest_email(
        org_id=ORG, actor=ACTOR, provider="gmail", provider_message_id="evt-1",
        from_address=from_address, to_address="sales@torpedo.example", subject="Interested in your research services", body="We'd like a quote.",
    )


# --------------------------------------------------------------------------- ingestion idempotency


@pytest.mark.asyncio
async def test_ingest_email_is_idempotent_on_provider_message_id(db, leadgen, suppression, reconciliation, outreach):
    llm = FakeLLM(content=_classification())
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)

    first = await _ingested_email(svc)
    second = await svc.ingest_email(org_id=ORG, actor=ACTOR, provider="gmail", provider_message_id="evt-1", from_address="x@y.com", to_address="z@torpedo.example", subject="different", body="different")

    assert first.id == second.id
    assert second.subject == first.subject  # the original, not the "different" replay


# --------------------------------------------------------------------------- classification + routing


@pytest.mark.asyncio
async def test_sales_lead_classification_creates_a_lead_via_existing_leadgen_pipeline(db, leadgen, suppression, reconciliation, outreach):
    content = _classification(decision="SALES_LEAD", confidence=0.92, extracted_entities={"contact_email": "prospect@acme.com", "contact_name": "Jordan Lee", "company_domain": "acme.com", "company_name": "Acme Research", "title": "VP Insights"})
    llm = FakeLLM(content=content)
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc)

    decision = await svc.analyze_and_route(org_id=ORG, actor=ACTOR, email_id=email.id)

    assert decision.decision == "SALES_LEAD"
    lead_event = await CanonicalRepository(db["raw_lead_events"], RawLeadEvent).find_one({"source_type": "email", "source_record_id": email.id})
    assert lead_event is not None
    assert lead_event.resolved_person_id is not None

    person = await leadgen._identity.get_person(lead_event.resolved_person_id)
    assert person.primary_email == "prospect@acme.com"


@pytest.mark.asyncio
async def test_classification_traces_back_to_the_ai_proposal_that_made_it(db, leadgen, suppression, reconciliation, outreach):
    llm = FakeLLM(content=_classification(decision="SPAM", confidence=0.6))
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc)

    await svc.analyze_and_route(org_id=ORG, actor=ACTOR, email_id=email.id)

    email_after = await CanonicalRepository(db["inbound_emails"], InboundEmail).get(email.id)
    assert email_after.ai_decision_subject_id == email.id
    proposal = await CanonicalRepository(db["ai_proposals"], AiProposal).find_one({"subject_id": email_after.ai_decision_subject_id, "task": "classify_email"})
    assert proposal is not None


@pytest.mark.asyncio
async def test_unsubscribe_classification_suppresses_the_sender(db, leadgen, suppression, reconciliation, outreach):
    llm = FakeLLM(content=_classification(decision="UNSUBSCRIBE", confidence=0.99))
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc, from_address="opt-out@acme.com")

    await svc.analyze_and_route(org_id=ORG, actor=ACTOR, email_id=email.id)

    assert await suppression.is_suppressed("opt-out@acme.com") is True


@pytest.mark.asyncio
async def test_payment_classification_records_a_reconciliation_candidate_never_touches_a_balance(db, leadgen, suppression, reconciliation, outreach):
    content = _classification(decision="PAYMENT", confidence=0.85, extracted_entities={"amount": {"amount_minor": 50000, "currency": "INR"}})
    llm = FakeLLM(content=content)
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc)

    await svc.analyze_and_route(org_id=ORG, actor=ACTOR, email_id=email.id)

    records = await CanonicalRepository(db["reconciliation_records"], ReconciliationRecord).find_all({"external_reference": email.id})
    assert len(records) == 1
    assert records[0].amount.amount_minor == 50000
    assert records[0].status == "unmatched"  # recorded as a candidate only — never auto-matched, never touches any balance


@pytest.mark.asyncio
async def test_existing_client_and_meeting_and_irrelevant_get_classified_with_no_automated_action(db, leadgen, suppression, reconciliation, outreach):
    for label in ("EXISTING_CLIENT", "MEETING", "IRRELEVANT", "SPAM"):
        llm = FakeLLM(content=_classification(decision=label))
        svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
        email = await svc.ingest_email(org_id=ORG, actor=ACTOR, provider="gmail", provider_message_id=f"evt-{label}", from_address="x@y.com", to_address="z@torpedo.example", subject="s", body="b")

        decision = await svc.analyze_and_route(org_id=ORG, actor=ACTOR, email_id=email.id)
        assert decision.decision == label

        updated = await CanonicalRepository(db["inbound_emails"], InboundEmail).get(email.id)
        assert updated.classification == label


@pytest.mark.asyncio
async def test_unrecognized_classification_is_rejected_and_nothing_is_routed(db, leadgen, suppression, reconciliation, outreach):
    llm = FakeLLM(content=_classification(decision="NOT_A_REAL_CLASSIFICATION"))
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc)

    with pytest.raises(EmailAIError):
        await svc.analyze_and_route(org_id=ORG, actor=ACTOR, email_id=email.id)

    updated = await CanonicalRepository(db["inbound_emails"], InboundEmail).get(email.id)
    assert updated.classification is None  # never partially applied
    activities = await CanonicalRepository(db["activities"], Activity).find_all({"subject_id": email.id})
    assert activities == []


@pytest.mark.asyncio
async def test_malformed_model_json_is_rejected_not_silently_defaulted(db, leadgen, suppression, reconciliation, outreach):
    llm = FakeLLM(content="not json at all")
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc)

    with pytest.raises(DecisionEngineError):
        await svc.analyze_and_route(org_id=ORG, actor=ACTOR, email_id=email.id)


@pytest.mark.asyncio
async def test_duplicate_analysis_does_not_re_invoke_the_model_or_reroute(db, leadgen, suppression, reconciliation, outreach):
    """The direct 'duplicate event -> no duplicate action' regression."""
    content = _classification(decision="SALES_LEAD", confidence=0.9, extracted_entities={"contact_email": "prospect@acme.com"})
    llm = FakeLLM(content=content)
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc)

    first = await svc.analyze_and_route(org_id=ORG, actor=ACTOR, email_id=email.id)
    second = await svc.analyze_and_route(org_id=ORG, actor=ACTOR, email_id=email.id)

    assert first == second
    assert len(llm.calls) == 1  # the model was only ever asked once

    lead_events = await CanonicalRepository(db["raw_lead_events"], RawLeadEvent).find_all({"source_type": "email", "source_record_id": email.id})
    assert len(lead_events) == 1  # not re-routed a second time


# --------------------------------------------------------------------------- follow-up (reuses Slice 7's governance)


async def _resumed_mailbox(db) -> None:
    await KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch)).resume(org_id=ORG, actor="system")
    await CanonicalRepository(db["mailboxes"], Mailbox).insert(
        Mailbox(id=MAILBOX_ID, org_id=ORG, created_by="system", updated_by="system", email_address="sales@torpedo.example", provider="smtp", credentials_id="cred-1")
    )


@pytest.mark.asyncio
async def test_followup_decision_sends_through_the_real_messaging_facade(db, leadgen, suppression, reconciliation, outreach, send_provider):
    await _resumed_mailbox(db)
    followup_content = _classification(decision="SEND_FOLLOWUP", confidence=0.9, actions=["send_response"])
    llm = FakeLLM(content=followup_content)
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc)

    async def fake_chat(self, *, messages, response_format=None):
        if any("draft business email" in str(m.get("content", "")).lower() for m in messages):
            return LLMResponse(content=json.dumps({"subject": "Re: quote", "body": BODY_OK, "confidence": 0.9}), model="fake-model")
        return LLMResponse(content=followup_content, model="fake-model")

    llm.chat = fake_chat.__get__(llm)

    decision = await svc.decide_followup(org_id=ORG, actor=ACTOR, email_id=email.id, mailbox_id=MAILBOX_ID)

    assert decision.decision == "SEND_FOLLOWUP"
    assert len(send_provider.calls) == 1
    assert send_provider.calls[0][0] == email.from_address


@pytest.mark.asyncio
async def test_shadow_mode_records_the_decision_but_never_sends(db, leadgen, suppression, reconciliation, outreach, send_provider):
    """Phase 14 continued — same shadow-mode discipline as the other four
    gated services, applied to the one send path in this module."""
    await _resumed_mailbox(db)
    followup_content = _classification(decision="SEND_FOLLOWUP", confidence=0.9, actions=["send_response"])
    llm = FakeLLM(content=followup_content)
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach, shadow_mode=True)
    email = await _ingested_email(svc)

    async def fake_chat(self, *, messages, response_format=None):
        if any("draft business email" in str(m.get("content", "")).lower() for m in messages):
            return LLMResponse(content=json.dumps({"subject": "Re: quote", "body": BODY_OK, "confidence": 0.9}), model="fake-model")
        return LLMResponse(content=followup_content, model="fake-model")

    llm.chat = fake_chat.__get__(llm)

    decision = await svc.decide_followup(org_id=ORG, actor=ACTOR, email_id=email.id, mailbox_id=MAILBOX_ID)
    assert decision.decision == "SEND_FOLLOWUP"
    assert send_provider.calls == []


@pytest.mark.asyncio
async def test_followup_is_never_sent_when_confidence_is_too_low(db, leadgen, suppression, reconciliation, outreach, send_provider):
    await _resumed_mailbox(db)
    llm = FakeLLM(content=_classification(decision="SEND_FOLLOWUP", confidence=0.2, actions=["send_response"]))
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc)

    await svc.decide_followup(org_id=ORG, actor=ACTOR, email_id=email.id, mailbox_id=MAILBOX_ID)
    assert send_provider.calls == []


@pytest.mark.asyncio
async def test_followup_is_never_sent_when_human_approval_is_required_even_at_high_confidence(db, leadgen, suppression, reconciliation, outreach, send_provider):
    await _resumed_mailbox(db)
    llm = FakeLLM(content=_classification(decision="SEND_FOLLOWUP", confidence=0.95, actions=["send_response"], requires_human_approval=True))
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc)

    await svc.decide_followup(org_id=ORG, actor=ACTOR, email_id=email.id, mailbox_id=MAILBOX_ID)
    assert send_provider.calls == []


@pytest.mark.asyncio
async def test_suppression_still_blocks_an_ai_selected_send(db, leadgen, suppression, reconciliation, outreach, send_provider):
    """The direct master-prompt §10 regression: AI decides to send, governance still
    enforces suppression regardless."""
    await _resumed_mailbox(db)
    await suppression.suppress(org_id=ORG, actor="system", email="prospect@acme.com", reason="prior unsubscribe", source="manual")
    followup_content = _classification(decision="SEND_FOLLOWUP", confidence=0.95, actions=["send_response"])
    llm = FakeLLM(content=followup_content)
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc, from_address="prospect@acme.com")

    async def fake_chat(self, *, messages, response_format=None):
        if any("draft business email" in str(m.get("content", "")).lower() for m in messages):
            return LLMResponse(content=json.dumps({"subject": "Re: quote", "body": BODY_OK, "confidence": 0.9}), model="fake-model")
        return LLMResponse(content=followup_content, model="fake-model")

    llm.chat = fake_chat.__get__(llm)

    await svc.decide_followup(org_id=ORG, actor=ACTOR, email_id=email.id, mailbox_id=MAILBOX_ID)

    assert send_provider.calls == []  # never reached the provider
    send_logs = await CanonicalRepository(db["send_log_entries"], SendLogEntry).find_all({"to_email": "prospect@acme.com"})
    assert len(send_logs) == 1
    assert send_logs[0].status == "suppressed"


@pytest.mark.asyncio
async def test_followup_is_idempotent_across_a_simulated_worker_restart(db, leadgen, suppression, reconciliation, outreach, send_provider):
    """Section 19's exact requirement: a worker restart (here: calling
    decide_followup twice) must not produce duplicate emails."""
    await _resumed_mailbox(db)
    followup_content = _classification(decision="SEND_FOLLOWUP", confidence=0.9, actions=["send_response"])
    llm = FakeLLM(content=followup_content)
    svc = _service(db, llm, leadgen, suppression, reconciliation, outreach)
    email = await _ingested_email(svc)

    async def fake_chat(self, *, messages, response_format=None):
        if any("draft business email" in str(m.get("content", "")).lower() for m in messages):
            return LLMResponse(content=json.dumps({"subject": "Re: quote", "body": BODY_OK, "confidence": 0.9}), model="fake-model")
        return LLMResponse(content=followup_content, model="fake-model")

    llm.chat = fake_chat.__get__(llm)

    await svc.decide_followup(org_id=ORG, actor=ACTOR, email_id=email.id, mailbox_id=MAILBOX_ID)
    await svc.decide_followup(org_id=ORG, actor=ACTOR, email_id=email.id, mailbox_id=MAILBOX_ID)  # simulated restart, re-decided

    assert len(send_provider.calls) == 1  # MessagingFacade's idempotency_key deduped the second attempt
