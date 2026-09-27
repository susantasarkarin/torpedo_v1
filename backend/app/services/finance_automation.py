"""
Finance follow-through after a project closes (finance_db).

Daily job (run_daily_finance_automation):
  1. Mark overdue   sent/partial invoices past due with a balance -> overdue.
  2. Reminders      at 1, 7, 15 and 30 days overdue, a payment-reminder DRAFT
                    in the finance mailbox to the customer's email, plus a CRM
                    task and a follow-up entry on the invoice. Invoices overdue
                    longer than REMINDER_MAX_AGE_DAYS are left to a person (the
                    2020-era backlog must not generate a wave of drafts).
  3. Auto-reconcile a received payment whose reference/notes quote exactly one
                    open invoice number is applied to it via the same rules as
                    POST /finance/payments/reconcile. Anything fuzzier (amount
                    look-alikes) is left for a person.
  4. CA pack        early each month: last month's invoices, payments received,
                    bills and expenses as CSVs in a DRAFT to CA_EMAIL.

Nothing here sends mail by itself: every email is a draft a person sends.
Mailbox: INVOICE_REMINDER_FROM (default info@surveyfieldwork.com).
"""
import csv
import io
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from bson import ObjectId

logger = logging.getLogger(__name__)

REMINDER_MILESTONES = (1, 7, 15, 30)
REMINDER_MAX_AGE_DAYS = int(os.getenv("INVOICE_REMINDER_MAX_AGE_DAYS", "120"))
OPEN_STATUSES = ("sent", "partial", "overdue")

_client = None


def _mongo():
    global _client
    if _client is None:
        from pymongo import MongoClient
        _client = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                              serverSelectionTimeoutMS=5000)
    return _client


def _fin():
    return _mongo()["finance_db"]


def _from_mailbox() -> str:
    return (os.getenv("INVOICE_REMINDER_FROM") or "info@surveyfieldwork.com").strip().lower()


def _balance(inv: Dict[str, Any]) -> float:
    total = float(inv.get("total_amount") or inv.get("total") or 0)
    paid = float(inv.get("amount_paid") or 0)
    bal = inv.get("balance_due")
    return float(bal) if bal is not None else max(0.0, total - paid)


