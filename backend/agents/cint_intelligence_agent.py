"""
CINT INTELLIGENCE AGENT (buyer performance scoring)

Deterministic, zero-AI/model scoring of Cint buyer (account_name) performance
from real, already-collected fields in cint_research.cint_surveys (157,023
documents as of 2026-09-17). Built the same way panel_intelligence_agent.py's
assess_panelist()/compute_engagement() were: a pure function over real fields,
no invented formula.

Real evidence behind this (live aggregation, 2026-09-17):
  - avg_conversion varies genuinely across named buyers: from 0.0037
    (OpinionSpark LLC) to 6.65 (Lucid Marketplace Services), with most
    buyers clustered well under 0.1 and a distinct smaller group above 1.5 --
    a real, natural gap, not an arbitrary line.
  - deactivation rate (deactivated surveys / total surveys) varies just as
    genuinely: SAGO has 13,577 of 16,925 surveys deactivated (80%), Kantar -
    CEX has 1,045 of 2,475 (42%).
  - `source_api` is 99%+ a single value (fulcrum_offerwall) across the whole
    collection -- not a useful axis to segment by today.
  - `deactivation_reason` is populated for only 12,942 of 75,222 inactive
    surveys (17%) and has exactly one distinct value observed
    ("not_on_offerwall") -- not rich enough yet to build a reason-level
    breakdown; noted as a real data-completeness gap, not built around.

Deliberately does NOT combine conversion and deactivation rate into one
weighted numeric score -- picking a weighting between them would be
inventing a business-policy judgment about which matters more, not reading
one from the data. Instead this returns a tier from the plain combination of
two independently-thresholded real signals, and callers can look at the two
raw numbers (`avg_conversion`, `deactivation_rate`) directly rather than
trust a single opaque score.

2026-09-17, cycle 8: wired into a live run(), mirroring panel_intelligence_
agent.py's exact pattern -- one aggregation query (not per-buyer queries),
underperforming buyers routed through ai_engine.submit_decision() in
recommend mode at risk="low" (informational review, no autonomous action --
no Cint API calls, no allocation changes). MIN_SURVEYS_FOR_SCORING guards
against flagging a buyer off a statistically meaningless sample size; the
pure scorer itself has no such floor (unchanged from cycle 6), the floor is
applied only at the orchestration layer before a flag is raised.
"""

import argparse
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services import crm_service, ai_engine
from database import get_database

AGENT_NAME = "cint_intelligence_agent"
MIRROR_COLLECTION = "cint_buyer_mirror"
# Below this, a 100% deactivation rate could just mean 2 unlucky surveys --
# not a statistically meaningful signal yet.
MIN_SURVEYS_FOR_SCORING = 10

# Real data shows a natural gap here (see module docstring) -- not a round
# number picked without basis.
HIGH_CONVERSION_THRESHOLD = 1.0     # percent; most buyers cluster well under 0.1
HIGH_DEACTIVATION_RATE = 0.5        # majority of this buyer's surveys got deactivated


def score_buyer_performance(
    surveys: int,
    avg_conversion: float,
    deactivated: int,
) -> Dict[str, Any]:
    """
    Pure. No I/O. Classifies a Cint buyer's (account_name) aggregate real
    performance into a descriptive tier.

    Tiers:
      - "no_data"        -- zero surveys on record
      - "strong"         -- conversion above threshold, deactivation rate not high
      - "underperforming" -- deactivation rate high, conversion not above threshold
      - "mixed"          -- both signals present (real conversion track record
                             AND a high deactivation rate) -- genuinely
                             ambiguous, not confidently good or bad
      - "average"        -- neither signal crosses its threshold
    """
    if surveys <= 0:
        return {"tier": "no_data", "deactivation_rate": None,
                "avg_conversion": avg_conversion}

    deactivation_rate = deactivated / surveys
    high_conversion = avg_conversion >= HIGH_CONVERSION_THRESHOLD
    high_deactivation = deactivation_rate >= HIGH_DEACTIVATION_RATE

    if high_conversion and high_deactivation:
        tier = "mixed"
    elif high_conversion:
        tier = "strong"
    elif high_deactivation:
        tier = "underperforming"
    else:
        tier = "average"

    return {
        "tier": tier,
        "deactivation_rate": round(deactivation_rate, 3),
        "avg_conversion": avg_conversion,
    }


