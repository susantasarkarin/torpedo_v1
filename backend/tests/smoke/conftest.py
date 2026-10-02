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

# NOTE: httpx is imported lazily inside the `client` fixture below. Only the
# server-dependent smoke tests use it, and those are excluded from the CI run
# (which installs the minimal requirements-ci.txt without httpx). Importing it
# at module level would abort collection of every smoke test in CI.

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000").rstrip("/")
SMOKE_USER = os.environ.get("SMOKE_USER", "admin")
SMOKE_PASS = os.environ.get("SMOKE_PASS", "password123")
TIMEOUT = float(os.environ.get("SMOKE_TIMEOUT", "15"))


@pytest.fixture(scope="session")
def client():
    """httpx client pointed at BASE_URL."""
    import httpx  # lazy: keeps httpx out of the minimal-deps CI collection
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


# --- never against production by accident ------------------------------------
# On 2026-09-29 the full test run on the production VM included these smoke
# tests; with the default base URL (localhost:8000) and the local Mongo they
# wrote to the LIVE system and left "Won RFQ" projects, contracts, work orders
# and a customer behind. On the production host they now skip unless
# SMOKE_ALLOW_PROD=1 is set on purpose.
def _on_production_host() -> bool:
    import socket
    return (os.path.isdir("/var/www/campaign_platform")
            or socket.gethostname().startswith("torpedo-prod"))


def pytest_collection_modifyitems(config, items):
    if not _on_production_host() or os.environ.get("SMOKE_ALLOW_PROD") == "1":
        return
    skip = pytest.mark.skip(reason="smoke tests write to the live system; set SMOKE_ALLOW_PROD=1 to run on the production host")
    for item in items:
        if "/smoke/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)
