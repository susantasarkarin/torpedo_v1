"""
Reply triage: label a reply to cold outreach as positive / negative /
needs_human / auto_reply, so the Leads page can show it and positive leads can
enter nurture (sales/nurture.py).

Why it is built this way (validated 2026-09-26 on 51 real replies):
- The raw reply body carries the whole quoted thread, including OUR pitch
  ("Open to a short chat?", "2M+ respondents..."). The local model read that
  text as the prospect's interest -- ~43% of its "Interested" calls were
  declines. So the quoted thread is stripped before anything looks at it.
- Clear declines, unsubscribes, legal threats and auto-replies are decided by
  deterministic rules; the local model only sees what the rules could not
  decide, with a 3-way schema-constrained output.
- A model-only "positive" is never trusted blindly: see POSITIVE_POLICY.
"""
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

VERDICTS = ("positive", "negative", "needs_human", "auto_reply")

# ---------------------------------------------------------------------------
# 1. Strip the quoted thread
# ---------------------------------------------------------------------------
_QUOTE_START = re.compile(
    r"^\s*(?:"
    r"from:\s|de:\s|da:\s|von:\s|van:\s|envoy[ée] par|"
    r"-{2,}\s*original message|_{8,}|"
    r"on .{3,160}wrote:|le .{3,120}a [ée]crit|am .{3,120}schrieb|"
    r"sent from my |get outlook for |"
    r"caution:|external email|this message is from an external sender|"
    r"you don'?t often get email from"
    r")",
    re.IGNORECASE,
)
# Outlook sometimes puts "From: x Sent: y To: z Subject:" on one line.
_INLINE_HEADER = re.compile(r"\bfrom:\s.{0,200}?\bsent:\s", re.IGNORECASE)


def strip_quoted(body: Optional[str]) -> str:
    """Return only what the replier wrote, above the quoted thread."""
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    m = _INLINE_HEADER.search(text)
    if m:
        text = text[:m.start()]
    kept = []
    for line in text.split("\n"):
        if _QUOTE_START.match(line) or line.lstrip().startswith(">"):
            break
        kept.append(line)
    out = "\n".join(kept).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


# ---------------------------------------------------------------------------
# 2. Deterministic rules
# ---------------------------------------------------------------------------
def _any(patterns, text, flags=re.IGNORECASE):
    for p in patterns:
        m = re.search(p, text, flags)
        if m:
            return m.group(0)
    return None


