"""
Two-stage RFQ detection + extraction for the local small model.

Why two stages: the 2026-09-20 real-data benchmark showed the old single
"read a whole sender history and fill a 15-field template" prompt makes the
1.5B model fabricate an RFQ (invented budget, dates, an "evidence" quote, a
placeholder ref like "123456") for mail that plainly isn't one. A small model
shown a filled-in template tends to fill it in. So the job is split into
steps a small model is good at, with the checks that don't need a model done
in code:

  1. prefilter  (sales/mail_prefilter.py)  deterministic, no model
  2. classify   tiny yes/no question, ~8 output tokens
  3. extract    only on "yes": flat fields, "null if not stated"
  4. ground     drop any value the email text doesn't support (in code)

The ref is generated here (thread id), never by the model, and each RFQ records
the exact email it came from. Model failures RAISE -- they must never look like
"this email has no RFQ" (see deep_scan_sender_rfqs' completeness handling).
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from leads import local_slm_client as _slm
from sales import mail_prefilter

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "two_stage_v1"
CLASSIFY_MAX_TOKENS = 16
EXTRACT_MAX_TOKENS = 400
CLASSIFY_TIMEOUT_S = 60.0
EXTRACT_TIMEOUT_S = 90.0
CLASSIFY_BODY_CHARS = 1200
EXTRACT_BODY_CHARS = 2500


# Server-side grammar for both stages. The 1.5B model otherwise writes invalid
# JSON in ~20% of extractions (e.g. `"loi": 45 - 60`, markdown fences), which
# would leave those emails permanently un-scanned. Plain response_format
# "json_object" is a no-op on this llama.cpp build; a schema is enforced.
CLASSIFY_SCHEMA = {"type": "object", "additionalProperties": False,
                   "properties": {"is_rfq": {"type": "boolean"}}, "required": ["is_rfq"]}


def _nullable(t: str) -> Dict[str, Any]:
    return {"type": [t, "null"]}


_EXTRACT_PROPS = {
    "title": _nullable("string"), "summary": _nullable("string"),
    "sample_size": _nullable("integer"), "country": _nullable("string"),
    "target_audience": _nullable("string"), "methodology": _nullable("string"),
    "loi": _nullable("number"), "ir": _nullable("number"), "budget": _nullable("number"),
    "currency": _nullable("string"), "deadline": _nullable("string"),
    "timeline": _nullable("string"),
}
EXTRACT_SCHEMA = {"type": "object", "additionalProperties": False,
                  "properties": _EXTRACT_PROPS, "required": list(_EXTRACT_PROPS)}


class RFQModelError(Exception):
    """The model didn't answer or returned unusable output. Callers must leave
    the email for retry, never record it as 'no RFQ'."""


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------

_QUOTE_MARKERS = re.compile(
    r"\n\s*On .{5,150}wrote:|\n\s*-{2,}\s*Original Message|"
    r"\n\s*_{5,}\s*\n\s*From:|\n\s*From:\s.+\n\s*Sent:|\n\s*>",
    re.IGNORECASE,
)


def strip_quoted(body: str) -> str:
    """The newest message only: everything above the first quoted-history marker."""
    body = body or ""
    m = _QUOTE_MARKERS.search("\n" + body)
    top = body[: m.start()] if m else body
    return top.strip()


def _body_of(doc: Mapping[str, Any]) -> str:
    return str(doc.get("body_plain") or doc.get("body") or doc.get("snippet") or "")


# --------------------------------------------------------------------------
# stage 1: classify
# --------------------------------------------------------------------------

_CLASSIFY_SYSTEM = ("You sort incoming email for Cogentix, a market-research "
                    "sample and fieldwork company. Reply with one JSON object only.")

_CLASSIFY_INSTRUCTIONS = """Decide whether the email at the bottom is a NEW REQUEST FROM A CLIENT OR PARTNER asking Cogentix for a price, quote, feasibility or sample availability for a specific research study.

Answer {"is_rfq": true} only when the sender asks Cogentix to supply something (sample, completes, recruitment, fieldwork) and gives or points to study details.

