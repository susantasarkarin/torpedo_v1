"""
Phase 14 — EventOrchestrator. This suite proves the *orchestration mechanics*
(single-flight claiming, recoverable-failure retry, max-attempts exhaustion,
correct dispatch-by-event_type) — not each AI service's own decision logic,
which is already exhaustively covered in test_finance_ai.py,
test_leadgen_ai_service.py, test_emailai_service.py, test_leadgen_ai_outreach.py,
and test_panel_ai_operations.py. Each AI-service dependency here is a minimal
fake implementing only the one method the orchestrator actually calls, so a
version conflict or a retry can be provoked directly, deterministically,
without needing a real DecisionEngine/LLM at all.
"""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import DecisionEngineError
from app.ai.llm import LLMUnavailable
from app.finance.ai_finance import AIFinanceError
from app.models.base import CanonicalRepository, VersionConflict
from app.panel.ai_operations import OperationsAIError
from app.panel.providers import SurveyProviderUnavailable
from app.scheduler.models import FAILED, MAX_ATTEMPTS, PENDING, PROCESSED, PROCESSING, Event
from app.scheduler.orchestrator import EventOrchestrator

ORG = "org-A"


class _Decision:
    def __init__(self, decision="NO_ACTION", confidence=0.9):
        self.decision = decision
        self.confidence = confidence


class FakeOperationsAI:
    def __init__(self, *, raises=None):
        self._raises = raises
        self.calls: list[dict] = []

    async def evaluate_and_act(self, *, org_id, actor, survey_id, trigger_type, provider=None):
        self.calls.append({"survey_id": survey_id, "trigger_type": trigger_type})
        if self._raises:
            raise self._raises
        return _Decision("NO_ACTION")


class FakeFinanceAI:
    def __init__(self, *, raises=None, match_payment=None):
        self._raises = raises
        self._match_payment = match_payment
        self.calls: list[dict] = []

    async def decide_ar_followup(self, *, org_id, actor, invoice_id):
        self.calls.append({"invoice_id": invoice_id})
        if self._raises:
            raise self._raises
        return _Decision("REMINDER")

    async def decide_ap_followup(self, *, org_id, actor, bill_id):
        self.calls.append({"bill_id": bill_id})
        if self._raises:
            raise self._raises
        return _Decision("SCHEDULE_PAYMENT")

    async def match_payment_to_invoice(self, *, org_id, actor, reconciliation_record_id, allow_overpayment=False):
        self.calls.append({"record_id": reconciliation_record_id})
        if self._raises:
            raise self._raises
        return _Decision("NO_MATCH"), self._match_payment


class FakeLeadGenAI:
    def __init__(self, *, raises=None):
        self._raises = raises
        self.calls: list[dict] = []

    async def evaluate_icp(self, *, org_id, actor, lead_state_id, prospect_context):
        self.calls.append({"lead_state_id": lead_state_id, "context": prospect_context})
        if self._raises:
            raise self._raises
        return _Decision("RESEARCH")


class FakeEmailAI:
    def __init__(self, *, raises=None):
        self._raises = raises
        self.calls: list[dict] = []
        self.ingested: list[dict] = []

    async def analyze_and_route(self, *, org_id, actor, email_id):
        self.calls.append({"email_id": email_id})
        if self._raises:
            raise self._raises
        return _Decision("SPAM")

    async def ingest_email(self, *, org_id, actor, provider, provider_message_id, from_address, to_address, subject, body, thread_id=None):
        self.ingested.append({"provider": provider, "provider_message_id": provider_message_id, "from_address": from_address})

        class _Email:
            id = f"email-{len(self.ingested)}"

        return _Email()


class FakeOutreachAI:
    def __init__(self, *, raises=None):
        self._raises = raises
        self.calls: list[dict] = []

    async def decide_and_act(self, *, org_id, actor, enrollment_id, mailbox_id):
        self.calls.append({"enrollment_id": enrollment_id, "mailbox_id": mailbox_id})
        if self._raises:
            raise self._raises
        return _Decision("NURTURE")


class FakeConversionAI:
    def __init__(self, *, raises=None, opportunity=None):
        self._raises = raises
        self._opportunity = opportunity
        self.calls: list[dict] = []

    async def evaluate_and_convert(self, *, org_id, actor, lead_state_id):
        self.calls.append({"lead_state_id": lead_state_id})
        if self._raises:
            raise self._raises
        return _Decision("HOLD"), self._opportunity


