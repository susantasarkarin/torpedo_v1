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
                   "sample provider", "respondent", "mystery shopping", "qualitative research",
                   "quantitative research", "research consultancy", "research consultants",
                   "insights agency", "insight agency", "research and insights")),
    ("aec", ("architecture and planning", "architecture & planning", "architecture", "architects",
             "civil engineering", "construction", "building construction", "structural engineering",
             "mep", "bim", "building information modeling", "building information modelling",
             "real estate development", "real estate", "property developer", "property development",
             "real estate developer", "interior design", "building materials", "land surveying",
             "urban planning")),
    ("brand", ("consumer goods", "consumer products", "fmcg", "cpg", "food and beverage",
               "food & beverage", "food production", "beverage", "retail", "apparel", "fashion",
               "cosmetics", "personal care", "beauty", "banking", "financial services", "insurance",
               "telecommunications", "telecom", "automotive", "pharmaceutical", "healthcare",
               "hospital", "consumer electronics", "broadcast media", "media production", "entertainment",
               "hospitality", "airlines", "e-commerce", "ecommerce", "restaurants",
               "advertising services", "marketing and advertising", "luxury goods", "sporting goods",
               "tobacco", "wine and spirits", "dairy")),
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


# Competitors are never targets (owner, 2026-10-22: "ignore all
# competitors"): a BIM / CAD outsourcing firm sells what BIMwave sells; a
# panel, sample or fieldwork provider sells what Survey Fieldwork sells.
# (Cogentix's competitors -- research agencies -- are already a different
# type.) Matched on the company NAME and the HEAD of its own text (LinkedIn
# industry, page title/description) -- body text of a big AEC firm mentions
# "BIM services" too, and that does not make AECOM a competitor.
COMPETITOR_NAME = {
    "bimwave": re.compile(r"\b(bim|cad|revit|drafting|scan ?to ?bim)\b", re.I),
    "sfw": re.compile(r"\b(panel|panels|sample|fieldwork|field work|data collection)\b", re.I),
}
COMPETITOR_TEXT = {
    "bimwave": re.compile(r"\b(bim|cad|revit)\s+(services|outsourcing|modell?ing services|drafting|"
                          r"consult\w* services|coordination services)|\bcad drafting|\bdrafting services|"
                          r"\bscan[ -]to[ -]bim|\bbim outsourcing", re.I),
    "sfw": re.compile(r"\b(panel provider|online panel|survey panel|sample provider|online sample|"
                      r"sample company|fieldwork (services|agency|company)|data collection (services|company)|"
                      r"respondent recruitment|panel company)\b", re.I),
}
COMPETITOR_SEED = {
    "sfw": {"dynata", "toluna", "cint", "lucidhq", "purespectrum", "pureprofile", "borderless access",
            "rakuten insight", "macromill", "schlesinger", "market cube", "innovatemr", "prodege",
            "quest mindshare", "mfour", "survey fieldwork", "surveyfieldwork"},
    "bimwave": {"bimheroes", "bim heroes", "pinnacle infotech", "pinnacleinfotech", "bimwave",
                "bimwave solutions", "bimwavesolutions"},
}


def competitor_of(name: str, head: str = "", domain: str = "") -> List[str]:
    """Which of our businesses this company competes with."""
    n = normalise_name(name)
    root = normalise_domain(domain).split(".")[0]
    out = []
    for biz in ("bimwave", "sfw"):
        if (n in COMPETITOR_SEED[biz] or root in COMPETITOR_SEED[biz]
                or COMPETITOR_NAME[biz].search(name or "") or COMPETITOR_TEXT[biz].search(head or "")):
            out.append(biz)
    return out