Answer {"is_rfq": false} for everything else, including:
- someone selling or pitching a service to Cogentix (marketing, web design, software, data, leads)
- Cogentix staff writing (introductions, follow-ups, asking other suppliers for quotes)
- thanks, status updates, scheduling or approvals about a project already running
- invoices, payments, bank details, contracts, tax notices
- automated messages, newsletters, out-of-office replies
- a partnership or panel-integration discussion with no specific study to price

Examples:
Subject: Need CPI - 400 completes UK parents
Email: Hi team, please share CPI and feasibility for n=400, parents of kids 5-12, UK, 12 min, IR 20%.
Answer: {"is_rfq": true}

Subject: Request for quotation - physician recruitment
Email: We need 12 oncologists in Germany for 45-minute interviews. Kindly quote per complete and confirm you can start next month.
Answer: {"is_rfq": true}

Subject: Partnership opportunity
Email: We are an app developer and would love to sell you our respondent-engagement tool. Can we set up a demo?
Answer: {"is_rfq": false}

Subject: Re: Wave 3 tracker
Email: Thanks for the update. Please pause fieldwork until we confirm the new quotas.
Answer: {"is_rfq": false}

Subject: Invoice 4471 overdue
Email: Please confirm when payment for invoice 4471 will be released.
Answer: {"is_rfq": false}

Subject: Panel API integration
Email: Our tech team can share the API docs so your members can access our survey router. Which day works for a call?
Answer: {"is_rfq": false}

Now the email to judge.
"""


def _coerce_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes"):
            return True
        if s in ("false", "no"):
            return False
    return None


def classify_is_rfq(subject: str, from_email: str, body: str) -> bool:
    top = strip_quoted(body)[:CLASSIFY_BODY_CHARS]
    user = (f"{_CLASSIFY_INSTRUCTIONS}Subject: {subject or '(none)'}\n"
            f"From: {from_email or 'unknown'}\nEmail: {top or '(empty)'}\nAnswer:")
    try:
        parsed = _slm.chat_json(system=_CLASSIFY_SYSTEM, user=user,
                                max_tokens=CLASSIFY_MAX_TOKENS, timeout=CLASSIFY_TIMEOUT_S,
                                json_schema=CLASSIFY_SCHEMA)
    except _slm.LocalSLMError as e:
        raise RFQModelError(f"classify call failed: {e}") from e
    verdict = _coerce_bool(parsed.get("is_rfq"))
    if verdict is None:
        raise RFQModelError(f"classify returned no usable is_rfq: {parsed!r}")
    return verdict


# --------------------------------------------------------------------------
# stage 2: extract
# --------------------------------------------------------------------------

_EXTRACT_SYSTEM = ("You extract fields from a market-research request email. "
                   "Reply with one JSON object only.")

_EXTRACT_INSTRUCTIONS = """Extract the study details from the email at the bottom.
Rules: copy values exactly as written. Use null for anything the email does not explicitly state. Never guess, infer or calculate.

Return exactly this JSON object:
{"title": "<short descriptive title, max 8 words>",
 "summary": "<one sentence, max 25 words>",
 "sample_size": <number of completes/respondents requested, integer, or null>,
 "country": "<country or countries named, or null>",
 "target_audience": "<who should be surveyed, as written, or null>",
 "methodology": "<method named in the email, e.g. online survey, CATI, IDI, focus group, F2F, or null>",
 "loi": <interview length in minutes, number, or null>,
 "ir": <incidence rate as a percent number, or null>,
 "budget": <price or budget number stated, or null>,
 "currency": "<currency named, or null>",
 "deadline": "<deadline or field dates exactly as written, or null>",
 "timeline": "<project duration exactly as written, or null>"}

