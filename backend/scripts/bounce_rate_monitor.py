"""
Bounce-rate and enrichment-stall monitoring, per source/campaign — plus
the Part 4 warm-up automatic halt.

Run manually (`python scripts/bounce_rate_monitor.py`) or on a cron/systemd
timer (recommended: every 15-30 min once warm-up sending resumes). Mostly
read-only — the one write this script can make is deliberate and narrow:
with --enforce-halt, if trailing-24h bounce rate for ANY campaign exceeds
HALT_BOUNCE_RATE_THRESHOLD, it flips outreach_kill_switch (the same doc
cold_outreach_router.py checks before every send) to paused=True. That's
the whole mechanism — it can only pause, never un-pause; resuming after a
halt is a deliberate human action via outreach_kill_switch.py.

Three things this repo otherwise has no visibility into without
SSH+mongosh archaeology (see the 2026-08-28 bounce-diagnosis findings doc):
  1. Bounce rate per source/campaign, trailing N days.
  2. Email-capture rate per source, trailing N days.
  3. Whether the AwaitingEnrichment queue is actually being drained
     (the background_enrich_leads job can silently stop running).

Exit code is non-zero when a configured threshold is breached, so this can
be wired into a cron job that alerts (e.g. mails/Slacks on failure) without
extra code.
"""

import os
import sys
from datetime import datetime, timedelta

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "torpedo")

BOUNCE_RATE_ALERT_THRESHOLD = float(os.getenv("BOUNCE_RATE_ALERT_THRESHOLD", "0.05"))  # 5%
# Part 4 warm-up spec: automatic halt if bounce rate exceeds 2% in any
# trailing 24h window. Separate from the 30-day alert threshold above —
# this one is tighter and triggers a write (the pause), not just a print.
HALT_BOUNCE_RATE_THRESHOLD = float(os.getenv("HALT_BOUNCE_RATE_THRESHOLD", "0.02"))  # 2%
HALT_MIN_SENDS = int(os.getenv("HALT_MIN_SENDS", "20"))  # don't halt on tiny/noisy samples
ENRICHMENT_STALL_ALERT_HOURS = float(os.getenv("ENRICHMENT_STALL_ALERT_HOURS", "3"))
CAPTURE_RATE_ALERT_THRESHOLD = float(os.getenv("CAPTURE_RATE_ALERT_THRESHOLD", "0.30"))  # 30%
LOOKBACK_DAYS = int(os.getenv("BOUNCE_MONITOR_LOOKBACK_DAYS", "30"))


def check_bounce_rate_by_campaign(client: MongoClient) -> bool:
    """Print bounce rate per campaign/business over the trailing window.
    Returns True if everything is under threshold, False if any campaign
    breached it (used as the process exit signal)."""
    tp = client[MONGO_DB_NAME]
    since = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)

    campaigns = {
        c["campaign_id"]: c.get("business", c["campaign_id"])
        for c in tp["outreach_campaigns_v2"].find({}, {"campaign_id": 1, "business": 1})
    }

    pipeline = [
        {"$match": {"sent_at": {"$gte": since}}},
        {"$group": {
            "_id": "$campaign_id",
            "total": {"$sum": 1},
            "bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}},
        }},
    ]

    ok = True
    print(f"\n=== Bounce rate by campaign (trailing {LOOKBACK_DAYS}d, alert > {BOUNCE_RATE_ALERT_THRESHOLD:.0%}) ===")
    for row in tp["outreach_sends_v2"].aggregate(pipeline):
        total = row["total"]
        bounced = row["bounced"]
        rate = bounced / total if total else 0.0
        business = campaigns.get(row["_id"], row["_id"])
        flag = " *** OVER THRESHOLD ***" if rate > BOUNCE_RATE_ALERT_THRESHOLD else ""
        if flag:
            ok = False
        print(f"  {business:20s} sends={total:5d} bounced={bounced:4d} rate={rate:6.1%}{flag}")

    return ok


def check_capture_rate_by_source(client: MongoClient) -> bool:
    """Print email-capture rate per lead source over the trailing window.
    Returns True if every source is above threshold, False if any source
    is under-capturing (used as the process exit signal)."""
    ea = client["email_automation"]
    since = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)

    pipeline = [
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {
            "_id": "$source",
            "total": {"$sum": 1},
            "with_email": {"$sum": {
                "$cond": [{"$and": [
                    {"$eq": [{"$type": "$email"}, "string"]},
                    {"$ne": ["$email", ""]},
                ]}, 1, 0]},
            },
        }},
    ]

    ok = True
    print(f"\n=== Email capture rate by source (trailing {LOOKBACK_DAYS}d, alert < {CAPTURE_RATE_ALERT_THRESHOLD:.0%}) ===")
    for row in ea["leads_raw"].aggregate(pipeline):
        total = row["total"]
        with_email = row["with_email"]
        rate = with_email / total if total else 0.0
        flag = " *** UNDER THRESHOLD ***" if rate < CAPTURE_RATE_ALERT_THRESHOLD else ""
        if flag:
            ok = False
        print(f"  {str(row['_id']):20s} leads={total:5d} with_email={with_email:4d} rate={rate:6.1%}{flag}")

    return ok


