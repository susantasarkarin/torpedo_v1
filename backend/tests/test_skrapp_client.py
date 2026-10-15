"""Skrapp replaces Hunter for lead email addresses (owner, 2026-10-15).

API per https://skrapp.io/api: GET api.skrapp.io/api/v2/find, X-Access-Key,
firstName/lastName/domain; quality.status valid|invalid|catch-all|unknown;
404 = not found, not charged.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

from leads import email_builder as eb
from leads import skrapp_client as sk

NOW = datetime(2026, 10, 15, 6, 0)


class _Col:
    def __init__(self, docs=None):
        self.docs = {d.get("_id", i): dict(d) for i, d in enumerate(docs or [])}

    def find_one(self, q, proj=None):
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in q.items()):
                return d
        return None

    def update_one(self, q, u, upsert=False):
        d = self.find_one(q)
        if d is None:
            d = dict(q)
            d.update(u.get("$setOnInsert", {}))
            self.docs[q.get("_id", len(self.docs) + 100)] = d
        d.update(u.get("$set", {}))
        for k, v in u.get("$inc", {}).items():
            d[k] = d.get(k, 0) + v
        for k, v in u.get("$addToSet", {}).items():
            d.setdefault(k, [])
            if v not in d[k]:
                d[k].append(v)


def _client(settings=None):
    return {"email_automation": {"skrapp_usage": _Col(), "skrapp_lookups": _Col(), "email_patterns": _Col()},
            "torpedo_settings": {"app_settings": _Col(settings or [])}}


def _resp(code, body=None):
    r = MagicMock(status_code=code)
    r.json.return_value = body or {}
    return r


def test_no_key_means_no_call(monkeypatch):
    for k in ("SKRAPP_API_KEY", "SKRAPP_API_KEY_1", "SKRAPP_API_KEY_2", "SKRAPP_API_KEY_3"):
        monkeypatch.delenv(k, raising=False)
    with patch.object(sk.requests, "get") as get:
        assert sk.find(_client(), "Jane", "Doe", "acme.com", now=NOW)["status"] == "not_configured"
    get.assert_not_called()


def test_request_shape_and_valid_answer(monkeypatch):
    monkeypatch.setenv("SKRAPP_API_KEY_1", "key-1")
    body = {"email": "Jane.Doe@acme.com", "pattern": "{first}.{last}", "quality": {"status": "valid"}}
    with patch.object(sk.requests, "get", return_value=_resp(200, body)) as get:
        out = sk.find(_client(), "Jane", "Doe", "acme.com", now=NOW)
    url, = get.call_args.args
    assert url == "https://api.skrapp.io/api/v2/find"
    assert get.call_args.kwargs["params"] == {"firstName": "Jane", "lastName": "Doe", "domain": "acme.com"}
    assert get.call_args.kwargs["headers"] == {"X-Access-Key": "key-1"}
    assert out == {"status": "found", "email": "jane.doe@acme.com", "pattern": "{first}.{last}", "quality": "valid"}


def test_a_person_costs_one_lookup(monkeypatch):
    monkeypatch.setenv("SKRAPP_API_KEY_1", "k")
    c = _client()
    with patch.object(sk.requests, "get", return_value=_resp(404)) as get:
        assert sk.find(c, "Jane", "Doe", "acme.com", now=NOW)["status"] == "not_found"
        assert sk.find(c, "Jane", "Doe", "acme.com", now=NOW)["status"] == "not_found"
    assert get.call_count == 1
    # a 404 is not charged
    assert c["email_automation"]["skrapp_usage"].find_one({"account_id": "1", "month": "2026-10"}) is None


def test_monthly_limit_and_key_rotation(monkeypatch):
    monkeypatch.setenv("SKRAPP_API_KEY_1", "k1")
    monkeypatch.setenv("SKRAPP_API_KEY_2", "k2")
    monkeypatch.setenv("SKRAPP_MONTHLY_LIMIT", "2")
    c = _client()
    c["email_automation"]["skrapp_usage"] = _Col([{"_id": "a", "account_id": "1", "month": "2026-10", "searches_used": 2}])
    with patch.object(sk.requests, "get", return_value=_resp(404)) as get:
        sk.find(c, "A", "B", "x.com", now=NOW)
    assert get.call_args.kwargs["headers"] == {"X-Access-Key": "k2"}
    c["email_automation"]["skrapp_usage"] = _Col([
        {"_id": "a", "account_id": "1", "month": "2026-10", "searches_used": 2},
        {"_id": "b", "account_id": "2", "month": "2026-10", "searches_used": 2}])
    with patch.object(sk.requests, "get") as get:
        assert sk.find(c, "C", "D", "x.com", now=NOW)["status"] == "monthly_limit"
    get.assert_not_called()


def test_builder_uses_only_a_valid_skrapp_address(monkeypatch):
    monkeypatch.setenv("SKRAPP_API_KEY_1", "k")
    for quality, status, has_email in (("valid", "built", True), ("catch-all", "skrapp_unverified", False),
                                        ("unknown", "skrapp_unverified", False)):
        c = _client()
        body = {"email": "jane.doe@acme.com", "pattern": "{first}.{last}", "quality": {"status": quality}}
        with patch.object(sk.requests, "get", return_value=_resp(200, body)):
            out = eb.skrapp_address(c, "jane", "doe", "acme.com", NOW, bounced=set())
        assert out["rec"]["status"] == status
        assert ("email" in out["set_fields"]) is has_email
    assert out_set_source(c) == "skrapp"


def out_set_source(c):
    return c["email_automation"]["email_patterns"].find_one({"domain": "acme.com"})["source"]


def test_builder_never_takes_a_bounced_or_off_domain_skrapp_address(monkeypatch):
    monkeypatch.setenv("SKRAPP_API_KEY_1", "k")
    body = {"email": "jane.doe@acme.com", "quality": {"status": "valid"}}
    with patch.object(sk.requests, "get", return_value=_resp(200, body)):
        assert eb.skrapp_address(_client(), "jane", "doe", "acme.com", NOW,
                                 bounced={"jane.doe@acme.com"})["rec"]["status"] == "bounced_before"
    body = {"email": "jane.doe@other.com", "quality": {"status": "valid"}}
    with patch.object(sk.requests, "get", return_value=_resp(200, body)):
        assert eb.skrapp_address(_client(), "jane", "doe", "acme.com", NOW, bounced=set())["rec"]["status"] == "ai_doubt"


def test_waiting_on_skrapp_retries_tomorrow(monkeypatch):
    for k in ("SKRAPP_API_KEY", "SKRAPP_API_KEY_1", "SKRAPP_API_KEY_2", "SKRAPP_API_KEY_3"):
        monkeypatch.delenv(k, raising=False)
    out = eb.skrapp_address(_client(), "jane", "doe", "acme.com", NOW, bounced=set())
    assert out["rec"] == {"status": "no_structure", "why": "skrapp_not_configured"}