The email:
"""


def extract_fields(subject: str, body: str) -> Dict[str, Any]:
    user = (f"{_EXTRACT_INSTRUCTIONS}Subject: {subject or '(none)'}\n"
            f"{(body or '')[:EXTRACT_BODY_CHARS]}")
    try:
        return _slm.chat_json(system=_EXTRACT_SYSTEM, user=user,
                              max_tokens=EXTRACT_MAX_TOKENS, timeout=EXTRACT_TIMEOUT_S,
                              json_schema=EXTRACT_SCHEMA)
    except _slm.LocalSLMError as e:
        raise RFQModelError(f"extract call failed: {e}") from e


# --------------------------------------------------------------------------
# stage 3: grounding -- drop anything the email text doesn't support
# --------------------------------------------------------------------------

# What must appear within 40 chars of a number for it to count as that field.
# Word-boundary aware on purpose: a plain substring test lets "n " match inside
# "Jan 2026" and "ir" match inside "their", grounding an invented number.
_FIELD_CONTEXT = {
    "sample_size": re.compile(
        r"(?<![a-z])(n(?=\s*[=:]?\s*\d)|ss\b|sample|complete|respondent|interview|idis?\b|"
        r"participant|panelist|recruit|need|seat|target|quota|total)"),
    "loi": re.compile(r"(?<![a-z])(loi\b|min(?:s|ute|utes)?\b|length|duration|interview)"),
    "ir": re.compile(r"(?<![a-z])(ir\b|incidence|feasib)|%"),
    "budget": re.compile(r"[$€£₹]|(?<![a-z])(usd|eur|gbp|inr|cad|aud|cpi|budget|cost|price|"
                         r"rate|quote|fee)"),
}

_COUNTRY_ALIASES = {
    "us": ("us", "usa", "u.s.", "united states", "america"),
    "usa": ("us", "usa", "u.s.", "united states", "america"),
    "united states": ("us", "usa", "u.s.", "united states", "america"),
    "uk": ("uk", "u.k.", "united kingdom", "britain", "england"),
    "united kingdom": ("uk", "u.k.", "united kingdom", "britain", "england"),
    "australia": ("au", "aus", "australia"), "canada": ("ca", "can", "canada"),
    "germany": ("de", "germany", "deutschland"), "france": ("fr", "france"),
    "india": ("in", "india"), "japan": ("jp", "japan"), "china": ("cn", "china"),
    "brazil": ("br", "brazil", "brasil"), "mexico": ("mx", "mexico"),
    "south korea": ("kr", "korea"), "korea": ("kr", "korea"),
    "singapore": ("sg", "singapore"), "spain": ("es", "spain"), "italy": ("it", "italy"),
    "netherlands": ("nl", "netherlands", "holland"),
    "saudi arabia": ("ksa", "saudi"), "united arab emirates": ("uae",),
}

# A method term the model returns is grounded if the email uses it or a synonym.
_METHOD_SYNONYMS = (
    {"f2f", "face-to-face", "face to face", "capi", "in-person", "in person", "intercept"},
    {"idi", "in-depth", "in depth", "interview", "vdi", "video"},
    {"cati", "telephone", "phone", "call"},
    {"cawi", "online", "web", "internet"}, {"panel"}, {"survey"},
    {"focus group", "fgd", "group"},
    {"qual", "qualitative"}, {"quant", "quantitative"},
    {"mobile", "app"}, {"tracker", "tracking", "wave"}, {"diary"}, {"hybrid"},
)
_METHOD_TERM = re.compile("|".join(sorted({re.escape(t) for g in _METHOD_SYNONYMS for t in g},
                                          key=len, reverse=True)), re.IGNORECASE)


def _method_grounded(method: str, text: str) -> bool:
    low = text.lower()
    terms = {m.group().lower() for m in _METHOD_TERM.finditer(str(method))}
    if not terms:
        return False
    for term in terms:
        group = next((g for g in _METHOD_SYNONYMS if term in g), {term})
        if not any(re.search(rf"(?<![a-z]){re.escape(s)}(?![a-z])", low) for s in group):
            return False
    return True


_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}


def _currency_grounded(currency: str, text: str) -> bool:
    if re.search(rf"(?<![a-z]){re.escape(str(currency).lower())}(?![a-z])", text.lower()):
        return True
    return _CURRENCY_SYMBOLS.get(str(currency).upper(), "\0") in text


def _number_tokens(text: str) -> Tuple[List[Tuple[float, int, int]], str]:
    """(number, start, end) triples over the text with thousands separators
    removed ("11,000" -> 11000), plus that cleaned text."""
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    return ([(float(m.group()), m.start(), m.end())
             for m in re.finditer(r"\d+(?:\.\d+)?", cleaned)], cleaned)


def _num_grounded(value: Any, field_name: str, text: str) -> bool:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    tokens, cleaned = _number_tokens(text)
    low = cleaned.lower()
    context = _FIELD_CONTEXT[field_name]
    targets = {v}
    if field_name == "ir" and 0 < v <= 1:
        targets.add(round(v * 100, 4))
    for num, s, e in tokens:
        if any(abs(num - t) < 1e-9 for t in targets):
            if context.search(low[max(0, s - 40): e + 40]):
                return True
    return False


def _grounded_countries(value: str, text: str) -> Tuple[List[str], List[str]]:
    """Split a country list into (named in the email, not named)."""
    low = f" {text.lower()} "
    kept: List[str] = []
    lost: List[str] = []
    for part in re.split(r"[,/&;]| and ", str(value)):
        part = part.strip()
        if not part:
            continue
        forms = set(_COUNTRY_ALIASES.get(part.lower(), ())) | {part.lower()}
        hit = any(re.search(rf"(?<![a-z]){re.escape(f)}(?![a-z])", low) for f in forms)
        (kept if hit else lost).append(part)
    return kept, lost


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def _phrase_in(value: str, text: str) -> bool:
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    return bool(norm(value)) and norm(value) in norm(text)


def _parse_explicit_date(phrase: str) -> Optional[str]:
    if not re.search(r"\b(19|20)\d{2}\b", phrase):
        return None
    try:
        from dateutil import parser as _dp
        return _dp.parse(phrase, fuzzy=False).date().isoformat()
    except (ValueError, OverflowError, ImportError):
        return None


def ground_fields(fields: Mapping[str, Any], text: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return (grounded_fields, dropped). Nothing invented survives; missing is
    fine (a reviewer fills it), fabricated is not."""
    out: Dict[str, Any] = {}
    dropped: List[Dict[str, Any]] = []

    def drop(name: str, value: Any, why: str) -> None:
        dropped.append({"field": name, "value": value, "reason": why})

    for name in ("sample_size", "loi", "ir", "budget"):
        v = fields.get(name)
        if v in (None, "", 0):
            out[name] = None
        elif _num_grounded(v, name, text):
            out[name] = v
        else:
            out[name] = None
            drop(name, v, "number not found near a matching keyword in the email")

    country = fields.get("country")
    if country in (None, ""):
        out["country"] = None
    else:
        named, unnamed = _grounded_countries(country, text)
        out["country"] = ", ".join(named) or None
        if unnamed:
            drop("country", ", ".join(unnamed), "not named in the email")

    method = fields.get("methodology")
    if method in (None, ""):
        out["methodology"] = None
    elif _method_grounded(method, text):
        out["methodology"] = method
    else:
        out["methodology"] = None
        drop("methodology", method, "method not stated in the email")

    audience = fields.get("target_audience")
    if audience in (None, ""):
        out["target_audience"] = None
    else:
        aw, tw = _words(str(audience)), _words(text)
        if aw and len(aw & tw) / len(aw) >= 0.5:
            out["target_audience"] = audience
        else:
            out["target_audience"] = None
            drop("target_audience", audience, "wording not found in the email")

    currency = fields.get("currency")
    if currency in (None, ""):
        out["currency"] = None
    elif _currency_grounded(currency, text):
        out["currency"] = currency
    else:
        out["currency"] = None
        drop("currency", currency, "currency not named in the email")

    timeline = fields.get("timeline")
    deadline = fields.get("deadline")
    out["timeline"] = timeline if timeline and _phrase_in(str(timeline), text) else None
    if timeline and not out["timeline"]:
        drop("timeline", timeline, "phrase not in the email")
    out["deadline"] = None
    if deadline:
        if not _phrase_in(str(deadline), text):
            drop("deadline", deadline, "phrase not in the email")
        else:
            iso = _parse_explicit_date(str(deadline))
            if iso:
                out["deadline"] = iso
            elif not out["timeline"]:
                out["timeline"] = deadline   # keep the client's own words

    for name in ("title", "summary"):
        v = fields.get(name)
        out[name] = str(v).strip() if isinstance(v, str) and v.strip() else None
    return out, dropped


