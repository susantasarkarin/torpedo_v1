"""Run from your machine: python backend/scripts/e2e_takesurvey_inapp.py (needs playwright + chromium).

End-to-end check of the 'Open in Chrome' offer on the LIVE landing page.

Writes nothing: /api/routing/inapp-event and /api/store are intercepted in the
browser and answered locally, so no event, no entry and no client redirect.
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "https://torpedo.cogentixresearch.com/takesurvey?api=false&vid={vid}&cc=IN&pid=74536&rid={rid}"
WV_UA = ("Mozilla/5.0 (Linux; Android 14; CPH2381 Build/UKQ1.230924.001; wv) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Version/4.0 Chrome/155.0.8059.43 Mobile Safari/537.36")
CHROME_UA = ("Mozilla/5.0 (Linux; Android 14; CPH2381) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/155.0.8059.43 Mobile Safari/537.36")
ANSWERS = {"Which of these is a fruit?": "Apple", "Which of these animals barks?": "Dog",
           "What colour is a clear daytime sky?": "Blue", "Which of these is a day of the week?": "Monday",
           "How many legs does a cat have?": "Four", "Which number is the biggest?": "100",
           "Which of these is cold?": "Ice", "Which of these can you drink?": "Water",
           "Which of these can fly?": "Bird", "What colour is fresh grass?": "Green"}
NO_STORAGE = """
for (const name of ['localStorage', 'sessionStorage']) {
  Object.defineProperty(window, name, { get() { return null; }, configurable: true });
}

"""

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def run(p, label, vid, rid, ua, no_storage=False, click=None):
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=ua, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    if no_storage:
        ctx.add_init_script(NO_STORAGE)
    page = ctx.new_page()
    events, stores, navs = [], [], []

    def on_event(route):
        events.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json", body='{"ok":true}')

    def on_store(route):
        stores.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json",
                      body='{"allocation_success":false,"allocation_error":"e2e test"}')

    page.route("**/api/routing/inapp-event", on_event)
    page.route("**/api/store", on_store)
    cdp = ctx.new_cdp_session(page)
    cdp.send("Page.enable")
    cdp.on("Page.frameRequestedNavigation", lambda e: navs.append(e.get("url", "")) if str(e.get("url", "")).startswith("intent:") else None)
    page.goto(BASE.format(vid=vid, rid=rid), wait_until="networkidle")
    page.wait_for_timeout(1500)
    card = page.get_by_text("This survey works best in your phone's browser.")
    shown = card.count() > 0 and card.first.is_visible()
    out = {"shown": shown, "events": events, "stores": stores, "navs": navs, "page": page, "browser": browser}

    if click == "chrome" and shown:
        try:
            page.get_by_role("button", name="Open in Chrome").click()
        except Exception:
            pass
        page.wait_for_timeout(1500)
    elif click in ("here", "proceed"):
        if shown and click == "here":
            page.get_by_role("button", name="Continue here").click()
            page.wait_for_timeout(500)
            out["shown_after"] = card.count() > 0 and card.first.is_visible()
        # answer the security question and press Proceed
        q = page.locator("label", has_text="?").filter(has=page.locator("span", has_text="*")).first
        text = (q.inner_text() if q.count() else "").replace("*", "").strip()
        ans = ANSWERS.get(text)
        if ans:
            page.locator(f"input[name=botcheck][value='{ans}']").check()
        page.wait_for_timeout(1500)
        time.sleep(2.5)  # the check refuses answers under 2s
        page.get_by_text("Proceed", exact=True).first.click()
        page.wait_for_timeout(2500)
    return out


with sync_playwright() as p:
    # 1. Research Desk in-app, offer half: card shows, landing logged, Chrome hand-off built right
    r = run(p, "offer", "5068", "claude-a", WV_UA, click="chrome")
    check("offer half sees the card", r["shown"])
    check("landing event logged for the offer half", any(e.get("event") == "landing" and e.get("arm") == "offer" for e in r["events"]), json.dumps(r["events"])[:160])
    check("tap logged as open_clicked", any(e.get("event") == "open_clicked" for e in r["events"]))
    intent = next((u for u in r["navs"] if u.startswith("intent:")), "")
    check("hand-off goes to Chrome via an Android intent", intent.startswith("intent://torpedo.cogentixresearch.com/takesurvey?")
          and "package=com.android.chrome" in intent and "from_inapp=1" in intent and "rid=claude-a" in intent, intent[:160])
    check("hand-off keeps every survey parameter", all(k in intent for k in ("vid=5068", "pid=74536", "cc=IN")))
    check("no entry is created before the choice", not r["stores"])
    r["browser"].close()

    # 2. Offer half chooses 'Continue here': card goes away, the normal flow works, arm is sent
    r = run(p, "offer-here", "5068", "claude-a", WV_UA, click="here")
    check("'Continue here' hides the card", r.get("shown_after") is False)
    check("'continued' logged", any(e.get("event") == "continued" for e in r["events"]))
    s = r["stores"][0] if r["stores"] else {}
    check("entry carries the arm", s.get("inAppArm") == "offer", str(s.get("inAppArm")))
    sig = s.get("botSignals") or {}
    check("entry carries the browser checks", sig.get("webview") is True and sig.get("localStorage") is True and sig.get("cookies") is True, json.dumps(sig))
    r["browser"].close()

    # 3. Research Desk in-app, control half: normal page, arm still recorded
    r = run(p, "control", "5068", "claude-b", WV_UA, click="proceed")
    check("control half sees no card", not r["shown"])
    check("control landing logged", any(e.get("event") == "landing" and e.get("arm") == "control" for e in r["events"]))
    s = r["stores"][0] if r["stores"] else {}
    check("control entry carries its arm", s.get("inAppArm") == "control", str(s.get("inAppArm")))
    r["browser"].close()

    # 4. Same visitor in Chrome (arrived from the offer): no card, arrival marked
    r = run(p, "chrome", "5068", "claude-a&from_inapp=1", CHROME_UA, click="proceed")
    check("Chrome visitor sees no card", not r["shown"])
    s = r["stores"][0] if r["stores"] else {}
    check("arrival in Chrome is marked", (s.get("params") or {}).get("from_inapp") == "1", json.dumps(s.get("params"))[:120])
    check("Chrome entry has no arm", "inAppArm" not in s or s.get("inAppArm") in (None, ""))
    r["browser"].close()

    # 5. Cint in-app: untouched
    r = run(p, "cint", "4738", "claude-a", WV_UA)
    check("Cint in-app visitor sees no card", not r["shown"] and not r["events"])
    r["browser"].close()

    # 6. In-app browser with storage and cookies switched off: page still works, checks say so
    r = run(p, "nostorage", "5068", "claude-b", WV_UA, no_storage=True, click="proceed")
    s = r["stores"][0] if r["stores"] else {}
    sig = s.get("botSignals") or {}
    check("page still works with storage off", bool(r["stores"]))
    check("checks report storage off", sig.get("localStorage") is False and sig.get("sessionStorage") is False, json.dumps(sig))
    r["browser"].close()

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
