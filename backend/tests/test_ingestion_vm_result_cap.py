"""
ingestion_vm.perform_google_search() CAPS RESULTS-PER-CALL, MIRRORING ingestion.py
=====================================================================================

2026-09-27: don't let one call fire up to 10 requests just because a caller
asked for up to 100 results -- cap it to 10 (one page) regardless of what's
requested. See the matching fix + tests for the sibling implementation in
leads/ingestion.py.
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def ingestion_vm(monkeypatch):
    """Import leads.ingestion_vm with Mongo stubbed out (it builds handles at import)."""
    fake_db = types.ModuleType("database")
    fake_db.get_client = lambda: MagicMock()
    monkeypatch.setitem(sys.modules, "database", fake_db)
    sys.modules.pop("leads.ingestion_vm", None)
    from leads import ingestion_vm as mod
    yield mod
    sys.modules.pop("leads.ingestion_vm", None)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _fake_client(status_code=200, items=None):
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = {"items": items if items is not None else [{"title": "Lead A"}]}
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return client, cm


def test_a_single_call_never_exceeds_the_per_call_result_cap(ingestion_vm):
    client, cm = _fake_client(items=[{"title": f"Lead {i}"} for i in range(10)])
    with patch.object(ingestion_vm, "get_google_api_credentials", return_value=("key", "cx")), \
         patch("httpx.AsyncClient", return_value=cm):
        results = _run(ingestion_vm.perform_google_search("test query", num_results=100))

    assert len(results) == 10
    assert client.get.call_count == 1   # never the up-to-10 requests 100 results implies


def test_a_request_within_the_cap_is_unaffected(ingestion_vm):
    client, cm = _fake_client()
    with patch.object(ingestion_vm, "get_google_api_credentials", return_value=("key", "cx")), \
         patch("httpx.AsyncClient", return_value=cm):
        results = _run(ingestion_vm.perform_google_search("test query", num_results=5))

    assert results == [{"title": "Lead A"}]
    assert client.get.call_count == 1
