"""Unified inbox (MARKETING_PLAN 3.7, 3.5.3, 6.3).

One inbox_items row per inbound message: website form, LinkedIn / Facebook /
Instagram comment or DM, WhatsApp message, lead-form lead. Each is
  linked     deterministically to a lead / contact (email, phone hash, known handle)
  classified with the mail pipeline's own rules + Qwen (CRM 3.3), plus social rules:
             positive / negative / neutral / rfq / spam / support / other, with sender type
  timed      SLA due_at in working hours (config marketing.sla_working_hours; leads 1 h,
             comments 4 h); breaches feed Needs attention
  answered   a drafted reply goes to the Review Queue ("inbox_reply"); auto-reply only for
             categories the owner switched on (marketing.inbox_auto_reply), and only in live
WhatsApp: STOP / unsubscribe records an opt-out; business-initiated messages need a
recorded opt-in AND either the 24-hour service window or an approved template; the
cross-channel cap (1 automated touch per person per day, 4.3) counts mail too.
"""
import hashlib
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from marketing import schema

CHANNELS = ("web_form", "linkedin_comment", "linkedin_dm", "linkedin_lead_form", "facebook_comment", "messenger",
            "instagram_comment", "instagram_dm", "facebook_lead_ad", "whatsapp")
LEAD_CHANNELS = {"web_form", "linkedin_lead_form", "facebook_lead_ad", "linkedin_dm", "messenger", "instagram_dm", "whatsapp"}
CATEGORIES = ("positive", "negative", "neutral", "rfq", "spam", "support", "other")
_SPAM = re.compile(r"\b(crypto|bitcoin|forex|casino|loan offer|seo services?|backlinks?|web ?design services|"
                   r"guest post|whatsapp me for|dm me for|make money|earn \$|promote your page|followers)\b|https?://\S+.*https?://\S+", re.I)
_SUPPORT = re.compile(r"\b(not received|haven'?t received|didn'?t get|pending payment|reward|points|redeem|redemption|incentive|"
                      r"voucher|gift card|survey (link|not working|closed)|disqualified|screened out|account (blocked|locked)|"
                      r"complain(t)?|refund)\b", re.I)
_PANELIST = re.compile(r"\b(survey|surveys|reward|points|redeem|panel(ist)?|incentive|disqualified|screened out)\b", re.I)
_STOP = re.compile(r"^\s*(stop|unsubscribe|opt ?out|remove me|band karo|stop messages?)\s*[.!]*\s*$", re.I)
_THANKS = re.compile(r"^\s*(thanks?|thank you|thx|great|nice|congrats|congratulations|👍|🙏|👏)[\s!.]*$", re.I)

REPLY_TEMPLATES = {
    ("SFW", "support"): "Hi {first}, thanks for writing to us. Please send your registered email and the survey ID so the "
                        "panel team can check this; we reply within one working day.",
    ("SFW", "positive"): "Hi {first}, thanks for reaching out to Survey Fieldwork. Could you share the audience, countries, "
                         "sample size and timeline? We'll come back with feasibility and a cost.",
    ("COGENTIX", "positive"): "Hi {first}, thank you for contacting Cogentix Research. Would you have 20 minutes this week "
                              "to walk us through the objectives?",
    ("BIM", "positive"): "Hi {first}, thank you for your interest. Could you share the project type, drawings or scope and "
                         "your timeline? We'll revert with an approach and estimate.",
    ("*", "rfq"): "Hi {first}, thank you for the brief. We're reviewing it and will come back with feasibility and a quote "
                  "within the day.",
    ("*", "neutral"): "Thanks, {first}. Noted.",
    ("*", "other"): "Hi {first}, thanks for your message. A member of our team will get back to you shortly.",
}


def phone_hash(phone: str) -> Optional[str]:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 8:
        return None
    if len(digits) == 10:
        digits = "91" + digits                       # Indian mobile without country code
    return hashlib.sha256(digits.encode()).hexdigest()


def working_due(start: datetime, hours: float, wh: Tuple[int, int] = (10, 18)) -> datetime:
    """SLA due time counting only working hours Mon-Fri, wh in IST. Times are UTC naive."""
    ist = timedelta(hours=5, minutes=30)
    t, left = start + ist, timedelta(hours=hours)
    while left > timedelta(0):
        day_start, day_end = t.replace(hour=wh[0], minute=0, second=0, microsecond=0), t.replace(hour=wh[1], minute=0, second=0, microsecond=0)
        if t.weekday() >= 5 or t >= day_end:
            t = (t + timedelta(days=1)).replace(hour=wh[0], minute=0, second=0, microsecond=0)
            continue
        if t < day_start:
            t = day_start
        step = min(left, day_end - t)
        t, left = t + step, left - step
    return t - ist


