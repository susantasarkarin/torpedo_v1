"""
Every invoice is a won project (owner, 2026-09-29: "refer to the number of
invoices and add some 15 more -- that is the real number of won projects").

The Finance invoices (imported from Zoho Books) carry a customer, a date and
an amount -- no line items or project names; 42 have a PO reference. Each is
tied to the RFQ it billed, strongest evidence first:

  1. the invoice number appears in a mail ("SF/21-22/040") -> that thread's RFQ
  2. the customer's RFQs in the 180 days before the invoice that are not
     already billed: the local model picks the one the PO reference names
     (AI first); otherwise the latest one we quoted, else the latest one
  3. no RFQ at all: the project is still a won project -- a record is made
     from the invoice itself

The RFQ is marked won (dated by its live link / go-ahead if the mail had
one, else the invoice) and handed off as history: work order, contract and a
completed Operations project, with the invoice and its PO linked.
"""
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.services import mail_categorizer as mc
from app.services import rfq_from_mail as rb

logger = logging.getLogger(__name__)

_INV_NO = re.compile(r"\b(?:SF|CR)/[0-9][0-9A-Za-z/\-]{3,14}\b")
_GENERIC = {"group", "research", "private", "limited", "india", "services", "solutions", "marketing", "insights",
            "international", "interactive", "company", "consulting", "global", "systems", "technologies", "data",
            "division", "retail", "pvt", "ltd", "llc", "inc", "the", "and", "for"}


def _name_tokens(name: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]{4,}", (name or "").lower()) if w not in _GENERIC}


def invoice_mentions(client) -> Dict[str, List[Dict[str, Any]]]:
    """invoice number -> mails that mention it (one pass over the pool)."""
    em = client["torpedo_gmail"]["email_metadata"]
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    rx = {"$regex": r"(SF|CR)/[0-9]"}
    for d in em.find({"$or": [{"subject": rx}, {"body_plain": rx}]},
                     {"subject": 1, "body_plain": 1, "gmail_thread_id": 1, "timestamp": 1, "direction": 1}):
        text = f"{d.get('subject') or ''}\n{(d.get('body_plain') or '')[:20000]}"
        for n in set(_INV_NO.findall(text)):
            out[n.upper()].append({"thread": d.get("gmail_thread_id"), "ts": d.get("timestamp"), "_id": d["_id"]})
    return out


