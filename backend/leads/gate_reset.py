"""
RESET LEADS RETIRED BY A CONFIG PROBLEM THAT HAS SINCE BEEN FIXED
==================================================================

Before 2026-09-26's config-hold fix, a missing setting (e.g.
OUTREACH_SENDER_POSTAL_ADDRESS) PERMANENTLY retired a lead as
workflow_status="skipped_gate" / "skipped_high_bounce_risk" -- statuses the
send loop never selects. 369 Survey Fieldwork leads were retired this way on
2026-09-04. The config-hold fix stops this happening to FUTURE leads, but does
nothing for these existing 369: nobody moves a lead out of skipped_gate.

This module is the one-time, deliberate migration for that existing backlog.
It is intentionally NOT automatic -- a lead that was retired for a real,
still-true reason (unsendable domain, no MX, role account, already replied,
suppressed since) must stay retired, so every check that would apply at send
time is re-run here, live, before a lead is offered for reset.

Split as pure/impure on purpose: `evaluate_candidates` and `stage_batches` are
pure functions over already-fetched data and injected check callables --
fully unit-testable with fakes, no live Mongo or DNS. `select_reset_candidates`
and `apply_reset` are the thin wiring layer that builds real callables from
messaging.suppression / app.services.outreach.email_validator / lifetime send
history, and is only exercised for real on the VM.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

RETIRED_STATUSES = ("skipped_gate", "skipped_high_bounce_risk")

# A domain this risky, historically, is held back even though the address
# itself never bounced -- the same domain-level heuristic used in the
# 2026-09-20 audit. Both thresholds must be met: a handful of sends is not a
# reliable rate.
_MIN_DOMAIN_SENDS = 5
_MAX_DOMAIN_BOUNCE_RATE = 0.30


@dataclass
class Candidate:
    lead_id: Any
    email: str
    held_reason: Optional[str] = None   # None == clean, ready to reset

    @property
    def clean(self) -> bool:
        return self.held_reason is None


def _domain(email: str) -> str:
    return (email or "").rsplit("@", 1)[-1].lower()


def evaluate_candidates(
    leads: List[Dict[str, Any]],
    *,
    is_suppressed: Callable[[str], bool],
    is_legacy_bounced: Callable[[str], bool],
    has_own_bounced_send: Callable[[str], bool],
    has_own_reply: Callable[[str], bool],
    live_deliverability_ok: Callable[[str], Tuple[bool, str]],
    domain_lifetime_stats: Callable[[str], Tuple[int, int]],  # (sent, bounced)
) -> List[Candidate]:
    """
    Re-run every send-time check against each lead, live, and return a
    Candidate per lead with `held_reason` set to the FIRST check it fails, or
    None if it survives all of them. Checks run cheapest/most-decisive first so
    a lead already known bad doesn't pay for a live deliverability call.
    """
    out: List[Candidate] = []
    for lead in leads:
        email = (lead.get("email") or "").strip().lower()
        lead_id = lead.get("_id")
        if not email or "@" not in email:
            out.append(Candidate(lead_id, email, "invalid or missing email"))
            continue
        if is_suppressed(email):
            out.append(Candidate(lead_id, email, "on the unified suppression list"))
            continue
        if is_legacy_bounced(email):
            out.append(Candidate(lead_id, email, "on the legacy bounce-suppression list"))
            continue
        if has_own_bounced_send(email):
            out.append(Candidate(lead_id, email, "this address has bounced before"))
            continue
        if has_own_reply(email):
            out.append(Candidate(lead_id, email, "this address already replied -- must not be re-mailed"))
            continue
        ok, reason = live_deliverability_ok(email)
        if not ok:
            out.append(Candidate(lead_id, email, f"deliverability check failed: {reason}"))
            continue
        sent, bounced = domain_lifetime_stats(_domain(email))
        if sent >= _MIN_DOMAIN_SENDS and bounced / sent >= _MAX_DOMAIN_BOUNCE_RATE:
            out.append(Candidate(lead_id, email,
                                 f"domain has a {bounced}/{sent} = {bounced/sent:.0%} lifetime bounce rate"))
            continue
        out.append(Candidate(lead_id, email, None))
    return out


def stage_batches(
    clean: List[Candidate], *, daily_cap: int, start: Optional[datetime] = None,
) -> List[Tuple[Candidate, datetime]]:
    """
    Split the clean candidates into batches of `daily_cap`, one batch per day,
    starting at `start` (default: now). Order is stable (input order preserved)
    so a re-run with the same candidate list produces the same schedule.
    Returns [(candidate, next_send_at), ...].
    """
    if daily_cap <= 0:
        raise ValueError("daily_cap must be positive")
    start = start or datetime.utcnow()
    staged = []
    for i, cand in enumerate(clean):
        day_offset = i // daily_cap
        staged.append((cand, start + timedelta(days=day_offset)))
    return staged


# ---------------------------------------------------------------- wiring

def select_reset_candidates(db, campaign_id: str,
                            statuses: Tuple[str, ...] = RETIRED_STATUSES) -> List[Candidate]:
    """Fetch retired leads for one campaign and evaluate them live. Read-only."""
    from app.services.outreach.email_validator import EmailValidator
    from messaging import suppression as _suppression

    leads = list(db["outreach_leads_v2"].find(
        {"campaign_id": campaign_id, "workflow_status": {"$in": list(statuses)}},
        {"email": 1}))

    bounce_coll = db["outreach_bounce_suppression"]
    sends_coll = db["outreach_sends_v2"]
    validator = EmailValidator(db)
    _domain_cache: Dict[str, Tuple[int, int]] = {}

    def _domain_stats(domain: str) -> Tuple[int, int]:
        if domain not in _domain_cache:
            pipeline = [
                {"$match": {"email": {"$regex": f"@{domain}$", "$options": "i"}}},
                {"$group": {"_id": None, "sent": {"$sum": 1},
                           "bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}}}},
            ]
            row = next(iter(sends_coll.aggregate(pipeline)), None)
            _domain_cache[domain] = (row["sent"], row["bounced"]) if row else (0, 0)
        return _domain_cache[domain]

    return evaluate_candidates(
        leads,
        is_suppressed=_suppression.is_suppressed,
        is_legacy_bounced=lambda e: bounce_coll.find_one({"email": e}) is not None,
        has_own_bounced_send=lambda e: sends_coll.find_one({"email": e, "status": "bounced"}) is not None,
        has_own_reply=lambda e: sends_coll.find_one({"email": e, "reply_received": True}) is not None,
        live_deliverability_ok=validator.validate_before_send,
        domain_lifetime_stats=_domain_stats,
    )


def apply_reset(db, staged: List[Tuple[Candidate, datetime]], *, dry_run: bool = True) -> Dict[str, int]:
    """
    Write next_send_at + workflow_status="in_sequence" for each staged
    candidate, clearing the old last_send_error. dry_run=True (default) does
    nothing and only reports what WOULD happen -- matches every other
    dry-run-by-default tool in this codebase (scripts/verification_gate.py,
    scripts/outreach_kill_switch.py).
    """
    if dry_run:
        return {"would_reset": len(staged), "applied": 0}
    now = datetime.utcnow()
    applied = 0
    for cand, next_send_at in staged:
        res = db["outreach_leads_v2"].update_one(
            {"_id": cand.lead_id},
            {"$set": {"workflow_status": "in_sequence", "next_send_at": next_send_at,
                      "updated_at": now},
             "$unset": {"last_send_error": ""}})
        applied += res.modified_count
    return {"would_reset": len(staged), "applied": applied}
