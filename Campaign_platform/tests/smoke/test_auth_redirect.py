"""
Smoke test 1 — Auth redirect

Unauthenticated access to any /admin/* route must redirect to /admin/login.
The login page must render an email/username field and a password field.
"""

import os
BASE_URL = os.environ.get("SMOKE_URL", "http://localhost:5173")


def test_root_redirects_to_login(page):
    """/ should redirect to /admin/login."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    assert "/admin/login" in page.url, f"Expected redirect to /admin/login, got: {page.url}"


def test_admin_dashboard_requires_auth(page):
    """/admin/dashboard without a session should redirect to /admin/login."""
    page.goto(f"{BASE_URL}/admin/dashboard")
    page.wait_for_load_state("networkidle")
    assert "/admin/login" in page.url, (
        f"Expected redirect to /admin/login, got: {page.url}"
    )


def test_login_page_renders(page):
    """Login page must have a username/email input and a password input."""
    page.goto(f"{BASE_URL}/admin/login")
    page.wait_for_load_state("networkidle")

    # Accept common login field selectors
    username_field = page.locator(
        'input[type="text"], input[type="email"], input[name="username"]'
    ).first
    password_field = page.locator('input[type="password"]').first

    assert username_field.is_visible(), "Login form: username/email input not visible"
    assert password_field.is_visible(), "Login form: password input not visible"


def test_login_page_has_submit(page):
    """Login page must have a submit button."""
    page.goto(f"{BASE_URL}/admin/login")
    page.wait_for_load_state("networkidle")
    btn = page.locator('button[type="submit"]').first
    assert btn.is_visible(), "Login form: submit button not visible"