_LEGAL = [
    r"\blegal action\b", r"\blawyer", r"\battorney\b", r"\bgdpr\b",
    r"\bcease and desist\b", r"\breport(?:ed|ing)? (?:you|this|it) (?:as|for) spam\b",
    r"\bharass",
]
_AUTO_REPLY = [
    r"\bout of (?:the )?office\b", r"\bautomatic reply\b", r"\bauto-?reply\b",
    r"\bi am (?:currently )?(?:away|on (?:annual |maternity |paternity )?leave|travell?ing)\b",
    r"\bi'?m (?:currently )?(?:away|on (?:annual )?leave)\b",
    r"\blimited access to (?:my )?e-?mail\b", r"\bno longer (?:with|at|employed)\b.{0,60}\b(?:please contact|reach out to)\b",
]
_UNSUBSCRIBE = [
    r"\bunsubscribe\b", r"\b(?:remove|take|keep) (?:me|us|my (?:name|email))\b.{0,30}\b(?:from|off)\b",
    r"\b(?:stop|end|do not|don'?t) (?:e-?mailing|emailing|contacting|sending|email) (?:me|us)\b",
]
_DECLINE = [
    r"\bnot interested\b",
    r"\bno (?:need|requirement|requirements|use) (?:for (?:this|that|it)|at (?:the moment|this time|present))\b",
    r"\b(?:there is|we have) no need\b", r"\bno need for (?:this|that|it)\b",
    r"\bdon'?t (?:see|have) (?:an? |any )?(?:opportunity|possibility|need|requirement)",
    r"\b(?:do not|don'?t) have (?:any(?:thing)?|nay|an?)? ?(?:active |specific |current |upcoming )?(?:projects?|requirements?|needs?|anything)\b",
    r"\b(?:do not|don'?t) need (?:any|this|it|your)\b",
    r"\bnothing (?:needed|required|at the moment)\b",
    r"\bno (?:active|current|upcoming|specific) (?:projects?|requirements?|needs?)\b",
    r"\bnot (?:currently )?(?:looking|in a position|out ?sourc)",
    r"\bnot looking forward to\b",
    r"\bno longer (?:working|in|involved)\b",
    r"\b(?:ceased trading|closed down|no longer (?:in business|trading|operating))\b",
    r"\bnot responsible for\b",
    r"\bvery low volume\b",
    r"\b(?:we|i) (?:revert|go|stick) to our own\b", r"\bour own field (?:team|coordinators)\b",
    r"\bwe (?:do|handle) (?:this|it|that) in-?house\b",
    r"\b(?:will|shall|would) (?:definitely |surely |certainly )?(?:reach out|reach you|connect|contact you|get in touch|circle back|remind the team)\b.{0,80}\b(?:if|when|once|should|whenever)\b",
    r"\b(?:do not|don'?t) (?:ever )?(?:purchase|buy|use|need) (?:sample|such|these|this service)\b",
    r"\bwrong (?:audience|person|contact)\b",
    r"\b(?:if|when|once|whenever|should) (?:we|i|our)\b.{0,40}\b(?:ever )?(?:need|have a need|needs change|requirement)",
    r"\bif we ever need\b",
]
# Case-sensitive on purpose: "[A-Z][a-z]+" must be a capitalised name, not
# "speak to are" out of a quoted pitch.
_REFERRAL = [
    r"\b(?i:you are now in contact with)\b", r"\b(?i:is|are) (?i:handled by)\b",
    r"\b(?i:please )?(?i:reach out|speak|talk|write) (?i:to) (?:(?i:my colleague)|[A-Z][a-z]+)\b",
    r"\b(?i:not the right (?:person|contact|team))\b", r"\b(?i:the right person (?:is|would be))\b",
    r"\b(?i:contact (?:the )?local)\b",
]
# An explicit ask from the prospect -- the strongest positive signal a reply
# can carry, and one no quoted pitch text can fake once the quote is stripped.
_EXPLICIT_ASK = [
    r"\b(?:send|share|forward|provide|email)\b.{0,40}\b(?:deck|credentials|capabilit\w*|panel ?book|rate ?card|pric\w*|quote|quotation|proposal|details|information|info|case stud\w*|examples?|feasibility|costs?|cpi)\b",
    r"\b(?:could|can|would) you\b.{0,60}\b(?:share|send|provide|quote|confirm|take a look|let us know|check)\b",
    r"\bfeasibility\b", r"\b(?:rough )?estimate\b", r"\bcpi'?s?\b",
    r"\bcosts? for the following\b", r"\bwhat markets\b", r"\bare you supporting\b",
    r"\b(?:let'?s|happy to|would love to|we can|i can) (?:talk|connect|chat|hop on|jump on|schedule|set up|do this|move forward|meet)\b",
    r"\bmove forward\b", r"\bworks? for (?:me|us)\b",
    r"\b(?:tomorrow|today|monday|tuesday|wednesday|thursday|friday)\b.{0,20}\b\d{1,2}(?::\d\d)?\s*(?:am|pm)\b",
    r"^\s*yes\b", r"\bsounds (?:good|great|interesting)\b",
    r"\bkindly share\b",
    r"\bschedule (?:a |the )?(?:meeting|call)\b", r"\bworks? for you\b",
    r"\bshall we (?:connect|talk|meet|speak|have a call)\b",
]
# The other side is quoting or selling to US (a vendor response, or a pitch
# back). Not a buying signal and not a decline -- a person should look.
_VENDOR_SIDE = [
    r"\b(?:attached|find)\b.{0,40}\b(?:cost sheet|our (?:quote|quotation|proposal|costs|rates|terms))\b",
    r"\bopportunity of pitching\b", r"\bindicative rates\b", r"\bcost per (?:1 )?minute\b",
    r"\bare you looking for an? .{0,60}\bprovider\b",
    r"\bwe can collaborate as an? (?:sample )?supplier\b",
]
_CALENDAR_SUBJECT = re.compile(r"^\s*(?:updated )?(?:invitation|accepted)\s*:", re.IGNORECASE)
_CALENDAR_BODY = re.compile(
    r"microsoft teams meeting|join zoom meeting|join with google meet|has invited you to|"
    r"invitation from google calendar", re.IGNORECASE)


