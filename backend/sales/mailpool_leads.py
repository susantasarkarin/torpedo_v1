"""
Mail pool -> leads (sales-module points 3, 4 and 6).

Every message in torpedo_gmail.email_metadata already carries to_emails,
from_email, cc_emails and timestamp, plus the segregation label
(app/services/mail_categorizer.py). This module adds, per message:

  mail_party           client | vendor | promotional | automated | internal |
                       outreach | finance | other
  mail_counterparty    the external address the message is with
  mail_summary         a short summary taken from the message's own text
                       (quoted thread, greeting and signature stripped)
  mail_summary_source  "extract"

The existing ai_summary field is left alone: it describes the sender, not the
message, and other pipelines read it.

Per correspondent:
  client -> email_automation.leads_enriched (Sales > Leads), source "gmail"
  vendor -> email_automation.vendor_leads   (Vendor > Leads), source "mail_pool"
each with a mail_pool block (message counts, first/last contact, last
subject and summary). A company that is both (Cint) gets both records.

Point 4: for prospects -- contacts who replied to our outreach or enquired --
the latest inbound message is triaged by the reply-triage rules; what the
rules cannot decide waits for the local model (a few per cycle, newest
first). Established clients and suppliers get no positive/negative label. A status a person set is never overwritten. Nurture
starts only for a fresh (<=14 days) positive from a prospect -- never for an
established client or a converted lead.

Point 6: a client lead whose address or company domain is on a won
opportunity is marked converted (stage "won"). Nothing else is created here:
Finance and Operations records only come from the real won path
(crm_service.mark_opportunity_won -> won_handoff).

Rollback: $unset the mail_* fields on email_metadata; delete leads_enriched
docs with created_by "mail_pool" and $unset mail_pool on the others; delete
vendor_leads with source "mail_pool" and $unset mail_pool on the others.
"""
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services import mail_categorizer as mc

logger = logging.getLogger(__name__)

PARTY_VERSION = 1
CLIENT_CATEGORIES = {"client", "rfq", "active_deal", "proposal", "new_inquiry", "outreach_reply"}
DEAL_CATEGORIES = {"rfq", "active_deal", "proposal"}
TRIAGE_SOURCE = "mail_pool_triage"
NURTURE_MAX_AGE_DAYS = 14

_I = re.IGNORECASE
# Deal mail from an unknown company that is selling to us: an inbound estimate
# is a supplier's, not a client's (dry run 2026-09-28: Zoho implementers'
# "Scope of Work & Estimate Enclosed" follow-ups had been read as clients).
_SELLING = re.compile(
    r"\b(estimate|proposal|quotation|quote|scope of work|rate card|cost sheet)s?\b.{0,25}\b(enclosed|attached)\b|"
    r"\b(our|the|my) (estimate|proposal|quotation|quote|pricing|rate card|cost sheet)\b.{0,40}"
    r"\b(i|we) (shared|sent|submitted)\b|"
    r"\b(estimate|proposal|quotation) (i|we) (shared|sent|submitted)\b|"
    r"\bwe (offer|provide|specialise|specialize in)\b|\bour services\b", _I)
# Our own mailers that sourced suppliers: whoever answers them is a vendor.
VENDOR_SOURCING_SUBJECTS = {"looking for partners in zoho erp implementation",
                            "survey fieldwork - updating of vendor database"}
_GREETING_LINE = re.compile(
    r"^(hi|hello|hey|dear|good (morning|afternoon|evening)|greetings)\b[^\n]{0,40}$", _I)
_SIGNOFF = re.compile(
    r"^(thanks|thank you|thanks (&|and) regards|regards|best|best regards|kind regards|warm regards|"
    r"cheers|sincerely|br|rgds|sent from my)\b", _I)


# ---------------------------------------------------------------------------
# per message
# ---------------------------------------------------------------------------
def extract_summary(subject: Optional[str], body: Optional[str], limit: int = 240) -> str:
    """The first real sentences the sender wrote, or the subject."""
    from sales.reply_triage import strip_quoted
    lines: List[str] = []
    for raw in strip_quoted(body or "").splitlines():
        s = raw.strip()
        if not s or s.startswith(">"):
            continue
        if _SIGNOFF.match(s) or s.startswith("--"):
            break
        if _GREETING_LINE.match(s):
            continue
        lines.append(s)
    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if out and len(out) + len(sentence) > limit:
            break
        out = f"{out} {sentence}".strip()
        if len(out) >= 120:
            break
    return (out or (subject or "").strip())[:limit]


