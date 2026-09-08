"""
Phase 9 (finance profitability/ageing intelligence) — FinanceAnalyticsService.
Every number here is a real aggregation over Invoice/Bill documents inserted
directly (this file tests the aggregation logic itself, not invoice/bill
creation mechanics, already covered in test_finance_service.py). Currency
safety is the property most worth proving wrong-by-default: a naive sum
across currencies would produce a meaningless number.
"""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.finance.analytics import FinanceAnalyticsService
from app.finance.models import Bill, GstDetails, Invoice, LineItem
from app.models.base import CanonicalRepository
from app.models.money import Money

ORG = "org-A"
ACTOR = "alice"
GST = GstDetails(place_of_supply="KA")


def _line_items():
    return [LineItem(description="research project", quantity=1, unit_price_minor=100_000, gst_rate_bps=1800)]


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def invoices(db) -> CanonicalRepository[Invoice]:
    return CanonicalRepository(db["invoices"], Invoice)


@pytest.fixture
def bills(db) -> CanonicalRepository[Bill]:
    return CanonicalRepository(db["bills"], Bill)


@pytest.fixture
def svc(invoices, bills) -> FinanceAnalyticsService:
    return FinanceAnalyticsService(invoices, bills)


async def _open_invoice(invoices, *, days_overdue: int | None, balance_due_minor=118_000, currency="INR", status="sent") -> Invoice:
    as_of = datetime.now(timezone.utc)
    due_at = as_of - timedelta(days=days_overdue) if days_overdue is not None else None
    return await invoices.insert(
        Invoice(
            org_id=ORG, created_by=ACTOR, updated_by=ACTOR, customer_account_id="cust-1", invoice_number=f"INV-{days_overdue}-{currency}",
            status=status, line_items=_line_items(), gst_details=GST,
            subtotal=Money(amount_minor=100_000, currency=currency), tax_total=Money(amount_minor=18_000, currency=currency), total=Money(amount_minor=118_000, currency=currency),
            amount_paid=Money(amount_minor=0, currency=currency), balance_due=Money(amount_minor=balance_due_minor, currency=currency), due_at=due_at,
        )
    )


async def _open_bill(bills, *, days_overdue: int | None, balance_due_minor=50_000, currency="INR", status="approved") -> Bill:
    as_of = datetime.now(timezone.utc)
    due_at = as_of - timedelta(days=days_overdue) if days_overdue is not None else None
    return await bills.insert(
        Bill(
            org_id=ORG, created_by=ACTOR, updated_by=ACTOR, vendor_account_id="vendor-1", bill_number=f"BILL-{days_overdue}-{currency}",
            status=status, line_items=_line_items(), gst_details=GST,
            subtotal=Money(amount_minor=42_373, currency=currency), tax_total=Money(amount_minor=7_627, currency=currency), total=Money(amount_minor=balance_due_minor, currency=currency),
            amount_paid=Money(amount_minor=0, currency=currency), balance_due=Money(amount_minor=balance_due_minor, currency=currency), due_at=due_at,
        )
    )


# --------------------------------------------------------------------------- ar_ageing


@pytest.mark.asyncio
async def test_not_yet_due_invoice_lands_in_current(db, svc, invoices):
    await _open_invoice(invoices, days_overdue=-5)  # due in 5 days
    report = await svc.ar_ageing(org_id=ORG)
    assert report["INR"]["current"]["count"] == 1
    assert report["INR"]["current"]["amount_minor"] == 118_000


@pytest.mark.asyncio
async def test_invoice_with_no_due_date_lands_in_current(db, svc, invoices):
    await _open_invoice(invoices, days_overdue=None)
    report = await svc.ar_ageing(org_id=ORG)
    assert report["INR"]["current"]["count"] == 1


@pytest.mark.asyncio
async def test_ar_ageing_buckets_by_real_days_overdue(db, svc, invoices):
    await _open_invoice(invoices, days_overdue=15)   # 1_30
    await _open_invoice(invoices, days_overdue=45)   # 31_60
    await _open_invoice(invoices, days_overdue=75)   # 61_90
    await _open_invoice(invoices, days_overdue=120)  # 90_plus

    report = await svc.ar_ageing(org_id=ORG)
    assert report["INR"]["1_30"]["count"] == 1
    assert report["INR"]["31_60"]["count"] == 1
    assert report["INR"]["61_90"]["count"] == 1
    assert report["INR"]["90_plus"]["count"] == 1
    assert report["INR"]["current"]["count"] == 0


@pytest.mark.asyncio
async def test_ar_ageing_ignores_closed_invoices(db, svc, invoices):
    await _open_invoice(invoices, days_overdue=45, status="paid")
    await _open_invoice(invoices, days_overdue=45, status="draft")
    await _open_invoice(invoices, days_overdue=45, status="void")

    report = await svc.ar_ageing(org_id=ORG)
    assert report == {}


@pytest.mark.asyncio
async def test_ar_ageing_never_sums_across_currencies(db, svc, invoices):
    await _open_invoice(invoices, days_overdue=45, balance_due_minor=100_000, currency="INR")
    await _open_invoice(invoices, days_overdue=45, balance_due_minor=500, currency="USD")

    report = await svc.ar_ageing(org_id=ORG)
    assert report["INR"]["31_60"]["amount_minor"] == 100_000
    assert report["USD"]["31_60"]["amount_minor"] == 500
    assert set(report.keys()) == {"INR", "USD"}  # never blended into one total


@pytest.mark.asyncio
async def test_ar_ageing_sums_multiple_invoices_in_the_same_bucket_and_currency(db, svc, invoices):
    await _open_invoice(invoices, days_overdue=45, balance_due_minor=50_000)
    await _open_invoice(invoices, days_overdue=50, balance_due_minor=30_000)

    report = await svc.ar_ageing(org_id=ORG)
    assert report["INR"]["31_60"]["count"] == 2
    assert report["INR"]["31_60"]["amount_minor"] == 80_000


@pytest.mark.asyncio
async def test_ar_ageing_never_crosses_orgs(db, svc, invoices):
    await invoices.insert(Invoice(org_id="org-B", created_by=ACTOR, updated_by=ACTOR, customer_account_id="cust-1", invoice_number="INV-X", status="sent", line_items=_line_items(), gst_details=GST, subtotal=Money(amount_minor=100_000, currency="INR"), tax_total=Money(amount_minor=18_000, currency="INR"), total=Money(amount_minor=118_000, currency="INR"), amount_paid=Money(amount_minor=0, currency="INR"), balance_due=Money(amount_minor=118_000, currency="INR")))
    report = await svc.ar_ageing(org_id=ORG)
    assert report == {}


# --------------------------------------------------------------------------- ap_ageing


@pytest.mark.asyncio
async def test_ap_ageing_buckets_open_bills(db, svc, bills):
    await _open_bill(bills, days_overdue=10)
    await _open_bill(bills, days_overdue=95)

    report = await svc.ap_ageing(org_id=ORG)
    assert report["INR"]["1_30"]["count"] == 1
    assert report["INR"]["90_plus"]["count"] == 1


@pytest.mark.asyncio
async def test_ap_ageing_ignores_draft_and_paid_bills(db, svc, bills):
    await _open_bill(bills, days_overdue=45, status="draft")
    await _open_bill(bills, days_overdue=45, status="paid")

    report = await svc.ap_ageing(org_id=ORG)
    assert report == {}
