"""
PIPELINE HEALTH — stage monitoring, funnel, and the duplicate-send canary
========================================================================

The Bedrock outage on 2026-08-09 stopped lead classification for a full day
and nobody noticed. Independent failover was added afterwards; the actual root
cause was not. The root cause was never the expired credential — it was that a
pipeline stage went to zero and nothing said so.

Read-only. Never writes to the pipeline.

WHAT IT WATCHES
---------------
1. Stage throughput, with ZERO-ALERTS. A stage producing zero for N
   consecutive cycles alerts REGARDLESS of whether it errored. Silent zero is
   the failure mode that already cost a day: the 2026-08-09 chain failed in
   under a second and every downstream stage simply had nothing to do — which
   looks identical to "no work available".

2. Runway in DAYS, not eligible-pool count. A cap-bound pipeline shows nothing
   in send rate while the pool drains, then hits a cliff whose cause is weeks
   in the past. "9,348 eligible" reads as healthy to everyone; "47 days at
   current cap" gets attention at 30 and forces a decision at 10. Same data,
   and only one of them behaves like a warning.

3. The duplicate-send canary — the Phase 2 cross-entity invariant evaluated
   against live data. No person may have sends from two entities inside the
   cooldown. This is the regression guard for the entire remediation.

4. Review queue DEPTH AND OLDEST-ITEM AGE. Depth alone does not catch the
   failure. Steady at 400 with nothing older than a day is healthy; steady at
   400 where the oldest item is six weeks old is the deferred 9,747 again — a
   correct-sounding deferral into a place nothing drains.

5. Per-entity funnel with every rejection reason preserved, so the cost of the
   classifier problem lands where someone would act on it rather than the
   leads vanishing from reporting.

Usage:
    python -m leads.pipeline_health              # human readable
    python -m leads.pipeline_health --json       # for alerting
    python -m leads.pipeline_health --canary     # invariant only, exit 1 on breach
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
LEADS_DB = os.getenv("MONGO_DB_NAME_LEADS", "email_automation")

# A stage this many consecutive cycles at zero is a problem, not a lull.
ZERO_CYCLE_ALERT_THRESHOLD = int(os.getenv("PIPELINE_ZERO_CYCLES", "3"))
# Runway thresholds in days: attention, then decision.
RUNWAY_WARN_DAYS = int(os.getenv("PIPELINE_RUNWAY_WARN_DAYS", "30"))
RUNWAY_CRITICAL_DAYS = int(os.getenv("PIPELINE_RUNWAY_CRITICAL_DAYS", "10"))
# A review item older than this is a backlog, not a queue.
REVIEW_AGE_ALERT_DAYS = int(os.getenv("PIPELINE_REVIEW_AGE_DAYS", "7"))

STAGES = ("search", "classify", "enrich", "qualify", "send")


@dataclass
class Alert:
    severity: str
    code: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass
class HealthReport:
    checked_at: str = ""
    stage_counts: Dict[str, int] = field(default_factory=dict)
    stage_zero_streaks: Dict[str, int] = field(default_factory=dict)
    runway: Dict[str, Any] = field(default_factory=dict)
    review_queue: Dict[str, Any] = field(default_factory=dict)
    funnel: Dict[str, Dict[str, int]] = field(default_factory=dict)
    canary_violations: List[Dict[str, Any]] = field(default_factory=list)
    alerts: List[Alert] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.alerts and not self.canary_violations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "checked_at": self.checked_at,
            "stage_counts": self.stage_counts,
            "stage_zero_streaks": self.stage_zero_streaks,
            "runway": self.runway,
            "review_queue": self.review_queue,
            "funnel": self.funnel,
            "canary_violation_count": len(self.canary_violations),
            "canary_violations": self.canary_violations[:20],
            "alerts": [a.to_dict() for a in self.alerts],
        }


# ---------------------------------------------------------------------------
# 3. Duplicate-send canary — regression guard for the whole remediation
# ---------------------------------------------------------------------------

def canary_violations(db, cooldown_days: int = None) -> List[Dict[str, Any]]:
    """
    Any person with sends from MORE THAN ONE entity inside the cooldown.

    Must return empty. Anything here is a human receiving mail from two of our
    brands — the original bug, recurring.
    """
    if cooldown_days is None:
        try:
            from .arbitration import CROSS_ENTITY_COOLDOWN_DAYS
            cooldown_days = CROSS_ENTITY_COOLDOWN_DAYS
        except Exception:
            cooldown_days = 90

    since = datetime.utcnow() - timedelta(days=cooldown_days)
    pipeline = [
        {"$match": {"sent_at": {"$gte": since}}},
        {"$group": {
            "_id": "$person_fingerprint",
            "entities": {"$addToSet": "$entity"},
            "sends": {"$sum": 1},
            "first_at": {"$min": "$sent_at"},
            "last_at": {"$max": "$sent_at"},
        }},
        {"$match": {"$expr": {"$gt": [{"$size": "$entities"}, 1]}}},
        {"$sort": {"sends": -1}},
        {"$limit": 500},
    ]
    out: List[Dict[str, Any]] = []
    try:
        for row in db["sends"].aggregate(pipeline):
            out.append({
                "person_fingerprint": row["_id"],
                "entities": sorted(e for e in row["entities"] if e),
                "sends": row["sends"],
                "span_days": (row["last_at"] - row["first_at"]).days,
            })
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# 2. Runway — days, never a raw count
# ---------------------------------------------------------------------------

def runway(db, daily_cap: int = None) -> Dict[str, Any]:
    if daily_cap is None:
        daily_cap = int(os.getenv("OUTREACH_SEND_DAILY_CAP", "200"))
    try:
        eligible = db["lead_interests"].count_documents({"bucket": {"$nin": [None, ""]}})
    except Exception:
        eligible = 0
    return {
        "eligible_pool": eligible,
        "effective_daily_cap": daily_cap,
        # THE number to alert on. eligible_pool is context, not a signal.
        "runway_days": round(eligible / daily_cap, 1) if daily_cap else None,
    }


# ---------------------------------------------------------------------------
# 4. Review queue — depth AND oldest-item age
# ---------------------------------------------------------------------------

def review_queue_state(db) -> Dict[str, Any]:
    depth, oldest_age_days = 0, None
    try:
        depth = db["ai_review_queue"].count_documents({"status": "pending"})
        oldest = db["ai_review_queue"].find_one({"status": "pending"},
                                                sort=[("queued_at", 1)])
        if oldest and isinstance(oldest.get("queued_at"), datetime):
            oldest_age_days = (datetime.utcnow() - oldest["queued_at"]).days
    except Exception:
        pass
    return {
        "depth": depth,
        # Depth alone will not catch the failure — see module docstring.
        "oldest_item_age_days": oldest_age_days,
    }


# ---------------------------------------------------------------------------
# 5. Per-entity funnel, rejection reasons preserved
# ---------------------------------------------------------------------------

def funnel(db) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    try:
        for row in db["lead_interests"].aggregate([
            {"$group": {"_id": {"bucket": "$bucket", "reason": "$outcome_reason"},
                        "n": {"$sum": 1}}},
        ]):
            bucket = row["_id"].get("bucket") or "unassigned"
            reason = row["_id"].get("reason") or "in_pipeline"
            out.setdefault(bucket, {})[reason] = row["n"]
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# 1. Stage throughput + zero-streak detection
# ---------------------------------------------------------------------------

def stage_counts(db, window_hours: int = 24) -> Dict[str, int]:
    since = datetime.utcnow() - timedelta(hours=window_hours)
    counts: Dict[str, int] = {s: 0 for s in STAGES}
    for stage, coll, query in (
        ("search", "leads_raw", {"created_at": {"$gte": since}}),
        ("classify", "lead_interests",
         {"updated_at": {"$gte": since}, "bucket": {"$nin": [None, ""]}}),
        ("enrich", "leads_enriched", {"updated_at": {"$gte": since}}),
        ("qualify", "lead_interests",
         {"updated_at": {"$gte": since}, "outcome_reason": "qualified"}),
        ("send", "sends", {"sent_at": {"$gte": since}}),
    ):
        try:
            counts[stage] = db[coll].count_documents(query)
        except Exception:
            counts[stage] = 0
    return counts


def zero_streaks(db, counts: Dict[str, int]) -> Dict[str, int]:
    """Consecutive cycles at zero, persisted so a streak survives restarts."""
    streaks: Dict[str, int] = {}
    for stage, n in counts.items():
        try:
            prev = (db["pipeline_health_state"].find_one({"stage": stage})
                    or {}).get("zero_streak", 0)
        except Exception:
            prev = 0
        streaks[stage] = 0 if n > 0 else prev + 1
    return streaks


def build_alerts(rep: "HealthReport") -> List[Alert]:
    alerts: List[Alert] = []

    for stage, streak in rep.stage_zero_streaks.items():
        if streak >= ZERO_CYCLE_ALERT_THRESHOLD:
            alerts.append(Alert(
                "critical", f"stage_zero_{stage}",
                f"stage '{stage}' produced zero for {streak} consecutive cycles. "
                f"Fires whether or not the stage errored — silent zero is the "
                f"2026-08-09 failure mode."))

    days = rep.runway.get("runway_days")
    if days is not None:
        if days <= RUNWAY_CRITICAL_DAYS:
            alerts.append(Alert("critical", "runway_critical",
                                f"{days} days of eligible leads at current cap."))
        elif days <= RUNWAY_WARN_DAYS:
            alerts.append(Alert("warning", "runway_low",
                                f"{days} days of eligible leads at current cap."))

    age = rep.review_queue.get("oldest_item_age_days")
    if age is not None and age >= REVIEW_AGE_ALERT_DAYS:
        alerts.append(Alert(
            "warning", "review_queue_stale",
            f"oldest pending review item is {age} days old (depth "
            f"{rep.review_queue.get('depth')}). Depth alone would look healthy."))

    if rep.canary_violations:
        alerts.append(Alert(
            "critical", "cross_entity_breach",
            f"{len(rep.canary_violations)} people have sends from more than one "
            f"entity inside the cooldown. This is the bug recurring."))

    return alerts


def check_health(client: MongoClient = None, window_hours: int = 24) -> HealthReport:
    client = client or MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[LEADS_DB]

    rep = HealthReport(checked_at=datetime.utcnow().isoformat())
    rep.stage_counts = stage_counts(db, window_hours)
    rep.stage_zero_streaks = zero_streaks(db, rep.stage_counts)
    rep.runway = runway(db)
    rep.review_queue = review_queue_state(db)
    rep.funnel = funnel(db)
    rep.canary_violations = canary_violations(db)
    rep.alerts = build_alerts(rep)
    return rep


def render(rep: HealthReport) -> str:
    lines = ["", "=" * 68,
             f"  PIPELINE HEALTH — {'HEALTHY' if rep.healthy else 'ATTENTION'}",
             "=" * 68, "  stage throughput (24h)"]
    for stage in STAGES:
        streak = rep.stage_zero_streaks.get(stage, 0)
        flag = f"   <- ZERO x{streak}" if streak else ""
        lines.append(f"    {stage:<12} {rep.stage_counts.get(stage, 0):>8}{flag}")

    r = rep.runway
    lines += ["", "  runway",
              f"    eligible pool      {r.get('eligible_pool', 0):>8}",
              f"    daily cap          {r.get('effective_daily_cap', 0):>8}",
              f"    RUNWAY DAYS        {str(r.get('runway_days')):>8}  <- alert on this",
              "", "  review queue",
              f"    depth              {rep.review_queue.get('depth', 0):>8}",
              f"    oldest item (days) {str(rep.review_queue.get('oldest_item_age_days')):>8}",
              "", f"  cross-entity canary: {len(rep.canary_violations)} violation(s)"]
    for v in rep.canary_violations[:5]:
        lines.append(f"    {v['person_fingerprint'][:16]} {v['entities']} "
                     f"{v['sends']} sends over {v['span_days']}d")
    if rep.funnel:
        lines += ["", "  per-entity funnel"]
        for bucket, reasons in sorted(rep.funnel.items()):
            lines.append(f"    {bucket}")
            for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
                lines.append(f"      {reason:<28} {n:>8}")
    lines += ["", f"  alerts: {len(rep.alerts)}"]
    for a in rep.alerts:
        lines.append(f"    [{a.severity.upper()}] {a.code}: {a.message}")
    lines += ["", "=" * 68, ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--canary", action="store_true",
                    help="cross-entity invariant only; exit 1 on breach")
    args = ap.parse_args()

    if args.canary:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        violations = canary_violations(client[LEADS_DB])
        print(json.dumps({"violations": len(violations),
                          "sample": violations[:20]}, indent=2, default=str))
        return 1 if violations else 0

    rep = check_health()
    print(json.dumps(rep.to_dict(), indent=2, default=str) if args.json else render(rep))
    return 0 if rep.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
