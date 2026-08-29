"""
Backfill account_id on crm_db.opportunities (RFQs) that were logged before
sales/mail_pool_ai.py's account-linking fix — 13,052 of 13,059 RFQ
opportunities (99.9%) had no account_id at all, because the old code only
linked an account when the AI explicitly extracted a company name, which
was rare. Without account_id, an RFQ can never appear on that account's
overview page (routers/sales_accounts.py queries opportunities by
account_id) — this is the root cause behind "RFQs not showing up along
with accounts/contacts."

LINK-ONLY BY DEFAULT: resolves each RFQ's sender-email domain to an
EXISTING account by name and links it there; never fabricates a new one.
An earlier version of this script auto-created a "client" account from
whoever's domain sent one email — which produced real research-industry
names (Ogilvy, Dupont) sitting next to personal ISP webmail (Bellsouth,
Bigpond, Embarqmail) and SaaS notification domains (Mailersend,
Zohomeeting, Sproutsocial) that were never a real client relationship.
See scripts/cleanup_rfq_backfill_accounts.py, which undid that batch.
Pass --allow-create to restore the old create-if-missing behavior (not
recommended without also reviewing the result before it's visible on the
Accounts page — accounts it creates are flagged
metadata.hidden_from_accounts_list so they aren't, until you promote one
you've actually verified).

Usage:
    python backfill_rfq_account_links.py                    # dry run, link-only
    python backfill_rfq_account_links.py --apply             # write account_id (link-only)
    python backfill_rfq_account_links.py --apply --allow-create  # also create new accounts (flagged hidden)
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
    parser.add_argument("--allow-create", action="store_true",
                         help="Create a new (flagged-hidden) account when no existing one "
                              "matches the sender domain, instead of leaving the RFQ unlinked.")
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
                {"name": {"$regex": f"^{company}$", "$options": "i"},
                 "metadata.hidden_from_accounts_list": {"$ne": True}}, {"_id": 1})
            if existing:
                accounts_cache[company] = str(existing["_id"])
            elif args.allow_create:
                # Off by default — see module docstring. A domain-derived
                # name manufactures a "client" out of whoever happened to
                # send one email (personal ISP webmail, SaaS notification
                # senders), not a reviewed prospect. Only creates when you
                # explicitly pass --allow-create, and even then flagged so
                # it's excluded from the default Accounts list, requiring
                # a human to promote it once confirmed real.
                if not dry_run:
                    from datetime import datetime
                    now = datetime.utcnow()
                    ins = accounts.insert_one({
                        "name": company, "account_type": "client",
                        "metadata": {"source": "rfq_backfill",
                                     "hidden_from_accounts_list": True},
                        "created_at": now, "updated_at": now,
                    })
                    accounts_cache[company] = str(ins.inserted_id)
                else:
                    accounts_cache[company] = "<would-create>"
                accounts_created += 1
            else:
                unresolvable += 1
                continue

        linked += 1
        if not dry_run:
            opportunities.update_one(
                {"_id": opp["_id"]}, {"$set": {"account_id": accounts_cache[company]}})

    print(f"Resolvable via sender domain: {linked}")
    print(f"  Accounts {'that would be ' if dry_run else ''}created: {accounts_created} "
          f"{'(--allow-create was off, so this should be 0)' if not args.allow_create else ''}")
    print(f"Unresolvable (no sender email on record, or no existing account matched "
          f"and --allow-create was off): {unresolvable}")
    print(f"Skipped (free email provider / our own domain): {skipped_free_provider}")

    if dry_run:
        print("\nNo writes made. Re-run with --apply to write account_id.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
