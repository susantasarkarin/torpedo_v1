"""Finance jobs (CRM plan 3.9 / Section 6), shadow by default.

receivables(): daily; the rules send upcoming lists on Mondays and overdue
lists every 14 days per client contact, plus the >60-day credit hold.
bank_import(): daily; CSV statements dropped in <BANK_STATEMENT_DIR>/<BU>/
are parsed into finance_db.bank_transactions (once per file, by hash) with
receipt match suggestions against open INR invoices.

Shadow: plans and suggestions only (email_automation.finance_decisions,
bank_transactions.suggestions). Live (owner, config accounting.mode): mails
become Review Queue drafts, credit hold is stamped on accounts, unmatched
bank lines go to the Review Queue. The existing per-invoice reminder drafts
in finance_automation keep running until the owner switches this live.
"""
import hashlib
import logging
import os
import re
from datetime import date, datetime
from typing import Any, Dict, Optional

from accounting import invoicing, reconcile

logger = logging.getLogger(__name__)
BU_OF_BRANCH = {"Survey Fieldwork": "SFW", "Cogentix Research": "COGENTIX", "BIM Wave Solutions": "BIM"}


def _gd():
    from database import get_database
    return get_database


def _mode() -> str:
    from platform_core import config_store
    return (config_store.get("accounting") or {}).get("mode", "shadow")


_BILLING = re.compile(r"^(accounts?|finance|billing|ap|payables?|invoices?)[._-]?", re.I)


def billing_contacts(crm, account_ids) -> Dict[str, str]:
    """Finance customers often have no email: use the account's contacts,
    a billing/accounts address first, else the most recently updated one."""
    from bson import ObjectId
    ids = [a for a in {str(x) for x in account_ids if x}]
    oids = [ObjectId(a) for a in ids if ObjectId.is_valid(a)]
    best: Dict[str, tuple] = {}
    for ct in crm["contacts"].find({"account_id": {"$in": ids + oids}, "email": {"$type": "string"}},
                                   {"account_id": 1, "email": 1, "updated_at": 1}):
        e = ct["email"].lower()
        rank = (1 if _BILLING.match(e) else 0, ct.get("updated_at") or datetime.min)
        a = str(ct["account_id"])
        if a not in best or rank > best[a][0]:
            best[a] = (rank, e)
    return {a: v[1] for a, v in best.items()}


def receivables(now: Optional[datetime] = None) -> Dict[str, Any]:
    from platform_core import config_store, review_queue
    gd = _gd()
    cfg = config_store.get("accounting")
    now = now or datetime.utcnow()
    fin, ea = gd("finance_db"), gd("email_automation")
    cust = {str(c["_id"]): c for c in fin["customers"].find({}, {"email": 1, "crm_account_id": 1, "name": 1})}
    billing = billing_contacts(gd("crm_db"), [c.get("crm_account_id") for c in cust.values() if not c.get("email")])
    invs = []
    for i in fin["invoices"].find({"status": {"$nin": ["draft", "void", "paid", "written_off"]}, "balance_due": {"$gt": 0},
                                   "intercompany": {"$ne": True},
                                   "is_deleted": {"$ne": True}},
                                  {"invoice_number": 1, "status": 1, "balance_due": 1, "due_date": 1, "customer_id": 1}):
        c = cust.get(str(i.get("customer_id"))) or {}
        if isinstance(i.get("due_date"), datetime):
            invs.append({"number": i["invoice_number"], "status": i["status"], "balance_due": i["balance_due"],
                         "due_date": i["due_date"].date(), "contact_email": (c.get("email") or "").lower() or billing.get(str(c.get("crm_account_id"))),
                         "account_id": c.get("crm_account_id")})
    last = {d["to"]: d["at"].date() for d in ea["finance_decisions"].find({"kind": "overdue_mail", "mode": "live"}).sort("at", 1)}
    plan = invoicing.receivable_mails(invs, (now).date(), last_overdue_mail=last, cfg=cfg)
    mode = cfg.get("mode", "shadow")
    for kind, mails in (("upcoming_mail", plan["upcoming"]), ("overdue_mail", plan["overdue"])):
        for m in mails:
            ea["finance_decisions"].insert_one({"kind": kind, "mode": mode, "at": now, **m})
            if mode == "live":
                review_queue.enqueue(type="other", module="finance", ref={"collection": "finance_mail", "id": f"{kind}:{m['to']}:{now:%Y%m%d}"},
                                     reason=f"{kind.replace('_', ' ')}: {len(m['invoices'])} invoice(s)", suggested=m)
    if mode == "live":
        from bson import ObjectId
        for aid in plan["credit_hold_accounts"]:
            try:
                gd("crm_db")["accounts"].update_one({"_id": ObjectId(str(aid))}, {"$set": {"credit_hold": True, "credit_hold_at": now}})
            except Exception:
                pass
    stats = {"mode": mode, "upcoming": len(plan["upcoming"]), "overdue": len(plan["overdue"]),
             "credit_hold_accounts": len(plan["credit_hold_accounts"])}
    ea["finance_decisions"].insert_one({"kind": "summary", "at": now, **stats})
    logger.info("receivables: %s", stats)
    return stats


