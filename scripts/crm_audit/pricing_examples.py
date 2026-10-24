"""5 worked pricing examples from real quoted RFQs vs the engine (A7). Read-only.

Rate card = LIVE Cint rows only: cint_research.cint_surveys with is_live and
is_active true (the /cint rate-card endpoint today uses every row, live or not).
CPI = revenue_per_interview.value (USD). Run from backend/.
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.getcwd())
from pymongo import MongoClient  # noqa: E402

from pricing import engine  # noqa: E402

# Specs read from each RFQ's source mail (crm_db.opportunities.metadata.rfq.source_email_id).
EXAMPLES = [
    {"opp": "6adb49f57e9ca4b06a1e8c37", "client": "Hansa Research Group", "date": "2026-10-23",
     "spec": "Premium SUV intenders/buyers, M/F 70:30, 35-50", "country": "IN", "loi": 15, "ir": 25, "n": 1600,
     "quoted": 240, "cur": "INR", "b2b": False},
    {"opp": "6acf626c39e86ad66ff1f143", "client": "Hansa Research Group", "date": "2026-10-14",
     "spec": "Corporate outing decision makers (B2B)", "country": "IN", "loi": 20, "ir": 25, "n": 410,
     "quoted": 650, "cur": "INR", "b2b": True},
    {"opp": "6aba79a991f85007c9b90cbd", "client": "Rakuten Insight", "date": "2026-08-12",
     "spec": "C-suite / owners, SME:MNC 80:20 (B2B)", "country": "SG", "loi": 10, "ir": 40, "n": None,
     "quoted": 22.0, "cur": "USD", "b2b": True},
    {"opp": "6aba79a891f85007c9b90b7e", "client": "Neoteric Research", "date": "2026-04-23",
     "spec": "Gen pop 18-45 (client budget $1)", "country": "IN", "loi": 9, "ir": 90, "n": 600,
     "quoted": 1.5, "cur": "USD", "b2b": False},
    {"opp": "6aba79a591f85007c9b908a4", "client": "Acesdigi MR", "date": "2025-06-25",
     "spec": "Manager+ in fintech/banking/retail etc. (B2B, client budget $11)", "country": "US", "loi": 12, "ir": 65,
     "n": 100, "quoted": 11.0, "cur": "USD", "b2b": True},
]


# Numeric Cint/Lucid country-language ids, VERIFIED 2026-10-24 against survey
# names (e.g. id 8 -> 75 of 76 country-named surveys say GB/UK). The map in
# routers/cint.py is wrong for 8/10/11/16 (it says IE/ES/IT/CO). Unverified
# ids are dropped rather than guessed.
VERIFIED_IDS = {9: "US", 5: "AU", 6: "CA", 8: "GB", 11: "DE", 10: "FR", 16: "BR"}


def country_of(cl):
    if isinstance(cl, (int, float)) or (isinstance(cl, str) and cl.isdigit()):
        return VERIFIED_IDS.get(int(cl))
    if isinstance(cl, str) and "_" in cl:
        return cl.split("_")[-1].upper()
    return None


def load_rows(c):
    out = []
    for d in c.cint_research.cint_surveys.find(
            {"is_live": True, "is_active": True},
            {"country_language": 1, "length_of_interview": 1, "bid_length_of_interview": 1, "bid_incidence": 1,
             "revenue_per_interview": 1, "overall_completes": 1, "activated_at": 1, "created_at": 1,
             "last_updated_at": 1}):
        rpi = d.get("revenue_per_interview")
        cpi = float(rpi.get("value") or 0) if isinstance(rpi, dict) else float(rpi or 0)
        loi = d.get("length_of_interview") or d.get("bid_length_of_interview")
        ir = d.get("bid_incidence")
        country = country_of(d.get("country_language"))
        if cpi <= 0 or loi is None or ir is None or not country:
            continue
        out.append({"country": country, "loi": float(loi), "ir": float(ir), "cpi": cpi,
                    "completes": d.get("overall_completes") or 0, "activated_at": d.get("activated_at"),
                    "created_at": d.get("created_at"), "updated_at": d.get("last_updated_at")})
    return out


def main():
    c = MongoClient(os.environ["MONGO_URI"])
    now = datetime.utcnow()
    rows = load_rows(c)
    fx = c.finance_db.invoice_fx.find_one({"currency": "USD"}, sort=[("rate_date", -1)])
    usd_inr = float(fx["rate"]) if fx else None
    from collections import Counter
    res = {"generated_at": now.isoformat(timespec="seconds"), "live_rows": len(rows),
           "live_rows_by_country": dict(Counter(r["country"] for r in rows).most_common(12)),
           "rows_with_activated_at_90d": sum(1 for r in rows if r["activated_at"] and (now - r["activated_at"]).days <= 90),
           "usd_inr": usd_inr, "usd_inr_source": (f"finance_db.invoice_fx {fx.get('rate_date')} ({fx.get('source')})" if fx else None),
           "examples": []}
    for ex in EXAMPLES:
        both = {w: engine.price_line(rows, bu="SFW", country=ex["country"], loi=ex["loi"], ir=ex["ir"], now=now, weighting=w)
                for w in ("completes", "recency")}
        quoted_usd = ex["quoted"] if ex["cur"] == "USD" else (ex["quoted"] / usd_inr if usd_inr else None)
        res["examples"].append({**ex, "quoted_usd": round(quoted_usd, 2) if quoted_usd else None, "engine": both})
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
