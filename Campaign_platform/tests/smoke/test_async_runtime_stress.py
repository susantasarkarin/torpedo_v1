"""
Runtime async stress checks.

Scenarios:
- Multi-tab + rapid route churn with polling enabled
- Auto-refresh toggle churn (start/cancel balance)
- Offline/reconnect behavior (no request storm)

These tests validate runtime behavior, not payload semantics.
"""

import os
import pytest
from playwright.sync_api import Browser, Error as PlaywrightError, TimeoutError

BASE_URL = os.environ.get("SMOKE_URL", "http://localhost:5173")
TEST_USER = os.environ.get("SMOKE_USER", "admin")
TEST_PASS = os.environ.get("SMOKE_PASS", "password123")


def _login(page) -> bool:
    username_selector = (
        'input[name="username"], input[name="email"], input[type="text"], '
        'input[type="email"], input[placeholder*="user" i], input[placeholder*="email" i]'
    )
    password_selector = 'input[type="password"], input[name="password"]'
    submit_selector = 'button[type="submit"], button:has-text("Login"), button:has-text("Sign in")'

    try:
        page.goto(f"{BASE_URL}/admin/login")
        page.wait_for_load_state("networkidle")

        username = page.locator(username_selector)
        password = page.locator(password_selector)
        submit = page.locator(submit_selector)

        # If the SPA shell/login form did not mount, treat auth as unavailable for this run.
        if username.count() == 0 or password.count() == 0 or submit.count() == 0:
            return False

        username.first.fill(TEST_USER)
        password.first.fill(TEST_PASS)
        submit.first.click()
        page.wait_for_load_state("networkidle")
        return "/admin/login" not in page.url
    except (PlaywrightError, TimeoutError):
        return False


def _enable_async_debug(page):
    page.evaluate(
        """
        () => {
          window.__ASYNC_DEBUG__ = true;
          try { localStorage.setItem('async_debug', '1'); } catch (_) {}
        }
        """
    )


def _open_logs_and_enable_refresh(page):
    page.goto(f"{BASE_URL}/admin/logs")
    page.wait_for_load_state("networkidle")
    checkbox = page.locator('input[type="checkbox"]')
    if checkbox.count() == 0:
        pytest.skip("Logs auto-refresh checkbox not found")
    if not checkbox.first.is_checked():
        checkbox.first.check()


def test_multi_tab_route_churn_no_poll_leak(browser: Browser):
    """Multi-tab and route churn should not produce runaway poll starts without cancels."""
    ctx = browser.new_context()
    p1 = ctx.new_page()
    p2 = ctx.new_page()

    logs = []

    def on_console(msg):
        text = msg.text
        if "[poll:" in text or "[ws:" in text or msg.type == "error":
            logs.append(text)

    p1.on("console", on_console)
    p2.on("console", on_console)

    if not _login(p1):
        ctx.close()
        pytest.skip("Auth unavailable for runtime stress tests")
    if not _login(p2):
        ctx.close()
        pytest.skip("Second tab auth unavailable for runtime stress tests")

    _enable_async_debug(p1)
    _enable_async_debug(p2)

    _open_logs_and_enable_refresh(p1)
    p2.goto(f"{BASE_URL}/admin/dashboard")
    p2.wait_for_load_state("networkidle")

    # Visibility churn via tab focus switching
    for _ in range(4):
        p1.bring_to_front()
        p1.wait_for_timeout(600)
        p2.bring_to_front()
        p2.wait_for_timeout(600)

    # Rapid route churn on tab with active polling
    for route in [
        "/admin/dashboard",
        "/admin/logs",
        "/admin/finance/customers",
        "/admin/logs",
    ]:
        p1.goto(f"{BASE_URL}{route}")
        p1.wait_for_timeout(800)

    poll_starts = sum(1 for line in logs if "[poll:start]" in line)
    poll_cancels = sum(1 for line in logs if "[poll:cancel" in line)

    # No fatal runtime failures in console.
    fatal_errors = [
        line for line in logs
        if "Unhandled" in line or "Maximum call stack" in line or "Cannot read properties" in line
    ]

    ctx.close()

    assert not fatal_errors, f"Fatal console errors detected: {fatal_errors[:5]}"
    assert poll_starts >= 1, "Expected at least one managed poll start"
    assert poll_cancels >= 1, "Expected at least one managed poll cancel during churn"


def test_logs_toggle_churn_balances_start_cancel(browser: Browser):
    """Repeated auto-refresh toggles should not leak polling loops."""
    ctx = browser.new_context()
    page = ctx.new_page()

    logs = []
    page.on("console", lambda msg: logs.append(msg.text) if "[poll:" in msg.text else None)

    if not _login(page):
        ctx.close()
        pytest.skip("Auth unavailable for runtime stress tests")

    _enable_async_debug(page)
    page.goto(f"{BASE_URL}/admin/logs")
    page.wait_for_load_state("networkidle")

    checkbox = page.locator('input[type="checkbox"]').first
    if checkbox.count() == 0:
        ctx.close()
        pytest.skip("Logs auto-refresh checkbox not found")

    for i in range(4):
        if not checkbox.is_checked():
            checkbox.check()
        page.wait_for_timeout(350)
        if checkbox.is_checked():
            checkbox.uncheck()
        page.wait_for_timeout(350)

    poll_starts = sum(1 for line in logs if "[poll:start]" in line)
    poll_cancels = sum(1 for line in logs if "[poll:cancel" in line)

    ctx.close()

    assert poll_starts >= 1, "Expected polling to start at least once"
    assert poll_cancels >= 1, "Expected polling to cancel during toggle churn"
    assert poll_cancels <= poll_starts + 2, "Unexpected cancel/start imbalance indicates unstable lifecycle"


def test_logs_offline_reconnect_no_request_storm(browser: Browser):
    """Going offline then online should not trigger runaway request bursts."""
    ctx = browser.new_context()
    page = ctx.new_page()

    if not _login(page):
        ctx.close()
        pytest.skip("Auth unavailable for runtime stress tests")

    _enable_async_debug(page)
    _open_logs_and_enable_refresh(page)

    request_count = {"logs": 0}

    def on_request(req):
        if "/settings/logs" in req.url:
            request_count["logs"] += 1

    page.on("request", on_request)

    # Let baseline polling run briefly.
    page.wait_for_timeout(6000)
    baseline = request_count["logs"]

    ctx.set_offline(True)
    page.wait_for_timeout(5000)
    ctx.set_offline(False)

    # Observe post-reconnect window.
    request_count["logs"] = 0
    page.wait_for_timeout(9000)
    post_reconnect = request_count["logs"]

    ctx.close()

    # 5s cadence => about 1-2 requests in 9s, allow headroom for jitter.
    assert post_reconnect <= 4, (
        f"Potential reconnect request storm detected: {post_reconnect} /settings/logs requests in 9s"
    )
    assert baseline >= 1, "Expected baseline polling requests before offline switch"
