"""
Crash-loop alert for torpedo-backend.service.

Run on a timer (cron/systemd timer, every 15-30 min) on the VM itself —
this shells out to systemctl/journalctl, so it only makes sense run
locally on torpedo-prod, not from the app process.

Exit code non-zero (and a printed alert) if the service has restarted
more than CRASH_LOOP_RESTART_THRESHOLD times in the trailing
CRASH_LOOP_WINDOW_MINUTES — i.e. visible in the next run of this script
(minutes), not "discovered a month later" by someone noticing the
enrichment backlog isn't draining.

Root cause context (see HALT_AND_VERIFY_PLAN_2026-08-28.md Part 2): the
crash loop is caused by ~99 call sites across this codebase creating a
fresh pymongo.MongoClient() per request/call instead of reusing the
shared pool from db_pools.py — each leaks 3 background threads and its
own connection-pool memory, accumulating until the service's 2GB
MemoryMax is hit and it's SIGKILLed. This script detects the symptom
(repeated restarts); it does not fix the cause.
"""

import subprocess
import sys
from datetime import datetime, timedelta

CRASH_LOOP_RESTART_THRESHOLD = 3
CRASH_LOOP_WINDOW_MINUTES = 60
SERVICE = "torpedo-backend.service"


def main() -> int:
    since = (datetime.utcnow() - timedelta(minutes=CRASH_LOOP_WINDOW_MINUTES)).strftime(
        "%Y-%m-%d %H:%M:%S")
    result = subprocess.run(
        ["journalctl", "-u", SERVICE, "--since", since, "--no-pager"],
        capture_output=True, text=True, timeout=30,
    )
    lines = result.stdout.splitlines()
    starts = [l for l in lines if "Started Torpedo Campaign Platform Backend" in l]
    kills = [l for l in lines if "code=killed, status=9/KILL" in l]

    print(f"=== Crash-loop check: trailing {CRASH_LOOP_WINDOW_MINUTES}min "
          f"(threshold: >{CRASH_LOOP_RESTART_THRESHOLD} restarts) ===")
    print(f"  Restarts: {len(starts)}")
    print(f"  SIGKILLs (OOM-pattern): {len(kills)}")

    if len(starts) > CRASH_LOOP_RESTART_THRESHOLD:
        print(f"  *** CRASH LOOP DETECTED: {len(starts)} restarts in "
              f"{CRASH_LOOP_WINDOW_MINUTES} minutes ***")
        return 1

    print("  OK — restart count within normal range.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
