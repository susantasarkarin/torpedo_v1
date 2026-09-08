"""
Slice 18 — the economic chain. `SurveyBillingService` never writes to Mongo except
through the real, unchanged Slice 8 `InvoiceService`/`BillService` — these tests
prove that composition and its idempotency guards, not re-prove Slice 8's own
invoice/bill mechanics (already covered in test_finance_service.py).
"""

from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.crm.models import Opportunity
from app.finance.models import Bill, GstDetails, Invoice
from app.finance.sequence import SequenceService
from app.finance.service import BillService, InvoiceService
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.panel.billing import SurveyBillingError, SurveyBillingService
from app.panel.models import Survey, SurveyResponse

ORG = "org-A"
ACTOR = "alice"
CURRENCY = "INR"
GST = GstDetails(place_of_supply="KA")


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def invoice_service(db) -> InvoiceService:
    return InvoiceService(CanonicalRepository(db["invoices"], Invoice), SequenceService(db["finance_sequences"]), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def bill_service(db) -> BillService:
    return BillService(CanonicalRepository(db["bills"], Bill), SequenceService(db["finance_sequences"]), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def billing_service(db, invoice_service, bill_service) -> SurveyBillingService:
    return SurveyBillingService(
        CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["surveys"], Survey),
        CanonicalRepository(db["opportunities"], Opportunity), invoice_service, bill_service,
    )


async def _survey(db, *, client_rate_minor=50_000, cpi_minor=20_000, opportunity_id=None) -> Survey:
    return await CanonicalRepository(db["surveys"], Survey).insert(
        Survey(
            org_id=ORG, created_by=ACTOR, updated_by=ACTOR, provider="cint", external_id="ext-1", quota_remaining=100,
            cpi=Money(amount_minor=cpi_minor, currency=CURRENCY), conversion_rate=0.3,
            client_rate=Money(amount_minor=client_rate_minor, currency=CURRENCY) if client_rate_minor is not None else None,
            opportunity_id=opportunity_id,
        )
    )


async def _completion(db, survey_id, *, ref="r1", event="e1") -> SurveyResponse:
    return await CanonicalRepository(db["survey_responses"], SurveyResponse).insert(
        SurveyResponse(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, allocation_id="a1", survey_id=survey_id, person_id="p1", respondent_ref=ref, provider="cint", external_event_id=event, final_status="complete")
    )


async def _opportunity(db, *, account_id="acct-1") -> Opportunity:
    return await CanonicalRepository(db["opportunities"], Opportunity).insert(Opportunity(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, account_id=account_id))


# --------------------------------------------------------------------------- record_billable_completion


@pytest.mark.asyncio
async def test_record_billable_completion_snapshots_the_supplier_cost(db, billing_service):
    survey = await _survey(db, cpi_minor=20_000)
    response = await _completion(db, survey.id)

    updated = await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=response.id)
    assert updated.billable is True
    assert updated.supplier_cost.amount_minor == 20_000


@pytest.mark.asyncio
async def test_record_billable_completion_is_idempotent_against_a_later_cpi_change(db, billing_service):
    survey = await _survey(db, cpi_minor=20_000)
    response = await _completion(db, survey.id)
    await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=response.id)

    # Survey.cpi changes later (a real refresh_projection would do this) — the
    # already-billable response must NOT be re-costed.
    fresh_survey = await CanonicalRepository(db["surveys"], Survey).get(survey.id)
    await CanonicalRepository(db["surveys"], Survey).update(fresh_survey.id, fresh_survey.version, {"cpi": Money(amount_minor=99_999, currency=CURRENCY)}, updated_by=ACTOR)

    replay = await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=response.id)
    assert replay.supplier_cost.amount_minor == 20_000  # unchanged


@pytest.mark.asyncio
async def test_record_billable_completion_rejects_a_non_complete_response(db, billing_service):
    survey = await _survey(db)
    response = await CanonicalRepository(db["survey_responses"], SurveyResponse).insert(
        SurveyResponse(org_id=ORG, created_by=ACTOR, updated_by=ACTOR, allocation_id="a1", survey_id=survey.id, person_id="p1", respondent_ref="r1", provider="cint", external_event_id="e1", final_status="terminated")
    )
    with pytest.raises(SurveyBillingError):
        await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=response.id)


# --------------------------------------------------------------------------- generate_client_invoice


