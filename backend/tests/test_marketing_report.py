"""Weekly marketing report (MARKETING_PLAN 6.4)."""
from datetime import datetime, timedelta

from marketing import report as R
from tests._fakemongo import FakeDB

MON = datetime(2026, 10, 26, 3, 30)      # Monday 09:00 IST


def test_week_window_is_previous_ist_week():
    s, u, ps = R._week(MON)
    assert s == datetime(2026, 10, 18, 18, 30) and u == datetime(2026, 10, 25, 18, 30) and ps == datetime(2026, 10, 11, 18, 30)


def test_build_has_all_five_sections_and_stores_once():
    d = {n: FakeDB() for n in ("email_automation", "crm_db")}
    gd = lambda n: d[n]
    ea = d["email_automation"]
    ea["decisions"].insert_one({"status": "in_review", "decision_type": "D2", "entity_label": "SFW Search", "final_action": "pause",
                                "impact_inr": 42000, "created_at": MON - timedelta(days=3), "review_item": "r1"})
    ea["seo_issues"].insert_one({"status": "open", "severity": "high", "first_seen": MON - timedelta(days=2), "site": "x"})
    r = R.build(gd, MON)
    assert r["week"] == "2026-W43" and [l["bu"] for l in r["bu_lines"]] == ["SFW", "COGENTIX", "BIM"]
    assert r["top_actions"][0]["action"] == "pause" and r["engine"]["decisions"] == 1 and r["seo"]["new_high"] == 1
    for h in ("1. By company", "2. Top actions", "3. Decision Engine", "4. SEO", "5. Content"):
        assert h in r["html"]
    assert "₹42,000" in r["html"]
    R.build(gd, MON)
    assert ea["marketing_reports"].count_documents({}) == 1
