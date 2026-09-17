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
    python -m backend.agents.panel_intelligence_agent            # dry-run is the default (no --execute)
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
# rewards_balance added 2026-09-17 -- confirmed (via a 200-doc field-union
# query against the real campaign_platform.panelists collection) to be the
# actual field name in production; none of the original synonyms below
# appear anywhere in the real schema, so without this the rewards check
# always read 0 regardless of a panelist's actual balance.
_REWARDS_KEYS = ["rewards_balance", "rewards_total", "reward_total", "points",
                 "rewards", "total_rewards"]
_STATUS_KEYS = ["status", "state", "panelStatus"]
# Real distinct status values in production (campaign_platform.panelists):
# active, bounced, confirmed, dnd. None of "flagged"/"suspicious"/"fraud"/
# "banned" below have ever been observed there -- kept for a source that
# might use them, but they cannot be assumed to mean anything for the real
# collection this agent's own defaults point at.
_INACTIVE_STATUSES = ("bounced", "dnd")


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


def _has_any_key(doc: Dict[str, Any], keys: List[str]) -> bool:
    return any(k in doc for k in keys)


def assess_panelist(panelist: Dict[str, Any]) -> Dict[str, Any]:
    """Pure fraud/anomaly heuristic. Returns {risk: low|high, reasons: [...]}. No I/O.

    The rewards-vs-completions checks below only fire when the document
    actually carries a survey-completion field. The real production
    `panelists` collection this agent defaults to has NO completion-count
    field at all (confirmed 2026-09-17) -- treating an absent field as "0
    completions" would flag every panelist with any reward balance as
    suspicious, which is a false-positive on missing data, not a real signal.
    """
    has_completion_data = _has_any_key(panelist, _SURVEYS_KEYS)
    surveys = _num(_first(panelist, _SURVEYS_KEYS, 0))
    rewards = _num(_first(panelist, _REWARDS_KEYS, 0))
    status = (_first(panelist, _STATUS_KEYS, "") or "").lower()

    reasons: List[str] = []
    if has_completion_data:
        if rewards > 0 and surveys == 0:
            reasons.append("rewards_without_completions")
        if rewards >= HIGH_REWARD_FLOOR and surveys > 0 and (rewards / surveys) > REWARD_PER_SURVEY_LIMIT:
            reasons.append("reward_per_survey_too_high")
    if status in ("flagged", "suspicious", "fraud", "banned"):
        reasons.append(f"status_{status}")
    # Real, inferable signal given the actual schema: a reward balance
    # sitting on an account marked bounced/dnd (do-not-disturb) is anomalous
    # under any reasonable reading, regardless of whether completion data
    # exists at all.
    if rewards > 0 and status in _INACTIVE_STATUSES:
        reasons.append(f"rewards_on_inactive_status:{status}")

    return {"risk": "high" if reasons else "low", "reasons": reasons}


# ------------------------------------------------------------------
# Invitation engagement / fatigue scoring
# ------------------------------------------------------------------
#
# Added 2026-09-17 after a real aggregation query against the production
# panel_invitation_log (3.46M documents): sampled panelists show a real
# pattern of 45 invitations sent, 0 ever confirmed, spanning ~3 months
# (roughly one invite every 2 days with zero engagement the entire time).
# Across a 50K-document sample of the whole collection, only 0.5% of all
# invitation-log entries ever reach "confirmed" -- this is a real,
# measurable pattern, not a hypothesis. Deterministic (no AI/model call) --
# the master-prompt PANEL section's "fatigue/inactivity detection" item,
# built the same way opportunity_scoring_agent.py's pure point-scorer is:
# a plain function over real, already-existing fields.
#
# Pure, no I/O -- callers are responsible for aggregating the real counts
# from panel_invitation_log (e.g. via the $group pipeline used to discover
# this pattern) and passing them in, exactly like assess_panelist() takes a
# plain dict rather than querying anything itself.

FATIGUE_INVITE_FLOOR = 10   # below this, "never confirmed" isn't yet meaningful
STALE_NO_RESPONSE_DAYS = 30  # only worth flagging once enough time has passed


def compute_engagement(
    invites_sent: int,
    invites_confirmed: int,
    days_since_last_invite: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Classify a panelist's invitation engagement from real invitation-log
    counts. Returns {tier, confirm_rate, reasons}.

    Tiers:
      - "never_invited"  -- no invitations on record at all
      - "engaged"         -- has at least one confirmation
      - "fatigued"        -- enough invitations sent, zero confirmations,
                              and (when known) not recently sent -- a real
                              candidate for reduced frequency or suppression
      - "unresponsive"    -- some invitations sent, zero confirmations, but
                              below the volume/age threshold to call it
                              "fatigue" yet
    """
    if invites_sent <= 0:
        return {"tier": "never_invited", "confirm_rate": 0.0, "reasons": []}

    confirm_rate = invites_confirmed / invites_sent

    if invites_confirmed > 0:
        return {"tier": "engaged", "confirm_rate": round(confirm_rate, 3), "reasons": []}

    reasons: List[str] = []
    if invites_sent >= FATIGUE_INVITE_FLOOR:
        reasons.append(f"never_confirmed_after_{invites_sent}_invites")
    if days_since_last_invite is not None and days_since_last_invite >= STALE_NO_RESPONSE_DAYS \
            and invites_sent >= FATIGUE_INVITE_FLOOR:
        reasons.append(f"no_response_in_{days_since_last_invite}_days")

    tier = "fatigued" if reasons else "unresponsive"
    return {"tier": tier, "confirm_rate": round(confirm_rate, 3), "reasons": reasons}


def _mirror_col():
    return crm_service._db()[MIRROR_COLLECTION]


def run(
    autonomy_mode: str = "recommend",
    # Corrected 2026-09-17: "panel" is empty in production -- the real
    # panelist collection (224K+ documents) lives in campaign_platform,
    # confirmed by direct query. The original default meant this agent, if
    # ever run with no args exactly as its own module docstring's usage
    # example shows, would scan zero panelists.
    source_db: str = "campaign_platform",
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
    parser.add_argument("--source-db", default="campaign_platform")
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
