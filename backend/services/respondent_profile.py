"""
Respondent targeting profile beyond age / gender (2026-10-20): state, city, PIN /
postcode, children (count and ages) and NCCS -- how surveys are targeted.

Where the profile comes from:
  SurveyFieldwork Panel members  their panel profile (services/panel_profile.py):
                                 CORE_05 state, CORE_06 city, CORE_07 PIN, CORE_13 /
                                 CORE_14 children, CORE_19 + CORE_20 NCCS inputs
  everyone else                  the landing page asks -- only what the surveys they
                                 could enter screen on, and only what is not known

Project criteria (projects.qualification, all optional, empty = not checked):
  states[], cities[]           any of these (case-insensitive; Bombay = Mumbai etc.)
  zipPrefixes[]                PIN / postcode starts with any of these, e.g. "400", "110"
  childrenMin, childrenMax     number of children under 18 in the household
  childAgeMin, childAgeMax     at least one child within this age range
  nccs[]                       grades A1..E3 -- India only: ignored on a project in any
                               other country, and never asked outside India

NCCS (India, MRUC 2011): grade from the chief income earner's education (7 levels)
x how many of 11 listed household items the household has. Same education levels
and items as the panel's CORE_19 / CORE_20, so panel and landing answers agree.
"""
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

NCCS_GRADES = ["A1", "A2", "A3", "B1", "B2", "C1", "C2", "D1", "D2", "E1", "E2", "E3"]

NCCS_EDUCATION = [
    "Illiterate",
    "Literate, no formal schooling / school up to 4 years",
    "School 5-9 years",
    "SSC / HSC",
    "Some college (incl. diploma) but not graduate",
    "Graduate / post-graduate - general",
    "Graduate / post-graduate - professional",
]
NCCS_DURABLES = [
    "Electricity connection", "Ceiling fan", "LPG stove", "Two-wheeler", "Colour TV", "Refrigerator",
    "Washing machine", "Personal computer / laptop", "Car / jeep / van", "Air conditioner", "Agricultural land",
]
# rows: number of items owned 0..9+; columns: education level 1..7
_NCCS_GRID = [
    ["E3", "E2", "E2", "E2", "E2", "E1", "D2"],
    ["E2", "E1", "E1", "E1", "D2", "D2", "D2"],
    ["E1", "E1", "D2", "D2", "D1", "D1", "D1"],
    ["D2", "D2", "D1", "D1", "C2", "C2", "C2"],
    ["D1", "C2", "C2", "C1", "C1", "B2", "B2"],
    ["C2", "C1", "C1", "B2", "B1", "B1", "B1"],
    ["C1", "B2", "B2", "B1", "A3", "A3", "A3"],
    ["C1", "B1", "B1", "A3", "A3", "A2", "A2"],
    ["B1", "A3", "A3", "A3", "A2", "A2", "A2"],
    ["B1", "A3", "A3", "A2", "A2", "A1", "A1"],
]

_CITY_ALIASES = {
    "bombay": "mumbai", "navi mumbai": "mumbai", "thane": "thane", "new delhi": "delhi", "delhi ncr": "delhi",
    "bangalore": "bengaluru", "bengaluru urban": "bengaluru", "calcutta": "kolkata", "madras": "chennai",
    "gurgaon": "gurugram", "poona": "pune", "baroda": "vadodara", "mysore": "mysuru", "trivandrum": "thiruvananthapuram",
    "cochin": "kochi", "vizag": "visakhapatnam", "benares": "varanasi", "banaras": "varanasi", "allahabad": "prayagraj",
    "pondicherry": "puducherry", "calicut": "kozhikode", "mangalore": "mangaluru", "belgaum": "belagavi",
}
OTHER = "__other__"
PROFILE_FIELDS = ("state", "city", "zip_code", "children_ages", "nccs")


def nccs_grade(education: Any, items_owned: int) -> Optional[str]:
    try:
        col = int(education) - 1
    except (TypeError, ValueError):
        return None
    if not 0 <= col < 7 or items_owned is None or items_owned < 0:
        return None
    return _NCCS_GRID[min(items_owned, 9)][col]


def norm_place(value: Any) -> str:
    v = re.sub(r"[^a-z ]", " ", str(value or "").lower())
    v = re.sub(r"\s+", " ", v).strip()
    v = re.sub(r"\b(city|district|urban)$", "", v).strip()
    return _CITY_ALIASES.get(v, v)


def _ints(values: Any, lo: int, hi: int) -> List[int]:
    out = []
    for v in values if isinstance(values, list) else []:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if lo <= n <= hi:
            out.append(n)
    return out


# ---------------------------------------------------------------------------
# Where the profile comes from
# ---------------------------------------------------------------------------

