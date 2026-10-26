"""Quora suggestions (3.5.4), self-reported source (3.8.5), shadow report (M6)."""
import copy
from datetime import datetime, timedelta

from marketing import config as mcfg, content as C, kpis as K, shadow_report as SR
from tests._fakemongo import FakeDB

NOW = datetime(2026, 11, 9, 6, 0)


def world():
    d = {n: FakeDB() for n in ("email_automation", "crm_db")}
    return d, (lambda n: d[n])


def test_quora_ranks_by_keywords_and_drafts_with_tagged_link():
    d, gd = world()
    d["email_automation"]["keywords"].insert_one({"bu": "BIM", "keyword": "scan to bim services", "status": "approved"})
    qs = ["What is the cost of scan to BIM for a hospital?", "Best pizza in Pune?", "How does point cloud to Revit modelling work?", "short"]
    out = C.suggest_quora(gd, qs, "BIM", qwen=lambda: {"status": "ok", "data": {"body": "Scan to BIM pricing depends on area and LOD."}},
                          now=NOW)
    assert [o["question"] for o in out] == ["How does point cloud to Revit modelling work?", "What is the cost of scan to BIM for a hospital?"]
    assert out[0]["score"] > out[1]["score"]                                        # 3 matched terms vs 2; pizza dropped
    it = d["email_automation"]["content_items"].find_one({"title": qs[0]})
    assert it["channel"] == "quora" and it["status"] == "draft" and "utm_source=quora" in it["body"] and "utm_campaign=bim-answers" in it["link"]


def test_source_check():
    d, gd = world()
    L = d["crm_db"]["leads"]
    L.insert_one({"created_at": NOW - timedelta(days=1), "web_submissions": [{"heard_from": "Google search",
                                                                                "first_touch": {"referrer": "https://www.google.com/"}}]})
    L.insert_one({"created_at": NOW - timedelta(days=1), "web_submissions": [{"heard_from": "A colleague",
                                                                                "first_touch": {"utm_source": "linkedin", "utm_medium": "social"}}]})
    r = K.source_check(gd, NOW - timedelta(days=30), NOW, None)
    assert r["answered"] == 2 and r["agree_pct"] == 50.0 and r["said"] == {"organic_search": 1, "referral": 1}
    assert K.heard_bucket("Saw your ad on LinkedIn") == "social"


def test_shadow_report(monkeypatch):
    d, gd = world()
    ea = d["email_automation"]
    for i in range(12):
        ea["decisions"].insert_one({"decision_type": "D4", "created_at": NOW - timedelta(days=13 - i // 2), "human": "approved" if i < 11 else "rejected",
                                    "status": "shadow_executed", "outcome": {"direction_correct": i % 2 == 0, "better_than_baseline": True}})
    ea["decisions"].insert_one({"decision_type": "D2", "created_at": NOW - timedelta(days=20), "status": "in_review"})
    ea["web_events"].insert_one({"host": "bimwavesolutions.com", "path": "/", "at": NOW - timedelta(hours=2), "type": "page_view"})
    ea["web_events"].distinct = lambda f, q: ["/", "/contact.html"]
    ea["seo_audits"].insert_one({"site": "bimwavesolutions.com", "started_at": NOW - timedelta(days=1), "page_rows": [
        {"url": "https://bimwavesolutions.com/", "status": 200}, {"url": "https://bimwavesolutions.com/about.html", "status": 200}]})
    from platform_core import config_store
    monkeypatch.setattr(config_store, "get", lambda s: {"sites": [{"domain": "bimwavesolutions.com", "bu": "BIM"}]})
    r = SR.build(gd, now=NOW, cfg=copy.deepcopy(mcfg.DEFAULTS))
    d4 = r["decisions"]["D4"]
    assert d4["made"] == 12 and d4["acceptance"] == 0.917 and d4["predicted_right"] == 0.5 and d4["may_go_above_L1"] is True
    assert "D2" not in r["decisions"] and r["shadow_days"] == 20 and r["min_shadow_days_met"]
    assert r["freshness"]["web tracker"]["status"] == "fresh" and r["freshness"]["GA4"]["status"] == "no data yet"
    assert r["tracking_coverage"]["bimwavesolutions.com"]["coverage_pct"] == 50.0