def _head(doc: Dict[str, Any]) -> str:
    return " | ".join(t for t in (doc.get("skrapp_text") or "", doc.get("linkedin_text") or "",
                                  (doc.get("website_text") or "").split(" || ")[0]) if t)


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
    if type_doc and business.lower() in competitor_of(type_doc.get("name") or "", _head(type_doc),
                                                       type_doc.get("domain") or ""):
        return "excluded", f"company is a {business} competitor"
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
        return {"_id": key, "type": st, "source": "seed", "relationship": rel,
                "name": name, "domain": normalise_domain(domain)}
    if queue_if_unknown:
        col.update_one({"_id": key}, {
            "$setOnInsert": {"status": "pending", "attempts": 0, "queued_at": now, "next_try_at": now},
            "$set": {"name": name, "domain": normalise_domain(domain)},
            "$inc": {"mailable_leads": 1 if mailable else 0, "seen": 1},
            "$max": {"priority": 3 if mailable else 1}}, upsert=True)
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
# Finding out what a company does (the scheduled job)
# ---------------------------------------------------------------------------
# Owner, 2026-10-21: "get the industry of all the companies using google
# search, then check if the icp is correct using qwen". ~9,100 company domains
# have been mailed and ~13,000 companies have a lead with an email, but the
# Google quota is 100 searches a day (free tier only, owner 2026-09-28) and
# lead-gen already uses all of it -- Google alone would take months. So each
# company's OWN WEBSITE is read first (free, no quota); its LinkedIn page via
# Google is the fallback for companies the website does not settle; the local
# model decides only when the text alone is not clear.
ACTIVE_STATUSES = ("not_started", "pending_scheduled", "in_sequence")
_WEBMAIL = {"gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com",
            "icloud.com", "aol.com", "rediffmail.com", "protonmail.com", "zoho.com", "gmx.com",
            "yandex.com", "mail.com", "msn.com", "me.com", "ymail.com"}


GOOGLE_BATCH = 5           # companies per Google call (owner, 2026-10-21)
GOOGLE_CALLS_PER_RUN = 4   # x every 5 min; the $5/day paid cap stops it


def _google_left() -> int:
    """Queries today's free tier + $5/day paid budget still allow; 0 while
    Google itself has paused us (429)."""
    try:
        from leads.ingestion import _is_cse_paused
        if _is_cse_paused():
            return 0
        from leads.google_rate_limit import queries_left_today
        return queries_left_today("company")
    except Exception:
        return 0


def _title_name(title: str) -> str:
    """'Ipsos | LinkedIn' / 'NielsenIQ - LinkedIn' -> normalised 'ipsos'."""
    return normalise_name(re.split(r"\s[|\-\u2013]\s", title or "")[0])


def _page_text(items: Iterable[Dict[str, Any]], name: str) -> Tuple[str, str]:
    """(text, url) of the result that is THIS company's LinkedIn page -- one
    search returns pages for several companies, so the page's own name must
    match, not just share a word."""
    want = normalise_name(name)
    if not want:
        return "", ""
    for it in items or []:
        link = it.get("link") or ""
        if "linkedin.com/company/" not in link:
            continue
        got = _title_name(it.get("title") or "")
        squash_got, squash_want = got.replace(" ", ""), want.replace(" ", "")
        if not got or not (got == want or squash_got == squash_want
                           or got.startswith(want + " ") or want.startswith(got + " ")):
            continue
        meta = " ".join(str(m.get("og:description") or "") for m in
                        ((it.get("pagemap") or {}).get("metatags") or []))
        return " ".join([it.get("title") or "", it.get("snippet") or "", meta]), link
    return "", ""


def _search_name(doc: Dict[str, Any]) -> str:
    n = re.sub(r"[\"\u201c\u201d]|\.\.\.|\u2026", " ", doc.get("name") or "").strip()
    if len(normalise_name(n)) < 2:
        n = (doc.get("domain") or "").split(".")[0]
    return " ".join(n.split())[:60]


def linkedin_batch(db, docs: List[Dict[str, Any]], now: datetime) -> int:
    """ONE Google call for up to GOOGLE_BATCH companies: their LinkedIn pages'
    titles and snippets (industry, what they do). Writes linkedin_text (''
    when no page matched) and linkedin_at on each. -> companies found."""
    import asyncio
    names = [(d, _search_name(d)) for d in docs]
    names = [(d, n) for d, n in names if n]
    if not names:
        return 0
    query = "site:linkedin.com/company (" + " OR ".join(f'"{n}"' for _, n in names) + ")"
    items = asyncio.run(_search(query, num=10))
    found = 0
    for d, n in names:
        text, url = _page_text(items, n)
        found += bool(text)
        d.update({"linkedin_text": text, "linkedin_url": url, "linkedin_at": now})
        db[COLLECTION].update_one({"_id": d["_id"]}, {"$set": {
            "linkedin_text": text, "linkedin_url": url, "linkedin_at": now}})
    db["company_type_usage"].update_one({"_id": now.strftime("%Y-%m-%d")},
                                        {"$inc": {"searches": 1, "companies": len(names), "found": found}},
                                        upsert=True)
    return found


