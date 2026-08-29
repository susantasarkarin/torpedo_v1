"""
Backfill account_id on crm_db.opportunities (RFQs) that were logged before
sales/mail_pool_ai.py's domain-fallback fix — 13,052 of 13,059 RFQ
opportunities (99.9%) had no account_id at all, because the old code only
linked an account when the AI explicitly extracted a company name, which
was rare. Without account_id, an RFQ can never appear on that account's
overview page (routers/sales_accounts.py queries opportunities by
account_id) — this is the root cause behind "RFQs not showing up along
with accounts/contacts."

Deterministic only: resolves the RFQ's account via the same domain-derived
naming as the live fix (sender's email domain -> title-cased company name),
skipping free-email-provider domains and RFQs with no traceable sender
email at all. Nothing is guessed beyond what the live code now does for
new RFQs — this makes old data consistent with new behavior, not a new
heuristic.

Usage:
    python backfill_rfq_account_links.py            # dry run, report only
    python backfill_rfq_account_links.py --apply     # write account_id
"""

import argparse
import os
import sys
from typing import Optional

from pymongo import MongoClient
from bson import ObjectId

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
CRM_DB_NAME = os.getenv("CRM_DB_NAME", "crm_db")

_SKIP_DOMAINS = frozenset({
    "gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com",
    "live.com", "aol.com", "icloud.com", "mail.com", "protonmail.com",
    "zoho.com", "yandex.com", "gmx.com", "rediffmail.com", "googlemail.com",
    "cogentixresearch.com", "surveyfieldwork.com",
})


def _company_from_domain(domain: str) -> str:
    return domain.split(".")[0].replace("-", " ").title()


def _resolve_sender_email(opp: dict, gmail_col) -> Optional[str]:
    """Best-effort: the RFQ metadata carries either source_emails[].from or
    a source_email_id to look up. Returns a lowercased email or None."""
    rfq_meta = (opp.get("metadata") or {}).get("rfq") or {}
    source_emails = rfq_meta.get("source_emails") or []
    if source_emails and source_emails[0].get("from"):
        return source_emails[0]["from"].strip().lower()

    source_email_id = rfq_meta.get("source_email_id")
    if source_email_id:
        try:
            doc = gmail_col.find_one({"_id": ObjectId(source_email_id)}, {"from_email": 1})
        except Exception:
            doc = None
        if doc and doc.get("from_email"):
            return doc["from_email"].strip().lower()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    dry_run = not args.apply

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    crm = client[CRM_DB_NAME]
    gmail_col = client["torpedo_gmail"]["email_metadata"]
    opportunities = crm["opportunities"]
    accounts = crm["accounts"]

    query = {
        "$or": [{"stage": "rfq"}, {"metadata.source": "rfq"},
                {"metadata.rfq": {"$exists": True}}],
        "account_id": {"$exists": False},
    }
    candidates = list(opportunities.find(query, {"metadata": 1}))
    print(f"Orphaned RFQ opportunities: {len(candidates)}")

    linked = 0
    unresolvable = 0
    skipped_free_provider = 0
    accounts_created = 0
    accounts_cache = {}  # company_name -> account_id

    for opp in candidates:
        email = _resolve_sender_email(opp, gmail_col)
        if not email or "@" not in email:
            unresolvable += 1
            continue
        domain = email.split("@", 1)[1]
        if not domain or domain in _SKIP_DOMAINS:
            skipped_free_provider += 1
            continue

        company = _company_from_domain(domain)
        if company not in accounts_cache:
            existing = accounts.find_one(
                {"name": {"$regex": f"^{company}$", "$options": "i"}}, {"_id": 1})
            if existing:
                accounts_cache[company] = str(existing["_id"])
            elif not dry_run:
                from datetime import datetime
                now = datetime.utcnow()
                ins = accounts.insert_one({
                    "name": company, "account_type": "client",
                    "metadata": {"source": "rfq_backfill"},
                    "created_at": now, "updated_at": now,
                })
                accounts_cache[company] = str(ins.inserted_id)
                accounts_created += 1
            else:
                accounts_cache[company] = "<would-create>"
                accounts_created += 1

        linked += 1
        if not dry_run:
            opportunities.update_one(
                {"_id": opp["_id"]}, {"$set": {"account_id": accounts_cache[company]}})

    print(f"Resolvable via sender domain: {linked}")
    print(f"  Accounts {'that would be ' if dry_run else ''}created: {accounts_created}")
    print(f"Unresolvable (no sender email on record): {unresolvable}")
    print(f"Skipped (free email provider / our own domain): {skipped_free_provider}")

    if dry_run:
        print("\nNo writes made. Re-run with --apply to write account_id "
              "and create any missing accounts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
