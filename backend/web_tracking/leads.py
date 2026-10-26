"""Website enquiry -> CRM lead (CRM plan 3.12 step 3 / owner 2026-10-24).

One submission from a company site:
  spam gates   honeypot field (website_url) must be empty, the form must
               have taken a human amount of time; per-IP rate limit is on
               the route
  dedupe       same email -> the existing CRM lead (updated, not duplicated);
               an existing contact or account is linked by email / domain
  bucketing    BU = the site's BU (the visitor chose that company); an
               account already owned by another BU is flagged in the review
  review       one Review Queue item "inbound_lead" with a draft reply
               (client-facing: a person approves it before anything is sent)
"""
import re
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from bson import ObjectId

from web_tracking.rules import CLICK_IDS, attribution

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$", re.I)
MIN_HUMAN_MS = 1500
REPEAT_MERGE_SECONDS = 600       # same email + site within 10 min = the same enquiry
FREE = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com", "rediffmail.com", "yahoo.co.in"}

DRAFTS = {
    "SFW": "Hi {first},\n\nThank you for reaching out to Survey Fieldwork. I'd be glad to help with {topic}. "
           "Could you share the target audience, countries, sample size and timeline? We'll come back with feasibility and a cost.\n\nBest regards,",
    "COGENTIX": "Hi {first},\n\nThank you for contacting Cogentix Research about {topic}. "
                "Would you have 20 minutes this week to walk us through the objectives? Happy to share relevant case studies.\n\nBest regards,",
    "BIM": "Hi {first},\n\nThank you for your enquiry about {topic}. "
           "Could you share the project type, drawings or scope and your timeline? We'll revert with an approach and estimate.\n\nBest regards,",
}