_SKIP_BLOCKS = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.S | re.I)
_META_NAMES = r"(?:description|og:description|og:title|keywords)"
_META = re.compile(r"<meta[^>]+(?:name|property)=[\"']" + _META_NAMES +
                   r"[\"'][^>]*content=[\"']([^\"']{3,400})", re.I)
_META_REV = re.compile(r"<meta[^>]+content=[\"']([^\"']{3,400})[\"'][^>]*(?:name|property)=[\"']" +
                       _META_NAMES + r"[\"']", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def website_text(domain: str, timeout: float = 6.0) -> str:
    """Title, meta descriptions and the first visible words of the company's
    home page; '' when it cannot be read."""
    import html as _html
    import httpx
    if not domain or domain in _WEBMAIL:
        return ""
    for url in (f"https://{domain}", f"https://www.{domain}", f"http://{domain}"):
        try:
            r = httpx.get(url, timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; company-research)"})
        except Exception:
            continue
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            continue
        page = r.text[:300_000]
        parts = [m.strip() for m in _TITLE.findall(page)[:1]]
        parts += _META.findall(page) + _META_REV.findall(page)
        body = re.sub(r"<[^>]+>", " ", _SKIP_BLOCKS.sub(" ", page))
        head = _html.unescape(" | ".join(p for p in parts if p))[:700]
        # "head || body": only the head (title, descriptions) is matched by
        # the word rules -- a page body mentions "social media", "cloud
        # infrastructure", "data collection" (privacy policy) on almost every
        # site; the body is for the model.
        return head + " || " + _html.unescape(" ".join(body.split()))[:800]
    return ""


_TYPE_SCHEMA = {"type": "object", "additionalProperties": False,
                "properties": {"type": {"type": "string", "enum": list(TYPES) + ["unclear"]}},
                "required": ["type"]}


def _model_type(name: str, text: str) -> Optional[str]:
    """None = the model could not say (or was unavailable); asked again later."""
    from leads.local_llm_gate import queue_wait
    from leads.local_slm_client import LocalSLMError, chat_json
    try:
        with queue_wait(120, priority="bulk"):
            got = chat_json(
                system="You sort companies by what they do. Reply only with JSON.",
                user=(f"Company: {name}\nWhat the company says about itself: {text[:900]}\n\n"
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


_YES_NO = {"type": "object", "additionalProperties": False,
           "properties": {"answer": {"type": "string", "enum": ["yes", "no"]}}, "required": ["answer"]}
# Plain questions the small model answers reliably (prod tests 2026-10-21):
# no false yes in 24 cases; brand 10/12, aec 11/12 right. The abstract
# "is this a company that sells consumer products (...)" form said no to
# NBCUniversal, BBC Studios and Merck.
_QUESTIONS = {
    "mr_agency": "Is this company a market research, survey, fieldwork or panel company?",
    "brand": "Does this company sell its own products or services to ordinary people (the public, "
             "consumers or patients), rather than only to other businesses?",
    "aec": "Does this company design, engineer or build buildings, roads, bridges, plants or other "
           "infrastructure?",
}


def _model_confirms(name: str, text: str, ctype: str) -> Optional[str]:
    """'yes' / 'no' -- or None when the model is unavailable."""
    from leads.local_llm_gate import queue_wait
    from leads.local_slm_client import LocalSLMError, chat_json
    try:
        with queue_wait(120, priority="bulk"):
            got = chat_json(system="Answer only yes or no, as JSON.",
                            user=(f"Company: {name}\nWhat it says about itself: {text[:900]}\n\n"
                                  + _QUESTIONS[ctype]),
                            max_tokens=10, json_schema=_YES_NO, timeout=90)
    except (LocalSLMError, Exception):
        return None
    return got.get("answer") if got.get("answer") in ("yes", "no") else None


async def _search(query: str, num: int = 10) -> List[Dict[str, Any]]:
    from leads.ingestion import perform_google_search
    return await perform_google_search(query, num_results=num, purpose="company")


def skrapp_text(client, domain: str, name: str) -> str:
    """'Industry: Real Estate | Puravankara Limited | Public Company | 1,001-5,000'
    from Skrapp's free company card; '' when it has none."""
    try:
        from leads import skrapp_client
        card = skrapp_client.company_snapshot(client, domain=domain, name="" if domain else name)
        if not card and domain and name:
            # no card under the email domain (a local or group domain): by name
            card = skrapp_client.company_snapshot(client, name=name)
    except Exception as e:
        logger.info("[CompanyFit] skrapp card failed for %s: %s", domain or name, e)
        return ""
    if not card:
        return ""
    parts = [f"Industry: {card['industry']}" if card.get("industry") else "", card.get("company_name") or "",
             card.get("type") or "", card.get("employees_range") or "", card.get("hq_country") or ""]
    return " | ".join(p for p in parts if p)


def resolve_one(db, doc: Dict[str, Any], now: datetime, allow_google: bool = True,
                allow_model: bool = True) -> str:
    """One step for one company -> typed | needs_google | needs_model | unclear | not_found."""
    name, domain = doc.get("name") or "", doc.get("domain") or ""
    upd: Dict[str, Any] = {"checked_at": now}
    li, li_url = doc.get("linkedin_text") or "", doc.get("linkedin_url") or ""
    ctype, evidence, source = None, "", ""
    # Skrapp's free company card first: LinkedIn's own industry, no quota
    sk = doc.get("skrapp_text")
    if sk is None and (domain or name):
        sk = skrapp_text(db.client, domain, name)
        upd["skrapp_text"] = sk
    sk = sk or ""
    if sk:
        (ctype, evidence), source = type_from_text(sk), "skrapp"
    if li and not ctype:
        (ctype, evidence), source = type_from_text(li), "linkedin"
    # the company's own website only when LinkedIn did not settle it
    site = doc.get("website_text")
    if site is None and domain and not ctype:
        site = website_text(domain)
        upd["website_text"] = site
    site = site or ""
    if not ctype and site:
        (ctype, evidence), source = type_from_text(site.split(" || ")[0]), "website"
    tried_google = bool(doc.get("linkedin_at"))  # Google runs in batches (linkedin_batch)
    text = " | ".join(t for t in (sk, li, site) if t)
    if not ctype and text and allow_model:
        ctype = _model_type(name or domain, text)
        if ctype:
            evidence, source = "model read the company's own text", "model"
    if ctype and ctype != "other":
        # Two independent checks must agree before anyone there is mailed:
        # the industry found above, and the model's yes to "is this company
        # really X?". In tests (2026-10-21) the local model never said yes
        # to a wrong pairing, but said no to about half of the right ones --
        # so a "no" goes to a person (status review), never to a campaign.
        upd.update({"proposed_type": ctype, "proposed_source": source, "evidence": evidence[:300]})
        if not allow_model:
            db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {**upd, "status": "needs_model"}})
            return "needs_model"
        ans = _model_confirms(name or domain, text, ctype)
        if ans == "yes" and ctype == "brand":
            # Research firms talk about consumers too: GWI and Egg Strategy
            # got a yes to "sells to ordinary people". A brand must also
            # NOT be a market research company.
            mr = _model_confirms(name or domain, text, "mr_agency")
            ans = None if mr is None else ("no" if mr == "yes" else "yes")
        if ans is None:  # outage: asked again, never a verdict
            db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {**upd, "status": "needs_model"}})
            return "model_unavailable"
        if ans == "no":
            db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {
                **upd, "status": "review", "ai_confirmed": False, "at": now}})
            logger.info("[CompanyFit] %s: %s by %s, AI does not confirm -> review", name or domain, ctype, source)
            return "review"
        upd["ai_confirmed"] = True
    if ctype:
        # "other" fits no campaign: nobody is mailed on it, so no second check
        upd.update({"type": ctype, "source": source, "evidence": evidence[:300], "status": "done", "at": now})
        db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": upd})
        n = rebasket_company(db, name, domain, ctype)
        logger.info("[CompanyFit] %s -> %s (%s %s, AI confirmed); %d leads re-basketed",
                    name or domain, ctype, source, evidence, n)
        return "typed"
    if not tried_google and (name or domain) and not text:
        # nothing readable yet; the next Google batch looks for its LinkedIn page
        db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {**upd, "status": "needs_google"}})
        return "needs_google"
    if text and not allow_model:
        db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {**upd, "status": "needs_model"}})
        return "needs_model"
    attempts = int(doc.get("attempts") or 0) + 1
    upd.update({"attempts": attempts, "status": "pending" if attempts < MAX_ATTEMPTS else "not_found",
                "last_result": "nothing readable" if not text else "text did not say",
                "next_try_at": now + timedelta(days=RETRY_DAYS),
                # read the site and LinkedIn afresh next time
                "website_text": None, "linkedin_at": None, "linkedin_text": ""})
    db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": upd})
    return "not_found" if not text else "unclear"


