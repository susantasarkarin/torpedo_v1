"""
perform_google_search() STOPS ON A REFUSED RESERVATION, DOESN'T RACE TO A 429
================================================================================

Covers the 2026-09-26 fix in leads/ingestion.py: reserve_query_slot() is
checked before every page request, not just reacted to after a real 429. A
refused reservation must (a) never fire the HTTP request it was guarding, and
(b) set the same 24h pause flag a reactive 429 would, so leads/router.py's
existing "don't mark this query exhausted, just idle" protection covers this
path too.
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def ingestion(monkeypatch):
    """Import leads.ingestion with Mongo stubbed out (it builds handles at import)."""
    fake_db = types.ModuleType("database")
    fake_db.get_client = lambda: MagicMock()
    monkeypatch.setitem(sys.modules, "database", fake_db)
    sys.modules.pop("leads.ingestion", None)
    from leads import ingestion as mod
    yield mod
    sys.modules.pop("leads.ingestion", None)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_refused_reservation_never_fires_the_http_request(ingestion):
    fake_client = MagicMock()
    fake_client.get = AsyncMock()
    fake_client_cm = MagicMock()
    fake_client_cm.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(ingestion, "_is_cse_paused", return_value=False), \
         patch.object(ingestion, "get_google_api_credentials", return_value=("key", "cx")), \
         patch("httpx.AsyncClient", return_value=fake_client_cm), \
         patch.object(ingestion, "_pause_cse_for_24h") as pause_mock, \
         patch("leads.google_rate_limit.reserve_query_slot", return_value=(False, "Daily quota exceeded")):
        results = _run(ingestion.perform_google_search("test query", num_results=10))

    assert results == []
    fake_client.get.assert_not_called()
    pause_mock.assert_called_once()


def test_refused_reservation_stops_further_pages_but_keeps_earlier_results(ingestion):
    """Page 1 succeeds, page 2's reservation is refused -- must return page 1's
    results, not discard them, and must not attempt page 2's HTTP call."""
    page1_response = MagicMock(status_code=200)
    page1_response.json.return_value = {"items": [{"title": "Lead A"}]}

    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=page1_response)
    fake_client_cm = MagicMock()
    fake_client_cm.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client_cm.__aexit__ = AsyncMock(return_value=False)

    reservations = iter([(True, "OK"), (False, "Daily quota exceeded")])

    with patch.object(ingestion, "_is_cse_paused", return_value=False), \
         patch.object(ingestion, "get_google_api_credentials", return_value=("key", "cx")), \
         patch("httpx.AsyncClient", return_value=fake_client_cm), \
         patch.object(ingestion, "_pause_cse_for_24h"), \
         patch("leads.google_rate_limit.reserve_query_slot", side_effect=lambda: next(reservations)):
        results = _run(ingestion.perform_google_search("test query", num_results=20))

    assert results == [{"title": "Lead A"}]
    assert fake_client.get.call_count == 1   # page 2 never attempted


def test_granted_reservation_lets_the_request_through_as_before(ingestion):
    ok_response = MagicMock(status_code=200)
    ok_response.json.return_value = {"items": [{"title": "Lead A"}]}

    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=ok_response)
    fake_client_cm = MagicMock()
    fake_client_cm.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(ingestion, "_is_cse_paused", return_value=False), \
         patch.object(ingestion, "get_google_api_credentials", return_value=("key", "cx")), \
         patch("httpx.AsyncClient", return_value=fake_client_cm), \
         patch("leads.google_rate_limit.reserve_query_slot", return_value=(True, "OK")):
        results = _run(ingestion.perform_google_search("test query", num_results=10))

    assert results == [{"title": "Lead A"}]
    fake_client.get.assert_called_once()


def test_rate_limiter_import_failure_fails_open_and_still_reaches_429_handling(ingestion):
    """If the rate limiter module is unavailable for any reason, the existing
    429-reactive path must still work -- never a hard crash on this feature."""
    resp_429 = MagicMock(status_code=429)
    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=resp_429)
    fake_client_cm = MagicMock()
    fake_client_cm.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client_cm.__aexit__ = AsyncMock(return_value=False)

    def _raise_import_error():
        raise ImportError("no rate limiter")

    with patch.object(ingestion, "_is_cse_paused", return_value=False), \
         patch.object(ingestion, "get_google_api_credentials", return_value=("key", "cx")), \
         patch("httpx.AsyncClient", return_value=fake_client_cm), \
         patch.object(ingestion, "_pause_cse_for_24h") as pause_mock, \
         patch.dict(sys.modules, {"leads.google_rate_limit": None}):
        results = _run(ingestion.perform_google_search("test query", num_results=10))

    assert results == []
    fake_client.get.assert_called_once()   # request still attempted (fail open)
    pause_mock.assert_called_once()        # then paused via the existing 429 path
