"""
SURVEY REVENUE AGENT  (Phase 5 — expected-revenue scoring & best-survey selection)

Ranks active surveys by EXPECTED REVENUE PER ENTRANT and surfaces the best one
as a recommendation through the AI decision engine.

Expected revenue per entrant (EPC) = cpi * P(complete), where P(complete) is, in
order of preference:
  1. actual conversion_rate (from survey_metrics), else
  2. the provider's expected incidence rate (ir), else
  3. a conservative default.

Reads survey inventory from the survey_allocation DB (surveys + survey_metrics).
The scoring math is a pure function (expected_revenue_score) so it is fully
unit-testable without any DB.

Usage:
    python -m backend.agents.survey_revenue_agent --dry-run
    python -m backend.agents.survey_revenue_agent --mode recommend --execute
"""

import argparse
from typing import Optional, Dict, Any, List

try:
    from ..app.services import ai_engine
    from ..database import get_database
except ImportError:  # pragma: no cover - absolute import / CLI fallback
    from app.services import ai_engine
    from database import get_database

AGENT_NAME = "survey_revenue_agent"
DEFAULT_P_COMPLETE = 0.30  # conservative fallback when no rate data exists


def expected_revenue_score(survey: Dict[str, Any], metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Pure scorer: expected revenue per entrant for one survey. No I/O."""
    try:
        cpi = float(survey.get("cpi") or 0)
    except (TypeError, ValueError):
        cpi = 0.0

    conv = None
    if metrics:
        conv = metrics.get("conversion_rate")
    if conv is None:
        conv = survey.get("conversion_rate")

    if conv is not None and float(conv) > 0:
        p = float(conv) / 100.0
        basis = "conversion_rate"
    elif survey.get("ir") is not None and float(survey.get("ir")) > 0:
        p = float(survey["ir"]) / 100.0
        basis = "expected_ir"
    else:
        p = DEFAULT_P_COMPLETE
        basis = "default"

    p = max(0.0, min(p, 1.0))
    return {"epc": round(cpi * p, 4), "cpi": cpi, "p_complete": round(p, 4), "basis": basis}


def rank_surveys(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rank a list of {"survey": doc, "metrics": doc|None} by expected revenue per
    entrant (desc), tie-breaking on remaining_quota (more capacity first).
    """
    ranked = []
    for it in items:
        survey = it["survey"]
        score = expected_revenue_score(survey, it.get("metrics"))
        sid = survey.get("survey_id") or str(survey.get("_id"))
        ranked.append({
            "survey_id": sid,
            "name": survey.get("name") or survey.get("survey_name") or sid,
            "remaining_quota": survey.get("remaining_quota"),
            **score,
        })
    ranked.sort(key=lambda x: (x["epc"], x.get("remaining_quota") or 0), reverse=True)
    return ranked


def run(
    autonomy_mode: str = "recommend",
    source_db: str = "survey_allocation",
    surveys_collection: str = "surveys",
    metrics_collection: str = "survey_metrics",
    only_active: bool = True,
    limit: Optional[int] = None,
    top_n: int = 5,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Rank active surveys by expected revenue and recommend the best. Returns stats."""
    db = get_database(source_db)
    query = {"status": "active"} if only_active else {}
    cursor = db[surveys_collection].find(query)
    if limit:
        cursor = cursor.limit(limit)

    metrics_col = db[metrics_collection]
    items = []
    for s in cursor:
        sid = s.get("survey_id") or str(s.get("_id"))
        m = metrics_col.find_one({"survey_id": sid}) if sid else None
        items.append({"survey": s, "metrics": m})

    ranked = rank_surveys(items)
    stats = {
        "agent": AGENT_NAME,
        "mode": autonomy_mode,
        "dry_run": dry_run,
        "scanned": len(ranked),
        "top": ranked[:top_n],
        "best": ranked[0] if ranked else None,
        "decision_id": None,
    }

    if not ranked or dry_run:
        return stats

    best = ranked[0]
    out = ai_engine.submit_decision(
        AGENT_NAME,
        decision=f"Best survey by expected revenue: {best['name']} (${best['epc']}/entrant)",
        recommended_action=f"Prioritize survey {best['name']} "
        f"(expected ${best['epc']}/entrant, basis={best['basis']})",
        confidence=0.6 if best["basis"] != "default" else 0.3,
        reason=f"Ranked {len(ranked)} active surveys by expected revenue per entrant "
        f"(cpi x P(complete)).",
        autonomy_mode=autonomy_mode,
        risk="low",
        linked_object_type="survey",
        linked_object_id=best["survey_id"],
        input_summary={"top": ranked[:top_n]},
    )
    stats["decision_id"] = out["decision"]["_id"]
    return stats


def main():
    parser = argparse.ArgumentParser(description="Rank surveys by expected revenue per entrant.")
    parser.add_argument("--mode", default="recommend", choices=["observe", "recommend", "approve", "autopilot"])
    parser.add_argument("--source-db", default="survey_allocation")
    parser.add_argument("--all", action="store_true", help="Include non-active surveys.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true", help="Log a recommendation (default is dry-run).")
    args = parser.parse_args()

    stats = run(
        autonomy_mode=args.mode,
        source_db=args.source_db,
        only_active=not args.all,
        limit=args.limit,
        dry_run=not args.execute,
    )
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Survey revenue agent [{mode}] ===")
    print(f"  scanned: {stats['scanned']}")
    for i, row in enumerate(stats["top"], 1):
        print(f"  #{i} {row['name']}: ${row['epc']}/entrant (cpi=${row['cpi']}, p={row['p_complete']}, {row['basis']})")
    if stats["decision_id"]:
        print(f"  decision_id: {stats['decision_id']}")


if __name__ == "__main__":
    main()
