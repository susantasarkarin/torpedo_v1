"""
lead_gen_mcp/search.py -- centralized CSE quota enforcement
=============================================================

lead_gen_mcp is a separate, live production service (torpedo-lead-gen-mcp.
service) that calls Google CSE directly. It used to gate requests with its
own can_make_query()/record_query() pair -- check-then-act, non-atomic, and
checked once per query rather than once per actual request -- while sharing
the SAME google_cse_usage/google_cse_monthly_usage collections as the
primary search paths (leads/ingestion.py, leads/ingestion_vm.py), which use
the atomic reserve_query_slot(). Two different gating mechanisms writing to
the same counters is exactly the race the atomic reservation was built to
prevent (2026-09-26 incident: concurrent workers each with their own
check-then-act view of the budget overshot the real 100/day cap).

Fixed 2026-09-27: lead_gen_mcp/search.py now calls the same
reserve_query_slot() every other caller uses, invoked before EVERY page
request (not once per query), so a multi-page batch can't slip past the
daily/hourly/monthly caps between an upfront check and later pages.

These tests mock reserve_query_slot and _fetch_page directly (no live HTTP)
to verify the sequencing and gating behavior of run_search_batch() itself.
`database` is stubbed before import (matching leads/ingestion.py's test
convention) since search.py's _load_rate_limiter() executes
google_rate_limit.py at import time, which otherwise opens a real MongoDB
connection.
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def search(monkeypatch):
    """Import lead_gen_mcp.search with Mongo stubbed out (its rate-limiter
    loader execs google_rate_limit.py, which builds a real client at import)."""
    fake_db = types.ModuleType("database")
    fake_db.get_client = lambda: MagicMock()
    monkeypatch.setitem(sys.modules, "database", fake_db)
    sys.modules.pop("lead_gen_mcp.search", None)
    from lead_gen_mcp import search as mod
    yield mod
    sys.modules.pop("lead_gen_mcp.search", None)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _items(n):
    """n fake GCSE result items, each a real LinkedIn profile link so
    _parse_serp_snippet doesn't filter them out."""
    return [
        {"link": f"https://www.linkedin.com/in/person{i}",
         "title": f"Person {i} - Manager at Co | LinkedIn",
         "snippet": "..."}
        for i in range(n)
    ]


def test_old_check_then_act_pair_is_gone(search):
    """can_make_query/record_query must no longer exist on this module --
    reserve_query_slot is the only quota gate."""
    assert not hasattr(search, "can_make_query")
    assert not hasattr(search, "record_query")
    assert hasattr(search, "reserve_query_slot")


def test_reserves_a_slot_before_every_page_not_once_per_query(search):
    """A 2-page batch must reserve twice, not once for the whole query --
    the exact gap the old can_make_query()-once-then-loop pattern had."""
    with patch.object(search, "reserve_query_slot", return_value=(True, "OK")) as reserve, \
         patch.object(search, "_fetch_page", new=AsyncMock(return_value=_items(10))), \
         patch.object(search, "QUERY_DELAY_SECONDS", 0):
        results = _run(search.run_search_batch(["ceo mumbai"], pages_per_query=2))
    assert reserve.call_count == 2
    assert results[0].quota_consumed == 2


def test_a_refused_reservation_stops_further_pages_for_that_query(search):
    """Page 1 allowed, page 2 refused -- must stop immediately, keep page 1's
    results, and report the refusal reason, not silently continue."""
    with patch.object(search, "reserve_query_slot",
                       side_effect=[(True, "OK"), (False, "Daily quota exceeded (100/day)")]), \
         patch.object(search, "_fetch_page", new=AsyncMock(return_value=_items(10))) as fetch, \
         patch.object(search, "QUERY_DELAY_SECONDS", 0):
        results = _run(search.run_search_batch(["ceo mumbai"], pages_per_query=5))
    assert results[0].quota_consumed == 1
    assert "Rate limited" in results[0].error
    assert "Daily quota exceeded" in results[0].error
    assert fetch.await_count == 1


def test_a_query_never_even_starts_a_page_once_refused_up_front(search):
    """The very first reservation being refused must produce zero fetched
    pages and a clear error, not a silent empty success."""
    with patch.object(search, "reserve_query_slot", return_value=(False, "Monthly CSE budget exceeded")), \
         patch.object(search, "_fetch_page", new=AsyncMock(return_value=_items(10))) as fetch, \
         patch.object(search, "QUERY_DELAY_SECONDS", 0):
        results = _run(search.run_search_batch(["ceo mumbai"], pages_per_query=3))
    assert results[0].quota_consumed == 0
    assert results[0].results == []
    assert "Monthly CSE budget exceeded" in results[0].error
    fetch.assert_not_awaited()


def test_pages_per_query_is_capped_at_10_regardless_of_caller_input(search):
    """run_search_batch already clamps pages_per_query to 10; confirm a
    caller asking for far more can never fetch (or reserve) more than 10
    pages for one query."""
    with patch.object(search, "reserve_query_slot", return_value=(True, "OK")) as reserve, \
         patch.object(search, "_fetch_page", new=AsyncMock(return_value=_items(10))), \
         patch.object(search, "QUERY_DELAY_SECONDS", 0):
        results = _run(search.run_search_batch(["ceo mumbai"], pages_per_query=50))
    assert reserve.call_count == 10
    assert results[0].quota_consumed == 10


def test_short_of_a_full_page_stops_pagination_without_over_reserving(search):
    """Fewer than 10 items on a page means no more results -- must stop
    there rather than reserving another slot it doesn't need."""
    with patch.object(search, "reserve_query_slot", return_value=(True, "OK")) as reserve, \
         patch.object(search, "_fetch_page", new=AsyncMock(return_value=_items(3))), \
         patch.object(search, "QUERY_DELAY_SECONDS", 0):
        results = _run(search.run_search_batch(["ceo mumbai"], pages_per_query=5))
    assert reserve.call_count == 1
    assert results[0].quota_consumed == 1
    assert len(results[0].results) == 3


class _FakeResponse:
    def __init__(self, items):
        self._items = items

    def raise_for_status(self):
        pass

    def json(self):
        return {"items": self._items}


class _FakeAsyncClient:
    def __init__(self):
        self.calls = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return _FakeResponse(_items(len(self.calls)))


def test_a_single_fetch_page_call_always_requests_exactly_10_results(search):
    """_fetch_page is the one place that actually talks to Google -- its
    'num' param must always be the hard per-call max, matching
    MAX_RESULTS_PER_CALL in leads/ingestion.py and leads/ingestion_vm.py."""
    client = _FakeAsyncClient()
    _run(search._fetch_page(client, "site:linkedin.com ceo", start=1, recency_filter=None))
    assert client.calls[0]["num"] == 10
