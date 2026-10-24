"""RFQ handling, steps 2-7 of CRM plan 3.4, with pricing from 3.5.

extract (Qwen via the gateway, code-checked) -> client defaults -> missing
critical fields -> price each CAWI line from the live Cint rate card.

Pure apart from the injected `run` (qwen_gateway.run). Nothing is sent from
here: a missing-info reply and every quote are Review Queue drafts until the
owner approves the client-facing copy and switches the module live.
"""
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from pricing import engine
from rfq import extraction_checks

SYSTEM = (
    "You extract the specification of a market-research RFQ from an email. "
    "Return JSON only, no prose: {\"line_items\": [{\"country\": ISO-3166 alpha-2 code, \"n\": integer or null, "
    "\"loi_minutes\": number or null, \"ir_percent\": number or null, \"methodology\": string or null, "
    "\"target\": string or null}], \"field_dates\": string or null, \"deliverables\": string or null, "
    "\"client_reference\": string or null, \"special_requirements\": string or null}. "
    "One line item per country or cell. If the mail gives one sample size per market, put it on every line. "
    "Use null for anything the mail does not state. Do not guess."
)

_NUM = {"type": ["number", "null"]}
_STR = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object", "required": ["line_items"],
    "properties": {
        "line_items": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["country"],
            "properties": {"country": _STR, "n": _NUM, "loi_minutes": _NUM, "ir_percent": _NUM,
                           "methodology": _STR, "target": _STR}}},
        "field_dates": _STR, "deliverables": _STR, "client_reference": _STR, "special_requirements": _STR,
    },
}

FIELD_LABELS = {"n": "sample size (N)", "loi_minutes": "interview length (LOI)", "country": "country",
                "ir_percent": "incidence rate (IR)"}


def code_check(data: Any, clean_text: str) -> List[str]:
    """extraction_checks minus 'required': a missing field is the flow's job
    (client defaults, then a missing-info reply), not an extraction fault."""
    if not isinstance(data, dict):
        return ["output is not an object"]
    return [p for p in extraction_checks.check(data, clean_text)["problems"] if not p.startswith("required:")]


