"""
BOUNCE-RATE CIRCUIT BREAKER
===========================

Pauses an entity's campaign automatically when its rolling hard-bounce rate
crosses a threshold, and alerts.

WHY A BREAKER AND NOT A DASHBOARD
---------------------------------
Domain reputation is the one resource in this pipeline that cannot be bought
back. Hard bounce rates above ~2% trigger throttling at the major providers,
and by the time a human reads a dashboard and decides, the damage is done and
compounding. The 45% bounce episode from alt-format guessing is the precedent:
the signal existed the whole time, and nothing acted on it.

So this ACTS, then tells you. Pausing is reversible in one command; a burned
sending domain is not.

FAILS CLOSED, DELIBERATELY
--------------------------
If bounce data cannot be read, the breaker treats the entity as unhealthy
rather than assuming it is fine. An unreadable bounce rate is the same
epistemic state as a bad one — you do not know it is safe to send.

MEASURED PER ENTITY AND PER SENDING DOMAIN
------------------------------------------
Per entity because pausing is per entity. Per domain because reputation
attaches to the domain, and while the three brands share one sending identity
a single entity's bounces are damaging all three — which is itself worth
seeing before domains are separated.

MINIMUM SAMPLE
--------------
A rate computed over a handful of sends is noise. Below MIN_SAMPLE the breaker
reports 'insufficient_data' and does not trip — one bounce in three sends is
33% and means nothing.

Usage:
    python -m leads.bounce_circuit_breaker              # report only
    python -m leads.bounce_circuit_breaker --enforce    # pause tripped entities
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
LEADS_DB = os.getenv("MONGO_DB_NAME_LEADS", "email_automation")
TORPEDO_DB = os.getenv("MONGO_DB_NAME", "torpedo")

# Providers throttle around 2%. Default sits at the line, not past it.
BOUNCE_RATE_THRESHOLD = float(os.getenv("BOUNCE_RATE_THRESHOLD", "0.02"))
# Rolling window for the rate.
BOUNCE_WINDOW_DAYS = int(os.getenv("BOUNCE_WINDOW_DAYS", "7"))
# Below this many sends a rate is noise, not signal.
MIN_SAMPLE = int(os.getenv("BOUNCE_MIN_SAMPLE", "50"))

ENTITIES = ("SFW", "COGENTIX_RESEARCH", "BIM")


@dataclass
class EntityBounceState:
    entity: str
    sends: int = 0
    hard_bounces: int = 0
    rate: Optional[float] = None
    status: str = "unknown"          # ok | tripped | insufficient_data | unreadable
    sending_domain: Optional[str] = None
    detail: str = ""

    @property
    def should_pause(self) -> bool:
        # 'unreadable' trips too — see module docstring on failing closed.
        return self.status in ("tripped", "unreadable")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity": self.entity,
            "sends": self.sends,
            "hard_bounces": self.hard_bounces,
            "rate": self.rate,
            "status": self.status,
            "sending_domain": self.sending_domain,
            "should_pause": self.should_pause,
            "detail": self.detail,
        }


@dataclass
class BreakerReport:
    checked_at: str = ""
    window_days: int = BOUNCE_WINDOW_DAYS
    threshold: float = BOUNCE_RATE_THRESHOLD
    entities: List[EntityBounceState] = field(default_factory=list)
    paused: List[str] = field(default_factory=list)
    shared_domain_warning: Optional[str] = None

    @property
    def healthy(self) -> bool:
        return not any(e.should_pause for e in self.entities)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "checked_at": self.checked_at,
            "window_days": self.window_days,
            "threshold": self.threshold,
            "entities": [e.to_dict() for e in self.entities],
            "paused": self.paused,
            "shared_domain_warning": self.shared_domain_warning,
        }


def _sending_domain(address: Optional[str]) -> Optional[str]:
    if not address or "@" not in address:
        return None
    return address.rsplit("@", 1)[1].strip().lower()


def measure(db, entity: str, window_days: int = None) -> EntityBounceState:
    """Rolling hard-bounce rate for one entity. Never writes."""
    window_days = window_days or BOUNCE_WINDOW_DAYS
    since = datetime.utcnow() - timedelta(days=window_days)
    state = EntityBounceState(entity=entity)

    try:
        state.sends = db["sends"].count_documents(
            {"entity": entity, "sent_at": {"$gte": since}})
        state.hard_bounces = db["sends"].count_documents(
            {"entity": entity, "sent_at": {"$gte": since},
             "status": {"$in": ["bounced", "hard_bounce", "bounce"]}})
    except Exception as exc:
        state.status = "unreadable"
        state.detail = (f"bounce data unreadable ({exc}); failing closed — an "
                        f"unreadable rate is the same epistemic state as a bad one")
        return state

    if state.sends < MIN_SAMPLE:
        state.status = "insufficient_data"
        state.detail = (f"{state.sends} sends in {window_days}d is below the "
                        f"{MIN_SAMPLE} minimum; a rate here would be noise")
        return state

    state.rate = round(state.hard_bounces / state.sends, 4)
    if state.rate >= BOUNCE_RATE_THRESHOLD:
        state.status = "tripped"
        state.detail = (f"hard-bounce rate {state.rate:.2%} >= "
                        f"{BOUNCE_RATE_THRESHOLD:.2%} over {window_days}d")
    else:
        state.status = "ok"
        state.detail = f"hard-bounce rate {state.rate:.2%}"
    return state


def pause_entity(torpedo_db, entity: str, reason: str) -> int:
    """
    Set is_active=False on the entity's active campaigns. Returns rows changed.

    NOTE: pausing a campaign does not drain sends already enqueued by
    scheduler.enqueue_send(). The caller must drain the queue as well — see
    the rollout plan. This function does not do it, because clearing a queue is
    a destructive action that should be explicit rather than a side effect of a
    health check.
    """
    business = {"SFW": "sfw", "COGENTIX_RESEARCH": "cogentix", "BIM": "bimwave"}.get(entity)
    if not business:
        return 0
    res = torpedo_db["outreach_campaigns_v2"].update_many(
        {"business": business, "is_active": True},
        {"$set": {"is_active": False,
                  "paused_reason": f"bounce_circuit_breaker: {reason}",
                  "paused_at": datetime.utcnow()}},
    )
    return res.modified_count


def check(client: MongoClient = None, enforce: bool = False) -> BreakerReport:
    client = client or MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[LEADS_DB]
    torpedo = client[TORPEDO_DB]

    rep = BreakerReport(checked_at=datetime.utcnow().isoformat())
    for entity in ENTITIES:
        state = measure(db, entity)
        state.sending_domain = _sending_domain(os.getenv("OUTREACH_SENDER_EMAIL"))
        rep.entities.append(state)

        if enforce and state.should_pause:
            try:
                changed = pause_entity(torpedo, entity, state.detail)
                if changed:
                    rep.paused.append(entity)
                    logger.error("PAUSED %s: %s", entity, state.detail)
            except Exception as exc:
                logger.error("failed to pause %s: %s", entity, exc)

    # While all three brands share one sending identity, one entity's bounces
    # damage the other two. Worth surfacing every run until domains are split.
    domains = {e.sending_domain for e in rep.entities if e.sending_domain}
    if len(domains) == 1 and len(rep.entities) > 1:
        rep.shared_domain_warning = (
            f"all {len(rep.entities)} entities send from {domains.pop()}. "
            f"Reputation is pooled: one entity's bounces damage all three, and "
            f"a per-entity breaker cannot isolate the damage until sending "
            f"domains are separated (with a warm-up plan).")
    return rep


def render(rep: BreakerReport) -> str:
    lines = ["", "=" * 68,
             f"  BOUNCE CIRCUIT BREAKER — {'OK' if rep.healthy else 'TRIPPED'}",
             "=" * 68,
             f"  threshold {rep.threshold:.2%} over {rep.window_days}d, "
             f"min sample {MIN_SAMPLE}", ""]
    for e in rep.entities:
        rate = f"{e.rate:.2%}" if e.rate is not None else "n/a"
        lines.append(f"  {e.entity:<20} {e.sends:>6} sends  {e.hard_bounces:>4} bounced  "
                     f"{rate:>7}  [{e.status}]")
        if e.detail:
            lines.append(f"      {e.detail}")
    if rep.paused:
        lines += ["", f"  PAUSED: {', '.join(rep.paused)}",
                  "  NOTE: already-enqueued sends are NOT drained by this tool."]
    if rep.shared_domain_warning:
        lines += ["", f"  WARNING: {rep.shared_domain_warning}"]
    lines += ["", "=" * 68, ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--enforce", action="store_true",
                    help="actually pause tripped entities (default: report only)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rep = check(enforce=args.enforce)
    print(json.dumps(rep.to_dict(), indent=2, default=str) if args.json else render(rep))
    return 0 if rep.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
