"""Panel overview proxy (Torpedo side): survey attempts handed to the Panel,
the alerts strip, and the members list pre-filtered by journey stage."""
from datetime import datetime

import pytest

from routers import panel_admin as pa


class FakeTraffic:
    def __init__(self, rows, counts=None):
        self.rows = rows
        self.counts = counts or []
        self.count_queries = []

    def aggregate(self, pipeline):
        return iter(self.rows)

    def count_documents(self, query):
        self.count_queries.append(query)
        return self.counts.pop(0) if self.counts else 0


@pytest.fixture
def calls(monkeypatch):
    sent = []
    monkeypatch.setattr(pa, "verify_admin_session", lambda request: "admin")
    monkeypatch.setattr(pa, "_sfw_write", lambda method, path, payload=None: sent.append((method, path, payload)) or {"ok": True, "path": path})
    monkeypatch.setattr(pa, "_sfw_get", lambda path, params=None: (
        {"members": [{"country": "India"}, {"country": "IN"}, {"country": "United States"}]} if path == "/profiling-flags"
        else {"path": path, "params": params}))
    return sent


def test_attempts_grouped_per_panelist_with_raw_statuses(monkeypatch):
    t1, t2 = datetime(2026, 11, 18, 10), datetime(2026, 11, 19, 9)
    monkeypatch.setattr(pa, "traffic_collection", FakeTraffic([
        {"_id": {"p": "SFW1", "s": "TERMINATED"}, "n": 3, "n30": 2, "last": t1},
        {"_id": {"p": "SFW1", "s": "OVERQUOTA"}, "n": 1, "n30": 0, "last": t2},
        {"_id": {"p": "SFW2"}, "n": 2, "last": t1},  # no status recorded
    ]))
    out = pa._panel_attempts()
    assert out["SFW1"] == {"attempts": 4, "statuses": {"TERMINATED": 3, "OVERQUOTA": 1}, "lastAt": t2.isoformat() + "Z",
                           "last30": {"attempts": 2, "statuses": {"TERMINATED": 2}}}
    assert out["SFW2"]["statuses"] == {"UNKNOWN": 2}


def test_member_funnel_sends_attempts_and_adds_alerts(monkeypatch, calls):
    monkeypatch.setattr(pa, "traffic_collection", FakeTraffic([{"_id": {"p": "SFW1", "s": "COMPLETE"}, "n": 1, "last": None}], counts=[1, 2]))
    data = pa.get_member_funnel(request=None, country="", days=30)
    method, path, payload = calls[0]
    assert (method, path) == ("POST", "/member-funnel")
    assert payload["attempts"]["SFW1"]["statuses"] == {"COMPLETE": 1} and payload["days"] == 30
    assert data["alerts"] == {"securityTermsToday": 1, "securityTermsWeek": 2, "flaggedProfiles": 3}


def test_alerts_follow_the_country_filter(monkeypatch, calls):
    fake = FakeTraffic([], counts=[0, 1])
    monkeypatch.setattr(pa, "traffic_collection", fake)
    alerts = pa._overview_alerts("IN")
    assert alerts["flaggedProfiles"] == 2  # "India" and "IN", not "United States"
    assert all("$or" in q for q in fake.count_queries)


def test_members_list_by_stage_goes_through_the_funnel(monkeypatch, calls):
    monkeypatch.setattr(pa, "traffic_collection", FakeTraffic([]))
    pa.get_sfwpanel_panelists(request=None, page=2, limit=25, search="", country="IN", sort_by="createdAt", order="desc", stage="membership", days=0)
    method, path, payload = calls[0]
    assert (method, path) == ("POST", "/member-funnel/members")
    assert payload["stage"] == "membership" and payload["country"] == "IN" and payload["page"] == 2


def test_members_list_without_stage_is_unchanged(monkeypatch, calls):
    out = pa.get_sfwpanel_panelists(request=None, page=1, limit=20, search="", country="", sort_by="createdAt", order="desc", stage="", days=0)
    assert out["path"] == "/panelists" and not calls


