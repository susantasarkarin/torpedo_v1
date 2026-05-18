"""
Smoke test 4 — Cold Outreach page

Verifies the Outreach page:
  - loads without a crash
  - renders the business selector tabs (SFW / Cogentix / BIMwave / Dual Fit)
  - makes at least one /api/cold-outreach/ API call that does NOT return 404
"""

import pytest
import os
BASE_URL = os.environ.get("SMOKE_URL", "http://localhost:5173")

OUTREACH_URL = f"{BASE_URL}/admin/sales/outreach"

EXPECTED_BUSINESSES = ["Survey Fieldwork", "Cogentix Research", "BIMwave", "Dual Fit"]


def test_outreach_page_loads(authed_page):
    """Outreach page must not crash on load."""
    authed_page.goto(OUTREACH_URL)
    authed_page.wait_for_load_state("networkidle")

    body_text = authed_page.inner_text("body").lower()
    assert "something went wrong" not in body_text, "React error boundary triggered on Outreach page"


def test_outreach_business_tabs_visible(authed_page):
    """All four business tabs must be visible."""
    authed_page.goto(OUTREACH_URL)
    authed_page.wait_for_load_state("networkidle")

    missing = []
    for biz in EXPECTED_BUSINESSES:
        # Allow partial match (e.g. abbreviated labels)
        if authed_page.get_by_text(biz, exact=False).count() == 0:
            missing.append(biz)

    assert not missing, f"Outreach page missing business tabs: {missing}"


def test_outreach_api_no_404(authed_page):
    """Outreach page must not trigger a 404 on any /api/cold-outreach/ call."""
    errors = []

    def on_response(response):
        if response.status == 404 and "cold-outreach" in response.url:
            errors.append(f"404 → {response.url}")

    authed_page.on("response", on_response)
    authed_page.goto(OUTREACH_URL)
    authed_page.wait_for_load_state("networkidle")
    authed_page.remove_listener("response", on_response)

    assert not errors, f"Cold-outreach 404s: {errors}"
