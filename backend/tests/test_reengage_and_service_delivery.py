"""Re-engagement (3.10) and Service Delivery (3.13)."""
from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from reengage import rules as rr
from reengage import runner as rrun
from service_delivery import rules as sd
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 24)


def test_engagement_status():
    assert rr.engagement_status(dnd=True, has_live_project=True, last_two_way=NOW, now=NOW) == "dnd"
    assert rr.engagement_status(dnd=False, has_live_project=True, last_two_way=None, now=NOW) == "active"
    assert rr.engagement_status(dnd=False, has_live_project=False, last_two_way=NOW - timedelta(days=30), now=NOW) == "active"
    assert rr.engagement_status(dnd=False, has_live_project=False, last_two_way=NOW - timedelta(days=100), now=NOW) == "dormant"
    assert rr.engagement_status(dnd=False, has_live_project=False, last_two_way=NOW - timedelta(days=800), now=NOW,
                                sequence={"finished_without_reply": True}) == "lost"


def test_sequence_three_steps_three_weeks_apart_stops_on_reply():
    assert rr.next_step(None, NOW) == "whats_new"
    s = {"sent": [{"step": "whats_new", "at": NOW - timedelta(days=10)}]}
    assert rr.next_step(s, NOW) is None
    s["sent"][0]["at"] = NOW - timedelta(days=22)
    assert rr.next_step(s, NOW) == "case_study"
    assert rr.next_step({**s, "replied_at": NOW}, NOW) is None
    done = {"sent": [{"step": x, "at": NOW - timedelta(days=90)} for x in ("a", "b", "c")]}
    assert rr.next_step(done, NOW) is None


def test_lost_rfq_checkin_and_release_cap():
    assert rr.lost_rfq_checkin_due({"outcome": "lost", "closed_at": NOW - timedelta(days=31)}, NOW)
    assert not rr.lost_rfq_checkin_due({"outcome": "lost", "closed_at": NOW - timedelta(days=5)}, NOW)
    c = [{"lifetime_revenue": v} for v in (5, 50, 1)]
    assert [x["lifetime_revenue"] for x in rr.release(c, 18, {**rr.DEFAULTS, "daily_release_cap": 20})] == [50, 5]


def test_last_two_way_needs_both_directions():
    seen = {"acme.com": {"inbound": NOW - timedelta(days=5), "outbound": NOW - timedelta(days=2)},
            "blast.com": {"outbound": NOW}}
    assert rrun.last_two_way(seen, ["acme.com"]) == NOW - timedelta(days=5)
    assert rrun.last_two_way(seen, ["blast.com"]) is None


def test_reengagement_shadow_run_never_stamps_accounts(monkeypatch):
    d = {n: FakeDB() for n in ("crm_db", "email_automation", "torpedo_gmail")}
    monkeypatch.setattr(rrun, "_gd", lambda: (lambda name: d[name]))
    monkeypatch.setattr(rrun, "domain_last_seen", lambda md: {"old.com": {"inbound": NOW - timedelta(days=200),
                                                                          "outbound": NOW - timedelta(days=200)}})
    from platform_core import config_store
    monkeypatch.setattr(config_store, "get", lambda s, db=None: config_store.defaults(s))
    d["email_automation"].list_collection_names = lambda: []
    aid = d["crm_db"]["accounts"].insert_one({"name": "Old Co", "domain": "old.com"}).inserted_id
    s = rrun.run(now=NOW)
    assert s["dormant"] == 1 and s["planned"] == 1
    assert "engagement_status" not in d["crm_db"]["accounts"].find_one({"_id": aid})


def _proj():
    p = sd.new_project(bu="BIM", account_id="a1", contact_id="c1", title="Plant study", scope="s", deliverables=["d"],
                       value=100000, currency="INR", start=NOW, end=NOW + timedelta(days=60), owner="pm",
                       opportunity_id="o1", now=NOW)
    p["_id"] = ObjectId()
    return p


def test_service_project_only_for_cogentix_and_bim():
    with pytest.raises(sd.SDError):
        sd.new_project(bu="SFW", account_id="a", contact_id=None, title="t", scope="", deliverables=[], value=1,
                       currency="INR", start=NOW, end=NOW, owner=None, opportunity_id="o", now=NOW)


def test_milestones_must_add_to_100_and_transitions_are_checked():
    assert sd.validate_milestones([{"deliverable": "a", "due": NOW, "owner": "x", "billing_pct": 40},
                                   {"deliverable": "b", "due": NOW, "owner": "x", "billing_pct": 40}])
    p = _proj()
    sd.move(p, "in_progress")
    with pytest.raises(sd.SDError):
        sd.move(p, "closed")


def test_sign_off_bills_the_milestone_and_last_one_closes():
    p = _proj()
    p["milestones"] = [{"deliverable": "Report", "due": NOW, "owner": "x", "billing_pct": 60},
                       {"deliverable": "Deck", "due": NOW, "owner": "x", "billing_pct": 40}]
    r1 = sd.sign_off(p, 0, by="pm", now=NOW)
    assert r1["invoice"]["amount"] == 60000 and r1["invoice"]["entity"] == "BIM" and not r1["close_project"]
    with pytest.raises(sd.SDError):
        sd.sign_off(p, 0, by="pm", now=NOW)
    assert sd.sign_off(p, 1, by="pm", now=NOW)["close_project"]


def test_price_needs_a_rate_and_is_reviewed():
    assert "review" in sd.price("BIM", "drafting")
    cfg = {**sd.DEFAULTS, "rate_table": {"BIM": {"drafting": {"day_rate": 8000}}}}
    out = sd.price("BIM", "drafting", days=5, cfg=cfg)
    assert out["amount"] == 40000 and out["review"]


def test_reminders_owner_before_due_client_after_5_days_and_on_hold():
    p = _proj()
    p["milestones"] = [{"deliverable": "Report", "due": NOW + timedelta(days=1), "owner": "pm", "billing_pct": 50},
                       {"deliverable": "Deck", "due": NOW + timedelta(days=20), "owner": "pm", "billing_pct": 50,
                        "sent_for_review_at": NOW - timedelta(days=6)}]
    held = _proj()
    held["status"] = "on_hold"
    held["history"].append({"to": "on_hold", "at": NOW - timedelta(days=8)})
    r = sd.reminders([p, held], NOW, {"c1": "x@client.com"})
    assert len(r["owner"]) == 1 and r["client"][0]["to"] == "x@client.com" and r["on_hold_for_paused_digest"] == [held]
