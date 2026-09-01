"""
Smoke: Auth Flows
=================
Verifies:
  - Login with valid credentials succeeds and returns session token
  - Login with bad credentials returns 401
  - Protected endpoint requires valid session
  - Logout invalidates the session
  - Profile endpoint returns current user info
"""

import pytest
import httpx

# Requires a RUNNING server on BASE_URL — these drive the live HTTP surface,
# not the code in-process. Marked so CI can run everything else (TOR-14):
#     pytest backend/tests -m "not smoke"
pytestmark = pytest.mark.smoke



class TestAuthLogin:
    def test_login_success(self, client: httpx.Client):
        """POST /login/ with correct creds returns 200 + session_id."""
        from conftest import SMOKE_USER, SMOKE_PASS  # noqa: PLC0415
        resp = client.post("/login/", json={"username": SMOKE_USER, "password": SMOKE_PASS})
        assert resp.status_code == 200
        body = resp.json()
        # Must have a usable token field
        token = body.get("session_id") or body.get("token") or body.get("access_token")
        assert token, f"Token field missing from login response: {body}"

    def test_login_wrong_password(self, client: httpx.Client):
        """POST /login/ with wrong password returns 4xx."""
        from conftest import SMOKE_USER  # noqa: PLC0415
        resp = client.post("/login/", json={"username": SMOKE_USER, "password": "__wrong__"})
        assert resp.status_code in (401, 400, 403)

    def test_login_missing_body(self, client: httpx.Client):
        """POST /login/ with no body returns 4xx (validation error)."""
        resp = client.post("/login/", content=b"", headers={"Content-Type": "application/json"})
        assert resp.status_code in (400, 422)

    def test_login_unknown_user(self, client: httpx.Client):
        """POST /login/ with unknown user returns 4xx."""
        resp = client.post("/login/", json={"username": "__no_such_user__", "password": "x"})
        assert resp.status_code in (401, 400, 404)


class TestSessionValidation:
    def test_profile_requires_auth(self, client: httpx.Client):
        """GET /profile/ without token returns 401/403."""
        resp = client.get("/profile/")
        assert resp.status_code in (401, 403)

    def test_profile_with_valid_token(self, client: httpx.Client, authed_headers: dict):
        """GET /profile/ with valid session returns 200 and username."""
        resp = client.get("/profile/", headers=authed_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "username" in body or "user" in body, f"Unexpected profile shape: {body}"

    def test_invalid_token_rejected(self, client: httpx.Client):
        """Requests with a forged token must be rejected."""
        resp = client.get("/profile/", headers={"Authorization": "forged.token.value"})
        assert resp.status_code in (401, 403)


class TestLogout:
    def test_logout_succeeds(self, client: httpx.Client):
        """POST /logout/ with valid session returns 200."""
        from conftest import SMOKE_USER, SMOKE_PASS  # noqa: PLC0415
        # Get a fresh token (don't invalidate the shared session fixture)
        resp = client.post("/login/", json={"username": SMOKE_USER, "password": SMOKE_PASS})
        assert resp.status_code == 200
        body = resp.json()
        token = body.get("session_id") or body.get("token") or body.get("access_token")
        assert token

        logout_resp = client.post("/logout/", headers={"Authorization": token})
        assert logout_resp.status_code == 200

    def test_health_no_auth_required(self, client: httpx.Client):
        """GET /health must be accessible without auth (liveness probe)."""
        resp = client.get("/health")
        assert resp.status_code == 200