def rule_verdict(reply: str) -> Optional[Dict[str, str]]:
    """Decide the clear cases. Returns None when the rules can't tell."""
    text = (reply or "").replace("’", "'").replace("‘", "'")
    if not text.strip():
        return {"verdict": "needs_human", "reason": "empty reply after stripping the quoted thread"}
    hit = _any(_LEGAL, text)
    if hit:
        return {"verdict": "needs_human", "reason": f"legal/complaint language: {hit!r}"}
    hit = _any(_UNSUBSCRIBE, text)
    if hit:
        return {"verdict": "negative", "reason": f"asked to be removed: {hit!r}"}
    hit = _any(_AUTO_REPLY, text)
    if hit:
        return {"verdict": "auto_reply", "reason": f"auto-reply: {hit!r}"}
    hit = _any(_VENDOR_SIDE, text)
    if hit:
        return {"verdict": "needs_human", "reason": f"they are quoting/selling to us: {hit!r}"}

    decline = _any(_DECLINE, text)
    ask = _any(_EXPLICIT_ASK, text)
    if decline and ask:
        return {"verdict": "needs_human",
                "reason": f"mixed signals: decline {decline!r} and ask {ask!r}"}
    if decline:
        return {"verdict": "negative", "reason": f"decline: {decline!r}"}
    if ask:
        return {"verdict": "positive", "reason": f"explicit ask: {ask!r}"}
    referral = _any(_REFERRAL, text, flags=0)
    if referral:
        return {"verdict": "needs_human", "reason": f"referral to someone else: {referral!r}"}
    return None


# ---------------------------------------------------------------------------
# 3. Local model for what the rules could not decide
# ---------------------------------------------------------------------------
_MODEL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["positive", "negative", "needs_human"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}

_MODEL_SYSTEM = (
    "You label a prospect's reply to a B2B sales email. Output JSON only.\n"
    "positive = the prospect shows interest: asks for information, pricing, a quote,"
    " a call, or wants to proceed.\n"
    "negative = the prospect declines, says there is no need now, says they will get"
    " in touch later if needed, or asks to stop emailing.\n"
    "needs_human = anything else: a referral to another person, an unrelated or"
    " operational message, a question that is not a buying signal, or you are unsure.\n"
    "A polite 'thank you' alone is needs_human, not positive."
)

# A model-only positive becomes needs_human with the proposal recorded, unless
# REPLY_TRIAGE_TRUST_MODEL_POSITIVE=true. Default off: this model's positive
# calls measured unreliable on real replies (see module docstring).
def _trust_model_positive() -> bool:
    return os.getenv("REPLY_TRIAGE_TRUST_MODEL_POSITIVE", "false").strip().lower() == "true"


def model_verdict(reply: str, subject: str = "") -> Optional[Dict[str, str]]:
    from leads.local_slm_client import LocalSLMError, chat_json
    user = f"SUBJECT: {subject[:150]}\n\nREPLY:\n{reply[:1200]}"
    try:
        out = chat_json(system=_MODEL_SYSTEM, user=user, max_tokens=120,
                        json_schema=_MODEL_SCHEMA)
    except LocalSLMError as e:
        logger.warning("reply triage: local model unavailable: %s", e)
        return None
    verdict = out.get("verdict")
    if verdict not in ("positive", "negative", "needs_human"):
        return None
    return {"verdict": verdict, "reason": str(out.get("reason") or "")[:300]}


