"""CintService must not reuse an AsyncClient across event loops (2026-10-14:
scheduler threads call asyncio.run() each time; the shared client failed every
later run with "Event loop is closed")."""
import asyncio

from app.services.cint_service import CintService


def _svc():
    s = CintService.__new__(CintService)
    s.api_timeout = 5
    s._client = None
    s._client_loop = None
    return s


def test_new_loop_gets_new_client_same_loop_reuses():
    s = _svc()

    async def grab():
        return s.client, s.client

    a1, a2 = asyncio.run(grab())
    b1, _ = asyncio.run(grab())
    assert a1 is a2
    assert b1 is not a1
