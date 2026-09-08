"""
FinanceAnalyticsService — real, deterministic reporting over the existing
Invoice/Bill data (Phase 9 of the master completion program: "AR/AP ageing,
collection intelligence"). Every number here is a real aggregation over real
documents the governed Slice 8 services already wrote — this module writes
nothing, and makes no AI decision; it's the same evidence
`AIFinanceService.decide_ar_followup()`/`decide_ap_followup()` (Slice 17)
already reason from per-invoice, made queryable as a real report instead of
staying implicit inside one decision at a time.

**Currency-safe by construction.** Summing `amount_minor` across invoices in
different currencies would silently produce a meaningless total — the same
discipline `app.models.money.Money` exists to prevent everywhere else in this
codebase. Every bucket is keyed `(currency, age_bucket)`, never just
`age_bucket` alone; a multi-currency book of business gets one real total per
currency, never one fabricated blended number.

**`AGEING_BUCKETS` mirrors standard AR/AP reporting conventions** (current,
1-30, 31-60, 61-90, 90+ days overdue) — an industry-standard framing, not an
invented one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.finance.models import Bill, Invoice
from app.models.base import CanonicalRepository

AGEING_BUCKETS = ("current", "1_30", "31_60", "61_90", "90_plus")


def _bucket_for(days_overdue: int | None) -> str:
    if days_overdue is None or days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "1_30"
    if days_overdue <= 60:
        return "31_60"
    if days_overdue <= 90:
        return "61_90"
    return "90_plus"


def _empty_bucket() -> dict:
    return {"count": 0, "amount_minor": 0}


class FinanceAnalyticsService:
    def __init__(self, invoices: CanonicalRepository[Invoice], bills: CanonicalRepository[Bill]):
        self._invoices = invoices
        self._bills = bills

    async def ar_ageing(self, *, org_id: str, as_of: datetime | None = None) -> dict:
        """`{currency: {bucket: {count, amount_minor}}}` over every open
        (`sent`/`partially_paid`) Invoice's real `balance_due` — the exact
        same candidate set `AIFinanceService.decide_ar_followup()` draws
        from (`InvoiceService.list_open()`), aggregated instead of decided
        on one at a time."""
        as_of = as_of or datetime.now(timezone.utc)
        open_invoices = await self._invoices.find_all({"org_id": org_id, "status": {"$in": ["sent", "partially_paid"]}})
        return self._ageing(open_invoices, as_of=as_of)

    async def ap_ageing(self, *, org_id: str, as_of: datetime | None = None) -> dict:
        """Same shape as `ar_ageing()`, over open (`approved`/`partially_paid`)
        Bills — the candidate set `AIFinanceService.decide_ap_followup()`
        draws from."""
        as_of = as_of or datetime.now(timezone.utc)
        open_bills = await self._bills.find_all({"org_id": org_id, "status": {"$in": ["approved", "partially_paid"]}})
        return self._ageing(open_bills, as_of=as_of)

    @staticmethod
    def _ageing(documents: list, *, as_of: datetime) -> dict:
        report: dict[str, dict[str, dict]] = {}
        for doc in documents:
            currency = doc.balance_due.currency
            days_overdue = (as_of - doc.due_at).days if doc.due_at else None
            bucket = _bucket_for(days_overdue)
            currency_report = report.setdefault(currency, {b: _empty_bucket() for b in AGEING_BUCKETS})
            currency_report[bucket]["count"] += 1
            currency_report[bucket]["amount_minor"] += doc.balance_due.amount_minor
        return report
