"""
Which campaign a lead's COMPANY fits -- the company decides the ICP, the
person's title only confirms it (owner, 2026-10-20: "the ICP is not getting
done properly ... IPSOS people are getting BIM mails").

Why this exists: lead-gen runs one Google search job per ICP and tagged every
person a job found with that job's ICP (scheduler.run_search_batch,
backlog_drain). compute_icp_basket trusted that tag before any other evidence,
so an Ipsos researcher whose LinkedIn page turned up in the BIMwave search
became basket C and was mailed BIM pitches. Which search found someone says
nothing about who they are; what company they work at does.

A company gets ONE type, stored in email_automation.company_types:

    mr_agency   market research / fieldwork / panel firm  -> SFW      (basket A)
    brand       consumer-facing company that buys research -> Cogentix (basket B)
    aec         architecture / engineering / construction  -> BIMwave  (basket C)
    other       none of the above                          -> no cold campaign

Where the type comes from, strongest first:
    manual      set by a person (never overwritten)
    seed        the well-known names in SEED below
    linkedin    the company's LinkedIn page, found with one Google search
                (owner: "if you do google search of the companies you will
                find the industry data very easily on linkedin"); the page's
                Industry line or wording decides, the local model only when
                the text alone does not
A company we already deal with as a client or vendor
(email_automation.party_relationships) is never cold-mailed, whatever its type.

Google searches come out of the same free 100/day CSE quota lead-gen uses, so
company lookups get their own small daily allowance (COMPANY_FIT_DAILY_SEARCHES,
default 25) and only run while lead-gen's hourly budget has room left -- a
refused CSE slot pauses ALL searches for 24h (ingestion._pause_cse_for_24h).
Companies with the most mailable leads are looked up first.

Switches:
    COMPANY_FIT_ENFORCE=false        gates at enrollment/send stop blocking
    COMPANY_FIT_DAILY_SEARCHES=0     no Google lookups (seed/manual only)
"""
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

TYPES = ("mr_agency", "brand", "aec", "other")
BASKET_FOR_TYPE = {"mr_agency": "A", "brand": "B", "aec": "C"}
BUSINESS_FOR_BASKET = {"A": "sfw", "B": "cogentix", "C": "bimwave"}
TYPE_FOR_BUSINESS = {"sfw": "mr_agency", "cogentix": "brand", "bimwave": "aec"}
EXCLUDED_RELATIONSHIPS = ("client", "vendor", "both")
MAX_ATTEMPTS = 3
RETRY_DAYS = 7

COLLECTION = "company_types"

# Well-known market-research / fieldwork / panel firms. Matched on the
# normalised company name (whole words) or the email/web domain root.
# Only names that cannot be anyone else ("Lucid" is also a car maker, "Sago"
# a food) -- the LinkedIn lookup settles the rest.
SEED: Dict[str, str] = {
    "ipsos": "mr_agency", "kantar": "mr_agency", "nielsen": "mr_agency", "nielseniq": "mr_agency",
    "gfk": "mr_agency", "dynata": "mr_agency", "toluna": "mr_agency", "cint": "mr_agency",
    "lucidhq": "mr_agency", "purespectrum": "mr_agency", "yougov": "mr_agency",
    "hansa research": "mr_agency", "market xcel": "mr_agency", "marketxcel": "mr_agency",
    "iqvia": "mr_agency", "circana": "mr_agency", "schlesinger": "mr_agency",
    "pureprofile": "mr_agency", "borderless access": "mr_agency", "savanta": "mr_agency",
    "rakuten insight": "mr_agency", "macromill": "mr_agency", "intage": "mr_agency",
    "hall and partners": "mr_agency", "dooblo": "mr_agency",
    "accenture": "other", "tata consultancy services": "other", "infosys": "other",
    "wipro": "other", "cognizant": "other", "capgemini": "other", "deloitte": "other",
}

