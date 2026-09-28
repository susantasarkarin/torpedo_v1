"""
Mail pool segregation (torpedo_gmail.email_metadata -> ai_tier1_category).

The Mail Pool page counts and filters on `ai_tier1_category`, but only the old
OpenAI classifier ever wrote it and that never ran here -- as of 2026-09-28 the
field was empty on all 366k messages, so every sidebar category showed 0 and
every category filter returned nothing. This module fills that field (and the
`email_type`/`system_subtype` pair the page uses for bounce/OOO badges). It does
NOT touch `ai_category` or `segment`, which other pipelines read.

How a message is categorised (validated on 5,000 real inbound messages):
  1. system mail (bounce, out-of-office, calendar response, read receipt)
  2. a reply in one of our cold-outreach threads
  3. confirmed noise senders (notification platforms, newsletters)
  4. banking/tax, then invoice/billing
  5. our own domain: RFQ thread / copy of our bulk mail / internal
  6. a reply to a subject we mailed in bulk (older campaigns predate the
     outreach log) -> outreach_reply
  7. content signals: rfq, active_deal (sign-off/PO/contract), proposal
  8. client, vendor (Finance customer / vendor records)
  9. new_inquiry
 10. anything left: the local SLM (Qwen) decides, in a throttled background
     pass, newest mail first. Until then it is 'others' + status pending_ai.
Outbound mail is categorised by rules only (it is our own mail).

Rollback: every write carries ai_tier1_source starting "mail_segregation";
$unset the ai_tier1_* fields (and email_type/system_subtype where
ai_tier1_system_set is true) on those docs.
"""
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

SOURCE_RULES = "mail_segregation:rules"
SOURCE_AI = "mail_segregation:qwen"
SOURCE_AI_FAILED = "mail_segregation:qwen_unavailable"

OWN_DOMAINS = {"surveyfieldwork.com", "cogentixresearch.com", "bimwavesolutions.com"}
WEBMAIL = {"gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com",
           "live.com", "icloud.com", "rediffmail.com", "proton.me", "protonmail.com", "aol.com"}

CATEGORIES = ("outreach_reply", "outreach", "rfq", "active_deal", "proposal", "new_inquiry",
              "client", "vendor", "internal", "invoice", "banking", "promotional",
              "automated", "spam", "others")
MODEL_CATEGORIES = ["rfq", "active_deal", "proposal", "new_inquiry", "client", "vendor",
                    "invoice", "promotional", "automated", "spam", "others"]
# Sales-facing labels the local model may suggest but not assign on its own: in
# the first live cycle it filed a password reset and an investment pitch as
# "rfq". Its suggestion is kept (ai_tier1_model_suggestion) and the message
# stays in "others" until a rule or a person places it.
UNTRUSTED_MODEL_CATEGORIES = {"rfq", "active_deal", "proposal", "new_inquiry", "client"}

# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------
_I = re.IGNORECASE
_CAL_RESPONSE = re.compile(r"^\s*(accepted|declined|tentative(ly accepted)?|updated invitation|"
                           r"invitation (canceled|cancelled))\s*:", _I)
_READ_RECEIPT = re.compile(r"^\s*(read|not read)\s*:", _I)
_AUTO_REPLY_BODY = re.compile(r"\b(i am|i'm) (currently )?(out of (the )?office|away|on (annual )?leave|"
                              r"travell?ing)\b|\bautomatic reply\b|\bauto-?reply\b|"
                              r"\blimited access to (my )?e-?mail\b", _I)

# Notification platforms: always automated, whatever their body says.
_AUTOMATED_FROM = re.compile(
    r"mailer-daemon@|no-?reply|noreply|donotreply|do-not-reply|notifications?@|alerts?@|"
    r"security@|account-alerts@|support@github\.com|"
    r"@(accounts\.google\.com|notify\.cloudflare\.com|em\d*\.cloudflare\.com|"
    r"notifications\.dynata\.com|zohosocial\.in|notification\.zohoannounces\.com|"
    r"scheduler\.pipedrive\.com|hunter\.io|read\.ai|e\.read\.ai|amazonses\.com|"
    r"email-abuse\.amazonses\.com|aws\.amazon\.com|amazonaws\.com|india5000\.com|youtube\.com|"
    r"skrapp\.io|docusign\.net|zoom\.us|intl\.paypal\.com|linkedin\.com|facebookmail\.com|"
    r"slack\.com|atlassian\.net|referrals\.digitalocean\.com)", _I)
