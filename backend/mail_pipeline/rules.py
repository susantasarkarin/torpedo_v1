"""Deterministic parts of 3.3: bounce hard/soft by code, out-of-office return
date, reconnect-later date, transfer target, confirmation / redirect / RFQ
signals. Pure functions; all tested."""
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"

# ----------------------------------------------------------------- bounces
_DSN_STATUS = re.compile(r"(?:Status:\s*|\b)([245])\.(\d{1,3})\.(\d{1,3})\b")
_SMTP_CODE = re.compile(r"\b([45])(\d)(\d)[ -]")
_SOFT_PHRASES = re.compile(r"mailbox (is )?full|over quota|quota exceeded|temporar(y|ily)|try again later|"
                           r"deferred|rate limit|too many|greylist|server busy", re.I)
_HARD_PHRASES = re.compile(r"user unknown|no such user|does not exist|address rejected|recipient (address )?rejected|"
                           r"unknown recipient|mailbox unavailable|invalid recipient|account (has been )?disabled|"
                           r"no longer (works|employed)|address couldn'?t be found|wasn'?t found", re.I)
_FAILED_RCPT = re.compile(r"(?:Final-Recipient|Original-Recipient):\s*rfc822;\s*<?([^\s<>;]+@[^\s<>;]+)>?|"
                          r"(?:delivery to the following recipients? (?:failed|has failed)[^\n]*\n\s*)<?([^\s<>]+@[^\s<>]+)>?|"
                          r"your message (?:wasn'?t delivered|could not be delivered) to <?([^\s<>]+@[^\s<>]+)>?", re.I)


def parse_bounce(subject: str, body: str) -> Dict[str, Any]:
    """{'kind': 'hard'|'soft', 'code': '5.1.1'|None, 'recipient': addr|None}.
    Codes decide first (5.x.x hard except 5.2.2 mailbox-full; 4.x.x soft);
    phrases decide when no code is present; unknown defaults to hard (a
    bounce we cannot read is not retried)."""
    text = f"{subject}\n{body or ''}"
    code, kind = None, None
    m = _DSN_STATUS.search(text)
    if m:
        code = ".".join(m.groups())
        kind = "soft" if m.group(1) == "4" or code == "5.2.2" else ("hard" if m.group(1) == "5" else None)
    if not kind:
        s = _SMTP_CODE.search(text)
        if s:
            code = "".join(s.groups())
            kind = "soft" if s.group(1) == "4" or code == "552" else "hard"
    if not kind:
        kind = "soft" if _SOFT_PHRASES.search(text) and not _HARD_PHRASES.search(text) else "hard"
    rm = _FAILED_RCPT.search(body or "")
    rcpt = next((g for g in (rm.groups() if rm else ()) if g), None)
    return {"kind": kind, "code": code, "recipient": (rcpt or "").strip(".,;").lower() or None}


# ------------------------------------------------------------------- dates
def _year_for(month: int, day: int, ref: date) -> date:
    d = date(ref.year, month, day)
    return d if d >= ref - timedelta(days=1) else date(ref.year + 1, month, day)


def _parse_date_phrase(s: str, ref: date) -> Optional[date]:
    s = s.strip().lower()
    m = re.match(rf"{_DAY}\s+(?:of\s+)?{_MONTH_RE}\.?,?\s*(\d{{4}})?", s)
    if m:
        d, mon, y = int(m.group(1)), MONTHS[m.group(2)[:3]], m.group(3)
        return date(int(y), mon, d) if y else _year_for(mon, d, ref)
    m = re.match(rf"{_MONTH_RE}\.?\s+{_DAY},?\s*(\d{{4}})?", s)
    if m:
        mon, d, y = MONTHS[m.group(1)[:3]], int(m.group(2)), m.group(3)
        return date(int(y), mon, d) if y else _year_for(mon, d, ref)
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", s)
    if m:     # day-first (India/UK/EU); US-style month-first mails are rarer here
        d, mon = int(m.group(1)), int(m.group(2))
        if mon > 12:
            d, mon = mon, d
        y = m.group(3)
        try:
            if y:
                return date(int(y) + (2000 if len(y) == 2 else 0), mon, d)
            return _year_for(mon, d, ref)
        except ValueError:
            return None
    return None


_OOO_RETURN = re.compile(r"(?:until|till|through|thru|back (?:in the office )?on|back by|returning(?: on)?|return(?:ing)? to the office on|"
                         r"will be back(?: on)?|in the office on|resume(?: work)? on)\s+(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+)?"
                         rf"({_DAY}\s+(?:of\s+)?{_MONTH_RE}\.?,?\s*\d{{0,4}}|{_MONTH_RE}\.?\s+{_DAY},?\s*\d{{0,4}}|\d{{4}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}[/.-]\d{{1,2}}(?:[/.-]\d{{2,4}})?)",
                         re.I)


def ooo_return_date(text: str, received: datetime) -> Optional[date]:
    """The date they say they are back. 'Until 3 Nov' means back on the 3rd
    or later; the caller adds one working day (3.3)."""
    m = _OOO_RETURN.search(text or "")
    if not m:
        return None
    d = _parse_date_phrase(m.group(1), received.date())
    return d if d and d >= received.date() - timedelta(days=1) else None


