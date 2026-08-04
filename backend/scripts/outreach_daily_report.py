"""
OUTREACH DAILY HEALTH REPORT
============================
Answers, in one place: are the per-account send caps holding, is the AI
personalisation actually being used, and is the bounce rate safe?

Written after the 2026-08-03 incident (all three Gmail accounts at ~2,000/day
against Google's hard cap, 45% bounce on two of them). Each section prints an
OK/WARN/ALERT verdict so this is usable from cron without reading numbers.

Usage:
    python -m scripts.outreach_daily_report            # today (UTC)
    python -m scripts.outreach_daily_report --day -1   # yesterday
    python -m scripts.outreach_daily_report --quiet    # only WARN/ALERT lines

Exit code is 1 when anything is at ALERT, so cron can mail on failure only.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

# Bounce thresholds. Mailbox providers throttle well below 10%.
BOUNCE_WARN = 0.05
BOUNCE_ALERT = 0.10

_verdicts = []


def say(level: str, message: str, quiet: bool = False) -> None:
    _verdicts.append(level)
    if quiet and level == "OK":
        return
    print(f"  [{level:5s}] {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Outreach daily health report")
    parser.add_argument("--day", type=int, default=0,
                        help="0 = today (UTC), -1 = yesterday, etc.")
    parser.add_argument("--quiet", action="store_true",
                        help="print only WARN/ALERT lines")
    args = parser.parse_args()

    day_start = (datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                 + timedelta(days=args.day))
    day_end = day_start + timedelta(days=1)
    window = {"$gte": day_start, "$lt": day_end}

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    t = client["torpedo"]
    sends = t["outreach_sends_v2"]

    print(f"=== Outreach report for {day_start:%Y-%m-%d} (UTC) ===")

    # Resolve the configured cap without importing the FastAPI router.
    try:
        cap = int(os.getenv("OUTREACH_DAILY_LIMIT_PER_MAILBOX", "") or 500)
    except (TypeError, ValueError):
        cap = 500

    # ---- 1. Per-account volume vs cap --------------------------------
    print("\n-- send volume vs cap --")
    volume = list(sends.aggregate([
        {"$match": {"sent_at": window}},
        {"$group": {"_id": "$from_email", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]))
    if not volume:
        say("OK", "no sends in this window", args.quiet)
    for row in volume:
        account, n = row["_id"], row["n"]
        if n > cap:
            say("ALERT", f"{account}: {n} sends EXCEEDS cap {cap}", args.quiet)
        elif n > cap * 0.9:
            say("WARN", f"{account}: {n}/{cap} (>90% of cap)", args.quiet)
        else:
            say("OK", f"{account}: {n}/{cap}", args.quiet)

    # ---- 2. Quota counters -------------------------------------------
    print("\n-- quota counters --")
    day_key = f"{day_start:%Y-%m-%d}"
    counters = list(t["outreach_daily_quota"].find({"day": day_key}))
    if not counters:
        say("WARN", f"no quota counters for {day_key} "
                    "(reservation code may not be running)", args.quiet)
    for doc in counters:
        count, limit = doc.get("count", 0), doc.get("limit", cap)
        label = f"{doc.get('from_email')}: counter={count} limit={limit}"
        say("ALERT" if count > limit else "OK", label, args.quiet)

    # ---- 3. AI personalisation ---------------------------------------
    print("\n-- content source --")
    by_source = {r["_id"]: r["n"] for r in sends.aggregate([
        {"$match": {"sent_at": window}},
        {"$group": {"_id": "$content_source", "n": {"$sum": 1}}},
    ])}
    total = sum(by_source.values())
    if not total:
        say("OK", "no sends to classify", args.quiet)
    else:
        ai = by_source.get("ai", 0)
        template = by_source.get("template", 0)
        unstamped = by_source.get(None, 0)
        if unstamped:
            say("ALERT", f"{unstamped} sends with NO content_source — a sender "
                         "process is running pre-fix code (restart workers)",
                args.quiet)
        if ai:
            say("OK", f"ai={ai} ({100.0 * ai / total:.0f}%)", args.quiet)
        if template:
            level = "WARN" if template > ai else "OK"
            say(level, f"template fallback={template} "
                       f"({100.0 * template / total:.0f}%)", args.quiet)

    # ---- 4. Bounce rate ----------------------------------------------
    print("\n-- bounce rate --")
    per_account = list(sends.aggregate([
        {"$match": {"sent_at": window}},
        {"$group": {
            "_id": "$from_email",
            "total": {"$sum": 1},
            "bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}},
        }},
        {"$sort": {"total": -1}},
    ]))
    for row in per_account:
        total_n = max(row["total"], 1)
        rate = row["bounced"] / total_n
        label = f"{row['_id']}: {row['bounced']}/{row['total']} = {rate:.1%}"
        if rate >= BOUNCE_ALERT:
            say("ALERT", label + "  <-- suspension risk", args.quiet)
        elif rate >= BOUNCE_WARN:
            say("WARN", label, args.quiet)
        else:
            say("OK", label, args.quiet)

    # ---- 5. Bounce-recovery guessing ---------------------------------
    print("\n-- guessed-address enrolment --")
    guessed = t["outreach_leads_v2"].count_documents({
        "created_at": window, "email_source": "bounce_recovery_alt"})
    if guessed:
        say("ALERT", f"{guessed} leads enrolled from bounce_recovery_alt — "
                     "alt-format guessing is ON (OUTREACH_BOUNCE_RECOVERY_ALT)",
            args.quiet)
    else:
        say("OK", "no alt-format guessed addresses enrolled", args.quiet)

    alerts = _verdicts.count("ALERT")
    warns = _verdicts.count("WARN")
    print(f"\n=== {alerts} ALERT, {warns} WARN ===")
    return 1 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
