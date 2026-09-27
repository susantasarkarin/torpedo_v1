"""
GOOGLE CSE RESERVE_QUERY_SLOT -- atomic, race-free daily/hourly budget
========================================================================

Covers leads/google_rate_limit.py's reserve_query_slot(), added 2026-09-26
after multiple concurrent lead-search workers (each tracking their own
per-job counter, not this shared one) fired 5 queries within 1.6 seconds
against the real 100/day cap -- the same check-then-act race already found
and fixed for outreach sends (_reserve_daily_send_slot).

A minimal fake Mongo collection implements only the operations this function
actually issues ($inc/$set/$setOnInsert via find_one_and_update, upsert,
return_document; plain $inc via update_one for the refund path), so these
tests exercise the real increment-then-check-then-refund logic without a
live Mongo.
"""
import os
import sys
from datetime import datetime
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import google_rate_limit as grl


class FakeUsageCollection:
    """Enough of a pymongo collection to exercise reserve_query_slot() for
    real: a single upserted doc per 'date', $inc/$set/$setOnInsert semantics."""

    def __init__(self):
        self.docs = {}

    def find_one_and_update(self, flt, update, upsert=False, return_document=None):
        key = flt["date"]
        doc = self.docs.get(key)
        if doc is None:
            if not upsert:
                return None
            doc = {"date": key, "total_queries": 0, "hourly_queries": {}}
            doc.update(update.get("$setOnInsert", {}))
            self.docs[key] = doc
        for path, amount in update.get("$inc", {}).items():
            if "." in path:
                top, sub = path.split(".", 1)
                doc.setdefault(top, {})
                doc[top][sub] = doc[top].get(sub, 0) + amount
            else:
                doc[path] = doc.get(path, 0) + amount
        doc.update(update.get("$set", {}))
        return dict(doc)

    def update_one(self, flt, update):
        key = flt["date"]
        doc = self.docs.get(key)
        if not doc:
            return
        for path, amount in update.get("$inc", {}).items():
            if "." in path:
                top, sub = path.split(".", 1)
                doc.setdefault(top, {})
                doc[top][sub] = doc[top].get(sub, 0) + amount
            else:
                doc[path] = doc.get(path, 0) + amount


@pytest.fixture
def fake_collection():
    coll = FakeUsageCollection()
    with patch.object(grl, "usage_collection", coll):
        yield coll


def _settings(**overrides):
    base = {"daily_limit": 100, "hourly_limit": 50, "rate_limit_enabled": True}
    base.update(overrides)
    return base


def test_first_reservation_of_the_day_succeeds(fake_collection):
    with patch.object(grl, "get_rate_limit_settings", return_value=_settings()):
        allowed, reason = grl.reserve_query_slot()
    assert allowed is True
    assert reason == "OK"


def test_reservation_actually_increments_the_shared_counter(fake_collection):
    with patch.object(grl, "get_rate_limit_settings", return_value=_settings()):
        grl.reserve_query_slot()
        grl.reserve_query_slot()
        doc = fake_collection.docs[grl.get_today_key()]
    assert doc["total_queries"] == 2


def test_disabled_rate_limiting_always_allows_and_never_touches_the_counter(fake_collection):
    with patch.object(grl, "get_rate_limit_settings", return_value=_settings(rate_limit_enabled=False)):
        allowed, reason = grl.reserve_query_slot()
    assert allowed is True
    assert fake_collection.docs == {}   # no reservation made at all


def test_daily_cap_refuses_the_101st_reservation_and_refunds_it(fake_collection):
    with patch.object(grl, "get_rate_limit_settings", return_value=_settings(daily_limit=100, hourly_limit=10_000)):
        for _ in range(100):
            allowed, _ = grl.reserve_query_slot()
            assert allowed is True
        allowed, reason = grl.reserve_query_slot()
    assert allowed is False
    assert "Daily quota exceeded" in reason
    # refunded: the counter must read exactly 100, not 101 -- an unrefunded
    # over-cap reservation would permanently under-count tomorrow's true usage
    doc = fake_collection.docs[grl.get_today_key()]
    assert doc["total_queries"] == 100


def test_hourly_cap_refuses_and_refunds_independently_of_daily(fake_collection):
    with patch.object(grl, "get_rate_limit_settings", return_value=_settings(daily_limit=10_000, hourly_limit=5)):
        for _ in range(5):
            allowed, _ = grl.reserve_query_slot()
            assert allowed is True
        allowed, reason = grl.reserve_query_slot()
    assert allowed is False
    assert "Hourly quota exceeded" in reason
    doc = fake_collection.docs[grl.get_today_key()]
    assert doc["hourly_queries"][str(grl.get_current_hour())] == 5


def test_a_refused_reservation_never_counts_against_a_later_successful_one(fake_collection):
    """Refund correctness: hitting the cap repeatedly must not corrupt the
    counter so that it never recovers (e.g. going negative or double-counting)."""
    with patch.object(grl, "get_rate_limit_settings", return_value=_settings(daily_limit=3, hourly_limit=10_000)):
        results = [grl.reserve_query_slot()[0] for _ in range(3)]
        assert results == [True, True, True]
        # Refused three more times in a row -- must stay refused, not flip
        # back to allowed from refund arithmetic drifting the counter down.
        for _ in range(3):
            allowed, _ = grl.reserve_query_slot()
            assert allowed is False
    doc = fake_collection.docs[grl.get_today_key()]
    assert doc["total_queries"] == 3


def test_concurrent_style_calls_never_overshoot_the_cap(fake_collection):
    """Simulates what actually happened live: several callers reserving in
    quick succession must collectively never exceed the cap, unlike the old
    check-then-record sequence."""
    with patch.object(grl, "get_rate_limit_settings", return_value=_settings(daily_limit=5, hourly_limit=10_000)):
        outcomes = [grl.reserve_query_slot()[0] for _ in range(20)]
    assert outcomes.count(True) == 5
    doc = fake_collection.docs[grl.get_today_key()]
    assert doc["total_queries"] == 5    # never overshoots, never undershoots
