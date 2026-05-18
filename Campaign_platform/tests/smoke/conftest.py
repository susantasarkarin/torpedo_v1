"""
Shared fixtures for Campaign Platform smoke tests.

Environment variables (set before running):
    SMOKE_URL       - Frontend base URL (default: http://localhost:5173)
    SMOKE_USER      - Admin username
    SMOKE_PASS      - Admin password

Run all smoke tests:
    python -m pytest Campaign_platform/tests/smoke/ -v

Run against production (assumes backend is live via nginx):
    SMOKE_URL=https://your-domain.com python -m pytest Campaign_platform/tests/smoke/ -v
"""

import os
import pytest
from playwright.sync_api import sync_playwright, Page, Browser

BASE_URL = os.environ.get("SMOKE_URL", "http://localhost:5173")
TEST_USER = os.environ.get("SMOKE_USER", "")
TEST_PASS = os.environ.get("SMOKE_PASS", "")


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser: Browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    yield pg
    ctx.close()


@pytest.fixture
def authed_page(browser: Browser):
    """Returns a page that has already completed the login flow."""
    if not TEST_USER or not TEST_PASS:
        pytest.skip("SMOKE_USER / SMOKE_PASS not set — skipping authenticated tests")

    ctx = browser.new_context()
    pg = ctx.new_page()

    pg.goto(f"{BASE_URL}/admin/login")
    pg.wait_for_load_state("networkidle")

    pg.fill('input[type="text"], input[name="username"], input[placeholder*="user" i]', TEST_USER)
    pg.fill('input[type="password"]', TEST_PASS)
    pg.click('button[type="submit"]')
    pg.wait_for_load_state("networkidle")

    yield pg
    ctx.close()