def counterparty(doc: Dict[str, Any]) -> str:
    """The external address a message is with ('' when there is none)."""
    if doc.get("direction") == "outbound":
        for r in doc.get("to_emails") or []:
            if isinstance(r, str) and mc._domain(r) and mc._domain(r) not in mc.OWN_DOMAINS:
                return r.strip().lower()
        return ""
    sender = (doc.get("from_email") or "").strip().lower()
    return "" if mc._domain(sender) in mc.OWN_DOMAINS else sender


def party_for(doc: Dict[str, Any], ctx: "mc.Context", rfq_openers: Dict[str, str]) -> str:
    cat = doc.get("ai_tier1_category") or "others"
    if cat in ("promotional", "spam"):
        return "promotional"
    if cat == "automated":
        return "automated"
    if cat == "internal":
        return "internal"
    if cat == "outreach":
        return "outreach"
    other = counterparty(doc)
    if not other:
        return "internal"
    role = ctx.role(other, doc.get("gmail_thread_id"))
    if role:
        return role
    if cat == "vendor":
        return "vendor"
    if mc.normalize_subject(doc.get("subject")) in VENDOR_SOURCING_SUBJECTS:
        return "vendor"
    if cat in CLIENT_CATEGORIES and doc.get("direction") != "outbound":
        from sales.reply_triage import strip_quoted
        if _SELLING.search(f"{doc.get('subject') or ''}\n{strip_quoted(doc.get('body') or '')[:1500]}"):
            return "vendor"
    if cat in DEAL_CATEGORIES:
        # Who asked whom: we open RFQ threads with suppliers, clients open them with us.
        opener = rfq_openers.get(doc.get("gmail_thread_id") or "")
        if opener == "us":
            return "vendor"
        if opener == "them" or doc.get("direction") != "outbound":
            return "client"
        return "other"
    if cat in CLIENT_CATEGORIES:
        return "client"
    if cat in ("invoice", "banking"):
        return "finance"
    return "other"


def rfq_thread_openers(client) -> Dict[str, str]:
    em = client["torpedo_gmail"]["email_metadata"]
    out: Dict[str, str] = {}
    for t in em.aggregate([
            {"$match": {"subject": {"$regex": mc._RFQ_MONGO, "$options": "i"},
                        "gmail_thread_id": {"$nin": [None, ""]}}},
            {"$sort": {"timestamp": 1}},
            {"$group": {"_id": "$gmail_thread_id", "dir": {"$first": "$direction"}}}], allowDiskUse=True):
        out[t["_id"]] = "us" if t.get("dir") == "outbound" else "them"
    return out


_PROJECTION = {"subject": 1, "from_email": 1, "to_emails": 1, "direction": 1, "gmail_thread_id": 1,
               "ai_tier1_category": 1, "snippet": 1,
               "body": {"$substrCP": [{"$ifNull": ["$body_plain", ""]}, 0, 3000]}}


def run_message_pass(client, ctx=None, limit: Optional[int] = None, batch_size: int = 1000,
                     redo: bool = False) -> Dict[str, Any]:
    """Label messages the segregation pass has labelled but this one has not
    (or all of them with redo=True, e.g. after a relationship changed)."""
    from pymongo import UpdateOne
    ctx = ctx or mc.build_context(client)
    openers = rfq_thread_openers(client)
    col = client["torpedo_gmail"]["email_metadata"]
    match: Dict[str, Any] = {"ai_tier1_category": {"$exists": True}}
    if not redo:
        match["mail_party_v"] = {"$ne": PARTY_VERSION}
    pipeline: List[Dict[str, Any]] = [{"$match": match}, {"$sort": {"timestamp": -1}}]
    if limit:
        pipeline.append({"$limit": limit})
    pipeline.append({"$project": _PROJECTION})

    now = datetime.utcnow()
    stats: Dict[str, Any] = {"processed": 0, "by_party": {}}
    ops: List[Any] = []
    for doc in col.aggregate(pipeline, allowDiskUse=True):
        party = party_for(doc, ctx, openers)
        stats["processed"] += 1
        stats["by_party"][party] = stats["by_party"].get(party, 0) + 1
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": {
            "mail_party": party,
            "mail_counterparty": counterparty(doc),
            "mail_summary": extract_summary(doc.get("subject"), doc.get("body") or doc.get("snippet")),
            "mail_summary_source": "extract",
            "mail_party_v": PARTY_VERSION,
            "mail_party_at": now,
        }}))
        if len(ops) >= batch_size:
            col.bulk_write(ops, ordered=False)
            ops = []
    if ops:
        col.bulk_write(ops, ordered=False)
    return stats