def classify(text: str, *, sender_type: str = "other", channel: str = "", model=None, subject: str = "") -> Dict[str, Any]:
    t = (text or "").strip()
    if not t:
        return {"category": "other", "sender_type": sender_type, "source": "rule"}
    if channel == "whatsapp" and _STOP.match(t):
        return {"category": "negative", "opt_out": True, "sender_type": sender_type, "source": "rule"}
    if _SPAM.search(t):
        return {"category": "spam", "sender_type": "other", "source": "rule"}
    if _PANELIST.search(t) and sender_type in ("other", "panelist") and _SUPPORT.search(t):
        return {"category": "support", "sender_type": "panelist", "source": "rule"}
    if _SUPPORT.search(t) and channel.endswith("_comment"):
        return {"category": "support", "sender_type": sender_type, "source": "rule"}
    if _THANKS.match(t):
        return {"category": "neutral", "subtype": "thanks", "sender_type": sender_type, "source": "rule"}
    try:
        from mail_pipeline import pipeline
        cat = pipeline.categorize({"subject": subject, "body_plain": t, "from_email": "", "timestamp": datetime.utcnow()},
                                  {"type": "client" if sender_type == "client" else "other"}, model=model,
                                  bounce_patterns=(re.compile(r"$^"), re.compile(r"$^"), re.compile(r"$^")))
    except Exception as e:
        return {"category": "other", "sender_type": sender_type, "source": f"rule (pipeline unavailable: {str(e)[:60]})"}
    c = cat.get("category")
    mapped = {"positive": "positive", "negative": "negative", "neutral": "neutral", "rfq": "rfq", "confirmation": "positive",
              "redirect_request": "support", "out_of_office": "neutral"}.get(c, "other")
    return {"category": mapped, "pipeline_category": c, "sender_type": sender_type, "source": cat.get("source"),
            "wants": cat.get("wants")}


def link(gd: Callable, author: Dict[str, Any]) -> Dict[str, Optional[str]]:
    crm, ea = gd("crm_db"), gd(schema.DB)
    email = (author.get("email") or "").strip().lower() or None
    ph = phone_hash(author.get("phone") or "")
    lead = crm["leads"].find_one({"email": email}, {"_id": 1, "contact_id": 1, "account_id": 1}) if email else None
    contact = crm["contacts"].find_one({"email": email}, {"_id": 1, "account_id": 1}) if email else None
    if not lead and ph:
        opt = ea["whatsapp_optins"].find_one({"phone_hash": ph, "lead_id": {"$ne": None}})
        if opt:
            lead = {"_id": opt["lead_id"], "contact_id": opt.get("contact_id")}
    if not lead and author.get("handle"):
        prev = ea["inbox_items"].find_one({"author.handle": author["handle"], "channel": author.get("channel"), "lead_id": {"$ne": None}})
        if prev:
            lead = {"_id": prev["lead_id"], "contact_id": prev.get("contact_id")}
    return {"lead_id": str(lead["_id"]) if lead else None,
            "contact_id": str((contact or {}).get("_id") or (lead or {}).get("contact_id") or "") or None,
            "account_id": str((contact or {}).get("account_id") or (lead or {}).get("account_id") or "") or None,
            "phone_hash": ph}


