"""Mail summaries and human-sounding reply drafts, on the escalation ladder
(owner, 2026-10-25). Pure apart from the injected `model` (ladder.run).

summary  short mails are their own summary (no model); longer ones go up the
         ladder. Accepted only when every number in the summary is in the
         mail and it is short.
draft    a reply a person would write: greets by first name, answers what was
         asked, proposes one next step, nothing invented. Starts at Haiku (the
         1.5B does not write natural prose). Code checks reject placeholders,
         links, AI disclaimers, numbers/prices not in the mail or our facts,
         and anything too short or too long. A draft is NEVER sent from here:
         it is the suggested text on a Review Queue item for a person.
"""
import re
from typing import Any, Callable, Dict, List, Optional

SUMMARY_SCHEMA = {"type": "object", "required": ["summary"], "properties": {
    "summary": {"type": "string"}, "asks": {"type": "array", "items": {"type": "string"}},
    "deadline": {"type": ["string", "null"]}}}
SUMMARY_SYSTEM = ("Summarise the newest email in at most two short sentences for a busy account manager: who wants "
                  "what. List what the sender asks us to do (asks, up to 3, imperative, short) and any deadline they "
                  "state. Use only facts in the email. JSON only.")
DRAFT_SCHEMA = {"type": "object", "required": ["body"], "properties": {"body": {"type": "string"}}}

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_BAD = re.compile(r"\[[^\]]*\]|\{[^}]*\}|<[A-Z_]+_?\d*>|https?://|www\.|as an ai|language model|lorem|placeholder|"
                  r"insert |your name|\bxx+\b", re.I)
_PROMISE = re.compile(r"\bguarantee[ds]?\b|\bfree of (cost|charge)\b|\b100\s*%|\bdiscount\b|\bbest price\b", re.I)
_SIGNOFF = re.compile(r"\n\s*(best|kind|warm)?\s*regards,?.*$|\n\s*(thanks|thank you|cheers),?\s*\n.*$", re.I | re.S)


def _numbers(text: str) -> set:
    return {n.replace(",", "") for n in _NUM.findall(text or "")}


def summary_check(data: Any, clean: str) -> List[str]:
    if not isinstance(data, dict) or not (data.get("summary") or "").strip():
        return ["empty summary"]
    s = data["summary"].strip()
    probs = []
    if len(s) > 400:
        probs.append("summary longer than 400 characters")
    extra = _numbers(" ".join([s] + list(data.get("asks") or []))) - _numbers(clean)
    if extra:
        probs.append(f"numbers not in the mail: {', '.join(sorted(extra))}")
    if _BAD.search(s):
        probs.append("placeholder / link / AI text in summary")
    return probs


def summarize(msg: Dict[str, Any], text: str, model: Optional[Callable[..., Dict[str, Any]]],
              ref: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return None
    if len(t) <= 240:
        return {"summary": t, "asks": [], "deadline": None, "tier": "rules"}
    if model is None:
        return None
    r = model(task="mail_summary", system=SUMMARY_SYSTEM, subject=msg.get("subject") or "", body=text,
              schema=SUMMARY_SCHEMA, code_check=summary_check, ref=ref, enqueue_on_fail=False)
    if r.get("status") in ("ok", "review") and isinstance(r.get("data"), dict) and not r.get("problems"):
        return {**r["data"], "tier": r.get("tier")}
    return None


# ---------------------------------------------------------------- drafts

PURPOSE = {
    "positive_reply_draft": "They replied positively to our outreach. Thank them, answer anything they asked, and propose "
                            "one concrete next step (a short call this week, or that they share their next requirement).",
    "neutral_reply": "Reply helpfully to what they wrote. If they introduced a colleague, thank them and say we will "
                     "write to that person.",
    "rfq_ack": "They sent an RFQ. Acknowledge it, say we are checking feasibility and will come back with costs, and "
               "ask only for missing details listed in FACTS (if any).",
}


def draft_system(bu: str, bu_facts: Dict[str, Any], purpose: str) -> str:
    who = bu_facts.get("label") or bu
    sells = bu_facts.get("what_we_sell") or ""
    return (f"You write a reply email on behalf of {who}" + (f" ({sells})" if sells else "") + ". "
            f"{PURPOSE.get(purpose, PURPOSE['neutral_reply'])} "
            "Write like a person at a small research firm: warm, plain, specific, 40-140 words, short paragraphs. "
            "Start with 'Hi <first name>,'. No subject line, no signature or sign-off (it is added later), no links, "
            "no prices, discounts, guarantees, dates or numbers unless they appear in the email or FACTS. "
            "Do not invent capabilities. JSON only: {\"body\": \"...\"}.")


def draft_check_factory(first_name: Optional[str], facts_text: str):
    allowed = None

    def check(data: Any, clean: str) -> List[str]:
        nonlocal allowed
        if allowed is None:
            allowed = _numbers(clean) | _numbers(facts_text)
        if not isinstance(data, dict) or not (data.get("body") or "").strip():
            return ["empty draft"]
        body = data["body"].strip()
        words = len(body.split())
        probs = []
        if words < 30 or words > 170:
            probs.append(f"{words} words (30-170 wanted)")
        if _BAD.search(body):
            probs.append("placeholder, link or AI wording")
        if _PROMISE.search(body):
            probs.append("price / discount / guarantee language")
        extra = _numbers(body) - allowed
        if extra:
            probs.append(f"numbers not in the mail or facts: {', '.join(sorted(extra))}")
        if first_name and not re.match(rf"^(hi|hello|dear)\s+{re.escape(first_name)}\b", body, re.I):
            probs.append(f"does not greet {first_name} by name")
        return probs
    return check


def first_name(display: Optional[str], email: Optional[str]) -> Optional[str]:
    n = (display or "").strip().strip('"')
    if n and "@" not in n:
        part = re.split(r"[\s,]+", n)[0]
        if part.isalpha() and len(part) > 1:
            return part.capitalize()
    local = (email or "").split("@")[0]
    part = re.split(r"[._\-]", local)[0]
    return part.capitalize() if part.isalpha() and len(part) > 2 else None


def draft_reply(msg: Dict[str, Any], text: str, *, purpose: str, bu: str, bu_facts: Dict[str, Any],
                model: Optional[Callable[..., Dict[str, Any]]], extra_facts: str = "",
                ref: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if model is None or not (text or "").strip():
        return None
    fn = first_name(msg.get("from_name"), msg.get("from_email"))
    facts = f"FACTS: {bu_facts.get('what_we_sell') or ''} {extra_facts}".strip()
    r = model(task="reply_draft", system=draft_system(bu, bu_facts, purpose), subject=msg.get("subject") or "",
              body=f"{text}\n\n{facts}" + (f"\nSender first name: {fn}" if fn else ""), schema=DRAFT_SCHEMA,
              code_check=draft_check_factory(fn, facts), ref=ref, bu=bu, enqueue_on_fail=False)
    if r.get("status") in ("ok", "review") and isinstance(r.get("data"), dict) and not r.get("problems"):
        body = _SIGNOFF.sub("", r["data"]["body"].strip()).strip()
        subj = msg.get("subject") or ""
        return {"subject": subj if subj.lower().startswith("re:") else f"Re: {subj}".strip(), "body": body,
                "tier": r.get("tier")}
    return None
