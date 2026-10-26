"""Content engine (MARKETING_PLAN 3.6, 3.5.4)."""
import copy
from datetime import datetime, timedelta

import pytest

from marketing import config as mcfg, content as C
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 6, 0)


def test_flow_is_enforced_and_logged():
    it = {"status": "idea"}
    with pytest.raises(ValueError):
        C.transition(it, "approved", "a")
    it.update(C.transition(it, "draft", "a", NOW))
    it.update(C.transition(it, "in_review", "a", NOW))
    it.update(C.transition(it, "approved", "owner", NOW))
    assert it["approved_by"] == "owner" and [h["to"] for h in it["history"]] == ["draft", "in_review", "approved"]
    with pytest.raises(ValueError):
        C.transition(it, "scheduled", "owner")                         # no date yet
    it["scheduled_for"] = NOW
    assert C.transition(it, "scheduled", "owner")["status"] == "scheduled"
    with pytest.raises(ValueError):
        C.transition({"status": "draft", "claim_problems": ["x"]}, "in_review", "a")


def test_claims_checker():
    v = C.BRAND_VOICE_DRAFTS["SFW"]
    probs = C.check_claims("We guarantee 60% incidence with our 5 lakh panelists for Hansa. The world's leading panel!", "SFW",
                           voice=v, approved_stats=["1.2 lakh"], clients=[("Hansa", False), ("Acme", True)])
    assert any("banned claim" in p and "guarantee" in p for p in probs)
    assert any("5 lakh panelists" in p for p in probs) and any("Hansa" in p for p in probs)
    assert any("world's leading" in p for p in probs)
    ok = C.check_claims("Our 1.2 lakh panel members across India; ask Acme how fieldwork went.", "SFW", voice=v,
                        approved_stats=["1.2 lakh"], clients=[("Acme", True)])
    assert ok == []
    assert C.check_claims("x" * 3001, "SFW", channel="linkedin")[0].startswith("3001 characters")


def test_utm_link_keeps_existing_params():
    u = C.utm_link("https://bimwavesolutions.com/services.html?ref=1", bu="BIM", channel="quora", campaign="Scan to BIM", content="q 42")
    assert "ref=1" in u and "utm_source=quora" in u and "utm_campaign=bim-scan-to-bim" in u and "utm_content=q-42" in u


def _db():
    d = {n: FakeDB() for n in ("email_automation", "crm_db")}
    return d, (lambda n: d[n])


def test_publish_due_is_shadow_until_live_and_publisher():
    d, gd = _db()
    col = d["email_automation"]["content_items"]
    col.insert_one({"status": "scheduled", "scheduled_for": NOW - timedelta(minutes=5), "channel": "linkedin", "bu": "SFW", "history": []})
    col.insert_one({"status": "scheduled", "scheduled_for": NOW + timedelta(days=1), "channel": "linkedin", "bu": "SFW"})
    cfg = copy.deepcopy(mcfg.DEFAULTS)
    assert C.publish_due(gd, now=NOW, cfg=cfg) == {"published": 0, "would_publish": 1, "errors": []}
    assert col.find_one({"scheduled_for": {"$lte": NOW}})["shadow_reason"] == "shadow mode"
    cfg.update(mode="live", action_modes={"content:linkedin": "live"})
    C.register_publisher("linkedin", lambda it: {"post_id": "urn:li:share:1", "url": "https://linkedin.com/x"})
    try:
        assert C.publish_due(gd, now=NOW, cfg=cfg)["published"] == 1
        assert col.find_one({"platform_post_id": "urn:li:share:1"})["status"] == "published"
        cfg["kill_switch"] = {"global": True}
        col.insert_one({"status": "scheduled", "scheduled_for": NOW, "channel": "linkedin", "bu": "SFW"})
        assert C.publish_due(gd, now=NOW, cfg=cfg) == {"published": 0, "would_publish": 0, "errors": []}
    finally:
        C._PUBLISHERS.clear()


def test_draft_uses_voice_and_only_given_facts():
    d, gd = _db()
    seen = {}

    def fake():
        return {"status": "ok", "data": {"title": "Fieldwork in 3 weeks", "body": "Need fieldwork across 5 states?", "hashtags": ["#research"]}}
    out = C.draft({"_id": "x", "bu": "SFW", "channel": "linkedin", "title": "CATI fieldwork"}, gd, qwen=fake)
    assert out["body"].startswith("Need fieldwork") and out["voice_status"] == "proposed" and out["hashtags"] == ["#research"]
    bad = C.draft({"_id": "x", "bu": "SFW", "channel": "linkedin"}, gd, qwen=lambda: {"status": "deferred"})
    assert "deferred" in bad["draft_error"]


def test_brand_voice_seed_never_overwrites():
    d, gd = _db()
    assert C.seed_brand_voice(gd, NOW) == 3
    bv = d["email_automation"]["brand_voice"]
    bv.docs[0]["voice"] = "owner edit"
    assert C.seed_brand_voice(gd, NOW) == 0 and bv.docs[0]["voice"] == "owner edit"
