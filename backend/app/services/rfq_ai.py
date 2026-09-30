"""
AI-first decisions for RFQs (owner, 2026-09-28: "AI should be your first
preference for decision making"), each checked against the mail before it is
stored.

The local model (Qwen 1.5B, shared single slot) decides; a guard verifies the
decision against the mail's own text, because this model states things that
are not there (asked about a mail that said nothing, it answered 1,000
completes and a 5,000 budget). A decision that fails its guard is not stored;
when the model is unavailable the rule-based reading stands and the decision
is retried later -- an outage is never written as a verdict.

  live_link()  did the client send the live survey link?  -> won, Online
               (owner rule: a live link from the client means the study is
               won and its methodology is online)
  quote()      what did we quote -- CPI, currency, total, taxes on top?
  is_rfq()     is this mail a client asking us for a quote?
"""
import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_URL = re.compile(r"https?://[^\s>\"\]]+", re.I)
_OUR_LINKS = re.compile(r"surveyfieldwork|cogentix|bimwave|force\.com|salesforce", re.I)
QUEUE_WAIT_SECONDS = 90


def _ask(system: str, user: str, schema: Dict[str, Any], max_tokens: int = 200) -> Optional[Dict[str, Any]]:
    """One model decision; None when the model is unavailable."""
    from leads.local_llm_gate import queue_wait
    from leads.local_slm_client import LocalSLMError, chat_json
    # 3,500 characters is ~900 tokens of English, but some mail (Arabic, CJK,
    # long tracking URLs) runs past the 2,048-token window; that is the
    # message's size, not an outage -- and treated as one, the same message
    # was retried every 2 minutes for hours (2026-09-30). Retry shorter.
    for limit in (3500, 1600, 700):
        try:
            with queue_wait(QUEUE_WAIT_SECONDS):
                return chat_json(system=system, user=user[:limit], max_tokens=max_tokens, json_schema=schema,
                                 timeout=120)
        except LocalSLMError as e:
            if "exceeds the available context" in str(e) and limit != 700:
                continue
            logger.warning("rfq_ai: model unavailable: %s", e)
            return None
    return None


# ---------------------------------------------------------------------------
# live link -> won, Online
# ---------------------------------------------------------------------------
_LIVE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "live_link_sent": {"type": "boolean"},
        "told_to_launch": {"type": "boolean"},
        "commissioned": {"type": "boolean"},
        "test_link_only": {"type": "boolean"},
        "study_name": {"type": "string", "maxLength": 100},
        "reason": {"type": "string", "maxLength": 160},
    },
    "required": ["live_link_sent", "told_to_launch", "commissioned", "test_link_only", "study_name", "reason"],
}
_LIVE_SYSTEM = (
    "You read an email a market-research client sent to their fieldwork supplier (us). "
    "live_link_sent = true only if THIS email itself gives us the LIVE survey link to start "
    "fieldwork (a URL presented as the live link, or 'the survey is live' with its link). "
    "Asking us for links, promising to send them later, sharing only a TEST link, or sending "
    "redirect/terminate links is NOT a live link. told_to_launch = true if the client tells us to "
    "launch / start / go live with the fieldwork now (e.g. 'test ID captured, please launch'). "
    "Saying the survey is NOT live, or asking us to pause, is false for both. commissioned = "
    "true if the client confirms they are going ahead with us: awards the study, says go ahead / "
    "good to go / on board, sends a PO number, or asks us to proceed with testing or launch. "
    "If the sender is a SUPPLIER quoting to us or asking us for our links, everything is false. "
    "test_link_only = true if only a test link is given. study_name = the study or project name "
    "the email is about. JSON only.")

# cheap pre-filter: only mails that could possibly carry a live link reach the model
_MAYBE_LIVE = re.compile(r"\blive\b|\bgo[- ]live\b|\blaunch", re.I)
_LIVE_WORD = re.compile(r"\blive\b", re.I)
_NOT_SURVEY = re.compile(r"linkedin\.|instagram\.|facebook\.|twitter\.|x\.com|youtube\.|google\.[a-z.]+/maps|"
                         r"wa\.me|whatsapp|calendly|zoom\.us|teams\.microsoft|aka\.ms|mailto:|"
                         r"\.(png|jpe?g|gif|svg|webp|ico|pdf|docx?|xlsx?)(\?|$)", re.I)
# "the market is not live", "is it live at your end?"
_NEGATED = re.compile(r"\b(not|isn'?t|never|no longer)\s+(yet\s+)?live\b|\blive at your end\?", re.I)
# the client tells us to start: "test ID is captured, please launch the study"
_LAUNCH = re.compile(r"\b(please|kindly|pls|plz|can you|go ahead and)\s+(launch|start|begin|kick ?off)\b[^.\n]{0,50}"
                     r"\b(fw|fieldwork|field work|study|survey|project|data collection|the link)\b|"
                     r"\bstart the (fw|fieldwork|field work)\b|\bmake (the )?study live\b|\bsoft launch\b", re.I)