# LinkedIn's own industry names (and close wording in an About text) -> type.
# Checked in this order: research before brand, because "Marketing Services"
# research shops also mention brands.
_INDUSTRY_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("mr_agency", ("market research", "marketing research", "consumer research", "survey research",
                   "fieldwork", "field work", "panel provider", "online panel", "data collection",
                   "opinion research", "polling", "consumer insights agency", "research agency",
                   "sample provider", "respondent", "mystery shopping")),
    ("aec", ("architecture and planning", "architecture & planning", "architecture", "architects",
             "civil engineering", "construction", "building construction", "structural engineering",
             "mep", "bim", "building information modeling", "building information modelling",
             "real estate development", "interior design", "infrastructure", "engineering services",
             "design services", "building materials", "surveying", "urban planning")),
    ("brand", ("consumer goods", "consumer products", "fmcg", "cpg", "food and beverage",
               "food & beverage", "food production", "beverage", "retail", "apparel", "fashion",
               "cosmetics", "personal care", "beauty", "banking", "financial services", "insurance",
               "telecommunications", "telecom", "automotive", "pharmaceutical", "healthcare",
               "hospital", "consumer electronics", "media", "broadcast", "entertainment",
               "hospitality", "travel", "airlines", "e-commerce", "ecommerce", "restaurants",
               "advertising services", "marketing and advertising", "luxury goods", "sporting goods",
               "tobacco", "wine and spirits", "dairy", "furniture", "household")),
    ("other", ("it services", "information technology", "software development", "computer software",
               "staffing", "recruiting", "human resources", "outsourcing", "education", "higher education",
               "government", "non-profit", "nonprofit", "legal services", "law practice", "accounting",
               "management consulting", "business consulting", "logistics", "manufacturing",
               "oil and gas", "mining", "utilities", "defense")),
]

_INDUSTRY_LINE = re.compile(r"Industr(?:y|ies)\s*[:\-–]?\s*([A-Za-z&,/ \-]{3,60})", re.I)

# Titles that never buy what any of our three businesses sell.
_NON_BUYER_TITLE = re.compile(
    r"\b(recruit\w*|talent acquisition|hr\b|human resources|payroll|accountant|accounts (?:payable|receivable)|"
    r"intern|internship|student|trainee|legal counsel|paralegal|receptionist|driver|security guard)\b", re.I)

_SUFFIXES = re.compile(r"\b(inc|incorporated|llc|ltd|limited|plc|corp|corporation|co|company|pvt|private|"
                       r"gmbh|sa|ag|bv|group|holdings|india|global|international|the)\b\.?", re.I)
_PLATFORM_DOMAINS = {"linkedin.com", "in.linkedin.com", "gmail.com", "yahoo.com", "outlook.com",
                     "hotmail.com", "google.com"}


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------
def enforce() -> bool:
    return os.getenv("COMPANY_FIT_ENFORCE", "true").lower() != "false"


def normalise_name(name: str) -> str:
    n = (name or "").lower().replace("&", " and ")
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = _SUFFIXES.sub(" ", n)
    return " ".join(n.split())


def normalise_domain(domain: str) -> str:
    d = re.sub(r"^(https?://)?(www\.)?", "", (domain or "").strip().lower()).split("/")[0]
    if "@" in d:
        d = d.split("@")[-1]
    return "" if (not d or "." not in d or d in _PLATFORM_DOMAINS or d.endswith(".linkedin.com")) else d


def company_key(name: str, domain: str = "") -> str:
    """The store key: the company's domain when we have a real one, else its
    normalised name. '' when there is nothing to key on."""
    d = normalise_domain(domain)
    if d:
        return d
    n = normalise_name(name)
    return f"name:{n}" if len(n) >= 2 else ""


def seed_type(name: str, domain: str = "") -> Optional[str]:
    n = f" {normalise_name(name)} "
    root = normalise_domain(domain).split(".")[0]
    for k, t in SEED.items():
        if f" {k} " in n or (root and root == k.replace(" ", "")):
            return t
    return None


