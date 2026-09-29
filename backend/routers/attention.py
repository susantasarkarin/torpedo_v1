"""
"Needs your attention" for the main dashboard.

One call that gathers what is waiting on a person across sales, finance,
operations and the automations -- each item with a count, a few examples and
the page where it is handled. Items with nothing waiting are left out; a
check that fails is reported as its own item rather than hidden.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attention", tags=["Attention"])


def _client():
    from database import get_client
    return get_client()


def _item(key, title, count, link, severity="normal", detail="", examples=None):
    return {"key": key, "title": title, "count": count, "link": link, "severity": severity,
            "detail": detail, "examples": examples or []}


def _leads(c, now) -> List[Dict[str, Any]]:
    le = c["email_automation"]["leads_enriched"]
    automated = {"$in": ["reply_triage", "mail_pool_triage"]}
    out = []
    q = {"lead_status": "Needs Human", "lead_status_source": automated}
    n = le.count_documents(q)
    if n:
        ex = [f"{d.get('name') or d.get('email')}: {((d.get('mail_pool') or {}).get('triage') or d.get('reply_triage') or {}).get('reason', '')[:80]}"
              for d in le.find(q, {"name": 1, "email": 1, "mail_pool.triage.reason": 1, "reply_triage.reason": 1})
              .sort("updated_at", -1).limit(3)]
        out.append(_item("leads_needs_human", "Replies the system could not judge", n,
                         "/admin/sales/leads", "high", "Read and set Positive / Negative", ex))
    # By when they replied, not when the record was touched (a backfill
    # touches every record).
    since = now - timedelta(days=14)
    q = {"lead_status": "Positive", "lead_status_source": automated, "stage": {"$ne": "won"},
         "$or": [{"mail_pool.last_contact_at": {"$gte": since}}, {"outreach_replied_at": {"$gte": since}}]}
    n = le.count_documents(q)
    if n:
        ex = [f"{d.get('name') or d.get('email')} ({d.get('company_name') or ''})"
              for d in le.find(q, {"name": 1, "email": 1, "company_name": 1}).sort("updated_at", -1).limit(3)]
        out.append(_item("leads_positive", "New positive replies (last 14 days)", n,
                         "/admin/sales/leads", "high", "Follow up or book a call", ex))
    q = {"nurture.status": "active", "nurture.history": {"$elemMatch": {"mode": "draft",
                                                                         "at": {"$gte": now - timedelta(days=7)}}}}
    n = le.count_documents(q)
    if n:
        out.append(_item("nurture_drafts", "Follow-up drafts waiting in Gmail", n, "/admin/sales/leads",
                         "normal", "Review and send the drafts in the sender's mailbox"))
    try:
        from app.services.reengagement import summary
        s = summary(c, now)
        if s["drafts_this_week"]:
            kinds = {"quote_no_reply": "quotes with no reply", "positive_quiet": "positive leads gone quiet",
                     "dormant_client": "past clients gone quiet"}
            detail = ", ".join(f"{n} {kinds[k]}" for k, n in s["by_kind"].items() if k in kinds)
            out.append(_item("reengagement_drafts", "Check-in drafts for people we forgot", s["drafts_this_week"],
                             "/admin/crm/tasks", "high", f"Review and send in Gmail — {detail}"))
    except Exception as e:
        logger.debug("attention: reengagement summary skipped: %s", e)
    q = {"nurture.status": "paused_new_reply"}
    n = le.count_documents(q)
    if n:
        out.append(_item("nurture_paused", "Nurtured prospects who wrote back", n, "/admin/sales/leads", "high",
                         "Answer them, then resume the nurture"))
    return out


def _tasks(c) -> List[Dict[str, Any]]:
    labels = {"finance_automation": "Finance follow-ups", "project_close": "Projects closed with no value",
              "nurture": "Calls to book (nurture)", "won_handoff": "Won-deal setup tasks",
              "invoice_reminder": "Payment reminders to send",
              "reengagement": "Clients and leads gone quiet"}
    out = []
    for row in c["crm_db"]["tasks"].aggregate([
            {"$match": {"status": "open"}},
            {"$group": {"_id": "$source", "n": {"$sum": 1}, "titles": {"$push": "$title"}}},
            {"$sort": {"n": -1}}]):
        src = row["_id"] or "other"
        out.append(_item(f"tasks_{src}", labels.get(src, f"Open tasks ({src})"), row["n"], "/admin/crm/tasks",
                         "high" if src in ("project_close", "finance_automation") else "normal",
                         examples=[t for t in row["titles"][-3:] if t]))
    return out


def _finance(c, now) -> List[Dict[str, Any]]:
    inv = c["finance_db"]["invoices"]
    out = []
    overdue = list(inv.aggregate([
        {"$match": {"status": {"$in": ["overdue", "partial"]}, "is_deleted": {"$ne": True}}},
        {"$group": {"_id": {"$ifNull": ["$currency_code", "$currency"]}, "n": {"$sum": 1},
                    "due": {"$sum": {"$ifNull": ["$balance_due", "$total_amount"]}}}}]))
    if overdue:
        n = sum(r["n"] for r in overdue)
        detail = ", ".join(f"{r['_id'] or '?'} {r['due']:,.0f}" for r in overdue)
        out.append(_item("invoices_overdue", "Overdue invoices", n, "/admin/finance/invoices", "high",
                         f"Outstanding: {detail}"))
    n = inv.count_documents({"status": "draft", "is_deleted": {"$ne": True}})
    if n:
        out.append(_item("invoices_draft", "Invoices still in draft", n, "/admin/finance/invoices", "normal",
                         "Review and send, or delete"))
    return out


def _rfqs(c, now) -> List[Dict[str, Any]]:
    # By when the RFQ mail arrived: a bulk backfill on 2026-08-31 created
    # hundreds of records from 2025 mail, and counting by created_at showed
    # them all as new.
    since = now - timedelta(days=30)
    q = {"stage": "rfq", "status": "open", "$or": [
        {"metadata.rfq.received_at": {"$gte": since}},
        {"metadata.rfq.received_at": {"$exists": False}, "created_at": {"$gte": since}}]}
    opp = c["crm_db"]["opportunities"]
    out = []
    n = opp.count_documents(q)
    if n:
        ex = [d.get("title") for d in opp.find(q, {"title": 1}).sort("created_at", -1).limit(3)]
        out.append(_item("rfqs_open", "RFQs received in the last 30 days", n, "/admin/sales/rfq", "high",
                         "Quote or close them", ex))
    pending = c["email_automation"]["rfq_review_queue"].count_documents({"status": "pending_review"})
    if pending:
        out.append(_item("rfq_review", "RFQs found in mail, waiting for your approval", pending,
                         "/admin/sales/rfq", "high", "Approve to create the RFQ, or reject"))
    return out


def _automation(c, now) -> List[Dict[str, Any]]:
    out = []
    try:
        from messaging import facade
        problem = facade._compliance_problem(transactional=False)
        if problem:
            out.append(_item("outreach_compliance", "Outreach is blocked by a missing setting", 1,
                             "/admin/sales/outreach", "high", str(problem)[:200]))
    except Exception as e:
        logger.debug("attention: compliance check skipped: %s", e)
    try:
        from integrations import zoho_books as zb
        if not zb.configured():
            out.append(_item("zoho_not_connected", "Zoho Books is not connected yet", 1, "", "normal",
                             "Add the Self Client credentials to the server (see scripts/zoho_connect.py); missing: "
                             + ", ".join(zb.missing_settings())))
        else:
            st = c["finance_db"]["zoho_sync_state"].find_one({"_id": "mirror"}) or {}
            last = st.get("last_run_at")
            if not last or last < now - timedelta(hours=13):
                out.append(_item("zoho_stale", "Zoho Books figures are out of date", 1, "", "normal",
                                 f"Last mirrored: {last:%Y-%m-%d %H:%M} UTC" if last else "Never mirrored"))
    except Exception as e:
        logger.debug("attention: zoho check skipped: %s", e)
    t = c["torpedo"]
    ks = t["outreach_kill_switch"].find_one({}) or {}
    if ks.get("paused"):
        out.append(_item("outreach_paused", "Outreach kill switch is ON", 1, "/admin/sales/outreach", "high",
                         (ks.get("reason") or "")[:200]))
    active = [x.get("campaign_id") for x in t["outreach_campaigns_v2"].find({"is_active": True}, {"campaign_id": 1})]
    if active:
        sendable = t["outreach_leads_v2"].count_documents({"campaign_id": {"$in": active}, "sendable": True,
                                                           "workflow_status": {"$in": ["in_sequence", "not_started"]}})
        if sendable == 0:
            verdicts = {r["_id"]: r["n"] for r in t["outreach_leads_v2"].aggregate([
                {"$match": {"verification_status_inhouse": {"$exists": True}}},
                {"$group": {"_id": "$verification_status_inhouse", "n": {"$sum": 1}}}])}
            detail = "New leads stay unsendable until you decide which verification verdicts may be sent to"
            if verdicts:
                detail += " — in-house check: " + ", ".join(
                    f"{verdicts.get('inhouse:' + v, 0)} {v}" for v in ("valid", "likely", "risky", "unknown", "invalid"))
            out.append(_item("outreach_no_sendable", "Active campaigns have no verified leads to send to", 1,
                             "/admin/sales/outreach", "high", detail))
    st = c["email_automation"]["scheduler_state"].find_one({"_id": "google_cse_state"}) or {}
    if st.get("paused_until") and st["paused_until"] > now:
        out.append(_item("leadgen_paused", "Lead search is paused", 1, "/admin/sales/campaign/ai-leads", "normal",
                         f"Until {st['paused_until']:%Y-%m-%d %H:%M} UTC — {(st.get('paused_reason') or '')[:120]}"))
    try:
        stash = c["email_automation"]["extraction_backlog"].count_documents({"status": "pending"})
    except Exception:
        stash = 0
    if stash:
        out.append(_item("leadgen_stash", "Search results waiting for the model", stash,
                         "/admin/sales/campaign/ai-leads", "low", "Retried automatically"))
    n = c["torpedo_gmail"]["email_metadata"].count_documents({"ai_tier1_status": "pending_ai"})
    if n:
        out.append(_item("mailpool_backlog", "Mail waiting for the model to sort", n, "/admin/mail-pool", "low",
                         "Sorted automatically, newest first"))
    return out


def _stats(c) -> Dict[str, Any]:
    t, ea, crm = c["torpedo"], c["email_automation"], c["crm_db"]
    return {
        "active_campaigns": t["outreach_campaigns_v2"].count_documents({"is_active": True}),
        "leads": ea["leads_enriched"].count_documents({}),
        "vendor_leads": ea["vendor_leads"].count_documents({}),
        "open_rfqs": crm["opportunities"].count_documents({"stage": "rfq", "status": "open"}),
    }


@router.get("")
def get_attention() -> Dict[str, Any]:
    c = _client()
    now = datetime.utcnow()
    items: List[Dict[str, Any]] = []
    for name, fn in (("leads", lambda: _leads(c, now)), ("tasks", lambda: _tasks(c)),
                     ("finance", lambda: _finance(c, now)), ("rfqs", lambda: _rfqs(c, now)),
                     ("automation", lambda: _automation(c, now))):
        try:
            items.extend(fn())
        except Exception as e:
            logger.warning("attention: %s check failed: %s", name, e)
            items.append(_item(f"check_failed_{name}", f"Could not check {name}", 1, "", "low", str(e)[:200]))
    order = {"high": 0, "normal": 1, "low": 2}
    items.sort(key=lambda i: (order.get(i["severity"], 1), -i["count"]))
    try:
        stats = _stats(c)
    except Exception as e:
        logger.warning("attention: stats failed: %s", e)
        stats = {}
    return {"generated_at": now, "items": items, "stats": stats}
