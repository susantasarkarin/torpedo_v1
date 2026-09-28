"""
RFQs built from the mail pool by rules (owner decision 2026-09-28).

The RFQ section had been filled by a bulk AI backfill that turned years of old
mail -- introductions, payment chases, partnership pitches -- into ~13,600
opportunities, 1,515 of them "won" by the model's say-so. It was cleared and
rebuilt from this module (scripts/rfq_reset_rebuild.py).

An RFQ is a thread a client opened with us asking for a quote:
  * the thread's first message is inbound (they asked us -- we open RFQ
    threads with suppliers, and those are purchasing, not sales);
  * that first inbound message is labelled rfq by mail segregation and its
    sender is on the client side (mail_party "client": a client, a prospect,
    or a both-ways company in a thread they opened);
  * one RFQ per thread; the same request arriving twice (our [SFW-BCC] copy,
    a resend) within DEDUP_DAYS from the same company is folded into the
    first.
Mail older than OPEN_DAYS goes in as closed history ("outcome not
recorded"); newer mail is open. Nothing is ever marked won here -- a person
does that. The local model fills the study details (LOI, IR, sample size,
country...) for open RFQs, a few per cycle.
"""
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services import mail_categorizer as mc

logger = logging.getLogger(__name__)

SOURCE = "mail_rules"
OPEN_DAYS = 60
DEDUP_DAYS = 14
_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|sv|antw)\s*:\s*|\[[^\]]{1,40}\]\s*)+", re.I)


def clean_title(subject: Optional[str]) -> str:
    return (_PREFIX.sub("", subject or "").strip() or "RFQ")[:150]


def _openers(em, thread_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(thread_ids), 5000):
        for t in em.aggregate([
                {"$match": {"gmail_thread_id": {"$in": thread_ids[i:i + 5000]}}},
                {"$sort": {"timestamp": 1}},
                {"$group": {"_id": "$gmail_thread_id", "dir": {"$first": "$direction"},
                            "first_id": {"$first": "$_id"}}}], allowDiskUse=True):
            out[t["_id"]] = t
    return out


