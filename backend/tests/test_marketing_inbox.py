"""Unified inbox (MARKETING_PLAN 3.7, 3.5.3, 6.3)."""
import copy
from datetime import datetime, timedelta

import pytest

from marketing import config as mcfg, inbox as I
from tests._fakemongo import FakeDB

MON_0930_IST = datetime(2026, 10, 26, 4, 0)       # Monday 09:30 IST (UTC naive)


@pytest.fixture
def env(monkeypatch):
    d = {n: FakeDB() for n in ("email_automation", "crm_db")}
    from platform_core import review_queue
    monkeypatch.setattr(review_queue, "_col", lambda db=None: d["email_automation"]["review_queue_items"])
    return d, (lambda n: d[n])


def cfg():
    return copy.deepcopy(mcfg.DEFAULTS)


def test_working_hours_sla():
    # 09:30 IST Monday: clock starts at 10:00 -> 1 h -> 11:00 IST = 05:30 UTC
    assert I.working_due(MON_0930_IST, 1) == datetime(2026, 10, 26, 5, 30)
    # Friday 17:30 IST + 1 h -> Monday 10:30 IST
    fri = datetime(2026, 10, 30, 12, 0)
    assert I.working_due(fri, 1) == datetime(2026, 11, 2, 5, 0)
    # 4 h from 16:00 IST -> 2 h today + 2 h next day -> 12:00 IST Tuesday
    assert I.working_due(datetime(2026, 10, 26, 10, 30), 4) == datetime(2026, 10, 27, 6, 30)


@pytest.mark.parametrize("text,channel,cat,who", [
    ("Buy cheap followers here https://x.io and https://y.io", "instagram_comment", "spam", "other"),
    ("I completed the survey but haven't received my reward points", "facebook_comment", "support", "panelist"),
    ("Thanks!", "linkedin_comment", "neutral", "other"),
    ("STOP", "whatsapp", "negative", "other"),
])
def test_social_rules(text, channel, cat, who):
    r = I.classify(text, channel=channel)
    assert r["category"] == cat and r["sender_type"] == who


def test_ingest_links_drafts_review_and_is_idempotent(env):
    d, gd = env
    d["crm_db"]["leads"].insert_one({"email": "asha@builder.in", "contact_id": "C1"})
    it = I.ingest(gd, channel="messenger", external_id="m1", bu="BIM", text="Please send a quote for scan to BIM of a 3 floor office",
                  author={"name": "Asha Rao", "email": "Asha@Builder.in"}, at=MON_0930_IST, cfg=cfg(), now=MON_0930_IST)
    assert it["lead_id"] and it["contact_id"] == "C1" and it["status"] == "open"
    assert it["due_at"] == datetime(2026, 10, 26, 5, 30) and it["sla_hours"] == 1
    assert "email" not in it["author"]                                          # no raw email copied into the inbox row
    item = d["email_automation"]["review_queue_items"].find_one({"type": "inbox_reply"})
    assert item["suggested"]["reply"].startswith("Hi Asha")
    again = I.ingest(gd, channel="messenger", external_id="m1", bu="BIM", text="dup", cfg=cfg(), now=MON_0930_IST)
    assert again["_id"] == it["_id"] and d["email_automation"]["inbox_items"].count_documents({}) == 1


def test_spam_gets_no_sla_or_review(env):
    d, gd = env
    it = I.ingest(gd, channel="instagram_comment", external_id="c9", bu="SFW", text="seo services cheap, dm me for backlinks",
                  cfg=cfg(), now=MON_0930_IST)
    assert it["status"] == "spam" and it["due_at"] is None
    assert d["email_automation"]["review_queue_items"].count_documents({}) == 0


def test_whatsapp_stop_records_opt_out_and_blocks_sends(env):
    d, gd = env
    ea = d["email_automation"]
    ea["whatsapp_optins"].insert_one({"phone_hash": I.phone_hash("9876543210"), "granted": True, "at": MON_0930_IST - timedelta(days=3)})
    ok, why = I.whatsapp_can_send(gd, "+91 98765 43210", template="rfq_follow_up", now=MON_0930_IST)
    assert not ok and "not approved" in why
    ea["whatsapp_templates"].insert_one({"name": "rfq_follow_up", "status": "approved"})
    assert I.whatsapp_can_send(gd, "9876543210", template="rfq_follow_up", now=MON_0930_IST)[0]
    assert not I.whatsapp_can_send(gd, "9876543210", now=MON_0930_IST)[0]          # free text outside 24 h
    I.ingest(gd, channel="whatsapp", external_id="w1", bu="SFW", text="Hi, any update?", author={"phone": "9876543210"},
             at=MON_0930_IST, cfg=cfg(), now=MON_0930_IST)
    assert I.whatsapp_can_send(gd, "9876543210", now=MON_0930_IST + timedelta(hours=2))[1] == "inside the 24-hour service window"
    I.ingest(gd, channel="whatsapp", external_id="w2", bu="SFW", text="stop", author={"phone": "9876543210"},
             at=MON_0930_IST + timedelta(hours=3), cfg=cfg(), now=MON_0930_IST + timedelta(hours=3))
    ok, why = I.whatsapp_can_send(gd, "9876543210", template="rfq_follow_up", now=MON_0930_IST + timedelta(hours=4))
    assert not ok and why == "opted out"
    assert not I.whatsapp_can_send(gd, "5550001111", template="rfq_follow_up", now=MON_0930_IST)[0]   # never cold WhatsApp


def test_contact_cap_across_channels(env, monkeypatch):
    d, gd = env
    from messaging import facade
    monkeypatch.setattr(facade, "_throttle_block", lambda a, c: None)
    assert I.contact_cap_ok(gd, lead_id="L1", cfg=cfg(), now=MON_0930_IST)[0]
    d["email_automation"]["marketing_touches"].insert_one({"lead_id": "L1", "automated": True, "at": MON_0930_IST - timedelta(hours=2)})
    ok, why = I.contact_cap_ok(gd, lead_id="L1", cfg=cfg(), now=MON_0930_IST)
    assert not ok and "cap 1" in why
    monkeypatch.setattr(facade, "_throttle_block", lambda a, c: "already mailed")
    assert not I.contact_cap_ok(gd, lead_id="L2", email="x@y.com", cfg=cfg(), now=MON_0930_IST)[0]    # mail counts too


def test_review_decision_closes_the_loop(env):
    d, gd = env
    it = I.ingest(gd, channel="linkedin_dm", external_id="d1", bu="COGENTIX", text="Interested in a brand health study, can we talk?",
                  author={"name": "Ravi"}, at=MON_0930_IST, cfg=cfg(), now=MON_0930_IST)
    ri = d["email_automation"]["review_queue_items"].docs[0]
    ri.update(status="approved", resolved_by="owner", resolved_at=MON_0930_IST + timedelta(minutes=40))
    assert I.sync_review_status(gd, now=MON_0930_IST + timedelta(hours=1)) == {"replied": 1, "closed": 0}
    row = d["email_automation"]["inbox_items"].find_one({})
    assert row["status"] == "replied" and row["response_minutes"] == 40 and row["sla_met"] is True
    assert I.sla_breaches(gd, now=MON_0930_IST + timedelta(days=1)) == []
