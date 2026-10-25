"""Rules tier for RFQ extraction (owner, 2026-10-25): the cheapest rung of the ladder.

RFQ mails state the spec in a few recurring forms ("n=500", "500 completes",
"LOI 15 min", "IR 25%", "Incidence: 30%", country names). This reads those,
and leaves a field empty when the mail is ambiguous (two different sample
sizes with no per-country mapping, two LOIs...) instead of guessing -- the
next rung (Qwen, then Haiku/Sonnet) fills what is left. The result goes
through the same code checks as any model answer.
"""
import re
from typing import Any, Dict, List, Optional

from rfq import extraction_checks

_NUM = r"(\d{1,3}(?:,\d{3})+|\d{2,6})"
N_PATTERNS = [
    re.compile(r"\bn\s*[=:\-]\s*" + _NUM + r"\b", re.I),
    re.compile(r"\b" + _NUM + r"\s*(?:n\b|completes?\b|respondents?\b|interviews?\b|samples?\b|surveys?\b)", re.I),
    re.compile(r"\bsample(?:\s*size)?\s*(?:of|[:=\-]|is)?\s*" + _NUM + r"\b", re.I),
    re.compile(r"\b(\d{2,6})n\b", re.I),
]
LOI_PATTERNS = [
    re.compile(r"\bLOI\s*(?:of|[:=\-]|is|~)?\s*(\d{1,3})(?:\s*(?:-|to)\s*\d{1,3})?\s*(?:min(?:ute)?s?|mins?)?\b", re.I),
    re.compile(r"\b(\d{1,3})\s*(?:min(?:ute)?s?|mins?)\b\s*(?:LOI|survey|questionnaire|interview|online)", re.I),
    re.compile(r"\blength(?:\s*of\s*interview)?\s*(?:of|[:=\-]|is)?\s*(\d{1,3})\s*(?:min(?:ute)?s?|mins?)\b", re.I),
]
IR_PATTERNS = [
    re.compile(r"\bIR\s*(?:of|[:=\-]|is|~)?\s*(\d{1,3}(?:\.\d+)?)\s*%?", re.I),
    re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*%\s*(?:IR|incidence)\b", re.I),
    re.compile(r"\bincidence(?:\s*rate)?\s*(?:of|[:=\-]|is|~)?\s*(\d{1,3}(?:\.\d+)?)\s*%?", re.I),
]
METHODS = [("CAWI", r"\b(cawi|online survey|online|web survey)\b"), ("CATI", r"\b(cati|telephonic|phone survey)\b"),
           ("CAPI", r"\b(capi|f2f|face[\s-]to[\s-]face)\b"), ("QUAL", r"\b(idi|idis|fgd|focus group|in[\s-]depth interview)")]


def _ints(patterns, text) -> List[float]:
    out = []
    for p in patterns:
        for m in p.finditer(text):
            try:
                out.append(float(m.group(1).replace(",", "")))
            except (ValueError, IndexError):
                pass
    return out


def _one(values: List[float]) -> Optional[float]:
    vals = sorted(set(values))
    return vals[0] if len(vals) == 1 else None


def per_country_n(text: str, countries: List[str]) -> Dict[str, int]:
    """'India - 500', 'US: 300n', 'UK (n=200)' -> {IN: 500, US: 300, GB: 200}."""
    names = {code: list(extraction_checks.COUNTRY_NAMES.get(code, [])) + [code] for code in countries}
    out = {}
    for code, labels in names.items():
        for lab in sorted(labels, key=len, reverse=True):
            m = re.search(r"\b" + re.escape(lab) + r"\b[^\n\d]{0,18}?(?:n\s*[=:]?\s*)?" + _NUM + r"\b(?!\s*%|\s*min)", text, re.I)
            if m:
                v = int(m.group(1).replace(",", ""))
                if 10 <= v <= 100000:
                    out[code] = v
                    break
    return out


def extract(text: str) -> Optional[Dict[str, Any]]:
    """-> {"line_items": [...]} with what the rules are sure of, or None if nothing usable."""
    t = text or ""
    countries = sorted(extraction_checks.countries_named(t))
    loi = _one([v for v in _ints(LOI_PATTERNS, t) if 1 <= v <= 120])
    ir = _one([v for v in _ints(IR_PATTERNS, t) if 0.1 <= v <= 100])
    method = next((m for m, rx in METHODS if re.search(rx, t, re.I)), None)
    by_country = per_country_n(t, countries) if len(countries) > 1 else {}
    n_all = _one([v for v in _ints(N_PATTERNS, t) if 10 <= v <= 100000])
    if not countries and n_all is None and loi is None:
        return None
    items = []
    for c in countries or [None]:
        n = by_country.get(c) if by_country else n_all
        items.append({"country": c, "n": int(n) if n else None, "loi_minutes": int(loi) if loi else None,
                      "ir_percent": ir, "methodology": method, "target": None})
    return {"line_items": items, "field_dates": None, "deliverables": None, "client_reference": None,
            "special_requirements": None}


def complete(data: Optional[Dict[str, Any]]) -> bool:
    """Rules are only accepted on their own when every line has country, N and LOI."""
    items = (data or {}).get("line_items") or []
    return bool(items) and all(i.get("country") and i.get("n") and i.get("loi_minutes") for i in items)
