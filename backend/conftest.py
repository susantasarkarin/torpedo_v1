"""
Backend pytest bootstrap.

`backend/pytest.ini` makes backend/ the rootdir, so pytest only collects
conftest files at or below this directory — a repo-root conftest.py is never
loaded when tests run from here. This is the one that actually takes effect.

Puts backend/ on sys.path so the app's absolute imports (`from routers import
...`) resolve regardless of the invoking directory (TOR-11). Absolute is the
ONE convention now: the app runs as `uvicorn main:app` with backend/ as the
working directory, so that is what actually works at runtime, and the 338
try-relative/except-absolute fallbacks that used to hide broken imports are
gone. `scripts/check_imports.py` keeps them gone.
"""

import os
import sys

BACKEND = os.path.dirname(os.path.abspath(__file__))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# config.py and session_state.py both refuse to import without a session
# secret — deliberately, since a well-known default is how an app ends up
# signing production sessions with a public key. Tests need *a* value; give
# them one that could never be mistaken for a real secret.
os.environ.setdefault("SESSION_SECRET", "pytest-only-not-a-real-secret")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")


# CRM audit 2026-10-24: messaging.facade.gate() now reads two pieces of live
# state from MongoDB (the outreach kill switch and the 24 h per-contact
# throttle). Unit tests have no database, so each read would wait for the
# driver's server-selection timeout. Stub both by default; the tests that
# pin those rules patch them back in explicitly.
import pytest


@pytest.fixture(autouse=True)
def _no_live_send_state(monkeypatch, request):
    if request.node.get_closest_marker("live_send_state"):
        return
    try:
        from messaging import facade
    except Exception:
        return
    monkeypatch.setattr(facade, "_throttle_block", lambda addr, channel: None, raising=False)
    monkeypatch.setattr(facade, "outreach_paused", lambda: False, raising=False)


@pytest.fixture(autouse=True)
def _no_cloud_ai(monkeypatch):
    """Tests never call Anthropic or read the live ladder config/spend: the cloud
    rungs fail at once (tests that exercise them pass their own transport)."""
    try:
        from platform_core import ladder
    except Exception:
        return

    def _offline(**kw):
        raise RuntimeError("cloud AI disabled in tests")
    monkeypatch.setattr(ladder, "anthropic_transport", _offline, raising=False)
    monkeypatch.setattr(ladder, "cfg", lambda: ladder.DEFAULTS, raising=False)
    try:
        from platform_core import qwen_gateway
        from tests._fakemongo import FakeDB
        gov = FakeDB()
        monkeypatch.setattr(qwen_gateway, "_gov_db", lambda: gov, raising=False)
    except Exception:
        pass