def _as_dt(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", ""))
        except ValueError:
            return None
    return None


def _draft(to: List[str], subject: str, body: str,
           attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    from app.services.gmail_workspace_service import GmailWorkspaceService
    svc = GmailWorkspaceService(mongo_uri=os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                                db_name="torpedo_gmail")
    svc.load_service_account()
    sender = _from_mailbox()
    return svc.create_draft(from_email=sender, to=to, subject=subject, body_plain=body,
                            signature_html=svc.get_signature(sender), attachments=attachments)


def _crm(kind: str, doc: Dict[str, Any]) -> None:
    try:
        from app.services import crm_service
        crm_service.create(kind, doc)
    except Exception as e:
        logger.warning("finance automation: crm %s failed: %s", kind, e)


# ---------------------------------------------------------------------------
# 1. overdue
# ---------------------------------------------------------------------------
def mark_overdue_invoices(now: Optional[datetime] = None) -> int:
    now = now or datetime.utcnow()
    # "partial" keeps its status (it carries information); it is still
    # reminded, since reminders cover every open status.
    res = _fin()["invoices"].update_many(
        {"status": "sent", "due_date": {"$lt": now},
         "balance_due": {"$gt": 0}, "is_deleted": {"$ne": True}},
        {"$set": {"status": "overdue", "overdue_since": now, "updated_at": now}})
    return res.modified_count


# ---------------------------------------------------------------------------
# 2. reminders
# ---------------------------------------------------------------------------
def due_milestone(days_overdue: int, already_sent: List[int]) -> Optional[int]:
    """The highest reminder milestone reached and not yet reminded, if any."""
    reached = [m for m in REMINDER_MILESTONES if days_overdue >= m and m not in already_sent]
    return max(reached) if reached else None


def reminder_text(inv: Dict[str, Any], customer: Dict[str, Any], days_overdue: int) -> Dict[str, str]:
    number = inv.get("invoice_number") or "your invoice"
    currency = inv.get("currency") or inv.get("currency_code") or ""
    amount = f"{currency} {_balance(inv):,.2f}".strip()
    due = _as_dt(inv.get("due_date"))
    due_s = due.strftime("%d %b %Y") if due else "the due date"
    name = (customer.get("name") or "").strip() or "there"
    firm = "a gentle reminder" if days_overdue < 15 else "a follow-up"
    subject = f"Payment reminder: invoice {number} ({amount} outstanding)"
    body = (
        f"Dear {name},\n\n"
        f"This is {firm} that invoice {number} for {amount} was due on {due_s} "
        f"and is now {days_overdue} day{'s' if days_overdue != 1 else ''} overdue.\n\n"
        f"If the payment has already been made, please share the remittance details so we can "
        f"reconcile it. Otherwise, we would be grateful if you could arrange the payment at the "
        f"earliest, or let us know if anything is holding it up.\n\n"
        f"Best regards,\nAccounts"
    )
    return {"subject": subject, "body": body}


def run_invoice_reminders(now: Optional[datetime] = None, limit: int = 50) -> Dict[str, int]:
    now = now or datetime.utcnow()
    fin = _fin()
    stats = {"checked": 0, "drafted": 0, "no_email": 0, "too_old": 0, "errors": 0}
    cursor = fin["invoices"].find({"status": {"$in": list(OPEN_STATUSES)},
                                   "is_deleted": {"$ne": True}}).limit(limit * 4)
    for inv in cursor:
        due = _as_dt(inv.get("due_date"))
        if not due or _balance(inv) <= 0:
            continue
        days = (now - due).days
        if days < REMINDER_MILESTONES[0]:
            continue
        stats["checked"] += 1
        if days > REMINDER_MAX_AGE_DAYS:
            stats["too_old"] += 1
            continue
        sent = [f.get("milestone") for f in (inv.get("followups") or []) if f.get("kind") == "auto_reminder"]
        milestone = due_milestone(days, sent)
        if milestone is None:
            continue

        customer = {}
        if inv.get("customer_id"):
            try:
                customer = fin["customers"].find_one({"_id": ObjectId(str(inv["customer_id"]))}) or {}
            except Exception:
                customer = {}
        text = reminder_text(inv, customer, days)
        email = (customer.get("email") or "").strip()
        outcome: Dict[str, Any] = {}
        if email:
            try:
                outcome = _draft([email], text["subject"], text["body"])
            except Exception as e:
                outcome = {"success": False, "error": str(e)}
            if outcome.get("success"):
                stats["drafted"] += 1
            else:
                stats["errors"] += 1
        else:
            stats["no_email"] += 1

        entry = {"at": now, "kind": "auto_reminder", "milestone": milestone, "channel": "email",
                 "days_overdue": days, "draft_id": outcome.get("draft_id"),
                 "error": outcome.get("error") or (None if email else "customer has no email"),
                 "note": text["subject"], "by": "system"}
        fin["invoices"].update_one({"_id": inv["_id"]}, {
            "$push": {"followups": entry}, "$set": {"last_followup_at": now, "updated_at": now}})
        where = f"draft ready in {_from_mailbox()}" if outcome.get("success") else \
            ("customer has no email on file" if not email else f"draft failed: {outcome.get('error')}")
        _crm("tasks", {"title": f"Payment reminder ({milestone}d overdue): {inv.get('invoice_number')}",
                       "description": f"{where}\n\n{text['body']}", "status": "open",
                       "due_date": now + timedelta(days=1), "source": "invoice_reminder",
                       "linked_object_type": "invoice", "linked_object_id": str(inv["_id"])})
        if stats["checked"] >= limit:
            break
    return stats


# ---------------------------------------------------------------------------
# 3. auto-reconcile on exact invoice-number reference
# ---------------------------------------------------------------------------
def _apply_payment(fin, payment: Dict[str, Any], inv: Dict[str, Any], now: datetime) -> float:
    total = float(inv.get("total_amount") or inv.get("total") or 0)
    paid = float(inv.get("amount_paid") or 0)
    unapplied = float(payment.get("amount_unapplied", payment.get("amount") or 0) or 0)
    apply_amt = min(unapplied, max(0.0, total - paid))
    if apply_amt <= 0:
        return 0.0
    new_paid = paid + apply_amt
    fin["invoices"].update_one({"_id": inv["_id"]}, {"$set": {
        "amount_paid": new_paid, "balance_due": max(0.0, total - new_paid),
        "status": "paid" if new_paid >= total - 0.01 else "partial",
        "updated_at": now, "last_payment_at": now}})
    fin["payments_received"].update_one({"_id": payment["_id"]}, {
        "$set": {"amount_unapplied": unapplied - apply_amt, "updated_at": now,
                 "reconciled_by": "auto_reference_match"},
        "$addToSet": {"invoice_ids": str(inv["_id"])},
        "$push": {"applications": {"invoice_id": str(inv["_id"]), "amount_applied": apply_amt,
                                   "at": now, "method": "auto_reference_match"}}})
    return apply_amt


def auto_reconcile_payments(now: Optional[datetime] = None, limit: int = 200) -> Dict[str, int]:
    now = now or datetime.utcnow()
    fin = _fin()
    stats = {"payments_checked": 0, "applied": 0, "ambiguous": 0}
    open_invoices = {(i.get("invoice_number") or "").strip(): i
                     for i in fin["invoices"].find({"status": {"$in": list(OPEN_STATUSES)},
                                                    "is_deleted": {"$ne": True}})
                     if i.get("invoice_number")}
    if not open_invoices:
        return stats
    payments = fin["payments_received"].find({
        "$or": [{"amount_unapplied": {"$gt": 0}},
                {"amount_unapplied": {"$exists": False}, "invoice_ids.0": {"$exists": False},
                 "invoice_id": {"$in": [None, ""]}}]}).limit(limit)
    for p in payments:
        stats["payments_checked"] += 1
        text = " ".join(str(p.get(k) or "") for k in ("reference", "notes", "description"))
        hits = [num for num in open_invoices
                if re.search(rf"(?<![\w/-]){re.escape(num)}(?![\w/-])", text)]
        if len(hits) != 1:
            stats["ambiguous"] += bool(hits)
            continue
        if _apply_payment(fin, p, open_invoices[hits[0]], now) > 0:
            stats["applied"] += 1
    return stats


# ---------------------------------------------------------------------------
# 4. monthly CA pack
# ---------------------------------------------------------------------------
def _csv(rows: List[Dict[str, Any]], fields: List[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (r.get(k).isoformat() if isinstance(r.get(k), datetime) else r.get(k))
                    for k in fields})
    return buf.getvalue()


def build_ca_pack(start: datetime, end: datetime) -> Dict[str, Any]:
    fin = _fin()
    def rows(col, date_field):
        return list(fin[col].find({date_field: {"$gte": start, "$lt": end}, "is_deleted": {"$ne": True}}))
    invoices = rows("invoices", "invoice_date")
    payments = rows("payments_received", "payment_date")
    bills = rows("bills", "bill_date")
    expenses = rows("expenses", "expense_date")
    files = {
        "invoices.csv": _csv(invoices, ["invoice_number", "invoice_date", "due_date", "customer_id",
                                        "currency", "subtotal", "tax_amount", "tds_amount",
                                        "total_amount", "amount_paid", "balance_due", "status", "gstin"]),
        "payments_received.csv": _csv(payments, ["payment_number", "payment_date", "customer_id",
                                                 "amount", "method", "reference", "invoice_ids"]),
        "bills.csv": _csv(bills, ["bill_number", "bill_date", "due_date", "vendor_id", "currency",
                                  "subtotal", "tax_amount", "total", "status"]),
        "expenses.csv": _csv(expenses, ["expense_number", "expense_date", "category", "vendor_id",
                                        "amount", "tax_amount", "currency", "notes"]),
    }
    summary = {
        "invoices": len(invoices),
        "invoiced_total": sum(float(i.get("total_amount") or i.get("total") or 0) for i in invoices),
        "payments": len(payments),
        "received_total": sum(float(p.get("amount") or 0) for p in payments),
        "bills": len(bills), "expenses": len(expenses),
    }
    return {"files": files, "summary": summary}


def run_monthly_ca_pack(now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    end = datetime(now.year, now.month, 1)
    start = datetime(end.year - 1, 12, 1) if end.month == 1 else datetime(end.year, end.month - 1, 1)
    period = start.strftime("%Y-%m")
    fin = _fin()
    ca_email = (os.getenv("CA_EMAIL") or "").strip()
    existing = fin["ca_packs"].find_one({"period": period})
    # Done once drafted; without a CA email, noted once and retried only after
    # CA_EMAIL is configured (no daily task spam).
    if existing and (existing.get("draft_id") or not ca_email):
        return {"skipped": f"pack for {period} already handled"}
    pack = build_ca_pack(start, end)
    record: Dict[str, Any] = {"period": period, "created_at": now, "summary": pack["summary"],
                              "ca_email": ca_email or None}
    if ca_email:
        s = pack["summary"]
        body = (f"Dear Sir/Madam,\n\nPlease find attached the accounts pack for {start.strftime('%B %Y')} "
                f"for tax filing:\n\n"
                f"- Invoices raised: {s['invoices']} (total {s['invoiced_total']:,.2f})\n"
                f"- Payments received: {s['payments']} (total {s['received_total']:,.2f})\n"
                f"- Bills: {s['bills']}\n- Expenses: {s['expenses']}\n\n"
                f"Please let us know if you need any supporting documents.\n\nBest regards,\nAccounts")
        try:
            out = _draft([ca_email], f"Accounts pack for tax filing — {start.strftime('%B %Y')}", body,
                         attachments=[{"filename": f"{period}-{n}", "content": c, "mime_type": "text/csv"}
                                      for n, c in pack["files"].items()])
        except Exception as e:
            out = {"success": False, "error": str(e)}
        record.update(draft_id=out.get("draft_id"), error=out.get("error"))
    else:
        record["error"] = "CA_EMAIL not set -- pack built but not drafted"
    fin["ca_packs"].update_one({"period": period}, {"$set": record}, upsert=True)
    _crm("tasks", {"title": f"Send {start.strftime('%B %Y')} accounts pack to CA",
                   "description": ("Draft with CSVs is ready in " + _from_mailbox()) if record.get("draft_id")
                   else record.get("error") or "", "status": "open", "source": "ca_pack",
                   "due_date": now + timedelta(days=3)})
    return {k: v for k, v in record.items() if k != "_id"}


def run_daily_finance_automation() -> Dict[str, Any]:
    now = datetime.utcnow()
    out: Dict[str, Any] = {"overdue_marked": mark_overdue_invoices(now)}
    out["reminders"] = run_invoice_reminders(now)
    out["reconcile"] = auto_reconcile_payments(now)
    if now.day <= 5:
        out["ca_pack"] = run_monthly_ca_pack(now)
    logger.info("[FinanceAutomation] %s", out)
    return out
