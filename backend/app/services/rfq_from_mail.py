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
from typing import Any, Dict, List, Optional, Tuple

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


_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ltd", "plc"}
_PERSONISH = re.compile(r"[(|_@]|\s-\s")


def registrable_root(domain: str) -> str:
    """research.clearlightscope.com -> clearlightscope; acme.co.uk -> acme."""
    labels = [l for l in (domain or "").lower().split(".") if l]
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        return labels[-3]
    return labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")


def _account_for(crm_service, accounts_col, email: str) -> Dict[str, Any]:
    """The company's CRM account: one already linked to its website, else an
    existing account with a clean name matching its domain ("Hansa Research
    Group" for hansaresearch.com -- names like "Adarsh V (Phoenixdatainnov)"
    are people, not companies), else a new account named after the domain."""
    domain = mc._domain(email)
    if not domain or domain in mc.WEBMAIL:
        acc, _ = crm_service.get_or_create_account(email, {})
        return acc
    root = registrable_root(domain)
    site = accounts_col.find_one({"website": {"$regex": re.escape(root) + r"\.[a-z.]+/?$", "$options": "i"}})
    named = []
    if len(root) >= 4:
        named = [a for a in accounts_col.find({"name": {"$regex": "^" + re.escape(root[:4]), "$options": "i"}},
                                               {"name": 1})
                 if not _PERSONISH.search(a.get("name") or "")
                 and root in re.sub(r"[^a-z0-9]", "", (a.get("name") or "").lower())]
    # A real company name ("Hansa Research Group") beats one that is just the
    # domain ("Hansaresearch"), even when the domain-named one carries the
    # website -- earlier backfills created those from the email address.
    proper = [a for a in named if re.sub(r"[^a-z0-9]", "", a["name"].lower()) != root]
    if proper:
        best = min(proper, key=lambda a: len(a["name"]))
        return {"_id": str(best["_id"]), "name": best["name"]}
    if site:
        return {"_id": str(site["_id"]), "name": site.get("name")}
    if named:
        best = min(named, key=lambda a: len(a["name"]))
        return {"_id": str(best["_id"]), "name": best["name"]}
    acc, _ = crm_service.get_or_create_account(root.replace("-", " ").title(), {"website": root_site(domain)})
    return acc


def root_site(domain: str) -> str:
    root = registrable_root(domain)
    i = domain.lower().find(root)
    return domain[i:] if i >= 0 else domain


def relink_accounts(client, created_since: datetime) -> Dict[str, int]:
    """Re-resolve the account of every rebuilt RFQ (after the naming rule
    changed) and drop accounts this module created that nothing uses now."""
    from bson import ObjectId
    from app.services import crm_service
    crm = client["crm_db"]
    moved = 0
    for o in crm["opportunities"].find({"metadata.rfq.source": SOURCE},
                                       {"account_id": 1, "contact_id": 1, "metadata.rfq.from_email": 1}):
        acc = _account_for(crm_service, crm["accounts"], ((o.get("metadata") or {}).get("rfq") or {}).get("from_email") or "")
        if str(o.get("account_id")) != str(acc["_id"]):
            crm["opportunities"].update_one({"_id": o["_id"]}, {"$set": {
                "account_id": acc["_id"], "metadata.rfq.account_id": acc["_id"],
                "metadata.rfq.account_name": acc.get("name")}})
            crm["projects"].update_many({"opportunity_id": str(o["_id"])}, {"$set": {"account_id": acc["_id"]}})
            if o.get("contact_id"):
                try:
                    crm["contacts"].update_one({"_id": ObjectId(str(o["contact_id"]))},
                                               {"$set": {"account_id": acc["_id"]}})
                except Exception:
                    pass
            moved += 1
    used = {str(x) for x in crm["opportunities"].distinct("account_id")} | \
           {str(x) for x in crm["contacts"].distinct("account_id")}
    # Only accounts created since the rebuild began (the caller passes that
    # moment) -- never an older account someone else made.
    orphans = [a["_id"] for a in crm["accounts"].find({"created_at": {"$gte": created_since}}, {"_id": 1})
               if str(a["_id"]) not in used]
    if orphans:
        crm["accounts"].delete_many({"_id": {"$in": orphans}})
    return {"relinked": moved, "orphan_accounts_removed": len(orphans)}


