from playwright.sync_api import sync_playwright
import os
base = os.environ.get("SMOKE_URL", "http://localhost:5173")
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    c = b.new_context()
    page = c.new_page()

    def on_console(msg):
        print("CONSOLE", msg.type, msg.text)

    def on_pageerror(err):
        print("PAGEERROR", err)

    def on_requestfailed(req):
        print("REQFAIL", req.url, req.failure)

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("requestfailed", on_requestfailed)

    page.goto(base + "/admin/login", wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(5000)

    print("URL", page.url)
    print("TITLE", page.title())
    print("INPUTS", page.locator("input").count())
    print("BUTTONS", page.locator("button").count())
    print("ROOT_HTML", page.locator("#root").inner_html()[:600] if page.locator("#root").count() else "NO_ROOT")

    c.close()
    b.close()