def queue_all(client=None) -> Dict[str, int]:
    """Queue every company we have mailed or could mail. Priority 3 = someone
    there is in a live sequence, 2 = someone there was mailed before (may need
    moving to the right campaign and mailing again), 1 = a lead with an email."""
    from pymongo import UpdateOne
    db = _db(client)
    tdb = db.client[os.getenv("MONGO_DB_NAME") or "torpedo"]
    best: Dict[str, Tuple[int, str, str]] = {}

    def _add(email: str, company: str, prio: int):
        dom = (email or "").lower().split("@")[-1] if "@" in (email or "") else ""
        dom = "" if dom in _WEBMAIL else dom
        key = company_key(company, dom)
        if key and (key not in best or best[key][0] < prio):
            best[key] = (prio, company or "", normalise_domain(dom))

    for r in tdb["outreach_leads_v2"].find({}, {"email": 1, "company_name": 1, "workflow_status": 1}):
        _add(r.get("email"), r.get("company_name") or "",
             3 if r.get("workflow_status") in ACTIVE_STATUSES else 2)
    for r in db["leads_enriched"].find({"email": {"$nin": [None, ""]}}, {"email": 1, "company_name": 1}):
        _add(r.get("email"), r.get("company_name") or "", 1)
    now = datetime.utcnow()
    ops = [UpdateOne({"_id": k}, {"$max": {"priority": p},
                                  "$setOnInsert": {"status": "pending", "attempts": 0, "queued_at": now,
                                                   "next_try_at": now, "name": n, "domain": d}},
                     upsert=True) for k, (p, n, d) in best.items()]
    for i in range(0, len(ops), 1000):
        db[COLLECTION].bulk_write(ops[i:i + 1000], ordered=False)
    return {"companies": len(best)}