def test_member_funnel_cached_per_filter_and_fresh_skips_cache(monkeypatch, calls):
    monkeypatch.setattr(pa, "traffic_collection", FakeTraffic([]))
    pa._OVERVIEW_CACHE.clear()
    pa.get_member_funnel(request=None, country="US", days=7)
    pa.get_member_funnel(request=None, country="US", days=7)
    assert len([c for c in calls if c[1] == "/member-funnel"]) == 1  # second call served from cache
    pa.get_member_funnel(request=None, country="GB", days=7)
    assert len([c for c in calls if c[1] == "/member-funnel"]) == 2  # another filter computes
    pa.get_member_funnel(request=None, country="US", days=7, fresh=1)
    assert len([c for c in calls if c[1] == "/member-funnel"]) == 3  # fresh=1 recomputes


def test_sfw_calls_reuse_one_session_per_thread():
    assert pa._sfw_session() is pa._sfw_session()


def test_members_list_adds_attempts_and_allows_500(monkeypatch):
    monkeypatch.setattr(pa, "verify_admin_session", lambda request: "admin")
    monkeypatch.setattr(pa, "traffic_collection", FakeTraffic([{"_id": {"p": "SFW1", "s": "COMPLETE"}, "n": 3, "last": None}]))
    rows = {"panelists": [{"panelistId": "SFW1"}, {"panelistId": "SFW9"}], "total": 2}
    seen = {}
    monkeypatch.setattr(pa, "_sfw_get", lambda path, params=None: seen.update(params=params) or {k: [dict(r) for r in v] if k == "panelists" else v for k, v in rows.items()})
    out = pa.get_sfwpanel_panelists(request=None, page=1, limit=500, search="", country="", sort_by="createdAt", order="desc", stage="", days=0)
    assert [r["attempts"] for r in out["panelists"]] == [3, 0] and seen["params"]["limit"] == 500


def test_stage_members_list_adds_attempts(monkeypatch):
    monkeypatch.setattr(pa, "verify_admin_session", lambda request: "admin")
    monkeypatch.setattr(pa, "traffic_collection", FakeTraffic([{"_id": {"p": "SFW1", "s": "COMPLETE"}, "n": 2, "last": None}]))
    monkeypatch.setattr(pa, "_sfw_write", lambda m, p, payload=None: {"panelists": [{"panelistId": "SFW1"}, {"panelistId": "X"}]})
    out = pa.get_sfwpanel_panelists(request=None, page=1, limit=500, search="", country="", sort_by="createdAt", order="desc", stage="membership", days=0)
    assert [r["attempts"] for r in out["panelists"]] == [2, 0]


def test_limit_cap_is_500():
    import inspect
    limit = inspect.signature(pa.get_sfwpanel_panelists).parameters["limit"].default
    assert any(getattr(m, "le", None) == 500 for m in limit.metadata)


def test_flag_review_proxies_pass_the_admin_username(calls):
    pa.clear_all_profiling_flags(request=None, user_id="u1")
    pa.suspend_member(request=None, user_id="u1", payload={"reason": "  Fake answers "})
    pa.unsuspend_member(request=None, user_id="u1")
    assert calls == [
        ("POST", "/profiling-flags/u1/clear-all", {"by": "admin"}),
        ("POST", "/members/u1/suspend", {"reason": "Fake answers", "by": "admin"}),
        ("POST", "/members/u1/unsuspend", {"by": "admin"}),
    ]


def test_suspend_requires_a_reason(calls):
    from fastapi import HTTPException
    for bad in ({}, {"reason": "   "}, {"reason": "x" * 301}):
        with pytest.raises(HTTPException) as e:
            pa.suspend_member(request=None, user_id="u1", payload=bad)
        assert e.value.status_code == 400
    assert calls == []
