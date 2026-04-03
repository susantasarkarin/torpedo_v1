"""
Batch Enrichment Runner  (concurrent)
======================================
Processes all pending/failed leads using Gemini (10-key rotation).
Uses a thread pool to saturate the paid-tier RPM limit (~2,000 RPM).
Safe to run while the backend is live — all MongoDB updates are atomic.

Key behaviour:
- WORKERS concurrent threads, each calling classify_single_lead independently
- 429/quota errors: per-thread exponential back-off (not a global pause)
- Auto-resets classification_attempts so previously-stalled leads are retried
- Fetches work in rolling batches so memory stays bounded

Usage:
    nohup python3 /var/www/campaign_platform/backend/scripts/run_enrichment.py \
        > /tmp/enrichment.log 2>&1 &

    # Custom worker count (default 30):
    ENRICHMENT_WORKERS=50 nohup python3 ... &
"""
import os
import sys
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from pymongo import MongoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("enrichment")

MONGO_URI         = "mongodb://localhost:27017/"
WORKERS           = int(os.getenv("ENRICHMENT_WORKERS", 30))
BATCH_SIZE        = WORKERS * 4      # keep the queue ~4× ahead of workers
PROGRESS_EVERY    = 100              # log a progress line every N completions
QUOTA_SLEEP_S     = 5                # initial back-off on 429
QUOTA_WAIT_MAX_M  = 30              # per-lead retry window (minutes)

QUOTA_SIGNALS = ("quota", "exceeded", "429", "rate limit", "resource_exhausted",
                 "rateLimitExceeded", "RESOURCE_EXHAUSTED")


def is_quota_error(msg: str) -> bool:
    m = msg.lower()
    return any(s.lower() in m for s in QUOTA_SIGNALS)


def reset_and_count(db) -> int:
    """Reset all stalled leads so they are eligible for processing."""
    result = db["leads_raw"].update_many(
        {"classification_status": {"$in": [
            "pending", "Pending", "failed", "Failed", "Processing", "processing"
        ]}},
        {"$set": {"classification_status": "pending", "classification_attempts": 0}},
    )
    log.info(f"Reset {result.modified_count} leads → status=pending, attempts=0")
    total = db["leads_raw"].count_documents({"classification_status": "pending"})
    log.info(f"Total pending leads ready: {total}")
    return total


def fetch_batch(db, size: int):
    """Fetch the next N pending lead IDs (atomic: only finds status=pending)."""
    return [
        str(doc["_id"])
        for doc in db["leads_raw"].find(
            {"classification_status": "pending", "classification_attempts": {"$lt": 10}},
            {"_id": 1},
        ).limit(size)
    ]


def process_lead(lead_id: str, classify_fn) -> tuple[bool, str | None]:
    """
    Worker function: classify one lead, retrying on quota errors.
    Returns (success, error_or_None).
    """
    deadline = datetime.utcnow() + timedelta(minutes=QUOTA_WAIT_MAX_M)
    attempt = 0

    while True:
        ok, error = classify_fn(lead_id)

        if ok:
            return True, None

        error_str = error or ""
        if is_quota_error(error_str):
            if datetime.utcnow() > deadline:
                return False, f"quota_timeout after {QUOTA_WAIT_MAX_M}min"
            attempt += 1
            sleep_s = min(QUOTA_SLEEP_S * (2 ** (attempt - 1)), 120)  # exp back-off, cap 2min
            log.debug(f"[{lead_id[:8]}] quota 429 — back-off {sleep_s}s (attempt {attempt})")
            time.sleep(sleep_s)
            # retry
        else:
            return False, error_str[:200]


def run():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["email_automation"]

    log.info(f"=== Torpedo Enrichment Runner started | workers={WORKERS} ===")

    total_pending = reset_and_count(db)
    if total_pending == 0:
        log.info("No pending leads. Exiting.")
        return

    # Import after path is set up
    from leads.service import classify_single_lead

    # Thread-safe counters
    _lock = threading.Lock()
    counts = {"success": 0, "failure": 0, "processed": 0}

    def bump(ok: bool):
        with _lock:
            counts["processed"] += 1
            if ok:
                counts["success"] += 1
            else:
                counts["failure"] += 1
            return counts["processed"]

    start = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        while True:
            batch = fetch_batch(db, BATCH_SIZE)
            if not batch:
                log.info("No more pending leads in queue.")
                break

            futures = {
                pool.submit(process_lead, lead_id, classify_single_lead): lead_id
                for lead_id in batch
            }

            for future in as_completed(futures):
                lead_id = futures[future]
                try:
                    ok, err = future.result()
                except Exception as exc:
                    ok, err = False, str(exc)

                n = bump(ok)

                if not ok and err and "quota_timeout" not in err:
                    log.debug(f"[{lead_id[:8]}] failed: {err}")

                if n % PROGRESS_EVERY == 0:
                    elapsed = time.time() - start
                    rate = n / elapsed if elapsed > 0 else 0
                    remaining = db["leads_raw"].count_documents(
                        {"classification_status": "pending",
                         "classification_attempts": {"$lt": 10}}
                    )
                    eta_m = (remaining / rate / 60) if rate > 0 else 0
                    log.info(
                        f"Progress {n} done | "
                        f"success={counts['success']} failed={counts['failure']} | "
                        f"{rate:.1f} leads/s | {remaining} remaining | ETA ~{eta_m:.0f}min"
                    )

    elapsed_total = (time.time() - start) / 60
    log.info(
        f"=== Done in {elapsed_total:.1f} min | "
        f"success={counts['success']} failed={counts['failure']} "
        f"total={counts['processed']} ==="
    )


if __name__ == "__main__":
    run()

