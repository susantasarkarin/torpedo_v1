"""Dashboards (CRM plan 3.14): definitions, periods, RAG, tiles, needs attention."""
from datetime import datetime, timedelta

from kpi import compute, definitions
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 24, 9, 0)      # 14:30 IST


def _dbs():
    d = {n: FakeDB() for n in ("finance_db", "crm_db", "email_automation", "torpedo", "torpedo_gmail", "ai_governance")}
    return d, (lambda name: d[name])


def test_every_kpi_has_a_module_and_a_known_compute():
    defs = definitions.all_definitions()
    assert len({d["key"] for d in defs}) == len(defs)
    for d in defs:
        assert d["module"] in definitions.MODULES
        assert d["compute"] is None or d["compute"] in compute.FUNCS


def test_rag_both_directions_and_no_target():
    t = {"amber": 80, "red": 60}
    assert definitions.rag(90, t, True) == "green" and definitions.rag(70, t, True) == "amber" and definitions.rag(50, t, True) == "red"
    assert definitions.rag(50, {"amber": 60, "red": 80}, False) == "green"
    assert definitions.rag(5, {}, True) == "none"


def test_periods_use_ist_calendar_and_financial_year():
    s, u, ps, pu = compute.period("mtd", NOW)
    assert s == datetime(2026, 9, 30, 18, 30) and u == NOW and ps == datetime(2026, 8, 31, 18, 30)
    assert compute.period("ytd", NOW)[0] == datetime(2026, 3, 31, 18, 30)
    assert compute.period("today", NOW)[0] == datetime(2026, 10, 23, 18, 30)


def test_revenue_converts_currency_and_filters_bu():
    d, gd = _dbs()
    d["finance_db"]["invoice_fx"].insert_one({"currency": "USD", "rate": 84.0, "rate_date": NOW})
    inv = d["finance_db"]["invoices"]
    inv.insert_one({"status": "paid", "branch": "Survey Fieldwork", "total": 100, "currency_code": "USD", "invoice_date": NOW - timedelta(days=2)})
    inv.insert_one({"status": "overdue", "branch": "Cogentix Research", "total": 1000, "currency_code": "INR", "invoice_date": NOW - timedelta(days=2)})
    inv.insert_one({"status": "draft", "branch": "Survey Fieldwork", "total": 9999, "currency_code": "INR", "invoice_date": NOW})
    s, u, _, _ = compute.period("mtd", NOW)
    assert compute.revenue_invoiced(gd, s, u, None) == 9400
    assert compute.revenue_invoiced(gd, s, u, "SFW") == 8400


def test_tiles_mark_kpis_without_a_source():
    d, gd = _dbs()
    tiles = compute.tiles(gd, "pulse", "mtd", None, now=NOW)
    by = {t["key"]: t for t in tiles}
    assert by["cash_in_bank"]["available"] is False and by["cash_in_bank"]["value"] is None
    assert by["projects_live"]["value"] == 0 and by["projects_live"]["status"] == "none"


def test_needs_attention_ranks_red_first_and_by_money_x_days():
    d, gd = _dbs()
    rq = d["email_automation"]["review_queue_items"]
    rq.insert_one({"status": "pending", "module": "rfq", "reason": "old", "created_at": NOW - timedelta(days=3), "value_inr": 50000})
    rq.insert_one({"status": "pending", "module": "rfq", "reason": "fresh", "created_at": NOW - timedelta(hours=1)})
    rq.insert_one({"status": "pending", "module": "ops", "reason": "amber", "created_at": NOW - timedelta(hours=6)})
    d["finance_db"]["invoices"].insert_one({"status": "overdue", "balance_due": 200000, "currency_code": "INR",
                                            "due_date": NOW - timedelta(days=70), "invoice_number": "SF-1"})
    out = compute.needs_attention(gd, NOW)
    whats = [i["what"] for i in out["items"]]
    assert "Review Queue: fresh" not in " ".join(whats)
    assert whats[0].startswith("Receivable > 60 days") and out["items"][-1]["severity"] == "amber"
