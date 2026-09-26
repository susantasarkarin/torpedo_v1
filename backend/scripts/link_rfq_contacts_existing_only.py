"""
Link RFQ opportunities to an already-existing CRM contact, by the source
email's from_email (2026-09-26 P1 fix, step 1 of 2).

Deliberately does NOT create new contacts -- see
list_rfq_contacts_to_create.py for the report of the ~1,443 opportunities
that would need one, held for a separate decision. This script only ever
sets contact_id (and account_id, if the matched contact has one) on an
opportunity that currently has none; it never touches any other field, and
never writes to the contacts collection.

Idempotent -- only matches contact_id: None, so a second run is a no-op.
Writes a JSON backup of every record it is about to touch before writing.

Usage:
    python scripts/link_rfq_contacts_existing_only.py --dry-run
    python scripts/link_rfq_contacts_existing_only.py
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--backup-path", default=None)
    args = parser.parse_args()

    from bson import ObjectId
    from database import get_db_manager
    from db_pools import get_db
    from app.services import crm_service

    opps = get_db_manager().client["crm_db"]["opportunities"]
    mail = get_db("torpedo_gmail")["email_metadata"]

    query = {"contact_id": None, "metadata.rfq.source_email_id": {"$nin": [None, ""]}}
    cursor = opps.find(query, {"metadata.rfq.source_email_id": 1, "account_id": 1})
    if args.limit:
        cursor = cursor.limit(args.limit)
    docs = list(cursor)
    log.info("candidates (contact_id is None, has a source_email_id): %d", len(docs))

    backup_path = args.backup_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"link_rfq_contacts.backup.{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json")
    backup = []

    stats = {"linked": 0, "no_matching_contact": 0, "no_email_found": 0, "no_sender_address": 0}
    for d in docs:
        eid = d["metadata"]["rfq"].get("source_email_id")
        try:
            email_doc = mail.find_one({"_id": ObjectId(eid)}, {"from_email": 1})
        except Exception:
            email_doc = None
        if not email_doc:
            stats["no_email_found"] += 1
            continue
        sender = (email_doc.get("from_email") or "").strip().lower()
        if not sender:
            stats["no_sender_address"] += 1
            continue

        contact = crm_service.find_contact_by_email(sender)
        if not contact:
            stats["no_matching_contact"] += 1
            continue

        update = {"contact_id": contact["_id"]}
        if not d.get("account_id") and contact.get("account_id"):
            update["account_id"] = contact["account_id"]

        backup.append({"_id": str(d["_id"]), "contact_id_before": None,
                       "account_id_before": d.get("account_id"), "matched_email": sender})
        stats["linked"] += 1
        if args.dry_run:
            continue
        opps.update_one({"_id": d["_id"]}, {"$set": update})

    if backup and not args.dry_run:
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup, f, indent=2, default=str)
        log.info("wrote pre-change backup for %d records to %s", len(backup), backup_path)

    log.info("%s: %s", "DRY RUN" if args.dry_run else "DONE", stats)


if __name__ == "__main__":
    main()
