"""Bank, GST and TDS reconciliation (CRM plan 3.9 steps 11-16). Pure.

Bank statements are parsed from CSV/Excel rows into
{date, amount (+ in / - out), reference, narration}; PDFs and bank APIs feed
the same shape. Matching proposes; anything not certain goes to the Review
Queue with the suggestions.
"""
import csv
import io
import itertools
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y", "%d/%m/%y")


def _date(s: str) -> Optional[date]:
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), f).date()
        except (ValueError, AttributeError):
            continue
    return None


def _num(s) -> float:
    s = str(s or "").replace(",", "").strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def parse_statement_csv(text: str) -> List[Dict[str, Any]]:
    """Generic bank CSV: finds date / narration / reference / debit / credit (or
    amount) columns by header name."""
    rows = list(csv.reader(io.StringIO(text)))
    head_i = next((i for i, r in enumerate(rows) if any("date" in c.lower() for c in r)), None)
    if head_i is None:
        return []
    head = [c.strip().lower() for c in rows[head_i]]

    def col(*names):
        return next((i for i, h in enumerate(head) if any(n in h for n in names)), None)
    ci = {"date": col("txn date", "transaction date", "value date", "date"), "narr": col("narration", "description", "particulars"),
          "ref": col("ref", "cheque", "utr"), "dr": col("withdrawal", "debit"), "cr": col("deposit", "credit"),
          "amt": col("amount")}
    out = []
    for r in rows[head_i + 1:]:
        if ci["date"] is None or ci["date"] >= len(r):
            continue
        d = _date(r[ci["date"]])
        if not d:
            continue
        if ci["cr"] is not None or ci["dr"] is not None:
            amt = _num(r[ci["cr"]] if ci["cr"] is not None and ci["cr"] < len(r) else 0) - \
                  _num(r[ci["dr"]] if ci["dr"] is not None and ci["dr"] < len(r) else 0)
        else:
            amt = _num(r[ci["amt"]]) if ci["amt"] is not None else 0
        if not amt:
            continue
        out.append({"date": d, "amount": round(amt, 2),
                    "reference": r[ci["ref"]].strip() if ci["ref"] is not None and ci["ref"] < len(r) else "",
                    "narration": r[ci["narr"]].strip() if ci["narr"] is not None and ci["narr"] < len(r) else ""})
    return out


def _party_hit(line: Dict[str, Any], name: str) -> bool:
    words = [w for w in re.split(r"\W+", (name or "").lower()) if len(w) > 3 and w not in {"private", "limited", "research", "services"}]
    text = (line.get("narration", "") + " " + line.get("reference", "")).lower()
    return any(w in text for w in words)


def match_receipt(line: Dict[str, Any], open_invoices: List[Dict[str, Any]], *, tds_rates=(0.02, 0.10),
                  charge_tolerance: float = 500.0, window_days: int = 120, max_bundle: int = 4) -> Dict[str, Any]:
    """One bank credit against open invoices (balance_due in INR): exact, net of
    client TDS, net of small bank charges, or a bundle of a client's invoices.
    'auto' only when exactly one candidate; otherwise suggestions for review."""
    amt = float(line["amount"])
    cands = [i for i in open_invoices if isinstance(i.get("date"), date)
             and timedelta(0) <= (line["date"] - i["date"]) <= timedelta(days=window_days)]
    found = []
    for inv in cands:
        bal, ref_hit = float(inv["balance_due"]), inv["number"].lower() in (line.get("reference", "") + line.get("narration", "")).lower()
        party = _party_hit(line, inv.get("customer_name", ""))
        if abs(amt - bal) < 0.01:
            found.append({"invoices": [inv["number"]], "how": "exact", "tds": 0.0, "charges": 0.0, "score": 3 + ref_hit + party})
            continue
        taxable = float(inv.get("taxable") or bal)
        for r in tds_rates:
            if abs(amt - (bal - taxable * r)) < 1:
                found.append({"invoices": [inv["number"]], "how": f"net of {r:.0%} TDS", "tds": round(bal - amt, 2),
                              "charges": 0.0, "score": 2 + ref_hit + party})
        if 0 < bal - amt <= charge_tolerance and (ref_hit or party):
            found.append({"invoices": [inv["number"]], "how": "net of bank charges", "tds": 0.0,
                          "charges": round(bal - amt, 2), "score": 1 + ref_hit + party})
        if amt < bal - charge_tolerance and (ref_hit or party):
            found.append({"invoices": [inv["number"]], "how": "partial", "tds": 0.0, "charges": 0.0, "score": ref_hit + party})
    by_cust: Dict[str, List[Dict[str, Any]]] = {}
    for inv in cands:
        by_cust.setdefault(str(inv.get("customer_id")), []).append(inv)
    for invs in by_cust.values():
        for k in range(2, min(max_bundle, len(invs)) + 1):
            for combo in itertools.combinations(invs, k):
                if abs(sum(float(i["balance_due"]) for i in combo) - amt) < 0.01:
                    found.append({"invoices": [i["number"] for i in combo], "how": "bundled", "tds": 0.0, "charges": 0.0,
                                  "score": 2 + _party_hit(line, combo[0].get("customer_name", ""))})
    found.sort(key=lambda f: -f["score"])
    top = [f for f in found if f["score"] == found[0]["score"]] if found else []
    auto = len(top) == 1 and top[0]["how"] != "partial" and top[0]["score"] >= 3
    return {"auto": auto, "match": top[0] if auto else None, "suggestions": found[:5]}