def type_from_text(text: str) -> Tuple[Optional[str], str]:
    """(type, evidence) from a LinkedIn page's text. The page's own
    'Industry: ...' line wins; otherwise the wording. (None, '') when the text
    does not say, or points two ways."""
    text = text or ""
    m = _INDUSTRY_LINE.search(text)
    if m:
        industry = m.group(1).strip().lower()
        for t, words in _INDUSTRY_RULES:
            if any(w in industry for w in words):
                return t, f"industry: {m.group(1).strip()}"
    low = text.lower()
    hits = [(t, next(w for w in words if re.search(rf"\b{re.escape(w)}\b", low)))
            for t, words in _INDUSTRY_RULES
            if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words)]
    kinds = {t for t, _ in hits}
    if len(kinds) == 1:
        return hits[0][0], f"wording: {hits[0][1]}"
    # research firms describe the brands they serve; research wins over brand
    if kinds == {"mr_agency", "brand"}:
        return "mr_agency", "wording: " + next(w for t, w in hits if t == "mr_agency")
    return None, ""


def decide(type_doc: Optional[Dict[str, Any]], business: str, title: str = "") -> Tuple[str, str]:
    """-> (verdict, reason). verdict: fit | mismatch | excluded | unknown."""
    want = TYPE_FOR_BUSINESS.get((business or "").lower())
    if not want:
        return "fit", "campaign has no company-type rule"
    if type_doc and type_doc.get("relationship") in EXCLUDED_RELATIONSHIPS:
        return "excluded", f"company is our {type_doc['relationship']}"
    ctype = (type_doc or {}).get("type")
    if ctype not in TYPES:
        return "unknown", "company type not known yet"
    if ctype != want:
        return "mismatch", f"company is {ctype}, campaign {business} needs {want}"
    if title and _NON_BUYER_TITLE.search(title):
        return "mismatch", f"title '{title[:60]}' does not buy {business}"
    return "fit", f"company is {ctype}"


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------
def _db(client=None):
    if client is None:
        from database import get_client
        client = get_client()
    return client["email_automation"]


def _relationship(db, name: str, domain: str) -> Optional[str]:
    keys = [k for k in (normalise_domain(domain), (name or "").strip().lower()) if k]
    if not keys:
        return None
    r = db["party_relationships"].find_one({"key": {"$in": keys},
                                            "relationship": {"$in": list(EXCLUDED_RELATIONSHIPS)}},
                                           {"relationship": 1})
    return (r or {}).get("relationship")


def lookup(name: str, domain: str = "", client=None, queue_if_unknown: bool = True,
           mailable: bool = False) -> Optional[Dict[str, Any]]:
    """The company's type document, or None. No network. An unknown company is
    queued for a LinkedIn lookup (mailable=True moves it up the queue)."""
    key = company_key(name, domain)
    if not key:
        return None
    db = _db(client)
    col = db[COLLECTION]
    doc = col.find_one({"_id": key})
    if not doc and normalise_domain(domain) and name:
        # a lead without a domain may have queued it under its name
        doc = col.find_one({"_id": company_key(name)})
    rel = _relationship(db, name, domain)
    if doc and doc.get("type") in TYPES:
        return {**doc, "relationship": rel} if rel else doc
    st = seed_type(name, domain)
    now = datetime.utcnow()
    if st:
        col.update_one({"_id": key}, {"$set": {"type": st, "source": "seed", "name": name,
                                                "domain": normalise_domain(domain), "at": now}},
                       upsert=True)
        return {"_id": key, "type": st, "source": "seed", "relationship": rel}
    if queue_if_unknown:
        col.update_one({"_id": key}, {
            "$setOnInsert": {"status": "pending", "attempts": 0, "queued_at": now, "next_try_at": now},
            "$set": {"name": name, "domain": normalise_domain(domain)},
            "$inc": {"mailable_leads": 1 if mailable else 0, "seen": 1}}, upsert=True)
    return {"_id": key, "relationship": rel} if rel else None


def check(business: str, name: str, domain: str = "", title: str = "", client=None,
          mailable: bool = True) -> Tuple[str, str]:
    """(verdict, reason) for sending this campaign to someone at this company."""
    try:
        doc = lookup(name, domain, client=client, mailable=mailable)
    except Exception as e:  # the store being down is not a verdict on the lead
        logger.warning("company_fit lookup failed for %r: %s", name, e)
        return "unknown", f"company lookup failed: {e}"[:200]
    return decide(doc, business, title)


