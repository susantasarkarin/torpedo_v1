"""
Enrichment Auto-Launcher
========================
Polls Gemini API until at least one key is working, then launches the
enrichment runner in the background and exits.

Run this overnight:
    nohup python3 /tmp/launch_when_ready.py > /tmp/launch.log 2>&1 &
"""
import sys, time, subprocess, urllib.request, json, logging
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger()

BACKEND = "/var/www/campaign_platform/backend"
RUNNER  = f"{BACKEND}/scripts/run_enrichment.py"
POLL_S  = 300   # check every 5 minutes

def any_key_works():
    c = MongoClient()
    settings = c['torpedo_settings']['app_settings'].find_one() or {}
    payload = json.dumps({"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}).encode()
    model = "gemini-2.0-flash"
    for i in range(1, 11):
        api_key = settings.get(f"gemini_api_key_{i}", "")
        if not api_key:
            continue
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10):
                log.info(f"Key {i} is WORKING — starting enrichment now!")
                return True
        except urllib.error.HTTPError as e:
            if e.code == 403:
                continue   # skip invalid keys
            # 429 — try next
        except Exception:
            pass
    return False

log.info("Waiting for Gemini key quota reset (polls every 5 min)...")
while True:
    if any_key_works():
        log.info(f"Launching enrichment runner: {RUNNER}")
        subprocess.Popen(
            [sys.executable, RUNNER],
            stdout=open("/tmp/enrichment.log", "w"),
            stderr=subprocess.STDOUT,
            cwd=BACKEND,
        )
        log.info("Enrichment runner launched. Check /tmp/enrichment.log for progress.")
        break
    log.info(f"No keys available yet — sleeping {POLL_S}s")
    time.sleep(POLL_S)
