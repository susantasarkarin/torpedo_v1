"""Mail pipeline (CRM plan 3.3), applied to each new inbound message.

  1 link      reference ID in the subject ([L-xxxxxx] outreach, [VB-...] vendor
              bid), else the Gmail thread: an outreach thread -> that lead; a
              known crm thread -> its type and record; an RFQ thread -> the RFQ
  2 sender    code first: our domains with every recipient internal ->
              internal; vendor master / vendor relationship / vendor-bid
              thread -> vendor; account, lead or client relationship ->
              client; unknown -> Qwen (sender_type), checked, else review
  3 category  bounce (hard/soft by code), out-of-office (+ return date) and the
              reply-triage rules first; RFQ / confirmation / redirect / transfer
              / reconnect-later by rule; Qwen (reply_classification) only for
              what rules leave open, its answer checked against the signals
  4 actions   a plan of actions (pause, stop, suppress, review item, event)

Mode (config mail_pipeline.mode): "shadow" (default) records the decision and
the planned actions in email_automation.mail_decisions and changes nothing;
"live" also applies them. Only the owner switches to live (Phase 5), and then
the older reply jobs (reply_triage, outreach bounce scanner) are turned off so
nothing is handled twice.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from . import rules

logger = logging.getLogger(__name__)

OWN_DOMAINS = {"surveyfieldwork.com", "cogentixresearch.com", "bimwavesolutions.com"}
REF_RE = re.compile(r"\[(L-[0-9A-F]{6}|VB-[A-Za-z0-9]+-\d+)\]")
CATEGORIES = ("positive", "negative", "bounce", "neutral", "out_of_office", "rfq",
              "confirmation", "redirect_request", "other")
NEUTRAL_SUBTYPES = ("transferred", "reconnect_later", "other")

REPLY_SCHEMA = {
    "type": "object",
    "required": ["category"],
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "neutral_subtype": {"type": ["string", "null"]},
        "company_wide_decline": {"type": ["boolean", "null"]},
        "wants": {"type": ["array", "null"]},
    },
}
REPLY_SYSTEM = (
    "Classify the newest reply in a B2B email thread for a market-research data-collection company. "
    "The sender type is given. Categories: positive (interested, asks for something), negative "
    "(declines / not interested / remove me), neutral (transferred to someone else, reconnect later, or "
    "other neutral), out_of_office, rfq (asks for a quote with specs), confirmation (awards the work / "
    "go ahead / PO), redirect_request (asks for our redirect links), other. "
    "Return JSON only: {\"category\": ..., \"neutral_subtype\": \"transferred\"|\"reconnect_later\"|\"other\"|null, "
    "\"company_wide_decline\": true|false|null, \"wants\": [\"credentials\"|\"panel_book\"|\"meeting\"|\"pricing\"|\"capabilities\"|\"other\"]}"
)
SENDER_SCHEMA = {"type": "object", "required": ["sender_type"],
                 "properties": {"sender_type": {"type": "string", "enum": ["client", "vendor", "internal", "other"]}}}
SENDER_SYSTEM = ("Decide who sent this email to a market-research data-collection company: client (buys "
                 "research or sample from us, or is a prospect), vendor (sells sample/services to us), "
                 "internal, or other (newsletters, tools, spam). Return JSON only: {\"sender_type\": ...}.")


def _domain(addr: str) -> str:
    return (addr or "").rsplit("@", 1)[-1].lower().strip(">")


# ------------------------------------------------------------------- 1 link
def link(msg: Dict[str, Any], db: Dict[str, Any]) -> Dict[str, Any]:
    subject = msg.get("subject") or ""
    m = REF_RE.search(subject)
    if m:
        ref = m.group(1)
        if ref.startswith("L-"):
            send = db["outreach_sends"].find_one({"ref_id": ref}, {"outreach_lead_id": 1, "lead_id": 1, "campaign_id": 1})
            if send:
                return {"how": "ref_id", "ref": ref, "type": "outreach", "outreach_lead_id": send.get("outreach_lead_id"),
                        "lead_id": send.get("lead_id"), "campaign_id": send.get("campaign_id")}
        else:
            bid = db["vendor_bids"].find_one({"ref_id": ref}, {"_id": 1, "rfq_id": 1})
            if bid:
                return {"how": "ref_id", "ref": ref, "type": "vendor_bid", "vendor_bid_id": str(bid["_id"]),
                        "rfq_id": bid.get("rfq_id")}
    tid = msg.get("gmail_thread_id")
    if tid:
        send = db["outreach_sends"].find_one({"gmail_thread_id": tid}, {"outreach_lead_id": 1, "lead_id": 1, "campaign_id": 1})
        if send:
            return {"how": "thread", "type": "outreach", "outreach_lead_id": send.get("outreach_lead_id"),
                    "lead_id": send.get("lead_id"), "campaign_id": send.get("campaign_id")}
        th = db["threads"].find_one({"gmail_thread_id": tid})
        if th:
            return {"how": "thread", "type": th.get("type"), **{k: th.get(k) for k in
                    ("account_id", "contact_id", "rfq_id", "project_id", "vendor_bid_id") if th.get(k)}}
        opp = db["opportunities"].find_one({"$or": [{"metadata.rfq.gmail_thread_id": tid},
                                                     {"metadata.rfq.gmail_thread_ids": tid}]}, {"_id": 1, "account_id": 1})
        if opp:
            return {"how": "thread", "type": "rfq", "rfq_id": str(opp["_id"]), "account_id": opp.get("account_id")}
    return {"how": "none", "type": None}


# ----------------------------------------------------------------- 2 sender
def sender_type(msg: Dict[str, Any], linked: Dict[str, Any], ctx: Any, db: Dict[str, Any],
                model: Optional[Any] = None) -> Dict[str, Any]:
    sender = (msg.get("from_email") or "").lower()
    dom = _domain(sender)
    rcpts = [a.lower() for a in (msg.get("to_emails") or []) + (msg.get("cc_emails") or []) if a]
    if dom in OWN_DOMAINS:
        if rcpts and all(_domain(a) in OWN_DOMAINS for a in rcpts):
            return {"type": "internal", "how": "own domains, internal recipients"}
        return {"type": "internal", "how": "own domain"}
    if linked.get("type") == "vendor_bid":
        return {"type": "vendor", "how": "vendor-bid thread"}
    role = None
    try:
        role = ctx.role(sender, msg.get("gmail_thread_id")) if ctx else None
    except Exception:
        role = None
    if role == "vendor":
        return {"type": "vendor", "how": "vendor master / relationship"}
    if role == "client":
        return {"type": "client", "how": "client relationship / evidence"}
    if linked.get("type") in ("outreach", "rfq"):
        return {"type": "client", "how": f"{linked['type']} thread"}
    if db["leads"].find_one({"email": sender}, {"_id": 1}) or db["contacts"].find_one({"email": sender}, {"_id": 1}):
        return {"type": "client", "how": "known lead/contact"}
    if dom and db["accounts"].find_one({"$or": [{"domain": dom}, {"root_domain": dom}],
                                        "status": {"$nin": ["deleted", "merged"]}}, {"_id": 1}):
        return {"type": "client", "how": "account domain"}
    if model is None:
        return {"type": "unknown", "how": "no rule; model not run"}
    res = model(task="sender_type", system=SENDER_SYSTEM, subject=msg.get("subject") or "",
                body=msg.get("body_plain") or "", schema=SENDER_SCHEMA,
                ref={"collection": "torpedo_gmail.email_metadata", "id": str(msg.get("_id"))})
    if res.get("status") == "ok":
        return {"type": res["data"]["sender_type"], "how": "model"}
    return {"type": "unknown", "how": f"model {res.get('status')}", "review_item": res.get("review_item")}


# --------------------------------------------------------------- 3 category
def _reply_text(msg):
    from sales.reply_triage import strip_quoted
    return strip_quoted(msg.get("body_plain") or msg.get("snippet") or "")


def categorize(msg: Dict[str, Any], sender: Dict[str, Any], model: Optional[Any] = None,
               bounce_patterns=None) -> Dict[str, Any]:
    subject = msg.get("subject") or ""
    sender_addr = (msg.get("from_email") or "").lower()
    received = msg.get("timestamp") if isinstance(msg.get("timestamp"), datetime) else datetime.utcnow()
    bounce_from, bounce_subj, ooo_subj = bounce_patterns
    if bounce_from.search(sender_addr) or bounce_subj.search(subject):
        b = rules.parse_bounce(subject, msg.get("body_plain") or "")
        return {"category": "bounce", "bounce": b, "source": "rule"}
    text = _reply_text(msg)
    if ooo_subj.search(subject) or re.search(r"\b(out of (the )?office|on (annual )?leave|away from (my|the) (desk|office))\b",
                                             text[:400], re.I):
        ret = rules.ooo_return_date(text or subject, received)
        return {"category": "out_of_office", "return_date": ret.isoformat() if ret else None, "source": "rule"}

    sig = rules.signals(f"{subject}\n{text}")
    if sender["type"] == "vendor":
        # A vendor's quote/bid is our purchasing, never a client RFQ (3.3.2);
        # bids on our requests are parsed by the vendor module (3.7a.4).
        return {"category": "other", "vendor_mail": True,
                "vendor_quote": bool(sig["rfq"] or sig["has_spec"]), "source": "rule"}
    if sender["type"] == "client":
        if sig["confirmation"]:
            return {"category": "confirmation", "source": "rule"}
        if sig["redirect_request"]:
            return {"category": "redirect_request", "source": "rule"}
        if sig["rfq"]:
            return {"category": "rfq", "source": "rule"}
    tgt = rules.transfer_target(text, OWN_DOMAINS, sender_addr)
    if tgt:
        return {"category": "neutral", "neutral_subtype": "transferred", "transfer_to": tgt, "source": "rule"}
    rc = rules.reconnect_date(text, received)
    from sales.reply_triage import rule_verdict
    rv = rule_verdict(text) or {}
    if rv.get("verdict") == "negative":
        company = bool(re.search(r"\b(we|our (company|team|organi[sz]ation))\b.{0,40}\b(not interested|no need|don'?t need|do not need)\b",
                                 text, re.I))
        return {"category": "negative", "company_wide_decline": company, "reason": rv.get("reason"), "source": "rule"}
    if rc:
        return {"category": "neutral", "neutral_subtype": "reconnect_later", "follow_up_on": rc.isoformat(), "source": "rule"}
    if rv.get("verdict") == "auto_reply":
        return {"category": "out_of_office", "return_date": None, "source": "rule"}
    if rv.get("verdict") == "positive":
        return {"category": "positive", "wants": [], "reason": rv.get("reason"), "source": "rule"}

    if model is None:
        return {"category": "other", "source": "rule", "reason": "no rule matched; model not run"}

    def check(data, clean):
        problems = []
        c = data.get("category")
        if c == "rfq" and not sig["has_spec"]:
            problems.append("model says rfq but the mail has no spec (N/LOI/IR/TG)")
        if c in ("rfq", "confirmation") and sender["type"] != "client":
            problems.append(f"{c} from a {sender['type']} sender: only client mail can create/update a client RFQ")
        if c == "confirmation" and not sig["confirmation"]:
            problems.append("model says confirmation but no award/go-ahead/PO language")
        return problems

    res = model(task="reply_classification", system=f"{REPLY_SYSTEM}\nSender type: {sender['type']}",
                subject=subject, body=text, schema=REPLY_SCHEMA, code_check=check,
                ref={"collection": "torpedo_gmail.email_metadata", "id": str(msg.get("_id"))})
    if res.get("status") == "ok":
        d = res["data"]
        out = {"category": d["category"], "source": "model", "wants": d.get("wants") or []}
        if d["category"] == "neutral":
            out["neutral_subtype"] = d.get("neutral_subtype") or "other"
        if d["category"] == "negative":
            out["company_wide_decline"] = bool(d.get("company_wide_decline"))
        return out
    return {"category": "other", "source": f"model {res.get('status')}", "review_item": res.get("review_item")}


# ------------------------------------------------------------------ 4 plan
def plan_actions(msg: Dict[str, Any], linked: Dict[str, Any], sender: Dict[str, Any],
                 cat: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What should happen. Executed only in live mode; recorded always."""
    c = cat["category"]
    sender_addr = (msg.get("from_email") or "").lower()
    lead = linked.get("outreach_lead_id")
    acts: List[Dict[str, Any]] = []
    if lead and c not in ("bounce", "out_of_office"):
        acts.append({"type": "stop_sequence", "outreach_lead_id": lead, "why": "any reply stops the sequence"})
    if c == "bounce":
        b = cat["bounce"]
        rcpt = b.get("recipient")
        if b["kind"] == "hard":
            acts.append({"type": "skrapp_refind", "email": rcpt, "why": f"hard bounce {b.get('code') or ''}".strip()})
            acts.append({"type": "suppress", "email": rcpt, "reason": "bounced",
                         "why": "removed unless Skrapp finds a different verified address"})
        else:
            acts.append({"type": "soft_bounce_retry", "email": rcpt, "retry_after_hours": 24, "max_retries": 2})
    elif c == "negative":
        acts.append({"type": "suppress", "email": sender_addr, "reason": "unsubscribed", "why": "contact declined -> DND"})
        if cat.get("company_wide_decline"):
            acts.append({"type": "account_dnd", "domain": _domain(sender_addr), "why": "company-wide decline"})
    elif c == "positive":
        acts.append({"type": "review", "review_type": "positive_reply_draft",
                     "why": "positive reply: draft answer from BU templates for approval", "wants": cat.get("wants")})
    elif c == "neutral":
        sub = cat.get("neutral_subtype")
        if sub == "transferred":
            acts.append({"type": "review", "review_type": "neutral_reply",
                         "why": f"transferred to {cat.get('transfer_to')}: create contact + intro mail (draft)",
                         "transfer_to": cat.get("transfer_to")})
        elif sub == "reconnect_later":
            acts.append({"type": "pause_sequence", "outreach_lead_id": lead, "until": cat.get("follow_up_on"),
                         "why": "reconnect later"})
        else:
            acts.append({"type": "review", "review_type": "neutral_reply", "why": "neutral reply"})
    elif c == "out_of_office":
        ret = cat.get("return_date")
        until = rules.next_working_day(datetime.fromisoformat(ret).date()).isoformat() if ret else None
        if lead:
            acts.append({"type": "pause_sequence", "outreach_lead_id": lead,
                         "until": until or (datetime.utcnow().date() + timedelta(days=7)).isoformat(),
                         "why": "out of office" + ("" if ret else " (no return date: 7 days)")})
    elif c in ("rfq", "confirmation", "redirect_request"):
        if sender["type"] == "client":
            acts.append({"type": "event", "event": {"rfq": "rfq_received", "confirmation": "rfq_confirmed",
                                                     "redirect_request": "redirect_requested"}[c],
                         "why": f"hand to {'RFQ handling (3.4)' if c != 'redirect_request' else 'Operations (3.6.3)'}"})
        else:
            acts.append({"type": "review", "review_type": "other", "why": f"{c} from a {sender['type']} sender"})
    if sender["type"] == "client":
        # client PO numbers ("PO", "Purchase Order", "PO No") go on the RFQ, project and quotation
        # so the Zoho invoice that quotes the PO links automatically
        pos = rules.po_numbers(msg.get("body_plain") or msg.get("snippet") or "")
        if pos:
            acts.append({"type": "set_po", "po_numbers": pos, "rfq_id": linked.get("rfq_id"),
                         "project_id": linked.get("project_id"), "gmail_thread_id": msg.get("gmail_thread_id"),
                         "why": f"client PO {', '.join(pos)} in mail"})
    if sender["type"] == "unknown":
        acts.append({"type": "review", "review_type": "ai_low_confidence", "why": "sender type unknown"})
    return acts


# ------------------------------------------------------------------ batch
def process(msg: Dict[str, Any], db: Dict[str, Any], ctx: Any, model: Optional[Any], bounce_patterns) -> Dict[str, Any]:
    linked = link(msg, db)
    snd = sender_type(msg, linked, ctx, db, model)
    if snd["type"] == "internal":
        cat = {"category": "other", "source": "rule", "reason": "internal mail"}
    else:
        cat = categorize(msg, snd, model, bounce_patterns)
    return {"message_id": str(msg.get("_id")), "gmail_message_id": msg.get("gmail_message_id"),
            "gmail_thread_id": msg.get("gmail_thread_id"), "received_at": msg.get("timestamp"),
            "link": linked, "sender": snd, "category": cat, "actions": plan_actions(msg, linked, snd, cat)}
