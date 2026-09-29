"""
Run the AI-first RFQ decisions over the whole history, in the background.

  live links / launch instructions -> won (+ Online), RFQ created if missing
  our quotes                       -> CPI, currency, value, Quoted
  is it really an RFQ              -> closes (never deletes) the ones that are not

Every model verdict is stored on the mail or the RFQ as it is made, so the run
can be stopped and resumed; a model outage stops a pass and it picks up where
it left off next time. It shares the single local-model slot with live work
and waits its turn.

  nohup nice -n 19 venv/bin/python scripts/rfq_ai_backfill.py > /tmp/rfq_ai_backfill.log 2>&1 &
"""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from pymongo import MongoClient
    from app.services import rfq_from_mail as rb
    c = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/")
    t0 = time.time()

    def log(msg):
        print(f"[{datetime.utcnow():%H:%M:%S} +{time.time() - t0:.0f}s] {msg}", flush=True)

    # 1. live links / launch -> won. Chunks of 25 decisions until nothing is left.
    total = {}
    while True:
        s = rb.apply_live_links(c, since=None, ai_calls=25)
        for k, v in s.items():
            total[k] = total.get(k, 0) + v
        log(f"live links: {s}")
        if s["asked"] == 0 or s["unavailable"]:
            if s["unavailable"]:
                time.sleep(120)
                continue
            break
    log(f"LIVE LINKS DONE {total}")

    # 2. our quotes, AI first, over every RFQ
    while True:
        s = rb.apply_quotes(c, only_open=False, ai_calls=40)
        log(f"quotes: {s}")
        if s["ai_unavailable"]:
            time.sleep(120)
            continue
        if s["ai_asked"] == 0:   # every candidate reply already has the model's verdict
            break
    log("QUOTES DONE")

    # 3. is it really an RFQ -- every rebuilt RFQ, newest first
    while True:
        s = rb.ai_check_new_rfqs(c, limit=25)
        log(f"is-rfq: {s}")
        if s["unavailable"]:
            time.sleep(120)
            continue
        if s["checked"] == 0:
            break
    log("IS-RFQ DONE")
    log("ALL DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