class FakeEmailIngestionProvider:
    def __init__(self, *, raises=None, raw_emails=None):
        self._raises = raises
        self._raw_emails = raw_emails or []
        self.calls: list[dict] = []

    async def fetch_new(self, *, mailbox_id, since_provider_message_id=None):
        self.calls.append({"mailbox_id": mailbox_id})
        if self._raises:
            raise self._raises
        return self._raw_emails


class _NoOpDetection:
    async def run_all(self, *, org_id, as_of=None):
        return {}


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def events(db) -> CanonicalRepository[Event]:
    return CanonicalRepository(db["events"], Event)


def _orchestrator(events, *, operations_ai=None, finance_ai=None, leadgen_ai=None, email_ai=None, outreach_ai=None, conversion_ai=None, email_ingestion_provider=None) -> EventOrchestrator:
    return EventOrchestrator(
        events=events, detection=_NoOpDetection(),
        operations_ai=operations_ai or FakeOperationsAI(), finance_ai=finance_ai or FakeFinanceAI(),
        leadgen_ai=leadgen_ai or FakeLeadGenAI(), email_ai=email_ai or FakeEmailAI(), outreach_ai=outreach_ai or FakeOutreachAI(),
        conversion_ai=conversion_ai or FakeConversionAI(),
        email_ingestion_provider=email_ingestion_provider or FakeEmailIngestionProvider(),
        survey_provider=None,
    )


async def _pending_event(events, *, event_type, entity_type, entity_id, payload=None) -> Event:
    return await events.insert(Event(org_id=ORG, created_by="system", updated_by="system", event_type=event_type, entity_type=entity_type, entity_id=entity_id, occurred_at=datetime.now(timezone.utc), dedupe_key=f"{event_type}:{entity_id}", payload=payload or {}))


class _LosesTheClaimRaceOnce:
    """Wraps a real CanonicalRepository[Event] and raises VersionConflict on
    the very first `.update()` call — simulating a concurrent tick that won
    the claim race a moment earlier — then delegates every other call to the
    real repository untouched. The atomic guarantee itself
    (`find_one_and_update` with a version-matched filter) is already proven
    generically for every entity in this codebase; this proves specifically
    that EventOrchestrator's own catch-and-skip around that guarantee works."""

    def __init__(self, real: CanonicalRepository[Event]):
        self._real = real
        self._raised = False

    async def find_all(self, query):
        return await self._real.find_all(query)

    async def get(self, doc_id):
        return await self._real.get(doc_id)

    async def update(self, doc_id, expected_version, changes, *, updated_by):
        if not self._raised:
            self._raised = True
            raise VersionConflict("lost the claim race")
        return await self._real.update(doc_id, expected_version, changes, updated_by=updated_by)


# --------------------------------------------------------------------------- dispatch coverage


@pytest.mark.asyncio
async def test_survey_operations_event_dispatches_with_trigger_type_from_payload(db, events):
    operations_ai = FakeOperationsAI()
    await _pending_event(events, event_type="survey_operations_trigger", entity_type="survey", entity_id="survey-1", payload={"trigger_type": "low_conversion"})
    orchestrator = _orchestrator(events, operations_ai=operations_ai)

    outcome = await orchestrator.process_pending(org_id=ORG)
    assert outcome == {"processed": 1, "failed": 0, "skipped": 0}
    assert operations_ai.calls == [{"survey_id": "survey-1", "trigger_type": "low_conversion"}]

    stored = (await events.find_all({}))[0]
    assert stored.processing_status == PROCESSED
    assert stored.result == {"decision": "NO_ACTION", "confidence": 0.9}


@pytest.mark.asyncio
async def test_ar_followup_event_dispatches_to_finance_ai(db, events):
    finance_ai = FakeFinanceAI()
    await _pending_event(events, event_type="ar_followup_due", entity_type="invoice", entity_id="inv-1")
    orchestrator = _orchestrator(events, finance_ai=finance_ai)

    await orchestrator.process_pending(org_id=ORG)
    assert finance_ai.calls == [{"invoice_id": "inv-1"}]


@pytest.mark.asyncio
async def test_ap_followup_event_dispatches_to_finance_ai(db, events):
    finance_ai = FakeFinanceAI()
    await _pending_event(events, event_type="ap_followup_due", entity_type="bill", entity_id="bill-1")
    orchestrator = _orchestrator(events, finance_ai=finance_ai)

    await orchestrator.process_pending(org_id=ORG)
    assert finance_ai.calls == [{"bill_id": "bill-1"}]


