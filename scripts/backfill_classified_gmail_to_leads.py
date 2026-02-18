"""
BACKFILL SCRIPT: Process all existing classified_gmail records
=============================================================
Runs through every document in the classified_gmail collection and:
1. AUTO-MOVE: CLIENT emails where we have an existing sent-email relationship → leads_raw
2. NAME FIX: Corrects first_name/last_name on existing leads_raw records created from classified_gmail

Run from project root:
    python scripts/backfill_classified_gmail_to_leads.py

Flags:
    --dry-run       Print what would happen, make no DB changes
    --limit N       Only process the first N records (default: all)
    --segment X     Only process a specific segment (default: CLIENT)
"""

import os
import sys
import argparse
from datetime import datetime

# ── path setup so we can import backend modules ──────────────────────────────
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
backend_dir = os.path.join(project_root, "backend")
sys.path.insert(0, project_root)
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, ".env"))

from pymongo import MongoClient
from bson import ObjectId
from leads.gmail_leads_service import extract_name_from_email

# ── Mongo setup ───────────────────────────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(MONGO_URI)

email_db = mongo_client["email_automation"]
torpedo_gmail_db = mongo_client["torpedo_gmail"]

classified_gmail_col = email_db["classified_gmail"]
leads_raw_col = email_db["leads_raw"]
email_metadata_col = torpedo_gmail_db["email_metadata"]


# ── helpers ───────────────────────────────────────────────────────────────────

def has_sent_email_to(email_address: str) -> bool:
    """Return True if we have ever sent an email to this address."""
    if not email_address:
        return False
    email_lower = email_address.lower().strip()
    return email_metadata_col.find_one({
        "direction": "sent",
        "$or": [
            {"to_email": email_lower},
            {"to_email": {"$regex": email_lower, "$options": "i"}},
            {"recipients": {"$elemMatch": {"$regex": email_lower, "$options": "i"}}}
        ]
    }) is not None


def already_a_lead(email_address: str) -> bool:
    """Return True if a leads_raw entry for this email already exists."""
    return leads_raw_col.find_one({"email": email_address.lower().strip()}) is not None


# ── main backfill ──────────────────────────────────────────────────────────────

