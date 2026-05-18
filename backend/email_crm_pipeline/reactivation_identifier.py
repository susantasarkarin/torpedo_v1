"""
reactivation_identifier.py — Task 3: Reactivation Candidate Identification
===========================================================================

Queries the CRM and pipeline collections to identify three buckets of
contacts worth re-engaging:

  Bucket 1 — Dormant Relationships
    Last communication > DORMANT_MONTHS months ago, with ≥2 prior exchanges.

  Bucket 2 — Unanswered Outbound Pitches
    We sent a pitch/quote/proposal, no reply within UNANSWERED_DAYS days,
    no active RFQ for this contact.

  Bucket 3 — Job Changers — New Opportunity
    Contact moved to a new company; we have no prior relationship there.

Output: reactivation_candidates.jsonl (also upserted to MongoDB).

Usage:
    python -m backend.email_crm_pipeline.reactivation_identifier
    python -m backend.email_crm_pipeline.reactivation_identifier --output ./data/candidates.jsonl
"""

import sys
import os
import json
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_collection
from email_crm_pipeline.config import (
    DB_CRM,
    COL_CONTACTS, COL_SALES_ACCOUNTS, COL_RFQS,
    COL_EMAIL_EXTRACTIONS, COL_CONTACT_HISTORY, COL_REACTIVATION,
    DORMANT_MONTHS, DORMANT_MIN_EXCHANGES, UNANSWERED_DAYS,
    REACTIVATION_FILE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bucket 1 — Dormant Relationships
# ---------------------------------------------------------------------------

def get_dormant_contacts(
    extractions_col: Any,
    contacts_col: Any,
    cutoff: datetime,
) -> list[dict]:
    """
    Find contacts whose last communication is older than cutoff and who had
    at least DORMANT_MIN_EXCHANGES prior email exchanges.
    """
    # Aggregate email counts and last date per contact email from extractions
    pipeline = [
        {
            "$match": {
                "contact.email": {"$exists": True, "$ne": None},
                "email_type": {"$in": ["client_rfq", "client_general", "vendor"]},
            }
        },
        {
            "$group": {
                "_id": "$contact.email",
                "email_count": {"$sum": 1},
                "last_date": {"$max": "$last_communication_date"},
                "company": {"$last": "$contact.company_name"},
                "country": {"$last": "$contact.country"},
                "name": {"$last": "$contact.name"},
                "designation": {"$last": "$contact.designation"},
                "rfq_summaries": {
                    "$push": {
                        "$cond": [
                            {"$eq": ["$rfq.is_rfq", True]},
                            "$rfq.rfq_summary",
                            "$$REMOVE",
                        ]
                    }
                },
            }
        },
        {
            "$match": {
                "email_count": {"$gte": DORMANT_MIN_EXCHANGES},
            }
        },
    ]

    results = list(extractions_col.aggregate(pipeline))
    candidates = []

    for row in results:
        last_date = row.get("last_date")
        if not last_date:
            continue
        # Normalise to datetime
        if isinstance(last_date, str):
            try:
                last_date = datetime.fromisoformat(last_date.replace("Z", "+00:00"))
            except ValueError:
                continue
        if not isinstance(last_date, datetime):
            continue

        # Ensure timezone-aware
        if last_date.tzinfo is None:
            last_date = last_date.replace(tzinfo=timezone.utc)

        if last_date < cutoff:
            candidates.append({
                "bucket": "dormant",
                "contact_email": row["_id"],
                "contact_name": row.get("name"),
                "designation": row.get("designation"),
                "company": row.get("company"),
                "country": row.get("country"),
                "last_communication_date": last_date.isoformat(),
                "total_exchanges": row["email_count"],
                "rfq_history": [s for s in (row.get("rfq_summaries") or []) if s],
                "relationship_context": (
                    f"Had {row['email_count']} email exchanges; "
                    f"last contact was {(datetime.now(timezone.utc) - last_date).days} days ago."
                ),
            })

    log.info("Bucket 1 (dormant): %d candidates", len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# Bucket 2 — Unanswered Outbound Pitches
# ---------------------------------------------------------------------------

def get_unanswered_outbound(
    extractions_col: Any,
    rfqs_col: Any,
    cutoff: datetime,
) -> list[dict]:
    """
    Find outbound pitches/quotes sent before cutoff with no reply received
    and no currently active RFQ.
    """
    outbound = list(extractions_col.find({
        "outbound_unanswered.is_outbound_pitch": True,
        "outbound_unanswered.response_received": {"$ne": True},
        "_email_timestamp": {"$lt": cutoff},
        "contact.email": {"$exists": True, "$ne": None},
    }))

    candidates = []
    seen_emails: set[str] = set()

    for doc in outbound:
        email = (doc.get("contact", {}).get("email") or "").lower()
        if not email or email in seen_emails:
            continue

        # Check for an active RFQ for this contact
        active_rfq = rfqs_col.find_one({
            "contact_email": email,
            "status": {"$in": ["pending", "quoted", "negotiating"]},
        })
        if active_rfq:
            continue

        seen_emails.add(email)
        email_ts = doc.get("_email_timestamp")
        if isinstance(email_ts, datetime):
            days_since = (datetime.now(timezone.utc) - email_ts.replace(tzinfo=timezone.utc)).days
        else:
            days_since = None

        candidates.append({
            "bucket": "unanswered_outbound",
            "contact_email": email,
            "contact_name": doc.get("contact", {}).get("name"),
            "designation": doc.get("contact", {}).get("designation"),
            "company": doc.get("contact", {}).get("company_name"),
            "country": doc.get("contact", {}).get("country"),
            "last_communication_date": (
                email_ts.isoformat() if isinstance(email_ts, datetime) else str(email_ts or "")
            ),
            "pitch_summary": doc.get("one_line_summary"),
            "days_since_sent": days_since,
            "rfq_history": (
                [doc["rfq"]["rfq_summary"]]
                if doc.get("rfq", {}).get("rfq_summary") else []
            ),
            "relationship_context": (
                f"We sent a pitch/proposal "
                f"{'%d days ago' % days_since if days_since else 'recently'} "
                f"with no response received."
            ),
        })

    log.info("Bucket 2 (unanswered outbound): %d candidates", len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# Bucket 3 — Job Changers
# ---------------------------------------------------------------------------

def get_job_changers(
    history_col: Any,
    accounts_col: Any,
    rfqs_col: Any,
) -> list[dict]:
    """
    Find contacts who changed jobs to a company we have no prior relationship with.
    """
    job_changes = list(history_col.find({"status": "inactive"}))
    candidates = []
    seen_emails: set[str] = set()

    for change in job_changes:
        email = (change.get("contact_email") or "").lower()
        new_company = change.get("new_company") or ""

        if not email or not new_company or email in seen_emails:
            continue

        # Check if we have any prior account or RFQ for the new company
        norm_name = new_company.lower().strip()
        existing_account = accounts_col.find_one({"normalized_name": {"$regex": norm_name[:20]}})
        existing_rfq = rfqs_col.find_one(
            {"contact_email": email, "status": {"$ne": "lost"}}
        )

        if existing_account or existing_rfq:
            continue  # Already have a relationship at new company

        seen_emails.add(email)
        candidates.append({
            "bucket": "job_changer",
            "contact_email": email,
            "contact_name": change.get("contact_name"),
            "company": new_company,
            "old_company": change.get("old_company"),
            "country": change.get("country"),
            "last_communication_date": (
                change["detected_at"].isoformat()
                if isinstance(change.get("detected_at"), datetime)
                else str(change.get("detected_at", ""))
            ),
            "rfq_history": [],
            "relationship_context": (
                f"Previously worked at {change.get('old_company', 'unknown company')}; "
                f"now at {new_company}. No prior relationship at new company."
            ),
        })

    log.info("Bucket 3 (job changers): %d candidates", len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_identification(output_path: Optional[Path] = None) -> dict:
    """
    Identify all three reactivation buckets and write them to JSONL + MongoDB.
    Returns summary counts.
    """
    extractions_col = get_collection(DB_CRM, COL_EMAIL_EXTRACTIONS)
    contacts_col = get_collection(DB_CRM, COL_CONTACTS)
    accounts_col = get_collection(DB_CRM, COL_SALES_ACCOUNTS)
    rfqs_col = get_collection(DB_CRM, COL_RFQS)
    history_col = get_collection(DB_CRM, COL_CONTACT_HISTORY)
    reactivation_col = get_collection(DB_CRM, COL_REACTIVATION)

    now = datetime.now(timezone.utc)
    dormant_cutoff = now - timedelta(days=DORMANT_MONTHS * 30)
    outbound_cutoff = now - timedelta(days=UNANSWERED_DAYS)

    bucket1 = get_dormant_contacts(extractions_col, contacts_col, dormant_cutoff)
    bucket2 = get_unanswered_outbound(extractions_col, rfqs_col, outbound_cutoff)
    bucket3 = get_job_changers(history_col, accounts_col, rfqs_col)

    all_candidates = bucket1 + bucket2 + bucket3
    run_date = now.isoformat()

    # Attach metadata
    for c in all_candidates:
        c["identified_at"] = run_date

    # Write JSONL
    out_path = output_path or REACTIVATION_FILE
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for c in all_candidates:
            f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")
    log.info("Wrote %d candidates to %s", len(all_candidates), out_path)

    # Upsert into MongoDB for dashboard/tracking
    for c in all_candidates:
        reactivation_col.update_one(
            {"contact_email": c["contact_email"], "bucket": c["bucket"]},
            {"$set": c},
            upsert=True,
        )

    summary = {
        "total": len(all_candidates),
        "dormant": len(bucket1),
        "unanswered_outbound": len(bucket2),
        "job_changers": len(bucket3),
        "output_file": str(out_path),
    }
    log.info("Reactivation identification complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Identify reactivation candidates from CRM data"
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Path to write the JSONL output (default: data/reactivation_candidates.jsonl)",
    )
    args = parser.parse_args()

    result = run_identification(output_path=Path(args.output) if args.output else None)
    print(json.dumps(result, indent=2, default=str))