def from_panel_answers(answers: Dict[str, Any], country: str = "", today: Optional[date] = None) -> Dict[str, Any]:
    """Targeting fields from a panel member's profileAnswers; absent when never answered."""
    answers = answers or {}
    today = today or date.today()
    out: Dict[str, Any] = {}
    if str(answers.get("CORE_05") or "").strip():
        out["state"] = str(answers["CORE_05"]).strip()
    if str(answers.get("CORE_06") or "").strip():
        out["city"] = str(answers["CORE_06"]).strip()
    if str(answers.get("CORE_07") or "").strip():
        out["zip_code"] = str(answers["CORE_07"]).strip()
    count = answers.get("CORE_13")
    kids = answers.get("CORE_14")
    if isinstance(kids, list) and kids:
        ages = [today.year - int(k["birthYear"]) for k in kids
                if isinstance(k, dict) and str(k.get("birthYear") or "").isdigit()]
        out["children_ages"] = [a for a in ages if 0 <= a <= 17]
    elif str(count).strip() == "0" or answers.get("CORE_12") == 1:
        out["children_ages"] = []          # said none, or lives alone
    if (country or str(answers.get("CORE_04") or "")).upper() == "IN":
        items = answers.get("CORE_20")
        if isinstance(items, list) and answers.get("CORE_19") is not None:
            owned = len(set(_ints(items, 1, 11)))
            grade = nccs_grade(answers.get("CORE_19"), owned)
            if grade:
                out["nccs"] = grade
    return out


def from_landing_answers(answers: Dict[str, Any]) -> Dict[str, Any]:
    """Targeting fields from the landing page's p_* answers (already cleaned)."""
    out: Dict[str, Any] = {}
    for field, key in (("state", "p_state"), ("city", "p_city"), ("zip_code", "p_zip")):
        if answers.get(key):
            out[field] = answers[key]
    if isinstance(answers.get("p_children"), list):
        out["children_ages"] = answers["p_children"]
    if answers.get("p_nccs_edu") and isinstance(answers.get("p_nccs_items"), list):
        grade = nccs_grade(answers["p_nccs_edu"], len(answers["p_nccs_items"]))
        if grade:
            out["nccs"] = grade
    return out


def clean_answers(raw: Dict[str, Any]) -> Dict[str, Any]:
    """The p_* landing answers, validated; unknown keys dropped."""
    out: Dict[str, Any] = {}
    for key in ("p_state", "p_city"):
        v = str(raw.get(key) or "").strip()[:80]
        if v:
            out[key] = v
    zip_code = re.sub(r"[^A-Za-z0-9 ]", "", str(raw.get("p_zip") or "")).strip().upper()[:10]
    if zip_code:
        out["p_zip"] = zip_code
    if isinstance(raw.get("p_children"), list):
        out["p_children"] = _ints(raw["p_children"], 0, 17)[:10]
    edu = str(raw.get("p_nccs_edu") or "").strip()
    if edu.isdigit() and 1 <= int(edu) <= 7:
        out["p_nccs_edu"] = edu
    if isinstance(raw.get("p_nccs_items"), list):
        out["p_nccs_items"] = sorted(set(_ints(raw["p_nccs_items"], 1, 11)))
    return out


# ---------------------------------------------------------------------------
# Criteria
# ---------------------------------------------------------------------------

def _list(raw: Any) -> List[str]:
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(v).strip() for v in (raw if isinstance(raw, list) else []) if str(v).strip()][:200]


def _int(raw: Any, lo: int, hi: int) -> Optional[int]:
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def criteria(raw: Dict[str, Any], country: str = "") -> Dict[str, Any]:
    """country: the project's; NCCS applies to India projects (or projects with no country set)."""
    raw = raw if isinstance(raw, dict) else {}
    india = str(country or "IN").strip().upper() in ("IN", "")
    return {
        "states": _list(raw.get("states")),
        "cities": _list(raw.get("cities")),
        "zipPrefixes": [re.sub(r"\s", "", z).upper() for z in _list(raw.get("zipPrefixes"))],
        "childrenMin": _int(raw.get("childrenMin"), 0, 10),
        "childrenMax": _int(raw.get("childrenMax"), 0, 10),
        "childAgeMin": _int(raw.get("childAgeMin"), 0, 17),
        "childAgeMax": _int(raw.get("childAgeMax"), 0, 17),
        "nccs": [g for g in (v.upper() for v in _list(raw.get("nccs"))) if g in NCCS_GRADES] if india else [],
    }


def needed_fields(crit: Dict[str, Any]) -> List[str]:
    out = []
    if crit["states"]:
        out.append("state")
    if crit["cities"]:
        out.append("city")
    if crit["zipPrefixes"]:
        out.append("zip_code")
    if any(crit[k] is not None for k in ("childrenMin", "childrenMax", "childAgeMin", "childAgeMax")):
        out.append("children_ages")
    if crit["nccs"]:
        out.append("nccs")
    return out


