"""
End-to-end browser smoke test (Playwright) for the CRM/AI admin UI.

Read-only: it logs in and NAVIGATES to each page to confirm it renders. It does
NOT click any mutating action (no Mark-Won / approve / reject), so it is safe to
point at a real environment.

Run against a deployed or locally-running app:

    pip install playwright && python -m playwright install chromium
    SMOKE_BASE_URL=https://torpedo.cogentixresearch.com \
    SMOKE_USER=admin SMOKE_PASS='***' \
    python scripts/e2e_smoke.py

Exit code 0 = login + all target routes rendered; 1 = something failed.
Screenshots are written to ./e2e_artifacts/.
"""

import os
import sys
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.getenv("SMOKE_BASE_URL", "http://localhost:5173").rstrip("/")
USER = os.getenv("SMOKE_USER", "admin")
PASS = os.getenv("SMOKE_PASS", "")
HEADLESS = os.getenv("SMOKE_HEADLESS", "true").lower() != "false"
NAV_TIMEOUT = int(os.getenv("SMOKE_NAV_TIMEOUT_MS", "60000"))

# (path, a text marker expected on the rendered page)
ROUTES = [
    # empty marker = only require the page not to bounce to /admin/login
    ("/admin/dashboard", ""),
    ("/admin/crm", "CRM Dashboard"),
    ("/admin/crm/pipeline", "Opportunity Pipeline"),
    ("/admin/crm/accounts", "Account Timeline"),
    ("/admin/ai/approvals", "AI Approvals"),
]

ARTIFACTS = Path("e2e_artifacts")
ARTIFACTS.mkdir(exist_ok=True)


def main() -> int:
    report = {"base": BASE, "login_ok": False, "routes": []}
    ok = True

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(ignore_https_errors=True)
        page = ctx.new_page()
        dialogs = []
        page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))

        # --- login ---
        page.goto(f"{BASE}/admin/login", wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        page.fill("#username", USER, timeout=15000)
        page.fill("#password", PASS, timeout=15000)
        page.click("button[type=submit]", timeout=15000)
        try:
            page.wait_for_function("() => !!localStorage.getItem('session_id')", timeout=20000)
            report["login_ok"] = True
        except Exception:
            report["login_ok"] = False
            report["login_dialogs"] = dialogs
        page.screenshot(path=str(ARTIFACTS / "login.png"))

        if not report["login_ok"]:
            print(json.dumps(report, indent=2))
            browser.close()
            return 1

        # --- navigate each route (read-only) ---
        for path, marker in ROUTES:
            r = {"path": path, "marker": marker, "ok": False}
            try:
                resp = page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                page.wait_for_timeout(2500)
                body = page.inner_text("body") or ""
                r["http_status"] = resp.status if resp else None
                r["final_url"] = page.url
                r["marker_present"] = marker.lower() in body.lower()
                # "ok" = we stayed on the route (not bounced to login) and content rendered
                r["ok"] = ("/admin/login" not in page.url) and r["marker_present"]
                page.screenshot(path=str(ARTIFACTS / (path.strip("/").replace("/", "_") + ".png")))
            except Exception as e:
                r["error"] = str(e)[:200]
            ok = ok and r["ok"]
            report["routes"].append(r)

        browser.close()

    print(json.dumps(report, indent=2))
    return 0 if (report["login_ok"] and ok) else 1


if __name__ == "__main__":
    sys.exit(main())