def triage_reply(body: str, subject: str = "", use_model: bool = True) -> Dict[str, Any]:
    """Full triage. Always returns a verdict; never raises."""
    # A calendar invite (or acceptance) sent BY the prospect means they booked
    # a meeting. Checked on the raw body: invite separators look like quotes.
    reply = strip_quoted(body)
    # Only when nothing was written above the invite: a reply that quotes an
    # old invite under its own text is judged on that text, not the invite.
    is_invite_message = not reply.strip() and _CALENDAR_BODY.search((body or "")[:800])
    if _CALENDAR_SUBJECT.search(subject or "") or (
            is_invite_message and not (subject or "").lower().startswith("declined")):
        return {"reply_text": reply[:1500] or (subject or "")[:200],
                "verdict": "positive", "method": "rules",
                "reason": "prospect sent/accepted a meeting invite"}
    result: Dict[str, Any] = {"reply_text": reply[:1500]}

    ruled = rule_verdict(reply)
    if ruled:
        result.update(ruled, method="rules")
        return result

    proposed = model_verdict(reply, subject) if use_model else None
    if not proposed:
        result.update(verdict="needs_human", method="fallback",
                      reason="rules undecided and the local model gave no answer")
        return result

    result["model_verdict"] = proposed["verdict"]
    if proposed["verdict"] == "positive" and not _trust_model_positive():
        result.update(verdict="needs_human", method="model_unconfirmed",
                      reason=f"model proposes positive (unconfirmed): {proposed['reason']}")
    else:
        result.update(verdict=proposed["verdict"], method="model",
                      reason=proposed["reason"])
    return result


# ---------------------------------------------------------------------------
# 4. Batch job
#
# The reply scanner (routers/cold_outreach_router.py) promotes each replier
# into email_automation.leads, but the Sales > Leads page reads
# email_automation.leads_enriched -- so until now ~73 of 76 replied prospects
# never appeared there. This job reads the scanner's promotions and writes the
# verdict onto the leads_enriched record the page shows, using the page's own
# lead_status field. A status a person set by hand is never overwritten.
# ---------------------------------------------------------------------------
NURTURE_AUTOSTART_MAX_AGE_DAYS = 14

LEAD_STATUS_FOR_VERDICT = {
    "positive": "Positive",
    "negative": "Negative",
    "needs_human": "Needs Human",
    "auto_reply": "Neutral",
}

_client = None


def _mongo():
    global _client
    if _client is None:
        from pymongo import MongoClient
        uri = os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return _client


def _latest_reply(gmail_db, email: str) -> Optional[Dict[str, Any]]:
    return gmail_db["email_metadata"].find_one(
        {"from_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"},
         "direction": "inbound"},
        {"body_plain": 1, "snippet": 1, "subject": 1, "gmail_message_id": 1,
         "gmail_thread_id": 1, "mailbox_id": 1, "timestamp": 1, "synced_at": 1},
        sort=[("timestamp", -1)],
    )


def _status_is_ours(enriched: Optional[Dict[str, Any]]) -> bool:
    """True when triage may set lead_status: no status yet, or the last one
    was set by triage itself. A human-set (or pre-existing, unlabelled)
    status always wins."""
    if not enriched or not enriched.get("lead_status"):
        return True
    # mail_pool_triage: the same rules run over the whole mail pool (sales/mailpool_leads.py)
    return enriched.get("lead_status_source") in ("reply_triage", "mail_pool_triage")


