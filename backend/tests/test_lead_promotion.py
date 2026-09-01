"""
Lead promotion: watermark resumption and the run cap.

This module decides how much cold, never-contacted traffic joins the mailable
pool each day, so its two safety properties are worth pinning down: the cap
bounds a run, and the watermark makes runs resume rather than repeat. It also
shipped with a 7-day lookback window that could never match anything, which is
why the "resumes regardless of age" case is tested explicitly.
"""

from datetime import datetime, timedelta

import pytest

from services import panel_lead_promotion as P


@pytest.fixture
def fake_data(monkeypatch):
    """Stub the two collections so no Mongo is required."""
    rows = [
        {"_id": f"user{i}@example.com",
         "countryCode": "IN",
         "createdAt": datetime(2026, 2, 1) + timedelta(days=i)}
        for i in range(20)
    ]

    state = {"pipelines": [], "upserted": [], "watermark": None}

    class _Cursor:
        """Stands in for a pymongo CommandCursor, which the code closes."""
        def __init__(self, items):
            self._it = iter(items)

        def __iter__(self):
            return self._it

        def close(self):
            pass

    class _Traffic:
        def aggregate(self, pipeline, **_kw):
            state["pipelines"].append(pipeline)
            match = pipeline[0]["$match"]
            created = match.get("createdAt") or {}
            after = created.get("$gt")
            out = rows if after is None else [r for r in rows if r["createdAt"] > after]
            return _Cursor(out)

    class _Panelists:
        def count_documents(self, q):
            return 0  # nothing pre-existing

        def bulk_write(self, ops, **_kw):
            state["upserted"].extend(ops)
            return type("R", (), {"upserted_count": len(ops)})()

    monkeypatch.setattr(P, "traffic_collection", _Traffic())
    monkeypatch.setattr(P, "panelists_collection", _Panelists())
    monkeypatch.setattr(P, "get_watermark", lambda: state["watermark"])
    monkeypatch.setattr(P, "set_watermark",
                        lambda v: state.__setitem__("watermark", v))
    return state


def test_cap_bounds_a_run(fake_data):
    r = P.promote_traffic_leads_to_panelists(limit=5)
    assert r["scanned"] == 5
    assert r["capped"] is True


def test_cap_of_zero_disables_instead_of_unleashing(fake_data):
    """0 must be the kill switch. It used to be falsy and therefore meant
    'no cap', so halting the job would have dumped the whole backlog."""
    r = P.promote_traffic_leads_to_panelists(limit=0)
    assert r["disabled"] is True
    assert r["scanned"] == 0
    assert fake_data["upserted"] == []


def test_negative_cap_means_unlimited(fake_data):
    r = P.promote_traffic_leads_to_panelists(limit=-1)
    assert r["scanned"] == 20
    assert r["capped"] is False


def test_watermark_advances_and_next_run_resumes(fake_data):
    first = P.promote_traffic_leads_to_panelists(limit=5, use_watermark=True)
    assert first["scanned"] == 5
    assert fake_data["watermark"] == datetime(2026, 2, 5)

    second = P.promote_traffic_leads_to_panelists(limit=5, use_watermark=True)
    assert second["scanned"] == 5
    # Resumed rather than repeated.
    assert fake_data["watermark"] == datetime(2026, 2, 10)


def test_watermark_uses_strict_greater_than(fake_data):
    """$gte would re-promote the boundary row on every single run."""
    P.promote_traffic_leads_to_panelists(limit=5, use_watermark=True)
    P.promote_traffic_leads_to_panelists(limit=5, use_watermark=True)
    second_match = fake_data["pipelines"][-1][0]["$match"]
    assert "$gt" in second_match["createdAt"]
    assert "$gte" not in second_match["createdAt"]


def test_dry_run_neither_writes_nor_moves_the_watermark(fake_data):
    r = P.promote_traffic_leads_to_panelists(limit=5, dry_run=True, use_watermark=True)
    assert fake_data["upserted"] == []
    assert fake_data["watermark"] is None
    assert r["watermark_advanced_to"] is None
    # Preview must still report what it WOULD add, not zero.
    assert r["inserted"] == 5


def test_old_records_are_still_reachable(fake_data):
    """The whole point of the watermark: age must not exclude anything.
    The previous 7-day lookback silently skipped a 37K backlog for months."""
    r = P.promote_traffic_leads_to_panelists(limit=-1, use_watermark=True)
    assert r["scanned"] == 20  # all of them, oldest dated Feb 2026


def test_promoted_records_are_marked_as_traffic_leads(fake_data):
    P.promote_traffic_leads_to_panelists(limit=1)
    doc = fake_data["upserted"][0]._doc["$setOnInsert"]
    assert doc["source"] == "traffic_lead"
    assert doc["double_opt_in_completed"] is False
    assert doc["country"] == "India"  # ISO code mapped to the CSV-style name