def run_backfill(dry_run: bool = False, limit: int = 0, segment_filter: str = "CLIENT"):
    query = {
        "segment": segment_filter,
        "moved_to_leads": {"$ne": True},   # skip already-moved records
        "deleted": {"$ne": True}
    }

    total_in_db = classified_gmail_col.count_documents(query)
    cursor = classified_gmail_col.find(query)
    if limit:
        cursor = cursor.limit(limit)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Backfill classified_gmail → leads_raw")
    print(f"  Segment  : {segment_filter}")
    print(f"  Matching : {total_in_db} records (limit={limit or 'all'})")
    print("─" * 60)

    moved = 0
    skipped_no_rel = 0
    skipped_dup = 0
    errors = 0

    for classified in cursor:
        doc_id = classified["_id"]
        sender_email = (classified.get("sender_email") or "").strip()
        sender_name = classified.get("sender_name") or ""

        if not sender_email:
            print(f"  [SKIP]  _id={doc_id}  — no sender_email")
            skipped_no_rel += 1
            continue

        # Only auto-move if we have an existing relationship
        if not has_sent_email_to(sender_email):
            print(f"  [SKIP]  {sender_email}  — no prior sent email")
            skipped_no_rel += 1
            continue

        # Skip duplicates
        if already_a_lead(sender_email):
            print(f"  [DUP]   {sender_email}  — already in leads_raw")
            skipped_dup += 1
            if not dry_run:
                # Mark as moved so we don't re-process
                classified_gmail_col.update_one(
                    {"_id": doc_id},
                    {"$set": {"moved_to_leads": True, "moved_by": "backfill", "moved_at": datetime.utcnow()}}
                )
            continue

        # Extract name properly
        full_name, first_name, last_name = extract_name_from_email(sender_email, sender_name)

        contacts = classified.get("contacts", [])
        lead_doc = {
            "source": "classified_gmail",
            "email": sender_email.lower(),
            "full_name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "title": next((c.get("title") for c in contacts if c.get("title")), ""),
            "company_name": next((c.get("company") for c in contacts if c.get("company")), ""),
            "segment": "CLIENT",
            "category": classified.get("category"),
            "confidence_score": classified.get("confidence_score", 0),
            "email_summary": classified.get("summary"),
            "email_sentiment": classified.get("sentiment"),
            "classification_segment": segment_filter,
            "classified_email_id": classified.get("email_id"),
            "contacts": contacts,
            "stage": "new",
            "created_at": datetime.utcnow(),
            "created_from": "classified_gmail",
            "auto_moved": True,
            "notes": "Backfill: Existing email relationship detected"
        }

        print(f"  [MOVE]  {sender_email}  →  leads_raw  (name: {full_name!r})")

        if not dry_run:
            try:
                result = leads_raw_col.insert_one(lead_doc)
                lead_id = str(result.inserted_id)

                classified_gmail_col.update_one(
                    {"_id": doc_id},
                    {
                        "$set": {
                            "moved_to_leads": True,
                            "moved_at": datetime.utcnow(),
                            "moved_by": "backfill",
                            "lead_id": lead_id,
                            "auto_moved": True
                        }
                    }
                )
                moved += 1
            except Exception as e:
                print(f"  [ERROR] {sender_email}  — {e}")
                errors += 1
        else:
            moved += 1

    print("─" * 60)
    print(f"{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Moved   : {moved}")
    print(f"  No rel  : {skipped_no_rel}")
    print(f"  Dups    : {skipped_dup}")
    print(f"  Errors  : {errors}")


# ── name-fix pass: repair existing leads_raw records with bad names ────────────

def fix_existing_lead_names(dry_run: bool = False):
    """
    For leads already in leads_raw that came from classified_gmail,
    re-parse first_name / last_name from the email address if the stored name
    looks wrong (empty, equals full email, or only one word when email has dots).
    """
    query = {"source": "classified_gmail", "email": {"$exists": True, "$ne": ""}}
    total = leads_raw_col.count_documents(query)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Name-fix pass on existing leads_raw ({total} records)")
    print("─" * 60)

    fixed = 0
    for lead in leads_raw_col.find(query):
        email = lead.get("email", "")
        current_name = lead.get("full_name", "")
        sender_name = lead.get("full_name", "")

        full_name, first_name, last_name = extract_name_from_email(email, sender_name)

        # Only update if names actually differ
        if (full_name != current_name or
                first_name != lead.get("first_name", "") or
                last_name != lead.get("last_name", "")):

            print(f"  [FIX]  {email}  old={current_name!r}  new={full_name!r}")
            if not dry_run:
                leads_raw_col.update_one(
                    {"_id": lead["_id"]},
                    {"$set": {
                        "full_name": full_name,
                        "first_name": first_name,
                        "last_name": last_name,
                        "name_fixed_at": datetime.utcnow()
                    }}
                )
            fixed += 1

    print("─" * 60)
    print(f"  Fixed: {fixed} records")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill classified_gmail to leads_raw")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without writing")
    parser.add_argument("--limit", type=int, default=0, help="Max records to process (0=all)")
    parser.add_argument("--segment", default="CLIENT", help="Segment filter (default: CLIENT)")
    parser.add_argument("--fix-names-only", action="store_true", help="Only run the name-fix pass")
    args = parser.parse_args()

    if args.fix_names_only:
        fix_existing_lead_names(dry_run=args.dry_run)
    else:
        run_backfill(dry_run=args.dry_run, limit=args.limit, segment_filter=args.segment)
        fix_existing_lead_names(dry_run=args.dry_run)
