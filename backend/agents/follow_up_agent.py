"""
FOLLOW-UP AGENT  (Phase 5 — falling-through-the-cracks detection)

Scans OPEN opportunities in the canonical CRM spine and flags ones that have
gone stale (no activity for `stale_days`), raising a follow-up task through the
AI decision engine so it surfaces in the right autonomy lane:
  - recommend mode (default): creates the follow-up task immediately
  - approve mode: parks the task creation as a pending action for human approval

"Stale" = the most recent linked activity (or the opportunity's own
updated_at/created_at) is older than the threshold.

Idempotent / non-spammy:
  - skips opportunities already nudged within `cooldown_days` (via logged
    ai_decisions), and
  - skips opportunities that already have an open follow-up task from this agent.

Usage:
    python -m backend.agents.follow_up_agent --dry-run
    python -m backend.agents.follow_up_agent --mode recommend --stale-days 14 --execute
"""

import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

try:
    from ..app.services import crm_service, ai_engine
except ImportError:  # pragma: no cover - absolute import / CLI fallback
    from app.services import crm_service, ai_engine

AGENT_NAME = "follow_up_agent"


def _last_touch(opp_id: str, opp: Dict[str, Any]) -> Optional[datetime]:
    """Most recent activity for the opportunity, else its own timestamps."""
    act = crm_service._col("activities").find_one(
        {"opportunity_id": opp_id}, sort=[("created_at", -1)]
    )
    if act and act.get("created_at"):
        return act["created_at"]
    return opp.get("updated_at") or opp.get("created_at")


def _recently_nudged(cooldown_after: datetime) -> set:
    seen = set()
    for d in crm_service._col("ai_decisions").find(
        {"agent_name": AGENT_NAME, "created_at": {"$gte": cooldown_after}},
        {"input_summary.opportunity_id": 1},
    ):
        oid = (d.get("input_summary") or {}).get("opportunity_id")
        if oid:
            seen.add(oid)
    return seen


def _has_open_followup_task() -> set:
    seen = set()
    for t in crm_service._col("tasks").find(
        {"linked_object_type": "opportunity", "status": "pending", "metadata.agent": AGENT_NAME},
        {"linked_object_id": 1},
    ):
        if t.get("linked_object_id"):
            seen.add(t["linked_object_id"])
    return seen


def run(
    autonomy_mode: str = "recommend",
    stale_days: int = 14,
    cooldown_days: int = 7,
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Detect stale open opportunities and raise follow-up tasks. Returns stats."""
    now = datetime.utcnow()
    stale_before = now - timedelta(days=stale_days)
    cooldown_after = now - timedelta(days=cooldown_days)

    recently_nudged = _recently_nudged(cooldown_after)
    has_task = _has_open_followup_task()

    stats = {
        "agent": AGENT_NAME,
        "mode": autonomy_mode,
        "dry_run": dry_run,
        "stale_days": stale_days,
        "scanned": 0,
        "stale_found": 0,
        "skipped_recent": 0,
        "skipped_has_task": 0,
        "processed": 0,
        "recommended": 0,
        "queued": 0,
        "errors": 0,
    }

    cursor = crm_service._col("opportunities").find({"status": "open"})
    if limit:
        cursor = cursor.limit(limit)

    for opp in cursor:
        stats["scanned"] += 1
        opp_id = str(opp["_id"])
        last = _last_touch(opp_id, opp)
        if last and last > stale_before:
            continue  # still warm
        stats["stale_found"] += 1

        if opp_id in recently_nudged:
            stats["skipped_recent"] += 1
            continue
        if opp_id in has_task:
            stats["skipped_has_task"] += 1
            continue

        if dry_run:
            stats["processed"] += 1
            continue

        try:
            days_stale = (now - last).days if last else None
            title = opp.get("title") or "Untitled opportunity"
            out = ai_engine.submit_decision(
                AGENT_NAME,
                decision=f"Opportunity '{title}' has had no activity for {days_stale} days",
                recommended_action=f"Follow up: {title}",
                action_type="create_task",
                action_payload={
                    "title": f"Follow up: {title}",
                    "status": "pending",
                    "priority": 2,
                    "linked_object_type": "opportunity",
                    "linked_object_id": opp_id,
                    "metadata": {"agent": AGENT_NAME, "source": "ai", "days_stale": days_stale},
                },
                reason=f"No activity since {last.isoformat() if last else 'unknown'} "
                f"(> {stale_days}d threshold)",
                autonomy_mode=autonomy_mode,
                risk="low",
                linked_object_type="opportunity",
                linked_object_id=opp_id,
                input_summary={"opportunity_id": opp_id, "days_stale": days_stale},
            )
            stats["processed"] += 1
            if out.get("task"):
                stats["recommended"] += 1
            if out.get("queued"):
                stats["queued"] += 1
            recently_nudged.add(opp_id)
        except Exception as e:  # one bad opp shouldn't abort the run
            stats["errors"] += 1
            print(f"  ⚠️ error on opportunity_id={opp_id}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Flag stale opportunities and raise follow-up tasks.")
    parser.add_argument("--mode", default="recommend", choices=["observe", "recommend", "approve", "autopilot"])
    parser.add_argument("--stale-days", type=int, default=14)
    parser.add_argument("--cooldown-days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true", help="Write changes (default is dry-run).")
    args = parser.parse_args()

    stats = run(
        autonomy_mode=args.mode,
        stale_days=args.stale_days,
        cooldown_days=args.cooldown_days,
        limit=args.limit,
        dry_run=not args.execute,
    )
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Follow-up agent [{mode}] ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
