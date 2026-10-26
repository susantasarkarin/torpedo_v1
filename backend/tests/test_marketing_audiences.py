"""Audiences (MARKETING_PLAN 3.4.5): hashed lists, shadow until live, replace-not-append."""
import copy
import json
from datetime import datetime

from bson import ObjectId

from marketing import ads_common as A, audiences as AU, config as mcfg
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 1, 0)


def world(monkeypatch):
    d = {n: FakeDB() for n in ("email_automation", "crm_db", "finance_db", "torpedo")}
    acc_won, acc_inv = ObjectId(), ObjectId()
    d["crm_db"]["accounts"].insert_one({"_id": acc_won, "bu": "SFW"})
    d["crm_db"]["accounts"].insert_one({"_id": acc_inv, "bu": "BIM"})
    d["crm_db"]["opportunities"].insert_one({"status": "won", "account_id": acc_won})
    d["finance_db"]["customers"].insert_one({"crm_account_id": str(acc_inv)})
    d["crm_db"]["contacts"].insert_one({"email": "buyer@hansa.com", "account_id": acc_won})
    d["crm_db"]["contacts"].insert_one({"email": "pm@builder.in", "account_id": acc_inv})
    d["crm_db"]["contacts"].insert_one({"email": "prospect@x.com", "account_id": ObjectId()})
    from messaging import suppression
    sup = FakeDB()["s"]
    sup.insert_one({"email": "stop@me.com"})
    monkeypatch.setattr(suppression, "_canonical", lambda: sup)
    return d, (lambda n: d[n])


def test_lists_are_hashed_and_scoped(monkeypatch):
    d, gd = world(monkeypatch)
    L = AU.build_lists(gd)
    excl = set(L["SFW"]["exclude_clients_dnd"])
    assert excl == {A.sha256_email(e) for e in ("buyer@hansa.com", "pm@builder.in", "stop@me.com")}
    assert A.sha256_email("prospect@x.com") not in excl
    assert L["SFW"]["seed_won_clients"] == [A.sha256_email("buyer@hansa.com")] and L["BIM"]["seed_won_clients"] == [A.sha256_email("pm@builder.in")]
    assert all(len(h) == 64 for h in excl)


def test_sync_is_shadow_until_live(monkeypatch):
    d, gd = world(monkeypatch)
    rep = AU.sync(gd, cfg=copy.deepcopy(mcfg.DEFAULTS), now=NOW)
    assert rep["synced"] == [] and rep["lists"]["SFW"]["exclude_clients_dnd"] == 3
    rows = d["email_automation"]["audiences"].docs
    assert len(rows) == 3 * 2 * 2 and all(r["status"] == "shadow" for r in rows)


class MetaCl:
    def __init__(self):
        self.s, self.calls = {"ad_account_ids": {"SFW": "55", "BIM": "56", "COGENTIX": "57"}}, []

    def post(self, path, **data):
        self.calls.append((path, data))
        return {"id": f"aud_{len(self.calls)}"}


def test_meta_live_creates_once_then_replaces(monkeypatch):
    d, gd = world(monkeypatch)
    cfg = copy.deepcopy(mcfg.DEFAULTS)
    cfg.update(mode="live", action_modes={"audiences:meta": "live"})
    m = MetaCl()
    rep = AU.sync(gd, cfg=cfg, now=NOW, meta_cl=m)
    assert "SFW/meta/exclude_clients_dnd" in rep["synced"] and not [e for e in rep["errors"] if "/meta/" in e]
    creates = [c for c in m.calls if c[0].endswith("/customaudiences")]
    replaces = [c for c in m.calls if c[0].endswith("/usersreplace")]
    assert creates and replaces and json.loads(replaces[0][1]["payload"])["schema"] == ["EMAIL_SHA256"]
    n_creates = len(creates)
    AU.sync(gd, cfg=cfg, now=NOW, meta_cl=m)
    assert len([c for c in m.calls if c[0].endswith("/customaudiences")]) == n_creates         # reused, not recreated


def test_meta_retargeting_rules_are_pixel_based():
    r = AU.retargeting_rules("bimwavesolutions.com")
    assert r[0]["rule"]["inclusions"]["rules"][0]["event_sources"] == [{"type": "pixel"}] and r[1]["name"] == "high_intent_30d"