def check_enrichment_stall(client: MongoClient) -> bool:
    """True if the enrichment queue is being drained; False if it looks
    stalled (nothing attempted recently while a backlog exists)."""
    ea = client["email_automation"]
    cutoff = datetime.utcnow() - timedelta(hours=ENRICHMENT_STALL_ALERT_HOURS)

    backlog = ea["leads_raw"].count_documents({"classification_status": "AwaitingEnrichment"})
    attempted_recently = ea["leads_raw"].count_documents(
        {"last_classification_attempt": {"$gte": cutoff}}
    )

    print(f"\n=== Enrichment queue health (stall alert if backlog > 0 and 0 attempts in {ENRICHMENT_STALL_ALERT_HOURS}h) ===")
    print(f"  AwaitingEnrichment backlog: {backlog}")
    print(f"  Classification attempts in last {ENRICHMENT_STALL_ALERT_HOURS}h: {attempted_recently}")

    stalled = backlog > 0 and attempted_recently == 0
    if stalled:
        print("  *** STALLED: backlog exists but nothing has been attempted recently ***")
    return not stalled


def check_and_enforce_24h_halt(client: MongoClient, enforce: bool) -> bool:
    """Part 4 automatic halt: trailing-24h bounce rate per campaign. If any
    campaign is over HALT_BOUNCE_RATE_THRESHOLD (default 2%) with at least
    HALT_MIN_SENDS sends in that window, and `enforce` is True, pause the
    global kill switch. Returns True if nothing needed halting."""
    tp = client[MONGO_DB_NAME]
    since = datetime.utcnow() - timedelta(hours=24)

    campaigns = {
        c["campaign_id"]: c.get("business", c["campaign_id"])
        for c in tp["outreach_campaigns_v2"].find({}, {"campaign_id": 1, "business": 1})
    }
    pipeline = [
        {"$match": {"sent_at": {"$gte": since}}},
        {"$group": {
            "_id": "$campaign_id",
            "total": {"$sum": 1},
            "bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}},
        }},
    ]

    print(f"\n=== 24h bounce-rate halt check (threshold {HALT_BOUNCE_RATE_THRESHOLD:.0%}, "
          f"min {HALT_MIN_SENDS} sends) ===")
    breaches = []
    for row in tp["outreach_sends_v2"].aggregate(pipeline):
        total, bounced = row["total"], row["bounced"]
        if total < HALT_MIN_SENDS:
            continue
        rate = bounced / total
        business = campaigns.get(row["_id"], row["_id"])
        flag = rate > HALT_BOUNCE_RATE_THRESHOLD
        print(f"  {business:20s} sends={total:4d} bounced={bounced:3d} rate={rate:6.1%}"
              f"{' *** HALT TRIGGERED ***' if flag else ''}")
        if flag:
            breaches.append((business, rate))

    if not breaches:
        print("  No campaign over threshold in the last 24h.")
        return True

    if enforce:
        col = tp["outreach_kill_switch"]
        reason = ("Automatic halt: " +
                   ", ".join(f"{b} at {r:.1%}" for b, r in breaches) +
                   f" (threshold {HALT_BOUNCE_RATE_THRESHOLD:.0%}) — bounce_rate_monitor.py")
        col.update_one(
            {"_id": "global"},
            {"$set": {
                "paused": True,
                "reason": reason,
                "updated_at": datetime.utcnow(),
                "updated_by": "bounce_rate_monitor.py --enforce-halt",
            }},
            upsert=True,
        )
        print(f"  *** ENFORCED: outreach_kill_switch set to paused. Reason: {reason}")
    else:
        print("  Would halt (pass --enforce-halt to actually pause sending).")

    return False


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enforce-halt", action="store_true",
                         help="Actually pause the kill switch if the 24h bounce rate check trips. "
                              "Without this flag, the check only reports what it would do.")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    bounce_ok = check_bounce_rate_by_campaign(client)
    capture_ok = check_capture_rate_by_source(client)
    enrichment_ok = check_enrichment_stall(client)
    halt_ok = check_and_enforce_24h_halt(client, args.enforce_halt)
    return 0 if (bounce_ok and capture_ok and enrichment_ok and halt_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
