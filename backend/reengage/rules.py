"""Re-engagement (CRM plan 3.10). Pure.

engagement_status per account: active | dormant | lost | dnd. Dormant = no
live project and no two-way communication for N days (config). Dormant
accounts get a 3-mail sequence, one step every 21 days, stopped by any reply;
lost / no-response RFQs get a check-in after 30 days and then join the
dormant sequence. The historical backlog is released under a daily cap.

The existing app/services/reengagement.py (Gmail drafts for quiet quotes and
positive replies) keeps running; this module owns the account status and the
dormant sequence.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    "mode": "shadow",
    "dormant_after_days": 90,
    "lost_after_days": 730,          # dormant this long with no reply to the sequence -> lost
    "sequence_steps": ["whats_new", "case_study", "check_in"],
    "sequence_gap_days": 21,
    "lost_rfq_checkin_days": 30,
    "daily_release_cap": 20,
}


def engagement_status(*, dnd: bool, has_live_project: bool, last_two_way: Optional[datetime],
                      now: datetime, sequence: Optional[Dict[str, Any]] = None, cfg=DEFAULTS) -> str:
    if dnd:
        return "dnd"
    if has_live_project or (last_two_way and now - last_two_way < timedelta(days=cfg["dormant_after_days"])):
        return "active"
    if (sequence or {}).get("finished_without_reply") and last_two_way and \
            now - last_two_way >= timedelta(days=cfg["lost_after_days"]):
        return "lost"
    return "dormant"


def next_step(seq: Optional[Dict[str, Any]], now: datetime, cfg=DEFAULTS) -> Optional[str]:
    """seq: {'sent': [{'step', 'at'}], 'replied_at'} -> next step name or None."""
    seq = seq or {}
    if seq.get("replied_at"):
        return None
    sent = seq.get("sent") or []
    if len(sent) >= len(cfg["sequence_steps"]):
        return None
    if sent and now - sent[-1]["at"] < timedelta(days=cfg["sequence_gap_days"]):
        return None
    return cfg["sequence_steps"][len(sent)]


def lost_rfq_checkin_due(rfq: Dict[str, Any], now: datetime, cfg=DEFAULTS) -> bool:
    closed = rfq.get("closed_at") or rfq.get("lost_at")
    return (rfq.get("outcome") in ("lost", "no_response") and isinstance(closed, datetime)
            and now - closed >= timedelta(days=cfg["lost_rfq_checkin_days"]) and not rfq.get("checkin_sent_at"))


def release(candidates: List[Dict[str, Any]], already_today: int, cfg=DEFAULTS) -> List[Dict[str, Any]]:
    """Highest value first (lifetime revenue), within the daily cap."""
    room = max(0, int(cfg["daily_release_cap"]) - already_today)
    return sorted(candidates, key=lambda c: -float(c.get("lifetime_revenue") or 0))[:room]


def draft(step: str, account_name: str, panel_book: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Plain draft; the owner's BU template replaces the wording (client-facing)."""
    if step == "whats_new":
        countries = ", ".join(c["country"] for c in (panel_book or {}).get("countries", [])[:6])
        body = ("It has been a while. A quick note on what is new with us"
                + (f": live panel coverage now includes {countries}." if countries else "."))
        return {"subject": "What's new", "body": body}
    if step == "case_study":
        return {"subject": "A recent project you may find relevant",
                "body": "Sharing a short case study from a recent project in your space."}
    return {"subject": "Checking in", "body": "Is there anything coming up where we could help?"}
