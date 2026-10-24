"""Vendor engagement (CRM plan 3.7a steps 2-10). Pure functions.

Vendor master = finance_db.vendors (name, GSTIN/PAN, payment terms already
there); the sourcing profile lives under `procurement`: countries, panel_size,
quality_score, rate_card, nda_signed, msa_signed, redirect_integration. Bids
are crm_db.vendor_bids, one per (rfq, line, vendor), ref_id VB-<rfq>-<n>.
The client's name never appears in anything sent to a vendor.
"""
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    "mode": "shadow",                  # shadow: plan only; live (owner): send through the gate
    "shortlist_size": 3,
    "min_quality_score": 60,           # 0-100
    "follow_up_after_working_hours": 4,
    "bid_deadline_working_hours": 24,
    "working_hours_ist": [10, 18],
    "invoice_tolerance_pct": 0.01,
}

BID_SCHEMA = {
    "type": "object", "required": ["cpi"],
    "properties": {"cpi": {"type": ["number", "null"]}, "currency": {"type": ["string", "null"]},
                   "feasible_n": {"type": ["integer", "null"]}, "timeline_days": {"type": ["number", "null"]},
                   "conditions": {"type": ["string", "null"]}, "declined": {"type": ["boolean", "null"]}},
}
BID_SYSTEM = ("You read a sample vendor's reply to our bid request. Return JSON only: {\"cpi\": number or null, "
              "\"currency\": ISO code or null, \"feasible_n\": integer or null, \"timeline_days\": number or null, "
              "\"conditions\": string or null, \"declined\": true if they cannot do it}. Use null when not stated.")


def ref_id(rfq_id: str, n: int) -> str:
    return f"VB-{str(rfq_id)[-6:]}-{n}"


# ---------------------------------------------------------------- shortlist + request


def shortlist(vendors: List[Dict[str, Any]], country: str, cfg: Dict[str, Any] = DEFAULTS) -> List[Dict[str, Any]]:
    c = (country or "").upper()
    ok = [v for v in vendors if v.get("status", "active") == "active"
          and c in [x.upper() for x in ((v.get("procurement") or {}).get("countries") or [])]
          and float((v.get("procurement") or {}).get("quality_score") or 0) >= cfg["min_quality_score"]]
    ok.sort(key=lambda v: (-float(v["procurement"].get("quality_score") or 0), v.get("name") or ""))
    return ok[: int(cfg["shortlist_size"])]


def bid_request(line: Dict[str, Any], shortfall: int, ref: str, client_name: str = "") -> Dict[str, str]:
    spec = [f"Country: {line.get('country')}", f"Sample needed: {shortfall}",
            f"LOI: {line.get('loi_minutes')} min", f"IR: {line.get('ir_percent')}%"]
    if line.get("target"):
        spec.append(f"Target: {line['target']}")
    body = ("Could you share your CPI and feasibility for the following?\n" + "\n".join(spec) +
            "\nPlease keep the reference in the subject when replying.")
    if client_name:
        for word in {client_name, *[w for w in re.split(r"\W+", client_name) if len(w) > 3]}:
            body = re.sub(re.escape(word), "[client]", body, flags=re.I)
    return {"subject": f"[{ref}] Bid request: {line.get('country')} n={shortfall}", "body": body}


def add_working_hours(t: datetime, hours: float, wh=(10, 18)) -> datetime:
    """t and result in IST; weekends skipped."""
    left = hours * 60
    cur = t
    while left > 0:
        if cur.weekday() >= 5 or cur.hour >= wh[1]:
            cur = (cur + timedelta(days=1)).replace(hour=wh[0], minute=0, second=0, microsecond=0)
            continue
        if cur.hour < wh[0]:
            cur = cur.replace(hour=wh[0], minute=0, second=0, microsecond=0)
        end = cur.replace(hour=wh[1], minute=0, second=0, microsecond=0)
        step = min(left, (end - cur).total_seconds() / 60)
        cur += timedelta(minutes=step)
        left -= step
    return cur


def bid_due_action(bid: Dict[str, Any], now_ist: datetime, cfg: Dict[str, Any] = DEFAULTS) -> Optional[str]:
    if bid.get("status") != "requested" or not isinstance(bid.get("requested_at_ist"), datetime):
        return None
    wh = tuple(cfg["working_hours_ist"])
    if now_ist >= add_working_hours(bid["requested_at_ist"], cfg["bid_deadline_working_hours"], wh):
        return "no_bid"
    if not bid.get("followed_up_at") and now_ist >= add_working_hours(bid["requested_at_ist"],
                                                                      cfg["follow_up_after_working_hours"], wh):
        return "follow_up"
    return None


# ---------------------------------------------------------------- parse + select


def bid_code_check(data: Any, clean_text: str) -> List[str]:
    if not isinstance(data, dict):
        return ["output is not an object"]
    nums = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", (clean_text or "").replace(",", ""))}
    out = []
    for f in ("cpi", "feasible_n"):
        v = data.get(f)
        if v is not None and float(v) not in nums:
            out.append(f"{f} {v} not found in the mail")
    if data.get("cpi") is not None and not (0 < float(data["cpi"]) < 500):
        out.append(f"cpi {data['cpi']} out of range")
    return out


