"""
PANEL INTELLIGENCE AGENT  (Phase 5 — panel mirror + fraud/anomaly flagging)

Keeps the panel "external for MVP, connected by API and mirrored into CRM" per
the master plan: it reads panelist activity from a configurable source and
mirrors a lightweight status record into `crm_db.panel_mirror` (one per panelist,
upserted). It also flags fraud/anomaly signals and routes them through the AI
decision engine (recommend mode -> a review task).

The fraud heuristic (`assess_panelist`) is a pure function (no I/O), unit-tested.
Field mapping is tolerant of common panel field names; the source db/collection
is configurable so it can point at the real panel store or a test fixture.

Usage:
    python -m backend.agents.panel_intelligence_agent --dry-run
    python -m backend.agents.panel_intelligence_agent --execute --limit 500
"""

import argparse
from datetime import datetime
from typing import Optional, Dict, Any, List

from app.services import crm_service, ai_engine
from database import get_database

AGENT_NAME = "panel_intelligence_agent"
MIRROR_COLLECTION = "panel_mirror"

REWARD_PER_SURVEY_LIMIT = 50.0   # avg reward/complete above this is suspicious
HIGH_REWARD_FLOOR = 500.0        # only scrutinise once total rewards are material

_ID_KEYS = ["panelist_id", "panelistId", "id", "vid", "uid", "email"]
_EMAIL_KEYS = ["email", "email_address", "panelistEmail"]
_SURVEYS_KEYS = ["surveys_completed", "completes", "completed_surveys", "completes_n"]
_REWARDS_KEYS = ["rewards_total", "reward_total", "points", "rewards", "total_rewards"]
_STATUS_KEYS = ["status", "state", "panelStatus"]


def _first(doc, keys, default=None):
    for k in keys:
        v = doc.get(k)
        if v not in (None, ""):
            return v
    return default


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def assess_panelist(panelist: Dict[str, Any]) -> Dict[str, Any]:
    """Pure fraud/anomaly heuristic. Returns {risk: low|high, reasons: [...]}. No I/O."""
    surveys = _num(_first(panelist, _SURVEYS_KEYS, 0))
    rewards = _num(_first(panelist, _REWARDS_KEYS, 0))
    status = (_first(panelist, _STATUS_KEYS, "") or "").lower()

    reasons: List[str] = []
    if rewards > 0 and surveys == 0:
        reasons.append("rewards_without_completions")
    if rewards >= HIGH_REWARD_FLOOR and surveys > 0 and (rewards / surveys) > REWARD_PER_SURVEY_LIMIT:
        reasons.append("reward_per_survey_too_high")
    if status in ("flagged", "suspicious", "fraud", "banned"):
        reasons.append(f"status_{status}")

    return {"risk": "high" if reasons else "low", "reasons": reasons}


def _mirror_col():
    return crm_service._db()[MIRROR_COLLECTION]


def run(
    autonomy_mode: str = "recommend",
    source_db: str = "panel",
    source_collection: str = "panelists",
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Mirror panel activity into the spine and flag anomalies. Returns stats."""
    src = get_database(source_db)[source_collection]
    stats = {
        "agent": AGENT_NAME, "mode": autonomy_mode, "dry_run": dry_run,
        "scanned": 0, "mirrored": 0, "flagged": 0, "errors": 0,
    }

    cursor = src.find({})
    if limit:
        cursor = cursor.limit(limit)

    for p in cursor:
        stats["scanned"] += 1
        pid = str(_first(p, _ID_KEYS, p.get("_id")))
        try:
            assessment = assess_panelist(p)
            if not dry_run:
                _mirror_col().update_one(
                    {"panelist_id": pid},
                    {"$set": {
                        "panelist_id": pid,
                        "email": _first(p, _EMAIL_KEYS),
                        "surveys_completed": _num(_first(p, _SURVEYS_KEYS, 0)),
                        "rewards_total": _num(_first(p, _REWARDS_KEYS, 0)),
                        "status": _first(p, _STATUS_KEYS),
                        "risk": assessment["risk"],
                        "risk_reasons": assessment["reasons"],
                        "source": f"{source_db}.{source_collection}",
                        "last_synced": datetime.utcnow(),
                    }},
                    upsert=True,
                )
            stats["mirrored"] += 1

            if assessment["risk"] == "high" and not dry_run:
                ai_engine.submit_decision(
                    AGENT_NAME,
                    decision=f"Panelist {pid} flagged: {', '.join(assessment['reasons'])}",
                    recommended_action=f"Review panelist {pid} for fraud ({', '.join(assessment['reasons'])})",
                    confidence=0.6,
                    reason="Heuristic fraud/anomaly signals on mirrored panel activity.",
                    autonomy_mode=autonomy_mode,
                    risk="medium",
                    linked_object_type="panelist",
                    linked_object_id=pid,
                    input_summary={"panelist_id": pid, "reasons": assessment["reasons"]},
                )
                stats["flagged"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  ⚠️ error on panelist={pid}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Mirror panel activity + flag fraud into the CRM spine.")
    parser.add_argument("--mode", default="recommend", choices=["observe", "recommend", "approve", "autopilot"])
    parser.add_argument("--source-db", default="panel")
    parser.add_argument("--source-collection", default="panelists")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true", help="Write changes (default is dry-run).")
    args = parser.parse_args()

    stats = run(
        autonomy_mode=args.mode, source_db=args.source_db,
        source_collection=args.source_collection, limit=args.limit, dry_run=not args.execute,
    )
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Panel intelligence [{mode}] ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
