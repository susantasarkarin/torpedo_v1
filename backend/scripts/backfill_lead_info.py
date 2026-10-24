"""
BACKFILL LEAD INFORMATION
=========================
Fills empty Lead Information fields on Sales > Leads records from data we
already hold: the address itself, the sender block the Gmail sync parsed for
each message (`sender_info`), and the signature of the lead's own emails.

Only empty fields are written — anything a person or an enrichment run set is
left alone. A first_name ending in a comma ("Kidd," from "Kidd, Tim (KWLWG)")
counts as empty: it is the surname of a "Last, First" display name split the
wrong way.

    python -m scripts.backfill_lead_info            # dry run, prints a sample
    python -m scripts.backfill_lead_info --apply
"""

import argparse
import os
import re
import sys
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

QUALIFIED_SOURCES = ["gmail", "gmail_contact", "gmail_calendar", "outreach_reply"]

PERSONAL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.co.uk",
    "hotmail.com", "outlook.com", "live.com", "msn.com", "icloud.com", "me.com",
    "aol.com", "proton.me", "protonmail.com", "rediffmail.com", "zoho.com",
    "gmx.com", "gmx.de", "web.de", "mail.com", "yandex.com", "yandex.ru", "qq.com",
    "163.com", "126.com",
}

CC_TLD_COUNTRY = {
    "in": "India", "uk": "United Kingdom", "us": "United States", "ca": "Canada",
    "au": "Australia", "nz": "New Zealand", "de": "Germany", "fr": "France",
    "es": "Spain", "it": "Italy", "nl": "Netherlands", "be": "Belgium",
    "ch": "Switzerland", "at": "Austria", "se": "Sweden", "no": "Norway",
    "dk": "Denmark", "fi": "Finland", "ie": "Ireland", "pt": "Portugal",
    "pl": "Poland", "cz": "Czech Republic", "ro": "Romania", "gr": "Greece",
    "tr": "Turkey", "ru": "Russia", "ua": "Ukraine", "il": "Israel",
    "ae": "United Arab Emirates", "sa": "Saudi Arabia", "qa": "Qatar",
    "eg": "Egypt", "za": "South Africa", "ng": "Nigeria", "ke": "Kenya",
    "sg": "Singapore", "my": "Malaysia", "id": "Indonesia", "th": "Thailand",
    "vn": "Vietnam", "ph": "Philippines", "cn": "China", "hk": "Hong Kong",
    "tw": "Taiwan", "jp": "Japan", "kr": "South Korea", "pk": "Pakistan",
    "bd": "Bangladesh", "lk": "Sri Lanka", "np": "Nepal", "br": "Brazil",
    "mx": "Mexico", "ar": "Argentina", "cl": "Chile", "pe": "Peru",
}
# .co, .io, .ai and .me are sold worldwide as generic names, so they say
# nothing about where the company is and are deliberately absent.

# Checked in order; the first tier with a whole-word hit wins. Substring
# matching (the old way) read "director" as C-Level because it contains "cto".
SENIORITY_RULES = [
    # VP first: "Vice President" also contains "president".
    ("VP", r"\b(vp|svp|evp|avp|vice president)\b"),
    ("C-Level", r"\b(ceo|cto|cfo|coo|cmo|cro|cio|chief|founder|co-founder|cofounder|owner|president|managing director|md|partner)\b"),
    ("Director", r"\b(director|head of|head)\b"),
    ("Manager", r"\b(manager|lead|team lead|supervisor)\b"),
    ("Entry", r"\b(intern|trainee|junior|assistant)\b"),
    ("IC", r"\b(analyst|executive|specialist|coordinator|associate|consultant|researcher|engineer|developer|officer)\b"),
]

