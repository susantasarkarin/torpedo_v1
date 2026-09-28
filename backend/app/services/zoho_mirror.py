"""
Read-only mirror of Zoho Books into finance_db (zoho_invoices,
zoho_contacts, zoho_payments), keyed by Zoho's own ids.

Zoho Books is the system of record (owner, 2026-09-28); the mirror lets the
dashboard and reminders read its figures without calling Zoho on every page
load. Nothing is ever written to Zoho from here.
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)

INVOICE_FIELDS = ("invoice_id", "invoice_number", "customer_id", "customer_name", "status", "date",
                  "due_date", "currency_code", "total", "balance", "reference_number", "last_payment_date",
                  "email", "is_emailed", "created_time", "last_modified_time")
CONTACT_FIELDS = ("contact_id", "contact_name", "company_name", "contact_type", "email", "gst_no",
                  "gst_treatment", "place_of_contact", "currency_code", "outstanding_receivable_amount",
                  "status", "last_modified_time")
PAYMENT_FIELDS = ("payment_id", "payment_number", "customer_id", "customer_name", "date", "amount",
                  "unused_amount", "currency_code", "reference_number", "payment_mode", "invoice_numbers",
                  "last_modified_time")


def _client():
    from pymongo import MongoClient
    return MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)


def _mirror(col, rows, key, fields, now) -> int:
    from pymongo import UpdateOne
    ops = [UpdateOne({"_id": r[key]}, {"$set": {**{f: r.get(f) for f in fields}, "mirrored_at": now}}, upsert=True)
           for r in rows if r.get(key)]
    for i in range(0, len(ops), 500):
        col.bulk_write(ops[i:i + 500], ordered=False)
    return len(ops)


def run_mirror() -> Dict[str, Any]:
    from integrations import zoho_books as zb
    if not zb.configured():
        return {"skipped": "Zoho Books not connected", "missing": zb.missing_settings()}
    fin = _client()["finance_db"]
    now = datetime.utcnow()
    out = {
        "invoices": _mirror(fin["zoho_invoices"], zb.invoices(), "invoice_id", INVOICE_FIELDS, now),
        "contacts": _mirror(fin["zoho_contacts"], zb.contacts(), "contact_id", CONTACT_FIELDS, now),
        "payments": _mirror(fin["zoho_payments"], zb.customer_payments(), "payment_id", PAYMENT_FIELDS, now),
    }
    fin["zoho_sync_state"].update_one({"_id": "mirror"}, {"$set": {"last_run_at": now, **out}}, upsert=True)
    logger.info("[ZohoMirror] %s", out)
    return out