def client_defaults(account: Dict[str, Any], rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """First rule for this account: by account_id, else by name substring
    (case-insensitive). Rules come from crm_db.client_defaults, then config."""
    aid, name = str(account.get("_id") or ""), (account.get("name") or "").lower()
    for r in rules:
        if r.get("account_id") and str(r["account_id"]) == aid:
            return r.get("defaults") or {}
    for r in rules:
        m = (r.get("match") or "").lower()
        if m and m in name:
            return r.get("defaults") or {}
    return {}


def apply_defaults(items: List[Dict[str, Any]], defaults: Dict[str, Any],
                   default_methodology: str) -> List[Dict[str, Any]]:
    out = []
    for it in items:
        it, used = dict(it), []
        for f, v in {**{"methodology": default_methodology}, **defaults}.items():
            if it.get(f) in (None, "") and v not in (None, ""):
                it[f] = v
                used.append(f)
        if it.get("country"):
            it["country"] = str(it["country"]).strip().upper()
        it["defaulted"] = used
        out.append(it)
    return out


def missing_fields(items: List[Dict[str, Any]], critical: List[str]) -> List[Dict[str, Any]]:
    return [{"line": k, "field": f} for k, it in enumerate(items, 1) for f in critical if it.get(f) in (None, "")]


def missing_info_draft(missing: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> str:
    """Plain draft asking only for what is missing. Client-facing: reviewed
    before sending, wording replaced by the BU reply template once supplied."""
    by_line: Dict[int, List[str]] = {}
    for m in missing:
        by_line.setdefault(m["line"], []).append(FIELD_LABELS.get(m["field"], m["field"]))
    lines = []
    for k, fields in sorted(by_line.items()):
        c = items[k - 1].get("country") if k - 1 < len(items) else None
        label = f"{c}" if c and len(items) > 1 else ("" if len(items) == 1 else f"line {k}")
        lines.append(f"- {label + ': ' if label else ''}{', '.join(fields)}")
    return ("Thank you for the RFQ. To send you a cost, could you please confirm:\n" + "\n".join(lines))


def _history_problem(cpi: float, history: List[float], tolerance: float) -> Optional[str]:
    if not history:
        return None
    ref = sorted(history)[len(history) // 2]
    if ref > 0 and abs(cpi - ref) / ref > tolerance:
        return f"CPI {cpi} is {abs(cpi - ref) / ref:.0%} away from this client's recent median {ref}"
    return None


def price_items(items: List[Dict[str, Any]], rows: List[Dict[str, Any]], *, bu: Optional[str], now: datetime,
                cfg: Dict[str, Any], pricing_cfg: Dict[str, Any], client_markup: Optional[float] = None,
                history: Optional[Dict[str, List[float]]] = None) -> List[Dict[str, Any]]:
    """Per line: both weightings side by side; the configured one is the price."""
    history = history or {}
    bounds = cfg.get("cpi_bounds_usd") or {}
    out = []
    for k, it in enumerate(items, 1):
        line = {"line": k, "country": it.get("country"), "review_reasons": []}
        if (it.get("methodology") or "").upper() != "CAWI":
            line["review_reasons"].append(f"{it.get('methodology') or 'unknown'} is priced by a person")
        elif not bu or bu not in pricing_cfg["markup"]:
            line["review_reasons"].append("BU unknown: markup cannot be chosen")
        elif any(it.get(f) in (None, "") for f in ("country", "loi_minutes", "ir_percent")):
            line["review_reasons"].append("country, LOI or IR missing")
        else:
            both = {w: engine.price_line(rows, bu=bu, country=it["country"], loi=float(it["loi_minutes"]),
                                         ir=float(it["ir_percent"]), now=now, weighting=w,
                                         client_markup=client_markup, cfg=pricing_cfg)
                    for w in ("completes", "recency")}
            chosen = both[cfg.get("weighting", "completes")]
            line.update(breakdown=both, client_cpi_usd=chosen.get("client_cpi_usd"))
            line["review_reasons"] += chosen["review_reasons"]
            cpi = chosen.get("client_cpi_usd")
            if cpi is not None:
                if bounds.get("min") is not None and cpi < bounds["min"]:
                    line["review_reasons"].append(f"CPI {cpi} below bound {bounds['min']}")
                if bounds.get("max") is not None and cpi > bounds["max"]:
                    line["review_reasons"].append(f"CPI {cpi} above bound {bounds['max']}")
                hp = _history_problem(cpi, history.get(it["country"], []), float(cfg.get("client_history_tolerance", 0.4)))
                if hp:
                    line["review_reasons"].append(hp)
        line["review"] = bool(line["review_reasons"])
        out.append(line)
    return out


def process(opp: Dict[str, Any], text: str, *, account: Dict[str, Any], bu: Optional[str],
            rules: List[Dict[str, Any]], rows: List[Dict[str, Any]], cfg: Dict[str, Any],
            pricing_cfg: Dict[str, Any], run: Callable[..., Dict[str, Any]], now: datetime,
            client_markup: Optional[float] = None, history: Optional[Dict[str, List[float]]] = None) -> Dict[str, Any]:
    oid = str(opp["_id"])
    ext = run(task="rfq_extraction", system=SYSTEM, subject="", body=text, schema=SCHEMA, code_check=code_check,
              ref={"collection": "crm_db.opportunities", "id": oid}, bu=bu)
    d: Dict[str, Any] = {"opportunity_id": oid, "account_id": str(account.get("_id") or ""), "bu": bu,
                         "extraction_status": ext.get("status"), "extraction_job": ext.get("job_id"),
                         "extraction_problems": ext.get("problems") or [], "review_item": ext.get("review_item")}
    data = ext.get("data") if isinstance(ext.get("data"), dict) else None
    if ext.get("status") in ("failed", "deferred") or not data:
        d.update(status="extraction_failed" if ext.get("status") != "deferred" else "deferred")
        return d
    items = apply_defaults(data.get("line_items") or [], client_defaults(account, rules), cfg["default_methodology"])
    d.update(line_items=items, details={k: data.get(k) for k in ("field_dates", "deliverables", "client_reference",
                                                                   "special_requirements")})
    missing = missing_fields(items, cfg["critical_fields"])
    if missing:
        d.update(status="awaiting_info", missing=missing, missing_info_draft=missing_info_draft(missing, items))
        return d
    d["pricing"] = price_items(items, rows, bu=bu, now=now, cfg=cfg, pricing_cfg=pricing_cfg,
                               client_markup=client_markup, history=history)
    d["status"] = "priced_review" if any(p["review"] for p in d["pricing"]) or ext.get("status") == "review" else "priced"
    return d