def next_working_day(d: date, days: int = 1) -> date:
    out = d
    while days > 0:
        out += timedelta(days=1)
        if out.weekday() < 5:
            days -= 1
    return out


_RECONNECT = re.compile(r"(?:reach out|get back|contact (?:me|us)|connect|touch base|follow up|reconnect|circle back|"
                        r"talk|speak|revisit|check (?:back|in))(?: with (?:me|us))?(?: again)?\s+"
                        r"(?:in|after|next|around|by|in about)\s+(?:a\s+|(\d+|a few|couple of)\s+)?"
                        r"(day|week|month|quarter|year|"
                        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)",
                        re.I)
_LATER_VAGUE = re.compile(r"\b(not (right )?now|later this year|next quarter|after (the )?(holidays|diwali|budget)|"
                          r"maybe later|some other time|in a while|down the line|not at this (time|moment))\b", re.I)


def reconnect_date(text: str, received: datetime, default_days: int = 14) -> Optional[date]:
    """Date to follow up when they ask to reconnect later; None if they did not."""
    m = _RECONNECT.search(text or "")
    ref = received.date()
    if m:
        n_raw, unit = (m.group(1) or "1").lower(), m.group(2).lower()
        n = {"a few": 3, "couple of": 2}.get(n_raw, int(n_raw) if n_raw.isdigit() else 1)
        if unit.startswith("day"):
            return ref + timedelta(days=n)
        if unit.startswith("week"):
            return ref + timedelta(weeks=n)
        if unit.startswith("month"):
            return ref + timedelta(days=30 * n)
        if unit.startswith("quarter"):
            return ref + timedelta(days=91 * n)
        if unit.startswith("year"):
            return ref + timedelta(days=365 * n)
        mon = MONTHS[unit[:3]]
        return _year_for(mon, 1, ref + timedelta(days=1))
    if _LATER_VAGUE.search(text or ""):
        return ref + timedelta(days=default_days)
    return None


# ------------------------------------------------------- transfer, signals
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TRANSFER = re.compile(r"\b(not the right (person|contact)|wrong person|no longer (handle|responsible|with)|"
                       r"(please )?(contact|reach out to|speak (to|with)|write to|connect with|loop(ing)? in|cc'?ing|copying)\b.{0,60}@|"
                       r"(he|she|they) (handles?|looks? after|is responsible for)|forward(ed|ing)? (this|your (mail|email)) to)", re.I)


def transfer_target(text: str, our_domains, sender: str) -> Optional[str]:
    """An address they point us to, if the reply is a hand-off."""
    if not _TRANSFER.search(text or ""):
        return None
    sender = (sender or "").lower()
    for e in _EMAIL.findall(text or ""):
        e = e.lower().strip(".")
        if e != sender and e.split("@")[1] not in our_domains:
            return e
    return "unknown"    # a hand-off without an address: a person finds the contact


_CONFIRM = re.compile(r"\b(go ahead|please proceed|you may proceed|green ?light|we('d| would)? like to proceed|"
                      r"(project|study) (is )?(awarded|confirmed|approved)|awarded to you|po (attached|is attached|enclosed|number)|"
                      r"purchase order (attached|enclosed|number|no)|let'?s (go|start|kick ?off)|approved the (quote|proposal|cost))\b", re.I)
_REDIRECT = re.compile(r"\b(redirects?|redirect links?|(complete|terminate|termination|quota ?full|over ?quota|security) (url|link)s?|"
                       r"end links?|exit links?)\b", re.I)
_ASK = re.compile(r"\b(share|send|provide|need|please|can you|could you|kindly)\b", re.I)
_RFQ_SIGNAL = re.compile(r"(?<![a-z])(rfq|rfp)(?![a-z])|request for (quote|quotation|proposal)|\b(quote|cpi|costing|feasibility)\b", re.I)
_SPEC = re.compile(r"\bloi\b|\bir\b|incidence|\bn\s*[=:]|sample size|completes|\btg\b|target group", re.I)


def signals(text: str) -> Dict[str, bool]:
    t = text or ""
    return {
        "confirmation": bool(_CONFIRM.search(t)),
        "redirect_request": bool(_REDIRECT.search(t) and _ASK.search(t)),
        "rfq": bool(_RFQ_SIGNAL.search(t) and _SPEC.search(t)) or bool(re.search(r"(?<![a-z])rfq(?![a-z])", t, re.I)),
        "has_spec": bool(_SPEC.search(t)),
    }


_PO = re.compile(r"\b(?:P\.?\s?O\.?|Purchase\s+Order)\s*(?:No\.?|Number|Num|#|Ref(?:erence)?)?\s*[:#.\-]?\s*"
                 r"([A-Z0-9][A-Z0-9/\-]{3,30})", re.I)
_QUOTED = re.compile(r"\nOn .{5,120}wrote:|\nFrom: |\n-{3,} ?Original Message")


def po_numbers(text: str) -> List[str]:
    """Client PO numbers ("PO", "P.O.", "Purchase Order", "PO No") in the new part of a mail."""
    t = _QUOTED.split(text or "")[0]
    out = []
    for m in _PO.findall(t):
        m = m.strip("-/.")
        if re.search(r"\d", m) and m.upper() not in out and not re.fullmatch(r"(?i)box\d*", m):
            out.append(m.upper())
    return out[:3]
