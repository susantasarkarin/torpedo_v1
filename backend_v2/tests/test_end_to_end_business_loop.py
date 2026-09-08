"""
End-to-end business loop — GSC signal -> prospect -> ICP -> Lead -> Account ->
Opportunity -> Survey -> eligibility gate -> AI panel allocation -> completion ->
billable completion -> client invoice -> supplier bill -> client payment ->
AI-matched reconciliation -> margin -> AI operational evaluation -> AI outreach
follow-up -> final audit trail.

This is the master-prompt's explicit demand for "at least one comprehensive
end-to-end integration test representing the full business loop." Every hop below
calls the same real, already-unit-tested service each slice built — this file
proves *composition*, not mechanics already covered elsewhere (webhook HMAC
verification, quota-race fallback, GST rounding, etc. all stay in their own test
files). All six AI decisions in this test are made by exactly ONE shared
`DecisionEngine` instance, wired to one shared `ScriptedLLM` and one shared
`AiProposal` repository — the direct, literal proof of the master prompt's
core mandate: "do not build isolated per-domain decision engines."

**Two hops are deliberately manual in this test, and documented as real,
honest gaps, not oversights**:
- Lead -> Opportunity: there is no automatic conversion anywhere in the
  codebase. A qualified lead's Account is real (resolved by
  `LeadGenService.ingest()` from a real `company_domain`), but creating the
  `Opportunity` from it is a human/ops decision this test makes explicitly,
  exactly as a real user would via the CRM UI.
- Lead -> Outreach enrollment: same story — `LeadEnrollment` has no
  automatic creation path from a qualified `LeadState` either.
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
from app.emailai.drafting import EmailMessageDrafter
from app.finance.models import Bill, BankAccount, CreditNote, Expense, GstDetails, Invoice, LineItem, Payment, ReconciliationRecord
from app.finance.sequence import SequenceService
from app.finance.service import BillService, InvoiceService, PaymentService, ReconciliationService
from app.finance.ai_finance import AIFinanceService
from app.identity.facet_service import FacetService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.leadgen.ai_leadgen import LeadGenAIService
from app.leadgen.ai_outreach import OutreachAIService
from app.leadgen.gsc import SearchSignal
from app.leadgen.models import DeadLetterEvent, LeadEnrollment, RawLeadEvent
from app.leadgen.service import LeadGenService
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.outreach.budget import BudgetService
from app.outreach.kill_switch import KillSwitch, KillSwitchService
from app.outreach.models import Mailbox, Message, SendLogEntry
from app.outreach.providers import ProviderSendResult
from app.outreach.service import MessagingFacade
from app.outreach.suppression import Suppression, SuppressionService
from app.panel.ai_allocation import PanelAllocationAIService
from app.panel.ai_operations import OperationsAIService
from app.panel.billing import SurveyBillingService
from app.panel.inactivity import StudyInactivityService
from app.panel.models import Allocation, Survey, SurveyResponse, Supplier, SupplierReconciliationRecord, TrafficSource  # noqa: F401 (keeps mongomock db namespace consistent with other suites)
from app.panel.providers import SurveyProjection
from app.panel.service import AllocationService, SurveyService
from app.rbac.identity import ResolvedIdentity
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.service import RBACService

ORG = "org-A"
ACTOR = "ops-alice"
CURRENCY = "INR"
SITE = "https://torpedo.example"
GST = GstDetails(place_of_supply="KA")


class ScriptedLLM:
    """One shared LLM standing in for every one of this loop's six AI decisions
    plus one drafting sub-call. Dispatches on the real `DecisionEngine`
    message shape (`{"task": ..., "context": ...}`) so each call gets the
    scripted response for *that* task, in any order — not a brittle
    call-position queue."""

    def __init__(self):
        self._by_task: dict[str, str] = {}
        self.calls: list[dict] = []

    def script(self, task: str, content: str) -> None:
        self._by_task[task] = content

    async def chat(self, *, messages, response_format=None):
        body = json.loads(messages[1]["content"])
        self.calls.append(body)
        task = body.get("task")
        if task and task in self._by_task:
            return LLMResponse(content=self._by_task[task], model="scripted-model")
        # Not a decide() call with a scripted task -> must be EmailMessageDrafter's draft() sub-call.
        return LLMResponse(
            content=json.dumps({"subject": "Following up", "body": "Hi — thought this might help. Unsubscribe any time at https://example.com/u", "confidence": 0.9}),
            model="scripted-model",
        )


class StubSurveyProvider:
    async def build_redirect_url(self, *, survey, respondent_ref):
        return f"https://stub/{survey.external_id}/{respondent_ref}"

    async def refresh(self, *, survey):
        return SurveyProjection(quota_remaining=survey.quota_remaining, cpi_minor=survey.cpi.amount_minor, conversion_rate=survey.conversion_rate)


class RecordingSendProvider:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    async def send(self, *, mailbox_credentials_id, to_email, subject, body):
        self.calls.append((to_email, subject, body))
        return ProviderSendResult(provider_message_id=f"pm-{len(self.calls)}")


def _decision(**overrides) -> str:
    payload = {
        "decision": "NONE", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "MEDIUM",
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


@pytest.fixture
def activities(db) -> CanonicalRepository[Activity]:
    return CanonicalRepository(db["activities"], Activity)


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def engine(llm, ai_proposals) -> DecisionEngine:
    """The ONE DecisionEngine every AI service below shares — the literal proof
    there is no second, isolated decision engine anywhere in this loop."""
    return DecisionEngine(llm, ToolRegistry(), ai_proposals)


@pytest.fixture
def identity(db, activities) -> IdentityService:
    return IdentityService(people=CanonicalRepository(db["people"], Person), accounts=CanonicalRepository(db["accounts"], Account), brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship), activities=activities)


@pytest.fixture
def facets(db, activities) -> FacetService:
    return FacetService(people=CanonicalRepository(db["people"], Person), accounts=CanonicalRepository(db["accounts"], Account), activities=activities, lead_states=CanonicalRepository(db["lead_states"], LeadState), panelist_profiles=CanonicalRepository(db["panelist_profiles"], PanelistProfile), customer_billing=CanonicalRepository(db["customer_billing"], CustomerBilling), vendor_profiles=CanonicalRepository(db["vendor_profiles"], VendorProfile), employee_records=CanonicalRepository(db["employee_records"], EmployeeRecord), auth_identities=CanonicalRepository(db["auth_identities"], AuthIdentity))


@pytest.fixture
def suppression(db) -> SuppressionService:
    return SuppressionService(CanonicalRepository(db["suppressions"], Suppression))


@pytest.fixture
def leadgen(db, identity, facets, suppression, activities) -> LeadGenService:
    return LeadGenService(identity, facets, suppression, raw_events=CanonicalRepository(db["raw_lead_events"], RawLeadEvent), ai_proposals=CanonicalRepository(db["ai_proposals_lead_enrichment"], AiProposal), enrollments=CanonicalRepository(db["lead_enrollments"], LeadEnrollment), dead_letters=CanonicalRepository(db["dead_letters"], DeadLetterEvent), activities=activities)


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
def payment_service(db, sequences, activities) -> PaymentService:
    return PaymentService(CanonicalRepository(db["payments"], Payment), CanonicalRepository(db["invoices"], Invoice), CanonicalRepository(db["bills"], Bill), sequences, activities)


@pytest.fixture
def reconciliation_service(db) -> ReconciliationService:
    return ReconciliationService(CanonicalRepository(db["reconciliation_records"], ReconciliationRecord), CanonicalRepository(db["payments"], Payment))


@pytest.fixture
def opportunity_service(db, invoice_service, activities) -> OpportunityService:
    return OpportunityService(CanonicalRepository(db["opportunities"], Opportunity), activities, invoice_service)


@pytest.fixture
def survey_service(db, activities) -> SurveyService:
    return SurveyService(CanonicalRepository(db["surveys"], Survey), activities)


@pytest.fixture
def allocation_service(db, activities) -> AllocationService:
    return AllocationService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), activities)


@pytest.fixture
def billing_service(db, invoice_service, bill_service) -> SurveyBillingService:
    return SurveyBillingService(CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["opportunities"], Opportunity), invoice_service, bill_service)


@pytest.fixture
def rbac(db) -> RBACService:
    return RBACService(user_roles=CanonicalRepository(db["user_roles"], UserRole), roles=CanonicalRepository(db["roles"], Role), approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority))


@pytest.fixture
def send_provider() -> RecordingSendProvider:
    return RecordingSendProvider()


@pytest.fixture
def outreach_facade(db, suppression, send_provider) -> MessagingFacade:
    return MessagingFacade(mailboxes=CanonicalRepository(db["mailboxes"], Mailbox), messages=CanonicalRepository(db["messages"], Message), send_logs=CanonicalRepository(db["send_log_entries"], SendLogEntry), ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal), activities=activities_for(db), suppression=suppression, kill_switch=KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch)), budget=BudgetService(db["budget_counters"]), provider=send_provider)


def activities_for(db) -> CanonicalRepository[Activity]:
    return CanonicalRepository(db["activities"], Activity)


async def _approve_and_send_invoice(invoice_service, rbac, invoice: Invoice, approver="finance-bob") -> Invoice:
    await rbac._approval_authorities.insert(ApprovalAuthority(org_id=ORG, created_by="seed", updated_by="seed", user_id=approver, entity_type="finance.invoice", max_amount=Money(amount_minor=100_000_000, currency=CURRENCY)))
    approver_identity = ResolvedIdentity(user_id=approver, org_id=ORG, principal_type="user", roles=frozenset(), permissions=frozenset({"finance.invoice.approve"}), real_actor_id=approver)
    await invoice_service.approve_invoice(identity=approver_identity, rbac=rbac, invoice_id=invoice.id)
    return await invoice_service.send_invoice(org_id=ORG, actor=ACTOR, invoice_id=invoice.id)


@pytest.mark.asyncio
async def test_full_business_loop_from_gsc_signal_to_margin_and_ai_followup(
    db, identity, facets, leadgen, invoice_service, bill_service, payment_service, reconciliation_service,
    opportunity_service, survey_service, allocation_service, billing_service, rbac, outreach_facade, send_provider,
    engine, llm, ai_proposals,
):
    # ---------------------------------------------------------------- 1. GSC signal -> AI lead generation
    leadgen_ai = LeadGenAIService(engine, leadgen)
    llm.script("generate_leads", _decision(
        decision="generate_leads", confidence=0.85,
        extracted_entities={"candidates": [{
            "company_domain": "acme-research.example", "company_name": "Acme Research", "contact_email": "jordan@acme-research.example",
            "contact_name": "Jordan Lee", "title": "VP Insights", "evidence": {"query": "ai survey panel provider", "clicks": 40},
        }]},
    ))
    signal = SearchSignal(query="ai survey panel provider", page="/services/panel", impressions=500, clicks=40, ctr=0.08, position=3.2, country="IN")

    class FakeGSC:
        async def get_search_analytics(self, *, site_url: str, days: int = 28):
            return [signal]

    results = await leadgen_ai.generate_leads(org_id=ORG, actor=ACTOR, site_url=SITE, gsc=FakeGSC())
    assert len(results) == 1
    lead_state_id, person_id = results[0].lead_state_id, results[0].person_id

    lead = await leadgen.get_lead(lead_state_id)
    account = await identity.get_account(lead.account_id)
    assert account is not None and account.domain == "acme-research.example"  # a real, resolved Account — never fabricated

    # ---------------------------------------------------------------- 2. AI ICP evaluation
    llm.script("evaluate_icp", _decision(decision="OUTREACH", confidence=0.9, extracted_entities={"score": 88, "classification": "A", "fit_reasons": ["existing customer base overlap"], "risks": []}))
    icp_decision = await leadgen_ai.evaluate_icp(org_id=ORG, actor=ACTOR, lead_state_id=lead_state_id, prospect_context={"industry": "market research", "country": "IN"})
    assert icp_decision.decision == "OUTREACH"

    lead_after_icp = await leadgen.get_lead(lead_state_id)
    assert lead_after_icp.ai_decision_subject_id == lead_state_id  # traced, without touching icp_score
    assert lead_after_icp.icp_score is None  # untouched — only app.leadgen.scoring's canonical scorer may ever set this

    # ---------------------------------------------------------------- 3. Honest manual gap: Lead -> Opportunity
    # No automatic conversion exists anywhere in the codebase — an ops/sales
    # decision creates the Opportunity from the qualified lead's real Account.
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor=ACTOR, account_id=account.id)

    # ---------------------------------------------------------------- 4. Survey created, commercially linked, made eligible
    survey = await survey_service.create_survey(
        org_id=ORG, actor=ACTOR, provider="cint", external_id="ext-loop-1", quota_remaining=10,
        cpi=Money(amount_minor=20_000, currency=CURRENCY), conversion_rate=0.35,
        category="consumer_goods", length_minutes=12, incentive=Money(amount_minor=15_000, currency=CURRENCY),
        opportunity_id=opportunity.id, client_rate=Money(amount_minor=50_000, currency=CURRENCY),
    )
    survey = await survey_service.set_eligibility(org_id=ORG, actor=ACTOR, survey_id=survey.id, is_active_in_pool=True, activated_at=None)

    # ---------------------------------------------------------------- 5. AI panel allocation
    allocation_ai = PanelAllocationAIService(engine, survey_service, allocation_service, CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["allocations"], Allocation))
    llm.script("evaluate_panel_allocation", _decision(decision=survey.id, confidence=0.88, actions=["allocate"], extracted_entities={survey.id: {"score": 0.82}}))
    alloc_decision, allocation = await allocation_ai.evaluate_and_allocate(org_id=ORG, actor=ACTOR, person_id=person_id, vendor_id="vendor-panel-1", country_code="IN", respondent_ref="respondent-1", provider=StubSurveyProvider())
    assert allocation is not None and allocation.survey_id == survey.id
    assert allocation.ai_decision_subject_id == f"{person_id}:respondent-1"

    # ---------------------------------------------------------------- 6. Completion recorded
    # Webhook signature/idempotency mechanics are covered in test_panel_service.py
    # and test_panel_routers.py — here we record the real outcome directly, the
    # same precedent test_panel_billing.py already established.
    response = await CanonicalRepository(db["survey_responses"], SurveyResponse).insert(
        SurveyResponse(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, allocation_id=allocation.id, survey_id=survey.id, person_id=person_id, respondent_ref="respondent-1", provider="cint", external_event_id="evt-1", final_status="complete")
    )

    # ---------------------------------------------------------------- 7. Billable completion (deterministic, no AI)
    response = await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=response.id)
    assert response.billable is True
    assert response.supplier_cost.amount_minor == 20_000

    # ---------------------------------------------------------------- 8 & 9. Client invoice + supplier bill
    invoice = await billing_service.generate_client_invoice(org_id=ORG, actor=ACTOR, survey_id=survey.id, gst_details=GST, currency=CURRENCY)
    assert invoice.opportunity_id == opportunity.id
    assert invoice.customer_account_id == account.id
    assert invoice.total.amount_minor == 50_000

    bill = await billing_service.generate_supplier_bill(org_id=ORG, actor=ACTOR, survey_id=survey.id, vendor_account_id="vendor-panel-1", gst_details=GST, currency=CURRENCY)
    assert bill.total.amount_minor == 20_000

    # ---------------------------------------------------------------- 10. Invoice approved & sent (unchanged Slice 8 governance)
    await invoice_service.submit_invoice(org_id=ORG, actor=ACTOR, invoice_id=invoice.id)
    invoice = await _approve_and_send_invoice(invoice_service, rbac, invoice)
    assert invoice.status == "sent"

    # ---------------------------------------------------------------- 11. Client payment arrives as an external signal
    record = await reconciliation_service.record_external_entry(org_id=ORG, actor=ACTOR, source="bank_feed", external_reference="txn-loop-1", amount=invoice.total)
    assert record.status == "unmatched"  # a candidate only — never a fabricated PAID invoice

    # ---------------------------------------------------------------- 12. AI-driven payment matching
    finance_ai = AIFinanceService(engine, invoice_service, bill_service, payment_service, reconciliation_service, CanonicalRepository(db["reconciliation_records"], ReconciliationRecord), ai_proposals, activities_for(db))
    llm.script("match_payment_to_invoice", _decision(decision=invoice.id, confidence=0.95))
    match_decision, payment = await finance_ai.match_payment_to_invoice(org_id=ORG, actor=ACTOR, reconciliation_record_id=record.id)
    assert payment is not None

    invoice_after_payment = await CanonicalRepository(db["invoices"], Invoice).get(invoice.id)
    assert invoice_after_payment.status == "paid"
    assert invoice_after_payment.amount_paid.amount_minor == 50_000

    # ---------------------------------------------------------------- 13. Margin
    margin = await billing_service.compute_margin(org_id=ORG, survey_id=survey.id)
    assert margin["revenue"].amount_minor == 50_000
    assert margin["supplier_cost"].amount_minor == 20_000
    assert margin["contribution_margin"].amount_minor == 30_000
    assert margin["margin_pct"] == 60.0

    # ---------------------------------------------------------------- 14. AI operational evaluation (same shared DecisionEngine, different domain)
    inactivity = StudyInactivityService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), activities_for(db))
    operations_ai = OperationsAIService(engine, survey_service, inactivity, CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["survey_responses"], SurveyResponse), activities_for(db), ai_proposals)
    llm.script("evaluate_operations_response", _decision(decision="NO_ACTION", confidence=0.8))
    ops_decision = await operations_ai.evaluate_and_act(org_id=ORG, actor=ACTOR, survey_id=survey.id, trigger_type="low_conversion")
    assert ops_decision.decision == "NO_ACTION"

    survey_after_ops = await CanonicalRepository(db["surveys"], Survey).get(survey.id)
    assert survey_after_ops.ai_decision_subject_id is not None

    # ---------------------------------------------------------------- 15. Honest manual gap: Lead -> Outreach enrollment, then AI outreach follow-up
    # No automatic LeadState -> LeadEnrollment wiring exists either — an ops
    # decision enrolls the same qualified lead from step 2 into outreach.
    enrollment = await CanonicalRepository(db["lead_enrollments"], LeadEnrollment).insert(
        LeadEnrollment(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, lead_state_id=lead_state_id, person_id=person_id, brand_id="brand-torpedo")
    )
    await KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch)).resume(org_id=ORG, actor="system")
    await CanonicalRepository(db["mailboxes"], Mailbox).insert(Mailbox(id="mailbox-loop-1", org_id=ORG, created_by="system", updated_by="system", email_address="sales@torpedo.example", provider="smtp", credentials_id="cred-1"))

    outreach_ai = OutreachAIService(engine, leadgen, outreach_facade, EmailMessageDrafter(llm), CanonicalRepository(db["lead_enrollments"], LeadEnrollment))
    llm.script("evaluate_outreach", _decision(decision="CONTACTED", confidence=0.9, actions=["send_message"]))
    outreach_decision = await outreach_ai.decide_and_act(org_id=ORG, actor=ACTOR, enrollment_id=enrollment.id, mailbox_id="mailbox-loop-1")
    assert outreach_decision.decision == "CONTACTED"
    assert len(send_provider.calls) == 1
    assert send_provider.calls[0][0] == "jordan@acme-research.example"

    enrollment_after = await CanonicalRepository(db["lead_enrollments"], LeadEnrollment).get(enrollment.id)
    assert enrollment_after.ai_decision_subject_id == enrollment.id

    # ---------------------------------------------------------------- 16. Final audit trail
    # Exactly one AiProposal per DecisionEngine.decide() call made in this loop
    # — never a second, isolated decision engine, and never a decision made
    # without an audit record. "message_drafting" is a *separate*, pre-existing
    # Slice 7 audit trail MessagingFacade.send() records for the drafted email
    # content itself — a real seventh proposal, not a duplicate of the sixth.
    proposals = await ai_proposals.find_all({"org_id": ORG})
    tasks_seen = {p.task for p in proposals}
    assert tasks_seen == {
        "generate_leads", "evaluate_icp", "evaluate_panel_allocation",
        "match_payment_to_invoice", "evaluate_operations_response", "evaluate_outreach", "message_drafting",
    }
    assert len(proposals) == 7  # one proposal per decision/draft — no duplicates, no silent extras

    # Every AI-touched entity in this loop traces back to a real AiProposal.
    assert await ai_proposals.find_one({"subject_id": lead_after_icp.ai_decision_subject_id, "task": "evaluate_icp"}) is not None
    assert await ai_proposals.find_one({"subject_id": allocation.ai_decision_subject_id, "task": "evaluate_panel_allocation"}) is not None
    assert await ai_proposals.find_one({"subject_id": survey_after_ops.ai_decision_subject_id, "task": "evaluate_operations_response"}) is not None
    assert await ai_proposals.find_one({"subject_id": enrollment_after.ai_decision_subject_id, "task": "evaluate_outreach"}) is not None