def set_type(name: str, domain: str, ctype: str, source: str = "manual", evidence: str = "",
             client=None) -> Dict[str, Any]:
    """Record a company's type (manual overrides are never replaced by a lookup)
    and re-basket that company's leads."""
    if ctype not in TYPES:
        raise ValueError(f"type must be one of {TYPES}")
    db = _db(client)
    key = company_key(name, domain)
    now = datetime.utcnow()
    db[COLLECTION].update_one({"_id": key}, {"$set": {
        "type": ctype, "source": source, "evidence": evidence[:300], "status": "done",
        "name": name, "domain": normalise_domain(domain), "at": now}}, upsert=True)
    return {"rebasketed": rebasket_company(db, name, domain, ctype)}


def rebasket_company(db, name: str, domain: str, ctype: str) -> int:
    """Put every lead at this company in the basket its type gives (E when the
    company fits no campaign). The periodic enrollment sync picks them up."""
    basket = BASKET_FOR_TYPE.get(ctype, "E")
    names = {"A": "Survey Fieldwork", "B": "Cogentix Research", "C": "BIMwave", "E": "Nurture / Unqualified"}
    tags = {"A": ["survey_fieldwork"], "B": ["cogentix"], "C": ["bimwave"], "E": ["nurture"]}
    ors: List[Dict[str, Any]] = []
    d = normalise_domain(domain)
    if d:
        ors.append({"company_domain": d})
    if name and len(name.strip()) >= 2:
        rx = {"$regex": f"^\\s*{re.escape(name.strip())}\\s*$", "$options": "i"}
        ors += [{"company_name": rx}, {"company": rx}]
    if not ors:
        return 0
    seg = {"A": "survey_fieldwork", "B": "cogentix", "C": "bimwave"}.get(basket)
    r = db["leads_enriched"].update_many({"$or": ors}, {"$set": {
        "company_icp_type": ctype, "classification_basket": basket,
        "classification_basket_name": names[basket], "icp_tags": tags[basket],
        "icp_segment": seg, "classification_confidence": "High",
        "classified_by": "company_fit", "classified_at": datetime.utcnow()}})
    # The AI pass's REVIEW means "the title alone could not tell"; the company
    # now tells. A person-level REJECT stays.
    bucket = {"A": "SFW", "B": "COGENTIX_RESEARCH", "C": "BIM"}.get(basket)
    if bucket:
        db["leads_enriched"].update_many({"$or": ors, "outreach_bucket": "REVIEW"},
                                         {"$set": {"outreach_bucket": bucket}})
    return r.modified_count


# ---------------------------------------------------------------------------
# LinkedIn lookup (the scheduled job)
# ---------------------------------------------------------------------------
def _daily_allowance_left(db) -> int:
    limit = int(os.getenv("COMPANY_FIT_DAILY_SEARCHES", "25"))
    if limit <= 0:
        return 0
    day = datetime.utcnow().strftime("%Y-%m-%d")
    used = (db["company_type_usage"].find_one({"_id": day}) or {}).get("searches", 0)
    return max(0, limit - used)


def _cse_has_room() -> bool:
    """Leave lead-gen its hour: a refused slot pauses every search for 24h."""
    try:
        from leads.google_rate_limit import get_usage_stats
        s = get_usage_stats()
        return s["hourly_remaining"] >= 3 and s["daily_remaining"] >= 5
    except Exception:
        return False


def _page_text(items: Iterable[Dict[str, Any]], name: str) -> Tuple[str, str]:
    """(text, url) of the result that is this company's LinkedIn page."""
    want = normalise_name(name)
    for it in items or []:
        link = it.get("link") or ""
        if "linkedin.com/company/" not in link:
            continue
        title = it.get("title") or ""
        if want and want.split()[0] not in normalise_name(title):
            continue
        meta = " ".join(str(m.get("og:description") or "") for m in
                        ((it.get("pagemap") or {}).get("metatags") or []))
        return " ".join([title, it.get("snippet") or "", meta]), link
    return "", ""


_TYPE_SCHEMA = {"type": "object", "additionalProperties": False,
                "properties": {"type": {"type": "string", "enum": list(TYPES) + ["unclear"]}},
                "required": ["type"]}