DEPARTMENT_RULES = [
    ("Research", r"\b(research|insights?|analytics|data|field|fieldwork|panel|survey|quantitative|qualitative|quant|qual|quotation)\b"),
    ("Sales", r"\b(sales|business development|bd|account executive|account manager|revenue|commercial)\b"),
    ("Marketing", r"\b(marketing|growth|brand|content|seo|communications)\b"),
    ("Operations", r"\b(operations|ops|project manager|project management|delivery|supply chain)\b"),
    ("Procurement", r"\b(procurement|purchasing|sourcing|vendor management)\b"),
    ("Finance", r"\b(finance|accounts?|accounting|controller|billing)\b"),
    ("Engineering", r"\b(engineering|developer|software|devops|it|technology)\b"),
    ("HR", r"\b(hr|human resources|people|talent|recruit\w*)\b"),
    ("Executive", r"\b(ceo|founder|co-founder|owner|president|managing director|chief)\b"),
]

# Where the lead's own text ends and the quoted thread (often our own mail,
# signature included) begins.
QUOTE_MARKERS = re.compile(
    r"^(>|On .{4,200}wrote:|From:\s|\*From:\*|-{2,}\s*Original Message|_{10,}|Sent from my |Get Outlook for)",
    re.IGNORECASE | re.MULTILINE,
)

TITLE_LINE = re.compile(r"^(?:title|designation|position|role)\s*[:\-]\s*(.+)$", re.IGNORECASE | re.MULTILINE)
PIPE_SIG = re.compile(r"^[A-Z][\w.'\-]+(?:\s+[A-Z][\w.'\-]+){0,3}\s*[|–]\s*([^|–\n]{3,80})", re.MULTILINE)
PHONE = re.compile(r"(\b(?:tel|phone|mob(?:ile)?|cell|direct|m|t|p)\.?\s*[:\-]?\s*)?(\+?\(?\d[\d\s\-().]{6,20}\d)", re.IGNORECASE)
LINKEDIN = re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_%]+)", re.IGNORECASE)


def split_name(display: str) -> Tuple[str, str]:
    """(first, last) from a display name, handling "Last, First (Org)"."""
    name = re.sub(r"\s*[(<\[].*?[)>\]]\s*", " ", display or "").strip().strip("\"'")
    if not name or "@" in name:
        return "", ""
    if "," in name:
        last, _, first = name.partition(",")
        first, last = first.strip(), last.strip()
        if first and last:
            return first.split()[0].title() if first.isupper() else first.split()[0], last
    parts = name.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return (parts[0], "") if parts else ("", "")


def seniority_for(title: str) -> Optional[str]:
    t = (title or "").lower()
    for level, pat in SENIORITY_RULES:
        if re.search(pat, t):
            return level
    return None


def department_for(title: str) -> Optional[str]:
    t = (title or "").lower()
    for dept, pat in DEPARTMENT_RULES:
        if re.search(pat, t):
            return dept
    return None


def country_for(domain: str) -> Optional[str]:
    tld = (domain or "").rsplit(".", 1)[-1].lower()
    return CC_TLD_COUNTRY.get(tld)


def own_text(body: str) -> str:
    """The part of an email the sender wrote, before the quoted thread."""
    if not body:
        return ""
    m = QUOTE_MARKERS.search(body)
    return body[:m.start()] if m else body


def _clean_title(value: str) -> Optional[str]:
    """A job title, or None.

    The parsed sender block is model-written and fills `title` with whatever
    it found — "Not specified", "Terms and Conditions", a street address, a
    website. Only a value that names a role or a function is kept.
    """
    v = re.sub(r"\s+", " ", (value or "")).strip(" |-–,*")
    if not v or len(v) > 80 or "@" in v or "www." in v.lower() or "http" in v.lower() or re.search(r"\d", v):
        return None
    if not (seniority_for(v) or department_for(v)):
        return None
    return v