# the client going ahead with us: "we would like to go ahead with this project", "good to go on
# board with you", "PO number A-17611", "proceed with testing", "we need to go live in field asap"
_COMMISSION = re.compile(
    r"\b(go(ing)? ahead with (this|the|you)|good to go|on ?board with you|award(ed)?\b[^.\n]{0,30}\b(you|study|project)|"
    r"\bcommission(ed|ing)?\b|\bpo (number|no\.?|#)|purchase order|proceed with (the )?(testing|launch|fieldwork|study)|"
    r"(need|want) to go live|launch (this|the study|the project) (asap|today|now))", re.I)
# ...but a supplier offering us: "we are feasible", "please share our/your live links"
_SUPPLIER_SIDE = re.compile(r"\bwe are feasible\b|\bshare (us )?the live links?\b|\bour (cpi|rates|pricing)\b", re.I)
_TEST_ONLY = re.compile(r"\btest(ing)?\s+links?\b", re.I)
_LIVE_OR_START = re.compile(r"\blive\s+(survey\s+)?links?\b|\bsurvey\s+links?\b|\bstart the (fw|fieldwork)\b|"
                            r"\blaunch\b|\bgo(ne)?\s+live\b", re.I)
# "please be on hold for the live link", "kindly send us the live links",
# "will share live link by tomorrow", "any update on the live links?"
_NOT_YET = re.compile(r"(on hold|wait(ing)?|send|share|provide|expect|update on|need|require|will)\b[^.\n]{0,40}\blive\b|"
                      r"\blive\b[^.\n]{0,30}\b(soon|tomorrow|once|shortly|later|will be|would be|is ready)\b", re.I)


def survey_urls(text: str):
    """Links that could be a survey: theirs, with a path or query -- not our
    redirects, not a homepage from a signature, not a social profile."""
    out = []
    for u in _URL.findall(text or ""):
        if _OUR_LINKS.search(u) or _NOT_SURVEY.search(u):
            continue
        rest = re.sub(r"^https?://[^/]+", "", u)
        if len(rest.strip("/")) >= 3:
            out.append(u)
    return out


def live_link_candidate(text: str) -> bool:
    return bool(_MAYBE_LIVE.search(text or "")) and bool(survey_urls(text))


def _guard_live(text: str) -> Optional[str]:
    """A survey link within a few lines after a 'live' that is not a request or
    a promise. Returns that link, else None."""
    for m in _LIVE_WORD.finditer(text):
        ctx = text[max(0, m.start() - 60):m.end() + 40]
        if _NOT_YET.search(ctx):
            continue
        urls = survey_urls(text[max(0, m.start() - 40):m.start() + 450])
        if urls:
            return urls[0]
    return None


_SIGN_OFF = re.compile(r"^\s*(regards|best regards|kind regards|warm regards|thanks\s*(&|and)\s*regards|"
                       r"many thanks|thanks|thank you|cheers|sincerely|best|br|rgds)\s*[,!.]?\s*$|"
                       r"^\s*(©|copyright|confidential|disclaimer|this (e-?mail|message) (and|is|may))", re.I)


def main_text(body: str) -> str:
    """The message itself: everything above the sign-off, so a signature link
    or a legal footer ('...commissioned...') cannot decide anything. Found
    live: Ipsos MENA's 'we shall contact you when the opportunity arises' was
    read as commissioned because of the disclaimer under it."""
    out = []
    for i, line in enumerate((body or "").splitlines()):
        if i > 0 and _SIGN_OFF.search(line):
            break
        out.append(line)
    return "\n".join(out)


_MAYBE_LAUNCH = re.compile(r"\blaunch|\bstart the (fw|fieldwork)|\bgo(ne)? live|\bstudy live|\bgo ahead|"
                           r"good to go|on ?board|commission|\bpo (number|no)|purchase order|proceed", re.I)