def apply_verdict(enriched_col, promoted: Dict[str, Any], triage: Dict[str, Any],
                  reply_doc: Optional[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """Write the verdict onto the leads_enriched record for this replier,
    creating it if the page has never seen them. Returns the enriched doc
    (post-update) plus whether triage owns its status."""
    email = (promoted.get("email") or "").strip().lower()
    verdict = triage["verdict"]
    enriched = enriched_col.find_one({"email": email})

    fields: Dict[str, Any] = {
        "outreach_replied_at": promoted.get("outreach_replied_at") or now,
        "outreach_campaign_id": promoted.get("outreach_campaign_id"),
        "reply_subject": (reply_doc or {}).get("subject") or promoted.get("reply_subject"),
        "reply_snippet": triage.get("reply_text", "")[:300] or promoted.get("reply_snippet"),
        "reply_sentiment": verdict,
        "reply_triage": {
            "verdict": verdict,
            "method": triage.get("method"),
            "reason": triage.get("reason"),
            "model_verdict": triage.get("model_verdict"),
            "reply_text": triage.get("reply_text", "")[:1500],
            "gmail_message_id": (reply_doc or {}).get("gmail_message_id"),
            "gmail_thread_id": (reply_doc or {}).get("gmail_thread_id"),
            "mailbox_id": (reply_doc or {}).get("mailbox_id"),
            "triaged_at": now,
        },
        "needs_human_review": verdict == "needs_human",
        "updated_at": now,
    }
    owns_status = _status_is_ours(enriched)
    if owns_status:
        fields["lead_status"] = LEAD_STATUS_FOR_VERDICT[verdict]
        fields["lead_status_source"] = "reply_triage"

    if enriched:
        enriched_col.update_one({"_id": enriched["_id"]}, {"$set": fields})
    else:
        doc = {
            "email": email,
            "source": "outreach_reply",
            "name": promoted.get("name") or "",
            "first_name": promoted.get("first_name") or promoted.get("firstName") or "",
            "company_name": promoted.get("company_name") or promoted.get("companyName") or "",
            "title": promoted.get("title") or "",
            "classification_basket": promoted.get("classification_basket") or "",
            "stage": "new",
            "created_at": now,
            "created_by": "reply_triage",
            **fields,
        }
        enriched_col.insert_one(doc)
    out = enriched_col.find_one({"email": email}) or {}
    out["_owns_status"] = owns_status
    return out


def honour_removal_request(email: str, triage: Dict[str, Any]) -> bool:
    """A reply asking to be removed is an opt-out: with the visible unsubscribe
    link switched off (owner, 2026-09-29) it is the only one, so it must stop
    all future mail -- not just label the lead Negative."""
    if triage.get("verdict") != "negative" or not str(triage.get("reason") or "").startswith("asked to be removed"):
        return False
    try:
        from services.outreach_unsubscribe import record_optout
        return record_optout(email, source="reply_asked_removal")
    except Exception as e:
        logger.warning("removal request for %s not recorded: %s", email, e)
        return False


def run_reply_triage_batch(limit: int = 20, use_model: bool = True) -> Dict[str, int]:
    """Triage replies the scanner promoted that have no verdict yet, or that
    got a newer reply since the last verdict. Starts nurture for fresh
    positives."""
    client = _mongo()
    ea = client["email_automation"]
    promoted_col, enriched_col = ea["leads"], ea["leads_enriched"]
    gmail_db = client["torpedo_gmail"]
    now = datetime.utcnow()
    stats = {"processed": 0, "positive": 0, "negative": 0, "needs_human": 0,
             "auto_reply": 0, "nurture_started": 0, "no_reply_found": 0}

    cursor = promoted_col.find(
        {"source": "outreach_reply",
         "$or": [{"reply_triaged_at": {"$exists": False}},
                 {"$expr": {"$gt": ["$outreach_replied_at", "$reply_triaged_at"]}}]},
    ).limit(limit)

    for promoted in cursor:
        email = (promoted.get("email") or "").strip().lower()
        if not email:
            continue
        reply_doc = _latest_reply(gmail_db, email)
        if not reply_doc:
            stats["no_reply_found"] += 1
        body = ((reply_doc or {}).get("body_plain") or (reply_doc or {}).get("snippet")
                or promoted.get("reply_snippet") or "")
        subject = (reply_doc or {}).get("subject") or promoted.get("reply_subject") or ""

        triage = triage_reply(body, subject, use_model=use_model)
        honour_removal_request(email, triage)
        enriched = apply_verdict(enriched_col, promoted, triage, reply_doc, now)
        promoted_col.update_one({"_id": promoted["_id"]}, {"$set": {
            "reply_triaged_at": now, "reply_sentiment": triage["verdict"]}})
        stats["processed"] += 1
        stats[triage["verdict"]] += 1

        if triage["verdict"] == "positive" and enriched.get("_owns_status"):
            replied_at = promoted.get("outreach_replied_at") or (reply_doc or {}).get("timestamp")
            fresh = isinstance(replied_at, datetime) and \
                replied_at >= now - timedelta(days=NURTURE_AUTOSTART_MAX_AGE_DAYS)
            if fresh:
                try:
                    from sales.nurture import start_nurture
                    if start_nurture(str(enriched["_id"]), started_by="reply_triage"):
                        stats["nurture_started"] += 1
                except Exception as e:  # nurture must never break triage
                    logger.warning("nurture start failed for %s: %s", email, e)

    if stats["processed"]:
        logger.info("[ReplyTriage] %s", stats)
    return stats