# ---------------------------------------------------------------------------
# per correspondent
# ---------------------------------------------------------------------------
def _own_addresses() -> Set[str]:
    """Our own people's addresses outside our domains (a director's personal
    Gmail shows up in RFQ threads as an outside party)."""
    raw = os.getenv("MAIL_POOL_OWN_ADDRESSES", "")
    return {a.strip().lower() for a in raw.split(",") if "@" in a}


def _is_person_address(addr: str) -> bool:
    if not addr or "@" not in addr or addr.lower() in _own_addresses():
        return False
    bounce_from, _, _ = mc._production_patterns()
    return not (bounce_from.search(addr) or mc._AUTOMATED_FROM.search(addr))


def _company_from_domain(domain: str) -> str:
    if not domain or domain in mc.WEBMAIL:
        return ""
    root = domain.split(".")[0]
    return root.replace("-", " ").title()


def contact_rollup(client, party: str, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """One row per external address with mail in this party."""
    match: Dict[str, Any] = {"mail_party": party, "mail_counterparty": {"$nin": [None, ""]}}
    if since:
        match["timestamp"] = {"$gte": since}
    rows = client["torpedo_gmail"]["email_metadata"].aggregate([
        {"$match": match},
        {"$sort": {"timestamp": 1}},
        {"$group": {
            "_id": "$mail_counterparty",
            "messages_in": {"$sum": {"$cond": [{"$eq": ["$direction", "inbound"]}, 1, 0]}},
            "messages_out": {"$sum": {"$cond": [{"$eq": ["$direction", "outbound"]}, 1, 0]}},
            "first_contact_at": {"$first": "$timestamp"},
            "last_contact_at": {"$last": "$timestamp"},
            "last_subject": {"$last": "$subject"},
            "last_summary": {"$last": "$mail_summary"},
            "last_direction": {"$last": "$direction"},
            "names": {"$addToSet": {"$cond": [{"$eq": ["$direction", "inbound"]}, "$from_name", None]}},
            "categories": {"$addToSet": "$ai_tier1_category"},
        }}], allowDiskUse=True)
    out = []
    for r in rows:
        if not _is_person_address(r["_id"]):
            continue
        r["name"] = next((n for n in (r.pop("names") or []) if n), "")
        out.append(r)
    return out


def _mail_pool_block(row: Dict[str, Any], relationship: str, now: datetime) -> Dict[str, Any]:
    return {
        "relationship": relationship,
        "messages_in": row["messages_in"],
        "messages_out": row["messages_out"],
        "first_contact_at": row["first_contact_at"],
        "last_contact_at": row["last_contact_at"],
        "last_subject": (row.get("last_subject") or "")[:200],
        "last_summary": row.get("last_summary") or "",
        "last_direction": row.get("last_direction"),
        "categories": sorted(c for c in row.get("categories") or [] if c),
        "synced_at": now,
    }


def _email_index(col) -> Dict[str, Any]:
    idx: Dict[str, Any] = {}
    for d in col.find({"email": {"$type": "string"}}, {"email": 1}):
        idx.setdefault(d["email"].strip().lower(), d["_id"])
    return idx


def upsert_client_leads(client, rows: List[Dict[str, Any]], now: datetime) -> Dict[str, int]:
    from pymongo import InsertOne, UpdateOne
    col = client["email_automation"]["leads_enriched"]
    idx = _email_index(col)
    ops, created, updated = [], 0, 0
    for r in rows:
        email = r["_id"]
        block = _mail_pool_block(r, "client", now)
        if email in idx:
            ops.append(UpdateOne({"_id": idx[email]}, {"$set": {"mail_pool": block, "updated_at": now}}))
            # Only fill a summary nobody else wrote.
            ops.append(UpdateOne(
                {"_id": idx[email], "$or": [{"conversation_summary": {"$in": [None, ""]}},
                                            {"conversation_summary_source": {"$regex": "^mail_pool"}}]},
                {"$set": {"conversation_summary": block["last_summary"],
                          "conversation_summary_source": "mail_pool_extract"}}))
            updated += 1
        else:
            domain = mc._domain(email)
            ops.append(InsertOne({
                "email": email, "name": r.get("name") or "",
                "first_name": (r.get("name") or "").split(" ")[0],
                "company_name": _company_from_domain(domain),
                "company_domain": "" if domain in mc.WEBMAIL else domain,
                "source": "gmail", "created_by": "mail_pool", "created_at": now, "updated_at": now,
                "conversation_summary": block["last_summary"],
                "conversation_summary_source": "mail_pool_extract",
                "mail_pool": block,
            }))
            created += 1
        if len(ops) >= 1000:
            col.bulk_write(ops, ordered=False)
            ops = []
    if ops:
        col.bulk_write(ops, ordered=False)
    return {"created": created, "updated": updated}


def upsert_vendor_leads(client, rows: List[Dict[str, Any]], now: datetime) -> Dict[str, int]:
    from pymongo import InsertOne, UpdateOne
    col = client["email_automation"]["vendor_leads"]
    idx = _email_index(col)
    ops, created, updated = [], 0, 0
    for r in rows:
        email = r["_id"]
        block = _mail_pool_block(r, "vendor", now)
        if email in idx:
            ops.append(UpdateOne({"_id": idx[email]}, {"$set": {"mail_pool": block, "updated_at": now}}))
            updated += 1
        else:
            ops.append(InsertOne({
                "name": r.get("name") or email.split("@")[0], "email": email, "title": "",
                "company": _company_from_domain(mc._domain(email)), "phone": "",
                "status": "new", "source": "mail_pool",
                "notes": f"From the mail pool: {r['messages_in']} received, {r['messages_out']} sent",
                "mail_pool": block, "created_at": now, "updated_at": now,
            }))
            created += 1
        if len(ops) >= 1000:
            col.bulk_write(ops, ordered=False)
            ops = []
    if ops:
        col.bulk_write(ops, ordered=False)
    return {"created": created, "updated": updated}


# ---------------------------------------------------------------------------
# point 6: a won RFQ converts the lead
# ---------------------------------------------------------------------------
def won_parties(client) -> Tuple[Dict[str, str], Dict[str, str]]:
    """(address -> won opportunity id, company domain -> won opportunity id).

    Only wins made through crm_service.mark_opportunity_won, which sets
    closed_at. The other ~1,500 'won' opportunities were labelled won by the
    mail-pool AI from old mail ("Request for Payment for Two Projects") and
    backfilled in bulk (2,500 activity rows in one second, 2026-09-01) --
    converting leads from them would spread the same mistakes."""
    from bson import ObjectId
    crm = client["crm_db"]
    by_contact: Dict[str, str] = {}
    by_account: Dict[str, str] = {}
    for opp in crm["opportunities"].find({"stage": "won", "closed_at": {"$exists": True}},
                                         {"contact_id": 1, "account_id": 1,
                                                            "metadata.rfq.contact_id": 1}):
        oid = str(opp["_id"])
        for cid in (opp.get("contact_id"), ((opp.get("metadata") or {}).get("rfq") or {}).get("contact_id")):
            if cid:
                by_contact[str(cid)] = oid
        if opp.get("account_id"):
            by_account[str(opp["account_id"])] = oid

    def oids(ids):
        out = []
        for i in ids:
            try:
                out.append(ObjectId(i))
            except Exception:
                pass
        return out

    emails: Dict[str, str] = {}
    for c in crm["contacts"].find({"_id": {"$in": oids(by_contact)}, "email": {"$regex": "@"}}, {"email": 1}):
        emails[c["email"].strip().lower()] = by_contact[str(c["_id"])]
    domains: Dict[str, str] = {}
    for a in crm["accounts"].find({"_id": {"$in": oids(by_account)}}, {"website": 1}):
        site = (a.get("website") or "").lower()
        d = re.sub(r"^(https?://)?(www\.)?", "", site).split("/")[0].strip()
        if d and "." in d and d not in mc.WEBMAIL and d not in mc.OWN_DOMAINS:
            domains[d] = by_account[str(a["_id"])]
    return emails, domains


def convert_won_leads(client, now: datetime) -> int:
    from pymongo import UpdateOne
    emails, domains = won_parties(client)
    col = client["email_automation"]["leads_enriched"]
    ops = []
    for lead in col.find({"mail_pool.relationship": "client", "stage": {"$ne": "won"}}, {"email": 1}):
        email = (lead.get("email") or "").lower()
        opp = emails.get(email) or domains.get(mc._domain(email))
        if opp:
            ops.append(UpdateOne({"_id": lead["_id"]}, {"$set": {
                "stage": "won", "engagement_status": "converted", "converted_at": now,
                "converted_via": "won_opportunity_match", "won_opportunity_id": opp, "updated_at": now}}))
    if ops:
        col.bulk_write(ops, ordered=False)
    return len(ops)


# ---------------------------------------------------------------------------
# point 4: triage the latest inbound mail of each client contact
# ---------------------------------------------------------------------------
def _status_is_automated(lead: Dict[str, Any]) -> bool:
    return not lead.get("lead_status") or lead.get("lead_status_source") in ("reply_triage", TRIAGE_SOURCE)


PROSPECT_CATEGORIES = {"outreach_reply", "new_inquiry"}


def is_prospect(mail_pool: Dict[str, Any]) -> bool:
    """Nurture is for people answering our outreach or enquiring. The first
    backfill also started it for vendors who booked a call to pitch us, an
    active deal, and a director's personal address -- all stopped by hand."""
    return bool(PROSPECT_CATEGORIES & set(mail_pool.get("categories") or []))


def _established_client(email: str, ctx: "mc.Context", won_domains: Dict[str, str]) -> bool:
    d = mc._domain(email)
    return (ctx.party(email) in ("client", "both")) or d in won_domains


def run_triage_pass(client, ctx, use_model: bool = False, model_limit: int = 0,
                    limit: Optional[int] = None) -> Dict[str, int]:
    """Rules on every contact whose latest inbound mail changed; the local
    model only on up to model_limit undecided ones (newest first)."""
    from bson import ObjectId
    from sales.reply_triage import LEAD_STATUS_FOR_VERDICT, model_verdict, rule_verdict, strip_quoted, triage_reply
    col = client["email_automation"]["leads_enriched"]
    em = client["torpedo_gmail"]["email_metadata"]
    now = datetime.utcnow()
    _, won_domains = won_parties(client)
    stats = {"checked": 0, "ruled": 0, "model": 0, "pending": 0, "nurture_started": 0, "kept_human": 0}

    latest = {r["_id"]: r for r in em.aggregate([
        {"$match": {"mail_party": "client", "direction": "inbound", "mail_counterparty": {"$nin": [None, ""]}}},
        {"$sort": {"timestamp": 1}},
        {"$group": {"_id": "$mail_counterparty", "mid": {"$last": "$_id"}, "ts": {"$last": "$timestamp"}}}],
        allowDiskUse=True)}

    q = {"mail_pool.relationship": "client"}
    model_used = 0
    cursor = col.find(q, {"email": 1, "lead_status": 1, "lead_status_source": 1, "stage": 1, "mail_pool": 1})
    leads = sorted(cursor, key=lambda l: (l.get("mail_pool") or {}).get("last_contact_at") or datetime.min,
                   reverse=True)
    for lead in leads[:limit] if limit else leads:
        email = (lead.get("email") or "").lower()
        last = latest.get(email)
        if not last:
            continue
        mp = lead.get("mail_pool") or {}
        if not is_prospect(mp):
            # Positive/negative is a prospect's answer to our outreach. On a
            # client's routine mail it is noise: an Ipsos cost-sheet note ("there
            # is no need...") read as Negative, Market Cube chasing an invoice
            # ("Can you check") as Positive.
            continue
        undecided_before =mp.get("triage_pending") and mp.get("triaged_message_id") == str(last["mid"])
        if mp.get("triaged_message_id") == str(last["mid"]) and not undecided_before:
            continue
        if not _status_is_automated(lead):
            stats["kept_human"] += 1
            col.update_one({"_id": lead["_id"]}, {"$set": {"mail_pool.triaged_message_id": str(last["mid"]),
                                                           "mail_pool.triage_pending": False}})
            continue
        if undecided_before and (not use_model or model_used >= model_limit):
            continue
        doc = em.find_one({"_id": last["mid"]}, {"subject": 1, "body_plain": 1, "snippet": 1,
                                                  "mailbox_id": 1, "gmail_thread_id": 1})
        body, subject = (doc or {}).get("body_plain") or (doc or {}).get("snippet") or "", (doc or {}).get("subject") or ""
        stats["checked"] += 1
        if undecided_before:
            model_used += 1
            triage = triage_reply(body, subject, use_model=True)
            if triage.get("method") == "fallback":
                continue  # model unavailable: leave it pending, never record an outage as a verdict
            stats["model"] += 1
        else:
            triage = triage_reply(body, subject, use_model=False)
            if triage.get("method") == "fallback":
                stats["pending"] += 1
                col.update_one({"_id": lead["_id"]}, {"$set": {
                    "mail_pool.triaged_message_id": str(last["mid"]), "mail_pool.triage_pending": True}})
                continue
            stats["ruled"] += 1
        verdict = triage["verdict"]
        from sales.reply_triage import honour_removal_request
        honour_removal_request(email, triage)
        col.update_one({"_id": lead["_id"]}, {"$set": {
            "lead_status": LEAD_STATUS_FOR_VERDICT[verdict], "lead_status_source": TRIAGE_SOURCE,
            "needs_human_review": verdict == "needs_human",
            "mail_pool.triaged_message_id": str(last["mid"]), "mail_pool.triage_pending": False,
            # mailbox + thread: nurture drafts its follow-up in the thread the
            # prospect wrote in, from the mailbox they wrote to.
            "mail_pool.triage": {"verdict": verdict, "method": triage.get("method"),
                                 "reason": triage.get("reason"), "model_verdict": triage.get("model_verdict"),
                                 "gmail_message_id": str(last["mid"]),
                                 "gmail_thread_id": (doc or {}).get("gmail_thread_id"),
                                 "mailbox_id": (doc or {}).get("mailbox_id"),
                                 "triaged_at": now},
            "updated_at": now}})
        fresh = isinstance(last.get("ts"), datetime) and last["ts"] >= now - timedelta(days=NURTURE_MAX_AGE_DAYS)
        if verdict == "positive" and fresh and is_prospect(mp) and lead.get("stage") != "won" \
                and not _established_client(email, ctx, won_domains):
            try:
                from sales.nurture import start_nurture
                if start_nurture(str(lead["_id"]), started_by=TRIAGE_SOURCE):
                    stats["nurture_started"] += 1
            except Exception as e:  # nurture must never break triage
                logger.warning("nurture start failed for %s: %s", email, e)
    return stats


# ---------------------------------------------------------------------------
# local-model conversation summaries (a few per cycle)
# ---------------------------------------------------------------------------
_SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False,
                   "properties": {"summary": {"type": "string", "maxLength": 400}}, "required": ["summary"]}