def ingest(gd: Callable, *, channel: str, external_id: str, bu: Optional[str], text: str, at: Optional[datetime] = None,
           author: Optional[Dict[str, Any]] = None, kind: str = "message", thread_id: Optional[str] = None,
           url: Optional[str] = None, sender_type: str = "other", model=None, review_item: Optional[str] = None,
           cfg: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Idempotent per (channel, external_id). Returns the stored item."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    now = now or datetime.utcnow()
    at = at or now
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    ea = gd(schema.DB)
    col = ea["inbox_items"]
    existing = col.find_one({"channel": channel, "external_id": external_id})
    if existing:
        return existing
    author = dict(author or {}, channel=channel)
    links = link(gd, author)
    cls = classify(text, sender_type=sender_type, channel=channel, model=model)
    sla = cfg.get("sla_working_hours") or {}
    hours = sla.get("lead", 1) if (channel in LEAD_CHANNELS and cls["category"] in ("positive", "rfq", "other")) else sla.get("comment", 4)
    from platform_core import config_store as _cs
    try:
        wh = tuple(_cs.get("mail").get("working_hours_ist") or (10, 18))
    except Exception:
        wh = (10, 18)
    status = "spam" if cls["category"] == "spam" else "open"
    doc = {"channel": channel, "external_id": external_id, "kind": kind, "thread_id": thread_id, "url": url,
           "author": {k: v for k, v in author.items() if k in ("name", "handle", "channel")},     # no raw email / phone stored here
           "text": (text or "")[:4000], "at": at, **{k: v for k, v in links.items()}, **{k: cls.get(k) for k in ("category", "sender_type", "wants")},
           "classified_by": cls.get("source"), "status": status,
           "due_at": None if status == "spam" else working_due(at, hours, wh), "sla_hours": hours, "review_item": review_item}
    if cls.get("opt_out") and links["phone_hash"]:
        ea["whatsapp_optins"].insert_one(schema.stamp({"phone_hash": links["phone_hash"], "granted": False, "lead_id": links["lead_id"],
                                                       "contact_id": links["contact_id"], "text": text[:120], "at": now},
                                                      bu=bu if bu in schema.BUS else None, source="whatsapp_stop", now=now))
        doc["status"] = "closed"
        doc["closed_reason"] = "opt-out recorded"
    doc = schema.stamp(doc, bu=bu if bu in schema.BUS else None, source=channel, now=now)
    doc["_id"] = col.insert_one(doc).inserted_id
    if doc["status"] == "open" and not review_item and cls["category"] not in ("negative",):
        draft = draft_reply(doc)
        auto = cls["category"] in (cfg.get("inbox_auto_reply") or []) and cfg.get("mode") == "live"
        if draft and not auto:
            from platform_core import review_queue
            item = review_queue.enqueue(type="inbox_reply", module="marketing", bu=doc.get("bu"),
                                        ref={"collection": "email_automation.inbox_items", "id": str(doc["_id"])},
                                        reason=f"{channel} {cls['category']} from {author.get('name') or author.get('handle') or 'someone'}"
                                               f" — reply due {doc['due_at']:%d %b %H:%M} UTC",
                                        payload={"text": doc["text"][:1500], "channel": channel, "category": cls["category"],
                                                 "lead_id": links["lead_id"], "url": url},
                                        suggested={"reply": draft}, resume={"handler": "inbox_reply", "ref": {"inbox_id": str(doc["_id"])}})
            col.update_one({"_id": doc["_id"]}, {"$set": {"review_item": item, "draft": draft}})
            doc["review_item"] = item
    return doc


def draft_reply(item: Dict[str, Any]) -> Optional[str]:
    cat = item.get("category")
    if cat in ("spam", "negative"):
        return None
    if cat == "neutral" and item.get("channel", "").endswith("_comment"):
        return None                                  # a "thanks" comment needs no reply
    tpl = REPLY_TEMPLATES.get((item.get("bu"), cat)) or REPLY_TEMPLATES.get(("*", cat)) or REPLY_TEMPLATES[("*", "other")]
    first = ((item.get("author") or {}).get("name") or "there").split()[0]
    return tpl.format(first=first)


def mark_replied(gd: Callable, inbox_id: str, *, by: str, now: Optional[datetime] = None) -> None:
    from bson import ObjectId
    now = now or datetime.utcnow()
    col = gd(schema.DB)["inbox_items"]
    it = col.find_one({"_id": ObjectId(inbox_id)})
    if it:
        col.update_one({"_id": it["_id"]}, {"$set": {"status": "replied", "replied_at": now, "replied_by": by,
                                                     "response_minutes": int((now - it["at"]).total_seconds() // 60),
                                                     "sla_met": bool(it.get("due_at")) and now <= it["due_at"], "updated_at": now}})


def sla_breaches(gd: Callable, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.utcnow()
    return list(gd(schema.DB)["inbox_items"].find({"status": "open", "due_at": {"$lt": now}}))


# ------------------------------------------------------------------ WhatsApp send gate (3.5.3) + contact cap (4.3)
def whatsapp_can_send(gd: Callable, phone: str, *, template: Optional[str] = None, bu: Optional[str] = None,
                      now: Optional[datetime] = None) -> Tuple[bool, str]:
    now = now or datetime.utcnow()
    ph = phone_hash(phone)
    if not ph:
        return False, "no valid phone number"
    ea = gd(schema.DB)
    latest = ea["whatsapp_optins"].find({"phone_hash": ph}).sort("at", -1).limit(1)
    latest = list(latest)
    if latest and latest[0].get("granted") is False:
        return False, "opted out"
    last_in = ea["inbox_items"].find_one({"channel": "whatsapp", "phone_hash": ph, "at": {"$gte": now - timedelta(hours=24)}})
    if last_in:
        return True, "inside the 24-hour service window"
    if not latest:
        return False, "no recorded WhatsApp opt-in (never cold WhatsApp)"
    if not template:
        return False, "outside the 24-hour window: only an approved template may be sent"
    tpl = ea["whatsapp_templates"].find_one({"name": template, "status": "approved", **({"bu": bu} if bu else {})})
    if not tpl:
        return False, f"template {template!r} is not approved by Meta"
    return True, "opt-in + approved template"


def contact_cap_ok(gd: Callable, *, lead_id: Optional[str] = None, email: Optional[str] = None,
                   phone: Optional[str] = None, now: Optional[datetime] = None, cfg: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """At most N automated touches per person per day across mail, WhatsApp and social DMs."""
    now = now or datetime.utcnow()
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    cap = int(cfg.get("contact_cap_per_day", 1))
    ors = [q for q in ({"lead_id": lead_id} if lead_id else None, {"email": (email or "").lower()} if email else None,
                       {"phone_hash": phone_hash(phone)} if phone and phone_hash(phone) else None) if q]
    n = gd(schema.DB)["marketing_touches"].count_documents({"$or": ors, "automated": True, "status": {"$ne": "shadow"},   # shadow never reached anyone
                                                          "at": {"$gte": now - timedelta(hours=24)}}) if ors else 0
    if email:
        try:
            from messaging import facade
            if facade._throttle_block(email.lower(), "nurture"):
                n += 1
        except Exception:
            pass
    return (n < cap, f"{n} automated touch(es) in 24 h (cap {cap})")


_SENDERS: Dict[str, Callable[[Dict[str, Any], str], Dict[str, Any]]] = {}


def register_sender(channel: str, fn: Callable[[Dict[str, Any], str], Dict[str, Any]]) -> None:
    """A platform integration registers fn(inbox_item, text) -> {"id": ...} that posts the reply."""
    _SENDERS[channel] = fn


def send_approved(gd: Callable, inbox_id: str, text: str, *, by: str, cfg: Optional[Dict[str, Any]] = None,
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """An approved reply: sent by the channel's sender when live (mode + action_modes['reply:<channel>']),
    otherwise kept as approved_waiting_sender (the person replies on the platform and marks it replied)."""
    from bson import ObjectId
    now = now or datetime.utcnow()
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    col = gd(schema.DB)["inbox_items"]
    it = col.find_one({"_id": ObjectId(inbox_id)})
    if not it:
        return {"ok": False, "error": "inbox item not found"}
    sender = _SENDERS.get(it["channel"])
    live = cfg.get("mode") == "live" and (cfg.get("action_modes") or {}).get(f"reply:{it['channel']}") == "live"
    upd = {"approved_reply": text, "approved_by": by, "updated_at": now}
    if not (sender and live):
        upd["reply_status"] = "approved_waiting_sender"
        col.update_one({"_id": it["_id"]}, {"$set": upd})
        return {"ok": True, "sent": False, "why": "shadow" if not live else f"no sender for {it['channel']}"}
    try:
        res = sender(it, text)
        upd.update(reply_status="sent", reply_platform_id=(res or {}).get("id"))
        col.update_one({"_id": it["_id"]}, {"$set": upd})
        return {"ok": True, "sent": True}
    except Exception as e:
        upd.update(reply_status="send_failed", reply_error=str(e)[:200])
        col.update_one({"_id": it["_id"]}, {"$set": upd})
        return {"ok": False, "error": str(e)[:200]}


def _resume(item: Dict[str, Any], decision: Dict[str, Any]):
    """Review approve -> send the approved text when that channel is live, else record it as waiting."""
    inbox_id = (item.get("resume") or {}).get("ref", {}).get("inbox_id")
    if not inbox_id:
        return None
    from database import get_database
    return send_approved(get_database, inbox_id, (decision.get("value") or {}).get("reply") or "", by=decision.get("by") or "reviewer")


try:
    from platform_core import review_queue as _rq
    _rq.register_handler("inbox_reply", _resume)
except Exception:      # pragma: no cover
    pass


def sync_review_status(gd: Optional[Callable] = None, now: Optional[datetime] = None) -> Dict[str, int]:
    """Open items whose Review item was decided: approved / corrected = replied (that is when the reply goes out),
    rejected = closed without reply. Feeds response time vs SLA."""
    if gd is None:
        from database import get_database as gd
    from bson import ObjectId
    ea = gd(schema.DB)
    out = {"replied": 0, "closed": 0}
    for it in ea["inbox_items"].find({"status": "open", "review_item": {"$ne": None}}):
        rid = it.get("review_item")
        ri = ea["review_queue_items"].find_one({"_id": ObjectId(rid)}) if rid and ObjectId.is_valid(str(rid)) else None
        if not ri or ri.get("status") == "pending":
            continue
        if ri["status"] in ("approved", "corrected"):
            mark_replied(gd, str(it["_id"]), by=ri.get("resolved_by") or "reviewer", now=ri.get("resolved_at") or now)
            out["replied"] += 1
        elif ri["status"] == "rejected":
            ea["inbox_items"].update_one({"_id": it["_id"]}, {"$set": {"status": "closed", "closed_reason": "review rejected",
                                                                      "updated_at": now or datetime.utcnow()}})
            out["closed"] += 1
    return out