def _clean(v, n=300) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def capture(gd: Callable, body: Dict[str, Any], *, site: Dict[str, Any], ip: str, ua: str,
            contact_from_token: Optional[str], cfg: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    f = body.get("fields") if isinstance(body.get("fields"), dict) else {}
    if _clean(f.get("website_url") or f.get("website_hp")):
        return {"ok": True}                                  # honeypot: pretend success, write nothing
    if isinstance(body.get("elapsed_ms"), (int, float)) and 0 <= body["elapsed_ms"] < MIN_HUMAN_MS and not body.get("retried"):
        return {"ok": True}                                  # filled faster than a person can type
    email = _clean(f.get("email"), 200).lower()
    name = _clean(f.get("name"), 120)
    if not EMAIL_RE.match(email):
        return {"ok": False, "error": "a valid email is required"}
    message = str(f.get("message") or "")[:4000].strip()
    company = _clean(f.get("company"), 160)
    interest = _clean(f.get("interest") or f.get("service"), 120)
    bu = site["bu"]
    domain = email.rsplit("@", 1)[-1]
    crm, ea = gd("crm_db"), gd("email_automation")

    contact = crm["contacts"].find_one({"email": email}, {"account_id": 1}) or (
        crm["contacts"].find_one({"_id": ObjectId(contact_from_token)}, {"account_id": 1, "email": 1})
        if contact_from_token and ObjectId.is_valid(contact_from_token) else None)
    account = None
    if contact and contact.get("account_id") and ObjectId.is_valid(str(contact["account_id"])):
        account = crm["accounts"].find_one({"_id": ObjectId(str(contact["account_id"]))}, {"name": 1, "bu": 1})
    if not account and domain not in FREE:
        account = crm["accounts"].find_one({"domain": domain, "merged_into": {"$exists": False}}, {"name": 1, "bu": 1})

    submission = {"at": now, "site": site["domain"], "page": _clean(body.get("page"), 500), "form": _clean(body.get("form"), 80),
                  "referrer": _clean(body.get("referrer"), 300), "interest": interest, "message": message,
                  "utm": {k: _clean(v, 100) for k, v in (body.get("utm") or {}).items() if str(k).startswith("utm_")},
                  "visitor_id": _clean(body.get("v"), 64), "ip_prefix": _ip_prefix(ip), "ua": ua[:200],
                  "click_ids": {k: _clean(v, 200) for k, v in (body.get("click_ids") or {}).items() if k in CLICK_IDS and v},
                  "first_touch": attribution(body.get("first_touch")), "cookie_consent": bool(body.get("consent")),
                  "heard_from": _clean(f.get("heard_from") or f.get("how_did_you_hear"), 120) or None,
                  "optin": {"email": _yes(f.get("optin_email")), "whatsapp": _yes(f.get("optin_whatsapp"))}}
    existing = crm["leads"].find_one({"email": email}, {"_id": 1, "bu": 1, "web_submissions": 1})
    last = ((existing or {}).get("web_submissions") or [{}])[-1]
    if existing and isinstance(last.get("at"), datetime) and (now - last["at"]).total_seconds() < REPEAT_MERGE_SECONDS \
            and last.get("site") == site["domain"]:
        # a retry (wrong captcha, double click, queued resend): same enquiry, no second review item
        crm["leads"].update_one({"_id": existing["_id"]}, {"$set": {"updated_at": now}})
        return {"ok": True, "lead_id": str(existing["_id"]), "dedupe": "repeat_merged"}
    fields = {"name": name or None, "company": company or (account or {}).get("name"), "updated_at": now,
              "last_inbound_at": now, "status": "new"}
    if existing:
        lead_id = str(existing["_id"])
        crm["leads"].update_one({"_id": existing["_id"]}, {"$set": {k: v for k, v in fields.items() if v},
                                                           "$push": {"web_submissions": submission},
                                                           "$addToSet": {"bus": bu}})
        dedupe = "existing_lead"
    else:
        doc = {"email": email, **fields, "phone": _clean(f.get("phone"), 40) or None, "source": "website_form",
               "bu": bu, "bus": [bu], "outreach_bucket": {"SFW": "SFW", "COGENTIX": "COGENTIX_RESEARCH", "BIM": "BIM"}[bu],
               "outreach_bucket_method": "inbound_site", "intent": "positive_inbound", "created_at": now,
               "contact_id": str(contact["_id"]) if contact else None,
               "account_id": str(account["_id"]) if account else None, "web_submissions": [submission],
               "metadata": {"source": "website_form", "site": site["domain"], "message": message[:2000]}}
        lead_id = str(crm["leads"].insert_one(doc).inserted_id)
        dedupe = "contact" if contact else "account_domain" if account else "new"
    phone = _clean(f.get("phone"), 40)
    if submission["optin"]["whatsapp"] and phone:
        # recorded opt-in, kept permanently; the only basis for business-initiated WhatsApp (3.5.3)
        import hashlib
        digits = re.sub(r"\D", "", phone)
        ea["whatsapp_optins"].insert_one({"phone_hash": hashlib.sha256(digits.encode()).hexdigest(), "phone_last4": digits[-4:],
                                          "lead_id": lead_id, "contact_id": str(contact["_id"]) if contact else None,
                                          "bu": bu, "site": site["domain"], "page": submission["page"], "granted": True,
                                          "text": _clean(f.get("optin_whatsapp_text"), 300) or None,
                                          "source": "website_form", "at": now, "created_at": now, "updated_at": now})
    if submission["optin"]["email"]:
        crm["leads"].update_one({"_id": ObjectId(lead_id)}, {"$set": {"email_optin": {"granted": True, "at": now,
                                                                                       "source": "website_form"}}})
    if submission["visitor_id"]:
        ea["web_visitors"].update_one({"visitor_id": submission["visitor_id"]},
                                      {"$set": {"lead_id": lead_id, "form_email": email,
                                                **({"contact_id": str(contact["_id"])} if contact else {})}}, upsert=True)
    first = (name.split() or ["there"])[0]
    topic = interest or "your requirement"
    note = None
    if account and account.get("bu") and account["bu"] != bu:
        note = f"account is owned by {account['bu']}; enquiry came via the {bu} site"
    from platform_core import review_queue
    item = review_queue.enqueue(
        type="inbound_lead", module="web", bu=bu,
        ref={"collection": "crm_db.leads", "id": f"{lead_id}:{now:%Y%m%d%H%M%S}"},
        reason=f"Website enquiry ({site['domain']}): {name or email}" + (f" — {company}" if company else "") + (f" [{note}]" if note else ""),
        payload={"lead_id": lead_id, "email": email, "company": company, "interest": interest, "message": message[:1500],
                 "page": submission["page"], "utm": submission["utm"], "dedupe": dedupe,
                 "account_id": str(account["_id"]) if account else None},
        suggested={"to": email, "subject": f"Re: your enquiry{(' about ' + interest) if interest else ''}",
                   "body": DRAFTS[bu].format(first=first, topic=topic)})
    try:      # the same enquiry in the unified inbox (MARKETING_PLAN 3.7), carrying this review item and the SLA
        from marketing import inbox
        inbox.ingest(gd, channel="web_form", external_id=f"{lead_id}:{now:%Y%m%d%H%M%S}", bu=bu, text=message,
                     at=now, author={"name": name, "email": email}, kind="form", url=submission["page"],
                     sender_type="client", review_item=item)
    except Exception:
        pass
    try:
        from platform_core.audit import log_action
        log_action(actor="website", action="create", entity_type="lead", entity_id=lead_id,
                   reason=f"website enquiry via {site['domain']} ({dedupe})", source="web_form")
    except Exception:
        pass
    return {"ok": True, "lead_id": lead_id, "dedupe": dedupe, "review_item": item}


def _yes(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "on", "yes", "y")


def _ip_prefix(ip: str) -> Optional[str]:
    from web_tracking.rules import ip_prefix
    return ip_prefix(ip)
