"""
Smoke Test Configuration
========================
Shared fixtures for all smoke tests.

Usage:
    # Against local dev server
    pytest backend/tests/smoke/ -v

    # Against production (read-only, careful!)
    SMOKE_BASE_URL=http://139.59.32.72:8000 SMOKE_USER=admin SMOKE_PASS=... pytest backend/tests/smoke/ -v -m readonly

Environment:
    SMOKE_BASE_URL   API base (default: http://localhost:8000)
    SMOKE_USER       Admin username (default: admin)
    SMOKE_PASS       Admin password (required — no default)
    SMOKE_TIMEOUT    Request timeout in seconds (default: 15)
"""

import os
import pytest
import httpx

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000").rstrip("/")
SMOKE_USER = os.environ.get("SMOKE_USER", "admin")
SMOKE_PASS = os.environ.get("SMOKE_PASS", "password123")
TIMEOUT = float(os.environ.get("SMOKE_TIMEOUT", "15"))


@pytest.fixture(scope="session")
def client():
    """httpx client pointed at BASE_URL."""
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session")
def auth_token(client):
    """
    Authenticate once per session and return the session token.
    All tests that need auth receive this via dependency injection.
    """
    resp = client.post("/login/", json={"username": SMOKE_USER, "password": SMOKE_PASS})
    assert resp.status_code == 200, f"Login failed ({resp.status_code}): {resp.text[:200]}"
    data = resp.json()
    token = data.get("session_id") or data.get("token") or data.get("access_token")
    assert token, f"No session token in login response: {data}"
    return token


@pytest.fixture(scope="session")
def authed_headers(auth_token):
    """Authorization header dict for authenticated requests."""
    return {"Authorization": auth_token}