# --------------------------------------------------------------------------
# per-email pipeline
# --------------------------------------------------------------------------

@dataclass
class EmailResult:
    skipped_reason: Optional[str] = None
    is_rfq: Optional[bool] = None
    rfq: Optional[Dict[str, Any]] = None
    dropped: List[Dict[str, Any]] = field(default_factory=list)
    classify_s: float = 0.0
    extract_s: float = 0.0


def make_ref(doc: Mapping[str, Any]) -> str:
    thread = doc.get("gmail_thread_id")
    return f"thr-{thread}" if thread else f"em-{doc.get('_id')}"


def _classify_stage(doc: Mapping[str, Any], res: EmailResult) -> None:
    reason = mail_prefilter.skip_reason(doc)
    if reason:
        res.skipped_reason = reason
        return
    t0 = time.monotonic()
    res.is_rfq = classify_is_rfq(str(doc.get("subject") or ""),
                                 str(doc.get("from_email") or ""), _body_of(doc))
    res.classify_s = time.monotonic() - t0


def _extract_stage(doc: Mapping[str, Any], res: EmailResult, known_refs: Sequence[str]) -> None:
    ref = make_ref(doc)
    if ref in known_refs:        # a later mail in a thread we already have: no second RFQ
        return
    subject, body = str(doc.get("subject") or ""), _body_of(doc)
    t1 = time.monotonic()
    raw = extract_fields(subject, body[:EXTRACT_BODY_CHARS])
    res.extract_s = time.monotonic() - t1
    grounded, res.dropped = ground_fields(raw, subject + "\n" + body)
    res.rfq = {
        "ref": ref,
        "title": grounded.get("title") or subject[:80] or "RFQ",
        "description": grounded.get("summary"),
        "budget": grounded.get("budget"), "currency": grounded.get("currency"),
        "items": [], "deadline": grounded.get("deadline"),
        "email_date": str(doc.get("date") or doc.get("timestamp") or ""),
        "status": "open",
        "methodology": grounded.get("methodology"), "loi": grounded.get("loi"),
        "ir": grounded.get("ir"), "sample_size": grounded.get("sample_size"),
        "country": grounded.get("country"), "study_type": None,
        "target_audience": grounded.get("target_audience"),
        "timeline": grounded.get("timeline"),
        "source_email_id": str(doc.get("_id")) if doc.get("_id") is not None else None,
        "grounding_dropped": res.dropped, "pipeline": PIPELINE_VERSION,
        "extracted_at": datetime.utcnow().isoformat(),
    }