def bank_import(now: Optional[datetime] = None, root: Optional[str] = None) -> Dict[str, Any]:
    gd = _gd()
    now = now or datetime.utcnow()
    root = root or os.getenv("BANK_STATEMENT_DIR", "/var/lib/crm/bank")
    fin = gd("finance_db")
    stats = {"files": 0, "lines": 0, "auto": 0, "review": 0}
    if not os.path.isdir(root):
        stats["skipped"] = f"{root} does not exist (owner drops statements per BU there)"
        return stats
    opens = [{"number": i["invoice_number"], "date": i["invoice_date"].date(), "balance_due": float(i["balance_due"]),
              "taxable": float(i.get("subtotal") or i["balance_due"]), "customer_id": str(i.get("customer_id")),
              "customer_name": i.get("customer_name") or ""}
             for i in fin["invoices"].find({"balance_due": {"$gt": 0}, "currency_code": "INR", "intercompany": {"$ne": True},
                                            "status": {"$nin": ["draft", "void", "paid", "written_off"]}},
                                           {"invoice_number": 1, "invoice_date": 1, "balance_due": 1, "subtotal": 1,
                                            "customer_id": 1, "customer_name": 1})
             if isinstance(i.get("invoice_date"), datetime)]
    for bu in sorted(os.listdir(root)):
        folder = os.path.join(root, bu)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".csv"):
                continue
            path = os.path.join(folder, name)
            with open(path, "rb") as fh:
                raw = fh.read()
            h = hashlib.sha256(raw).hexdigest()
            if fin["bank_statements"].find_one({"_id": h}):
                continue
            lines = reconcile.parse_statement_csv(raw.decode("utf-8", "replace"))
            for ln in lines:
                m = reconcile.match_receipt(ln, opens) if ln["amount"] > 0 else {"auto": False, "suggestions": []}
                fin["bank_transactions"].insert_one({"bu": bu.upper(), "date": datetime.combine(ln["date"], datetime.min.time()),
                                                     "amount": ln["amount"], "reference": ln["reference"], "narration": ln["narration"],
                                                     "statement": h, "auto_match": m.get("match") if m["auto"] else None,
                                                     "suggestions": m.get("suggestions") or [], "status": "suggested" if m["auto"] else "unmatched",
                                                     "created_at": now, "source": f"bank_csv:{name}"})
                stats["auto" if m["auto"] else "review"] += 1
            fin["bank_statements"].insert_one({"_id": h, "bu": bu.upper(), "file": name, "lines": len(lines), "imported_at": now})
            stats["files"] += 1
            stats["lines"] += len(lines)
    logger.info("bank import: %s", stats)
    return stats