def signature_fields(body: str) -> Dict[str, str]:
    """Title, phone and LinkedIn from the sender's own signature block."""
    text = own_text(body)
    tail = "\n".join(text.strip().splitlines()[-15:])
    out = {}
    m = TITLE_LINE.search(tail) or PIPE_SIG.search(tail)
    if m and _clean_title(m.group(1)):
        out["title"] = _clean_title(m.group(1))
    for pm in PHONE.finditer(tail):
        number = pm.group(2).strip()
        digits = re.sub(r"\D", "", number)
        # An unlabelled run must look like a phone: a + prefix, 10+ digits
        # broken by separators, or a bare Indian mobile. Dates (18.04.2019)
        # and bare reference numbers (223404411203) otherwise pass.
        labelled = bool(pm.group(1))
        shaped = (number.startswith("+")
                  or (len(digits) >= 10 and re.search(r"[\s\-().]", number))
                  or re.fullmatch(r"[6-9]\d{9}", digits))
        if 7 <= len(digits) <= 15 and (labelled or shaped):
            out["phone"] = number
            break
    lm = LINKEDIN.search(tail)
    if lm:
        out["linkedin_url"] = f"https://www.linkedin.com/in/{lm.group(1)}"
    return out


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() in ("", "Unknown", "—"))


def derive_lead_info(lead: Dict, messages: List[Dict]) -> Dict:
    """Fields to $set on this lead. `messages` are the lead's own emails, newest first."""
    updates: Dict = {}
    email = (lead.get("email") or "").strip().lower()
    domain = email.split("@", 1)[1] if email.count("@") == 1 else ""

    def fill(field, value):
        if value and _empty(lead.get(field)) and field not in updates:
            updates[field] = value

    first, last = split_name(lead.get("name") or "")
    if first and (_empty(lead.get("first_name")) or str(lead.get("first_name")).endswith(",")):
        updates["first_name"] = first
    if last and (_empty(lead.get("last_name")) or "first_name" in updates):
        updates["last_name"] = last

    if domain and domain not in PERSONAL_DOMAINS:
        fill("company_domain", domain)
        fill("company_website", f"https://{domain}")
    fill("country", country_for(domain))

    for msg in messages:
        info = msg.get("sender_info") if isinstance(msg.get("sender_info"), dict) else {}
        fill("title", _clean_title(info.get("title") or ""))
        fill("phone", (info.get("phone") or "").strip() or None)
        fill("location", (info.get("location") or "").strip() or None)
        fill("linkedin_url", (info.get("linkedin") or "").strip() or None)
        fill("company_industry", (info.get("company_industry") or "").strip() or None)
        fill("company_size", (info.get("company_size") or "").strip() or None)
    for msg in messages:
        for field, value in signature_fields(msg.get("body_plain") or "").items():
            fill(field, value)

    title = updates.get("title") or lead.get("title") or ""
    fill("seniority_level", seniority_for(title))
    fill("department", department_for(title))
    return updates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    client = MongoClient(MONGO_URI)
    leads = client["email_automation"]["leads_enriched"]
    mail = client["torpedo_gmail"]["email_metadata"]

    query = {"$or": [{"source": {"$in": QUALIFIED_SOURCES}},
                     {"outreach_replied_at": {"$exists": True}}]}
    cursor = leads.find(query, {"email": 1, "name": 1, "first_name": 1, "last_name": 1,
                                "company_domain": 1, "company_website": 1, "country": 1,
                                "title": 1, "phone": 1, "location": 1, "linkedin_url": 1,
                                "company_industry": 1, "company_size": 1,
                                "seniority_level": 1, "department": 1})
    if args.limit:
        cursor = cursor.limit(args.limit)

    filled = Counter()
    touched = 0
    samples = []
    now = datetime.utcnow()
    for lead in cursor:
        email = (lead.get("email") or "").strip().lower()
        if not email:
            continue
        messages = [m for m in mail.find(
            {"mail_counterparty": email},
            {"from_email": 1, "sender_info": 1, "body_plain": 1},
        ).sort("timestamp", -1).limit(25)
            if (m.get("from_email") or "").strip().lower() == email][:10]
        updates = derive_lead_info(lead, messages)
        if not updates:
            continue
        touched += 1
        filled.update(updates.keys())
        if len(samples) < 12:
            samples.append(f"{email}: {updates}")
        if args.apply:
            updates["lead_info_backfilled_at"] = now
            leads.update_one({"_id": lead["_id"]}, {"$set": updates})

    for s in samples:
        print(s)
    print(f"\n{'UPDATED' if args.apply else 'WOULD UPDATE'} {touched:,} leads")
    for field, n in filled.most_common():
        print(f"  {field:18} {n:,}")
    if not args.apply:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
