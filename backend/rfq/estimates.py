"""Every RFQ has an estimate; every change of scope or price is a new version (owner, 2026-10-26).

One estimate group per RFQ (finance_db.estimates, estimate_group_id = the
opportunity id). sync() takes the RFQ as it stands now -- the flow decision's
line items and prices when there is one, else the RFQ fields -- and compares it
with the group's latest version:
  no version yet          -> version 1
  scope changed           (countries, N, LOI, IR, methodology) -> version n+1
  price changed           (per-line CPI, or the quoted value / currency) -> version n+1
  same                    -> nothing
The earlier version is kept, with superseded_by / is_latest false; a draft one
reads "superseded", a sent or accepted one keeps its status (it was real).
Each version records what changed. Nothing is deleted.

Status of a new version follows the RFQ: open -> draft, won -> accepted,
closed / lost -> expired. All of it is internal: an estimate is never mailed here.
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

SCOPE = ("country", "n", "loi_minutes", "ir_percent", "methodology")
STATUS_BY_RFQ = {"open": "draft", "won": "accepted", "closed": "expired", "lost": "expired"}
VALID_DAYS = 30


def _num(v):
    try:
        return round(float(v), 2) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def snapshot(opp: Dict[str, Any], decision: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """{lines: [...scope + cpi], value, currency} -- what the estimate must say."""
    r = (opp.get("metadata") or {}).get("rfq") or {}
    prices = {p.get("country"): p.get("client_cpi_usd") for p in (decision or {}).get("pricing") or []}
    lines = []
    for it in (decision or {}).get("line_items") or []:
        ln = {k: it.get(k) for k in SCOPE}
        ln["n"], ln["loi_minutes"], ln["ir_percent"] = _num(ln["n"]), _num(ln["loi_minutes"]), _num(ln["ir_percent"])
        ln["cpi"] = _num(prices.get(it.get("country")))
        lines.append(ln)
    if not lines:
        lines = [{"country": r.get("country") or r.get("geography"), "n": _num(r.get("sample_size")),
                  "loi_minutes": _num(r.get("loi")), "ir_percent": _num(r.get("ir")),
                  "methodology": r.get("methodology"), "cpi": None}]
    for ln in lines:
        ln["country"] = (str(ln["country"]).strip() if ln.get("country") else None)
        ln["methodology"] = (str(ln["methodology"]).strip() if ln.get("methodology") else None)
    lines.sort(key=lambda x: (x["country"] or "", x["methodology"] or ""))
    value = _num(opp.get("amount")) or _num(r.get("quoted_value")) or _num(r.get("budget"))
    priced = sum((ln["cpi"] or 0) * (ln["n"] or 0) for ln in lines)
    return {"lines": lines, "value": round(priced, 2) if priced else value,
            "currency": ("USD" if priced else (opp.get("currency") or r.get("currency") or None))}


def fingerprint(s: Dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(s, sort_keys=True, default=str).encode()).hexdigest()[:16]


def diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, List[str]]:
    """What changed, in words: {"scope": [...], "price": [...]}."""
    out: Dict[str, List[str]] = {"scope": [], "price": []}
    ob = {ln.get("country"): ln for ln in old.get("lines") or []}
    nb = {ln.get("country"): ln for ln in new.get("lines") or []}
    for c in sorted(set(nb) - set(ob), key=str):
        out["scope"].append(f"{c or 'market'} added")
    for c in sorted(set(ob) - set(nb), key=str):
        out["scope"].append(f"{c or 'market'} removed")
    for c in sorted(set(ob) & set(nb), key=str):
        for k in SCOPE[1:]:
            if ob[c].get(k) != nb[c].get(k):
                out["scope"].append(f"{c or 'market'} {k}: {ob[c].get(k)} -> {nb[c].get(k)}")
        if ob[c].get("cpi") != nb[c].get("cpi"):
            out["price"].append(f"{c or 'market'} CPI: {ob[c].get('cpi')} -> {nb[c].get('cpi')}")
    for k in ("value", "currency"):
        if old.get(k) != new.get(k):
            out["price"].append(f"{k}: {old.get(k)} -> {new.get(k)}")
    return out


def line_items(s: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []
    for ln in s["lines"]:
        desc = " - ".join(x for x in (ln.get("methodology") or "Online Survey", ln.get("country")) if x)
        if ln.get("loi_minutes"):
            desc += f" | LOI: {ln['loi_minutes']:g} mins"
        if ln.get("ir_percent"):
            desc += f" | IR: {ln['ir_percent']:g}%"
        qty = ln.get("n") or 1
        rate = ln.get("cpi") or 0
        items.append({"description": desc, "quantity": qty, "unit": "completes" if ln.get("n") else "project",
                      "rate": rate, "unit_price": rate, "amount": round(qty * rate, 2)})
    if len(items) == 1 and not items[0]["rate"] and s.get("value"):
        it = items[0]           # a quoted total with no per-complete price: carry the total, CPI derived
        it["amount"] = s["value"]
        it["rate"] = it["unit_price"] = round(s["value"] / (it["quantity"] or 1), 4)
    return items


def _rfq_no(opp) -> str:
    from app.services.spine_rfq import _rfq_display_id
    return _rfq_display_id(opp)


def latest(fin, opp_id: str) -> Optional[Dict[str, Any]]:
    return fin["estimates"].find_one({"estimate_group_id": opp_id, "is_latest": True})


def sync(fin, opp: Dict[str, Any], decision: Optional[Dict[str, Any]] = None, *, now: Optional[datetime] = None,
         reason: str = "rfq updated", customer: Optional[Dict[str, Any]] = None, apply: bool = True,
         override: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[Dict[str, Any]]]:
    """-> ("created" | "new_version" | "unchanged", the estimate written or that would be).

    override: an estimate a person built (convert-to-estimate) -- its items and
    totals are the new version's, whatever the RFQ fields say."""
    now = now or datetime.utcnow()
    oid = str(opp["_id"])
    snap = snapshot(opp, decision)
    if override:
        snap = {**snap, "manual": {k: override.get(k) for k in ("line_items", "total", "currency")}}
    fp = fingerprint(snap)
    prev = latest(fin, oid)
    if prev and prev.get("fingerprint") == fp:
        return "unchanged", prev
    version = int((prev or {}).get("version") or 0) + 1
    base = (prev or {}).get("estimate_base") or "EST-" + _rfq_no(opp).replace("RFQ-", "")
    change = diff(prev.get("snapshot") or {}, snap) if prev else {"scope": [], "price": []}
    if override:
        change["price"].append("set by a person")
    status = STATUS_BY_RFQ.get((opp.get("status") or "open").lower(), "draft")
    if override:
        status = override.get("status") or "draft"
    items = override["line_items"] if override and override.get("line_items") else line_items(snap)
    subtotal = round(sum(float(i.get("amount") or 0) for i in items), 2)
    doc = {
        "estimate_base": base, "estimate_number": f"{base}-V{version}", "document_number": f"{base}-V{version}",
        "version": version, "is_latest": True, "estimate_group_id": oid, "opportunity_id": oid,
        "rfq_id": _rfq_no(opp), "rfq_object_id": oid,
        "customer_id": str(customer["_id"]) if customer else None,
        "customer_name": (customer or {}).get("name") or (customer or {}).get("company_name"),
        "project_name": opp.get("title"), "status": status, "date": now,
        "expiry_date": now + timedelta(days=VALID_DAYS), "currency": snap.get("currency"),
        "currency_code": snap.get("currency"), "items": items, "line_items": items, "subtotal": subtotal,
        "tax_total": 0, "total": subtotal, "total_amount": subtotal,
        "snapshot": snap, "fingerprint": fp, "change": change, "change_reason": reason,
        "previous_version_id": str(prev["_id"]) if prev else None, "source": "rfq",
        "created_at": now, "updated_at": now,
    }
    if override:
        doc.update({k: override[k] for k in ("discount_percent", "discount_amount", "tax_percent", "tax_amount",
                                              "total", "notes", "terms", "customer_id", "customer_name",
                                              "expiry_date") if k in override})
        doc["total_amount"] = doc["total"]
    if not apply:
        return ("new_version" if prev else "created"), doc
    new_id = fin["estimates"].insert_one(doc).inserted_id
    doc["_id"] = new_id
    if prev:
        upd = {"is_latest": False, "superseded_by": str(new_id), "superseded_at": now, "updated_at": now}
        if (prev.get("status") or "draft") in ("draft", "expired"):
            upd["status"] = "superseded"
        fin["estimates"].update_one({"_id": prev["_id"]}, {"$set": upd})
    return ("new_version" if prev else "created"), doc


def customer_for(fin, opp) -> Optional[Dict[str, Any]]:
    aid = str(opp.get("account_id") or "")
    return fin["customers"].find_one({"crm_account_id": aid}, {"name": 1, "company_name": 1}) if aid else None


def history(fin, opp_id: str) -> List[Dict[str, Any]]:
    return list(fin["estimates"].find({"estimate_group_id": opp_id},
                                      {"snapshot": 0, "fingerprint": 0}).sort("version", 1))