def reasons(crit: Dict[str, Any], profile: Dict[str, Any]) -> List[str]:
    """Why this profile fails these criteria ([] = qualifies). Missing data fails as '<field>_missing'."""
    profile = profile or {}
    out = []
    if crit["states"]:
        state = norm_place(profile.get("state"))
        if not state:
            out.append("state_missing")
        elif state not in {norm_place(s) for s in crit["states"]}:
            out.append("state")
    if crit["cities"]:
        city = norm_place(profile.get("city"))
        if not city:
            out.append("city_missing")
        elif city not in {norm_place(c) for c in crit["cities"]}:
            out.append("city")
    if crit["zipPrefixes"]:
        z = re.sub(r"\s", "", str(profile.get("zip_code") or "")).upper()
        if not z:
            out.append("zip_missing")
        elif not any(z.startswith(p) for p in crit["zipPrefixes"]):
            out.append("zip")
    if "children_ages" in needed_fields(crit):
        ages = profile.get("children_ages")
        if not isinstance(ages, list):
            out.append("children_missing")
        else:
            if crit["childrenMin"] is not None and len(ages) < crit["childrenMin"]:
                out.append("children")
            elif crit["childrenMax"] is not None and len(ages) > crit["childrenMax"]:
                out.append("children")
            if crit["childAgeMin"] is not None or crit["childAgeMax"] is not None:
                lo = crit["childAgeMin"] if crit["childAgeMin"] is not None else 0
                hi = crit["childAgeMax"] if crit["childAgeMax"] is not None else 17
                if not any(lo <= a <= hi for a in ages):
                    out.append("child_age")
    if crit["nccs"]:
        grade = profile.get("nccs")
        if not grade:
            out.append("nccs_missing")
        elif grade not in crit["nccs"]:
            out.append("nccs")
    return out


# ---------------------------------------------------------------------------
# Landing-page questions
# ---------------------------------------------------------------------------

def questions(crits: List[Dict[str, Any]], known: Dict[str, Any], country: str = "") -> List[Dict[str, Any]]:
    """Questions for fields some project screens on and the profile does not hold.
    State and city are asked as a list: every target place across the surveys, plus
    'Somewhere else' -- so the answer always matches how the criteria are written."""
    known = known or {}
    fields = []
    for c in crits:
        for f in needed_fields(c):
            if f not in fields and (known.get(f) in (None, "") if f != "children_ages" else not isinstance(known.get(f), list)):
                fields.append(f)
    out = []
    for f in fields:
        if f in ("state", "city"):
            places, seen = [], set()
            for c in crits:
                for p in c["states" if f == "state" else "cities"]:
                    if norm_place(p) not in seen:
                        seen.add(norm_place(p))
                        places.append(p)
            out.append({"id": f"p_{f}", "type": "select",
                        "text": "Which state do you live in?" if f == "state" else "Which city do you live in?",
                        "options": [{"value": p, "label": p} for p in sorted(places, key=str.lower)]
                        + [{"value": OTHER, "label": "Somewhere else"}]})
        elif f == "zip_code":
            india = country.upper() == "IN"
            out.append({"id": "p_zip", "type": "text",
                        "text": "What is your PIN code?" if india else "What is your postcode / ZIP code?",
                        "pattern": "^[1-9][0-9]{5}$" if india else "^[A-Za-z0-9 ]{3,10}$",
                        "placeholder": "6 digits" if india else ""})
        elif f == "children_ages":
            out.append({"id": "p_children", "type": "children",
                        "text": "How many children under 18 live in your household?",
                        "ageText": "Age of child", "max": 6})
        elif f == "nccs" and country.upper() in ("IN", ""):
            out.append({"id": "p_nccs_edu", "type": "select",
                        "text": "What is the highest education of the main earner in your household?",
                        "options": [{"value": str(i + 1), "label": t} for i, t in enumerate(NCCS_EDUCATION)]})
            out.append({"id": "p_nccs_items", "type": "multi",
                        "text": "Which of these does your household have? (tick all that apply)",
                        "noneLabel": "None of these",
                        "options": [{"value": str(i + 1), "label": t} for i, t in enumerate(NCCS_DURABLES)]})
    return out


def merge(profile: Dict[str, Any], *sources: Dict[str, Any]) -> Dict[str, Any]:
    """profile + targeting fields from the sources (earlier source wins; never overwrite a known value)."""
    out = dict(profile or {})
    for src in sources:
        for k in PROFILE_FIELDS:
            if k in (src or {}) and (out.get(k) in (None, "") and not isinstance(out.get(k), list)):
                out[k] = src[k]
    return out


def split_answers(answers: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(qualification answers, p_* profile answers)."""
    prof = {k: v for k, v in (answers or {}).items() if str(k).startswith("p_")}
    return {k: v for k, v in (answers or {}).items() if k not in prof}, prof
