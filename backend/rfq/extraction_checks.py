"""Code checks on an RFQ extraction (owner, 2026-10-24): these replace the
model's self-reported confidence, which the benchmark showed is uncalibrated.

An extraction passes only if every check holds:
  required   at least one line item with country, N and LOI (IR may be absent:
             client defaults or a missing-info reply handle it)
  ranges     LOI 1-120 min, IR 0.1-100 %, N 1-100,000, country an ISO-2 code
  grounded   every LOI / IR / N number appears in the source text, and every
             country is named in it (code or a known name), so a value the
             model invented cannot pass
  coverage   every country the source names (from a known list) is in some line
             item, so a dropped market (seen in the 1.5B benchmark) fails

Until the 7B benchmark reaches >= 95% per field, a pass still goes to the
Review Queue; the result only says *why* a person should look.
"""
import re
from typing import Any, Dict, List

COUNTRY_NAMES = {
    "IN": ["india"], "US": ["usa", "united states", "u.s.", "america", "united states of america"], "GB": ["uk", "united kingdom", "britain", "england"],
    "DE": ["germany"], "FR": ["france"], "JP": ["japan"], "KR": ["korea", "south korea", "south-corea"],
    "BR": ["brazil"], "CN": ["china", "mainland china"], "MX": ["mexico"], "SG": ["singapore"],
    "AU": ["australia"], "NZ": ["new zealand"], "CA": ["canada"], "IT": ["italy"], "ES": ["spain"],
    "ZA": ["south africa", "south-africa"], "HK": ["hong kong"], "TW": ["taiwan"], "AE": ["uae", "emirates"],
    "SA": ["ksa", "saudi"], "ID": ["indonesia"], "MY": ["malaysia"], "PH": ["philippines"], "TH": ["thailand"],
    "VN": ["vietnam"], "CH": ["switzerland"], "QA": ["qatar"], "KW": ["kuwait"], "NL": ["netherlands"],
    "IE": ["ireland"], "PL": ["poland"], "TR": ["turkey"], "AR": ["argentina"], "CL": ["chile"],
    "CO": ["colombia", "columbia"], "PE": ["peru"], "NG": ["nigeria"], "KE": ["kenya"], "EG": ["egypt"],
    "GH": ["ghana"], "TZ": ["tanzania"], "ET": ["ethiopia"], "MA": ["morocco", "marokko"], "DZ": ["algeria"],
    "TN": ["tunisia"], "UG": ["uganda"], "MG": ["madagascar"], "LY": ["libya"], "SN": ["senegal"],
    "CI": ["ivory coast", "cote d'ivoire"], "CM": ["cameroon"], "ZW": ["zimbabwe"], "ZM": ["zambia"],
    "HU": ["hungary"], "CZ": ["czech republic", "czechia"], "EE": ["estonia"], "LV": ["latvia"], "LT": ["lithuania"],
    "SK": ["slovakia"], "SI": ["slovenia"], "HR": ["croatia"], "RS": ["serbia"], "RO": ["romania"],
    "BG": ["bulgaria"], "GR": ["greece"], "PT": ["portugal"], "AT": ["austria"], "BE": ["belgium"],
    "DK": ["denmark"], "SE": ["sweden"], "NO": ["norway"], "FI": ["finland"], "UA": ["ukraine"],
    "RU": ["russia"], "AL": ["albania"], "IL": ["israel"], "JO": ["jordan"], "LB": ["lebanon"], "IQ": ["iraq"],
    "IR": ["iran"], "OM": ["oman"], "BH": ["bahrain"], "PK": ["pakistan"], "BD": ["bangladesh"],
    "LK": ["sri lanka"], "NP": ["nepal"], "MM": ["myanmar"], "KH": ["cambodia"], "KZ": ["kazakhstan"],
    "VE": ["venezuela"], "BO": ["bolivia"], "EC": ["ecuador"], "UY": ["uruguay"], "PY": ["paraguay"],
    "DO": ["dominican republic"], "PR": ["puerto rico"], "GT": ["guatemala"], "CR": ["costa rica"],
    "PA": ["panama"], "SV": ["el salvador"], "HN": ["honduras"], "JM": ["jamaica"],
}
COUNTRY_NAMES["ID"] += ["indonesie", "indonesië"]          # Dutch spellings seen in client mail
COUNTRY_NAMES["SA"] += ["saudi arabia", "saoedi-arabië"]
_ALIASES = {"UK": "GB", "ANZ": None}
# codes RFQs use on their own for a market; every other code must be written as a name
BARE_CODES = {"US", "GB", "DE", "FR", "JP", "KR", "BR", "CN", "MX", "SG", "AU", "NZ", "CA", "ES", "ZA", "HK", "TW",
              "AE", "SA", "MY", "PH", "TH", "VN", "NL", "PL", "TR", "AR", "CL", "NG", "KE", "EG", "IE", "QA", "KW"}


def _nums(text: str) -> set:
    return {float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def _in_text(value, nums: set) -> bool:
    vals = value if isinstance(value, (list, tuple)) else [value]
    return all(v is None or float(v) in nums for v in vals)


def countries_named(text: str) -> set:
    low = f" {text.lower()} "
    found = set()
    for code, names in COUNTRY_NAMES.items():
        if any(re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", low) for n in names):
            found.add(code)
        if code in BARE_CODES and re.search(rf"(?<![A-Za-z]){code}(?![A-Za-z])", text):
            found.add(code)   # other 2-letter codes are also words/abbreviations (IR, CR, PR, HR, NO...): name only
    if re.search(r"(?<![A-Za-z])UK(?![A-Za-z])", text):
        found.add("GB")
    if re.search(r"(?<![A-Za-z])IN(?![A-Za-z])", text):
        found.add("IN")
    return found


def check(extraction: Dict[str, Any], source_text: str) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = extraction.get("line_items") or []
    nums, problems = _nums(source_text), []
    named = countries_named(source_text)
    if not any(i.get("country") and i.get("n") and i.get("loi_minutes") for i in items):
        problems.append("required: no line item has country, N and LOI")
    got_countries = set()
    for k, i in enumerate(items, 1):
        c = (i.get("country") or "").strip().upper()
        c = _ALIASES.get(c, c) or ""
        loi, ir, n = i.get("loi_minutes"), i.get("ir_percent"), i.get("n")
        if c:
            got_countries.add(c)
            if not re.fullmatch(r"[A-Z]{2}", c):
                problems.append(f"line {k}: country {c!r} is not an ISO-2 code")
            elif c not in named:
                problems.append(f"line {k}: country {c} not named in the mail")
        if loi is not None and not (1 <= float(loi) <= 120):
            problems.append(f"line {k}: LOI {loi} out of range")
        if ir is not None and not (0.1 <= float(ir) <= 100):
            problems.append(f"line {k}: IR {ir} out of range")
        if n is not None and not (1 <= float(n) <= 100000):
            problems.append(f"line {k}: N {n} out of range")
        for name, v in (("LOI", loi), ("IR", ir), ("N", n)):
            if v is not None and not _in_text(v, nums):
                problems.append(f"line {k}: {name} {v} not found in the mail")
    missing = sorted(named - got_countries)
    if missing:
        problems.append(f"coverage: mail names {','.join(missing)} but no line item has it")
    return {"pass": not problems, "problems": problems, "countries_named": sorted(named)}
