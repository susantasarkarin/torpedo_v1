"""
OPPORTUNITY SCORING AGENT  (Phase 5 — opportunity scoring + next-best-action)

Scores OPEN opportunities (0–100) from spine signals only (no external keys) and
derives a next-best-action. Writes `score` / `next_best_action` / `score_factors`
back onto each opportunity (idempotent — recomputed each run, low-risk derived
analytics) and logs ONE summary ai_decision per run for explainability/audit.

Scoring signals:
  - amount        (deal size, capped contribution)
  - stage         (pipeline progression weight)
  - recency       (recent activity boosts; staleness penalised)
  - linkage       (has linked account / contact)

The pure `score_opportunity()` has no I/O and is unit-tested.

Usage:
    python -m backend.agents.opportunity_scoring_agent --dry-run
    python -m backend.agents.opportunity_scoring_agent --execute --limit 200
"""

import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

try:
    from ..app.services import crm_service, ai_engine
except ImportError:  # pragma: no cover - absolute import / CLI fallback
    from app.services import crm_service, ai_engine

AGENT_NAME = "opportunity_scoring_agent"

_STAGE_POINTS = {
    "new": 5, "rfq": 10, "qualified": 20, "proposal": 30,
    "negotiation": 40, "won": 50, "lost": 0,
}


def score_opportunity(opp: Dict[str, Any], last_activity: Optional[datetime],
                      now: Optional[datetime] = None) -> Dict[str, Any]:
    """Pure scorer: returns {score, next_best_action, factors}. No I/O."""
    now = now or datetime.utcnow()

    # amount: up to 40 pts ($1k -> 1pt, capped).
    try:
        amount = float(opp.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    amount_pts = max(0, min(round(amount / 1000.0), 40))

    stage = (opp.get("stage") or "new").lower()
    stage_pts = _STAGE_POINTS.get(stage, 5)

    # recency: days since last touch.
    days_idle = None
    if last_activity:
        days_idle = (now - last_activity).days
        recency_pts = 15 if days_idle <= 7 else (5 if days_idle <= 30 else 0)
    else:
        recency_pts = 0

    linkage_pts = (5 if opp.get("account_id") else 0) + (5 if opp.get("contact_id") else 0)

    score = min(100, amount_pts + stage_pts + recency_pts + linkage_pts)

    # next-best-action
    if opp.get("status") and opp["status"] != "open":
        nba = "none"
    elif days_idle is None or days_idle > 14:
        nba = "follow_up"
    elif stage in ("new", "rfq"):
        nba = "qualify"
    elif stage == "qualified":
        nba = "send_proposal"
    elif stage == "proposal":
        nba = "follow_up_on_proposal"
    elif stage == "negotiation":
        nba = "push_to_close"
    else:
        nba = "advance"

    return {
        "score": int(score),
        "next_best_action": nba,
        "factors": {
            "amount_pts": amount_pts, "stage_pts": stage_pts,
            "recency_pts": recency_pts, "linkage_pts": linkage_pts,
            "days_idle": days_idle,
        },
    }


def _last_activity(opp_id: str, opp: Dict[str, Any]) -> Optional[datetime]:
    act = crm_service._col("activities").find_one({"opportunity_id": opp_id}, sort=[("created_at", -1)])
    if act and act.get("created_at"):
        return act["created_at"]
    return opp.get("updated_at") or opp.get("created_at")


def run(limit: Optional[int] = None, dry_run: bool = False, top_n: int = 10) -> Dict[str, Any]:
    """Score open opportunities, write scores back, log a summary decision."""
    now = datetime.utcnow()
    cursor = crm_service._col("opportunities").find({"status": "open"})
    if limit:
        cursor = cursor.limit(limit)

    ranked = []
    stats = {"agent": AGENT_NAME, "dry_run": dry_run, "scanned": 0, "scored": 0,
             "decision_id": None, "errors": 0}

    for opp in cursor:
        stats["scanned"] += 1
        opp_id = str(opp["_id"])
        try:
            result = score_opportunity(opp, _last_activity(opp_id, opp), now)
            ranked.append({
                "opportunity_id": opp_id,
                "title": opp.get("title") or opp_id,
                "score": result["score"],
                "next_best_action": result["next_best_action"],
            })
            if not dry_run:
                crm_service.update("opportunities", opp_id, {
                    "score": result["score"],
                    "next_best_action": result["next_best_action"],
                    "score_factors": result["factors"],
                })
            stats["scored"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  ⚠️ error on opportunity_id={opp_id}: {e}")

    ranked.sort(key=lambda x: x["score"], reverse=True)
    stats["top"] = ranked[:top_n]

    if ranked and not dry_run:
        out = ai_engine.submit_decision(
            AGENT_NAME,
            decision=f"Scored {len(ranked)} open opportunities",
            reason="Heuristic score from amount, stage, activity recency, and linkage.",
            autonomy_mode="observe",
            risk="low",
            input_summary={"top": ranked[:top_n]},
        )
        stats["decision_id"] = out["decision"]["_id"]

    return stats


def main():
    parser = argparse.ArgumentParser(description="Score open opportunities + next-best-action.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true", help="Write scores (default is dry-run).")
    args = parser.parse_args()

    stats = run(limit=args.limit, dry_run=not args.execute)
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Opportunity scoring [{mode}] ===")
    print(f"  scanned: {stats['scanned']}  scored: {stats['scored']}  errors: {stats['errors']}")
    for r in stats.get("top", []):
        print(f"  [{r['score']:3d}] {r['title']}  -> {r['next_best_action']}")


if __name__ == "__main__":
    main()
