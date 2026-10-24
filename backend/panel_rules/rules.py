"""Panel rules (CRM plan 3.7b). Pure functions over member / invite / response
records; the member store is the SFW panel (API on the SFW VM), so callers
pass the rows. Member PII never leaves: everything here works on member IDs.

Quality is FLAG-ONLY until the owner enables enforcement (config
panel.enforce_quality): suspend() returns the decision, it does not act.
"""
import statistics
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

DEFAULTS: Dict[str, Any] = {
    "response_window_days": 90,
    "same_category_exclusion_days": 30,
    "max_invites_per_week": 3,
    "wave_safety": 1.2,              # invite 20% more than the IR/response maths says
    "max_wave_share": 0.25,          # never more than 25% of the eligible pool in one wave
    "reminder_after_hours": 24,
    "speeder_fraction": 1 / 3,       # LOI under a third of the median -> speeder
    "straightline_min_items": 5,
    "suspend_below_score": 30,
    "enforce_quality": False,
    "profile_refresh_days": 182,
    "redemption_max_per_30d": 3,
}


def _matches(member: Dict[str, Any], quota: Dict[str, Any]) -> bool:
    for k, want in (quota or {}).items():
        have = (member.get("profile") or {}).get(k, member.get(k))
        if isinstance(want, (list, tuple, set)):
            if have not in want:
                return False
        elif isinstance(want, dict) and ("min" in want or "max" in want):
            try:
                v = float(have)
            except (TypeError, ValueError):
                return False
            if ("min" in want and v < want["min"]) or ("max" in want and v > want["max"]):
                return False
        elif have != want:
            return False
    return True


def response_rate(invites: List[Dict[str, Any]], now: datetime, cfg=DEFAULTS) -> float:
    since = now - timedelta(days=cfg["response_window_days"])
    recent = [i for i in invites if isinstance(i.get("sent_at"), datetime) and i["sent_at"] >= since]
    return (sum(1 for i in recent if i.get("started")) / len(recent)) if recent else 0.0


def feasibility(members: Iterable[Dict[str, Any]], *, country: str, ir_percent: float,
                invites_by_member: Dict[str, List[Dict[str, Any]]], now: datetime,
                quota: Optional[Dict[str, Any]] = None, cfg=DEFAULTS) -> Dict[str, Any]:
    """matching active members x each member's 90-day response rate x IR."""
    match, expected = 0, 0.0
    for m in members:
        if m.get("status") != "active" or (m.get("country") or "").upper() != country.upper() or not _matches(m, quota or {}):
            continue
        match += 1
        expected += response_rate(invites_by_member.get(str(m["_id"]), []), now, cfg)
    return {"matching_active": match, "expected_starts": round(expected, 1),
            "feasible_completes": int(expected * float(ir_percent) / 100)}


def invite_exclusion(member: Dict[str, Any], invites: List[Dict[str, Any]], category: Optional[str],
                     now: datetime, cfg=DEFAULTS) -> Optional[str]:
    if member.get("status") != "active":
        return "not active"
    if not member.get("double_opt_in"):
        return "no double opt-in"
    if member.get("unsubscribed") or member.get("suppressed"):
        return "unsubscribed or suppressed"
    week = [i for i in invites if isinstance(i.get("sent_at"), datetime) and i["sent_at"] >= now - timedelta(days=7)]
    if len(week) >= cfg["max_invites_per_week"]:
        return f"{len(week)} invites in the last 7 days"
    if category:
        cut = now - timedelta(days=cfg["same_category_exclusion_days"])
        if any(i.get("category") == category and isinstance(i.get("sent_at"), datetime) and i["sent_at"] >= cut
               for i in invites):
            return f"same category ({category}) in the last {cfg['same_category_exclusion_days']} days"
    return None


def next_wave(*, target: int, completes: int, ir_percent: float, response: float, pending_invites: int,
              eligible: int, cfg=DEFAULTS) -> int:
    """Invites for the next wave, topped up from the actual IR: what is still
    needed / (response x IR) x safety, minus invites still open, capped."""
    need = max(0, target - completes)
    if need == 0 or response <= 0 or ir_percent <= 0:
        return 0
    want = int(need / (response * ir_percent / 100) * cfg["wave_safety"]) - pending_invites
    return max(0, min(want, int(eligible * cfg["max_wave_share"]), eligible))


def reminder_due(invite: Dict[str, Any], now: datetime, cfg=DEFAULTS) -> bool:
    return (isinstance(invite.get("sent_at"), datetime) and not invite.get("started") and not invite.get("reminded_at")
            and now - invite["sent_at"] >= timedelta(hours=cfg["reminder_after_hours"]))


def profile_refresh_due(member: Dict[str, Any], now: datetime, cfg=DEFAULTS) -> bool:
    at = member.get("profile_updated_at")
    return not isinstance(at, datetime) or now - at >= timedelta(days=cfg["profile_refresh_days"])


# ---------------------------------------------------------------- quality


