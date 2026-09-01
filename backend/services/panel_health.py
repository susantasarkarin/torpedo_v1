"""
Panel health check - the thing that would have caught every outage this
project has had so far without a human reading logs by hand.

Three failure modes this exists to catch, all of which happened silently in
production before someone went looking:
  1. A cron stops firing but never errors (lead promotion: scanned=0 every
     night for two weeks because a lookback window could never match).
  2. A send pipeline degrades but "succeeded" (bounce rate climbing with
     nothing watching it).
  3. Shared infrastructure runs out (SES quota starving transactional mail
     that real users are waiting on).

No alert destination (Slack webhook, alert email) is configured anywhere in
this deployment, so this does NOT try to page anyone. It does two things that
are useful without one: logs at ERROR/WARNING on threshold breach (so it is
visible in `journalctl -u torpedo-backend` and picked up for free by any log
shipper added later) and exposes a snapshot via
GET /panel-admin/dashboard/health for the admin dashboard. If SLACK_WEBHOOK_URL
is ever set this also posts there - same optional-fallback shape as the
DigitalOcean inference fallback: absent means silently skipped, not broken.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

import requests

logger = logging.getLogger("panel_health")

from services.panel_bounce_handler import invitation_log_collection, suppression_collection
from services.panel_job_state import get_all_heartbeats

# job_name -> (expected cadence in hours, human label). Matches the beat
# schedule in celery_app.py; the multiplier below turns cadence into a
# staleness threshold with generous buffer for retries.
JOB_CADENCE_HOURS: Dict[str, Any] = {
    "suppression_sync": (24, "SES suppression sync"),
    "lead_promotion": (24, "Traffic lead promotion"),
    "registration_sync": (24, "SFW registration sync"),
    "invite_cron": (24, "Daily join-panel invites"),
    "login_cron": (24, "Daily login reminders"),
    "drip_cron": (24, "Re-engagement drips"),
}
# A job is STALE once it's this many cadences overdue. 1.25x a 24h job means
# it hasn't run in 30h - one missed run plus room for the retry/backoff window
# built into each task, not two consecutive misses.
STALE_MULTIPLIER = 1.25

FAILURE_RATE_WARN = 0.20
FAILURE_RATE_ERROR = 0.40

SLACK_WEBHOOK_URL = (os.getenv("SLACK_WEBHOOK_URL") or "").strip()


def _job_staleness() -> List[Dict[str, Any]]:
    now = datetime.utcnow()
    heartbeats = get_all_heartbeats()
    out = []
    for job_name, (cadence_hours, label) in JOB_CADENCE_HOURS.items():
        last = heartbeats.get(job_name)
        threshold = timedelta(hours=cadence_hours * STALE_MULTIPLIER)
        if last is None:
            status = "never_seen"
            age_hours = None
        else:
            age = now - last
            age_hours = round(age.total_seconds() / 3600, 1)
            status = "stale" if age > threshold else "ok"
        out.append({
            "job": job_name, "label": label, "last_success_at": last.isoformat() if last else None,
            "age_hours": age_hours, "threshold_hours": cadence_hours * STALE_MULTIPLIER,
            "status": status,
        })
    return out


def _send_failure_stats(window_hours: int = 24) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(hours=window_hours)
    pipeline = [
        {"$match": {"sent_at": {"$gte": since}, "status": {"$in": ["sent", "failed"]}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]
    counts = {row["_id"]: row["n"] for row in invitation_log_collection.aggregate(pipeline)}
    sent = counts.get("sent", 0)
    failed = counts.get("failed", 0)
    total = sent + failed
    rate = (failed / total) if total else 0.0

    # Breakdown by cause. Only populated for failures logged after error_code
    # capture was added - earlier rows have nothing to group by.
    breakdown_pipeline = [
        {"$match": {"sent_at": {"$gte": since}, "status": "failed",
                    "error_code": {"$exists": True, "$ne": ""}}},
        {"$group": {"_id": "$error_code", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 10},
    ]
    breakdown = {
        row["_id"]: row["n"]
        for row in invitation_log_collection.aggregate(breakdown_pipeline)
    }
    unclassified = failed - sum(breakdown.values())

    return {
        "window_hours": window_hours, "sent": sent, "failed": failed, "total": total,
        "failure_rate": round(rate, 4), "by_error_code": breakdown,
        "unclassified_failures": max(0, unclassified),
    }


def _suppression_velocity(window_hours: int = 24) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(hours=window_hours)
    pipeline = [
        {"$match": {"suppressed_at": {"$gte": since}}},
        {"$group": {"_id": "$reason", "n": {"$sum": 1}}},
    ]
    by_reason = {row["_id"]: row["n"] for row in suppression_collection.aggregate(pipeline)}
    return {"window_hours": window_hours, "by_reason": by_reason,
            "total": sum(by_reason.values())}


def _ses_quota() -> Dict[str, Any]:
    try:
        from services.panel_email_service import _get_ses_client, PANEL_SES_RESERVE, PANEL_DAILY_SEND_CAP
        quota = _get_ses_client().get_send_quota()
        max_24h = int(quota.get("Max24HourSend") or 0)
        sent_24h = int(quota.get("SentLast24Hours") or 0)
        remaining = max(0, max_24h - sent_24h) if max_24h > 0 else None
        return {
            "reachable": True, "max_24h": max_24h, "sent_last_24h": sent_24h,
            "remaining": remaining, "transactional_reserve": PANEL_SES_RESERVE,
            "transactional_at_risk": remaining is not None and remaining < PANEL_SES_RESERVE,
        }
    except Exception as e:
        return {"reachable": False, "error": str(e)}


def _post_to_slack(text: str) -> None:
    if not SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=5)
    except Exception as e:
        logger.warning(f"[panel-health] Slack post failed (non-fatal): {e}")


def check_panel_health() -> Dict[str, Any]:
    """Full snapshot + threshold evaluation. Logs on breach; never raises -
    a health check that can crash the thing it's monitoring defeats the point."""
    jobs = _job_staleness()
    failures = _send_failure_stats()
    suppression = _suppression_velocity()
    quota = _ses_quota()

    problems: List[str] = []

    stale_jobs = [j for j in jobs if j["status"] == "stale"]
    for j in stale_jobs:
        msg = (f"[panel-health] STALE JOB: {j['label']} ({j['job']}) has not "
               f"completed in {j['age_hours']}h (threshold {j['threshold_hours']}h)")
        logger.error(msg)
        problems.append(msg)

    never_seen = [j for j in jobs if j["status"] == "never_seen"]
    for j in never_seen:
        # WARNING not ERROR: a freshly-deployed heartbeat has no history yet.
        # It graduates to ERROR the first time it's actually overdue.
        logger.warning(f"[panel-health] job {j['job']} has never reported a heartbeat")

    if failures["total"] >= 20:  # ignore noise at tiny sample sizes
        rate = failures["failure_rate"]
        if rate >= FAILURE_RATE_ERROR:
            msg = (f"[panel-health] SEND FAILURE RATE {rate:.1%} over "
                   f"{failures['window_hours']}h ({failures['failed']}/{failures['total']})")
            logger.error(msg)
            problems.append(msg)
        elif rate >= FAILURE_RATE_WARN:
            logger.warning(
                f"[panel-health] send failure rate {rate:.1%} over "
                f"{failures['window_hours']}h ({failures['failed']}/{failures['total']})")

    if quota.get("transactional_at_risk"):
        msg = (f"[panel-health] SES QUOTA AT RISK: {quota.get('remaining')} remaining, "
               f"below the {quota.get('transactional_reserve')} transactional reserve")
        logger.error(msg)
        problems.append(msg)
    elif not quota.get("reachable"):
        logger.warning(f"[panel-health] could not read SES quota: {quota.get('error')}")

    if problems:
        _post_to_slack("Panel health check found issues:\n" + "\n".join(problems))

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "jobs": jobs,
        "send_failures": failures,
        "suppression_velocity": suppression,
        "ses_quota": quota,
        "problems": problems,
        "healthy": not problems,
    }
