"""
Phase 14 — EventDetectionService. Every detector reuses an existing,
already-tested deterministic candidate query (`OperationsAIService.detect_triggers()`,
`InvoiceService.list_open()`, etc.) — these tests prove the *idempotent Event
creation* around each one, not re-prove the underlying detector's own logic.
"""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import DecisionEngine
from app.ai.llm import LLMResponse
from app.ai.tools import ToolRegistry
from app.emailai.models import InboundEmail
from app.finance.models import Bill, GstDetails, Invoice, LineItem, Payment, ReconciliationRecord
from app.finance.sequence import SequenceService
from app.finance.service import BillService, InvoiceService, ReconciliationService
from app.identity.facets import LeadState
from app.identity.models import Account, Person
from app.leadgen.models import LeadEnrollment
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.outreach.models import Mailbox
from app.panel.ai_operations import OperationsAIService
from app.panel.inactivity import StudyInactivityService
from app.panel.models import Allocation, Survey, SurveyResponse
from app.panel.service import SurveyService
from app.scheduler.detectors import EventDetectionService
from app.scheduler.models import Event

ORG = "org-A"
CURRENCY = "INR"
GST = GstDetails(place_of_supply="KA")


class FakeLLM:
    def __init__(self, content: str = '{"decision": "NO_ACTION", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "LOW", "entities": [], "actions": [], "follow_up_at": null, "requires_human_approval": false, "extracted_entities": {}}'):
        self._content = content

    async def chat(self, *, messages, response_format=None):
        return LLMResponse(content=self._content, model="fake-model")


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def activities(db) -> CanonicalRepository[Activity]:
    return CanonicalRepository(db["activities"], Activity)


@pytest.fixture
def events(db) -> CanonicalRepository[Event]:
    return CanonicalRepository(db["events"], Event)


@pytest.fixture
def survey_service(db, activities) -> SurveyService:
    return SurveyService(CanonicalRepository(db["surveys"], Survey), activities)


@pytest.fixture
def operations_ai(db, survey_service, activities) -> OperationsAIService:
    engine = DecisionEngine(FakeLLM(), ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    inactivity = StudyInactivityService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), activities)
    return OperationsAIService(engine, survey_service, inactivity, CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["survey_responses"], SurveyResponse), activities, CanonicalRepository(db["ai_proposals"], AiProposal))


@pytest.fixture
def sequences(db) -> SequenceService:
    return SequenceService(db["finance_sequences"])


@pytest.fixture
def invoice_service(db, sequences, activities) -> InvoiceService:
    return InvoiceService(CanonicalRepository(db["invoices"], Invoice), sequences, activities)


@pytest.fixture
def bill_service(db, sequences, activities) -> BillService:
    return BillService(CanonicalRepository(db["bills"], Bill), sequences, activities)


@pytest.fixture
def reconciliation_service(db) -> ReconciliationService:
    return ReconciliationService(CanonicalRepository(db["reconciliation_records"], ReconciliationRecord), CanonicalRepository(db["payments"], Payment))


@pytest.fixture
def detection(db, operations_ai, invoice_service, bill_service, reconciliation_service, events) -> EventDetectionService:
    return EventDetectionService(
        events=events, operations_ai=operations_ai, invoice_service=invoice_service, bill_service=bill_service,
        reconciliation_service=reconciliation_service, lead_states=CanonicalRepository(db["lead_states"], LeadState),
        accounts=CanonicalRepository(db["accounts"], Account), people=CanonicalRepository(db["people"], Person),
        inbound_emails=CanonicalRepository(db["inbound_emails"], InboundEmail), lead_enrollments=CanonicalRepository(db["lead_enrollments"], LeadEnrollment),
        mailboxes=CanonicalRepository(db["mailboxes"], Mailbox),
    )


def _line_items(unit_price_minor=50_000):
    return [LineItem(description="research project", quantity=1, unit_price_minor=unit_price_minor, gst_rate_bps=1800)]


# --------------------------------------------------------------------------- survey_operations_trigger