def live_link(subject: str, text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """-> (decision or None, status). status: 'ai', 'guard_rejected', 'unavailable', 'not_candidate'.

    The model decides; the checks run on the BODY (a subject like "Live Sound
    Engineers" once made a mail of test links look live):
      live link  -> a survey link near a 'live' that is not a request, a
                    promise or a negation, and not a test-links-only mail
      launch     -> the body instructs us to launch/start, not negated
    """
    body_only = main_text(text or "")
    if not (live_link_candidate(body_only) or _MAYBE_LAUNCH.search(body_only)):
        return None, "not_candidate"
    out = _ask(_LIVE_SYSTEM, f"SUBJECT: {subject}\n\n{body_only}", _LIVE_SCHEMA)
    if out is None:
        return None, "unavailable"
    negated = bool(_NEGATED.search(body_only))
    test_only = bool(_TEST_ONLY.search(body_only)) and not _LIVE_OR_START.search(body_only)
    supplier = bool(_SUPPLIER_SIDE.search(body_only))
    url = _guard_live(body_only)
    live_ok = bool(out.get("live_link_sent")) and bool(url) and not negated and not test_only and not supplier
    launch_ok = bool(out.get("told_to_launch")) and bool(_LAUNCH.search(body_only)) and not negated and not supplier
    commission_ok = bool(out.get("commissioned")) and bool(_COMMISSION.search(body_only)) and not supplier
    claimed = any(out.get(k) for k in ("live_link_sent", "told_to_launch", "commissioned"))
    if claimed and not (live_ok or launch_ok or commission_ok):
        return None, "guard_rejected"
    out["live_link_sent"] = live_ok
    out["told_to_launch"] = launch_ok
    out["commissioned"] = commission_ok
    out["url"] = url if live_ok else None
    return out, "ai"


# ---------------------------------------------------------------------------
# our quote
# ---------------------------------------------------------------------------
_QUOTE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "quoted": {"type": "boolean"},
        "cpi": {"type": ["number", "null"]},
        "total": {"type": ["number", "null"]},
        "currency": {"type": "string", "maxLength": 3},
        "taxes_extra": {"type": "boolean"},
    },
    "required": ["quoted", "cpi", "total", "currency", "taxes_extra"],
}
_QUOTE_SYSTEM = (
    "You read a reply a fieldwork company (us) sent to a client about a study. quoted = true if "
    "we state our price. cpi = the price per complete/interview/respondent as a number, null if "
    "not stated; total = a total price for the whole study, null if not stated. currency = ISO "
    "code (INR, USD, EUR, GBP, ...) only if the reply shows it, else empty. taxes_extra = true if "
    "taxes/GST are on top ('+ taxes'). Copy numbers exactly as written. JSON only.")


def _appears(value: Optional[float], text: str) -> bool:
    if not value:
        return False
    t = text.replace(",", "")
    v = float(value)
    cands = {f"{v:g}", f"{int(v)}" if v == int(v) else f"{v:g}", f"{v:.2f}", f"{v:.1f}"}
    return any(re.search(rf"(?<![\d.]){re.escape(c)}(?![\d])", t) for c in cands)


_CURRENCY_MARK = {"INR": r"INR|Rs\.?|₹", "USD": r"USD|US\$|\$", "EUR": r"EUR|€", "GBP": r"GBP|£"}


def quote(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """-> (quote or None, status). Guard: every number must be in the reply, and a
    currency only counts if the reply shows it."""
    out = _ask(_QUOTE_SYSTEM, text, _QUOTE_SCHEMA, max_tokens=120)
    if out is None:
        return None, "unavailable"
    if not out.get("quoted"):
        return {"quoted": False}, "ai"
    cpi = out.get("cpi") if _appears(out.get("cpi"), text) else None
    total = out.get("total") if _appears(out.get("total"), text) else None
    if not cpi and not total:
        return None, "guard_rejected"
    cur = (out.get("currency") or "").upper()
    mark = _CURRENCY_MARK.get(cur, re.escape(cur) if len(cur) == 3 else None)
    if not mark or not re.search(rf"(?<![A-Za-z]){mark}", text, re.I if cur != "USD" else 0):
        cur = None
    return {"quoted": True, "cpi": cpi, "total": total, "currency": cur,
            "taxes_extra": bool(out.get("taxes_extra"))}, "ai"


# ---------------------------------------------------------------------------
# is this an RFQ to us
# ---------------------------------------------------------------------------
_RFQ_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"asks_us_for_a_quote": {"type": "boolean"}, "reason": {"type": "string", "maxLength": 160}},
    "required": ["asks_us_for_a_quote", "reason"],
}
_RFQ_SYSTEM = (
    "We are a market-research fieldwork company. Does this email ask US to quote a price "
    "(costing, CPI, feasibility with cost) for a study or project? A newsletter, an invoice, a "
    "payment chase, a vendor selling to us, an introduction, or a question with no request for "
    "our price is false. JSON only.")


def is_rfq(subject: str, text: str) -> Tuple[Optional[bool], str]:
    out = _ask(_RFQ_SYSTEM, f"SUBJECT: {subject}\n\n{text}", _RFQ_SCHEMA, max_tokens=90)
    if out is None:
        return None, "unavailable"
    return bool(out.get("asks_us_for_a_quote")), (out.get("reason") or "")[:160]