_SUMMARY_SYSTEM = ("You summarise the recent email conversation between a market-research fieldwork "
                   "company (us) and one correspondent. Two sentences, factual: what they want or "
                   "offer, and where it stands. JSON only.")


def run_summary_pass(client, limit: int = 5) -> Dict[str, int]:
    from leads.local_slm_client import LocalSLMError, chat_json
    from sales.reply_triage import strip_quoted
    em = client["torpedo_gmail"]["email_metadata"]
    stats = {"attempted": 0, "written": 0, "unavailable": 0}
    targets = []
    for coll, rel in (("leads_enriched", "client"), ("vendor_leads", "vendor")):
        col = client["email_automation"][coll]
        for d in col.find({"mail_pool.relationship": rel, "mail_pool.model_summary_at": {"$exists": False}},
                          {"email": 1, "mail_pool.last_contact_at": 1}).sort("mail_pool.last_contact_at", -1).limit(limit):
            targets.append((col, d))
    targets.sort(key=lambda t: (t[1].get("mail_pool") or {}).get("last_contact_at") or datetime.min, reverse=True)
    for col, lead in targets[:limit]:
        email = (lead.get("email") or "").lower()
        msgs = list(em.find({"mail_counterparty": email}, {"direction": 1, "subject": 1, "body_plain": 1,
                                                          "snippet": 1, "timestamp": 1})
                    .sort("timestamp", -1).limit(3))
        convo = "\n\n".join(
            f"[{'THEM' if m.get('direction') == 'inbound' else 'US'} {m.get('timestamp'):%Y-%m-%d}] "
            f"{(m.get('subject') or '')[:120]}\n{strip_quoted(m.get('body_plain') or m.get('snippet') or '')[:500]}"
            for m in reversed(msgs) if m.get("timestamp"))
        if not convo:
            continue
        stats["attempted"] += 1
        try:
            # 160 tokens cut the JSON off mid-string (live, 2026-09-28).
            out = chat_json(system=_SUMMARY_SYSTEM, user=convo, max_tokens=320, json_schema=_SUMMARY_SCHEMA)
        except LocalSLMError as e:
            stats["unavailable"] += 1
            logger.warning("mail pool summary: local model unavailable: %s", e)
            if stats["unavailable"] >= 2:
                break
            continue
        summary = str(out.get("summary") or "").strip()[:500]
        if not summary:
            continue
        now = datetime.utcnow()
        col.update_one({"_id": lead["_id"]}, {"$set": {"mail_pool.model_summary": summary,
                                                       "mail_pool.model_summary_at": now}})
        if col.name == "leads_enriched":
            col.update_one({"_id": lead["_id"], "$or": [
                {"conversation_summary": {"$in": [None, ""]}},
                {"conversation_summary_source": {"$regex": "^mail_pool"}}]},
                {"$set": {"conversation_summary": summary, "conversation_summary_source": "mail_pool_qwen"}})
        stats["written"] += 1
    return stats


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------
def run_full(client, ctx=None) -> Dict[str, Any]:
    """Whole pool: label every message, then build every contact record."""
    ctx = ctx or mc.build_context(client)
    now = datetime.utcnow()
    out: Dict[str, Any] = {"messages": run_message_pass(client, ctx)}
    out["client_leads"] = upsert_client_leads(client, contact_rollup(client, "client"), now)
    out["vendor_leads"] = upsert_vendor_leads(client, contact_rollup(client, "vendor"), now)
    out["converted"] = convert_won_leads(client, now)
    out["triage"] = run_triage_pass(client, ctx)
    return out