def create_from_doc(client, doc: Dict[str, Any], now: datetime, key: Optional[str] = None,
                    via: str = "rfq thread") -> Tuple[str, bool]:
    """One RFQ from the client's first message of a thread -> (opportunity id,
    created as closed history?)."""
    from bson import ObjectId
    from app.services import crm_service
    em = client["torpedo_gmail"]["email_metadata"]
    opp = client["crm_db"]["opportunities"]
    sender = (doc.get("from_email") or "").strip().lower()
    ts = doc.get("timestamp") or now
    tid = doc.get("gmail_thread_id")
    key = key or f"{mc._domain(sender)}|{mc.normalize_subject(doc.get('subject'))}"
    account = _account_for(crm_service, client["crm_db"]["accounts"], sender)
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
        "created_via": via, "dedup_key": key})
    oid = res["opportunity"]["_id"]
    is_history = ts < now - timedelta(days=OPEN_DAYS)
    update = {"created_at": ts}
    if is_history:
        update.update(status="closed", closed_at=now, closed_by="rfq_from_mail",
                      closed_reason=f"historical RFQ (mail older than {OPEN_DAYS} days) -- outcome not recorded")
    opp.update_one({"_id": ObjectId(oid)}, {"$set": update})
    em.update_one({"_id": doc["_id"]}, {"$set": {"rfq_id": oid, "rfq_synced": True, "rfq_source": SOURCE}})
    return oid, is_history


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
        oid, is_history = create_from_doc(client, doc, now, key)
        stats["closed_history" if is_history else "open"] += 1
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


# ---------------------------------------------------------------------------
# our quote: CPI, currency, value -- read from our own reply in the thread
# ---------------------------------------------------------------------------
_CUR_CODES = ("INR|USD|EUR|GBP|AUD|CAD|SGD|AED|SAR|IDR|MYR|THB|VND|JPY|CNY|KRW|ZAR|CHF|HKD|NZD|PHP")
_CUR = rf"(\b(?:{_CUR_CODES})\b|Rs\.?|₹|US\$|\$|€|£)"
_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_PRICE = rf"(?:{_CUR}\s*{_NUM}|{_NUM}\s*{_CUR})"
_NOT_A_PRICE = re.compile(r"^\s*(%|percent|min|mins|minutes|days|weeks|hours|pp\b|respondents|completes)", re.I)
_TAXES = re.compile(r"^\s*\+?\s*(\(?\s*(local\s+)?taxes|tax\b|gst)", re.I)
# A price after a quote word, with words (never digits) in between:
# "CPI - 160", "Our quote for this study is INR 115+taxes", "CPI in this case is $10"
_LABELED = re.compile(rf"\b(cpi|quote|quotation|cost|rate|price|charges?|execute this study for)\b[^\d\n%]{{0,60}}?"
                      rf"(?:{_PRICE}|{_NUM})", re.I)
# A bare price with taxes on top: "INR 150+taxes"
_TAXED = re.compile(rf"{_PRICE}(?=\s*\+\s*(?:taxes|tax|gst))", re.I)
# "$10 per complete", "IDR 60,000 per visit", "150 INR per respondent"
_PER_UNIT = re.compile(rf"{_PRICE}\s*(?:per|/)\s*(?:complete|completed interview|interview|respondent|survey|"
                       r"visit|participant|recruit|head|session|group|id|audit)", re.I)