def _model_type(name: str, text: str) -> Optional[str]:
    from leads.local_llm_gate import queue_wait
    from leads.local_slm_client import LocalSLMError, chat_json
    try:
        with queue_wait(120, priority="bulk"):
            got = chat_json(
                system="You sort companies by what they do. Reply only with JSON.",
                user=(f"Company: {name}\nLinkedIn page text: {text[:900]}\n\n"
                      "Which one is it?\n"
                      "mr_agency = market research, fieldwork, survey or panel company\n"
                      "aec = architecture, engineering, construction or BIM company\n"
                      "brand = company selling consumer products or services (FMCG, retail, bank, "
                      "telecom, auto, pharma, media ...)\n"
                      "other = anything else (IT services, staffing, software, consulting, government ...)\n"
                      "unclear = the text does not say"),
                max_tokens=20, json_schema=_TYPE_SCHEMA, timeout=90)
    except (LocalSLMError, Exception):
        return None
    t = got.get("type")
    return t if t in TYPES else None


async def _search(query: str) -> List[Dict[str, Any]]:
    from leads.ingestion import perform_google_search
    return await perform_google_search(query, num_results=5)


def resolve_one(db, doc: Dict[str, Any], now: datetime) -> str:
    import asyncio
    name, domain = doc.get("name") or "", doc.get("domain") or ""
    query = f'site:linkedin.com/company "{name}"' if name else f'site:linkedin.com/company "{domain}"'
    db["company_type_usage"].update_one({"_id": now.strftime("%Y-%m-%d")}, {"$inc": {"searches": 1}},
                                        upsert=True)
    items = asyncio.run(_search(query))
    text, url = _page_text(items, name or domain.split(".")[0])
    ctype, evidence = type_from_text(text) if text else (None, "")
    if text and not ctype:
        ctype = _model_type(name or domain, text)
        evidence = "model read the LinkedIn page" if ctype else ""
    if ctype:
        db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {
            "type": ctype, "source": "linkedin", "evidence": evidence[:300], "linkedin_url": url,
            "status": "done", "at": now}})
        n = rebasket_company(db, name, domain, ctype)
        logger.info("[CompanyFit] %s -> %s (%s); %d leads re-basketed", name or domain, ctype, evidence, n)
        return "typed"
    attempts = int(doc.get("attempts") or 0) + 1
    db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {
        "attempts": attempts, "status": "pending" if attempts < MAX_ATTEMPTS else "not_found",
        "last_result": "no linkedin page" if not text else "page did not say",
        "next_try_at": now + timedelta(days=RETRY_DAYS)}})
    return "not_found" if text == "" else "unclear"


def run(client=None, limit: int = 5, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Type the waiting companies with the most mailable leads first."""
    db = _db(client)
    now = now or datetime.utcnow()
    stats: Dict[str, Any] = {}
    try:
        ensure_indexes(client)
    except Exception:
        pass
    budget = min(limit, _daily_allowance_left(db))
    if budget <= 0:
        return {"skipped": "daily allowance used"}
    try:
        from leads.ingestion import _is_cse_paused
        if _is_cse_paused():
            return {"skipped": "google search paused"}
    except Exception:
        pass
    pending = db[COLLECTION].find({"status": "pending", "type": {"$exists": False},
                                   "next_try_at": {"$lte": now}}).sort(
        [("mailable_leads", -1), ("seen", -1)]).limit(budget)
    for doc in pending:
        if not _cse_has_room():
            stats["stopped"] = "leaving the search quota to lead-gen"
            break
        try:
            r = resolve_one(db, doc, now)
        except Exception as e:
            logger.warning("[CompanyFit] lookup failed for %r: %s", doc.get("name"), e)
            r = "error"
        stats[r] = stats.get(r, 0) + 1
    logger.info("[CompanyFit] %s", stats)
    return stats


def ensure_indexes(client=None) -> None:
    db = _db(client)
    db[COLLECTION].create_index([("status", 1), ("next_try_at", 1), ("mailable_leads", -1)])
    db["leads_enriched"].create_index("company_domain")