def run_scheduled_cycle() -> Dict[str, Any]:
    """APScheduler entry point (after segregation): new messages, the contacts
    they touch, conversions, triage, and a few model summaries/verdicts."""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                         serverSelectionTimeoutMS=5000)
    ctx = mc.build_context(client)
    now = datetime.utcnow()
    msgs = run_message_pass(client, ctx, limit=5000)
    since = now - timedelta(days=2)
    touched = {"client": [], "vendor": []}
    if msgs["processed"]:
        for party in touched:
            recent = {r["_id"] for r in contact_rollup(client, party, since=since)}
            touched[party] = [r for r in contact_rollup(client, party) if r["_id"] in recent] if recent else []
    out = {
        "messages": msgs,
        "client_leads": upsert_client_leads(client, touched["client"], now),
        "vendor_leads": upsert_vendor_leads(client, touched["vendor"], now),
        "converted": convert_won_leads(client, now),
        "triage": run_triage_pass(client, ctx, use_model=True,
                                  model_limit=int(os.getenv("MAIL_POOL_TRIAGE_AI_PER_RUN", "3"))),
        "summaries": run_summary_pass(client, limit=int(os.getenv("MAIL_POOL_SUMMARY_AI_PER_RUN", "3"))),
    }
    try:  # email address structures for addresses seen in the last day
        from app.services import email_structure
        out["address_structures"] = email_structure.backfill(client, since=now - timedelta(days=1))
    except Exception as e:
        logger.warning("[MailPoolLeads] address structures failed: %s", e)
    try:  # RFQs from client-opened RFQ threads (app/services/rfq_from_mail.py)
        from app.services import rfq_from_mail
        out["rfqs"] = rfq_from_mail.run_scheduled_cycle(client)
    except Exception as e:
        logger.warning("[MailPoolLeads] rfq build failed: %s", e)
    logger.info("[MailPoolLeads] %s", out)
    return out