@pytest.mark.asyncio
async def test_survey_operations_detector_creates_one_event_per_trigger(db, detection, survey_service):
    survey = await survey_service.create_survey(org_id=ORG, actor="system", provider="cint", external_id="s1", quota_remaining=5, cpi=Money(amount_minor=500, currency=CURRENCY), conversion_rate=0.1)
    await survey_service.set_eligibility(org_id=ORG, actor="system", survey_id=survey.id, is_active_in_pool=True, activated_at=None)

    created = await detection.detect_survey_operations(org_id=ORG)
    assert len(created) == 1
    assert created[0].event_type == "survey_operations_trigger"
    assert created[0].entity_id == survey.id
    # A freshly-eligible survey with zero allocations ever also matches
    # no_traffic_7_days, which detect_triggers() prioritizes ahead of
    # low_conversion ("no traffic is the most urgent signal") — this test
    # proves one Event gets created per triggered survey, not which of the
    # two real conditions detect_triggers() itself chose to report first.
    assert created[0].payload["trigger_type"] in ("no_traffic_7_days", "low_conversion")


@pytest.mark.asyncio
async def test_survey_operations_detector_is_idempotent_same_day(db, detection, survey_service):
    survey = await survey_service.create_survey(org_id=ORG, actor="system", provider="cint", external_id="s1", quota_remaining=5, cpi=Money(amount_minor=500, currency=CURRENCY), conversion_rate=0.1)
    await survey_service.set_eligibility(org_id=ORG, actor="system", survey_id=survey.id, is_active_in_pool=True, activated_at=None)

    first = await detection.detect_survey_operations(org_id=ORG)
    second = await detection.detect_survey_operations(org_id=ORG)
    assert len(first) == 1
    assert second == []  # already queued for today, not re-created


# --------------------------------------------------------------------------- ar_followup_due / ap_followup_due


