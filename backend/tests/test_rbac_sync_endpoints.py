"""RBAC decorators work on plain `def` endpoints as well as `async def`."""

import asyncio

from fastapi import Request

from rbac import decorators


def _request():
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""})


def test_sync_endpoint_returns_its_value(monkeypatch):
    monkeypatch.setattr(decorators, "rbac_enabled", lambda: False)

    @decorators.require_any_permission("finance.invoice.read")
    def get_invoices(request):
        return {"invoices": [1, 2]}

    assert asyncio.run(get_invoices(request=_request())) == {"invoices": [1, 2]}


def test_async_endpoint_still_works(monkeypatch):
    monkeypatch.setattr(decorators, "rbac_enabled", lambda: False)

    @decorators.require_any_permission("finance.invoice.read")
    async def get_customers(request):
        return {"customers": []}

    assert asyncio.run(get_customers(request=_request())) == {"customers": []}
