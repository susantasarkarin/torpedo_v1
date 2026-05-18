"""
Smoke test 3 — Finance routes (no double-prefix)

All finance sub-pages must load without a 404 response.
Previously broken: router prefix /finance + route paths /finance/... → /finance/finance/...
This test confirms the fix is live end-to-end.
"""

import pytest
from playwright.sync_api import Page
import os
BASE_URL = os.environ.get("SMOKE_URL", "http://localhost:5173")


FINANCE_ROUTES = [
    "/admin/finance/dashboard",
    "/admin/finance/customers",
    "/admin/finance/vendors",
    "/admin/finance/invoices",
    "/admin/finance/bills",
    "/admin/finance/items",
]


@pytest.mark.parametrize("route", FINANCE_ROUTES)
def test_finance_page_no_404(authed_page, route):
    """Finance page must not show a 404 or 'not found' response."""
    errors = []

    def on_response(response):
        # Flag any API call that returns 404
        if response.status == 404 and "/finance/" in response.url:
            errors.append(f"404 on {response.url}")

    authed_page.on("response", on_response)

    authed_page.goto(f"{BASE_URL}{route}")
    authed_page.wait_for_load_state("networkidle")
    authed_page.remove_listener("response", on_response)

    assert not errors, f"Finance 404s detected on {route}: {errors}"


@pytest.mark.parametrize("route", FINANCE_ROUTES)
def test_finance_page_renders(authed_page, route):
    """Finance page must render without a crash error boundary."""
    authed_page.goto(f"{BASE_URL}{route}")
    authed_page.wait_for_load_state("networkidle")

    # React error boundary typically renders text containing "Something went wrong"
    body_text = authed_page.inner_text("body").lower()
    assert "something went wrong" not in body_text, (
        f"React error boundary triggered on {route}"
    )
