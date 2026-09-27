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


class FakeMonthlyUsageCollection:
    """Same shape as FakeUsageCollection, keyed by 'month' instead of 'date'."""

    def __init__(self):
        self.docs = {}

    def find_one_and_update(self, flt, update, upsert=False, return_document=None):
        key = flt["month"]
        doc = self.docs.get(key)
        if doc is None:
            if not upsert:
                return None
            doc = {"month": key, "billable_queries": 0}
            doc.update(update.get("$setOnInsert", {}))
            self.docs[key] = doc
        for path, amount in update.get("$inc", {}).items():
            doc[path] = doc.get(path, 0) + amount
        doc.update(update.get("$set", {}))
        return dict(doc)

    def update_one(self, flt, update):
        key = flt["month"]
        doc = self.docs.get(key)
        if not doc:
            return
        for path, amount in update.get("$inc", {}).items():
            doc[path] = doc.get(path, 0) + amount

    def find_one(self, flt):
        return self.docs.get(flt["month"])


@pytest.fixture
def fake_collection():
    coll = FakeUsageCollection()
    with patch.object(grl, "usage_collection", coll):
        yield coll


@pytest.fixture
def fake_monthly_collection():
    coll = FakeMonthlyUsageCollection()
    with patch.object(grl, "monthly_usage_collection", coll):
        yield coll


def _settings(**overrides):
    base = {
        "daily_limit": 100,
        "hourly_limit": 50,
        "rate_limit_enabled": True,
        "monthly_budget_usd": 10.0,
        "cost_per_1000_queries": 5.0,
        "monthly_paid_query_limit": 2000,
    }
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


def test_the_101st_query_becomes_billable_and_succeeds_when_monthly_budget_has_room(
        fake_collection, fake_monthly_collection):
    """daily_limit is the free tier, not a hard stop: the 101st reservation
    still succeeds, but draws from the separate monthly paid budget instead
    of the daily counter's own limit."""
    with patch.object(grl, "get_rate_limit_settings",
                       return_value=_settings(daily_limit=100, hourly_limit=10_000,
                                              monthly_paid_query_limit=2000)):
        for _ in range(100):
            allowed, _ = grl.reserve_query_slot()
            assert allowed is True
        allowed, reason = grl.reserve_query_slot()
    assert allowed is True
    assert reason == "OK"
    assert fake_collection.docs[grl.get_today_key()]["total_queries"] == 101
    assert fake_monthly_collection.docs[grl.get_month_key()]["billable_queries"] == 1


def test_a_free_query_never_touches_the_monthly_collection(fake_collection, fake_monthly_collection):
    with patch.object(grl, "get_rate_limit_settings",
                       return_value=_settings(daily_limit=100, hourly_limit=10_000)):
        for _ in range(50):
            allowed, _ = grl.reserve_query_slot()
            assert allowed is True
    assert fake_monthly_collection.docs == {}


def test_billable_queries_are_refused_once_the_monthly_budget_is_exhausted(
        fake_collection, fake_monthly_collection):
    with patch.object(grl, "get_rate_limit_settings",
                       return_value=_settings(daily_limit=100, hourly_limit=10_000,
                                              monthly_paid_query_limit=1)):
        for _ in range(101):  # 100 free + the month's one paid query
            allowed, _ = grl.reserve_query_slot()
            assert allowed is True
        allowed, reason = grl.reserve_query_slot()
    assert allowed is False
    assert "Monthly CSE budget exceeded" in reason
    # refunded on both sides -- a refused billable query must not count
    # against tomorrow's daily total or next month's budget
    assert fake_collection.docs[grl.get_today_key()]["total_queries"] == 101
    assert fake_monthly_collection.docs[grl.get_month_key()]["billable_queries"] == 1


def test_hourly_cap_refuses_a_would_be_billable_query_before_touching_monthly(
        fake_collection, fake_monthly_collection):
    """Hourly is pure burst protection and is checked before any monthly
    reservation is attempted, whether or not the query would have been
    billable."""
    with patch.object(grl, "get_rate_limit_settings",
                       return_value=_settings(daily_limit=0, hourly_limit=0,
                                              monthly_paid_query_limit=2000)):
        allowed, reason = grl.reserve_query_slot()
    assert allowed is False
    assert "Hourly quota exceeded" in reason
    assert fake_monthly_collection.docs == {}


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


def test_a_refused_reservation_never_counts_against_a_later_successful_one(
        fake_collection, fake_monthly_collection):
    """Refund correctness: hitting the cap repeatedly must not corrupt the
    counter so that it never recovers (e.g. going negative or double-counting).
    monthly_paid_query_limit=0 so crossing daily_limit still refuses -- this
    test is about refund arithmetic, not the monthly-budget behavior."""
    with patch.object(grl, "get_rate_limit_settings",
                       return_value=_settings(daily_limit=3, hourly_limit=10_000,
                                              monthly_paid_query_limit=0)):
        results = [grl.reserve_query_slot()[0] for _ in range(3)]
        assert results == [True, True, True]
        # Refused three more times in a row -- must stay refused, not flip
        # back to allowed from refund arithmetic drifting the counter down.
        for _ in range(3):
            allowed, _ = grl.reserve_query_slot()
            assert allowed is False
    doc = fake_collection.docs[grl.get_today_key()]
    assert doc["total_queries"] == 3


def test_concurrent_style_calls_never_overshoot_the_cap(fake_collection, fake_monthly_collection):
    """Simulates what actually happened live: several callers reserving in
    quick succession must collectively never exceed the cap, unlike the old
    check-then-record sequence. monthly_paid_query_limit=0 keeps this test
    about the daily/hourly race, not the monthly-budget behavior."""
    with patch.object(grl, "get_rate_limit_settings",
                       return_value=_settings(daily_limit=5, hourly_limit=10_000,
                                              monthly_paid_query_limit=0)):
        outcomes = [grl.reserve_query_slot()[0] for _ in range(20)]
    assert outcomes.count(True) == 5
    doc = fake_collection.docs[grl.get_today_key()]
    assert doc["total_queries"] == 5    # never overshoots, never undershoots


def test_derive_monthly_paid_query_limit_matches_the_10_dollar_ask():
    """2026-09-27 ask: max $10/month at $5 per 1000 queries -- 2000 paid
    queries/month, on top of the existing 100/day free tier."""
    assert grl._derive_monthly_paid_query_limit(10.0, 5.0) == 2000


def test_derive_monthly_paid_query_limit_never_divides_by_zero():
    assert grl._derive_monthly_paid_query_limit(10.0, 0) == 0


def test_real_default_settings_derive_the_2000_query_monthly_limit():
    """No DB override, no env override: get_rate_limit_settings()'s hardcoded
    defaults must resolve to exactly the $10/month, 2000-paid-query budget."""
    with patch.object(grl, "_app_settings", MagicMockNoConfig()), \
         patch.dict(os.environ, {}, clear=False):
        for var in ("GOOGLE_CSE_MONTHLY_BUDGET_USD", "GOOGLE_CSE_COST_PER_1000_QUERIES"):
            os.environ.pop(var, None)
        settings = grl.get_rate_limit_settings()
    assert settings["monthly_budget_usd"] == 10.0
    assert settings["cost_per_1000_queries"] == 5.0
    assert settings["monthly_paid_query_limit"] == 2000


class MagicMockNoConfig:
    def find_one(self, *args, **kwargs):
        return None
