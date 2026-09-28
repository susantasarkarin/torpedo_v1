"""
Lead nurture for positive outreach replies (Sales > Leads, leads_enriched).

A positive lead gets the `positive_nurture` track from
configs/followup_scripts.json: acknowledge + propose a concall, a reminder,
a value touch, then the RFQ/proposal path. Each due step:
  - creates a Gmail DRAFT in the mailbox the prospect replied to, threaded into
    their conversation, for a person to review and send (NURTURE_AUTO_SEND=true
    sends it instead -- default off: this is a live, warm conversation);
  - opens a CRM task (the concall on step 1, a follow-up otherwise);
  - raises a CRM notification.
Nurture pauses the moment the prospect writes again (a person should answer a
live reply, not a template), and stops on Negative / won / lost. Conversion to
a client still happens only on RFQ won (crm_service.mark_opportunity_won).
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from bson import ObjectId

logger = logging.getLogger(__name__)

TRACK = "positive_nurture"
_CONFIG = Path(__file__).resolve().parent.parent / "configs" / "followup_scripts.json"

# What each ICP basket's buyer usually cares about, for the step-3 value touch.
_PAIN_AREA = {
    "A": "reliable sample for hard-to-reach audiences on tight timelines",
    "B": "turning research data into clear, decision-ready insight",
    "C": "streamlining BIM and digital engineering workflows",
    "D": "fieldwork capacity and faster insight delivery",
}


def _auto_send() -> bool:
    return os.getenv("NURTURE_AUTO_SEND", "false").strip().lower() == "true"


def _steps() -> List[Dict[str, Any]]:
    try:
        cfg = json.loads(_CONFIG.read_text(encoding="utf-8"))
        return sorted(cfg["sequences"][TRACK]["steps"], key=lambda s: s["step"])
    except Exception as e:
        logger.error("nurture: cannot load %s: %s", _CONFIG, e)
        return []


_client = None


def _db(name: str):
    global _client
    if _client is None:
        from pymongo import MongoClient
        _client = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                              serverSelectionTimeoutMS=5000)
    return _client[name]


def _leads():
    return _db("email_automation")["leads_enriched"]


def _first_name(lead: Dict[str, Any]) -> str:
    name = lead.get("first_name") or (lead.get("name") or "").split(" ")[0]
    return name.strip() or "there"


def _original_subject(lead: Dict[str, Any]) -> str:
    subj = lead.get("reply_subject") or "our conversation"
    return re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", subj, flags=re.IGNORECASE).strip() or "our conversation"


def render_step(lead: Dict[str, Any], step_cfg: Dict[str, Any], signer: str) -> Dict[str, str]:
    """Fill one step's templates for this lead. Unknown placeholders are left
    as-is rather than raising, so a config edit can never crash the job."""
    values = {
        "first_name": _first_name(lead),
        "company": lead.get("company_name") or "your team",
        "original_subject": _original_subject(lead),
        "persona_type": "research",
        "pain_area": _PAIN_AREA.get(lead.get("classification_basket") or "", "your current priorities"),
    }

    class _Keep(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    subject = step_cfg["subject_template"].format_map(_Keep(values))
    body = step_cfg["script_template"].format_map(_Keep(values))
    # The scripts are signed "Susanta"; sign as whoever owns the thread.
    if signer:
        body = re.sub(r"(Best,\s*\n)Susanta\s*$", r"\g<1>" + signer, body)
    return {"subject": subject, "body": body}


def _notify(title: str, lead: Dict[str, Any], kind: str, summary: str = "") -> None:
    try:
        from app.services import crm_service
        crm_service.create("notifications", {
            "type": kind, "title": title, "summary": summary,
            "lead_id": str(lead["_id"]), "lead_email": lead.get("email"),
            "read": False,
        })
    except Exception as e:
        logger.warning("nurture: notification failed: %s", e)


def _task(lead: Dict[str, Any], title: str, due: datetime, description: str = "") -> Optional[str]:
    try:
        from app.services import crm_service
        task = crm_service.create("tasks", {
            "title": title, "description": description,
            "linked_object_type": "lead", "linked_object_id": str(lead["_id"]),
            "lead_email": lead.get("email"), "due_date": due,
            "status": "open", "source": "nurture",
        })
        return task.get("_id")
    except Exception as e:
        logger.warning("nurture: task creation failed: %s", e)
        return None


def start_nurture(lead_id: str, started_by: str = "human") -> bool:
    """Put a positive lead on the nurture track. Idempotent."""
    leads = _leads()
    lead = leads.find_one({"_id": ObjectId(lead_id)})
    if not lead:
        return False
    if (lead.get("nurture") or {}).get("status") in ("active", "paused_new_reply"):
        return False
    if lead.get("stage") in ("won", "lost", "converted") or lead.get("lead_status") == "Negative":
        return False
    now = datetime.utcnow()
    leads.update_one({"_id": lead["_id"]}, {"$set": {
        "nurture": {
            "track": TRACK, "status": "active", "step": 0,
            "started_at": now, "started_by": started_by,
            "next_due_at": now, "last_touch_at": now, "history": [],
        },
        "updated_at": now,
    }})
    _notify(f"Positive reply from {lead.get('name') or lead.get('email')}"
            f"{' at ' + lead['company_name'] if lead.get('company_name') else ''} — nurture started",
            lead, "positive_reply", (lead.get("reply_triage") or {}).get("reply_text", "")[:300])
    return True


def resume_nurture(lead_id: str) -> bool:
    """Resume a nurture paused by a new reply, once a person has answered."""
    now = datetime.utcnow()
    res = _leads().update_one(
        {"_id": ObjectId(lead_id), "nurture.status": "paused_new_reply"},
        {"$set": {"nurture.status": "active", "nurture.last_touch_at": now,
                  "nurture.next_due_at": now + timedelta(days=3),
                  "needs_human_review": False, "updated_at": now}})
    return res.modified_count > 0


def stop_nurture(lead_id: str, reason: str) -> bool:
    now = datetime.utcnow()
    res = _leads().update_one(
        {"_id": ObjectId(lead_id), "nurture.status": {"$in": ["active", "paused_new_reply"]}},
        {"$set": {"nurture.status": "stopped", "nurture.stopped_reason": reason,
                  "nurture.stopped_at": now, "updated_at": now}})
    return res.modified_count > 0


def _new_reply_since(lead: Dict[str, Any], since: datetime) -> bool:
    email = (lead.get("email") or "").lower()
    if not email:
        return False
    return _db("torpedo_gmail")["email_metadata"].count_documents({
        "from_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"},
        "direction": "inbound", "timestamp": {"$gt": since}}, limit=1) > 0


def _thread_mailbox(lead: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """The outreach mailbox the prospect replied to, and its thread id."""
    # reply_triage: outreach replies; mail_pool.triage: prospects found in the
    # mail pool. Reading only the first left every mail-pool nurture with "no
    # outreach mailbox" -- stored, never drafted (seen live, 2026-09-28).
    triage = lead.get("reply_triage") or (lead.get("mail_pool") or {}).get("triage") or {}
    mailbox_id = triage.get("mailbox_id")
    mailbox = None
    if mailbox_id:
        try:
            mailbox = _db("torpedo_gmail")["workspace_mailboxes"].find_one({"_id": ObjectId(mailbox_id)})
        except Exception:
            mailbox = None
    return {
        "email": (mailbox or {}).get("email"),
        "display_name": (mailbox or {}).get("display_name") or "",
        "thread_id": triage.get("gmail_thread_id"),
    }


def _deliver(lead: Dict[str, Any], rendered: Dict[str, str], box: Dict[str, Optional[str]]) -> Dict[str, Any]:
    """Create the draft (or send, when NURTURE_AUTO_SEND=true)."""
    if not box.get("email"):
        return {"mode": "stored", "error": "no outreach mailbox on the reply thread"}
    from app.services.gmail_workspace_service import GmailWorkspaceService
    svc = GmailWorkspaceService(mongo_uri=os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                                db_name="torpedo_gmail")
    svc.load_service_account()
    signature = svc.get_signature(box["email"])
    if _auto_send():
        import html as _html
        res = svc.send_email(from_email=box["email"], to=[lead["email"]],
                             subject=rendered["subject"],
                             body_html=_html.escape(rendered["body"]).replace("\n", "<br>"),
                             body_plain=rendered["body"], thread_id=box.get("thread_id"),
                             signature_html=signature)
        return {"mode": "sent", "message_id": res.get("message_id"), "error": res.get("error"),
                "success": res.get("success")}
    res = svc.create_draft(from_email=box["email"], to=[lead["email"]],
                           subject=rendered["subject"], body_plain=rendered["body"],
                           thread_id=box.get("thread_id"), signature_html=signature)
    return {"mode": "draft", "draft_id": res.get("draft_id"), "error": res.get("error"),
            "success": res.get("success")}


def run_nurture_due_batch(limit: int = 20) -> Dict[str, int]:
    """Advance every active nurture whose next step is due."""
    leads = _leads()
    steps = _steps()
    now = datetime.utcnow()
    stats = {"due": 0, "delivered": 0, "stored": 0, "paused_new_reply": 0,
             "stopped": 0, "completed": 0, "errors": 0}
    if not steps:
        return stats

    for lead in leads.find({"nurture.status": "active", "nurture.next_due_at": {"$lte": now}}).limit(limit):
        stats["due"] += 1
        nur = lead["nurture"]

        if lead.get("stage") in ("won", "lost", "converted") or lead.get("lead_status") == "Negative":
            leads.update_one({"_id": lead["_id"]}, {"$set": {
                "nurture.status": "stopped", "nurture.stopped_at": now,
                "nurture.stopped_reason": f"lead is {lead.get('lead_status') or lead.get('stage')}",
                "updated_at": now}})
            stats["stopped"] += 1
            continue
        last_touch = nur.get("last_touch_at") or nur.get("started_at") or now
        if nur.get("step", 0) > 0 and _new_reply_since(lead, last_touch):
            leads.update_one({"_id": lead["_id"]}, {"$set": {
                "nurture.status": "paused_new_reply", "nurture.paused_at": now,
                "needs_human_review": True, "updated_at": now}})
            _notify(f"{lead.get('name') or lead.get('email')} replied again — nurture paused, please respond",
                    lead, "nurture_paused")
            stats["paused_new_reply"] += 1
            continue

        next_steps = [s for s in steps if s["step"] > nur.get("step", 0)]
        if not next_steps:
            leads.update_one({"_id": lead["_id"]}, {"$set": {
                "nurture.status": "completed", "nurture.completed_at": now, "updated_at": now}})
            stats["completed"] += 1
            continue
        step_cfg = next_steps[0]

        box = _thread_mailbox(lead)
        signer = (box.get("display_name") or "").split(" ")[0]
        rendered = render_step(lead, step_cfg, signer)
        try:
            outcome = _deliver(lead, rendered, box)
        except Exception as e:
            outcome = {"mode": "stored", "error": str(e)}
        if outcome.get("mode") in ("draft", "sent") and outcome.get("success"):
            stats["delivered"] += 1
        else:
            stats["stored"] += 1
            if outcome.get("error"):
                stats["errors"] += 1

        is_concall = "concall" in step_cfg.get("label", "").lower()
        task_title = (f"Concall with {lead.get('name') or lead.get('email')}" if is_concall
                      else f"Nurture step {step_cfg['step']}: {step_cfg.get('label')} — {lead.get('name') or lead.get('email')}")
        task_id = _task(lead, task_title, now + timedelta(days=2 if is_concall else 1),
                        f"{'Draft ready in Gmail (' + box['email'] + ')' if outcome.get('mode') == 'draft' and outcome.get('success') else 'Email text stored on the lead'}:\n\n{rendered['body']}")

        after = [s for s in steps if s["step"] > step_cfg["step"]]
        started = nur.get("started_at") or now
        next_due = (started + timedelta(days=after[0].get("delay_days", 3))) if after else None
        if next_due is not None and next_due <= now:
            next_due = now + timedelta(days=1)
        history_entry = {
            "step": step_cfg["step"], "label": step_cfg.get("label"), "at": now,
            "mode": outcome.get("mode"), "draft_id": outcome.get("draft_id"),
            "message_id": outcome.get("message_id"), "error": outcome.get("error"),
            "subject": rendered["subject"], "body": rendered["body"], "task_id": task_id,
            "mailbox": box.get("email"),
        }
        update = {"nurture.step": step_cfg["step"], "nurture.last_touch_at": now,
                  "updated_at": now}
        if next_due:
            update["nurture.next_due_at"] = next_due
        else:
            update["nurture.status"] = "completed"
            update["nurture.completed_at"] = now
        leads.update_one({"_id": lead["_id"]}, {"$set": update, "$push": {"nurture.history": history_entry}})
        _notify(f"Nurture step {step_cfg['step']} ({step_cfg.get('label')}) ready for "
                f"{lead.get('name') or lead.get('email')}", lead, "nurture_step",
                rendered["subject"])

    if stats["due"]:
        logger.info("[Nurture] %s", stats)
    return stats