_AUTOMATED_SUBJECT = re.compile(
    r"terms of service|privacy policy|security alert|password (reset|changed|reminder)|"
    r"reset (your )?password|change (your )?password|verify your|verification code|sign-?in to your|new sign-in|"
    r"\botp\b|one time password|subscription (has )?expired|credits (have been )?reset|"
    r"account (deletion|is ready)|action required.*account|scheduled (weekly|monthly) report", _I)
# Newsletters / marketing: promotional.
_PROMO_FROM = re.compile(
    r"newsletters?@|news@|marketing@|offers?@|promo(tions)?@|events@|webinars?@|"
    r"@(yourstory\.com|connect\.esomar\.org|email\.openai\.com|tm\.openai\.com|email\.grok\.com|"
    r"mailbluster\.com|easysendy\.net|snov\.io|persona\.ly|greenbook\.org|mail\.anthropic\.com|"
    r"rewards\.airasia\.com|naukri\.com|reply\.aveva\.com|discuss\.io)", _I)
_PROMO_SUBJECT = re.compile(r"\d+\s*% ?off|\bsale\b|webinar|newsletter|register now|"
                            r"you'?re invited|limited time|last chance|early bird|unlimited applies", _I)

_BANKING = re.compile(r"@([a-z0-9.-]*bank[a-z0-9.-]*\.(in|com)|gst\.gov\.in|incometax\.gov\.in|"
                      r"tin-nsdl\.com|nsdl\.co\.in|epfindia\.gov\.in)$|statement for period|"
                      r"gstr-?\d|\bgstin\b|income tax|\btds\b|account statement", _I)
_INVOICE = re.compile(r"\binvoice\b|\breceipt\b|payment (reminder|received|due|confirmation|of)|"
                      r"\bbill(ing)? (details|statement)\b|outstanding balance|coming due|"
                      r"statement ref|\bremittance\b|credit note|debit note|"
                      r"@(zohobooks\.com|sender\.zoho-books\.in)$", _I)

# Letter boundaries, not \b: "Urgent_RFQ_Bev" and "RFQ_Tourism" are RFQs.
_RFQ = re.compile(r"(?<![a-z])(rfq|rfp)(?![a-z])|\brequest for (quote|quotation|proposal)\b|"
                  r"\bquote request\b", _I)
_ACTIVE_DEAL = re.compile(r"\bsign[- ]?off\b|\bpurchase order\b|\bpo attached\b|\bscope of work\b|"
                          r"\bsow\b|\bproject briefing\b|\bkick[- ]?off\b|\bgo[- ]ahead\b|"
                          r"\bcontract (signed|attached)\b|\bfinal (contract|scope)\b|\bwork order\b|"
                          r"\bnext steps\b|^\s*invitation\s*:", _I)
_PROPOSAL = re.compile(r"\bproposal\b|\bquotation\b|\bcost sheet\b|\bpricing\b|\bfeasibility\b|"
                       r"\bcpi'?s?\b|\bquote\b", _I)
# Someone asking US about our services -- not replies to inquiries we made.
_NEW_INQUIRY = re.compile(r"\bwebsite enquiry\b|\bnew enquiry\s*:\s*sales\b|"
                          r"\b(enquiry|inquiry) (for|about|regarding) (your|survey|fieldwork|panel|research|data)\b|"
                          r"\binterested in your (services|panel|capabilities)\b|"
                          r"\bdo you (offer|provide|conduct|do) (survey|fieldwork|panel|research|data|cati|online)\b|"
                          r"\blooking for (a|an) (partner|vendor|supplier|agency|panel|fieldwork)\b", _I)
_SUBJECT_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|sv)\s*:\s*|\[[^\]]{1,20}\]\s*)+", _I)
_GREETING = re.compile(r"^\s*(hi|hello|dear|hey)\s+[\w.'-]+[,!]?\s*", _I)


