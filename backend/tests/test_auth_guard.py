"""Login required for data-changing requests (2026-10-19 incident: an outside
scanner enrolled 817 leads via an unauthenticated POST)."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import auth_guard
import session_state


@pytest.fixture
def client(monkeypatch):
    async def fake_verify(request):
        if request.headers.get("Authorization") != "good-token":
            raise HTTPException(status_code=401, detail="Missing session token")
        return "admin"
    monkeypatch.setattr(session_state, "verify_session", fake_verify)
    monkeypatch.delenv("AUTH_GUARD_MODE", raising=False)
    monkeypatch.delenv("AUTH_GUARD_ENFORCE_PREFIXES", raising=False)
    monkeypatch.delenv("AUTH_GUARD_OFF", raising=False)
    app = FastAPI()
    app.add_middleware(auth_guard.AuthGuard)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def any_route(path: str):
        return {"ok": True, "path": path}
    return TestClient(app)


@pytest.mark.parametrize("path", [
    "/api/cold-outreach/dual-fit/enroll",     # the one the scanner used
    "/gmail/emails/send", "/gmail-ws/send", "/api/v1/email-sync/send",
    "/settings/app", "/gmail-ws/config/service-account", "/api/operations/async/1/cancel",
    "/performance/clear-cache", "/api/sales-outreach/send/1",
])
def test_scanner_targets_are_refused_without_login(client, path):
    assert client.post(path).status_code == 401
    assert client.post(path, headers={"Authorization": "bad"}).status_code == 401
    assert client.post(path, headers={"Authorization": "good-token"}).status_code == 200


@pytest.mark.parametrize("path", [
    "/api/store", "/api/routing/inapp-event", "/api/panel/login", "/panel/signup",
    "/api/cold-outreach/unsubscribe/abc/one-click", "/campaigns/automation/tracking/events",
    "/api/sales-outreach/event", "/gmail/oauth/callback", "/webhooks/ses", "/login", "/api/login",
    "/api/mystery-shopping/public/new", "/api/prefetch-ip",
])
def test_public_endpoints_still_work_without_login(client, path):
    assert client.post(path).status_code == 200


def test_reads_are_not_touched(client):
    assert client.get("/api/cold-outreach/campaigns").status_code == 200


def test_other_areas_are_report_only_until_checked(client, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="auth_guard"):
        r = client.post("/api/vendors/1")
    assert r.status_code == 200
    assert any("would block POST /api/vendors/1" in m for m in caplog.messages)


def test_full_enforce_and_emergency_off(client, monkeypatch):
    monkeypatch.setenv("AUTH_GUARD_MODE", "enforce")
    assert client.post("/api/vendors/1").status_code == 401
    assert client.post("/api/store").status_code == 200          # public stays public
    monkeypatch.setenv("AUTH_GUARD_OFF", "true")
    assert client.post("/api/cold-outreach/dual-fit/enroll").status_code == 200


def test_panel_admin_is_not_mistaken_for_public_panel(client, monkeypatch):
    assert not auth_guard.is_public("/panel-admin/redemptions/1/hold")
    assert auth_guard.is_public("/api/panel/profile")
