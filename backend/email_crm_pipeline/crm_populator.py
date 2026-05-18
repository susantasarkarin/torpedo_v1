"""
crm_populator.py — Task 2: Deduplication & CRM Population
===========================================================

Reads extractions from email_crm_extractions, deduplicates, and upserts
records into the existing CRM collections:
  - email_automation.contacts       (upsert on email)
  - email_automation.sales_accounts (upsert on normalized_name + country)
  - email_automation.rfqs           (upsert on contact_email + subject_key + month)

Job-change signals are recorded in email_automation.contact_history.

Usage:
    python -m backend.email_crm_pipeline.crm_populator
    python -m backend.email_crm_pipeline.crm_populator --dry-run
    python -m backend.email_crm_pipeline.crm_populator --since 2024-01-01
"""

import sys
import os
import re
import json
import logging
import argparse
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import ReturnDocument

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_collection
from email_crm_pipeline.config import (
    DB_CRM,
    COL_EMAIL_EXTRACTIONS, COL_CONTACTS, COL_SALES_ACCOUNTS,
    COL_RFQS, COL_CONTACT_HISTORY, COL_VENDORS, COL_FINANCE_LOG,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Company name normalisation
# ---------------------------------------------------------------------------

_SUFFIX_RE = re.compile(
    r"\b(ltd|limited|inc|incorporated|corp|corporation|pvt|private|"
    r"llc|llp|gmbh|ag|plc|co|company|group|holdings|international)\b\.?",
    re.IGNORECASE,
)

def normalize_company_name(name: Optional[str]) -> str:
    """Lower-case and strip common legal suffixes for dedup key."""
    if not name:
        return ""
    cleaned = _SUFFIX_RE.sub("", name)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


# ---------------------------------------------------------------------------
# RFQ ID generator
# ---------------------------------------------------------------------------

def next_rfq_id(rfqs_col: Any) -> str:
    """Generate the next sequential RFQ-YYYY-NNNN identifier."""
    year = datetime.now(timezone.utc).year
    prefix = f"RFQ-{year}-"
    last = rfqs_col.find_one(
        {"rfq_id": {"$regex": f"^{prefix}"}},
        sort=[("rfq_id", -1)],
    )
    if last:
        try:
            seq = int(last["rfq_id"].split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


# ---------------------------------------------------------------------------
# Contact upsert
# ---------------------------------------------------------------------------

def upsert_contact(extraction: dict, contacts_col: Any, dry_run: bool = False) -> Optional[str]:
    """
    Upsert a contact record from extraction data.
    Returns the contact's string _id, or None if the extraction has no email.
    """
    contact_data = extraction.get("contact", {})
    email = (contact_data.get("email") or "").strip().lower()
    if not email:
        return None

    now = datetime.now(timezone.utc)

    set_fields = {
        "updatedAt": now,
        "last_seen_date": now,
    }
    # Only overwrite non-null values from the extraction
    if contact_data.get("name"):
        parts = contact_data["name"].rsplit(" ", 1)
        set_fields["firstName"] = parts[0]
        set_fields["lastName"] = parts[1] if len(parts) > 1 else ""
    if contact_data.get("designation"):
        set_fields["designation"] = contact_data["designation"]
    if contact_data.get("company_name"):
        set_fields["company"] = contact_data["company_name"]
    if contact_data.get("country"):
        set_fields["country"] = contact_data["country"]
    if contact_data.get("phone"):
        set_fields["phone"] = contact_data["phone"]
    if contact_data.get("linkedin"):
        set_fields["linkedin"] = contact_data["linkedin"]

    # Tag by email_type
    email_type = extraction.get("email_type", "unknown")
    tag_map = {
        "vendor": "vendor",
        "finance": "finance",
        "client_rfq": "client",
        "client_general": "client",
    }
    tag = tag_map.get(email_type)

    set_on_insert = {
        "email": email,
        "createdAt": now,
        "first_seen_date": now,
        "source": "email_pipeline",
        "tags": [tag] if tag else [],
    }

    if not dry_run:
        result = contacts_col.find_one_and_update(
            {"email": email},
            {
                "$set": set_fields,
                "$setOnInsert": set_on_insert,
                "$addToSet": {"tags": tag} if tag else {},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        contact_id = str(result["_id"]) if result else None
    else:
        existing = contacts_col.find_one({"email": email})
        contact_id = str(existing["_id"]) if existing else "dry_run_id"
        log.info("[DRY-RUN] Would upsert contact: %s (%s)", email, set_fields.get("company", "?"))

    return contact_id


# ---------------------------------------------------------------------------
# Account (sales_account) upsert
# ---------------------------------------------------------------------------

def upsert_account(extraction: dict, accounts_col: Any, dry_run: bool = False) -> Optional[str]:
    """
    Upsert a sales_account record keyed on (normalized_company_name, country).
    Returns the account's string _id.
    """
    account_data = extraction.get("account", {})
    raw_name = account_data.get("company_name") or ""
    country = (account_data.get("country") or "").strip()
    norm_name = normalize_company_name(raw_name)

    if not norm_name:
        return None

    now = datetime.now(timezone.utc)

    set_fields = {
        "updated_at": now,
        "is_multi_country": account_data.get("is_multi_country", False),
    }
    set_on_insert = {
        "account_name": raw_name.strip(),
        "normalized_name": norm_name,
        "country": country,
        "created_at": now,
        "first_seen_date": now,
        "source": "email_pipeline",
    }

    if not dry_run:
        result = accounts_col.find_one_and_update(
            {"normalized_name": norm_name, "country": country},
            {"$set": set_fields, "$setOnInsert": set_on_insert},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return str(result["_id"]) if result else None
    else:
        existing = accounts_col.find_one({"normalized_name": norm_name, "country": country})
        log.info("[DRY-RUN] Would upsert account: %s / %s", norm_name, country)
        return str(existing["_id"]) if existing else "dry_run_id"


# ---------------------------------------------------------------------------
# RFQ upsert
# ---------------------------------------------------------------------------

def _subject_key(text: str) -> str:
    """Normalise a subject line into a dedup key (strip Re:/Fwd:, lowercase)."""
    cleaned = re.sub(r"^(re|fwd|fw):\s*", "", text.strip(), flags=re.IGNORECASE)
    return cleaned.lower().strip()


def upsert_rfq(
    extraction: dict,
    contact_id: Optional[str],
    account_id: Optional[str],
    rfqs_col: Any,
    dry_run: bool = False,
) -> Optional[str]:
    """
    Upsert an RFQ record.  Dedup key: (contact_email, subject_key, received_month).
    Returns the rfq_id string, or None if this email is not an RFQ.
    """
    rfq_data = extraction.get("rfq", {})
    if not rfq_data.get("is_rfq"):
        return None

    contact_email = (extraction.get("contact", {}).get("email") or "").lower()
    if not contact_email:
        return None

    # Build dedup key from subject stored in extraction
    subject = extraction.get("one_line_summary", "") or ""
    subj_key = _subject_key(subject)

    # Use received_date month for dedup (group same RFQ across email threads)
    raw_date = rfq_data.get("received_date") or extraction.get("last_communication_date")
    try:
        received_dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        received_dt = datetime.now(timezone.utc)
    received_month = received_dt.strftime("%Y-%m")

    now = datetime.now(timezone.utc)

    # Map status
    status_map = {
        "received": "pending",
        "quoted": "quoted",
        "won": "won",
        "lost": "lost",
        "pending": "pending",
    }
    raw_status = rfq_data.get("rfq_status", "unknown")
    status = status_map.get(raw_status, "pending")

    set_fields = {
        "updated_at": now,
        "last_seen_date": now,
    }
    if rfq_data.get("rfq_summary"):
        set_fields["summary"] = rfq_data["rfq_summary"]
    if rfq_data.get("project_type"):
        set_fields["project_type"] = rfq_data["project_type"]
    if rfq_data.get("geography"):
        set_fields["geography"] = rfq_data["geography"]

    source_email_entry = {
        "email_id": extraction.get("_source_email_id"),
        "date": received_dt,
        "direction": extraction.get("_email_direction", "inbound"),
    }

    if not dry_run:
        existing = rfqs_col.find_one({
            "contact_email": contact_email,
            "subject_key": subj_key,
            "received_month": received_month,
        })
        if existing:
            rfqs_col.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": set_fields,
                    "$addToSet": {"source_emails": source_email_entry},
                },
            )
            return existing.get("rfq_id")
        else:
            rfq_id = next_rfq_id(rfqs_col)
            doc = {
                "rfq_id": rfq_id,
                "contact_email": contact_email,
                "contact_id": contact_id,
                "account_id": account_id,
                "subject_key": subj_key,
                "received_month": received_month,
                "status": status,
                "priority": "medium",
                "project_type": rfq_data.get("project_type"),
                "geography": rfq_data.get("geography"),
                "summary": rfq_data.get("rfq_summary"),
                "source_emails": [source_email_entry],
                "received_date": received_dt,
                "created_at": now,
                "updated_at": now,
                "first_seen_date": now,
                "last_seen_date": now,
                "created_by": "email_pipeline",
            }
            rfqs_col.insert_one(doc)
            return rfq_id
    else:
        log.info(
            "[DRY-RUN] Would upsert RFQ for %s | %s | %s",
            contact_email, subj_key[:50], received_month,
        )
        return "DRY-RUN-RFQ-ID"


def upsert_vendor_from_extraction(extraction: dict, vendors_col: Any, dry_run: bool = False) -> None:
    """Upsert vendor metadata for vendor-classified emails into the existing vendors collection."""
    contact = extraction.get("contact", {})
    company_name = (contact.get("company_name") or "").strip()
    email = (contact.get("email") or "").strip().lower()
    if not company_name and not email:
        return

    now = datetime.now(timezone.utc)
    selector = {"vendorName": company_name} if company_name else {"primary_email": email}
    update = {
        "$set": {
            "updated_at": now,
            "source": "email_pipeline",
            "primary_email": email,
            "country": contact.get("country"),
            "contact_name": contact.get("name"),
        },
        "$setOnInsert": {
            "vendorName": company_name or (email.split("@")[-1] if "@" in email else "Unknown Vendor"),
            "created_at": now,
            "status": "active",
        },
    }
    if dry_run:
        log.info("[DRY-RUN] Would upsert vendor %s (%s)", company_name or "?", email)
        return
    vendors_col.update_one(selector, update, upsert=True)


def log_finance_email(extraction: dict, finance_log_col: Any, dry_run: bool = False) -> None:
    """Write one upserted finance-classified event into a dedicated finance log collection."""
    source_email_id = extraction.get("_source_email_id")
    if not source_email_id:
        return
    doc = {
        "source_email_id": source_email_id,
        "email_type": extraction.get("email_type"),
        "contact": extraction.get("contact", {}),
        "account": extraction.get("account", {}),
        "summary": extraction.get("one_line_summary"),
        "logged_at": datetime.now(timezone.utc),
    }
    if dry_run:
        log.info("[DRY-RUN] Would log finance email %s", source_email_id)
        return
    finance_log_col.update_one(
        {"source_email_id": source_email_id},
        {"$set": doc, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Job-change detection and recording
# ---------------------------------------------------------------------------

def detect_and_record_job_change(
    extraction: dict,
    contact_id: str,
    contacts_col: Any,
    history_col: Any,
    dry_run: bool = False,
) -> None:
    """
    If Claude flagged a job change, record the old relationship in contact_history
    and mark it as inactive.
    """
    signal = extraction.get("job_change_signal", {})
    if not signal.get("detected"):
        return

    old_company = signal.get("old_company")
    new_company = signal.get("new_company")
    if not (old_company or new_company):
        return

    now = datetime.now(timezone.utc)
    history_doc = {
        "contact_id": contact_id,
        "contact_email": extraction.get("contact", {}).get("email"),
        "old_company": old_company,
        "new_company": new_company,
        "contact_name": extraction.get("contact", {}).get("name"),
        "country": extraction.get("contact", {}).get("country"),
        "notes": signal.get("notes"),
        "detected_at": now,
        "source_email_id": extraction.get("_source_email_id"),
        "status": "inactive",  # old relationship is now inactive
    }

    if not dry_run:
        history_col.insert_one(history_doc)
        log.info("Recorded job change for contact %s: %s → %s", contact_id, old_company, new_company)
    else:
        log.info(
            "[DRY-RUN] Would record job change: %s → %s", old_company, new_company
        )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_crm_population(
    since_date: Optional[datetime] = None,
    dry_run: bool = False,
) -> dict:
    """
    Read all unprocessed extractions and populate CRM collections.
    Returns summary counts.
    """
    extractions_col = get_collection(DB_CRM, COL_EMAIL_EXTRACTIONS)
    contacts_col = get_collection(DB_CRM, COL_CONTACTS)
    accounts_col = get_collection(DB_CRM, COL_SALES_ACCOUNTS)
    rfqs_col = get_collection(DB_CRM, COL_RFQS)
    history_col = get_collection(DB_CRM, COL_CONTACT_HISTORY)
    vendors_col = get_collection(DB_CRM, COL_VENDORS)
    finance_log_col = get_collection(DB_CRM, COL_FINANCE_LOG)

    query: dict[str, Any] = {"crm_populated": {"$ne": True}}
    if since_date:
        query["_extracted_at"] = {"$gte": since_date}

    extractions = list(extractions_col.find(query).sort("_extracted_at", 1))
    total = len(extractions)
    log.info("Found %d extractions to populate into CRM", total)

    counts = {
        "total": total,
        "contacts_upserted": 0,
        "accounts_upserted": 0,
        "rfqs_upserted": 0,
        "job_changes_recorded": 0,
        "skipped": 0,
    }

    for extraction in extractions:
        email_type = extraction.get("email_type", "unknown")

        # Skip types we don't want to put into CRM
        if email_type in ("promotional", "unknown"):
            if not dry_run:
                extractions_col.update_one(
                    {"_id": extraction["_id"]},
                    {"$set": {"crm_populated": True, "crm_skipped": True}},
                )
            counts["skipped"] += 1
            continue

        if email_type == "finance":
            log_finance_email(extraction, finance_log_col, dry_run)

        if email_type == "vendor":
            upsert_vendor_from_extraction(extraction, vendors_col, dry_run)

        # 1 — Upsert contact
        contact_id = upsert_contact(extraction, contacts_col, dry_run)
        if contact_id:
            counts["contacts_upserted"] += 1

        # 2 — Upsert account
        account_id = upsert_account(extraction, accounts_col, dry_run)
        if account_id:
            counts["accounts_upserted"] += 1

        # 3 — Upsert RFQ (only for rfq-type emails)
        rfq_id = upsert_rfq(extraction, contact_id, account_id, rfqs_col, dry_run)
        if rfq_id:
            counts["rfqs_upserted"] += 1

        # 4 — Record job change if detected
        if contact_id:
            detect_and_record_job_change(
                extraction, contact_id, contacts_col, history_col, dry_run
            )
            if extraction.get("job_change_signal", {}).get("detected"):
                counts["job_changes_recorded"] += 1

        # 5 — Mark extraction as populated
        if not dry_run:
            extractions_col.update_one(
                {"_id": extraction["_id"]},
                {"$set": {"crm_populated": True}},
            )

    log.info(
        "CRM population complete. contacts=%d accounts=%d rfqs=%d job_changes=%d skipped=%d",
        counts["contacts_upserted"], counts["accounts_upserted"],
        counts["rfqs_upserted"], counts["job_changes_recorded"], counts["skipped"],
    )
    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Populate CRM collections from email_crm_extractions"
    )
    parser.add_argument("--since", metavar="YYYY-MM-DD",
                        help="Only process extractions on or after this date")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing to MongoDB")
    args = parser.parse_args()

    since = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    result = run_crm_population(since_date=since, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