def candidates(client, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The first inbound RFQ message of each client-opened thread, oldest first."""
    em = client["torpedo_gmail"]["email_metadata"]
    match: Dict[str, Any] = {"direction": "inbound", "ai_tier1_category": "rfq", "mail_party": "client",
                             "gmail_thread_id": {"$nin": [None, ""]}}
    if since:
        match["timestamp"] = {"$gte": since}
    firsts = list(em.aggregate([
        {"$match": match}, {"$sort": {"timestamp": 1}},
        {"$group": {"_id": "$gmail_thread_id", "mid": {"$first": "$_id"}}}], allowDiskUse=True))
    openers = _openers(em, [f["_id"] for f in firsts])
    keep = [f["mid"] for f in firsts if (openers.get(f["_id"]) or {}).get("dir") == "inbound"]
    docs = []
    for i in range(0, len(keep), 2000):
        docs.extend(em.find({"_id": {"$in": keep[i:i + 2000]}},
                            {"subject": 1, "from_email": 1, "from_name": 1, "timestamp": 1, "gmail_thread_id": 1,
                             "mail_summary": 1, "mailbox_id": 1, "cc_emails": 1}))
    docs.sort(key=lambda d: d.get("timestamp") or datetime.min)
    return docs


def _account_for(crm_service, accounts_col, email: str) -> Dict[str, Any]:
    domain = mc._domain(email)
    if domain and domain not in mc.WEBMAIL:
        acc = accounts_col.find_one({"website": {"$regex": re.escape(domain) + "$", "$options": "i"}})
        if acc:
            return {"_id": str(acc["_id"]), "name": acc.get("name")}
        root = domain.split(".")[0].replace("-", " ").title()
        acc, _ = crm_service.get_or_create_account(root, {"website": domain})
        return acc
    acc, _ = crm_service.get_or_create_account(email, {})
    return acc


def build(client, since: Optional[datetime] = None, now: Optional[datetime] = None,
          limit: Optional[int] = None) -> Dict[str, int]:
    """Create RFQs for candidate threads that do not have one yet. Idempotent."""
    from bson import ObjectId
    from app.services import crm_service
    now = now or datetime.utcnow()
    em = client["torpedo_gmail"]["email_metadata"]
    opp = client["crm_db"]["opportunities"]
    accounts_col = client["crm_db"]["accounts"]
    have = set(opp.distinct("metadata.rfq.gmail_thread_id", {"metadata.rfq.source": SOURCE}))
    recent: Dict[str, List[Dict[str, Any]]] = {}   # dedup key -> [(ts, opp id)]
    stats = {"candidates": 0, "created": 0, "open": 0, "closed_history": 0, "folded_duplicates": 0,
             "already_built": 0}
    for doc in candidates(client, since):
        if limit and stats["created"] >= limit:
            break
        stats["candidates"] += 1
        tid = doc["gmail_thread_id"]
        if tid in have:
            stats["already_built"] += 1
            continue
        sender = (doc.get("from_email") or "").strip().lower()
        ts = doc.get("timestamp") or now
        key = f"{mc._domain(sender)}|{mc.normalize_subject(doc.get('subject'))}"
        earlier = next((r for r in recent.get(key, []) if abs((ts - r["ts"]).days) <= DEDUP_DAYS), None)
        if earlier is None:
            prior = opp.find_one({"metadata.rfq.source": SOURCE, "metadata.rfq.dedup_key": key,
                                  "metadata.rfq.received_at": {"$gte": ts - timedelta(days=DEDUP_DAYS),
                                                               "$lte": ts + timedelta(days=DEDUP_DAYS)}},
                                 {"_id": 1})
            if prior:
                earlier = {"ts": ts, "id": str(prior["_id"])}
        if earlier:
            opp.update_one({"_id": ObjectId(earlier["id"])},
                           {"$addToSet": {"metadata.rfq.source_emails": str(doc["_id"]),
                                          "metadata.rfq.gmail_thread_ids": tid}})
            em.update_one({"_id": doc["_id"]}, {"$set": {"rfq_id": earlier["id"], "rfq_synced": True,
                                                         "rfq_source": SOURCE}})
            have.add(tid)
            stats["folded_duplicates"] += 1
            continue
        account = _account_for(crm_service, accounts_col, sender)
        contact, _ = crm_service.get_or_create_contact(sender, {"name": doc.get("from_name") or "",
                                                                "account_id": account["_id"]})
        summary = doc.get("mail_summary") or ""
        res = crm_service.create_rfq({
            "title": clean_title(doc.get("subject")), "account_id": account["_id"],
            "contact_id": contact["_id"], "budget": 0, "currency": None,
            "description": summary, "ai_summary": summary, "summary": summary,
            "received_at": ts, "source_email_id": str(doc["_id"]), "source_emails": [str(doc["_id"])],
            "gmail_thread_id": tid, "gmail_thread_ids": [tid], "mailbox_id": doc.get("mailbox_id"),
            "from_email": sender, "from_name": doc.get("from_name"), "contact_email": sender,
            "account_name": account.get("name"), "direction": "inbound", "source": SOURCE,
            "dedup_key": key})
        oid = res["opportunity"]["_id"]
        is_history = ts < now - timedelta(days=OPEN_DAYS)
        update = {"created_at": ts}
        if is_history:
            update.update(status="closed", closed_at=now, closed_by="rfq_from_mail",
                          closed_reason=f"historical RFQ (mail older than {OPEN_DAYS} days) -- outcome not recorded")
            stats["closed_history"] += 1
        else:
            stats["open"] += 1
        opp.update_one({"_id": ObjectId(oid)}, {"$set": update})
        em.update_one({"_id": doc["_id"]}, {"$set": {"rfq_id": oid, "rfq_synced": True, "rfq_source": SOURCE}})
        recent.setdefault(key, []).append({"ts": ts, "id": oid})
        have.add(tid)
        stats["created"] += 1
    return stats


# ---------------------------------------------------------------------------
# study details for open RFQs -- the local model, a few per cycle
# ---------------------------------------------------------------------------
_DETAIL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "methodology": {"type": "string", "maxLength": 60},
        "country": {"type": "string", "maxLength": 80},
        "target_audience": {"type": "string", "maxLength": 120},
        "sample_size": {"type": ["integer", "null"]},
        "loi": {"type": ["integer", "null"]},
        "ir": {"type": ["integer", "null"]},
        "deadline": {"type": "string", "maxLength": 40},
        "budget": {"type": ["number", "null"]},
        "currency": {"type": "string", "maxLength": 3},
    },
    "required": ["methodology", "country", "target_audience", "sample_size", "loi", "ir", "deadline",
                 "budget", "currency"],
}
_DETAIL_SYSTEM = ("You read a market-research RFQ email and pull out the study details. Use only what "
                  "the email states; empty string or null when it does not say. loi = interview length "
                  "in minutes, ir = incidence rate in percent, sample_size = number of completes. "
                  "JSON only.")


_FILLER = re.compile(r"^\s*(not (specified|mentioned|stated|provided|available)|n/?a|none|unknown|tbd|-)\s*$", re.I)
_METHODS = ("online", "cati", "capi", "cawi", "f2f", "face to face", "face-to-face", "idi", "idis", "fgd", "fgds",
            "focus group", "in-depth", "panel", "qualitative", "quantitative", "clt", "hut", "mystery",
            "telephonic", "phone", "b2b", "b2c")
_METHOD_LABEL = {"online": "Online", "panel": "Panel", "phone": "Phone", "telephonic": "Telephonic",
                 "face to face": "Face-to-face", "face-to-face": "Face-to-face", "idis": "IDI", "fgds": "FGD",
                 "focus group": "Focus group", "in-depth": "In-depth", "qualitative": "Qualitative",
                 "quantitative": "Quantitative", "mystery": "Mystery shopping"}
_CURRENCIES = {"USD", "INR", "EUR", "GBP", "AUD", "CAD", "SGD", "AED", "JPY", "CNY", "IDR", "MYR", "ZAR", "CHF"}


def grounded_details(out: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Keep only what the email actually says.

    Tried on a real mail that stated nothing ("The ID mentioned below has been
    captured. Please go ahead."), the local model answered sample_size 1000,
    LOI 15, IR 5, budget 5000 and "Not specified" for the rest. A number is
    kept only if it appears in the mail; a budget only with a currency the mail
    names; filler strings are dropped."""
    t = (text or "").lower()
    digits = set(re.findall(r"\d[\d,]*(?:\.\d+)?", t))
    digits |= {d.replace(",", "") for d in digits}
    kept: Dict[str, Any] = {}
    # Methodology: the method terms the mail itself uses, not the model's prose
    # ("The study will be conducted through an online survey using a").
    methods = [m for m in _METHODS if re.search(rf"\b{m}\b", t)]
    if methods:
        kept["methodology"] = ", ".join(_METHOD_LABEL.get(m, m.upper() if len(m) <= 4 else m.title())
                                        for m in methods)[:60]
    # Country and deadline: only wording the mail contains.
    for k in ("country", "deadline"):
        v = str(out.get(k) or "").strip()
        if v and not _FILLER.match(v) and len(v) <= 40 and v.lower() in t:
            kept[k] = v
    # Audience: short, and mostly the mail's own words.
    v = str(out.get("target_audience") or "").strip()
    words = [w for w in re.findall(r"[a-z0-9+\-]+", v.lower()) if len(w) > 1]
    if v and not _FILLER.match(v) and len(v) <= 100 and words and \
            sum(w in t for w in words) / len(words) >= 0.7:
        kept["target_audience"] = v
    for k in ("sample_size", "loi", "ir"):
        v = out.get(k)
        if isinstance(v, (int, float)) and v > 0 and (str(int(v)) in digits or f"{int(v):,}" in digits):
            kept[k] = int(v)
    cur = str(out.get("currency") or "").upper().strip()
    b = out.get("budget")
    if (isinstance(b, (int, float)) and b > 0 and cur in _CURRENCIES
            and (str(int(b)) in digits or f"{int(b):,}" in digits)
            and (cur.lower() in t or {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}.get(cur, "\0") in t)):
        kept["budget"] = b
        kept["currency"] = cur
    return kept


def enrich_open(client, limit: int = 2) -> Dict[str, int]:
    from bson import ObjectId
    from leads.local_slm_client import LocalSLMError, chat_json
    from sales.reply_triage import strip_quoted
    opp = client["crm_db"]["opportunities"]
    em = client["torpedo_gmail"]["email_metadata"]
    stats = {"attempted": 0, "filled": 0, "unavailable": 0}
    for o in opp.find({"metadata.rfq.source": SOURCE, "status": "open", "stage": "rfq",
                       "metadata.rfq.details_at": {"$exists": False}},
                      {"metadata.rfq.source_email_id": 1}).sort("metadata.rfq.received_at", -1).limit(limit):
        src = ((o.get("metadata") or {}).get("rfq") or {}).get("source_email_id")
        try:
            doc = em.find_one({"_id": ObjectId(src)}, {"subject": 1, "body_plain": 1, "snippet": 1})
        except Exception:
            doc = None
        body = strip_quoted((doc or {}).get("body_plain") or (doc or {}).get("snippet") or "")[:2500]
        stats["attempted"] += 1
        try:
            from leads.local_llm_gate import queue_wait
            with queue_wait(60):  # a background job: waiting for the shared slot costs nothing
                out = chat_json(system=_DETAIL_SYSTEM, user=f"SUBJECT: {(doc or {}).get('subject') or ''}\n\n{body}",
                                max_tokens=260, json_schema=_DETAIL_SCHEMA)
        except LocalSLMError as e:
            stats["unavailable"] += 1
            logger.warning("rfq details: local model unavailable: %s", e)
            break  # an outage is never written as details; retried next cycle
        text = f"{(doc or {}).get('subject') or ''}\n{body}"
        fields = {f"metadata.rfq.{k}": v for k, v in grounded_details(out, text).items()}
        fields["metadata.rfq.details_at"] = datetime.utcnow()
        fields["metadata.rfq.details_source"] = "qwen"
        opp.update_one({"_id": o["_id"]}, {"$set": fields})
        stats["filled"] += 1
    return stats


def run_scheduled_cycle(client) -> Dict[str, Any]:
    """New RFQs from the last few days' mail, then details for a couple."""
    out = {"built": build(client, since=datetime.utcnow() - timedelta(days=3))}
    out["details"] = enrich_open(client, limit=int(os.getenv("RFQ_DETAILS_AI_PER_RUN", "2")))
    return out
