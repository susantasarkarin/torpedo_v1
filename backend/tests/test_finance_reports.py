"""Finance reports from invoices, bills and expenses, in INR."""
from datetime import datetime

import pytest

from app.services import finance_reports as fr


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(fr, "_live_fx", lambda: None)
    monkeypatch.setattr(fr, "_historical", lambda cur, day: None)


class _Col:
    def __init__(self, docs):
        self.docs = docs

    def find(self, q=None, p=None):
        return list(self.docs)


def _db(invoices=(), bills=(), expenses=()):
    return {"invoices": _Col(invoices), "bills": _Col(bills), "expenses": _Col(expenses)}


INV = [
    {"invoice_date": datetime(2026, 3, 1), "due_date": datetime(2026, 3, 31), "currency_code": "USD",
     "subtotal": 1000, "tax_total": 0, "total_amount": 1000, "balance_due": 1000, "status": "overdue"},
    {"invoice_date": datetime(2026, 4, 10), "due_date": datetime(2026, 5, 10), "currency_code": "INR",
     "subtotal": 100000, "tax_total": 18000, "total_amount": 118000, "balance_due": 0, "amount_paid": 118000,
     "status": "paid"},
    {"invoice_date": datetime(2026, 4, 12), "currency_code": "INR", "subtotal": 5, "total_amount": 5, "status": "draft"},
]


def test_profit_loss_converts_and_skips_drafts(monkeypatch):
    monkeypatch.setenv("FINANCE_FX_RATES", '{"USD": 80}')
    r = fr.profit_loss(_db(INV), "2026-01-01", "2026-12-31")
    assert r["revenue"]["total_sales"] == 80000 + 100000
    assert r["net_profit"] == 180000 and r["fx_rates"]["USD"] == 80


def test_aging_buckets_unpaid_by_days_past_due(monkeypatch):
    monkeypatch.setenv("FINANCE_FX_RATES", '{"USD": 80}')
    r = fr.aging(_db(INV), "receivables", None, "2026-06-15")
    assert r["61_90"] == 80000 and r["total"] == 80000 and r["count"] == 1


def test_gst_and_cash_flow():
    g = fr.gst(_db(INV), "2026-04-01", "2026-04-30")
    assert g["output_gst"] == 18000 and g["net_gst"] == 18000
    c = fr.cash_flow(_db(INV), "2026-03-01", "2026-04-30")
    assert [m["month"] for m in c["months"]] == ["2026-03", "2026-04"]
    assert c["months"][1]["inflow"] == 118000 and c["inflow"] == 118000


def test_every_report_the_page_asks_for_exists():
    for rid in ("profit-loss", "balance-sheet", "cash-flow", "gst-report", "aging/receivables", "aging/payables"):
        assert rid in fr.REPORTS
        assert "basis" in fr.REPORTS[rid](_db(INV), "2026-01-01", "2026-12-31")


class _Locks:
    def __init__(self, docs=()):
        self.docs = {d["_id"]: d for d in docs}
        self.writes = 0

    def find(self, q=None, p=None):
        return list(self.docs.values())

    def update_one(self, q, u, upsert=False):
        if q["_id"] not in self.docs:  # $setOnInsert: never overwrite
            self.docs[q["_id"]] = {"_id": q["_id"], **u["$setOnInsert"]}
            self.writes += 1


def test_invoice_rate_is_its_own_date_and_locked_forever(monkeypatch):
    calls = []
    monkeypatch.setattr(fr, "_historical", lambda cur, day: calls.append(day) or 75.56)
    locks = _Locks()
    db = {"invoices": _Col([]), "bills": _Col([]), "expenses": _Col([]), "invoice_fx": locks}
    inv = {"_id": "a1", "currency_code": "USD", "invoice_date": datetime(2020, 4, 7)}
    assert fr.Converter(db).rate(inv) == 75.56 and calls == ["2020-04-07"]
    # later: a different market rate must not change the locked one
    monkeypatch.setattr(fr, "_historical", lambda cur, day: 99.0)
    assert fr.Converter(db).rate(inv) == 75.56 and locks.writes == 1


def test_rate_on_the_invoice_itself_wins():
    db = {"invoices": _Col([]), "bills": _Col([]), "expenses": _Col([]), "invoice_fx": _Locks()}
    inv = {"_id": "z", "currency_code": "USD", "invoice_date": datetime(2026, 1, 1), "exchange_rate": 88.1}
    assert fr.Converter(db).rate(inv) == 88.1
