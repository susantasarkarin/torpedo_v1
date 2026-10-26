"""Marketing dashboard 13 + Command Centre feeds (MARKETING_PLAN 6.1-6.2)."""
from datetime import datetime, timedelta

from kpi import compute, definitions
from marketing import kpis as K
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 6, 0)
S, U = NOW - timedelta(days=30), NOW


def world():
    d = {n: FakeDB() for n in ("email_automation", "crm_db", "finance_db", "torpedo_gmail", "torpedo_settings", "ai_governance")}
    return d, (lambda n: d[n])


def test_module_13_registered():
    keys = {x["key"] for x in definitions.all_definitions() if x["module"] == "marketing"}
    assert "marketing" in definitions.MODULES and len(keys) == len(K.DEFS)
    assert all(compute.FUNCS.get(x[7]) for x in K.DEFS)


def test_attributed_rfqs_and_won_exclude_outreach_email():
    d, gd = world()
    ar = d["email_automation"]["attribution_results"]
    ar.insert_one({"model": "last_non_direct", "event": "rfq", "conversion_at": NOW - timedelta(days=2),
                   "credits": {"organic_search": {"credit": 1.0, "value_inr": 0}}})
    ar.insert_one({"model": "last_non_direct", "event": "rfq", "conversion_at": NOW - timedelta(days=2),
                   "credits": {"email": {"credit": 1.0, "value_inr": 0}}})
    ar.insert_one({"model": "last_non_direct", "event": "won", "conversion_at": NOW - timedelta(days=1),
                   "credits": {"paid_search": {"credit": 1.0, "value_inr": 200000}}})
    ar.insert_one({"model": "first_touch", "event": "won", "conversion_at": NOW - timedelta(days=1),
                   "credits": {"paid_search": {"credit": 1.0, "value_inr": 999}}})
    assert K.mkt_rfqs(gd, S, U, None) == 1.0 and K.mkt_won_inr(gd, S, U, None) == 200000
    assert K.mkt_spend_inr(gd, S, U, None) is None and K.mkt_roas(gd, S, U, None) is None       # no ad source yet
    d["email_automation"]["ad_metrics_daily"].insert_one({"level": "campaign", "date": (NOW - timedelta(days=3)).strftime("%Y-%m-%d"),
                                                          "spend_inr": 50000})
    assert K.mkt_roas(gd, S, U, None) == 4.0 and K.mkt_cost_per_rfq(gd, S, U, None) == 50000


def test_inbox_and_decision_kpis():
    d, gd = world()
    ib = d["email_automation"]["inbox_items"]
    for m, ok in ((30, True), (50, True), (400, False)):
        ib.insert_one({"status": "replied", "replied_at": NOW - timedelta(days=1), "sla_met": ok, "response_minutes": m})
    assert K.mkt_inbox_sla_pct(gd, S, U, None) == 66.7 and K.mkt_inbox_median_min(gd, S, U, None) == 50
    dc = d["email_automation"]["decisions"]
    dc.insert_one({"created_at": NOW - timedelta(days=1), "human": "approved", "status": "shadow_executed"})
    dc.insert_one({"created_at": NOW - timedelta(days=1), "status": "in_review"})
    assert K.mkt_decisions(gd, S, U, None) == {"proposed": 2, "accepted": 1, "executed": 1}


def test_leads_ignore_staging_tests():
    d, gd = world()
    L = d["crm_db"]["leads"]
    L.insert_one({"source": "website_form", "created_at": NOW - timedelta(days=1), "web_submissions": [{"page": "https://bimwavesolutions.com/contact"}]})
    L.insert_one({"source": "csv_import", "created_at": NOW - timedelta(days=1)})
    assert K.mkt_leads(gd, S, U, None) >= 1


def test_feeds():
    d, gd = world()
    ea = d["email_automation"]
    ea["decisions"].insert_one({"status": "in_review", "decision_type": "D2", "rule_id": "d2_spend_no_rfq", "entity_label": "SFW Search",
                                "impact_inr": 42000, "created_at": NOW - timedelta(days=4)})
    ea["inbox_items"].insert_one({"status": "open", "due_at": NOW - timedelta(hours=10), "channel": "whatsapp", "text": "any update?"})
    ea["whatsapp_templates"].insert_one({"name": "quote_sent", "status": "rejected"})
    ea["gsc_sitemaps"].insert_one({"path": "https://x/sitemap.xml", "errors": 2})
    for i in range(8, 15):
        ea["gsc_pages_daily"].insert_one({"page": "/scan-to-bim", "date": (NOW - timedelta(days=i)).strftime("%Y-%m-%d"), "clicks": 10})
    for i in range(2, 8):
        ea["gsc_pages_daily"].insert_one({"page": "/scan-to-bim", "date": (NOW - timedelta(days=i)).strftime("%Y-%m-%d"), "clicks": 2})
    items = []
    K.attention(gd, NOW, lambda *a: items.append(a))
    whats = [a[1] for a in items]
    assert any("0 RFQs in 30 days" in w for w in whats) and any("Inbox past SLA" in w for w in whats)
    assert any("template rejected" in w for w in whats) and any("sitemap error" in w for w in whats)
    assert any("Organic clicks down" in w and "/scan-to-bim" in w for w in whats)
    assert any("waiting > 3 days" in w for w in whats)
    assert all(a[0] == "marketing" for a in items)
