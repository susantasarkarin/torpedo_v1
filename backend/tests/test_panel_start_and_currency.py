"""Panel member survey start (/takesurvey link) and reward currency by country."""
import pytest
from bson import ObjectId
from fastapi import HTTPException

from routers import panel as pn


class FakeSurveys:
    def __init__(self, doc):
        self.doc = doc

    def find_one(self, q):
        return self.doc if self.doc and q.get("_id") == self.doc["_id"] and q.get("status") == "active" else None


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_currency_follows_country():
    assert pn.currency_for_country("GB") == "GBP"
    assert pn.currency_for_country("United Kingdom") == "GBP"
    assert pn.currency_for_country("us") == "USD"
    assert pn.currency_for_country("IN") == "INR"
    assert pn.currency_for_country("France") == "INR"
    assert pn.currency_for_country(None) == "INR"


def test_balance_uses_member_currency(monkeypatch):
    class R:
        def aggregate(self, p):
            return iter([])
    monkeypatch.setattr(pn, "rewards_collection", R())
    res = _run(pn.get_rewards_balance({"_id": ObjectId(), "country": "GB", "rewards_balance": 5}))
    assert res.currency == "GBP" and res.balance == 5


def test_start_survey_builds_takesurvey_link_with_panel_id(monkeypatch):
    sid, mid = ObjectId(), ObjectId()
    monkeypatch.setattr(pn, "surveys_collection", FakeSurveys({"_id": sid, "status": "active", "project_number": "P123"}))
    monkeypatch.setenv("FRONTEND_URL", "https://example.test")
    monkeypatch.setenv("SFW_PANEL_VENDOR_IDS", "2656")
    out = _run(pn.start_survey(str(sid), {"_id": mid, "country": "GB"}))
    from urllib.parse import urlparse, parse_qs
    u = urlparse(out["url"])
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert u.path == "/takesurvey" and out["redirect_url"] == out["url"]
    assert q["pid"] == "P123" and q["vid"] == "2656" and q["cc"] == "GB" and q["panel"] == str(mid) and q["rid"]


def test_start_survey_unknown_is_404(monkeypatch):
    monkeypatch.setattr(pn, "surveys_collection", FakeSurveys(None))
    for bad in ("nope", str(ObjectId())):
        with pytest.raises(HTTPException) as e:
            _run(pn.start_survey(bad, {"_id": ObjectId(), "country": "IN"}))
        assert e.value.status_code == 404
