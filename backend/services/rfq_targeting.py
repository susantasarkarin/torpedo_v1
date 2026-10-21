"""
Screening criteria read from the client's RFQ email (2026-10-20), for the
project form's "Fill from RFQ" button -- a suggestion the team checks and
applies; nothing is applied on its own.

The client's RFQs follow one layout (Hansa, 7 live studies checked):

    Target Group:                       <- or Target Audience / TG / Target Respondents
      * Males/Females (80:20)           gender split = quota, both genders screened in
      * Women only                      gender screen
      * Aged 18-60 years old (...)      age range (first range in the block)
      * NCCS A/B                        NCCS grades (A = A1-A3, B = B1-B2, ...)
      * Mothers of kids aged 5-12       children criteria
      * Who watch YouTube weekly        anything else: listed, not screened
    LOI - 10 Min / IR: 40%
    Sample Plan: Mumbai 100 / Delhi NCR 100 / ...   cities

Read from the first client message of the project's thread that has a target
block (the thread is found by the RFQ link, else by the project name, which
starts with the RFQ subject), with attachments' text when the RFQ reader
already extracted it.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from services.respondent_profile import norm_place

_CITIES = [
    "Mumbai", "Delhi", "Delhi NCR", "New Delhi", "Gurugram", "Gurgaon", "Noida", "Ghaziabad", "Faridabad",
    "Bengaluru", "Bangalore", "Chennai", "Kolkata", "Hyderabad", "Pune", "Ahmedabad", "Surat", "Vadodara",
    "Baroda", "Rajkot", "Jaipur", "Lucknow", "Kanpur", "Nagpur", "Indore", "Bhopal", "Patna", "Ranchi",
    "Raipur", "Bhubaneswar", "Guwahati", "Chandigarh", "Ludhiana", "Amritsar", "Jalandhar", "Dehradun",
    "Coimbatore", "Madurai", "Trichy", "Tiruchirappalli", "Kochi", "Cochin", "Thiruvananthapuram",
    "Trivandrum", "Kozhikode", "Calicut", "Visakhapatnam", "Vizag", "Vijayawada", "Mysuru", "Mysore",
    "Mangaluru", "Mangalore", "Hubli", "Belagavi", "Nashik", "Aurangabad", "Thane", "Navi Mumbai",
    "Varanasi", "Prayagraj", "Allahabad", "Agra", "Meerut", "Jodhpur", "Udaipur", "Kota", "Gwalior",
    "Jabalpur", "Siliguri", "Durgapur", "Asansol", "Jamshedpur", "Dhanbad", "Cuttack", "Goa", "Panaji",
    "Srinagar", "Jammu", "Shimla", "Puducherry", "Pondicherry", "Salem", "Tiruppur", "Warangal", "Guntur",
    "Pimpri-Chinchwad", "Howrah", "Vasai-Virar", "Kalyan", "Bareilly", "Aligarh", "Moradabad", "Gorakhpur",
]
# one spelling per city in suggestions
_PREFERRED = {"bangalore": "Bengaluru", "gurgaon": "Gurugram", "new delhi": "Delhi", "baroda": "Vadodara",
              "cochin": "Kochi", "trivandrum": "Thiruvananthapuram", "calicut": "Kozhikode", "vizag": "Visakhapatnam",
              "mysore": "Mysuru", "mangalore": "Mangaluru", "allahabad": "Prayagraj", "pondicherry": "Puducherry",
              "trichy": "Tiruchirappalli"}
_CITY_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted((re.escape(c) for c in _CITIES), key=len, reverse=True)) + r")(?![A-Za-z])", re.I)
_CANON = {c.lower(): c for c in _CITIES}
# Delhi NCR covers its satellite cities
NCR = ["Delhi", "Gurugram", "Noida", "Ghaziabad", "Faridabad"]

_START = re.compile(r"(?im)^\W*(target\s*(group|audience|respondents?|segment)|\bTG\b)")
_END = re.compile(r"(?im)^\W*(thank\s*you|thanks|best\s+regards|regards|disclaimer|from:\s)")
_NCCS_GROUPS = {"A": ["A1", "A2", "A3"], "B": ["B1", "B2"], "C": ["C1", "C2"], "D": ["D1", "D2"], "E": ["E1", "E2", "E3"]}


def brief_block(text: str) -> str:
    """The target-group block through the sample plan, without signature or quoted mail."""
    text = (text or "").replace("\r\n", "\n")
    m = _START.search(text)
    if not m:
        return ""
    rest = text[m.start():]
    end = _END.search(rest, 20)
    return rest[: end.start()] if end else rest[:6000]


def _ages(block: str) -> Tuple[Optional[int], Optional[int], str]:
    for m in re.finditer(r"(?i)(\d{2})\s*(?:-|–|—|to)\s*(\d{2})\s*(?:years?|yrs?|y\.?o\.?)?", block):
        lo, hi = int(m.group(1)), int(m.group(2))
        line_end = block.find("\n", m.start())
        line = block[block.rfind("\n", 0, m.start()) + 1: line_end if line_end > 0 else None]
        if re.search(r"(?i)\b(aged?|years?|yrs|adults?)\b", line) and 12 <= lo < hi <= 99 \
                and not re.search(r"(?i)\b(kids?|child(ren)?|son|daughter)\b", line):
            return lo, hi, line.strip()
    m = re.search(r"(?i)\b(\d{2})\s*\+\s*(?:years?|yrs)|(?:above|over)\s+(\d{2})\s*(?:years?|yrs)"
                  r"|\bage[sd]?\s*[:\-]?\s*(\d{2})\s*(?:years?\s*)?(?:and|&)\s*(?:above|over)", block)
    if m:
        lo = int(m.group(1) or m.group(2) or m.group(3))
        return lo, None, m.group(0)
    return None, None, ""


def _nccs(block: str) -> Tuple[List[str], str]:
    m = re.search(r"(?i)\b(NCCS|SEC)\b\s*[:\-]?\s*((?:[A-E][1-3]?\b\s*(?:/|,|&|\+|and|or)?\s*)+)", block)
    if not m:
        return [], ""
    grades: List[str] = []
    for tok in re.findall(r"[A-E][1-3]?", m.group(2).upper()):
        for g in (_NCCS_GROUPS[tok] if len(tok) == 1 else [tok]):
            if g not in grades:
                grades.append(g)
    return grades, m.group(0).strip()


def _gender(block: str) -> Tuple[List[str], str]:
    if re.search(r"(?i)\b(women|females?|ladies|housewives|mothers)\s+only\b|\bonly\s+(women|females?)\b|\bhousewives\b", block):
        return ["f"], "women only"
    if re.search(r"(?i)\b(men|males?)\s+only\b|\bonly\s+(men|males?)\b", block):
        return ["m"], "men only"
    m = re.search(r"(?im)^.*\bmothers?\s+(of|with)\b.*$", block)
    if m:
        return ["f"], m.group(0).strip()
    return [], ""


def _children(block: str) -> Tuple[Dict[str, int], str]:
    m = re.search(r"(?i)\b(mothers?|fathers?|parents?|having|with|has)\b[^\n]{0,30}?\b(kids?|child(?:ren)?)\b[^\n]{0,20}?"
                  r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})", block)
    if m:
        lo, hi = int(m.group(3)), int(m.group(4))
        if 0 <= lo <= hi <= 17:
            return {"childrenMin": 1, "childAgeMin": lo, "childAgeMax": hi}, m.group(0).strip()
    m = re.search(r"(?i)\b(mothers?|fathers?|parents?)\s+of\s+(kids?|child(?:ren)?)\b", block)
    if m:
        return {"childrenMin": 1}, m.group(0).strip()
    return {}, ""


def _cities(block: str) -> List[str]:
    if re.search(r"(?i)\bpan[\s-]*india\b", block):
        return []
    out: List[str] = []
    seen = set()
    for m in _CITY_RE.finditer(block):
        name = _CANON[m.group(1).lower()]
        for c in (NCR if name == "Delhi NCR" else [_PREFERRED.get(name.lower(), name)]):
            if norm_place(c) not in seen:
                seen.add(norm_place(c))
                out.append(c)
    return out


def extract(text: str) -> Dict[str, Any]:
    """{qualification: {...criteria found}, found: [{field, value, from}], notes: [lines not screened], loi, ir}."""
    block = brief_block(text)
    if not block:
        return {"qualification": {}, "found": [], "notes": [], "block": ""}
    qual: Dict[str, Any] = {}
    found = []
    lo, hi, age_src = _ages(block)
    if lo is not None:
        qual["ageMin"] = lo
        if hi is not None:
            qual["ageMax"] = hi
        found.append({"field": "age", "value": f"{lo}-{hi}" if hi else f"{lo}+", "from": age_src})
    genders, g_src = _gender(block)
    if genders:
        qual["genders"] = genders
        found.append({"field": "gender", "value": "female" if genders == ["f"] else "male", "from": g_src})
    grades, n_src = _nccs(block)
    if grades:
        qual["nccs"] = grades
        found.append({"field": "nccs", "value": "/".join(grades), "from": n_src})
    kids, k_src = _children(block)
    if kids:
        qual.update(kids)
        found.append({"field": "children", "value": kids, "from": k_src})
    cities = _cities(block)
    if cities:
        qual["cities"] = ", ".join(cities)
        found.append({"field": "cities", "value": ", ".join(cities), "from": "sample plan / markets"})
    loi = re.search(r"(?i)\bLOI\s*[:\-]?\s*(\d{1,3})\s*min", block)
    ir = re.search(r"(?i)\bIR\s*[:\-]?\s*(\d{1,3})\s*%", block)
    used = {s for s in (age_src, g_src, n_src, k_src) if s}
    notes = []
    for line in block.split("\n"):
        line = line.strip(" \t*•o-–·").strip()
        if (len(line) < 12 or _START.match(line) or any(line in u or u in line for u in used)
                or re.match(r"(?i)^(LOI|IR|market|sample|centres?|cities|total|pp|males?/females?|core tg)\b", line)
                or re.fullmatch(r"[\d\s,%()]+", line) or _CITY_RE.fullmatch(line)):
            continue
        if re.search(r"(?i)\b(males?\s*/\s*females?)\b", line):
            continue
        notes.append(line[:200])
    return {"qualification": qual, "found": found, "notes": notes[:15], "block": block[:4000],
            "loi": int(loi.group(1)) if loi else None, "ir": int(ir.group(1)) if ir else None}


def rfq_subject(project_name: str) -> str:
    """'RE: RFQ_Abha_Brand Uplift Study_HRG_SFW - Dubur amala' -> 'RFQ_Abha_Brand Uplift Study_HRG_SFW'."""
    name = re.sub(r"(?i)^\s*((re|fw|fwd)\s*:\s*)+", "", project_name or "")
    return name.split(" - ")[0].strip()


async def find_brief(mail_col, project: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The first client message of the project's RFQ thread that has a target block."""
    query: Dict[str, Any] = {"direction": {"$ne": "outbound"}}
    ors = []
    if project.get("rfqId"):
        ors.append({"rfq_id": str(project["rfqId"])})
    subject = rfq_subject(str(project.get("projectName") or ""))
    if len(subject) >= 8:
        # "RFQ_Life Insurance Cues 2026 Part 2_HRG_SFW" was renamed "RFQ_Mid Year_Life ..." on the project
        core = re.sub(r"(?i)^RFQ_|_HRG_SFW$", "", subject)
        ors.append({"subject": {"$regex": re.escape(subject), "$options": "i"}})
        if len(core) >= 6:
            ors.append({"subject": {"$regex": re.escape(core), "$options": "i"}})
    if not ors:
        return None
    query["$or"] = ors
    proj = {"subject": 1, "body_plain": 1, "timestamp": 1, "attachment_text": 1, "from_email": 1}
    async for m in mail_col.find(query, proj).sort("timestamp", 1).limit(60):
        text = m.get("body_plain") or ""
        for a in m.get("attachment_text") or []:
            text += "\n" + str((a or {}).get("text") or "")
        if brief_block(text):
            return {"subject": m.get("subject"), "at": m.get("timestamp"), "from": m.get("from_email"), "text": text}
    return None
