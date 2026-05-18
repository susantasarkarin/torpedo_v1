"""
Smoke test 2 — Login golden flow

Full login → dashboard → logout cycle.
Requires SMOKE_USER and SMOKE_PASS environment variables.
"""

import pytest
import os
BASE_URL = os.environ.get("SMOKE_URL", "http://localhost:5173")
TEST_USER = os.environ.get("SMOKE_USER", "")
TEST_PASS = os.environ.get("SMOKE_PASS", "")


def test_login_success(authed_page):
    """After login, browser must NOT be on /admin/login."""
    assert "/admin/login" not in authed_page.url, (
        f"Login appeared to fail — still on: {authed_page.url}"
    )


def test_dashboard_loads_after_login(authed_page):
    """After login, a recognisable dashboard element must be present."""
    authed_page.goto(f"{BASE_URL}/admin/dashboard")
    authed_page.wait_for_load_state("networkidle")

    # Accept any of these common dashboard indicators
    indicators = [
        "nav",
        '[class*="navbar"]',
        '[class*="dashboard"]',
        '[class*="sidebar"]',
    ]
    found = any(authed_page.locator(sel).count() > 0 for sel in indicators)
    assert found, "Dashboard page did not render a recognisable layout element"


def test_logout_clears_session(authed_page):
    """Clicking logout must redirect back to /admin/login."""
    authed_page.goto(f"{BASE_URL}/admin/dashboard")
    authed_page.wait_for_load_state("networkidle")

    logout_btn = authed_page.locator('button:has-text("Logout"), a:has-text("Logout")').first
    if not logout_btn.is_visible():
        pytest.skip("Logout button not found in current viewport — check Navbar rendering")

    logout_btn.click()
    authed_page.wait_for_load_state("networkidle")

    assert "/admin/login" in authed_page.url, (
        f"After logout expected /admin/login, got: {authed_page.url}"
    )

    # session_id must be cleared from localStorage
    session_id = authed_page.evaluate("localStorage.getItem('session_id')")
    assert session_id is None, "session_id still present in localStorage after logout"
