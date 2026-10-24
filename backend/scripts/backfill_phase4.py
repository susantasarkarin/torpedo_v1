"""Phase 4 backfill runner. Dry run unless --apply; --apply refuses to run
without a mongodump newer than --max-backup-age-hours (default 3).

  venv/bin/python scripts/backfill_phase4.py                 # all steps, dry run
  venv/bin/python scripts/backfill_phase4.py --step rfq_bu --apply

Each run is recorded in email_automation.backfill_runs and audit-logged.
"""
import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pymongo import MongoClient  # noqa: E402

from backfill import steps  # noqa: E402


def latest_backup_age_hours(backup_dir: str) -> float:
    dumps = sorted(glob.glob(os.path.join(backup_dir, "*", "full.archive.gz")))
    if not dumps:
        return float("inf")
    return (time.time() - os.path.getmtime(dumps[-1])) / 3600


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", action="append", help="step name (repeatable); default all")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup-dir", default=os.getenv("BACKUP_DIR", "/var/www/campaign_platform/backups"))
    ap.add_argument("--max-backup-age-hours", type=float, default=3.0)
    a = ap.parse_args()
    if a.apply:
        age = latest_backup_age_hours(a.backup_dir)
        if age > a.max_backup_age_hours:
            sys.exit(f"refusing to apply: newest mongodump is {age:.1f} h old (> {a.max_backup_age_hours})")
    c = MongoClient(os.environ["MONGO_URI"])
    names = a.step or [n for n, _ in steps.STEPS]
    fns = dict(steps.STEPS)
    now = datetime.utcnow()
    out = {}
    for n in names:
        t0 = time.time()
        rep = fns[n](c, apply=a.apply, now=now)
        out[n] = {**rep, "secs": round(time.time() - t0, 1)}
        print(json.dumps({n: out[n]}, default=str), flush=True)
        if a.apply:
            c.email_automation.backfill_runs.insert_one({"step": n, "at": now, "report": json.loads(json.dumps(out[n], default=str))})
            c.crm_db.audit_log.insert_one({"timestamp": now, "user_id": "system:backfill", "action": "update",
                                           "entity_type": "backfill", "entity_id": n, "reason": "Phase 4 backfill",
                                           "metadata": {"report": json.loads(json.dumps(out[n], default=str))}})


if __name__ == "__main__":
    main()