def normalize_subject(subject: Optional[str]) -> str:
    """'Re: [SFW-BCC] Hi Rob, I have a Proposal!' -> 'i have a proposal!'"""
    s = _SUBJECT_PREFIX.sub("", subject or "")
    s = _GREETING.sub("", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _domain(addr: str) -> str:
    return addr.split("@")[-1].strip().lower() if addr and "@" in addr else ""


# ---------------------------------------------------------------------------
# context: who is a client / vendor
# ---------------------------------------------------------------------------
class Context:
    def __init__(self, client_domains: Set[str], vendor_domains: Set[str],
                 client_emails: Set[str], vendor_emails: Set[str],
                 outreach_threads: Set[str], bulk_subjects: Optional[Set[str]] = None,
                 relationships: Optional[Dict[str, str]] = None):
        # build_context has already resolved domains that look like both.
        self.client_domains = client_domains - vendor_domains
        self.vendor_domains = vendor_domains
        self.client_emails = client_emails
        self.vendor_emails = vendor_emails - client_emails
        # Set by a person (domain or address -> client/vendor); beats all evidence.
        self.relationships = {k.lower(): v for k, v in (relationships or {}).items()
                              if v in ("client", "vendor")}
        self.outreach_threads = outreach_threads
        # Subjects we have mailed in bulk (older campaigns predate the
        # outreach_sends_v2 log, so thread matching alone misses them).
        self.bulk_subjects = bulk_subjects or set()

    def is_bulk_subject(self, subject: Optional[str]) -> bool:
        s = normalize_subject(subject)
        return bool(s) and s in self.bulk_subjects

    def party(self, addr: str) -> Optional[str]:
        addr = (addr or "").lower()
        d = _domain(addr)
        if addr in self.relationships:
            return self.relationships[addr]
        if d and d in self.relationships:
            return self.relationships[d]
        if addr in self.client_emails:
            return "client"
        if addr in self.vendor_emails:
            return "vendor"
        if d and d not in WEBMAIL:
            if d in self.client_domains:
                return "client"
            if d in self.vendor_domains:
                return "vendor"
        return None


BULK_SUBJECT_MIN_SENDS = 20

# Subjects mailed in bulk that are NOT sales outreach: respondent recruitment
# and vendor sourcing for live projects, plus one generic phrase. Their
# replies come from respondents/suppliers, not prospects. Reviewed by hand
# against the 70 bulk subjects found on 2026-09-28; extend as needed. New
# cold-outreach campaigns are matched by thread (outreach_sends_v2) anyway.
NOT_OUTREACH_BULK = {
    "api details - cogentix research", "bladder cancer emotive journey research",
    "cashfree brand study | post phase", "how are you?", "invitation for idi",
    "invitation for online idi", "invitation for online idi [reminder 1]",
    "looking for partners in zoho erp implementation",
    "need extra support to close out 2024 scpo 1008609", "next steps to cpx research monetization",
    "nr12433_cgr", "online fgd - usa", "pre-post ad eval fintech brand",
    "redbus (ad-hoc costing for dec'25)", "redbus bht | wave 3",
    "survey fieldwork - updating of vendor database", "urgent requirement for online focus group",
}


RFQ_THREADS_MIN = 2
# A domain Finance records as a vendor is still a client if it plainly buys
# from us: it opened at least this many RFQ threads, 3x more than we opened.
STRONG_CLIENT_THREADS = 10
_RFQ_MONGO = r"(^|[^a-z])(rfq|rfp)([^a-z]|$)|request for (quote|quotation|proposal)"
RELATIONSHIPS_COLLECTION = ("email_automation", "party_relationships")


def rfq_thread_direction(client) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Per company domain: RFQ threads they opened with us (they buy) and RFQ
    threads we opened with them (we buy). The word RFQ alone does not say who
    is the client -- we send RFQs to our vendors and their replies come back
    inbound -- the first message of the thread does."""
    em = client["torpedo_gmail"]["email_metadata"]
    bounce_from, bounce_subj, _ = _production_patterns()
    asked_us: Dict[str, int] = {}
    we_asked: Dict[str, int] = {}

    def company(addr):
        d = _domain(addr or "")
        return d if d and d not in WEBMAIL and d not in OWN_DOMAINS else ""

    for t in em.aggregate([
            {"$match": {"subject": {"$regex": _RFQ_MONGO, "$options": "i"},
                        "gmail_thread_id": {"$nin": [None, ""]}}},
            {"$sort": {"timestamp": 1}},
            {"$group": {"_id": "$gmail_thread_id", "dir": {"$first": "$direction"},
                        "f": {"$first": "$from_email"}, "to": {"$first": "$to_emails"},
                        "s": {"$first": "$subject"}}}], allowDiskUse=True):
        if t.get("dir") == "inbound":
            sender = (t.get("f") or "").lower()
            # A bounce quoting an RFQ subject is not an RFQ from that domain.
            if bounce_from.search(sender) or bounce_subj.search(t.get("s") or "") \
                    or _AUTOMATED_FROM.search(sender):
                continue
            d = company(sender)
            if d:
                asked_us[d] = asked_us.get(d, 0) + 1
        elif t.get("dir") == "outbound":
            for d in {company(r) for r in (t.get("to") or [])} - {""}:
                we_asked[d] = we_asked.get(d, 0) + 1
    return asked_us, we_asked


def load_relationships(client) -> Dict[str, str]:
    db, name = RELATIONSHIPS_COLLECTION
    return {r["key"]: r["relationship"] for r in client[db][name].find(
        {"key": {"$type": "string"}, "relationship": {"$in": ["client", "vendor"]}},
        {"key": 1, "relationship": 1})}


def build_context(client) -> Context:
    """Who is a client / vendor.

    1. Relationships a person set (email_automation.party_relationships) win.
    2. Evidence: a client opened RFQ threads with us; a vendor is one we opened
       RFQ threads with, or one Finance records as a vendor. Where both apply,
       the vendor reading wins unless the domain plainly buys from us.
    Measured 2026-09-28: RFQ-subject counts alone filed Cint, PureSpectrum,
    Lucid and other sample suppliers as clients (their replies to our RFQs).
    CRM contacts and Finance customers are not usable -- auto-created from
    every correspondent, billed clients recorded by name without email.
    Webmail and our own domains never count."""
    asked_us, we_asked = rfq_thread_direction(client)
    rfq_clients = {d for d, n in asked_us.items()
                   if n >= RFQ_THREADS_MIN and n >= 3 * we_asked.get(d, 0)}
    rfq_vendors = {d for d, n in we_asked.items()
                   if n >= RFQ_THREADS_MIN and n >= 3 * asked_us.get(d, 0)}
    client_domains = set(rfq_clients)

    crm = client["crm_db"]
    contact_ids = set()
    for opp in crm["opportunities"].find({"stage": "won"}, {"contact_id": 1, "metadata.rfq.contact_id": 1}):
        for cid in (opp.get("contact_id"), ((opp.get("metadata") or {}).get("rfq") or {}).get("contact_id")):
            if cid:
                contact_ids.add(str(cid))
    from bson import ObjectId
    oids = []
    for cid in contact_ids:
        try:
            oids.append(ObjectId(cid))
        except Exception:
            pass
    won_emails = {c["email"].strip().lower() for c in crm["contacts"].find(
        {"_id": {"$in": oids}, "email": {"$regex": "@"}}, {"email": 1})}

    ve = {v["email"].strip().lower() for v in client["finance_db"]["vendors"].find(
        {"email": {"$regex": "@"}}, {"email": 1})}

    def domains(emails):
        return {d for d in (_domain(e) for e in emails) if d and d not in WEBMAIL and d not in OWN_DOMAINS}

    client_domains = {d for d in client_domains | domains(won_emails)
                      if d not in WEBMAIL and d not in OWN_DOMAINS}
    # Exact addresses only for non-webmail won contacts; a gmail address is a person, not a company.
    ce = {e for e in won_emails if _domain(e) not in WEBMAIL}

    threads = set(client["torpedo"]["outreach_sends_v2"].distinct("gmail_thread_id")) - {None, ""}
    counts: Dict[str, int] = {}
    for row in client["torpedo_gmail"]["email_metadata"].aggregate([
            {"$match": {"direction": "outbound"}},
            {"$group": {"_id": "$subject", "n": {"$sum": 1}}}], allowDiskUse=True):
        key = normalize_subject(row["_id"])
        if key:
            counts[key] = counts.get(key, 0) + row["n"]
    bulk = {s for s, n in counts.items()
            if n >= BULK_SUBJECT_MIN_SENDS and not _RFQ.search(s) and s not in NOT_OUTREACH_BULK}

    vendor_domains = domains(ve) | {d for d in rfq_vendors if d not in WEBMAIL and d not in OWN_DOMAINS}
    strong_clients = {d for d in client_domains if asked_us.get(d, 0) >= STRONG_CLIENT_THREADS
                      and asked_us[d] >= 3 * we_asked.get(d, 0)}
    vendor_domains -= strong_clients
    return Context(client_domains, vendor_domains, ce, ve, threads, bulk,
                   relationships=load_relationships(client))


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------
_prod_patterns = None


def _production_patterns():
    """The exact bounce/OOO patterns the live reply scanner uses."""
    global _prod_patterns
    if _prod_patterns is None:
        from routers.cold_outreach_router import (
            _BOUNCE_FROM_PATTERN, _BOUNCE_SUBJECT_PATTERN, _OOO_SUBJECT_PATTERN)
        _prod_patterns = (_BOUNCE_FROM_PATTERN, _BOUNCE_SUBJECT_PATTERN, _OOO_SUBJECT_PATTERN)
    return _prod_patterns


def categorize_inbound(doc: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """-> {category, reason, system_subtype?, needs_ai}"""
    from sales.reply_triage import strip_quoted
    subject = doc.get("subject") or ""
    sender = (doc.get("from_email") or "").lower()
    body = doc.get("body") or doc.get("body_plain") or doc.get("snippet") or ""
    text = strip_quoted(body)[:1500]
    head = f"{subject}\n{text[:600]}"
    bounce_from, bounce_subj, ooo_subj = _production_patterns()

    def out(category, reason, **kw):
        return {"category": category, "reason": reason, "needs_ai": False, **kw}

    # 1. system mail
    if bounce_from.search(sender) or bounce_subj.search(subject):
        return out("automated", "bounce / delivery failure", system_subtype="bounce")
    if ooo_subj.search(subject) or (_AUTO_REPLY_BODY.search(text[:400]) and len(text) < 1200):
        return out("automated", "out-of-office / auto-reply", system_subtype="out_of_office")
    if _CAL_RESPONSE.search(subject):
        return out("automated", "calendar response", system_subtype="calendar_response")
    if _READ_RECEIPT.search(subject):
        return out("automated", "read receipt", system_subtype="read_receipt")

    # 2. replies in our cold-outreach threads
    if doc.get("gmail_thread_id") and doc["gmail_thread_id"] in ctx.outreach_threads:
        return out("outreach_reply", "reply in a cold-outreach thread")

    # 3. confirmed noise senders -- checked before content, so a newsletter
    #    that mentions "pricing" is not filed as a proposal
    if _PROMO_FROM.search(sender) or _PROMO_SUBJECT.search(subject):
        return out("promotional", "newsletter / marketing sender or subject")
    if _AUTOMATED_FROM.search(sender) or _AUTOMATED_SUBJECT.search(subject):
        return out("automated", "notification platform / automated subject")

    # 4. banking & tax, then invoices. A bank that is also a client (IDFC's
    #    mystery-shopping work) is a client, not "banking".
    party = ctx.party(sender)
    if party is None and (_BANKING.search(sender) or _BANKING.search(subject)):
        return out("banking", "bank / tax authority")
    if _INVOICE.search(sender) or _INVOICE.search(subject):
        return out("invoice", "invoice / payment / statement")

    # 5. our own domain: an internal RFQ thread, a copy of our own bulk mail,
    #    or internal mail -- never "proposal" just because our pitch says so
    if _domain(sender) in OWN_DOMAINS:
        if _RFQ.search(head):
            return out("rfq", "internal mail in an RFQ thread")
        if ctx.is_bulk_subject(subject):
            return out("outreach", "copy of our own bulk mail")
        return out("internal", "sent from our own domain")

    # 6. a reply to a subject we mailed in bulk: a prospect answering outreach
    if _RFQ.search(subject) is None and ctx.is_bulk_subject(subject):
        return out("outreach_reply", "reply to one of our bulk outreach mails")

    # 7. content signals
    if _RFQ.search(head):
        return out("rfq", "RFQ / request for quote language")
    if _ACTIVE_DEAL.search(subject) or _ACTIVE_DEAL.search(text[:500]):
        return out("active_deal", "sign-off / PO / contract / next steps")
    if _PROPOSAL.search(head):
        return out("proposal", "proposal / quote / pricing discussion")

    # 8. who it is from
    if party:
        return out(party, "sender's company has sent us RFQs / won business" if party == "client"
                   else "sender is a Finance vendor")

    # 9. first contact
    if _NEW_INQUIRY.search(head):
        return out("new_inquiry", "first-contact / inquiry language")

    return {"category": "others", "reason": "no rule matched", "needs_ai": True}


def categorize_outbound(doc: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    subject = doc.get("subject") or ""
    recipients = [r.lower() for r in (doc.get("to_emails") or []) if isinstance(r, str)]

    def out(category, reason):
        return {"category": category, "reason": reason, "needs_ai": False}

    if doc.get("gmail_thread_id") and doc["gmail_thread_id"] in ctx.outreach_threads:
        return out("outreach", "our cold-outreach send")
    if recipients and all(_domain(r) in OWN_DOMAINS for r in recipients):
        return out("internal", "sent to our own domain only")
    if _INVOICE.search(subject):
        return out("invoice", "invoice / payment mail we sent")
    if _RFQ.search(subject):
        return out("rfq", "RFQ thread")
    if ctx.is_bulk_subject(subject):
        return out("outreach", "bulk outreach / marketing mail")
    if _ACTIVE_DEAL.search(subject):
        return out("active_deal", "sign-off / PO / contract / next steps")
    if _PROPOSAL.search(subject):
        return out("proposal", "proposal / quote / pricing")
    for r in recipients:
        party = ctx.party(r)
        if party:
            return out(party, f"sent to a known {party}")
    return out("others", "no rule matched (outbound)")


# ---------------------------------------------------------------------------
# local model for what the rules could not place
# ---------------------------------------------------------------------------
_MODEL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"category": {"type": "string", "enum": MODEL_CATEGORIES},
                   "reason": {"type": "string"}},
    "required": ["category", "reason"],
}
_MODEL_SYSTEM = (
    "You sort the inbound mailbox of a market-research fieldwork company. "
    "Pick exactly one category. JSON only.\n"
    "rfq = asks us for a quote/proposal for a project. "
    "active_deal = an agreed or in-progress project: sign-off, contract, PO, scheduling, delivery. "
    "proposal = discussion of a quote/proposal/pricing already exchanged. "
    "new_inquiry = someone new asking about our services. "
    "client = routine mail from a company that buys from us. "
    "vendor = mail from a supplier selling to us or supplying sample/services. "
    "invoice = bills, payments, receipts. "
    "promotional = newsletters, marketing, event invites. "
    "automated = system notifications. spam = unsolicited junk or scams. "
    "others = personal or anything else."
)


def model_categorize(doc: Dict[str, Any]) -> Tuple[Optional[str], str]:
    from leads.local_slm_client import LocalSLMError, chat_json
    from sales.reply_triage import strip_quoted
    body = strip_quoted(doc.get("body") or doc.get("body_plain") or doc.get("snippet") or "")
    user = (f"FROM: {doc.get('from_email') or ''}\nSUBJECT: {(doc.get('subject') or '')[:150]}\n\n"
            f"BODY:\n{body[:1000]}")
    try:
        out = chat_json(system=_MODEL_SYSTEM, user=user, max_tokens=120, json_schema=_MODEL_SCHEMA)
    except LocalSLMError as e:
        return None, f"model unavailable: {e}"[:300]
    cat = out.get("category")
    if cat not in MODEL_CATEGORIES:
        return None, "model returned an invalid category"
    return cat, str(out.get("reason") or "")[:300]


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------
def _update_for(result: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    fields = {
        "ai_tier1_category": result["category"],
        "ai_tier1_reason": result["reason"],
        "ai_tier1_source": SOURCE_RULES,
        "ai_tier1_status": "pending_ai" if result.get("needs_ai") else "done",
        "ai_tier1_at": now,
    }
    if result.get("system_subtype"):
        fields.update(email_type="system", system_subtype=result["system_subtype"],
                      ai_tier1_system_set=True)
    return fields


_PROJECTION = {"subject": 1, "from_email": 1, "to_emails": 1, "direction": 1, "gmail_thread_id": 1,
               "snippet": 1, "body": {"$substrCP": [{"$ifNull": ["$body_plain", ""]}, 0, 3000]}}


def run_rules_pass(client, ctx: Optional[Context] = None, limit: Optional[int] = None,
                   dry_run: bool = False, only_unlabelled: bool = True,
                   batch_size: int = 1000) -> Dict[str, Any]:
    """Categorise messages by rules. only_unlabelled=True touches only messages
    this module has never labelled (safe to run on every cycle)."""
    from pymongo import UpdateOne
    ctx = ctx or build_context(client)
    col = client["torpedo_gmail"]["email_metadata"]
    match = {"ai_tier1_status": {"$exists": False}} if only_unlabelled else {}
    pipeline = [{"$match": match}, {"$sort": {"timestamp": -1}}]
    if limit:
        pipeline.append({"$limit": limit})
    pipeline.append({"$project": _PROJECTION})

    now = datetime.utcnow()
    stats: Dict[str, Any] = {"processed": 0, "by_category": {}, "pending_ai": 0, "system": 0}
    ops: List[Any] = []
    for doc in col.aggregate(pipeline, allowDiskUse=True):
        if doc.get("direction") == "outbound":
            result = categorize_outbound(doc, ctx)
        else:
            result = categorize_inbound(doc, ctx)
        stats["processed"] += 1
        stats["by_category"][result["category"]] = stats["by_category"].get(result["category"], 0) + 1
        stats["pending_ai"] += int(bool(result.get("needs_ai")))
        stats["system"] += int(bool(result.get("system_subtype")))
        if not dry_run:
            ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": _update_for(result, now)}))
            if len(ops) >= batch_size:
                col.bulk_write(ops, ordered=False)
                ops = []
    if ops and not dry_run:
        col.bulk_write(ops, ordered=False)
    return stats


def model_verdict_fields(cat: str, reason: str, now: datetime) -> Dict[str, Any]:
    fields = {"ai_tier1_category": cat, "ai_tier1_reason": reason, "ai_tier1_source": SOURCE_AI,
              "ai_tier1_status": "done", "ai_tier1_at": now}
    if cat in UNTRUSTED_MODEL_CATEGORIES:
        fields.update(ai_tier1_category="others", ai_tier1_model_suggestion=cat,
                      ai_tier1_reason=f"possible {cat} (model only, unverified): {reason}"[:300])
    return fields


def run_ai_pass(client, limit: int = 10) -> Dict[str, int]:
    """Let the local model place the newest messages the rules left pending."""
    col = client["torpedo_gmail"]["email_metadata"]
    stats = {"attempted": 0, "resolved": 0, "unavailable": 0}
    docs = list(col.aggregate([
        {"$match": {"ai_tier1_status": "pending_ai"}},
        {"$sort": {"timestamp": -1}}, {"$limit": limit}, {"$project": _PROJECTION}]))
    for doc in docs:
        stats["attempted"] += 1
        cat, reason = model_categorize(doc)
        now = datetime.utcnow()
        if cat:
            col.update_one({"_id": doc["_id"]}, {"$set": model_verdict_fields(cat, reason, now)})
            stats["resolved"] += 1
        else:
            # Left pending; the next cycle retries it. A model outage is never
            # recorded as a verdict (see ai-outage-damage-pattern).
            stats["unavailable"] += 1
            if stats["unavailable"] >= 3:
                break  # abort on a streak rather than burn the whole batch
    return stats


def ensure_indexes(client) -> None:
    col = client["torpedo_gmail"]["email_metadata"]
    col.create_index([("ai_tier1_category", 1)], name="ai_tier1_category_1", background=True)
    col.create_index([("ai_tier1_status", 1), ("timestamp", -1)], name="ai_tier1_status_ts", background=True)


def run_scheduled_cycle() -> Dict[str, Any]:
    """APScheduler entry point: label new mail by rules, then let the model
    place a small, capped batch of the pending ones (newest first)."""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                         serverSelectionTimeoutMS=5000)
    ensure_indexes(client)
    rules = run_rules_pass(client, limit=5000)
    # ~15 calls x ~20s every 10 min keeps roughly half of the single shared
    # local-model slot free for live work (reply triage, nurture).
    ai = run_ai_pass(client, limit=int(os.getenv("MAIL_SEGREGATION_AI_PER_RUN", "15")))
    if rules["processed"] or ai["attempted"]:
        logger.info("[MailSegregation] rules=%s ai=%s", rules, ai)
    return {"rules": rules, "ai": ai}