@pytest.mark.asyncio
async def test_reconciliation_event_result_includes_payment_id_when_matched(db, events):
    class _Payment:
        id = "payment-1"

    finance_ai = FakeFinanceAI(match_payment=_Payment())
    await _pending_event(events, event_type="reconciliation_unmatched", entity_type="reconciliation_record", entity_id="rec-1")
    orchestrator = _orchestrator(events, finance_ai=finance_ai)

    await orchestrator.process_pending(org_id=ORG)
    stored = (await events.find_all({}))[0]
    assert stored.result["payment_id"] == "payment-1"


@pytest.mark.asyncio
async def test_lead_icp_event_dispatches_with_prospect_context_from_payload(db, events):
    leadgen_ai = FakeLeadGenAI()
    await _pending_event(events, event_type="lead_icp_evaluation_due", entity_type="lead_state", entity_id="lead-1", payload={"prospect_context": {"industry": "market research"}})
    orchestrator = _orchestrator(events, leadgen_ai=leadgen_ai)

    await orchestrator.process_pending(org_id=ORG)
    assert leadgen_ai.calls == [{"lead_state_id": "lead-1", "context": {"industry": "market research"}}]


@pytest.mark.asyncio
async def test_email_classification_event_dispatches_to_email_ai(db, events):
    email_ai = FakeEmailAI()
    await _pending_event(events, event_type="email_classification_due", entity_type="inbound_email", entity_id="email-1")
    orchestrator = _orchestrator(events, email_ai=email_ai)

    await orchestrator.process_pending(org_id=ORG)
    assert email_ai.calls == [{"email_id": "email-1"}]


@pytest.mark.asyncio
async def test_outreach_followup_event_dispatches_with_mailbox_id_from_payload(db, events):
    outreach_ai = FakeOutreachAI()
    await _pending_event(events, event_type="outreach_followup_due", entity_type="lead_enrollment", entity_id="enr-1", payload={"mailbox_id": "mailbox-1"})
    orchestrator = _orchestrator(events, outreach_ai=outreach_ai)

    await orchestrator.process_pending(org_id=ORG)
    assert outreach_ai.calls == [{"enrollment_id": "enr-1", "mailbox_id": "mailbox-1"}]


@pytest.mark.asyncio
async def test_lead_conversion_event_dispatches_to_conversion_ai(db, events):
    conversion_ai = FakeConversionAI()
    await _pending_event(events, event_type="lead_conversion_due", entity_type="lead_state", entity_id="lead-1")
    orchestrator = _orchestrator(events, conversion_ai=conversion_ai)

    await orchestrator.process_pending(org_id=ORG)
    assert conversion_ai.calls == [{"lead_state_id": "lead-1"}]


@pytest.mark.asyncio
async def test_lead_conversion_event_result_includes_opportunity_id_when_converted(db, events):
    class _Opportunity:
        id = "opp-1"

    conversion_ai = FakeConversionAI(opportunity=_Opportunity())
    await _pending_event(events, event_type="lead_conversion_due", entity_type="lead_state", entity_id="lead-1")
    orchestrator = _orchestrator(events, conversion_ai=conversion_ai)

    await orchestrator.process_pending(org_id=ORG)
    stored = (await events.find_all({}))[0]
    assert stored.result["opportunity_id"] == "opp-1"


@pytest.mark.asyncio
async def test_email_ingestion_event_dispatches_to_the_provider_and_ingests_each_raw_email(db, events):
    class _RawEmail:
        provider_message_id = "msg-1"
        from_address = "lead@example.com"
        to_address = "sales@torpedo.example"
        subject = "Hi"
        body = "Interested"
        thread_id = None

    provider = FakeEmailIngestionProvider(raw_emails=[_RawEmail()])
    email_ai = FakeEmailAI()
    await _pending_event(events, event_type="email_ingestion_due", entity_type="mailbox", entity_id="mailbox-1", payload={"provider": "gmail"})
    orchestrator = _orchestrator(events, email_ai=email_ai, email_ingestion_provider=provider)

    await orchestrator.process_pending(org_id=ORG)
    assert provider.calls == [{"mailbox_id": "mailbox-1"}]
    assert email_ai.ingested == [{"provider": "gmail", "provider_message_id": "msg-1", "from_address": "lead@example.com"}]

    stored = (await events.find_all({}))[0]
    assert stored.result["ingested_count"] == 1
    assert stored.processing_status == PROCESSED


