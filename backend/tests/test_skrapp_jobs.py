"""Bounced people re-found through Skrapp become FRESH outreach (owner 2026-10-22)."""
from datetime import datetime

from leads import skrapp_jobs as sj

NOW = datetime(2026, 10, 22)


class _Cur(list):
    def sort(self, *a, **k):
        return self


class _Col:
    def __init__(self, docs=()):
        self.docs = [dict(d) for d in docs]
        self.inserted = []

    def _match(self, d, q):
        for k, v in (q or {}).items():
            if isinstance(v, dict):
                if "$in" in v and d.get(k) not in v["$in"]:
                    return False
                if "$ne" in v and d.get(k) == v["$ne"]:
                    return False
            elif d.get(k) != v:
                return False
        return True

    def find(self, q=None, proj=None):
        return _Cur(d for d in self.docs + self.inserted if self._match(d, q))

    def find_one(self, q=None, proj=None):
        r = self.find(q)
        return r[0] if r else None

    def update_one(self, q, u, upsert=False):
        pass

    def insert_one(self, d):
        self.inserted.append(d)


class _DB(dict):
    def __missing__(self, k):
        self[k] = _Col()
        return self[k]


def _setup(monkeypatch, found):
    t, ea = _DB(), _DB()
    t["outreach_leads_v2"] = _Col([{"_id": 1, "email": "old@acme.com", "workflow_status": "bounced",
                                    "campaign_id": "c-sfw", "name": "Priya Sharma", "company_name": "Acme"}])
    t["outreach_campaigns_v2"] = _Col([{"campaign_id": "c-sfw", "business": "sfw", "is_active": True}])
    client = {"torpedo": t, "email_automation": ea}
    from leads import skrapp_client, icp_check, company_fit
    monkeypatch.setattr(skrapp_client, "email_credits_left", lambda c: 10)
    monkeypatch.setattr(skrapp_client, "find", lambda *a, **k: found)
    monkeypatch.setattr(icp_check, "known_dead", lambda c: {"old@acme.com", "dead@acme.com"})
    monkeypatch.setattr(company_fit, "lookup", lambda *a, **k: {"type": "mr_agency"})
    return client, t


def test_new_valid_address_starts_fresh_outreach(monkeypatch):
    client, t = _setup(monkeypatch, {"status": "found", "email": "priya.sharma@acme.com", "quality": "valid"})
    assert sj.refind_bounced(client, now=NOW) == {"fresh_outreach": 1}
    row = t["outreach_leads_v2"].inserted[0]
    assert row["email"] == "priya.sharma@acme.com" and row["current_step"] == 0
    assert row["sendable"] is True and row["replaces_bounced"] == "old@acme.com"


def test_dead_or_unverified_address_is_not_sent(monkeypatch):
    client, t = _setup(monkeypatch, {"status": "found", "email": "dead@acme.com", "quality": "valid"})
    assert sj.refind_bounced(client, now=NOW) == {"same_or_dead": 1}
    client, t = _setup(monkeypatch, {"status": "found", "email": "p@acme.com", "quality": "catch-all"})
    assert sj.refind_bounced(client, now=NOW) == {"not_valid": 1}
    assert not t["outreach_leads_v2"].inserted


def test_no_credits_asks_nothing(monkeypatch):
    client, t = _setup(monkeypatch, {"status": "found"})
    from leads import skrapp_client
    monkeypatch.setattr(skrapp_client, "email_credits_left", lambda c: 0)
    assert "skipped" in sj.refind_bounced(client, now=NOW)
