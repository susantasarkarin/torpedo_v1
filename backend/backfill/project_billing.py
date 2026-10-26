"""Closed projects = billed: map each to its estimate and invoice (owner, 2026-10-26).

Owner: every study in Operations > Projects marked closed has been billed;
live / paused ones are not billed yet.

  invoice   a closed project with no invoice link takes the invoice of the
            same customer dated nearest after its close date (-30 .. +150 days;
            one invoice may carry several projects -- month-end bulk billing).
            Customer = the project's finance customer, else the customer whose
            name matches the project's client. No such invoice in Torpedo ->
            billing.status "billed_no_invoice_record" (the owner says it was
            billed; the invoice predates the Zoho import) -- never a guess
  estimate  a project with an RFQ: its RFQ estimate's current version is
            accepted. A project without one gets an estimate (version 1, source
            "project") from its CPI x completes, accepted, linked to the invoice

Dry run unless apply. Fill-only / addToSet; stamped backfill.project_billing.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bson import ObjectId

WINDOW = (timedelta(days=-30), timedelta(days=150))


def _norm(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    s = re.sub(r"\b(pvt|private|ltd|limited|llp|llc|inc|gmbh|group|the|services?|solutions?)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def _date(v) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)[:19])
    except Exception:
        return None


def run(c, apply=False, now=None) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    fin, ea, crm = c.finance_db, c.email_automation, c.crm_db
    stamp = {"backfill.project_billing": now}
    invoices = list(fin.invoices.find({"is_deleted": {"$ne": True}},
                                      {"invoice_number": 1, "customer_id": 1, "invoice_date": 1, "total": 1,
                                       "ops_project_id": 1, "ops_project_ids": 1, "currency_code": 1}))
    linked = {str(i["ops_project_id"]) for i in invoices if i.get("ops_project_id")} \
        | {str(x) for i in invoices for x in (i.get("ops_project_ids") or [])}
    by_cust = defaultdict(list)
    for i in invoices:
        if i.get("customer_id") and _date(i.get("invoice_date")):
            by_cust[str(i["customer_id"])].append(i)
    customers = list(fin.customers.find({}, {"name": 1, "legal_name": 1, "company_name": 1, "merged_into": 1}))
    by_name = {}
    for cu in customers:
        cid = cu.get("merged_into") or str(cu["_id"])
        for n in (cu.get("name"), cu.get("legal_name"), cu.get("company_name")):
            if _norm(n):
                by_name.setdefault(_norm(n), cid)

    rep: Counter = Counter()
    samples = defaultdict(list)
    proj_ops, inv_ops, est_new, est_acc = [], [], [], []
    for p in ea.projects.find({"is_deleted": {"$ne": True}, "projectStatus": "close"}):
        pid = str(p["_id"])
        rep["closed projects"] += 1
        has_inv = bool(p.get("invoice_ids")) or pid in linked or p.get("lifecycle_status") == "invoiced"
        cust = str(p.get("finance_customer_id") or p.get("customer_id") or "") or None
        if not cust:
            key = _norm(p.get("client"))
            cust = by_name.get(key) or next((v for k, v in by_name.items() if key and len(key) >= 5 and
                                             (k.startswith(key) or key.startswith(k))), None)
            if cust:
                rep["customer found by client name"] += 1
        inv = None
        if not has_inv:
            closed = _date(p.get("projectCloseDate")) or _date(p.get("createdAt"))
            cands = [i for i in by_cust.get(cust or "", []) if closed and
                     WINDOW[0] <= _date(i["invoice_date"]) - closed <= WINDOW[1]]
            cands.sort(key=lambda i: (_date(i["invoice_date"]) < closed, abs((_date(i["invoice_date"]) - closed).days)))
            inv = cands[0] if cands else None
            if inv:
                rep["invoice matched (customer + date)"] += 1
                if len(samples["matched"]) < 10:
                    samples["matched"].append(f"{(p.get('projectName') or '')[:40]} ({str(closed)[:10]}) -> "
                                              f"{inv['invoice_number']} ({str(inv['invoice_date'])[:10]})")
                proj_ops.append(({"_id": p["_id"]}, {"$addToSet": {"invoice_ids": str(inv["_id"]), "invoice_links": {
                    "invoice": inv["invoice_number"], "invoice_id": str(inv["_id"]), "method": "project_billing_match",
                    "detail": "same customer, invoice dated nearest the close date"}},
                    "$set": {"lifecycle_status": "invoiced", "billing": {"status": "invoiced", "at": now}, **stamp}}))
                inv_ops.append(({"_id": inv["_id"]}, {"$addToSet": {"ops_project_ids": pid}, "$set": stamp}))
            else:
                rep["billed, invoice not in Torpedo"] += 1
                if len(samples["no_invoice_record"]) < 8:
                    samples["no_invoice_record"].append(f"{(p.get('projectName') or '')[:40]} [{p.get('client')}] {str(closed)[:10]}")
                proj_ops.append(({"_id": p["_id"], "billing.status": {"$exists": False}}, {"$set": {
                    "billing": {"status": "billed_no_invoice_record", "at": now,
                                "note": "owner: closed projects are billed; no invoice record in Torpedo"}, **stamp}}))
        # estimate
        opp = str(p.get("opportunity_id") or p.get("rfqId") or "")
        est = fin.estimates.find_one({"estimate_group_id": opp, "is_latest": True}, {"status": 1}) if opp else None
        if est:
            if est.get("status") not in ("accepted",):
                rep["RFQ estimate marked accepted"] += 1
                est_acc.append(est["_id"])
        elif not fin.estimates.find_one({"estimate_group_id": f"project:{pid}"}, {"_id": 1}):
            qty = p.get("actualCompletes") or p.get("totalCompletes") or p.get("totalCompletesRequired") or 0
            try:
                qty, cpi = float(qty or 0), float(p.get("cpi") or 0)
            except (TypeError, ValueError):
                qty, cpi = 0.0, 0.0
            total = round(qty * cpi, 2) if qty and cpi else float(p.get("projectValue") or 0)
            rep["estimate created from project"] += 1
            est_new.append({"estimate_base": f"EST-P-{pid[-6:].upper()}", "estimate_number": f"EST-P-{pid[-6:].upper()}-V1",
                            "document_number": f"EST-P-{pid[-6:].upper()}-V1", "version": 1, "is_latest": True,
                            "estimate_group_id": f"project:{pid}", "ops_project_id": pid, "customer_id": cust,
                            "project_name": p.get("projectName"), "status": "accepted",
                            "date": _date(p.get("createdAt")) or now, "currency": p.get("currency"),
                            "currency_code": p.get("currency"),
                            "items": [{"description": p.get("projectName") or "Fieldwork", "quantity": qty or 1,
                                       "rate": cpi or total, "unit_price": cpi or total, "amount": total}],
                            "total_amount": total, "total": total, "subtotal": total, "tax_total": 0,
                            "invoice_ids": [str(inv["_id"])] if inv else [], "source": "project",
                            "change": {"scope": [], "price": []}, "change_reason": "backfill: closed project, billed",
                            "created_at": now, "updated_at": now, **stamp})
    rep["live / paused (not billed)"] = ea.projects.count_documents({"is_deleted": {"$ne": True},
                                                                     "projectStatus": {"$in": ["live", "pause"]}})
    if apply:
        for f, u in proj_ops:
            ea.projects.update_one(f, u)
        for f, u in inv_ops:
            fin.invoices.update_one(f, u)
        if est_acc:
            fin.estimates.update_many({"_id": {"$in": est_acc}}, {"$set": {"status": "accepted", "updated_at": now, **stamp}})
        if est_new:
            fin.estimates.insert_many(est_new)
    return {**rep, "samples": dict(samples)}
