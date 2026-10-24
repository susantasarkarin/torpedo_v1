"""CPI pricing from the live Cint rate card (CRM plan 3.5).

Pure functions, no I/O: callers pass the rate-card rows and the config. The
config values below are the owner's defaults (2026-10-24); in Phase 3 they are
read from the config collection, and these constants are only the fallback.

Row shape (one live Cint survey):
    {"country": "IN", "loi": 15, "ir": 25.0, "cpi": 1.19 (USD),
     "completes": 7022, "activated_at": datetime | None, "updated_at": datetime}
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULTS: Dict[str, Any] = {
    "markup": {"SFW": 1.5, "COGENTIX": 1.6, "BIM": 1.6},   # x Cint weighted median
    "margin_floor": 0.30,                                  # below -> Review Queue
    "min_rows": 5,                                         # widen bands one step if fewer
    "completes_window_days": 90,                           # weight = completes in this window
    "recency_half_life_days": 30,                          # weight for the recency option
    "ir_bands": [0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 101],   # same edges as routers/cint.py
    "loi_bands": [0, 5, 10, 15, 20, 30, 9999],
}


def band_index(value: float, edges: Sequence[float]) -> int:
    """Index of the half-open band [edges[i], edges[i+1]) holding value."""
    for i in range(len(edges) - 1):
        if edges[i] <= value < edges[i + 1]:
            return i
    return len(edges) - 2


def select_rows(rows: List[Dict[str, Any]], *, country: str, loi: float, ir: float,
                cfg: Dict[str, Any] = DEFAULTS) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Exact country, nearest LOI and IR band; widen both by one band at a time
    until at least min_rows rows match (max 3 steps). Returns (rows, trace)."""
    li, ii = band_index(loi, cfg["loi_bands"]), band_index(ir, cfg["ir_bands"])
    same_country = [r for r in rows if (r.get("country") or "").upper() == country.upper()]
    for widen in range(0, 4):
        lo_l, hi_l = max(0, li - widen), min(len(cfg["loi_bands"]) - 2, li + widen)
        lo_i, hi_i = max(0, ii - widen), min(len(cfg["ir_bands"]) - 2, ii + widen)
        picked = [r for r in same_country
                  if lo_l <= band_index(r["loi"], cfg["loi_bands"]) <= hi_l
                  and lo_i <= band_index(r["ir"], cfg["ir_bands"]) <= hi_i]
        if len(picked) >= cfg["min_rows"]:
            break
    trace = {"country": country.upper(), "widened_steps": widen,
             "loi_range": [cfg["loi_bands"][lo_l], cfg["loi_bands"][hi_l + 1]],
             "ir_range": [cfg["ir_bands"][lo_i], cfg["ir_bands"][hi_i + 1]],
             "rows_in_country": len(same_country), "rows_used": len(picked),
             "enough_rows": len(picked) >= cfg["min_rows"]}
    return picked, trace


def weight_completes(rows, now: datetime, cfg=DEFAULTS):
    """Option A: completes in the recent window. Only surveys activated inside the
    window count (their completes all fall inside it); older or undated rows are dropped."""
    since = now - timedelta(days=cfg["completes_window_days"])
    out = [(r, float(r.get("completes") or 0)) for r in rows
           if isinstance(r.get("activated_at"), datetime) and r["activated_at"] >= since]
    return [(r, w) for r, w in out if w > 0]


def weight_recency(rows, now: datetime, cfg=DEFAULTS):
    """Option B: recency. w = 0.5 ** (age_days / half_life), age from activation
    (else creation/last update). Rows older than the completes window are dropped too."""
    since = now - timedelta(days=cfg["completes_window_days"])
    out = []
    for r in rows:
        t = r.get("activated_at") or r.get("created_at") or r.get("updated_at")
        if not isinstance(t, datetime) or t < since:
            continue
        age = max(0.0, (now - t).total_seconds() / 86400)
        out.append((r, 0.5 ** (age / cfg["recency_half_life_days"])))
    return out


def weighted_median(weighted: List[Tuple[Dict[str, Any], float]]) -> Optional[float]:
    """Sort by CPI; the first CPI where cumulative weight >= 50% of total weight."""
    pts = sorted(((float(r["cpi"]), w) for r, w in weighted if w > 0), key=lambda x: x[0])
    total = sum(w for _, w in pts)
    if not pts or total <= 0:
        return None
    acc = 0.0
    for cpi, w in pts:
        acc += w
        if acc >= 0.5 * total:
            return cpi
    return pts[-1][0]


def price_line(rows, *, bu: str, country: str, loi: float, ir: float, now: datetime,
               weighting: str = "completes", client_markup: Optional[float] = None,
               vendor_cost: Optional[float] = None, cfg: Dict[str, Any] = DEFAULTS) -> Dict[str, Any]:
    """Full breakdown for one RFQ line (3.5 steps 2–7). review=True means a
    person must price or approve it; nothing is sent on review."""
    picked, trace = select_rows(rows, country=country, loi=loi, ir=ir, cfg=cfg)
    weighted = (weight_completes if weighting == "completes" else weight_recency)(picked, now, cfg)
    median = weighted_median(weighted)
    markup = client_markup or cfg["markup"][bu]
    out = {"weighting": weighting, **trace, "rows_weighted": len(weighted),
           "weighted_median_usd": median, "markup": markup, "review_reasons": []}
    if median is None or not trace["enough_rows"]:
        out["review_reasons"].append("not enough live rate-card rows for this spec")
        out["client_cpi_usd"] = None
    else:
        out["client_cpi_usd"] = round(median * markup, 2)
        cost = vendor_cost if vendor_cost is not None else median
        margin = 1 - cost / out["client_cpi_usd"]
        out["margin"] = round(margin, 3)
        if margin < cfg["margin_floor"]:
            out["review_reasons"].append(f"margin {margin:.0%} below floor {cfg['margin_floor']:.0%}")
    out["review"] = bool(out["review_reasons"])
    return out