def _ai_pick(inv: Dict[str, Any], cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The model chooses which RFQ a PO reference names; None if unsure/unavailable."""
    from app.services import rfq_ai
    listing = "\n".join(f"{i + 1}. {c['title']}" for i, c in enumerate(cands[:12]))
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"choice": {"type": "integer"}}, "required": ["choice"]}
    out = rfq_ai._ask("An invoice's PO reference names a study. Which RFQ title below is that study? Answer "
                      "its number, or 0 if none clearly matches. JSON only.",
                      f"PO reference: {inv.get('po_reference')}\n\nRFQs:\n{listing}", schema, max_tokens=20)
    k = (out or {}).get("choice")
    if isinstance(k, int) and 1 <= k <= min(12, len(cands)):
        chosen = cands[k - 1]
        # guard: the choice must share a word with the PO reference
        if rb._tokens(chosen["title"]) & rb._tokens(inv.get("po_reference") or ""):
            return chosen
    return None


def link_invoices(client, now: Optional[datetime] = None, limit: Optional[int] = None,
                  dry_run: bool = False, samples: Optional[List[str]] = None) -> Dict[str, int]:
    """dry_run: decide and count, write nothing (samples collects a line per invoice)."""
    from app.services.won_handoff import handoff_won_opportunity
    now = now or datetime.utcnow()
    fin, crm = client["finance_db"], client["crm_db"]
    opp = crm["opportunities"]
    mentions = invoice_mentions(client)
    customers = {str(c["_id"]): c for c in fin["customers"].find({}, {"name": 1, "company_name": 1, "email": 1})}
    stats = {"invoices": 0, "by_mail_mention": 0, "by_ai_po": 0, "by_customer_and_date": 0,
             "created_from_invoice": 0, "already_linked": 0}
    billed = {str(x) for x in opp.distinct("_id", {"metadata.rfq.invoice_ids.0": {"$exists": True}})}
    invs = list(fin["invoices"].find({"is_deleted": {"$ne": True}}).sort("invoice_date", 1))
    for inv in invs[:limit] if limit else invs:
        stats["invoices"] += 1
        inv_id = str(inv["_id"])
        if opp.find_one({"metadata.rfq.invoice_ids": inv_id}, {"_id": 1}):
            stats["already_linked"] += 1
            continue
        when = inv.get("invoice_date") or inv.get("created_at") or now
        cust = customers.get(str(inv.get("customer_id"))) or {}
        cust_name = cust.get("company_name") or cust.get("name") or "Client"
        target, via = None, ""

        # 1. the invoice number in a mail
        for m in mentions.get((inv.get("invoice_number") or "").upper(), []):
            o = opp.find_one({"metadata.rfq.gmail_thread_ids": m["thread"]})
            if o:
                target, via = o, "invoice number in the project's mail"
                stats["by_mail_mention"] += 1
                break

        # 2. the customer's RFQs shortly before the invoice
        if not target:
            toks = _name_tokens(cust_name)
            dom = mc._domain((cust.get("email") or "").lower())
            if dom and dom not in mc.WEBMAIL:
                toks.add(rb.registrable_root(dom))
            cands = []
            if toks:
                for o in opp.find({"metadata.rfq.received_at": {"$gte": when - timedelta(days=180), "$lte": when}},
                                  {"title": 1, "stage": 1, "status": 1, "metadata.rfq": 1}):
                    r = o["metadata"]["rfq"]
                    rfq_toks = _name_tokens(r.get("account_name") or "") | {
                        rb.registrable_root(mc._domain((r.get("from_email") or "").lower()))}
                    if toks & rfq_toks and str(o["_id"]) not in billed:
                        cands.append(o)
            cands.sort(key=lambda o: o["metadata"]["rfq"].get("received_at") or datetime.min, reverse=True)
            if cands and inv.get("po_reference") and len(cands) > 1:
                target = _ai_pick(inv, cands)
                if target:
                    via = "the model matched the invoice's PO reference"
                    stats["by_ai_po"] += 1
            if not target and cands:
                quoted = [o for o in cands if o["metadata"]["rfq"].get("quote_email_id")]
                target = (quoted or cands)[0]
                via = "customer's RFQ shortly before the invoice"
                stats["by_customer_and_date"] += 1

        if dry_run:
            if not target:
                stats["created_from_invoice"] += 1
            if samples is not None:
                samples.append(f"{inv.get('invoice_number')} {str(when)[:10]} {cust_name[:30]} -> "
                               f"{(target or {}).get('title', '(new record)')[:45]} [{via or 'no RFQ'}]")
            if target:
                billed.add(str(target["_id"]))
            continue

        # 3. no RFQ: the invoice is still a won project
        if not target:
            from app.services import crm_service
            res = crm_service.create_rfq({
                "title": f"{cust_name} -- invoice {inv.get('invoice_number')}", "budget": 0,
                "currency": inv.get("currency_code"), "received_at": when, "direction": "inbound",
                "source": "invoice", "account_name": cust_name, "description": "Created from a Finance invoice "
                "with no matching RFQ in the mail"})
            target = opp.find_one({"_id": ObjectId(res["opportunity"]["_id"])})
            via = "invoice with no RFQ in the mail"
            stats["created_from_invoice"] += 1

        r = target.get("metadata", {}).get("rfq", {})
        won_at = (r.get("live_link") or {}).get("at") or when
        sets = {"stage": "won", "status": "won", "won_at": won_at, "closed_at": won_at,
                "won_via": f"invoiced {inv.get('invoice_number')} ({via})"}
        if not target.get("amount"):
            sets.update({"amount": float(inv.get("total_amount") or inv.get("total") or 0),
                         "currency": inv.get("currency_code") or target.get("currency"), "value_source": "invoice"})
        opp.update_one({"_id": target["_id"]}, {"$set": sets, "$addToSet": {"metadata.rfq.invoice_ids": inv_id},
                                                 "$unset": {"closed_reason": "", "closed_by": ""}})
        billed.add(str(target["_id"]))
        handoff_won_opportunity(opp.find_one({"_id": target["_id"]}), historical=True, invoice=inv)
    return stats
