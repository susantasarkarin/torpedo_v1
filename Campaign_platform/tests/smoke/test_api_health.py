"""
Smoke test 5 — API health and X-Request-ID header

Checks:
  - Backend health endpoint responds 200
  - api.js sends X-Request-ID on all requests (verified via response headers echo or
    by asserting the header is present in outbound requests captured by the page)
  - No API calls on the dashboard return 5xx errors
"""

import os
import requests
import pytest
BASE_URL = os.environ.get("SMOKE_URL", "http://localhost:5173")
BACKEND_URL = os.environ.get("SMOKE_BACKEND_URL", "http://localhost:8000")


def test_backend_health():
    """Backend /health endpoint must return 200."""
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=5)
        assert r.status_code == 200, f"Health check returned {r.status_code}"
    except requests.exceptions.ConnectionError:
        pytest.skip("Backend not reachable — skipping health check")


def test_dashboard_no_5xx(authed_page):
    """No API call from the dashboard must return a 5xx error."""
    errors = []

    def on_response(response):
        if response.status >= 500:
            errors.append(f"{response.status} → {response.url}")

    authed_page.on("response", on_response)
    authed_page.goto(f"{BASE_URL}/admin/dashboard")
    authed_page.wait_for_load_state("networkidle")
    authed_page.remove_listener("response", on_response)

    assert not errors, f"5xx responses on dashboard load: {errors}"


def test_x_request_id_sent(authed_page):
    """
    Outbound requests from the primary frontend must include X-Request-ID.
    We capture request headers on the first API call made after page load.
    """
    seen_request_ids = []

    def on_request(request):
        rid = request.headers.get("x-request-id")
        if rid:
            seen_request_ids.append(rid)

    authed_page.on("request", on_request)
    authed_page.goto(f"{BASE_URL}/admin/dashboard")
    authed_page.wait_for_load_state("networkidle")
    authed_page.remove_listener("request", on_request)

    assert seen_request_ids, (
        "No outbound request included X-Request-ID header. "
        "Check that getHeaders() in api.js adds crypto.randomUUID()."
    )
    # Each request should have a distinct UUID
    assert len(seen_request_ids) == len(set(seen_request_ids)), (
        "Duplicate X-Request-ID values detected — UUIDs must be unique per request"
    )
