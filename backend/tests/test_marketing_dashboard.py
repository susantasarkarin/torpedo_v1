"""Marketing dashboard sections (MARKETING_PLAN 6.1)."""
import copy
from datetime import datetime, timedelta

from marketing import config as mcfg, dashboard as D
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 6, 0)
S = NOW - timedelta(days=30)


def world():
    d = {n: FakeDB() for n in ("email_automation", "crm_db")}
    return d, (lambda n: d[n])


def test_empty_sources_say_no_data():
    d, gd = world()
    out = D.all_sections(gd, now=NOW, cfg=copy.deepcopy(mcfg.DEFAULTS))
    assert out["website"]["no_data"] and out["paid"]["no_data"] and out["seo"]["no_gsc_data"]
    assert out["attribution"]["rfq_by_channel"] == {} and out["social"]["platforms"] is None


def test_website_funnel_and_sources():
    d, gd = world()
    ea = d["email_automation"]
    ea["web_sessions"].insert_one({"visitor_id": "v1", "started_at": NOW - timedelta(days=2), "utm": {"utm_medium": "cpc"}, "landing": "https://x/pricing?a=1"})
    ea["web_sessions"].insert_one({"visitor_id": "v2", "started_at": NOW - timedelta(days=1), "referrer": "https://www.google.com/", "landing": "https://x/"})
    ea["web_visitors"].insert_one({"visitor_id": "v1", "first_seen": NOW - timedelta(days=90)})
    ea["web_visitors"].insert_one({"visitor_id": "v2", "first_seen": NOW - timedelta(days=1)})
    for t in ("page_view", "form_start", "form_start", "form_abandon", "form_submit"):
        ea["web_events"].insert_one({"type": t, "visitor_id": "v1", "at": NOW - timedelta(days=2), "ua": "Mozilla/5.0 (iPhone)"})
    w = D.website(gd, S, NOW)
    assert w["by_source"] == {"paid_search": 1, "organic_search": 1} and w["new_visitors"] == 1 and w["returning_visitors"] == 1
    assert w["funnel"]["form_starts"] == 2 and w["form_abandonment_pct"] == 50.0 and w["devices"] == {"mobile": 1}
    assert ("https://x/pricing", 1) in w["top_entry_pages"]


def test_paid_table_pacing_waste():
    d, gd = world()
    ea = d["email_automation"]
    for i in range(1, 6):
        ea["ad_metrics_daily"].insert_one({"level": "campaign", "platform": "google", "entity_id": "c1", "name": "SFW Search", "bu": "SFW",
                                           "date": (NOW - timedelta(days=i)).strftime("%Y-%m-%d"), "spend_inr": 2000, "leads": 1, "rfqs": 0.2})
    ea["search_terms"].insert_one({"term": "free survey jobs", "date": (NOW - timedelta(days=2)).strftime("%Y-%m-%d"), "spend_inr": 900, "leads": 0})
    cfg = copy.deepcopy(mcfg.DEFAULTS)
    cfg["budget"]["monthly_cap_inr"] = {"SFW": {"google": 100000}}
    p = D.paid(gd, S, NOW, None, cfg)
    row = p["campaigns"][0]
    assert row["spend_inr"] == 10000 and row["cpl_inr"] == 2000 and row["cost_per_rfq_inr"] == 10000
    assert p["search_term_waste_inr"] == 900 and p["pacing"]["SFW/google"]["cap_inr"] == 100000


def test_attribution_model_switch():
    d, gd = world()
    ea = d["email_automation"]
    ea["attribution_results"].insert_one({"model": "first_touch", "event": "rfq", "conversion_at": NOW - timedelta(days=3), "touches": 4,
                                          "days_to_convert": 20, "credits": {"organic_search": {"credit": 1.0, "value_inr": 0}}})
    ea["attribution_results"].insert_one({"model": "last_non_direct", "event": "rfq", "conversion_at": NOW - timedelta(days=3), "touches": 4,
                                          "days_to_convert": 20, "credits": {"email": {"credit": 1.0, "value_inr": 0}}})
    assert D.attribution_mix(gd, S, NOW, model="first_touch")["rfq_by_channel"] == {"organic_search": 1.0}
    a = D.attribution_mix(gd, S, NOW)
    assert a["rfq_by_channel"] == {"email": 1.0} and a["avg_touches_to_rfq"] == 4 and a["avg_days_to_rfq"] == 20
