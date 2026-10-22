"""2026-10-22: all 199 bounces of the day went to addresses already known dead
(bounced send history, or the lead marked bounced) -- the send gate only read
outreach_bounce_suppression."""
import routers.cold_outreach_router as r


class _C:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, q, proj=None):
        for d in self.docs:
            ok = True
            for k, v in q.items():
                ok &= (d.get(k) in v["$in"]) if isinstance(v, dict) else d.get(k) == v
            if ok:
                return d
        return None


def _dbs(sends=(), leads=(), supp=()):
    tdb = {"outreach_sends_v2": _C(list(sends))}
    ldb = {"leads_enriched": _C(list(leads)), "suppression_list": _C(list(supp))}
    return tdb, ldb


def test_earlier_bounced_send_blocks(monkeypatch):
    tdb, ldb = _dbs(sends=[{"email": "a@x.com", "status": "bounced"}])
    monkeypatch.setattr(r, "get_leads_db", lambda: ldb)
    assert "bounced before" in r._known_bounce(tdb, "a@x.com")


def test_lead_marked_bounced_blocks(monkeypatch):
    tdb, ldb = _dbs(leads=[{"email": "a@x.com", "email_status": "Bounced"}])
    monkeypatch.setattr(r, "get_leads_db", lambda: ldb)
    assert r._known_bounce(tdb, "a@x.com")


def test_clean_address_passes(monkeypatch):
    tdb, ldb = _dbs(sends=[{"email": "a@x.com", "status": "sent"}],
                    leads=[{"email": "a@x.com", "email_status": "Valid"}])
    monkeypatch.setattr(r, "get_leads_db", lambda: ldb)
    assert r._known_bounce(tdb, "a@x.com") == ""
