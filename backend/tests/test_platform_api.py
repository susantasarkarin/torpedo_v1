"""Platform API: every endpoint requires a session; config writes are audited."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import platform_api
from session_state import verify_session


def _client(monkeypatch, user="owner"):
    app = FastAPI()
    app.include_router(platform_api.router)
    if user:
        app.dependency_overrides[verify_session] = lambda: user
    return TestClient(app)


def test_requires_login(monkeypatch):
    c = _client(monkeypatch, user=None)
    assert c.get("/api/platform/review-queue").status_code == 401


def test_config_put_rejects_unknown_keys(monkeypatch):
    from platform_core import config_store
    def _set(section, values, actor):
        raise ValueError("unknown keys for pricing: x")
    monkeypatch.setattr(config_store, "set", _set)
    r = _client(monkeypatch).put("/api/platform/config/pricing", json={"x": 1})
    assert r.status_code == 400


def test_resolve_passes_the_user_as_actor(monkeypatch):
    from platform_core import review_queue
    seen = {}
    monkeypatch.setattr(review_queue, "resolve", lambda i, a, actor, **k: seen.update(actor=actor, action=a) or {"ok": True})
    r = _client(monkeypatch).post("/api/platform/review-queue/abc/approve", json={})
    assert r.status_code == 200 and seen == {"actor": "owner", "action": "approve"}
