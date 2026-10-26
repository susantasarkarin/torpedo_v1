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

Most invoice mail is not in an RFQ thread (QuickBooks/Zoho notifications carry
only number, due date and amount; the rest is collections). Two more rules:
  study name   the subject names a study ("Cashfree Brand Study | Post Phase",
               "RFQ_200378", "A-21171") -> the ONE project of the invoice's
               customer sharing a job code or two distinctive words; several
               candidates is a suggestion
  client PO    a client mail naming exactly one of our invoices and exactly one
               PO ("PO No", or a SAP 45xxxxxxxx in the subject) -> that
               invoice's po_reference, only when empty

Writes only on --apply (scripts/backfill_phase4.py --step mail_invoice_links):
fill-only on opportunity_id / po_number / po_reference, addToSet on
invoice_links / ops_project_ids, stamped backfill.mail_invoice_links.
Nothing overwritten.
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


SAP_PO = re.compile(r"\b45\d{8}\b")
CODE = re.compile(r"\b[A-Z]{0,4}[-_]?\d{4,8}\b", re.I)
GENERIC = set("""study survey surveys fieldwork invoice invoices pending payment payments outstanding reminder request
proposal project projects research phase post with from your this that for and the india global online quote
followup follow update details account ageing report contact market group final data recruitment""".split())


def name_keys(s: str):
    """(job codes, distinctive words) of a subject or project name."""
    s = INV_TOKEN.sub(" ", s or "")
    codes = {re.sub(r"[-_]", "", c).upper() for c in CODE.findall(s)}
    codes = {c for c in codes if not re.fullmatch(r"(19|20)\d\d", c)}            # a year is not a job code
    words = {w for w in re.findall(r"[a-z]{4,}", s.lower()) if w not in GENERIC}
    return codes, words


def name_match(subject: str, candidates) -> list:
    """Candidates (id, name) the subject names: a shared job code, or two shared distinctive words."""
    sc, sw = name_keys(subject)
    if not sc and len(sw) < 2:
        return []
    out = []
    for cid, name in candidates:
        cc, cw = name_keys(name)
        if (sc & cc) or len(sw & cw) >= 2:
            out.append(cid)
    return out