def quality_flags(resp: Dict[str, Any], *, median_loi: Optional[float], seen: Dict[str, set],
                  cfg=DEFAULTS) -> List[str]:
    """seen: {'person': set, 'device': set, 'ip': set} for this project so far (mutated)."""
    flags = []
    for k, field in (("person", "member_id"), ("device", "fingerprint"), ("ip", "ip")):
        v = resp.get(field)
        if v:
            if v in seen.setdefault(k, set()):
                flags.append(f"duplicate {k}")
            seen[k].add(v)
    if resp.get("ip_country") and resp.get("country") and resp["ip_country"].upper() != resp["country"].upper():
        flags.append(f"IP country {resp['ip_country']} vs {resp['country']}")
    if median_loi and resp.get("loi_minutes") is not None and float(resp["loi_minutes"]) < median_loi * cfg["speeder_fraction"]:
        flags.append("speeder")
    for grid in resp.get("grids") or []:
        if len(grid) >= cfg["straightline_min_items"] and len(set(grid)) == 1:
            flags.append("straight-lining")
            break
    for text in resp.get("open_ends") or []:
        t = (text or "").strip().lower()
        if t and (len(set(t.replace(" ", ""))) <= 2 or t in {"na", "n/a", "nothing", "good", "ok", "asdf"}):
            flags.append("junk open-end")
            break
    return flags


def median_loi(lois: List[float]) -> Optional[float]:
    lois = [float(x) for x in lois if x is not None]
    return statistics.median(lois) if lois else None


def suspend(member: Dict[str, Any], cfg=DEFAULTS) -> Dict[str, Any]:
    score = member.get("quality_score")
    low = score is not None and float(score) < cfg["suspend_below_score"]
    return {"suspend": low and bool(cfg["enforce_quality"]), "flag": low,
            "reason": f"quality score below {cfg['suspend_below_score']}" if low else None}


# ---------------------------------------------------------------- incentives


def incentive_status(complete: Dict[str, Any], recon: Optional[Dict[str, Any]]) -> str:
    """pending until the client's reconciliation lists this ID as accepted."""
    if not recon or not recon.get("received"):
        return "pending_reconciliation"
    rid = str(complete.get("rid") or complete.get("_id"))
    if rid in {str(x) for x in recon.get("accepted") or []}:
        return "confirmed"
    if rid in {str(x) for x in recon.get("rejected") or []}:
        return "rejected"
    return "pending_reconciliation"


def redemption_check(member: Dict[str, Any], redemption: Dict[str, Any], history: List[Dict[str, Any]],
                     now: datetime, cfg=DEFAULTS) -> List[str]:
    probs = []
    confirmed = float(member.get("confirmed_balance") or 0)
    if float(redemption.get("amount") or 0) > confirmed:
        probs.append(f"amount above confirmed balance {confirmed}")
    recent = [h for h in history if isinstance(h.get("at"), datetime) and h["at"] >= now - timedelta(days=30)]
    if len(recent) >= cfg["redemption_max_per_30d"]:
        probs.append(f"{len(recent)} redemptions in 30 days")
    if member.get("quality_flags"):
        probs.append("member has quality flags")
    if redemption.get("payout_account") and redemption["payout_account"] in (member.get("shared_payout_accounts") or []):
        probs.append("payout account shared with another member")
    return probs


def project_incentive_cost(completes: List[Dict[str, Any]]) -> float:
    return round(sum(float(c.get("incentive") or 0) for c in completes if c.get("incentive_status") == "confirmed"), 2)


# ---------------------------------------------------------------- panel book + privacy


def panel_book(stats: Dict[str, Any], bu: str, month: str) -> Dict[str, Any]:
    """Monthly per BU from live stats: what 3.3 positive replies attach."""
    by_c = stats.get("active_by_country") or {}
    return {"bu": bu, "month": month, "active_members": sum(by_c.values()),
            "countries": [{"country": c, "active": n} for c, n in sorted(by_c.items(), key=lambda x: -x[1])],
            "response_rate_90d": stats.get("response_rate_90d"), "profiling_points": stats.get("profiling_points"),
            "quality": stats.get("quality")}


PII_FIELDS = ("email", "phone", "first_name", "last_name", "name", "address", "dob", "ip", "payout_account")


def erasure_update(member: Dict[str, Any], now: datetime, request_id: str) -> Dict[str, Any]:
    """A member's deletion request: PII blanked, ID and aggregates kept,
    status flagged. The row itself is never deleted (ground rule)."""
    return {"$set": {**{f: None for f in PII_FIELDS if f in member}, "status": "erased", "suppressed": True,
                     "erased_at": now, "erasure_request_id": request_id}}


def consent_record(member_id: str, kind: str, granted: bool, source: str, now: datetime,
                   text_version: str) -> Dict[str, Any]:
    return {"member_id": member_id, "kind": kind, "granted": granted, "source": source, "at": now,
            "text_version": text_version}
