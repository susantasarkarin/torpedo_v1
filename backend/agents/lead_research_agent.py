"""
LEAD RESEARCH AGENT  (Phase 5 — automated lead enrichment)

Finds canonical leads (default `crm_db.leads`) that are missing key fields
(title / phone / company), enriches them via a pluggable provider, and routes
each enrichment as an APPROVAL-GATED `update_record` decision through the AI
decision engine. Nothing is written to a lead until a human approves (approve
mode) — enrichment is low-risk but still reviewed by default.

Enrichment provider:
  - default `_apollo_enrich` calls the Apollo REST API (people/match) when
    APOLLO_API_KEY is set; returns None (graceful skip) when there's no key,
    no email, no match, or an API error.
  - the provider is injectable (`enricher=`) so tests run fully offline.
  NOTE: the backend cannot use the assistant's Apollo *MCP* tools — those are
  not available in-process — hence the REST provider behind an API key.

De-spam: a lead enriched (decided on) by this agent within `cooldown_days`
(default 30) is skipped, tracked via logged ai_decisions input_summary.lead_id.

Usage:
    python -m backend.agents.lead_research_agent --dry-run
    APOLLO_API_KEY=... python -m backend.agents.lead_research_agent --mode approve --execute --limit 50
"""

import os
import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable

from app.services import crm_service, ai_engine

AGENT_NAME = "lead_research_agent"
ENRICHABLE_FIELDS = ("title", "phone", "company")


def _apollo_enrich(lead: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Enrich a lead via Apollo people/match (needs APOLLO_API_KEY). None on miss."""
    key = os.getenv("APOLLO_API_KEY")
    email = lead.get("email")
    if not key or not email:
        return None
    try:
        import requests
        resp = requests.post(
            "https://api.apollo.io/api/v1/people/match",
            json={"email": email},
            headers={"X-Api-Key": key, "Content-Type": "application/json"},
            timeout=20,
        )
        if resp.status_code != 200:
            return None
        person = (resp.json() or {}).get("person") or {}
    except Exception:
        return None

    updates: Dict[str, Any] = {}
    if person.get("title"):
        updates["title"] = person["title"]
    phones = person.get("phone_numbers") or []
    if phones and phones[0].get("raw_number"):
        updates["phone"] = phones[0]["raw_number"]
    if person.get("organization", {}).get("name"):
        updates["company"] = person["organization"]["name"]
    if person.get("linkedin_url"):
        updates["linkedin"] = person["linkedin_url"]
    return updates or None


def _needs_enrichment(lead: Dict[str, Any]) -> bool:
    return any(not lead.get(f) for f in ENRICHABLE_FIELDS)


def _recently_enriched(cooldown_after: datetime) -> set:
    seen = set()
    for d in crm_service._col("ai_decisions").find(
        {"agent_name": AGENT_NAME, "created_at": {"$gte": cooldown_after}},
        {"input_summary.lead_id": 1},
    ):
        lid = (d.get("input_summary") or {}).get("lead_id")
        if lid:
            seen.add(lid)
    return seen


def run(
    autonomy_mode: str = "approve",
    source_collection: str = "leads",
    limit: Optional[int] = None,
    cooldown_days: int = 30,
    dry_run: bool = False,
    enricher: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Enrich leads missing key fields via approval-gated decisions. Returns stats."""
    enrich = enricher or _apollo_enrich
    cooldown_after = datetime.utcnow() - timedelta(days=cooldown_days)
    recently = _recently_enriched(cooldown_after)

    stats = {
        "agent": AGENT_NAME,
        "mode": autonomy_mode,
        "dry_run": dry_run,
        "scanned": 0,
        "candidates": 0,
        "skipped_recent": 0,
        "no_data": 0,
        "enriched": 0,
        "queued": 0,
        "executed": 0,
        "errors": 0,
    }

    # Leads missing at least one enrichable field.
    query = {"$or": [{f: {"$exists": False}} for f in ENRICHABLE_FIELDS]
             + [{f: {"$in": [None, ""]}} for f in ENRICHABLE_FIELDS]}
    cursor = crm_service._col(source_collection).find(query)
    if limit:
        cursor = cursor.limit(limit)

    for lead in cursor:
        stats["scanned"] += 1
        lead_id = str(lead["_id"])
        if not _needs_enrichment(lead):
            continue
        stats["candidates"] += 1
        if lead_id in recently:
            stats["skipped_recent"] += 1
            continue
        if dry_run:
            continue

        try:
            updates = enrich(lead)
            if not updates:
                stats["no_data"] += 1
                # Still log a decision so cooldown applies (avoid re-querying dead leads).
                ai_engine.submit_decision(
                    AGENT_NAME,
                    decision=f"No enrichment found for lead {lead.get('email') or lead_id}",
                    autonomy_mode="observe",
                    risk="low",
                    linked_object_type="lead",
                    linked_object_id=lead_id,
                    input_summary={"lead_id": lead_id, "result": "no_data"},
                )
                recently.add(lead_id)
                continue

            out = ai_engine.submit_decision(
                AGENT_NAME,
                decision=f"Enrich lead {lead.get('email') or lead_id}: {', '.join(updates.keys())}",
                recommended_action=f"Apply enrichment to lead: {', '.join(updates.keys())}",
                action_type="update_record",
                action_payload={"collection": source_collection, "id": lead_id, "updates": updates},
                confidence=0.7,
                reason=f"Provider returned {len(updates)} field(s): {', '.join(updates.keys())}",
                autonomy_mode=autonomy_mode,
                risk="low",
                linked_object_type="lead",
                linked_object_id=lead_id,
                input_summary={"lead_id": lead_id, "fields": list(updates.keys())},
            )
            stats["enriched"] += 1
            if out.get("queued"):
                stats["queued"] += 1
            if out.get("executed"):
                stats["executed"] += 1
            recently.add(lead_id)
        except Exception as e:  # one bad lead shouldn't abort the run
            stats["errors"] += 1
            print(f"  ⚠️ error on lead_id={lead_id}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Enrich leads missing key fields (Apollo).")
    parser.add_argument("--mode", default="approve", choices=["observe", "recommend", "approve", "autopilot"])
    parser.add_argument("--collection", default="leads")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--cooldown-days", type=int, default=30)
    parser.add_argument("--execute", action="store_true", help="Write changes (default is dry-run).")
    args = parser.parse_args()

    stats = run(
        autonomy_mode=args.mode,
        source_collection=args.collection,
        limit=args.limit,
        cooldown_days=args.cooldown_days,
        dry_run=not args.execute,
    )
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Lead research agent [{mode}] ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