def mail_pos(subject: str, body: str) -> set:
    from mail_pipeline.rules import po_numbers
    found = set(po_numbers(body or "")) | set(po_numbers(subject or "")) | set(SAP_PO.findall(subject or ""))
    # a PO is mostly digits: "INTS2SHOP", "STS/ACTIVITY-6687..." are words or system ids
    return {p for p in found if len(re.findall(r"\d", p)) >= 4 and not re.search(r"[A-Z]{5,}", p)}


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
    proj_by_cust = defaultdict(list)
    for p in ea.projects.find({"is_deleted": {"$ne": True}}, {"opportunity_id": 1, "rfqId": 1, "po_number": 1,
                                                             "projectName": 1, "finance_customer_id": 1, "customer_id": 1}):
        k = str(p.get("opportunity_id") or p.get("rfqId") or "")
        if k:
            proj_by_opp[k].append(p)
        for ck in {str(p.get("finance_customer_id") or ""), str(p.get("customer_id") or "")} - {""}:
            proj_by_cust[ck].append(p)
    proj_by_id = {str(p["_id"]): p for ps in proj_by_cust.values() for p in ps}

    rep: Counter = Counter()
    samples = defaultdict(list)
    links = defaultdict(set)          # invoice no -> opportunity ids (accepted)
    suggest = defaultdict(set)
    name_links = defaultdict(set)     # invoice no -> project ids named in the subject (accepted)
    inv_po = defaultdict(set)         # invoice no -> client POs in a mail naming only that invoice
    pos = defaultdict(set)            # opportunity id -> client POs seen in its thread
    q = {"body_plain": {"$regex": r"(SF|CR)\s*/\s*\d", "$options": "i"}}
    for m in md.find(q, {"subject": 1, "body_plain": 1, "gmail_thread_id": 1, "mail_counterparty": 1, "direction": 1,
                         "from_email": 1}):
        subj, body = m.get("subject") or "", (m.get("body_plain") or "")[:20000]
        found = {t for t in tokens(subj + "\n" + body) if t in invoices}
        if not found:
            continue
        rep["mails_naming_our_invoices"] += 1
        client_mail = not (m.get("from_email") or "").lower().endswith(OWN)
        if client_mail and len(found) == 1:
            ps = mail_pos(subj, body)
            if len(ps) == 1:
                inv_po[next(iter(found))] |= ps
        opp = thread_opp.get(m.get("gmail_thread_id"))
        if not opp:
            rep["mail_not_in_an_rfq_thread"] += 1
            for no in found:
                cands = [(str(p["_id"]), p.get("projectName") or "")
                         for p in proj_by_cust.get(str(invoices[no].get("customer_id")), [])]
                hit = name_match(subj, cands)
                if len(hit) == 1:
                    name_links[no].add(hit[0])
                elif hit:
                    rep["study_name_matched_several_projects (not linked)"] += 1
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
    for no in list(name_links):
        if len(name_links[no]) > 1:
            name_links.pop(no)
            rep["study_name_points_to_several_projects (not linked)"] += 1
    rep["invoices_linked_by_study_name"] = len(name_links)
    for no, ps in list(name_links.items())[:12]:
        p = proj_by_id[next(iter(ps))]
        samples["by_study_name"].append(f"{no} -> project '{(p.get('projectName') or '')[:50]}'")
    po_fill = {}
    for no, ps in inv_po.items():
        have = (invoices[no].get("po_reference") or "").strip().upper()
        if len(ps) > 1:
            rep["invoice_with_several_pos_in_mail (not set)"] += 1
        elif have:
            rep["po_in_mail_" + ("agrees_with_invoice" if have == next(iter(ps)) else "differs_from_invoice (kept)")] += 1
        else:
            po_fill[no] = next(iter(ps))
    rep["invoice_po_filled_from_mail"] = len(po_fill)
    for no, po in list(po_fill.items())[:12]:
        samples["invoice_po"].append(f"{no} <- PO {po}")

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
        for no, pids in name_links.items():
            inv = invoices[no]
            ps = [proj_by_id[x] for x in pids]
            opps = sorted({str(p.get("opportunity_id")) for p in ps if p.get("opportunity_id")})
            upd = {"$addToSet": {"ops_project_ids": {"$each": sorted(pids)}, "linked_opportunity_ids": {"$each": opps}},
                   "$set": {"backfill.mail_invoice_links": now}}
            if not inv.get("opportunity_id") and len(opps) == 1:
                upd["$set"]["opportunity_id"] = opps[0]
            iops.append(UpdateOne({"_id": inv["_id"]}, upd))
            for p in ps:
                pops.append(UpdateOne({"_id": p["_id"]}, {"$addToSet": {
                    "invoice_ids": str(inv["_id"]),
                    "invoice_links": {"invoice": inv["invoice_number"], "invoice_id": str(inv["_id"]),
                                      "method": "mail_subject_study_name", "detail": "study named in the invoice mail"}},
                    "$set": {"backfill.mail_invoice_links": now}}))
        for no, po in po_fill.items():
            iops.append(UpdateOne({"_id": invoices[no]["_id"], "po_reference": {"$in": [None, ""]}},
                                  {"$set": {"po_reference": po, "po_reference_source": "mail",
                                            "backfill.mail_invoice_links": now}}))
        for col, ops in ((fin.invoices, iops), (ea.projects, pops), (crm.opportunities, oops)):
            for i in range(0, len(ops), 500):
                if ops[i:i + 500]:
                    col.bulk_write(ops[i:i + 500], ordered=False)
        rep["review_items_resolved"] = _resolve(ea, {str(p["_id"]) for o in linked_opps for p in proj_by_opp.get(o, [])}
                                                | {x for s in name_links.values() for x in s}, now)
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
