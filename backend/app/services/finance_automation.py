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
  4. CA pack        on the 5th (CA_PACK_DAY): last month's invoices, payments
                    received, bills and expenses as CSVs, SENT to CA_EMAIL
                    (owner, 2026-09-29; CA_PACK_SEND=false makes it a draft).
  5. Statements     once a month, per client: every pending invoice in one
                    statement to the client's billing address -- drafts until
                    FINANCE_STATEMENTS_SEND=true (statuses come from an unsynced
                    Zoho export, so a person checks the first ones).

Reminders are drafts a person sends; the CA pack is sent.
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


def _send(to: List[str], subject: str, body_html: str, body_plain: str,
          attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Send (not draft) from the finance mailbox. Attachments: content as bytes."""
    from app.services.gmail_workspace_service import GmailWorkspaceService
    svc = GmailWorkspaceService(mongo_uri=os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                                db_name="torpedo_gmail")
    svc.load_service_account()
    sender = _from_mailbox()
    return svc.send_email(from_email=sender, to=to, subject=subject, body_html=body_html, body_plain=body_plain,
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
    """The highest reminder milestone reached and not yet covered, if any.

    A reminder at milestone M also covers every lower milestone: an invoice
    first seen at 77 days overdue gets one 30-day reminder, not a 15-, 7- and
    1-day one on the following days (seen live on the first run, 2026-09-28).
    """
    covered = max((m for m in already_sent if m is not None), default=0)
    reached = [m for m in REMINDER_MILESTONES if days_overdue >= m and m > covered]
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
    for inv in invoices:  # the CA needs the client, not an internal id
        inv["customer_name"] = _customer_name(fin, inv.get("customer_id"))
    payments = rows("payments_received", "payment_date")
    bills = rows("bills", "bill_date")
    expenses = rows("expenses", "expense_date")
    files = {
        "invoices.csv": _csv(invoices, ["invoice_number", "invoice_date", "due_date", "customer_name",
                                        "currency_code", "subtotal", "tax_amount", "tds_amount",
                                        "total_amount", "amount_paid", "balance_due", "status", "gstin",
                                        "po_reference"]),
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


CA_PACK_DAY = int(os.getenv("CA_PACK_DAY", "5"))


def _customer_name(fin, customer_id) -> str:
    try:
        c = fin["customers"].find_one({"_id": ObjectId(str(customer_id))}, {"name": 1, "company_name": 1})
    except Exception:
        c = None
    return ((c or {}).get("company_name") or (c or {}).get("name") or "").strip()


def run_monthly_ca_pack(now: Optional[datetime] = None) -> Dict[str, Any]:
    """On the 5th (owner, 2026-09-29): last month's invoices -- and payments,
    bills, expenses -- SENT to the CA as CSVs. Runs on the first daily run on or
    after CA_PACK_DAY, once per month."""
    now = now or datetime.utcnow()
    end = datetime(now.year, now.month, 1)
    start = datetime(end.year - 1, 12, 1) if end.month == 1 else datetime(end.year, end.month - 1, 1)
    period = start.strftime("%Y-%m")
    if now.day < CA_PACK_DAY:
        return {"skipped": f"the {period} pack goes on day {CA_PACK_DAY}"}
    fin = _fin()
    ca_email = (os.getenv("CA_EMAIL") or "").strip()
    existing = fin["ca_packs"].find_one({"period": period})
    # Done once sent; without a CA email, noted once and retried only after
    # CA_EMAIL is configured (no daily task spam).
    if existing and (existing.get("message_id") or existing.get("draft_id") or not ca_email):
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
        files = [{"filename": f"{period}-{n}", "content": c.encode("utf-8"), "mime_type": "text/csv"}
                 for n, c in pack["files"].items()]
        subject = f"Accounts pack for tax filing — {start.strftime('%B %Y')}"
        try:
            if os.getenv("CA_PACK_SEND", "true").strip().lower() == "true":
                out = _send([ca_email], subject, body.replace("\n", "<br>"), body, attachments=files)
                record.update(message_id=out.get("message_id"), sent_at=now if out.get("success") else None)
            else:
                out = _draft([ca_email], subject, body, attachments=files)
                record.update(draft_id=out.get("draft_id"))
        except Exception as e:
            out = {"success": False, "error": str(e)}
        record["error"] = out.get("error")
    else:
        record["error"] = "CA_EMAIL not set -- pack built but not sent"
    fin["ca_packs"].update_one({"period": period}, {"$set": record}, upsert=True)
    if record.get("error") or not record.get("sent_at"):
        _crm("tasks", {"title": f"{start.strftime('%B %Y')} accounts pack for the CA",
                       "description": ("Draft with CSVs is ready in " + _from_mailbox()) if record.get("draft_id")
                       else record.get("error") or "", "status": "open", "source": "ca_pack",
                       "due_date": now + timedelta(days=3)})
    return {k: v for k, v in record.items() if k != "_id"}


# ---------------------------------------------------------------------------
# 5. monthly statement of pending invoices, per client
# ---------------------------------------------------------------------------
STATEMENT_DAY = int(os.getenv("FINANCE_STATEMENT_DAY", "1"))
_BILLING_HINT = re.compile(r"account|finance|billing|payable|invoice", re.I)


def statement_recipient(fin, customer: Dict[str, Any]) -> Optional[str]:
    """The client's billing address: its own email, else an accounts/finance
    address recorded on another customer entry for the same company (Finance
    holds one entry per contact, e.g. 'Accounts Payable | Hansa Research Group')."""
    email = (customer.get("email") or "").strip().lower()
    if email and "@" in email and not email.endswith(("surveyfieldwork.com", "cogentixresearch.com")):
        return email
    first = re.split(r"[\s|(\-]", (customer.get("company_name") or customer.get("name") or "").strip())[0]
    if len(first) < 4:
        return None
    best = None
    for c in fin["customers"].find({"name": {"$regex": re.escape(first), "$options": "i"},
                                    "email": {"$regex": "@"}}, {"name": 1, "email": 1}):
        e = c["email"].strip().lower()
        if e.endswith(("surveyfieldwork.com", "cogentixresearch.com", "gmail.com")):
            continue
        if _BILLING_HINT.search(c.get("name") or "") or _BILLING_HINT.search(e.split("@")[0]):
            return e
        best = best or e
    return best


def statement_html(customer_name: str, invoices: List[Dict[str, Any]], now: datetime) -> Dict[str, str]:
    rows, totals = [], {}
    for inv in sorted(invoices, key=lambda i: _as_dt(i.get("invoice_date")) or now):
        cur = inv.get("currency_code") or inv.get("currency") or ""
        bal = _balance(inv)
        totals[cur] = totals.get(cur, 0.0) + bal
        due = _as_dt(inv.get("due_date"))
        overdue = (now - due).days if due and due < now else 0
        rows.append((inv.get("invoice_number") or "", (_as_dt(inv.get("invoice_date")) or now).strftime("%d %b %Y"),
                     due.strftime("%d %b %Y") if due else "", cur,
                     float(inv.get("total_amount") or inv.get("total") or 0), bal, overdue,
                     inv.get("po_reference") or ""))
    th = "".join(f"<th style='text-align:left;padding:4px 8px;border-bottom:1px solid #ccc'>{h}</th>" for h in
                 ("Invoice", "Date", "Due", "Currency", "Amount", "Balance", "Days overdue", "PO"))
    tr = "".join("<tr>" + "".join(f"<td style='padding:4px 8px'>{v:,.2f}</td>" if isinstance(v, float)
                                  else f"<td style='padding:4px 8px'>{v}</td>" for v in r) + "</tr>" for r in rows)
    tot = ", ".join(f"{c} {v:,.2f}" for c, v in totals.items())
    html = (f"<p>Dear {customer_name},</p><p>Please find below the statement of invoices pending as on "
            f"{now.strftime('%d %B %Y')}.</p><table style='border-collapse:collapse;font-size:13px'>"
            f"<tr>{th}</tr>{tr}</table><p><b>Total outstanding: {tot}</b></p><p>If any of these has been "
            f"paid, please share the remittance details so we can reconcile it.</p><p>Best regards,<br>Accounts</p>")
    plain = (f"Dear {customer_name},\n\nStatement of invoices pending as on {now.strftime('%d %B %Y')}:\n\n" +
             "\n".join(f"{r[0]}  {r[1]}  due {r[2]}  {r[3]} {r[5]:,.2f} outstanding" for r in rows) +
             f"\n\nTotal outstanding: {tot}\n\nIf any of these has been paid, please share the remittance "
             f"details so we can reconcile it.\n\nBest regards,\nAccounts")
    return {"subject": f"Statement of pending invoices — {customer_name} — {now.strftime('%B %Y')}",
            "html": html, "plain": plain, "total": tot}


def run_client_statements(now: Optional[datetime] = None) -> Dict[str, int]:
    """Owner, 2026-09-29: a consolidated report of all pending invoices sent to
    each client individually. Once a month, on or after FINANCE_STATEMENT_DAY.
    Drafts unless FINANCE_STATEMENTS_SEND=true -- invoice statuses come from a
    Zoho export that is not synced yet, so a person checks the first ones."""
    now = now or datetime.utcnow()
    period = now.strftime("%Y-%m")
    stats = {"clients": 0, "drafted": 0, "sent": 0, "no_email": 0, "errors": 0, "already_done": 0}
    if now.day < STATEMENT_DAY:
        return stats
    fin = _fin()
    send = os.getenv("FINANCE_STATEMENTS_SEND", "false").strip().lower() == "true"
    by_customer: Dict[str, List[Dict[str, Any]]] = {}
    for inv in fin["invoices"].find({"status": {"$in": list(OPEN_STATUSES)}, "is_deleted": {"$ne": True}}):
        if _balance(inv) > 0 and inv.get("customer_id"):
            by_customer.setdefault(str(inv["customer_id"]), []).append(inv)
    for cid, invs in by_customer.items():
        stats["clients"] += 1
        if fin["statements"].find_one({"customer_id": cid, "period": period}):
            stats["already_done"] += 1
            continue
        try:
            customer = fin["customers"].find_one({"_id": ObjectId(cid)}) or {}
        except Exception:
            customer = {}
        name = customer.get("company_name") or customer.get("name") or "Client"
        st = statement_html(name, invs, now)
        to = statement_recipient(fin, customer)
        record = {"customer_id": cid, "customer_name": name, "period": period, "created_at": now,
                  "invoice_ids": [str(i["_id"]) for i in invs], "total": st["total"], "to": to}
        if not to:
            stats["no_email"] += 1
            record["error"] = "no billing email on file"
            _crm("tasks", {"title": f"Statement of pending invoices for {name}: no billing email on file",
                           "description": st["plain"], "status": "open", "source": "finance_statement",
                           "due_date": now + timedelta(days=2)})
        else:
            try:
                out = (_send([to], st["subject"], st["html"], st["plain"]) if send
                       else _draft([to], st["subject"], st["plain"]))
            except Exception as e:
                out = {"success": False, "error": str(e)}
            if out.get("success"):
                stats["sent" if send else "drafted"] += 1
            else:
                stats["errors"] += 1
            record.update(mode="sent" if send else "draft", message_id=out.get("message_id"),
                          draft_id=out.get("draft_id"), error=out.get("error"))
        fin["statements"].update_one({"customer_id": cid, "period": period}, {"$set": record}, upsert=True)
    return stats


DRAFT_NUDGE_AFTER_DAYS = 3
DRAFT_NUDGE_MAX_AGE_DAYS = 60


def flag_unsent_drafts(now: Optional[datetime] = None) -> int:
    """A CRM task for each invoice left in draft.

    Reminders, overdue marking and the CA pack only see invoices that were
    sent. Invoices raised on project close are drafts, and nothing sends them:
    in the 2026-09-28 replay of the whole mail history every close invoice sat
    in draft for good and no later finance step ever saw it. One task per
    draft, once; drafts older than DRAFT_NUDGE_MAX_AGE_DAYS are left alone."""
    now = now or datetime.utcnow()
    fin = _fin()
    n = 0
    for inv in fin["invoices"].find({
            "status": "draft", "is_deleted": {"$ne": True}, "draft_nudged_at": {"$exists": False},
            "created_at": {"$lte": now - timedelta(days=DRAFT_NUDGE_AFTER_DAYS),
                           "$gte": now - timedelta(days=DRAFT_NUDGE_MAX_AGE_DAYS)}}).limit(200):
        number = inv.get("invoice_number") or str(inv["_id"])
        _crm("tasks", {
            "title": f"Invoice {number} is still a draft — review and send it",
            "description": (f"{inv.get('customer_name') or ''} "
                            f"{inv.get('currency_code') or inv.get('currency') or ''} "
                            f"{inv.get('total_amount') or ''}").strip(),
            "due_date": now, "status": "open", "source": "finance_automation",
            "linked_object_type": "invoice", "linked_object_id": str(inv["_id"])})
        fin["invoices"].update_one({"_id": inv["_id"]}, {"$set": {"draft_nudged_at": now}})
        n += 1
    return n


def run_daily_finance_automation() -> Dict[str, Any]:
    now = datetime.utcnow()
    out: Dict[str, Any] = {"overdue_marked": mark_overdue_invoices(now)}
    out["unsent_drafts_flagged"] = flag_unsent_drafts(now)
    out["reminders"] = run_invoice_reminders(now)
    out["reconcile"] = auto_reconcile_payments(now)
    out["ca_pack"] = run_monthly_ca_pack(now)          # sends on/after the 5th, once a month
    out["statements"] = run_client_statements(now)     # once a month per client
    logger.info("[FinanceAutomation] %s", out)
    return out
