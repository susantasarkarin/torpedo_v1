"""Signal + rule layer (MARKETING_PLAN 4.1-4.2) on synthetic data."""
import copy
from datetime import datetime, timedelta

import pytest

from marketing import config as mcfg, engine as E, rules as Ru
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 3, 0)          # a Monday
R = copy.deepcopy(Ru.RULES)
R["target_cpl_inr"] = {"SFW": 1500}


def day(n):
    return (NOW - timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.fixture
def db():
    d = {n: FakeDB() for n in ("email_automation", "crm_db")}
    return d, (lambda n: d[n])


def ad(ea, eid, n, **f):
    ea["ad_metrics_daily"].insert_one({"level": f.pop("level", "campaign"), "entity_id": eid, "date": day(n), "bu": "SFW",
                                       "platform": "google", **f})


def test_z_test():
    t = Ru.two_proportion(20, 1000, 45, 1000)
    assert t["p"] < 0.01 and t["b_rate"] == 0.045
    assert Ru.two_proportion(10, 1000, 11, 1000)["p"] > 0.5 and Ru.two_proportion(0, 0, 1, 1)["p"] == 1.0


def test_paid_rules_pause_realloc_bids_negatives(db):
    d, gd = db
    ea = d["email_automation"]
    for i in range(1, 11):
        ad(ea, "c_waste", i, spend_inr=2000, leads=0, rfqs=0, clicks=50, conversions=0, name="Waste")
        ad(ea, "c_good", i, spend_inr=1000, leads=2, rfqs=1, clicks=40, conversions=2, name="Good")
        ad(ea, "c_meh", i, spend_inr=3000, leads=2, rfqs=0.25 if i <= 4 else 0, clicks=60, conversions=2, name="Meh")
        ad(ea, "c_bid", i, spend_inr=4000, leads=2, rfqs=1, clicks=80, conversions=2, name="Over target")
    for i in range(1, 6):
        ea["search_terms"].insert_one({"campaign_id": "c_meh", "term": "free survey jobs", "date": day(i), "spend_inr": 600,
                                       "clicks": 5, "leads": 0, "bu": "SFW"})
        ea["search_terms"].insert_one({"campaign_id": "c_meh", "term": "panel recruitment agency", "date": day(i), "spend_inr": 800,
                                       "clicks": 4, "leads": 1, "bu": "SFW"})
    cs = Ru.paid_candidates(ea, NOW, R)
    by = {(c["decision_type"], c["entity_key"]): c for c in cs}
    pause = by[("D2", "google:campaign:c_waste")]
    assert pause["action"] == "pause" and pause["evidence"]["spend_inr_30d"] == 20000 and pause["impact_inr"] == 20000
    realloc = by[("D1", "google:SFW:realloc")]
    assert realloc["parameters"]["from"] == "c_meh" and realloc["parameters"]["to"] == "c_good"
    assert ("D3", "google:campaign:c_meh") not in by                                   # CPA 1500 = target: no change
    bid = by[("D3", "google:campaign:c_bid")]                                           # CPA 2000 > 1500 + 20%
    assert bid["parameters"]["change_pct"] == -10 and bid["evidence"]["cpa_inr"] == 2000
    neg = by[("D4", "google:campaign:c_meh:negatives")]
    assert neg["parameters"]["terms"] == ["free survey jobs"] and neg["evidence"]["wasted_spend_inr_30d"] == 3000


def test_creative_winner_and_fatigue(db):
    d, gd = db
    ea = d["email_automation"]
    for i in range(1, 8):
        ad(ea, "adA", i, level="ad", group_id="g1", impressions=1000, clicks=10, spend_inr=500, frequency=2)
        ad(ea, "adB", i, level="ad", group_id="g1", impressions=1000, clicks=30, spend_inr=500, frequency=5)
    cs = Ru.paid_candidates(ea, NOW, R)
    win = [c for c in cs if c["rule_id"] == "d5_ctr_winner"][0]
    assert win["parameters"] == {"winner": "adB", "loser": "adA"} and win["evidence"]["p_value"] < 0.05
    assert any(c["rule_id"] == "d5_fatigue" and c["entity_key"].endswith("adB") for c in cs)


def test_seo_opportunities_and_issues(db):
    d, gd = db
    ea = d["email_automation"]
    for i in range(1, 15):
        ea["gsc_pages_daily"].insert_one({"site": "sc-domain:bimwavesolutions.com", "page": "https://bimwavesolutions.com/scan-to-bim",
                                          "date": day(i), "impressions": 40, "clicks": 1, "position": 11.0, "bu": "BIM"})
    ea["seo_issues"].insert_one({"site": "bimwavesolutions.com", "status": "open", "severity": "high", "code": "js_only_content", "bu": "BIM"})
    cs = Ru.seo_candidates(ea, NOW, R)
    sites = {c["entity_key"] for c in cs}
    assert sites == {"seo:sc-domain:bimwavesolutions.com", "seo:bimwavesolutions.com"}
    opp = [c for c in cs if c["evidence"]["opportunity_pages"]][0]
    assert opp["evidence"]["impressions_28d"] == 560 and opp["action"] == "rank_fixes"


def test_lead_scoring_routes_and_respects_whatsapp_optin(db):
    d, gd = db
    ea = d["email_automation"]
    ea["touchpoints"].insert_one({"lead_id": "L1", "kind": "form", "at": NOW - timedelta(days=9), "bu": "BIM"})
    ea["touchpoints"].insert_one({"lead_id": "L1", "kind": "mail_in", "at": NOW - timedelta(days=8), "bu": "BIM"})
    ea["touchpoints"].insert_one({"lead_id": "L1", "kind": "visit", "at": NOW - timedelta(days=10), "landing": "https://x/pricing"})
    ea["touchpoints"].insert_one({"lead_id": "L1", "kind": "visit", "at": NOW - timedelta(days=11), "channel": "paid_search"})
    ea["touchpoints"].insert_one({"lead_id": "L2", "kind": "visit", "at": NOW - timedelta(days=1)})
    cs = Ru.lead_candidates(ea, d["crm_db"], NOW, R)
    l1 = [c for c in cs if c["entity_key"] == "lead:L1"][0]
    assert l1["parameters"]["grade"] == "A" and l1["action"] == "route_sales_call"
    nba = [c for c in cs if c["entity_key"] == "lead:L1:nba"][0]
    assert nba["parameters"]["channel"] == "email"                       # no WhatsApp opt-in -> never WhatsApp
    ea["whatsapp_optins"].insert_one({"lead_id": "L1", "granted": True})
    nba2 = [c for c in Ru.lead_candidates(ea, d["crm_db"], NOW, R) if c["entity_key"] == "lead:L1:nba"][0]
    assert nba2["parameters"]["channel"] == "whatsapp"
    assert [c for c in cs if c["entity_key"] == "lead:L2"][0]["parameters"]["grade"] == "D"


def test_experiments_and_anomalies(db):
    d, gd = db
    ea = d["email_automation"]
    ea["experiments"].insert_one({"name": "CTA copy", "status": "running", "started_at": NOW - timedelta(days=10),
                                  "arms": [{"name": "A", "n": 1000, "conversions": 20}, {"name": "B", "n": 1000, "conversions": 45}]})
    ea["experiments"].insert_one({"name": "old", "status": "running", "started_at": NOW - timedelta(days=50),
                                  "arms": [{"name": "A", "n": 50, "conversions": 1}, {"name": "B", "n": 50, "conversions": 2}]})
    xs = Ru.experiment_candidates(ea, NOW, R)
    assert {c["action"] for c in xs} == {"declare_winner", "stop_test"}
    assert [c for c in xs if c["action"] == "declare_winner"][0]["parameters"]["winner"] == "B"
    for i in range(2, 9):
        ad(ea, "c1", i, spend_inr=1000, impressions=10000, clicks=200)
    ad(ea, "c1", 1, spend_inr=3500, impressions=10000, clicks=40)
    ea["web_events"].insert_one({"host": "bimwavesolutions.com", "type": "page_view", "at": NOW - timedelta(hours=30)})
    an = Ru.anomaly_candidates(ea, NOW, R, [{"domain": "bimwavesolutions.com", "bu": "BIM"}])
    assert {c["rule_id"] for c in an} == {"d13_spend_spike", "d13_ctr_crash", "d13_tracker_silent"}


def test_weekly_review_ranks_by_impact():
    cs = [Ru.cand("D2", f"k{i}", "pause", impact_inr=i * 1000) for i in range(8)]
    w = Ru.weekly_candidate(cs, NOW)
    assert [a["impact_inr"] for a in w["parameters"]["actions"]] == [7000, 6000, 5000, 4000, 3000]


def test_lane_run_decides_top_candidates_in_shadow(db, monkeypatch):
    d, gd = db
    ea = d["email_automation"]
    for i in range(1, 11):
        ad(ea, "c_waste", i, spend_inr=2000, leads=0, rfqs=0, clicks=50, conversions=0, name="Waste")
    from platform_core import config_store, review_queue, audit
    c = copy.deepcopy(mcfg.DEFAULTS)
    c["rules"] = {"target_cpl_inr": {"SFW": 1500}}
    monkeypatch.setattr(config_store, "get", lambda s: c if s == "marketing" else {"sites": []})
    monkeypatch.setattr(review_queue, "_col", lambda db=None: ea["review_queue_items"])
    monkeypatch.setattr(audit, "log_action", lambda **k: None)
    ea["decision_candidates"].insert_many = lambda docs: [ea["decision_candidates"].insert_one(x) for x in docs]
    rep = Ru.run("P2", gd, now=NOW, qwen=lambda t, br, chk: (_ for _ in ()).throw(ConnectionError("down")))
    assert rep["by_type"] == {"D2": 1} and rep["decisions"] == {"in_review": 1}
    dec = ea["decisions"].find_one({})
    assert dec["metric"]["name"] == "wasted_spend_inr" and dec["impact_inr"] == 20000 and dec["mode"] == "shadow"
    assert Ru.run("P2", gd, now=NOW, dry_run=True)["sample"][0]["action"] == "pause"


def test_outcome_metric_before_vs_after(db):
    d, gd = db
    ea = d["email_automation"]
    ex = NOW - timedelta(days=7)
    for i in range(8, 15):
        ea["web_events"].insert_one({"host": "x.com", "type": "form_submit", "at": NOW - timedelta(days=i)})
    for i in range(1, 4):
        ea["web_events"].insert_one({"host": "x.com", "type": "form_submit", "at": NOW - timedelta(days=i)})
    m = Ru.outcome_metric(gd)({"metric": {"name": "form_submits", "entity": "x.com", "higher_is_better": True},
                               "executed_at": ex, "outcome_due_at": NOW})
    assert m == {"baseline": 7, "actual": 3, "higher_is_better": True, "name": "form_submits"}
    assert Ru.outcome_metric(gd)({"metric": {}, "executed_at": ex, "outcome_due_at": NOW}) is None


def test_leads_with_pending_inbound_item_are_left_to_the_reply_flow(db):
    d, gd = db
    ea = d["email_automation"]
    ea["touchpoints"].insert_one({"lead_id": "L9", "kind": "form", "at": NOW - timedelta(days=1)})
    ea["review_queue_items"].insert_one({"type": "inbound_lead", "status": "pending", "payload": {"lead_id": "L9"}})
    assert not [c for c in Ru.lead_candidates(ea, d["crm_db"], NOW, R) if c["entity_key"].startswith("lead:L9")]
    ea["review_queue_items"].docs[0]["status"] = "approved"
    assert [c for c in Ru.lead_candidates(ea, d["crm_db"], NOW, R) if c["entity_key"] == "lead:L9"]


def test_staging_submissions_are_not_scored(db):
    d, gd = db
    ea = d["email_automation"]
    ea["touchpoints"].insert_one({"lead_id": "T1", "kind": "form", "at": NOW - timedelta(days=1),
                                  "landing": "http://127.0.0.3:8701/contact.html"})
    ea["touchpoints"].insert_one({"lead_id": "T2", "kind": "form", "at": NOW - timedelta(days=1),
                                  "landing": "https://cogentixresearch.com/contact.html"})
    keys = {c["entity_key"] for c in Ru.lead_candidates(ea, d["crm_db"], NOW, R)}
    assert "lead:T2" in keys and not any(k.startswith("lead:T1") for k in keys)
    assert Ru._test_host("http://localhost:3000/") and Ru._test_host("http://192.168.1.4/") and not Ru._test_host("https://bimwavesolutions.com/")
