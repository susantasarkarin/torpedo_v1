"""Service Delivery for Cogentix & BIM non-data-services work (CRM plan 3.13).

Stages are the plan's (kick_off -> in_progress -> client_review -> revision
-> delivered -> closed, plus on_hold); no manual tracker existed to copy
(AUDIT 3.13). Collection: crm_db.service_projects, milestones embedded.
Pure functions; the runner applies them.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

STATUSES = ["kick_off", "in_progress", "client_review", "revision", "delivered", "closed", "on_hold"]
TRANSITIONS = {
    "kick_off": {"in_progress", "on_hold"},
    "in_progress": {"client_review", "on_hold", "delivered"},
    "client_review": {"revision", "delivered", "in_progress", "on_hold"},
    "revision": {"client_review", "on_hold"},
    "delivered": {"closed", "revision"},
    "closed": set(),
    "on_hold": {"kick_off", "in_progress", "client_review", "revision"},
}

DEFAULTS: Dict[str, Any] = {
    "mode": "shadow",
    "rate_table": {"COGENTIX": {}, "BIM": {}},    # owner: {service_type: {"day_rate": x} | {"fixed_fee": x}}
    "owner_reminder_days_before_due": 2,
    "client_review_reminder_after_days": 5,
    "on_hold_days_before_client_mail": 7,
    "always_review_prices": True,
}


class SDError(ValueError):
    pass


def new_project(*, bu: str, account_id: str, contact_id: Optional[str], title: str, scope: str,
                deliverables: List[str], value: float, currency: str, start: datetime, end: datetime,
                owner: Optional[str], opportunity_id: str, now: datetime) -> Dict[str, Any]:
    if bu not in ("COGENTIX", "BIM"):
        raise SDError("Service Delivery is for Cogentix and BIM work")
    return {"bu": bu, "account_id": account_id, "contact_id": contact_id, "title": title, "scope": scope,
            "deliverables": deliverables, "value": float(value), "currency": currency, "start": start, "end": end,
            "owner": owner, "team": [], "opportunity_id": opportunity_id, "status": "kick_off", "milestones": [],
            "linked_ops_projects": [], "history": [{"to": "kick_off", "at": now, "by": "system"}],
            "created_at": now, "updated_at": now, "source": "live"}


def price(bu: str, service_type: str, *, days: Optional[float] = None, cfg=DEFAULTS) -> Dict[str, Any]:
    rate = ((cfg.get("rate_table") or {}).get(bu) or {}).get(service_type)
    if not rate:
        return {"review": f"no rate for {bu}/{service_type} in config (owner)"}
    if "fixed_fee" in rate:
        amt = float(rate["fixed_fee"])
    elif "day_rate" in rate and days:
        amt = float(rate["day_rate"]) * float(days)
    else:
        return {"review": "effort (days) needed for a day-rate service"}
    return {"amount": round(amt, 2), "review": "prices reviewed until the owner turns this off"
            if cfg.get("always_review_prices", True) else None}


def validate_milestones(ms: List[Dict[str, Any]]) -> List[str]:
    probs = []
    total = round(sum(float(m.get("billing_pct") or 0) for m in ms), 4)
    if ms and abs(total - 100) > 0.01:
        probs.append(f"billing % adds to {total}, not 100")
    for i, m in enumerate(ms, 1):
        for f in ("deliverable", "due", "owner"):
            if not m.get(f):
                probs.append(f"milestone {i}: {f} missing")
    return probs


def move(p: Dict[str, Any], to: str) -> None:
    if to not in TRANSITIONS.get(p["status"], set()):
        raise SDError(f"{p['status']} -> {to} is not allowed")


def sign_off(p: Dict[str, Any], idx: int, *, by: str, now: datetime) -> Dict[str, Any]:
    """Milestone signed off -> its invoice line (value x billing %); the last
    one closes the project. Returns the invoice request for Finance (3.9)."""
    m = p["milestones"][idx]
    if m.get("signed_off_at"):
        raise SDError("already signed off")
    m.update(signed_off_at=now, signed_off_by=by)
    amount = round(p["value"] * float(m["billing_pct"]) / 100, 2)
    last = all(x.get("signed_off_at") for x in p["milestones"])
    return {"invoice": {"entity": p["bu"], "account_id": p["account_id"], "amount": amount, "currency": p["currency"],
                        "service_type": "research", "memo": f"{p['title']}: {m['deliverable']}",
                        "source": {"type": "service_milestone", "project": str(p.get("_id")), "milestone": idx}},
            "close_project": last}


def reminders(projects: List[Dict[str, Any]], now: datetime, contact_email: Dict[str, str], cfg=DEFAULTS) -> Dict[str, Any]:
    owner: List[Dict[str, Any]] = []
    client_by: Dict[str, List[str]] = {}
    on_hold = []
    for p in projects:
        if p["status"] == "closed":
            continue
        for m in p.get("milestones") or []:
            due = m.get("due")
            if isinstance(due, datetime) and not m.get("signed_off_at"):
                left = (due - now).days
                if 0 <= left <= cfg["owner_reminder_days_before_due"]:
                    owner.append({"to": m.get("owner") or p.get("owner"), "project": p["title"], "milestone": m["deliverable"],
                                  "due": due})
                elif left < 0:
                    owner.append({"to": m.get("owner") or p.get("owner"), "project": p["title"], "milestone": m["deliverable"],
                                  "due": due, "overdue_days": -left})
            sent = m.get("sent_for_review_at")
            if isinstance(sent, datetime) and not m.get("signed_off_at") and \
                    now - sent > timedelta(days=cfg["client_review_reminder_after_days"]):
                to = contact_email.get(str(p.get("contact_id")))
                if to:
                    client_by.setdefault(to, []).append(f"{p['title']}: {m['deliverable']}")
        held = next((h["at"] for h in reversed(p.get("history") or []) if h.get("to") == "on_hold"), None)
        if p["status"] == "on_hold" and held and now - held > timedelta(days=cfg["on_hold_days_before_client_mail"]):
            on_hold.append(p)
    client = [{"to": t, "subject": "Deliverables awaiting your review",
               "body": "These are with you for review:\n" + "\n".join(f"- {x}" for x in items)} for t, items in client_by.items()]
    return {"owner": owner, "client": client, "on_hold_for_paused_digest": on_hold}
