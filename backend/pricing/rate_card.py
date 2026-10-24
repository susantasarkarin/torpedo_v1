"""Live Cint rate card rows for pricing (CRM plan 3.5 step 1).

Source: cint_research.cint_surveys with is_live and is_active true (the /cint
rate-card screen also counts rows that are no longer live). CPI is
revenue_per_interview.value in USD; weight fields are overall_completes and
activated_at.
"""
from typing import Any, Dict, List, Optional

# Numeric Cint/Lucid country-language ids, VERIFIED 2026-10-24 against survey
# names (e.g. id 8 -> 75 of 76 country-named surveys say GB/UK). Unverified
# ids are dropped rather than guessed.
VERIFIED_IDS = {9: "US", 5: "AU", 6: "CA", 8: "GB", 11: "DE", 10: "FR", 16: "BR"}


def country_of(cl) -> Optional[str]:
    if isinstance(cl, (int, float)) or (isinstance(cl, str) and cl.isdigit()):
        return VERIFIED_IDS.get(int(cl))
    if isinstance(cl, str) and "_" in cl:
        return cl.split("_")[-1].upper()
    return None


def to_row(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rpi = d.get("revenue_per_interview")
    cpi = float(rpi.get("value") or 0) if isinstance(rpi, dict) else float(rpi or 0)
    loi = d.get("length_of_interview") or d.get("bid_length_of_interview")
    ir = d.get("bid_incidence")
    country = country_of(d.get("country_language"))
    if cpi <= 0 or loi is None or ir is None or not country:
        return None
    return {"country": country, "loi": float(loi), "ir": float(ir), "cpi": cpi,
            "completes": d.get("overall_completes") or 0, "activated_at": d.get("activated_at"),
            "created_at": d.get("created_at"), "updated_at": d.get("last_updated_at")}


def load_rows(cint_db) -> List[Dict[str, Any]]:
    out = []
    for d in cint_db["cint_surveys"].find(
            {"is_live": True, "is_active": True},
            {"country_language": 1, "length_of_interview": 1, "bid_length_of_interview": 1, "bid_incidence": 1,
             "revenue_per_interview": 1, "overall_completes": 1, "activated_at": 1, "created_at": 1,
             "last_updated_at": 1}):
        r = to_row(d)
        if r:
            out.append(r)
    return out
