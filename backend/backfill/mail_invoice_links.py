"""Link invoices and client POs to RFQs/projects from the mail chain (owner, 2026-10-26).

Closed studies carry their billing in the thread: "please find invoice
CR/26-27/014", "PO No 4500123456". For every mail that names one of OUR invoice
numbers:
  thread -> RFQ (opportunity) by Gmail thread id -> its Operations project(s)
  accepted only when the invoice's customer is the RFQ's account (directly or
  through the Zoho legal-name aliases) -- otherwise it is a suggestion for a
  person, never a link
Client PO numbers found in those RFQ threads (mail_pipeline.rules.po_numbers,
client mail only) fill the RFQ / project PO when empty and are checked against
the invoice's Zoho order number.

Writes only on --apply (scripts/backfill_phase4.py --step mail_invoice_links):
fill-only on opportunity_id / po_number, addToSet on invoice_links /
ops_project_ids, stamped backfill.mail_invoice_links. Nothing overwritten.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId

INV_TOKEN = re.compile(r"\b(SF|CR)\s*/\s*(\d{2,4}(?:-\d{2})?|\d{2,3})\s*/\s*(\d{2,4}(?:-\d{2})?[a-z]?)\b", re.I)
OWN = ("surveyfieldwork.com", "cogentixresearch.com", "bimwavesolutions.com")


def norm_no(s: str) -> str:
    return re.sub(r"\s+", "", s or "").upper()


def tokens(text: str) -> set:
    return {norm_no(m.group(0)) for m in INV_TOKEN.finditer(text or "")}


def run(c, apply=False, now=None) -> Dict[str, Any]:
    from mail_pipeline.rules import po_numbers
    now = now or datetime.utcnow()
    fin, crm, ea = c.finance_db, c.crm_db, c.email_automation
    md = c.torpedo_gmail.email_metadata
    invoices = {norm_no(i["invoice_number"]): i for i in fin.invoices.find(
        {"invoice_number": {"$type": "string"}, "is_deleted": {"$ne": True}},
        {"invoice_number": 1, "customer_id": 1, "opportunity_id": 1, "ops_project_id": 1, "ops_project_ids": 1,
         "po_reference": 1, "status": 1})}
    cust_acc = {str(x["_id"]): str(x.get("crm_account_id") or "") for x in fin.customers.find({}, {"crm_account_id": 1})}
    thread_opp: Dict[str, Dict[str, Any]] = {}
    for o in crm.opportunities.find({}, {"account_id": 1, "title": 1, "po_number": 1, "metadata.rfq.gmail_thread_id": 1,
                                         "metadata.rfq.gmail_thread_ids": 1, "metadata.rfq.po_number": 1}):
        r = (o.get("metadata") or {}).get("rfq") or {}
        for t in [r.get("gmail_thread_id")] + list(r.get("gmail_thread_ids") or []):
            if t:
                thread_opp[t] = o
    proj_by_opp = defaultdict(list)
    for p in ea.projects.find({"is_deleted": {"$ne": True}}, {"opportunity_id": 1, "rfqId": 1, "po_number": 1}):
        k = str(p.get("opportunity_id") or p.get("rfqId") or "")
        if k:
            proj_by_opp[k].append(p)

    rep: Counter = Counter()
    samples = defaultdict(list)
    links = defaultdict(set)          # invoice no -> opportunity ids (accepted)
    suggest = defaultdict(set)
    pos = defaultdict(set)            # opportunity id -> client POs seen in its thread
    q = {"body_plain": {"$regex": r"(SF|CR)\s*/\s*\d", "$options": "i"}}
    for m in md.find(q, {"subject": 1, "body_plain": 1, "gmail_thread_id": 1, "mail_counterparty": 1, "direction": 1,
                         "from_email": 1}):
        found = {t for t in tokens((m.get("subject") or "") + "\n" + (m.get("body_plain") or "")[:20000]) if t in invoices}
        if not found:
            continue
        rep["mails_naming_our_invoices"] += 1
        opp = thread_opp.get(m.get("gmail_thread_id"))
        if not opp:
            rep["mail_not_in_an_rfq_thread"] += 1
            continue
        oid = str(opp["_id"])
        for no in found:
            inv = invoices[no]
            inv_acc = cust_acc.get(str(inv.get("customer_id")))
            if inv_acc and str(opp.get("account_id") or "") == inv_acc:
                links[no].add(oid)
            else:
                suggest[no].add(oid)
    # client POs in the threads of RFQs that got an invoice link
    linked_opps = {o for s in links.values() for o in s}
    for t, o in thread_opp.items():
        if str(o["_id"]) not in linked_opps:
            continue
        for m in md.find({"gmail_thread_id": t, "direction": "inbound"}, {"body_plain": 1, "from_email": 1}).limit(40):
            if (m.get("from_email") or "").lower().endswith(OWN):
                continue
            for po in po_numbers(m.get("body_plain") or ""):
                pos[str(o["_id"])].add(po)

    rep["invoices_linked_to_an_rfq"] = len(links)
    rep["invoices_only_suggested (customer != RFQ account)"] = len(set(suggest) - set(links))
    rep["rfqs_with_client_po_in_thread"] = len(pos)
    already = sum(1 for no in links if invoices[no].get("opportunity_id"))
    rep["of_which_invoice_already_had_an_rfq"] = already
    for no, opps in list(links.items())[:10]:
        samples["linked"].append(f"{no} -> RFQ {', '.join(sorted(opps))[:60]}"
                                 + (f" (was {invoices[no].get('opportunity_id')})" if invoices[no].get("opportunity_id") else ""))
    for no, opps in list((k, v) for k, v in suggest.items() if k not in links)[:10]:
        samples["suggested"].append(f"{no} -> RFQ {', '.join(sorted(opps))[:60]} (customer differs)")
    for oid, ps in list(pos.items())[:10]:
        samples["client_po"].append(f"RFQ {oid}: {', '.join(sorted(ps))}")

    if apply:
        from pymongo import UpdateOne
        iops, pops, oops = [], [], []
        for no, opps in links.items():
            inv = invoices[no]
            projs = [str(p["_id"]) for o in opps for p in proj_by_opp.get(o, [])]
            upd = {"$addToSet": {"ops_project_ids": {"$each": projs}, "linked_opportunity_ids": {"$each": sorted(opps)}},
                   "$set": {"backfill.mail_invoice_links": now}}
            if not inv.get("opportunity_id") and len(opps) == 1:
                upd["$set"]["opportunity_id"] = next(iter(opps))
            iops.append(UpdateOne({"_id": inv["_id"]}, upd))
            for o in opps:
                for p in proj_by_opp.get(o, []):
                    pops.append(UpdateOne({"_id": p["_id"]}, {"$addToSet": {
                        "invoice_ids": str(inv["_id"]),
                        "invoice_links": {"invoice": inv["invoice_number"], "invoice_id": str(inv["_id"]),
                                          "method": "mail_thread_invoice_no", "detail": "invoice number in the RFQ thread"}},
                        "$set": {"backfill.mail_invoice_links": now}}))
        for oid, ps in pos.items():
            po = sorted(ps)[0] if len(ps) == 1 else None
            if po:
                oops.append(UpdateOne({"_id": ObjectId(oid), "po_number": {"$in": [None, ""]}},
                                      {"$set": {"po_number": po, "metadata.rfq.po_number": po}}))
                for p in proj_by_opp.get(oid, []):
                    pops.append(UpdateOne({"_id": p["_id"], "po_number": {"$in": [None, ""]}}, {"$set": {"po_number": po}}))
            else:
                rep["rfqs_with_several_pos (not set, review)"] += 1
        for col, ops in ((fin.invoices, iops), (ea.projects, pops), (crm.opportunities, oops)):
            for i in range(0, len(ops), 500):
                if ops[i:i + 500]:
                    col.bulk_write(ops[i:i + 500], ordered=False)
        rep["review_items_resolved"] = _resolve(ea, {str(p["_id"]) for o in linked_opps for p in proj_by_opp.get(o, [])}, now)
    return {**rep, "samples": dict(samples)}


def _resolve(ea, project_ids, now) -> int:
    n = 0
    for it in ea.review_queue_items.find({"status": "pending", "type": "invoice_request",
                                          "ref.collection": "email_automation.projects"}, {"ref": 1}):
        if str((it.get("ref") or {}).get("id")) in project_ids:
            ea.review_queue_items.update_one({"_id": it["_id"]}, {"$set": {
                "status": "resolved", "resolved_at": now, "updated_at": now,
                "resolution": {"action": "approve", "by": "system:mail_invoice_links",
                               "note": "invoice number found in the RFQ's mail thread"}}})
            n += 1
    return n