@pytest.mark.asyncio
async def test_ar_followup_detector_creates_event_for_open_invoice(db, detection, invoice_service):
    invoice = await invoice_service.create_invoice(org_id=ORG, actor="alice", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    await invoice_service._invoices.update(invoice.id, invoice.version, {"status": "sent"}, updated_by="alice")

    created = await detection.detect_ar_followup(org_id=ORG)
    assert len(created) == 1
    assert created[0].event_type == "ar_followup_due"
    assert created[0].entity_id == invoice.id


@pytest.mark.asyncio
async def test_ar_followup_detector_ignores_draft_invoices(db, detection, invoice_service):
    await invoice_service.create_invoice(org_id=ORG, actor="alice", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    created = await detection.detect_ar_followup(org_id=ORG)
    assert created == []


@pytest.mark.asyncio
async def test_ap_followup_detector_creates_event_for_open_bill(db, detection, bill_service):
    bill = await bill_service.create_bill(org_id=ORG, actor="alice", vendor_account_id="vendor-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    await bill_service._bills.update(bill.id, bill.version, {"status": "approved"}, updated_by="alice")

    created = await detection.detect_ap_followup(org_id=ORG)
    assert len(created) == 1
    assert created[0].event_type == "ap_followup_due"
    assert created[0].entity_id == bill.id


# --------------------------------------------------------------------------- reconciliation_unmatched


@pytest.mark.asyncio
async def test_reconciliation_detector_creates_event_for_unmatched_record(db, detection, reconciliation_service):
    record = await reconciliation_service.record_external_entry(org_id=ORG, actor="alice", source="bank_feed", external_reference="txn-1", amount=Money(amount_minor=50_000, currency=CURRENCY))
    created = await detection.detect_reconciliation_unmatched(org_id=ORG)
    assert len(created) == 1
    assert created[0].entity_id == record.id


# --------------------------------------------------------------------------- lead_icp_evaluation_due


@pytest.mark.asyncio
async def test_lead_icp_detector_only_fires_for_qualified_leads_without_prior_evaluation(db, detection):
    lead_states = CanonicalRepository(db["lead_states"], LeadState)
    qualified = await lead_states.insert(LeadState(org_id=ORG, created_by="system", updated_by="system", person_id="p1", source_type="gsc_ai", state="qualified"))
    await lead_states.insert(LeadState(org_id=ORG, created_by="system", updated_by="system", person_id="p2", source_type="gsc_ai", state="discovered"))  # not yet qualified — not offered

    created = await detection.detect_lead_icp_evaluation(org_id=ORG)
    assert len(created) == 1
    assert created[0].entity_id == qualified.id


@pytest.mark.asyncio
async def test_lead_icp_detector_skips_leads_already_evaluated(db, detection):
    lead_states = CanonicalRepository(db["lead_states"], LeadState)
    await lead_states.insert(LeadState(org_id=ORG, created_by="system", updated_by="system", person_id="p1", source_type="gsc_ai", state="qualified", ai_decision_subject_id="lead-1"))

    created = await detection.detect_lead_icp_evaluation(org_id=ORG)
    assert created == []


@pytest.mark.asyncio
async def test_lead_icp_detector_builds_real_context_from_account_and_person(db, detection):
    accounts = CanonicalRepository(db["accounts"], Account)
    people = CanonicalRepository(db["people"], Person)
    account = await accounts.insert(Account(org_id=ORG, created_by="system", updated_by="system", name="Acme", name_normalized="acme", domain="acme.example", industry="market research"))
    person = await people.insert(Person(org_id=ORG, created_by="system", updated_by="system", title="VP Insights"))
    lead_states = CanonicalRepository(db["lead_states"], LeadState)
    lead = await lead_states.insert(LeadState(org_id=ORG, created_by="system", updated_by="system", person_id=person.id, account_id=account.id, source_type="gsc_ai", state="qualified"))

    created = await detection.detect_lead_icp_evaluation(org_id=ORG)
    assert len(created) == 1
    ctx = created[0].payload["prospect_context"]
    assert ctx["industry"] == "market research"
    assert ctx["company_domain"] == "acme.example"
    assert ctx["title"] == "VP Insights"


# --------------------------------------------------------------------------- lead_conversion_due


@pytest.mark.asyncio
async def test_lead_conversion_detector_only_fires_for_qualified_leads_with_a_real_account(db, detection):
    lead_states = CanonicalRepository(db["lead_states"], LeadState)
    eligible = await lead_states.insert(LeadState(org_id=ORG, created_by="system", updated_by="system", person_id="p1", source_type="gsc_ai", state="qualified", account_id="acct-1"))
    await lead_states.insert(LeadState(org_id=ORG, created_by="system", updated_by="system", person_id="p2", source_type="gsc_ai", state="qualified", account_id=None))  # no account
    await lead_states.insert(LeadState(org_id=ORG, created_by="system", updated_by="system", person_id="p3", source_type="gsc_ai", state="discovered", account_id="acct-2"))  # not yet qualified

    created = await detection.detect_lead_conversion(org_id=ORG)
    assert len(created) == 1
    assert created[0].entity_id == eligible.id


@pytest.mark.asyncio
async def test_lead_conversion_detector_skips_leads_already_decided(db, detection):
    lead_states = CanonicalRepository(db["lead_states"], LeadState)
    await lead_states.insert(LeadState(org_id=ORG, created_by="system", updated_by="system", person_id="p1", source_type="gsc_ai", state="qualified", account_id="acct-1", ai_conversion_decision_subject_id="lead-1"))

    created = await detection.detect_lead_conversion(org_id=ORG)
    assert created == []


# --------------------------------------------------------------------------- email_classification_due


@pytest.mark.asyncio
async def test_email_classification_detector_only_fires_for_unclassified_emails(db, detection):
    emails = CanonicalRepository(db["inbound_emails"], InboundEmail)
    unclassified = await emails.insert(InboundEmail(org_id=ORG, created_by="system", updated_by="system", provider="gmail", provider_message_id="m1", from_address="a@x.com", to_address="b@x.com", subject="hi", body="hi"))
    await emails.insert(InboundEmail(org_id=ORG, created_by="system", updated_by="system", provider="gmail", provider_message_id="m2", from_address="a@x.com", to_address="b@x.com", subject="hi", body="hi", classification="SPAM"))

    created = await detection.detect_email_classification(org_id=ORG)
    assert len(created) == 1
    assert created[0].entity_id == unclassified.id


# --------------------------------------------------------------------------- outreach_followup_due


@pytest.mark.asyncio
async def test_outreach_followup_detector_requires_an_active_mailbox(db, detection):
    enrollments = CanonicalRepository(db["lead_enrollments"], LeadEnrollment)
    await enrollments.insert(LeadEnrollment(org_id=ORG, created_by="system", updated_by="system", lead_state_id="lead-1", person_id="p1", brand_id="brand-1"))

    created = await detection.detect_outreach_followup(org_id=ORG)
    assert created == []  # no configured mailbox — never a fabricated mailbox_id


@pytest.mark.asyncio
async def test_outreach_followup_detector_fires_for_a_stale_non_terminal_enrollment(db, detection):
    await CanonicalRepository(db["mailboxes"], Mailbox).insert(Mailbox(org_id=ORG, created_by="system", updated_by="system", email_address="sales@torpedo.example", provider="smtp", credentials_id="cred-1"))
    enrollments = CanonicalRepository(db["lead_enrollments"], LeadEnrollment)
    enrollment = await enrollments.insert(LeadEnrollment(org_id=ORG, created_by="system", updated_by="system", lead_state_id="lead-1", person_id="p1", brand_id="brand-1"))

    as_of = datetime.now(timezone.utc) + timedelta(days=4)  # past the 3-day staleness window
    created = await detection.detect_outreach_followup(org_id=ORG, as_of=as_of)
    assert len(created) == 1
    assert created[0].entity_id == enrollment.id
    assert created[0].payload["mailbox_id"]


@pytest.mark.asyncio
async def test_outreach_followup_detector_skips_recently_updated_enrollments(db, detection):
    await CanonicalRepository(db["mailboxes"], Mailbox).insert(Mailbox(org_id=ORG, created_by="system", updated_by="system", email_address="sales@torpedo.example", provider="smtp", credentials_id="cred-1"))
    enrollments = CanonicalRepository(db["lead_enrollments"], LeadEnrollment)
    await enrollments.insert(LeadEnrollment(org_id=ORG, created_by="system", updated_by="system", lead_state_id="lead-1", person_id="p1", brand_id="brand-1"))

    created = await detection.detect_outreach_followup(org_id=ORG)  # as_of defaults to now — just created, not stale yet
    assert created == []


@pytest.mark.asyncio
async def test_outreach_followup_detector_never_fires_for_stopped_enrollments(db, detection):
    await CanonicalRepository(db["mailboxes"], Mailbox).insert(Mailbox(org_id=ORG, created_by="system", updated_by="system", email_address="sales@torpedo.example", provider="smtp", credentials_id="cred-1"))
    enrollments = CanonicalRepository(db["lead_enrollments"], LeadEnrollment)
    await enrollments.insert(LeadEnrollment(org_id=ORG, created_by="system", updated_by="system", lead_state_id="lead-1", person_id="p1", brand_id="brand-1", sequence_state="STOPPED"))

    as_of = datetime.now(timezone.utc) + timedelta(days=4)
    created = await detection.detect_outreach_followup(org_id=ORG, as_of=as_of)
    assert created == []


# --------------------------------------------------------------------------- run_all


@pytest.mark.asyncio
async def test_run_all_aggregates_counts_across_every_detector(db, detection, invoice_service):
    await invoice_service.create_invoice(org_id=ORG, actor="alice", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    invoice = (await invoice_service._invoices.find_all({}))[0]
    await invoice_service._invoices.update(invoice.id, invoice.version, {"status": "sent"}, updated_by="alice")

    counts = await detection.run_all(org_id=ORG)
    assert counts["ar_followup_due"] == 1
    assert counts["survey_operations_trigger"] == 0
    assert set(counts.keys()) == {
        "survey_operations_trigger", "ar_followup_due", "ap_followup_due", "reconciliation_unmatched",
        "lead_icp_evaluation_due", "lead_conversion_due", "email_classification_due", "outreach_followup_due",
        "email_ingestion_due",
    }
