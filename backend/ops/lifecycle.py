"""Operations project lifecycle (CRM plan 3.6) on email_automation.projects.

The spec status lives in `lifecycle_status` next to the legacy fields
(`status`, `projectStatus`), which the Operations page and close_project still
read; legacy_status() maps them until the Phase 4 backfill stamps every project.
Every move is checked against TRANSITIONS, kept in lifecycle_history and audited.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

STATUSES = ["awaiting_setup", "testing", "soft_launch", "live", "paused", "field_closed",
            "reconciliation", "closed", "invoiced"]
TRANSITIONS = {
    "awaiting_setup": {"testing", "paused", "field_closed"},
    "testing": {"soft_launch", "live", "paused", "field_closed"},
    "soft_launch": {"live", "paused", "field_closed"},
    "live": {"paused", "field_closed"},
    "paused": {"testing", "soft_launch", "live", "field_closed"},
    "field_closed": {"reconciliation", "live"},
    "reconciliation": {"closed"},
    "closed": {"invoiced"},
    "invoiced": set(),
}

DEFAULTS: Dict[str, Any] = {
    "mode": "shadow",                       # shadow: plan mails only; live (owner): send through the gate
    "pm_rule": "by_bu",                     # by_bu | round_robin
    "pm_by_bu": {"SFW": None, "COGENTIX": None, "BIM": None},   # owner fills; None = unassigned -> Review Queue
    "pm_round_robin": [],
    "soft_launch_share": 0.10,
    "soft_launch_ir_points_below": 10,      # actual IR more than X points below quoted -> CPI revision
    "soft_launch_loi_pct_above": 0.25,      # actual LOI more than Y% above quoted -> CPI revision
    "paused_days_before_mail": 7,
    "paused_mail_cap": 4,
    "recon_reminder_days": [3, 7],
    "recon_bill_on_our_count_after_days": 14,
    "field_update_hour_ist": 18,
    "redirect_base_url": "https://torpedo.cogentixresearch.com",
}


class TransitionError(ValueError):
    pass


def legacy_status(p: Dict[str, Any]) -> str:
    if p.get("lifecycle_status") in STATUSES:
        return p["lifecycle_status"]
    if p.get("invoice_ids"):
        return "invoiced"
    if p.get("status") == "completed" or (p.get("projectStatus") or "").lower() in ("close", "closed"):
        return "closed"
    ps = (p.get("projectStatus") or "").lower()
    if ps == "live" or p.get("status") == "active":
        return "live" if (p.get("actualCompletes") or 0) or p.get("liveLink") else "awaiting_setup"
    if ps in ("pause", "paused", "hold"):
        return "paused"
    return "awaiting_setup"


def check(frm: str, to: str) -> None:
    if to not in STATUSES:
        raise TransitionError(f"unknown status {to!r}")
    if to not in TRANSITIONS.get(frm, set()):
        raise TransitionError(f"{frm} -> {to} is not allowed")


def transition(col, project: Dict[str, Any], to: str, *, actor: str, reason: str,
               now: Optional[datetime] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    frm = legacy_status(project)
    check(frm, to)
    now = now or datetime.utcnow()
    entry = {"from": frm, "to": to, "at": now, "by": actor, "reason": reason}
    upd = {"lifecycle_status": to, "lifecycle_updated_at": now, **(extra or {})}
    if to == "paused":
        upd.update(paused_at=now, paused_reason=reason, paused_mails_sent=0)
    if to == "reconciliation":
        upd["reconciliation_started_at"] = now
    col.update_one({"_id": project["_id"]}, {"$set": upd, "$push": {"lifecycle_history": entry}})
    try:
        from platform_core.audit import log_action
        log_action(actor=actor, action="update", entity_type="ops_project", entity_id=str(project["_id"]),
                   reason=reason, changes={"lifecycle_status": {"from": frm, "to": to}}, source="ops.lifecycle")
    except Exception:
        pass
    return entry


def assign_pm(bu: Optional[str], cfg: Dict[str, Any], assigned_counts: Dict[str, int]) -> Optional[str]:
    """Config rule only; None means no PM is configured (owner) -> Review Queue."""
    if cfg.get("pm_rule") == "round_robin":
        pms: List[str] = [p for p in cfg.get("pm_round_robin") or [] if p]
        return min(pms, key=lambda p: (assigned_counts.get(p, 0), pms.index(p))) if pms else None
    return (cfg.get("pm_by_bu") or {}).get(bu or "")
