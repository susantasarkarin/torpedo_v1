"""Operations decisions and mail bodies (CRM plan 3.6 steps 2-9). Pure.

Redirect format is the one our past mails use (e.g. 2026-10-23, AA8423):
three labelled URLs with rid={RID}. Every other body is a plain draft that
the owner's BU template replaces; in shadow mode none of it is sent.
"""
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------- redirects


def redirect_set(base_url: str) -> Dict[str, str]:
    b = base_url.rstrip("/")
    return {"complete": f"{b}/surveycomplete?rid={{RID}}", "terminate": f"{b}/surveyterminate?rid={{RID}}",
            "quotafull": f"{b}/surveyquotafull?rid={{RID}}",
            "security": f"{b}/surveyterminate?type=security&rid={{RID}}"}


def redirect_mail(rs: Dict[str, str]) -> str:
    return (f"Complete Page URL\n{rs['complete']}\nTerminate Page URL\n{rs['terminate']}\n"
            f"Quota Full Page URL\n{rs['quotafull']}")


# ---------------------------------------------------------------- client intents in thread replies

_INTENTS = [
    ("redirects_requested", re.compile(r"\b(share|send|provide)\b.{0,30}\bredirect", re.I)),
    ("test_confirmed", re.compile(r"\b(test(ing)?|links?)\b.{0,40}\b(ok|okay|fine|working|approved|confirmed|looks good)\b"
                                  r"|\b(go live|launch (it|the study)|start (the )?field)\b", re.I)),
    ("pause_resume", re.compile(r"\b(resume|restart|re-?open)\b", re.I)),
    ("pause_close_bill", re.compile(r"\bclose\b.{0,40}\b(bill|invoice)\b|\bbill\b.{0,40}\b(achieved|delivered|completes?)\b", re.I)),
    ("pause_cancel", re.compile(r"\bcancel(led|l)?\b", re.I)),
    ("stop_field", re.compile(r"\b(stop|close|halt) (the )?(field|survey|study|links?)\b", re.I)),
    ("ids_attached", re.compile(r"\b(accepted|rejected|valid|invalid|final)\b.{0,20}\b(ids?|list)\b", re.I)),
]


def detect_intents(text: str) -> List[str]:
    """Rules first (a person reviews anything else via the mail pipeline)."""
    t = re.split(r"\nOn .{5,120}wrote:|\nFrom: ", text or "")[0]
    return [name for name, rx in _INTENTS if rx.search(t)]


# ---------------------------------------------------------------- soft launch


def soft_launch_variance(project: Dict[str, Any], cfg: Dict[str, Any]) -> List[str]:
    q_ir, a_ir = project.get("clientIR"), project.get("actualIR")
    q_loi, a_loi = project.get("loi"), project.get("actualLOI")
    out = []
    try:
        if q_ir is not None and a_ir is not None and float(q_ir) - float(a_ir) > cfg["soft_launch_ir_points_below"]:
            out.append(f"IR {float(a_ir):g}% vs quoted {float(q_ir):g}%")
        if q_loi and a_loi is not None and float(a_loi) > float(q_loi) * (1 + cfg["soft_launch_loi_pct_above"]):
            out.append(f"LOI {float(a_loi):g} min vs quoted {float(q_loi):g}")
    except (TypeError, ValueError):
        pass
    return out


def soft_launch_reached(project: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    need = float(project.get("totalCompletesRequired") or 0)
    return need > 0 and float(project.get("actualCompletes") or 0) >= need * cfg["soft_launch_share"]


# ---------------------------------------------------------------- consolidated mails


def _line(p: Dict[str, Any]) -> str:
    need, got = p.get("totalCompletesRequired") or 0, p.get("actualCompletes") or 0
    bits = [f"{p.get('projectName') or 'Project'}: {got}/{need} completes"]
    if p.get("actualIR") is not None:
        bits.append(f"IR {p['actualIR']}%")
    if p.get("actualLOI") is not None:
        bits.append(f"LOI {p['actualLOI']} min")
    return " | ".join(bits)


def field_updates(live: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One mail per client contact covering all their live projects."""
    by: Dict[str, List[Dict[str, Any]]] = {}
    for p in live:
        if p.get("_contact_email"):
            by.setdefault(p["_contact_email"], []).append(p)
    return [{"to": to, "kind": "field_update", "project_ids": [str(p["_id"]) for p in ps],
             "subject": "Daily field update", "body": "Today's field status:\n" + "\n".join(f"- {_line(p)}" for p in ps)}
            for to, ps in by.items()]


def paused_digests(paused: List[Dict[str, Any]], now: datetime, cfg: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Mondays only: projects paused > N days, one mail per client. After the
    cap the project goes to a person instead of another mail."""
    out: Dict[str, List[Dict[str, Any]]] = {"mails": [], "review": []}
    if now.weekday() != 0:
        return out
    by: Dict[str, List[Dict[str, Any]]] = {}
    for p in paused:
        at = p.get("paused_at")
        if not isinstance(at, datetime) or now - at < timedelta(days=cfg["paused_days_before_mail"]):
            continue
        if int(p.get("paused_mails_sent") or 0) >= cfg["paused_mail_cap"]:
            out["review"].append(p)
        elif p.get("_contact_email"):
            by.setdefault(p["_contact_email"], []).append(p)
    for to, ps in by.items():
        lines = "\n".join(f"- {p.get('projectName') or 'Project'} (paused since {p['paused_at']:%d %b}"
                          f"{': ' + p['paused_reason'] if p.get('paused_reason') else ''})" for p in ps)
        out["mails"].append({"to": to, "kind": "paused_digest", "project_ids": [str(p["_id"]) for p in ps],
                             "subject": "Paused projects: how would you like to proceed?",
                             "body": "These projects are paused:\n" + lines +
                                     "\nFor each, please let us know: resume, close and bill delivered completes, or cancel."})
    return out


def reconciliation_step(p: Dict[str, Any], now: datetime, cfg: Dict[str, Any]) -> Optional[str]:
    """request -> reminder at day 3, 7 -> bill on our count after 14 days."""
    start = p.get("reconciliation_started_at")
    if not isinstance(start, datetime) or p.get("reconciliation_ids_received"):
        return None
    sent = list(p.get("reconciliation_mails") or [])
    age = (now - start).days
    if "request" not in sent:
        return "request"
    for d in cfg["recon_reminder_days"]:
        if age >= d and f"reminder_{d}" not in sent:
            return f"reminder_{d}"
    if age >= cfg["recon_bill_on_our_count_after_days"]:
        return "bill_on_our_count"
    return None


def reconciliation_mails(projects: List[Dict[str, Any]], now: datetime, cfg: Dict[str, Any]) -> Dict[str, Any]:
    mails: Dict[str, Dict[str, Any]] = {}
    bill = []
    for p in projects:
        step = reconciliation_step(p, now, cfg)
        if step == "bill_on_our_count":
            bill.append(p)
        elif step and p.get("_contact_email"):
            m = mails.setdefault(p["_contact_email"], {"to": p["_contact_email"], "kind": "reconciliation",
                                                       "project_ids": [], "steps": {}, "names": []})
            m["project_ids"].append(str(p["_id"]))
            m["steps"][str(p["_id"])] = step
            m["names"].append(p.get("projectName") or "Project")
    for m in mails.values():
        m["subject"] = "Accepted / rejected IDs for reconciliation"
        m["body"] = ("Field is closed on:\n" + "\n".join(f"- {n}" for n in m.pop("names")) +
                     "\nPlease share the accepted and rejected respondent IDs so we can finalise the counts.")
    return {"mails": list(mails.values()), "bill_on_our_count": bill}