def match_payment(line: Dict[str, Any], approved_bills: List[Dict[str, Any]]) -> Dict[str, Any]:
    amt = -float(line["amount"])
    hits = [b for b in approved_bills if abs(float(b["net_payable"]) - amt) < 0.01]
    named = [b for b in hits if _party_hit(line, b.get("vendor_name", ""))]
    pick = named if len(named) == 1 else hits if len(hits) == 1 else []
    return {"auto": bool(pick), "match": pick[0]["bill_no"] if pick else None, "suggestions": [b["bill_no"] for b in hits][:5]}


# ---------------------------------------------------------------- GST / TDS


def _key(gstin, number) -> tuple:
    return ((gstin or "").upper(), re.sub(r"\s+", "", str(number or "")).upper())


def gst_outward(invoices: List[Dict[str, Any]], gstr1: List[Dict[str, Any]], tol: float = 1.0) -> Dict[str, Any]:
    """Issued B2B invoices vs GSTR-1 rows {gstin, number, taxable, tax}."""
    filed = {_key(r["gstin"], r["number"]): r for r in gstr1}
    out = {"matched": [], "missing_in_gstr1": [], "value_mismatch": [], "extra_in_gstr1": []}
    seen = set()
    for inv in invoices:
        if not inv.get("client_gstin"):
            continue
        k = _key(inv["client_gstin"], inv["number"])
        r = filed.get(k)
        if not r:
            out["missing_in_gstr1"].append(inv["number"])
            continue
        seen.add(k)
        ok = abs(float(r["taxable"]) - float(inv["taxable"])) <= tol and abs(float(r["tax"]) - float(inv["tax"])) <= tol
        out["matched" if ok else "value_mismatch"].append(inv["number"])
    out["extra_in_gstr1"] = [r["number"] for k, r in filed.items() if k not in seen]
    return out


def gst_inward(bills: List[Dict[str, Any]], gstr2b: List[Dict[str, Any]], tol: float = 1.0) -> Dict[str, Any]:
    """Purchase bills vs GSTR-2B; a bill absent from 2B usually means the
    vendor has not filed -> input credit at risk."""
    filed = {_key(r["gstin"], r["number"]): r for r in gstr2b}
    out = {"matched": [], "vendor_not_filed": [], "value_mismatch": []}
    for b in bills:
        r = filed.get(_key(b.get("vendor_gstin"), b["bill_no"]))
        if not r:
            out["vendor_not_filed"].append(b["bill_no"])
        elif abs(float(r["tax"]) - float(b["input_gst"])) > tol:
            out["value_mismatch"].append(b["bill_no"])
        else:
            out["matched"].append(b["bill_no"])
    return out


def tds_receivable(receipts: List[Dict[str, Any]], form26as: List[Dict[str, Any]], tol: float = 1.0) -> Dict[str, Any]:
    """TDS clients deducted (per receipt) vs Form 26AS/AIS, by deductor TAN."""
    by_tan: Dict[str, float] = {}
    for r in form26as:
        by_tan[(r.get("tan") or "").upper()] = by_tan.get((r.get("tan") or "").upper(), 0.0) + float(r["tds"])
    ours: Dict[str, float] = {}
    for r in receipts:
        if r.get("tds"):
            ours[(r.get("client_tan") or "").upper()] = ours.get((r.get("client_tan") or "").upper(), 0.0) + float(r["tds"])
    rows = []
    for tan in sorted(set(by_tan) | set(ours)):
        a, b = round(ours.get(tan, 0.0), 2), round(by_tan.get(tan, 0.0), 2)
        rows.append({"tan": tan or "(no TAN)", "booked": a, "in_26as": b, "ok": abs(a - b) <= tol})
    return {"rows": rows, "all_ok": all(r["ok"] for r in rows)}


def tds_payable(deducted: float, deposited: float, returned: float, tol: float = 1.0) -> Dict[str, Any]:
    return {"deducted": deducted, "deposited": deposited, "in_returns": returned,
            "undeposited": round(deducted - deposited, 2), "unreturned": round(deposited - returned, 2),
            "ok": abs(deducted - deposited) <= tol and abs(deposited - returned) <= tol}


# ---------------------------------------------------------------- reports


def aging(items: List[Dict[str, Any]], today: date, buckets=(0, 30, 60, 90)) -> Dict[str, float]:
    labels = ["current"] + [f"{a + 1}-{b}" for a, b in zip(buckets, buckets[1:])] + [f"{buckets[-1]}+"]
    out = {l: 0.0 for l in labels}
    for i in items:
        days = (today - i["due_date"]).days
        bal = float(i.get("balance_due") or 0)
        if days <= 0:
            out["current"] += bal
            continue
        for a, b in zip(buckets, buckets[1:]):
            if a < days <= b:
                out[f"{a + 1}-{b}"] += bal
                break
        else:
            out[f"{buckets[-1]}+"] += bal
    return {k: round(v, 2) for k, v in out.items()}


def project_margin(revenue: float, vendor_cost: float, incentive_cost: float, other_direct: float = 0.0) -> Dict[str, Any]:
    m = revenue - vendor_cost - incentive_cost - other_direct
    return {"revenue": revenue, "direct_cost": round(vendor_cost + incentive_cost + other_direct, 2),
            "margin": round(m, 2), "margin_pct": round(m / revenue, 3) if revenue else None}