_N_BEFORE = re.compile(r"\bn\s*[=:]?\s*(\d[\d,]*)\s*\)?\s*:?\s*$", re.I)
_CUR_CODE = {"rs": "INR", "rs.": "INR", "₹": "INR", "us$": "USD", "$": "USD", "€": "EUR", "£": "GBP"}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _cur(token: Optional[str]) -> Optional[str]:
    t = (token or "").strip()
    return _CUR_CODE.get(t.lower()) or (t.upper() if re.fullmatch(_CUR_CODES, t, re.I) else None)


def _groups(m) -> Tuple[Optional[str], Optional[str]]:
    """(currency token, number) from a match of _PRICE / _NUM alternatives."""
    g = [x for x in m.groups() if x is not None]
    cur = next((x for x in g if _cur(x)), None)
    num = next((x for x in reversed(g) if re.fullmatch(_NUM, x)), None)
    return cur, num


def parse_quote(text: str) -> Optional[Dict[str, Any]]:
    """Our CPI quote from one of our replies, or None.
    -> {cpi, currency|None, lines: [{n|None, cpi}], taxes_extra: bool}

    Written against how we actually quote (2026-09-28 sample of 289 replies
    the first version missed): "Our quote for this study is INR 115+taxes",
    "CPI for this study is INR 130 + taxes", "CPI in this case is $10",
    "Can we execute this study for INR 130+taxes", a bare "INR 150+taxes",
    "rate is IDR 60,000 per visit". Percentages, minutes and day counts after
    the number are not prices; a bare number counts only after "CPI" or with
    "+ taxes"."""
    body = text or ""
    found: Dict[int, Dict[str, Any]] = {}
    cur = None

    def add(pos: int, c: Optional[str], num: Optional[str], after: int, n: Optional[int] = None,
            bare_ok: bool = False) -> None:
        nonlocal cur
        if not num or _NOT_A_PRICE.match(body[after:after + 12]):
            return
        if not c and not bare_ok and not _TAXES.match(body[after:after + 16]):
            return
        v = _num(num)
        if not 0 < v < 1_000_000 or pos in found:
            return
        # "The total cost for this study is 70000+ taxes" is the whole study,
        # not a per-complete price.
        # ...but "(Total 320 PP)" is a sample count, not a total price.
        is_total = bool(re.search(r"\b(total|overall|lump ?sum|entire)\b(?![\s:=]*\d)",
                                  body[max(0, pos - 45):pos], re.I))
        found[pos] = {"cpi": v, "n": n, "at": pos, "total": is_total}
        cur = cur or _cur(c)

    for m in _PER_UNIT.finditer(body):
        c, num = _groups(m)
        n_m = _N_BEFORE.search(body[max(0, m.start() - 40):m.start()])
        add(m.start(), c, num, m.end(), int(n_m.group(1).replace(",", "")) if n_m else None, bare_ok=True)
    for m in _LABELED.finditer(body):
        c, num = _groups(m)
        # positioned at the price, not the label, so duplicates line up
        pos = m.start() + max(0, m.group(0).rfind(num or "") - 6) if num else m.start()
        add(pos, c, num, m.end(), bare_ok=m.group(1).lower() == "cpi")
    for m in _TAXED.finditer(body):
        c, num = _groups(m)
        add(m.start(), c, num, m.end(), bare_ok=True)

    lines = sorted(found.values(), key=lambda l: l["at"])
    # the same price matched by two patterns a few characters apart
    dedup: List[Dict[str, Any]] = []
    for l in lines:
        prev = dedup[-1] if dedup else None
        same = (prev and l["cpi"] == prev["cpi"] and l["at"] - prev["at"] < 20
                and not (l.get("n") and prev.get("n") and l["n"] != prev["n"]))
        if same:
            if l.get("n") and not prev.get("n"):
                prev["n"] = l["n"]
            continue
        dedup.append(l)
    lines = dedup
    if not lines:
        return None
    taxes_extra = bool(re.search(r"\+\s*\(?\s*(local |applicable )?(taxes|tax|gst)|plus (taxes|gst)|"
                                 r"excl(uding|\.)? (taxes|gst)", body, re.I))
    per_unit = [l for l in lines if not l["total"]]
    totals = [l for l in lines if l["total"]]
    return {"cpi": per_unit[0]["cpi"] if per_unit else None, "currency": cur, "taxes_extra": taxes_extra,
            "total": totals[0]["cpi"] if totals else None,
            "lines": [{"n": l["n"], "cpi": l["cpi"]} for l in per_unit]}