def _mirror_col():
    return crm_service._db()[MIRROR_COLLECTION]


def _buyer_aggregates(
    source_db: str, source_collection: str, limit: Optional[int]
) -> List[Dict[str, Any]]:
    """
    One aggregation query for real per-buyer stats -- not a query per buyer.
    Returns rows sorted by survey volume (largest buyers first), matching
    how the real data was originally explored.
    """
    coll = get_database(source_db)[source_collection]
    pipeline: List[Dict[str, Any]] = [
        {"$match": {"account_name": {"$ne": None}}},
        {"$group": {
            "_id": "$account_name",
            "surveys": {"$sum": 1},
            "avg_conversion": {"$avg": "$conversion"},
            "deactivated": {"$sum": {"$cond": [{"$eq": ["$is_active", False]}, 1, 0]}},
        }},
        {"$sort": {"surveys": -1}},
    ]
    if limit:
        pipeline.append({"$limit": limit})
    return list(coll.aggregate(pipeline))


def run(
    autonomy_mode: str = "recommend",
    source_db: str = "cint_research",
    source_collection: str = "cint_surveys",
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Score real Cint buyer performance and flag underperformers. Returns stats."""
    stats = {
        "agent": AGENT_NAME, "mode": autonomy_mode, "dry_run": dry_run,
        "scanned": 0, "mirrored": 0, "flagged": 0, "errors": 0,
    }

    buyers = _buyer_aggregates(source_db, source_collection, limit)

    for b in buyers:
        account_name = b["_id"]
        stats["scanned"] += 1
        try:
            assessment = score_buyer_performance(
                surveys=b["surveys"],
                avg_conversion=b.get("avg_conversion") or 0.0,
                deactivated=b["deactivated"],
            )

            if not dry_run:
                _mirror_col().update_one(
                    {"account_name": account_name},
                    {"$set": {
                        "account_name": account_name,
                        "surveys": b["surveys"],
                        "tier": assessment["tier"],
                        "avg_conversion": assessment["avg_conversion"],
                        "deactivation_rate": assessment["deactivation_rate"],
                        "source": f"{source_db}.{source_collection}",
                        "last_synced": datetime.utcnow(),
                    }},
                    upsert=True,
                )
            stats["mirrored"] += 1

            if (assessment["tier"] == "underperforming"
                    and b["surveys"] >= MIN_SURVEYS_FOR_SCORING and not dry_run):
                deactivation_pct = (assessment["deactivation_rate"] or 0) * 100
                ai_engine.submit_decision(
                    AGENT_NAME,
                    decision=(
                        f"Cint buyer '{account_name}' underperforming: "
                        f"{deactivation_pct:.0f}% deactivation rate over "
                        f"{b['surveys']} surveys, avg conversion "
                        f"{assessment['avg_conversion']:.3f}"
                    ),
                    recommended_action=f"Review Cint buyer '{account_name}' relationship/traffic quality",
                    confidence=0.6,
                    reason="Deterministic performance scoring on aggregated Cint survey history.",
                    autonomy_mode=autonomy_mode,
                    risk="low",
                    linked_object_type="cint_buyer",
                    linked_object_id=account_name,
                    input_summary={
                        "account_name": account_name,
                        "surveys": b["surveys"],
                        "avg_conversion": assessment["avg_conversion"],
                        "deactivation_rate": assessment["deactivation_rate"],
                    },
                )
                stats["flagged"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  ⚠️ error on buyer={account_name}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Score real Cint buyer performance and flag underperformers.")
    parser.add_argument("--mode", default="recommend",
                        choices=["observe", "recommend", "approve", "autopilot"])
    parser.add_argument("--source-db", default="cint_research")
    parser.add_argument("--source-collection", default="cint_surveys")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true", help="Write changes (default is dry-run).")
    args = parser.parse_args()

    stats = run(
        autonomy_mode=args.mode, source_db=args.source_db,
        source_collection=args.source_collection, limit=args.limit,
        dry_run=not args.execute,
    )
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Cint intelligence [{mode}] ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