def analyze_email(doc: Mapping[str, Any], known_refs: Sequence[str] = ()) -> EmailResult:
    """Run one email through prefilter -> classify -> extract -> ground.
    Raises RFQModelError if the model fails; never returns 'no RFQ' for that."""
    res = EmailResult()
    _classify_stage(doc, res)
    if res.is_rfq:
        _extract_stage(doc, res, known_refs)
    return res


def analyze_chunk(docs: Sequence[Mapping[str, Any]],
                  known_refs: Sequence[str] = ()) -> List[EmailResult]:
    """Same result per email as analyze_email, but every classification runs
    before any extraction. Consecutive classify calls share the fixed
    instruction/example prefix, which the server keeps cached; alternating with
    extraction (a different prefix) throws that cache away every time."""
    results = [EmailResult() for _ in docs]
    for doc, res in zip(docs, results):
        _classify_stage(doc, res)
    known = list(known_refs)
    for doc, res in zip(docs, results):
        if res.is_rfq:
            _extract_stage(doc, res, known)
            if res.rfq:
                known.append(res.rfq["ref"])
    return results


def scan_chunk(open_ledger: Sequence[Mapping[str, Any]],
               chunk_docs: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop-in for the old chunk scan. Returns None if ANY model call fails, so
    the caller treats the chunk as un-scanned and retries it."""
    known = [r.get("ref") for r in open_ledger if r.get("ref")]
    try:
        results = analyze_chunk(chunk_docs, known)
    except RFQModelError as e:
        logger.warning("[mail-ai] two-stage scan failed, chunk left for retry: %s", e)
        return None
    new_rfqs = [r.rfq for r in results if r.rfq]
    stats = {"skipped": sum(1 for r in results if r.skipped_reason),
             "classified_no": sum(1 for r in results if r.is_rfq is False),
             "known_thread": sum(1 for r in results if r.is_rfq and not r.rfq),
             "rfq": len(new_rfqs)}
    return {"new_rfqs": new_rfqs, "rfq_updates": [], "stats": stats}
