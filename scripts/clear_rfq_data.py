"""
Delete inbound RFQ-tagged opportunities from crm_db.opportunities, and reset
the mail-pool RFQ-scan ledger so backend/sales/mail_pool_ai.py's
deep_scan_sender_rfqs() re-reads every sender from scratch on the next
resync (see backend/routers/rfq.py: POST /rfq/resync-all).

RUN scripts/backup_rfq_opportunities.py FIRST. This is destructive.

Scope / safety guards:
  - Inbound RFQs only. Any opportunity with metadata.rfq.direction ==
    "outbound" (the manually-entered to-vendor RFQs) is left untouched —
    the mail-pool rebuild only regenerates inbound RFQs, so an outbound one
    deleted here can never come back automatically.
  - Any RFQ that already has a linked estimate_id or invoice_id in
    finance_db is SKIPPED, not deleted, so a real financial document never
    ends up pointing at a dead opportunity. Skipped RFQs are reported, not
    silently dropped.
  - Does NOT touch email_metadata.ai_analysis stamps — only the per-sender
    rfq_scan ledger. A full re-classification of the mail pool is out of
    scope and far more expensive than an RFQ-only rebuild.

Usage:
    python scripts/clear_rfq_data.py                    # dry run (default)
    python scripts/clear_rfq_data.py --yes-really-delete # actually deletes
"""
import argparse
import os

import pymongo
from bson import ObjectId

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

client = pymongo.MongoClient(MONGO_URI)
db = client["email_automation"]
crm_db = client["crm_db"]
finance_db = client["finance_db"]

opportunities_col = crm_db["opportunities"]
sender_analysis_col = db["mail_sender_analysis"]
estimates_col = finance_db["estimates"]
invoices_col = finance_db["invoices"]

# Same base predicate spine_rfq._rfq_query() uses, restricted to inbound
# (absent direction == inbound, matching spine_rfq.py's own convention).
RFQ_INBOUND_PREDICATE = {
    "$or": [
        {"stage": "rfq"},
        {"metadata.source": "rfq"},
        {"metadata.rfq": {"$exists": True}},
    ],
    "metadata.rfq.direction": {"$ne": "outbound"},
}


def _has_linked_finance_doc(opportunity_id: str) -> str | None:
    """Return a reason string if this opportunity has a linked estimate or
    invoice (financial records are never deleted by this script), else None."""
    est = estimates_col.find_one({
        "$or": [{"opportunity_id": opportunity_id}, {"rfq_object_id": opportunity_id}]
    }, {"estimate_number": 1})
    if est:
        return f"linked to estimate {est.get('estimate_number', est['_id'])}"

    inv = invoices_col.find_one({
        "$or": [{"opportunity_id": opportunity_id}, {"rfq_object_id": opportunity_id}]
    }, {"invoice_number": 1})
    if inv:
        return f"linked to invoice {inv.get('invoice_number', inv['_id'])}"

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--yes-really-delete", action="store_true",
        help="Actually delete. Without this flag, only prints what would happen.",
    )
    args = parser.parse_args()
    dry_run = not args.yes_really_delete

    opportunities = list(opportunities_col.find(RFQ_INBOUND_PREDICATE))
    print(f"Found {len(opportunities)} inbound RFQ-tagged opportunities")

    to_delete = []
    skipped = []
    sender_emails = set()

    for opp in opportunities:
        opp_id = str(opp["_id"])
        reason = _has_linked_finance_doc(opp_id)
        if reason:
            skipped.append((opp_id, opp.get("title"), reason))
            continue
        to_delete.append(opp)
        rfq_payload = (opp.get("metadata") or {}).get("rfq") or {}
        # source_email_id doesn't carry the sender's address; resolve via the
        # linked contact instead so the scan-ledger reset can target the
        # right sender doc.
        contact_id = opp.get("contact_id")
        if contact_id:
            contact = crm_db["contacts"].find_one({"_id": ObjectId(contact_id)}, {"email": 1})
            if contact and contact.get("email"):
                sender_emails.add(contact["email"].strip().lower())

    print(f"\nWould delete: {len(to_delete)}")
    for opp in to_delete[:20]:
        print(f"  - {opp.get('title', '(untitled)')} [{opp['_id']}]")
    if len(to_delete) > 20:
        print(f"  ... and {len(to_delete) - 20} more")

    print(f"\nSkipped (linked to finance records, NOT deleted): {len(skipped)}")
    for opp_id, title, reason in skipped:
        print(f"  - {title!r} [{opp_id}]: {reason}")

    print(f"\nSender rfq_scan ledgers that would be reset: {len(sender_emails)}")

    if dry_run:
        print("\nDRY RUN — nothing deleted. Re-run with --yes-really-delete to apply.")
        return

    if not to_delete:
        print("\nNothing to delete.")
        return

    delete_ids = [opp["_id"] for opp in to_delete]
    result = opportunities_col.delete_many({"_id": {"$in": delete_ids}})
    print(f"\nDeleted {result.deleted_count} opportunities")

    if sender_emails:
        reset_result = sender_analysis_col.update_many(
            {"_id": {"$in": list(sender_emails)}},
            {"$unset": {"rfq_scan.ledger": "", "rfq_scan.last_scanned_date": ""}},
        )
        print(f"Reset rfq_scan ledger for {reset_result.modified_count} senders")

    print("\nDone. Run POST /rfq/resync-all (in batches) to rebuild from the mail pool.")


if __name__ == "__main__":
    main()