@pytest.mark.asyncio
async def test_generate_client_invoice_requires_client_rate(db, billing_service):
    survey = await _survey(db, client_rate_minor=None, opportunity_id="opp-1")
    response = await _completion(db, survey.id)
    await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=response.id)

    with pytest.raises(SurveyBillingError):
        await billing_service.generate_client_invoice(org_id=ORG, actor=ACTOR, survey_id=survey.id, gst_details=GST, currency=CURRENCY)


@pytest.mark.asyncio
async def test_generate_client_invoice_requires_opportunity_id(db, billing_service):
    survey = await _survey(db, opportunity_id=None)
    response = await _completion(db, survey.id)
    await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=response.id)

    with pytest.raises(SurveyBillingError):
        await billing_service.generate_client_invoice(org_id=ORG, actor=ACTOR, survey_id=survey.id, gst_details=GST, currency=CURRENCY)


@pytest.mark.asyncio
async def test_generate_client_invoice_creates_a_real_invoice_and_marks_completions_billed(db, billing_service):
    opportunity = await _opportunity(db)
    survey = await _survey(db, client_rate_minor=50_000, opportunity_id=opportunity.id)
    r1 = await _completion(db, survey.id, ref="r1", event="e1")
    r2 = await _completion(db, survey.id, ref="r2", event="e2")
    await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=r1.id)
    await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=r2.id)

    invoice = await billing_service.generate_client_invoice(org_id=ORG, actor=ACTOR, survey_id=survey.id, gst_details=GST, currency=CURRENCY)

    assert invoice.customer_account_id == "acct-1"
    assert invoice.opportunity_id == opportunity.id
    assert invoice.total.amount_minor == 100_000  # 2 completions * 50000, no GST configured on the line
    assert invoice.status == "draft"

    updated_r1 = await CanonicalRepository(db["survey_responses"], SurveyResponse).get(r1.id)
    assert updated_r1.client_invoice_id == invoice.id


@pytest.mark.asyncio
async def test_generate_client_invoice_never_double_bills_the_same_completion(db, billing_service):
    opportunity = await _opportunity(db)
    survey = await _survey(db, opportunity_id=opportunity.id)
    r1 = await _completion(db, survey.id)
    await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=r1.id)
    await billing_service.generate_client_invoice(org_id=ORG, actor=ACTOR, survey_id=survey.id, gst_details=GST, currency=CURRENCY)

    with pytest.raises(SurveyBillingError):  # no NEW unbilled completions
        await billing_service.generate_client_invoice(org_id=ORG, actor=ACTOR, survey_id=survey.id, gst_details=GST, currency=CURRENCY)


# --------------------------------------------------------------------------- generate_supplier_bill


@pytest.mark.asyncio
async def test_generate_supplier_bill_creates_a_real_bill_and_marks_completions_costed(db, billing_service):
    survey = await _survey(db, cpi_minor=20_000)
    r1 = await _completion(db, survey.id)
    await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=r1.id)

    bill = await billing_service.generate_supplier_bill(org_id=ORG, actor=ACTOR, survey_id=survey.id, vendor_account_id="vendor-1", gst_details=GST, currency=CURRENCY)

    assert bill.vendor_account_id == "vendor-1"
    assert bill.total.amount_minor == 20_000
    updated_r1 = await CanonicalRepository(db["survey_responses"], SurveyResponse).get(r1.id)
    assert updated_r1.supplier_bill_id == bill.id


# --------------------------------------------------------------------------- compute_margin


@pytest.mark.asyncio
async def test_compute_margin_is_revenue_minus_cost(db, billing_service):
    survey = await _survey(db, client_rate_minor=50_000, cpi_minor=20_000)
    for i in range(3):
        r = await _completion(db, survey.id, ref=f"r{i}", event=f"e{i}")
        await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=r.id)

    margin = await billing_service.compute_margin(org_id=ORG, survey_id=survey.id)
    assert margin["completions"] == 3
    assert margin["revenue"].amount_minor == 150_000
    assert margin["supplier_cost"].amount_minor == 60_000
    assert margin["contribution_margin"].amount_minor == 90_000
    assert margin["margin_pct"] == 60.0


@pytest.mark.asyncio
async def test_compute_margin_with_no_client_rate_reports_zero_revenue_and_no_percentage(db, billing_service):
    survey = await _survey(db, client_rate_minor=None, cpi_minor=20_000)
    r = await _completion(db, survey.id)
    await billing_service.record_billable_completion(org_id=ORG, actor=ACTOR, survey_response_id=r.id)

    margin = await billing_service.compute_margin(org_id=ORG, survey_id=survey.id)
    assert margin["revenue"].amount_minor == 0
    assert margin["margin_pct"] is None  # never a fabricated 0% or 100%