def client_currency(client, account_name: str, domain: str, country: str = "") -> Tuple[Optional[str], str]:
    """(currency, how we know) for a client with no currency in its own mail."""
    first = re.split(r"[\s|(\-]", (account_name or "").strip())[0]
    if len(first) >= 4:
        rows = list(client["finance_db"]["invoices"].aggregate([
            {"$match": {"customer_name": {"$regex": "^" + re.escape(first), "$options": "i"}}},
            {"$group": {"_id": {"$ifNull": ["$currency_code", "$currency"]}, "n": {"$sum": 1}}},
            {"$sort": {"n": -1}}, {"$limit": 1}]))
        if rows and rows[0]["_id"]:
            return rows[0]["_id"], "invoiced before in this currency"
    if (domain or "").endswith(".in") or "india" in (country or "").lower():
        return "INR", "Indian client"
    return None, ""


# ---------------------------------------------------------------------------
# AI-first: our quote, the client's live link (won, Online), is it an RFQ
# ---------------------------------------------------------------------------
_PRICEISH = re.compile(rf"{_CUR}|\bcpi\b|\bquote\b|\bcost\b|\brate\b|\bprice\b|per complete|\+\s*tax", re.I)
_STOP = {"rfq", "rfp", "survey", "study", "fieldwork", "field", "work", "project", "request", "quote", "quotation",
         "sfw", "hrg", "the", "and", "for", "with", "from", "research", "online", "live", "link", "links",
         "vendor", "re", "fw", "fwd", "new", "updated", "update"}


def _tokens(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]{4,}", (s or "").lower()) if w not in _STOP}