@pytest.mark.asyncio
async def test_email_provider_unavailable_is_recoverable_not_a_crash(db, events):
    from app.emailai.providers import EmailProviderUnavailable

    provider = FakeEmailIngestionProvider(raises=EmailProviderUnavailable("no credentials"))
    await _pending_event(events, event_type="email_ingestion_due", entity_type="mailbox", entity_id="mailbox-1", payload={"provider": "gmail"})
    orchestrator = _orchestrator(events, email_ingestion_provider=provider)

    outcome = await orchestrator.process_pending(org_id=ORG)
    assert outcome == {"processed": 0, "failed": 1, "skipped": 0}
    stored = (await events.find_all({}))[0]
    assert stored.processing_status == FAILED
    assert "no credentials" in stored.last_error


# --------------------------------------------------------------------------- failure/retry mechanics


@pytest.mark.asyncio
async def test_recoverable_error_marks_event_failed_and_increments_attempts(db, events):
    finance_ai = FakeFinanceAI(raises=LLMUnavailable("no GPU credential configured"))
    await _pending_event(events, event_type="ar_followup_due", entity_type="invoice", entity_id="inv-1")
    orchestrator = _orchestrator(events, finance_ai=finance_ai)

    outcome = await orchestrator.process_pending(org_id=ORG)
    assert outcome == {"processed": 0, "failed": 1, "skipped": 0}

    stored = (await events.find_all({}))[0]
    assert stored.processing_status == FAILED
    assert stored.attempts == 1
    assert "no GPU credential" in stored.last_error


@pytest.mark.asyncio
async def test_failed_event_is_retried_on_a_later_cycle(db, events):
    finance_ai = FakeFinanceAI(raises=DecisionEngineError("malformed decision"))
    await _pending_event(events, event_type="ar_followup_due", entity_type="invoice", entity_id="inv-1")
    orchestrator = _orchestrator(events, finance_ai=finance_ai)

    await orchestrator.process_pending(org_id=ORG)
    await orchestrator.process_pending(org_id=ORG)  # simulated next tick

    stored = (await events.find_all({}))[0]
    assert stored.attempts == 2
    assert stored.processing_status == FAILED


@pytest.mark.asyncio
async def test_event_exceeding_max_attempts_is_not_retried(db, events):
    finance_ai = FakeFinanceAI(raises=AIFinanceError("still broken"))
    event = await _pending_event(events, event_type="ar_followup_due", entity_type="invoice", entity_id="inv-1")
    await events.update(event.id, event.version, {"processing_status": FAILED, "attempts": MAX_ATTEMPTS}, updated_by="system")
    orchestrator = _orchestrator(events, finance_ai=finance_ai)

    outcome = await orchestrator.process_pending(org_id=ORG)
    assert outcome == {"processed": 0, "failed": 0, "skipped": 0}
    assert finance_ai.calls == []  # never even attempted — exhausted


@pytest.mark.asyncio
async def test_survey_provider_unavailable_and_operations_error_are_both_recoverable(db, events):
    for exc in (SurveyProviderUnavailable("no credentials"), OperationsAIError("bad action")):
        operations_ai = FakeOperationsAI(raises=exc)
        event = await _pending_event(events, event_type="survey_operations_trigger", entity_type="survey", entity_id=f"s-{exc.__class__.__name__}", payload={"trigger_type": "low_conversion"})
        orchestrator = _orchestrator(events, operations_ai=operations_ai)
        await orchestrator.process_pending(org_id=ORG)
        stored = await events.get(event.id)
        assert stored.processing_status == FAILED


# --------------------------------------------------------------------------- single-flight claiming


@pytest.mark.asyncio
async def test_an_event_already_processing_is_invisible_to_the_next_ticks_candidate_query(db, events):
    """An event another still-in-flight tick already claimed (PROCESSING) is
    not PENDING or FAILED, so a concurrent/overlapping tick's own candidate
    query never sees it at all — never touched twice by two ticks running
    close together."""
    operations_ai = FakeOperationsAI()
    event = await _pending_event(events, event_type="survey_operations_trigger", entity_type="survey", entity_id="survey-1", payload={"trigger_type": "low_conversion"})
    await events.update(event.id, event.version, {"processing_status": PROCESSING}, updated_by="system")
    orchestrator = _orchestrator(events, operations_ai=operations_ai)

    outcome = await orchestrator.process_pending(org_id=ORG)
    assert outcome == {"processed": 0, "failed": 0, "skipped": 0}
    assert operations_ai.calls == []


