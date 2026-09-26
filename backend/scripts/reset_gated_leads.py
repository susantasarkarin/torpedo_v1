#!/usr/bin/env python3
"""
One-time migration: re-evaluate leads a fixed config problem retired
(workflow_status skipped_gate / skipped_high_bounce_risk) against every
send-time check, live, and reset the ones that are genuinely clean into a
staggered, capped resume schedule. See leads/gate_reset.py for the full
rationale and why this must NOT be automatic.

Usage:
    python scripts/reset_gated_leads.py --campaign-id <id>                    # dry run
    python scripts/reset_gated_leads.py --campaign-id <id> --apply --daily-cap 25
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient

from leads.gate_reset import apply_reset, select_reset_candidates, stage_batches

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "torpedo")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--daily-cap", type=int, default=25)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[MONGO_DB_NAME]

    candidates = select_reset_candidates(db, args.campaign_id)
    clean = [c for c in candidates if c.clean]
    held = [c for c in candidates if not c.clean]

    print(f"Evaluated {len(candidates)} retired leads for campaign {args.campaign_id}.")
    print(f"  clean (ready to reset): {len(clean)}")
    print(f"  held back: {len(held)}")
    if held:
        reasons = {}
        for c in held:
            key = c.held_reason.split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
        for reason, n in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {n}")

    staged = stage_batches(clean, daily_cap=args.daily_cap)
    if staged:
        days = (len(staged) - 1) // args.daily_cap + 1
        print(f"\nWith a cap of {args.daily_cap}/day, this schedules over {days} day(s).")

    result = apply_reset(db, staged, dry_run=not args.apply)
    if args.apply:
        print(f"\nApplied: reset {result['applied']} of {result['would_reset']} leads "
              f"into their staggered schedule.")
    else:
        print(f"\nDry run only — nothing written. Would reset {result['would_reset']} leads. "
              f"Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