def ai_quote_for_thread(client, tids: List[str], ai_budget: Dict[str, int]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    """(quote, the reply it came from, source) from our latest reply that states
    a price -- the model decides; rules only when it is unavailable or out of
    budget. The model's verdict per reply is kept, so a reply is asked once."""
    from app.services import rfq_ai
    from sales.reply_triage import strip_quoted
    em = client["torpedo_gmail"]["email_metadata"]
    for d in em.find({"gmail_thread_id": {"$in": tids}, "direction": "outbound"},
                     {"body_plain": 1, "timestamp": 1, "quote_ai": 1}).sort("timestamp", -1):
        body = strip_quoted(d.get("body_plain") or "")
        if not _PRICEISH.search(body) or not re.search(r"\d", body):
            continue
        cached = d.get("quote_ai")
        if cached:
            if cached.get("quoted"):
                return cached, d, "ai"
            continue
        if ai_budget["left"] > 0:
            ai_budget["left"] -= 1
            ai_budget["asked"] = ai_budget.get("asked", 0) + 1
            q, status = rfq_ai.quote(body[:2500])
            if status == "unavailable":
                ai_budget["left"] = 0          # stop asking this pass; rules stand in
                ai_budget["unavailable"] = True
            if status == "ai" and q is not None:
                em.update_one({"_id": d["_id"]}, {"$set": {"quote_ai": q}})
                if q.get("quoted"):
                    return q, d, "ai"
                continue
            if status == "guard_rejected":
                em.update_one({"_id": d["_id"]}, {"$set": {"quote_ai": {"quoted": False, "guard_rejected": True}}})
        # model unavailable, out of budget, or its answer failed the check: rules
        rq = parse_quote(body)
        if rq:
            return rq, d, "rules"
    return None, None, ""


def apply_quotes(client, only_open: bool = False, ai_calls: int = 0) -> Dict[str, int]:
    """CPI, currency and value from our latest quote in the thread -- read by
    the model first (up to ai_calls new questions), rules otherwise. An RFQ we
    quoted moves to proposal ('Quoted')."""
    opp = client["crm_db"]["opportunities"]
    q: Dict[str, Any] = {"metadata.rfq.source": SOURCE}
    if only_open:
        q["status"] = "open"
    budget = {"left": ai_calls}
    stats = {"checked": 0, "quoted": 0, "by_ai": 0, "by_rules": 0, "valued": 0, "currency_set": 0}
    for o in opp.find(q, {"stage": 1, "status": 1, "metadata.rfq": 1, "amount": 1, "value_source": 1}):
        r = (o.get("metadata") or {}).get("rfq") or {}
        stats["checked"] += 1
        tids = [t for t in (r.get("gmail_thread_ids") or [r.get("gmail_thread_id")]) if t]
        quote, qdoc, qsource = ai_quote_for_thread(client, tids, budget)
        sets: Dict[str, Any] = {}
        currency = (quote or {}).get("currency")
        source = "stated in our quote" if currency else ""
        if quote and not currency and quote.get("taxes_extra"):
            currency, source = "INR", "our quote adds taxes (GST): Indian client"
        if not currency:
            currency, source = client_currency(client, r.get("account_name") or "",
                                               mc._domain(r.get("from_email") or ""), r.get("country") or "")
        if currency:
            sets.update({"metadata.rfq.currency": currency, "metadata.rfq.currency_source": source,
                         "currency": currency})
            stats["currency_set"] += 1
        if quote:
            n = r.get("sample_size")
            lines = quote.get("lines") or ([{"n": None, "cpi": quote["cpi"]}] if quote.get("cpi") else [])
            line_value = sum(l["n"] * l["cpi"] for l in lines if l.get("n"))
            value = quote.get("total") or line_value or (quote["cpi"] * n if n and quote.get("cpi") else None)
            sets.update({"metadata.rfq.cpi": quote.get("cpi"), "metadata.rfq.quote_lines": lines,
                         "metadata.rfq.taxes_extra": bool(quote.get("taxes_extra")),
                         "metadata.rfq.quote_email_id": str(qdoc["_id"]), "metadata.rfq.quote_source": qsource,
                         "quoted_at": qdoc.get("timestamp")})
            if value:
                sets["metadata.rfq.quoted_value"] = round(value, 2)
                if o.get("value_source") != "manual":
                    sets.update({"amount": round(value, 2), "value_source": "quote"})
                stats["valued"] += 1
            if o.get("stage") in ("rfq", "new", "qualified"):
                sets["stage"] = "proposal"
            stats["quoted"] += 1
            stats["by_ai" if qsource == "ai" else "by_rules"] += 1
        if sets:
            opp.update_one({"_id": o["_id"]}, {"$set": sets})
    stats["ai_asked"] = budget.get("asked", 0)
    stats["ai_unavailable"] = bool(budget.get("unavailable"))
    return stats


def _rfq_for_live_link(client, doc: Dict[str, Any], study_name: str) -> Optional[Dict[str, Any]]:
    """The RFQ a live-link mail belongs to: same thread, else the latest RFQ
    from the same company in the 120 days before whose title shares a
    distinctive word with the mail (or that company's only one then)."""
    opp = client["crm_db"]["opportunities"]
    hit = opp.find_one({"metadata.rfq.source": SOURCE, "metadata.rfq.gmail_thread_ids": doc.get("gmail_thread_id")})
    if hit:
        return hit
    root = registrable_root(mc._domain((doc.get("from_email") or "").lower()))
    ts = doc.get("timestamp") or datetime.utcnow()
    cands = [o for o in opp.find({"metadata.rfq.source": SOURCE,
                                  "metadata.rfq.received_at": {"$gte": ts - timedelta(days=120), "$lte": ts},
                                  "metadata.rfq.from_email": {"$regex": re.escape(root) + r"\.", "$options": "i"}},
                                 {"title": 1, "stage": 1, "status": 1, "metadata.rfq.received_at": 1})]
    if not cands:
        return None
    words = _tokens(f"{study_name} {doc.get('subject') or ''}")
    scored = sorted(((len(words & _tokens(o.get("title"))), o["metadata"]["rfq"]["received_at"], o) for o in cands),
                    key=lambda x: (x[0], x[1]), reverse=True)
    if scored[0][0] >= 1:
        return scored[0][2]
    return cands[0] if len(cands) == 1 else None


def apply_live_links(client, since: Optional[datetime] = None, ai_calls: int = 50,
                     now: Optional[datetime] = None) -> Dict[str, int]:
    """Owner rule: the client sent us the live link -> the study is won and its
    methodology is online. The model decides whether a mail really gives us the
    live link; the guard wants a link of theirs in the mail."""
    from bson import ObjectId
    from app.services import crm_service, rfq_ai
    from sales.reply_triage import strip_quoted
    now = now or datetime.utcnow()
    em = client["torpedo_gmail"]["email_metadata"]
    opp = client["crm_db"]["opportunities"]
    match: Dict[str, Any] = {"direction": "inbound", "mail_party": "client", "live_link_ai": {"$exists": False},
                             "body_plain": {"$regex": "live|launch", "$options": "i"}}
    if since:
        match["timestamp"] = {"$gte": since}
    stats = {"asked": 0, "live_links": 0, "won_now": 0, "won_history": 0, "no_rfq_found": 0,
             "already_won": 0, "unavailable": 0, "guard_rejected": 0}
    for doc in em.find(match, {"subject": 1, "body_plain": 1, "timestamp": 1, "from_email": 1,
                               "gmail_thread_id": 1}).sort("timestamp", 1):
        text = strip_quoted(doc.get("body_plain") or "")
        if stats["asked"] >= ai_calls:
            break
        decision, status = rfq_ai.live_link(doc.get("subject") or "", text[:3000])
        if status == "not_candidate":
            continue
        stats["asked"] += 1
        if status == "unavailable":
            stats["unavailable"] += 1
            break  # retried next run; nothing recorded
        record = {"status": status, "at": now, **({k: decision.get(k) for k in
                  ("live_link_sent", "told_to_launch", "test_link_only", "study_name", "reason", "url")}
                  if decision else {})}
        em.update_one({"_id": doc["_id"]}, {"$set": {"live_link_ai": record}})
        if status == "guard_rejected":
            stats["guard_rejected"] += 1
            continue
        live, launch = bool(decision.get("live_link_sent")), bool(decision.get("told_to_launch"))
        if not (live or launch):
            continue
        stats["live_links"] += 1
        o = _rfq_for_live_link(client, doc, decision.get("study_name") or "")
        if not o:
            # A project the client started in its own thread ("NR14338_CG")
            # that never read as an RFQ: the study happened, so it gets its
            # record, from the thread's first message if the client opened it.
            first = em.find_one({"gmail_thread_id": doc.get("gmail_thread_id")},
                                {"subject": 1, "from_email": 1, "from_name": 1, "timestamp": 1, "direction": 1,
                                 "gmail_thread_id": 1, "mail_summary": 1, "mailbox_id": 1},
                                sort=[("timestamp", 1)])
            if not first or first.get("direction") != "inbound" or \
                    mc._domain((first.get("from_email") or "").lower()) in mc.OWN_DOMAINS:
                stats["no_rfq_found"] += 1
                continue
            new_id, _ = create_from_doc(client, first, now, via="client live link / launch")
            o = opp.find_one({"_id": ObjectId(new_id)}, {"title": 1, "stage": 1, "status": 1})
            stats["created_for_live_link"] = stats.get("created_for_live_link", 0) + 1
        if o.get("stage") == "won":
            stats["already_won"] += 1
            continue
        oid = str(o["_id"])
        why = "client sent the live link" if live else "client told us to launch the fieldwork"
        link = {"url": decision.get("url"), "at": doc.get("timestamp"), "email_id": str(doc["_id"]),
                "study_name": decision.get("study_name"), "reason": why, "decided_by": "ai"}
        sets = {"metadata.rfq.live_link": link}
        if live:  # owner rule: a live link from the client means an online study
            sets.update({"metadata.rfq.methodology": "Online",
                         "metadata.rfq.methodology_source": "client sent the live link"})
        opp.update_one({"_id": o["_id"]}, {"$set": sets})
        if o.get("status") == "open":
            # the live flow: Finance customer, work order, contract, Ops project
            crm_service.mark_opportunity_won(oid)
            opp.update_one({"_id": o["_id"]}, {"$set": {"won_via": why, "won_at": doc.get("timestamp")}})
            stats["won_now"] += 1
        else:
            # history: won, dated by the live link; no Finance/Ops records for
            # a study that ran long ago
            opp.update_one({"_id": o["_id"]}, {"$set": {
                "stage": "won", "status": "won", "won_at": doc.get("timestamp"), "closed_at": doc.get("timestamp"),
                "won_via": f"{why} (historical: no Finance/Ops setup)"},
                "$unset": {"closed_reason": "", "closed_by": ""}})
            stats["won_history"] += 1
    return stats


def ai_check_new_rfqs(client, limit: int = 3) -> Dict[str, int]:
    """For RFQs the rules created from recent mail: the model confirms the mail
    asks us for a quote; if it says no, the RFQ is closed (not deleted) with
    its reason."""
    from bson import ObjectId
    from app.services import rfq_ai
    from sales.reply_triage import strip_quoted
    opp = client["crm_db"]["opportunities"]
    em = client["torpedo_gmail"]["email_metadata"]
    stats = {"checked": 0, "confirmed": 0, "not_rfq": 0, "unavailable": 0}
    for o in opp.find({"metadata.rfq.source": SOURCE, "metadata.rfq.ai_is_rfq": {"$exists": False}},
                      {"status": 1, "metadata.rfq.source_email_id": 1}).sort("metadata.rfq.received_at", -1).limit(limit):
        try:
            d = em.find_one({"_id": ObjectId(o["metadata"]["rfq"]["source_email_id"])}, {"subject": 1, "body_plain": 1})
        except Exception:
            d = None
        verdict, reason = rfq_ai.is_rfq((d or {}).get("subject") or "", strip_quoted((d or {}).get("body_plain") or "")[:2500])
        if verdict is None:
            stats["unavailable"] += 1
            break
        stats["checked"] += 1
        sets = {"metadata.rfq.ai_is_rfq": verdict, "metadata.rfq.ai_is_rfq_reason": reason}
        if verdict:
            stats["confirmed"] += 1
        else:
            stats["not_rfq"] += 1
            if o.get("status") == "open":
                sets.update(status="closed", closed_at=datetime.utcnow(), closed_by="rfq_ai",
                            closed_reason=f"AI: not a request for our quote -- {reason}")
        opp.update_one({"_id": o["_id"]}, {"$set": sets})
    return stats


def run_scheduled_cycle(client) -> Dict[str, Any]:
    """New RFQs from recent mail; then, AI first: confirm new RFQs, our quotes
    on open ones, live links (won, Online) in recent mail, study details."""
    now = datetime.utcnow()
    out = {"built": build(client, since=now - timedelta(days=3))}
    out["ai_is_rfq"] = ai_check_new_rfqs(client, limit=int(os.getenv("RFQ_AI_CHECK_PER_RUN", "2")))
    out["quotes"] = apply_quotes(client, only_open=True, ai_calls=int(os.getenv("RFQ_QUOTE_AI_PER_RUN", "2")))
    out["live_links"] = apply_live_links(client, since=now - timedelta(days=3),
                                         ai_calls=int(os.getenv("RFQ_LIVE_AI_PER_RUN", "2")))
    out["details"] = enrich_open(client, limit=int(os.getenv("RFQ_DETAILS_AI_PER_RUN", "2")))
    return out