@pytest.mark.asyncio
async def test_losing_the_claim_race_is_counted_as_skipped_not_failed(db, events):
    """Exercises EventOrchestrator's own VersionConflict catch directly: a
    real race (two ticks reading the same PENDING event before either claims
    it) surfaces as exactly this exception from `CanonicalRepository.update()`."""
    operations_ai = FakeOperationsAI()
    await _pending_event(events, event_type="survey_operations_trigger", entity_type="survey", entity_id="survey-1", payload={"trigger_type": "low_conversion"})
    racing_events = _LosesTheClaimRaceOnce(events)
    orchestrator = _orchestrator(racing_events, operations_ai=operations_ai)

    outcome = await orchestrator.process_pending(org_id=ORG)
    assert outcome == {"processed": 0, "failed": 0, "skipped": 1}
    assert operations_ai.calls == []  # never even dispatched — the claim itself was lost


@pytest.mark.asyncio
async def test_process_pending_only_considers_pending_and_failed_events(db, events):
    operations_ai = FakeOperationsAI()
    await _pending_event(events, event_type="survey_operations_trigger", entity_type="survey", entity_id="s1", payload={"trigger_type": "low_conversion"})
    processed_already = await _pending_event(events, event_type="survey_operations_trigger", entity_type="survey", entity_id="s2", payload={"trigger_type": "low_conversion"})
    await events.update(processed_already.id, processed_already.version, {"processing_status": PROCESSED, "result": {"decision": "NO_ACTION"}}, updated_by="system")
    orchestrator = _orchestrator(events, operations_ai=operations_ai)

    outcome = await orchestrator.process_pending(org_id=ORG)
    assert outcome["processed"] == 1
    assert operations_ai.calls == [{"survey_id": "s1", "trigger_type": "low_conversion"}]


# --------------------------------------------------------------------------- stuck-PROCESSING recovery (Phase 16 failure/recovery audit)


@pytest.mark.asyncio
async def test_a_stale_processing_event_is_reclaimed_and_processed(db, events):
    """An event orphaned in PROCESSING by a crash (OOM kill, an unexpected
    non-recoverable exception, a VM restart between claim and terminal
    write) must not stay stuck forever — it was never PENDING/FAILED again,
    so nothing else would ever pick it up. Backdating updated_at simulates
    the crash having happened STUCK_PROCESSING_THRESHOLD ago."""
    from app.scheduler.models import STUCK_PROCESSING_THRESHOLD

    operations_ai = FakeOperationsAI()
    event = await _pending_event(events, event_type="survey_operations_trigger", entity_type="survey", entity_id="survey-1", payload={"trigger_type": "low_conversion"})
    stale_at = datetime.now(timezone.utc) - STUCK_PROCESSING_THRESHOLD - timedelta(minutes=1)
    await events._collection.update_one({"_id": event.id}, {"$set": {"processing_status": PROCESSING, "updated_at": stale_at}})
    orchestrator = _orchestrator(events, operations_ai=operations_ai)

    outcome = await orchestrator.process_pending(org_id=ORG)
    assert outcome == {"processed": 1, "failed": 0, "skipped": 0}
    assert operations_ai.calls == [{"survey_id": "survey-1", "trigger_type": "low_conversion"}]

    reclaimed = await events.get(event.id)
    assert reclaimed.processing_status == PROCESSED


@pytest.mark.asyncio
async def test_a_recently_processing_event_is_not_reclaimed(db, events):
    """The reclaim window only widens the candidate set for events old enough
    to be genuinely orphaned — a PROCESSING event from moments ago (this
    same tick, or a real concurrent worker) must stay untouched, exactly as
    test_an_event_already_processing_is_invisible_to_the_next_ticks_candidate_query
    already proves for the zero-age case; this proves it holds just under
    the threshold too, not only at age zero."""
    from app.scheduler.models import STUCK_PROCESSING_THRESHOLD

    operations_ai = FakeOperationsAI()
    event = await _pending_event(events, event_type="survey_operations_trigger", entity_type="survey", entity_id="survey-1", payload={"trigger_type": "low_conversion"})
    almost_stale_at = datetime.now(timezone.utc) - STUCK_PROCESSING_THRESHOLD + timedelta(minutes=1)
    await events._collection.update_one({"_id": event.id}, {"$set": {"processing_status": PROCESSING, "updated_at": almost_stale_at}})
    orchestrator = _orchestrator(events, operations_ai=operations_ai)

    outcome = await orchestrator.process_pending(org_id=ORG)
    assert outcome == {"processed": 0, "failed": 0, "skipped": 0}
    assert operations_ai.calls == []