def run(client=None, limit: int = 30, now: Optional[datetime] = None, model_calls: int = 20,
        google_calls: int = GOOGLE_CALLS_PER_RUN) -> Dict[str, Any]:
    """Work the queue, live-sequence companies first. Google (LinkedIn pages,
    5 companies per call, within the $5/day cap) is the main source; the
    company's own website fills in where LinkedIn says nothing, and is the
    whole source when the day's Google budget is spent. The model confirms."""
    db = _db(client)
    now = now or datetime.utcnow()
    stats: Dict[str, Any] = {}
    try:
        ensure_indexes(client)
    except Exception:
        pass
    col = db[COLLECTION]
    sort = [("priority", -1), ("queued_at", 1)]

    def _note(kind, r):
        stats[kind + r] = stats.get(kind + r, 0) + 1

    def _resolve(kind, doc, **kw):
        try:
            _note(kind, resolve_one(db, doc, now, **kw))
        except Exception as e:
            logger.warning("[CompanyFit] lookup failed for %r: %s", doc.get("name"), e)
            _note(kind, "error")

    # 1. Google: LinkedIn pages, GOOGLE_BATCH companies per call (no model
    #    needed -- runs first so a busy model never holds it up)
    waiting = {"status": "needs_google", "type": {"$exists": False},
               "linkedin_at": None, "next_try_at": {"$lte": now}}
    calls = 0
    while calls < google_calls and _google_left() > 0:
        batch = list(col.find(waiting).sort(sort).limit(GOOGLE_BATCH))
        if not batch:
            break
        calls += 1
        try:
            stats["google_found"] = stats.get("google_found", 0) + linkedin_batch(db, batch, now)
        except Exception as e:
            logger.warning("[CompanyFit] google batch failed: %s", e)
            break
        for doc in batch:
            _resolve("", doc, allow_google=False, allow_model=False)
    stats["google_calls"] = calls
    # 2. the model confirms (or decides) what the text in hand points to.
    #    The one model slot is shared and RFQ/extraction outrank this; when
    #    it is busy (a wait times out) stop and leave the rest for next run.
    for doc in col.find({"status": "needs_model"}).sort(sort).limit(model_calls):
        _resolve("model:", doc, allow_google=False, allow_model=True)
        if stats.get("model:model_unavailable"):
            break
    # 3. new companies: Skrapp's free card, then their own website
    for doc in col.find({"status": "pending", "type": {"$exists": False},
                         "next_try_at": {"$lte": now}}).sort(sort).limit(limit):
        _resolve("new:", doc, allow_google=False, allow_model=False)
    logger.info("[CompanyFit] %s", stats)
    return stats


def ensure_indexes(client=None) -> None:
    db = _db(client)
    db[COLLECTION].create_index([("status", 1), ("priority", -1), ("queued_at", 1)])
    db["leads_enriched"].create_index("company_domain")
