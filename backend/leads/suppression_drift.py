"""
SUPPRESSION DRIFT CHECK
=======================

Interim guard on the only finding in this remediation that is a live legal
exposure rather than a reputational or quality problem.

THE SPLIT-BRAIN
---------------
There are two suppression stores and they are not synced:

    email_automation.suppression_list          <- UNSUBSCRIBES are written here
        written by campaigns/suppression.py, leads/ses_notifications.py:83
        read by leads/outreach_qualification.py, which is NOT the live sender

    torpedo.outreach_bounce_suppression        <- the LIVE SENDER reads this
        read by outreach_engine/sending_engine.py:201
        written by the bounce path

So an unsubscribe lands in a store the sending path never consults.
Unsubscribes have not been honored. CAN-SPAM requires honoring an opt-out
within 10 business days.

WHY A CHECK AND NOT JUST A MERGE
--------------------------------
A one-way union clears the backlog and then re-diverges within a day, because
campaigns/suppression.py and ses_notifications.py keep writing new
unsubscribes to the orphaned store. Repointing those writers touches ~35 call
sites and is its own reviewable change; smuggling it into a hotfix is how you
get a second incident on top of the first. So the honest interim is: merge,
sync continuously, and FAIL LOUDLY on drift.

BIDIRECTIONAL BY DESIGN
-----------------------
Checks divergence in BOTH directions. A one-directional check that only looks
for "missing from outreach_bounce_suppression" would report healthy if
something ever wrote a suppression the other store lacked — equally a bug, and
invisible to the check meant to catch exactly this class of problem.

TWO INVOCATIONS, ONE IMPLEMENTATION
-----------------------------------
    python -m leads.suppression_drift            # one-shot, exit 1 on drift
    python -m leads.suppression_drift --json     # for the scheduler/alerting

Run it BEFORE the merge for a clean before-picture, and again after, where it
must return zero drift. Same code both times — a verification you only run
after the fact cannot tell you what the fix changed.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Set

from pymongo import MongoClient

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
LEADS_DB = os.getenv("MONGO_DB_NAME_LEADS", "email_automation")
TORPEDO_DB = os.getenv("MONGO_DB_NAME", "torpedo")

# The store unsubscribes are written to, and which the live sender ignores.
UNSUB_STORE = (LEADS_DB, "suppression_list")
# The store the live sender actually consults before every send.
SENDER_STORE = (TORPEDO_DB, "outreach_bounce_suppression")


def _norm(email: Any) -> str:
    return (email or "").strip().lower()


def _addresses(db, collection: str) -> Set[str]:
    return {
        _norm(d.get("email"))
        for d in db[collection].find({}, {"email": 1})
        if _norm(d.get("email"))
    }


@dataclass
class DriftReport:
    unsub_store_count: int = 0
    sender_store_count: int = 0
    # Suppressed per the unsubscribe store, invisible to the sender.
    # THE DANGEROUS DIRECTION: these people can still be emailed.
    missing_from_sender: List[str] = field(default_factory=list)
    # Suppressed per the sender store, absent from the unsubscribe store.
    # Not a sending risk, but still drift, and a one-way check would miss it.
    missing_from_unsub: List[str] = field(default_factory=list)
    checked_at: str = ""

    @property
    def total_drift(self) -> int:
        return len(self.missing_from_sender) + len(self.missing_from_unsub)

    @property
    def healthy(self) -> bool:
        return self.total_drift == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "checked_at": self.checked_at,
            "unsub_store_count": self.unsub_store_count,
            "sender_store_count": self.sender_store_count,
            "total_drift": self.total_drift,
            "missing_from_sender_count": len(self.missing_from_sender),
            "missing_from_unsub_count": len(self.missing_from_unsub),
            "missing_from_sender_sample": self.missing_from_sender[:20],
            "missing_from_unsub_sample": self.missing_from_unsub[:20],
        }

    def render(self) -> str:
        lines = [
            "",
            "=" * 68,
            f"  SUPPRESSION DRIFT — {'HEALTHY' if self.healthy else 'DRIFT DETECTED'}",
            "=" * 68,
            f"  {UNSUB_STORE[0]}.{UNSUB_STORE[1]:<34} {self.unsub_store_count:>8}",
            f"  {SENDER_STORE[0]}.{SENDER_STORE[1]:<34} {self.sender_store_count:>8}",
            "",
            f"  suppressed but INVISIBLE TO THE SENDER   {len(self.missing_from_sender):>8}",
            "      ^ these addresses can still receive mail. This is the",
            "        CAN-SPAM exposure; every one is a person who opted out.",
            "",
            f"  in sender store, absent from unsub store {len(self.missing_from_unsub):>8}",
            "      ^ not a sending risk, but still drift. A one-directional",
            "        check would call this healthy.",
            "",
        ]
        if self.missing_from_sender:
            lines.append("  sample (invisible to sender):")
            for e in self.missing_from_sender[:10]:
                lines.append(f"    {e}")
            lines.append("")
        lines += ["=" * 68, ""]
        return "\n".join(lines)


def check_drift(client: MongoClient = None) -> DriftReport:
    """Compare both stores. Never writes."""
    client = client or MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    unsub = _addresses(client[UNSUB_STORE[0]], UNSUB_STORE[1])
    sender = _addresses(client[SENDER_STORE[0]], SENDER_STORE[1])

    return DriftReport(
        unsub_store_count=len(unsub),
        sender_store_count=len(sender),
        missing_from_sender=sorted(unsub - sender),
        missing_from_unsub=sorted(sender - unsub),
        checked_at=datetime.utcnow().isoformat(),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true",
                    help="machine-readable, for the scheduler and alerting")
    args = ap.parse_args()

    report = check_drift()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.render())

    # Non-zero exit on drift so this works as a pre-merge gate and as a
    # scheduled check without a wrapper deciding what "failure" means.
    return 0 if report.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
