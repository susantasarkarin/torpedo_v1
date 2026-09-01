"""
backfill_spine_rfqs.py — one-off migration onto the CRM spine.

Run once after deploying the spine-backed RFQ page. Three independent steps,
each idempotent and each runnable alone:

  --step legacy    email_automation.rfqs  -> crm_db.opportunities
                   Rows written by the two retired writers (rfq.py's
                   /sync-from-gmail and crm_populator.upsert_rfq). Matched on
                   rfq_id so re-running never duplicates.

  --step accounts  crm_db.accounts -> email_automation.sales_accounts
                   Same adoption the nightly reconcile does, run now so the
                   Account page is populated immediately rather than tomorrow.

  --step mail      Queue the mail-pool AI over the FULL mailbox history.
                   This is the expensive one — see the cost note below.

Usage:
    python -m backend.scripts.backfill_spine_rfqs --step legacy --dry-run
    python -m backend.scripts.backfill_spine_rfqs --step legacy
    python -m backend.scripts.backfill_spine_rfqs --step accounts
    python -m backend.scripts.backfill_spine_rfqs --step mail --batches 50
    python -m backend.scripts.backfill_spine_rfqs --step all

COST NOTE on --step mail
------------------------
The mail pool is ~361K emails across ~6.3K unique senders. mail_pool_ai batches
by SENDER (one cheap-model call covers all of that sender's mail), so a full
pass is roughly 6.3K calls, not 361K — on the order of $50 and about a day of
wall-clock at the standing 10-min/50-sender beat. This script only queues the
work; the existing Celery beat drains it. Nothing here bypasses the rate limit.
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


def _imports():
    from db_pools import get_db
    from app.services import crm_service
    return get_db, crm_service


# ---------------------------------------------------------------------------
# Step 1 — legacy email_automation.rfqs -> crm_db.opportunities
# ---------------------------------------------------------------------------

def migrate_legacy_rfqs(dry_run: bool = False, limit: int = 0) -> dict:
    """
    Move hand-created and pipeline-created rows out of email_automation.rfqs
    onto the spine, preserving rfq_id so existing links keep resolving.
    """
    get_db, crm_service = _imports()
    rfqs = get_db("email_automation")["rfqs"]
    opportunities = crm_service._col("opportunities")

    stats = {"scanned": 0, "migrated": 0, "already_present": 0, "skipped": 0}

    query = {"is_deleted": {"$ne": True}}
    cursor = rfqs.find(query).sort("created_at", 1)
    if limit:
        cursor = cursor.limit(limit)

    # Legacy status -> spine stage. Legacy rows only ever used these five.
    stage_map = {
        "pending": "rfq",
        "quoted": "proposal",
        "negotiating": "negotiation",
        "won": "won",
        "lost": "lost",
    }

    for rfq in cursor:
        stats["scanned"] += 1
        rfq_id = rfq.get("rfq_id")
        if not rfq_id:
            stats["skipped"] += 1
            continue

        if opportunities.find_one({"metadata.rfq.rfq_id": rfq_id}, {"_id": 1}):
            stats["already_present"] += 1
            continue

        if dry_run:
            log.info("[DRY-RUN] would migrate %s (%s)", rfq_id, rfq.get("status"))
            stats["migrated"] += 1
            continue

        contact_email = (rfq.get("contact_email") or "").strip().lower()
        company = rfq.get("sender_company") or rfq.get("account_name")

        account_id = None
        if company:
            account, _ = crm_service.get_or_create_account(
                company,
                defaults={"account_type": "client",
                          "metadata": {"source": "legacy_rfq_migration"}},
            )
            account_id = account["_id"]

        contact_id = None
        if contact_email:
            contact, _ = crm_service.get_or_create_contact(
                contact_email,
                defaults={"name": rfq.get("sender_name"),
                          "account_id": account_id,
                          "metadata": {"source": "legacy_rfq_migration"}},
            )
            contact_id = contact["_id"]

        value = rfq.get("manual_value")
        if value is None:
            value = rfq.get("extracted_value") or 0

        # Carry the whole legacy row into metadata.rfq so nothing the old page
        # displayed is lost, then stamp the fields spine_rfq reads by name.
        payload = {
            "rfq_id": rfq_id,
            "description": rfq.get("description"),
            "summary": rfq.get("summary"),
            "budget": rfq.get("extracted_value"),
            "currency": rfq.get("extracted_currency") or rfq.get("manual_currency"),
            "methodology": rfq.get("methodology"),
            "loi": rfq.get("loi"),
            "ir": rfq.get("ir"),
            "country": rfq.get("country"),
            "sample_size": rfq.get("sample_size"),
            "target_audience": rfq.get("target_audience"),
            "timeline": rfq.get("timeline"),
            "study_type": rfq.get("study_type"),
            "additional_requirements": rfq.get("additional_requirements"),
            "ai_summary": rfq.get("ai_summary"),
            "email_body": rfq.get("email_body"),
            "sender_name": rfq.get("sender_name"),
            "sender_title": rfq.get("sender_title"),
            "source_emails": rfq.get("source_emails", []),
            "deadline": rfq.get("due_date"),
            "estimate_id": rfq.get("estimate_id"),
            "migrated_from": "email_automation.rfqs",
            "migrated_at": datetime.utcnow().isoformat(),
        }

        legacy_status = (rfq.get("status") or "pending").lower()
        stage = stage_map.get(legacy_status, "rfq")

        opportunity = crm_service.create("opportunities", {
            "title": rfq.get("title") or rfq_id,
            "description": rfq.get("description"),
            "account_id": account_id,
            "contact_id": contact_id,
            "amount": value,
            "currency": rfq.get("manual_currency") or rfq.get("extracted_currency"),
            "stage": stage,
            "status": "won" if stage == "won" else ("lost" if stage == "lost" else "open"),
            "priority": rfq.get("priority"),
            "created_at": rfq.get("created_at"),
            "closed_at": rfq.get("closed_date"),
            "loss_reason": rfq.get("loss_reason") if stage == "lost" else None,
            "metadata": {"source": "rfq", "rfq": payload},
        })

        # Leave a breadcrumb on the legacy row so a second run is a no-op even
        # if the spine copy is later renamed.
        rfqs.update_one(
            {"_id": rfq["_id"]},
            {"$set": {"migrated_to_spine": True,
                      "spine_opportunity_id": opportunity["_id"]}},
        )
        stats["migrated"] += 1

    log.info("legacy RFQ migration: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Step 2 — crm_db.accounts -> email_automation.sales_accounts
# ---------------------------------------------------------------------------

def adopt_spine_accounts(dry_run: bool = False) -> dict:
    """Run the reverse reconcile immediately instead of waiting for the nightly beat."""
    get_db, crm_service = _imports()

    from tasks.crm_spine_tasks import _adopt_spine_accounts_into_sales

    sales_accounts = get_db("email_automation")["sales_accounts"]
    stats: dict = {}

    if dry_run:
        accounts = crm_service._col("accounts")
        linked = sales_accounts.count_documents({"crm_account_id": {"$exists": True}})
        total = accounts.count_documents({
            "$or": [{"account_type": "client"}, {"account_type": {"$exists": False}}],
            "metadata.source_deleted": {"$ne": True},
        })
        log.info("[DRY-RUN] %d client accounts on spine, %d already linked -> "
                 "up to %d would be adopted", total, linked, max(total - linked, 0))
        return {"spine_client_accounts": total, "already_linked": linked}

    _adopt_spine_accounts_into_sales(sales_accounts, crm_service, stats)
    log.info("spine account adoption: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Step 3 — queue the full-history mail-pool AI pass
# ---------------------------------------------------------------------------

def queue_mail_backfill(batches: int, per_batch: int, dry_run: bool = False) -> dict:
    """
    Queue N mail-pool AI passes so the whole mailbox history gets processed.

    The task itself picks up whichever senders are still unprocessed, so
    queueing N batches is simply "do N batches' worth of work now" rather than
    waiting N*10 minutes for the beat.
    """
    if dry_run:
        log.info("[DRY-RUN] would queue %d batches x %d senders = %d senders",
                 batches, per_batch, batches * per_batch)
        return {"queued": 0, "would_queue": batches}

    from tasks.mail_pool_ai_tasks import process_mail_pool_sender_batch

    queued = []
    for _ in range(batches):
        task = process_mail_pool_sender_batch.delay(limit=per_batch)
        queued.append(task.id)

    log.info("queued %d mail-pool AI batches (%d senders each)", len(queued), per_batch)
    return {"queued": len(queued), "task_ids": queued}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--step", choices=["legacy", "accounts", "mail", "all"],
                        default="all", help="Which migration step to run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap legacy rows processed (0 = no cap)")
    parser.add_argument("--batches", type=int, default=20,
                        help="Mail-pool AI batches to queue (--step mail)")
    parser.add_argument("--per-batch", type=int, default=50,
                        help="Senders per mail-pool batch")
    args = parser.parse_args()

    results = {}

    if args.step in ("legacy", "all"):
        results["legacy"] = migrate_legacy_rfqs(dry_run=args.dry_run, limit=args.limit)

    if args.step in ("accounts", "all"):
        results["accounts"] = adopt_spine_accounts(dry_run=args.dry_run)

    if args.step in ("mail", "all"):
        results["mail"] = queue_mail_backfill(
            batches=args.batches, per_batch=args.per_batch, dry_run=args.dry_run
        )

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