def auto_select(bids: List[Dict[str, Any]], shortfall: int, *, client_cpi: float, own_cost: Optional[float],
                own_n: int, margin_floor: float, min_quality: float) -> Dict[str, Any]:
    """Cheapest set covering the shortfall; ties -> higher score; the blend
    with our own sample must keep margin >= floor, else a person decides."""
    usable = [b for b in bids if b.get("status") == "received" and b.get("cpi") and b.get("feasible_n")
              and float(b.get("quality_score") or 0) >= min_quality]
    usable.sort(key=lambda b: (float(b["cpi"]), -float(b.get("quality_score") or 0)))
    picked, need, cost = [], shortfall, 0.0
    for b in usable:
        if need <= 0:
            break
        take = min(int(b["feasible_n"]), need)
        picked.append({"bid_id": str(b["_id"]), "vendor_id": b.get("vendor_id"), "n": take, "cpi": float(b["cpi"])})
        cost += take * float(b["cpi"])
        need -= take
    if need > 0:
        return {"ok": False, "reason": f"bids cover {shortfall - need} of {shortfall}", "picked": picked}
    total_n = own_n + shortfall
    blended = (cost + own_n * float(own_cost or 0)) / total_n if total_n else 0
    margin = 1 - blended / client_cpi if client_cpi else -1
    if margin < margin_floor:
        return {"ok": False, "reason": f"blended margin {margin:.0%} below floor {margin_floor:.0%}",
                "picked": picked, "margin": round(margin, 3)}
    return {"ok": True, "picked": picked, "blended_cost": round(blended, 3), "margin": round(margin, 3)}


# ---------------------------------------------------------------- invoice + scorecard


def invoice_match(po: Dict[str, Any], accepted_n: int, invoice: Dict[str, Any],
                  tolerance: float = DEFAULTS["invoice_tolerance_pct"]) -> Dict[str, Any]:
    expected = round(accepted_n * float(po["cpi"]), 2)
    billed_n, billed = invoice.get("n"), round(float(invoice.get("amount") or 0), 2)
    diffs = []
    if billed_n is not None and int(billed_n) != int(accepted_n):
        diffs.append(f"completes billed {billed_n} vs accepted {accepted_n}")
    if expected and abs(billed - expected) / expected > tolerance:
        diffs.append(f"amount {billed} vs expected {expected} ({accepted_n} x {po['cpi']})")
    if (invoice.get("currency") or po.get("currency")) != po.get("currency"):
        diffs.append(f"currency {invoice.get('currency')} vs PO {po.get('currency')}")
    return {"match": not diffs, "expected": expected, "billed": billed, "differences": diffs}


def scorecard(prev: Dict[str, Any], project: Dict[str, Any]) -> Dict[str, Any]:
    """Running means over projects: response hours, delivery vs commitment,
    rejection rate, invoice accuracy -> quality_score 0-100."""
    n = int(prev.get("projects") or 0)

    def mean(k, v):
        return v if n == 0 or prev.get(k) is None else (prev[k] * n + v) / (n + 1)
    s = {"projects": n + 1}
    s["response_hours"] = mean("response_hours", float(project.get("response_hours") or 0))
    committed = float(project.get("committed_n") or 0)
    s["delivery_ratio"] = mean("delivery_ratio", min(1.0, float(project.get("delivered_n") or 0) / committed) if committed else 0)
    s["rejection_rate"] = mean("rejection_rate", float(project.get("rejection_rate") or 0))
    s["invoice_accuracy"] = mean("invoice_accuracy", 1.0 if project.get("invoice_matched") else 0.0)
    resp = max(0.0, 1 - s["response_hours"] / 24)
    s["quality_score"] = round(100 * (0.2 * resp + 0.4 * s["delivery_ratio"] + 0.3 * (1 - s["rejection_rate"])
                                      + 0.1 * s["invoice_accuracy"]), 1)
    return s


# ---------------------------------------------------------------- award + daily counts


def vendor_entry_link(base_url: str, survey_no: str, vendor_id: str, country: str) -> str:
    """The /takesurvey vendor entry (routers/traffic.py); the vendor fills rid."""
    return (f"{base_url.rstrip('/')}/takesurvey?api=false&pid={survey_no}&vid={vendor_id}"
            f"&cc={(country or '').upper()}&rid=[RID]")


def award_plan(selection: Dict[str, Any], all_bids: List[Dict[str, Any]], *, base_url: str, survey_no: str,
               country: str, vendor_redirects: Dict[str, str]) -> Dict[str, Any]:
    """On client confirmation: PO + entry link + our vendor redirect set per
    awarded vendor; a not-awarded note to every other bidder that replied."""
    won = {p["bid_id"] for p in selection.get("picked") or []}
    awards = [{"bid_id": p["bid_id"], "vendor_id": p["vendor_id"], "po": {"n": p["n"], "cpi": p["cpi"]},
               "entry_link": vendor_entry_link(base_url, survey_no, p["vendor_id"], country),
               "redirects": vendor_redirects} for p in selection.get("picked") or []]
    regrets = [str(b["_id"]) for b in all_bids if str(b["_id"]) not in won and b.get("status") == "received"]
    return {"awards": awards, "regrets": regrets}


def daily_vendor_counts(traffic: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Per vendor: complete / terminate / quotafull / security counts for the day."""
    out: Dict[str, Dict[str, int]] = {}
    for t in traffic:
        v = str(t.get("vendorId") or t.get("vendor_id") or "")
        if v:
            k = (t.get("status") or "other").lower()
            out.setdefault(v, {}).setdefault(k, 0)
            out[v][k] += 1
    return out
