"""
Phase 3 migration adapter: legacy leads -> canonical CRM spine.

Reads legacy lead documents from `email_automation.leads` (READ-ONLY — the source
is never modified) and projects them onto the canonical `crm_db`:
  - each legacy lead -> a canonical `leads` record
  - its company    -> a canonical `accounts` record (deduped by normalized name)
  - provenance is stored on every created record under `metadata.source` /
    `metadata.source_id`, so the migration is idempotent (re-runs skip already
    migrated leads).

Usage:
    # dry run (default): report what would happen, write nothing
    python -m backend.migrations.002_migrate_legacy_leads

    # execute
    python -m backend.migrations.002_migrate_legacy_leads --execute --limit 500
"""

import argparse
from typing import Optional, Dict, Any

try:
    from ..database import get_database
    from ..app.services import crm_service
except ImportError:  # pragma: no cover - absolute import fallback / CLI
    from database import get_database
    from app.services import crm_service


def _split_name(name: Optional[str]) -> tuple:
    if not name:
        return None, None
    parts = name.strip().split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _domain_from_email(email: Optional[str]) -> Optional[str]:
    if email and "@" in email:
        return email.split("@", 1)[1].strip().lower() or None
    return None


def migrate_legacy_leads(
    source_db: str = "email_automation",
    source_collection: str = "leads",
    dry_run: bool = True,
    limit: Optional[int] = None,
    default_business_unit: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Project legacy leads onto the canonical CRM spine. Returns run statistics.
    Idempotent: leads already migrated (same source + source_id) are skipped.
    """
    source_key = f"{source_db}.{source_collection}"
    src = get_database(source_db)[source_collection]

    # Build the set of already-migrated source ids for idempotency.
    migrated_ids = set()
    for doc in crm_service._col("leads").find(
        {"metadata.source": source_key}, {"metadata.source_id": 1}
    ):
        sid = (doc.get("metadata") or {}).get("source_id")
        if sid:
            migrated_ids.add(sid)

    stats = {
        "source": source_key,
        "dry_run": dry_run,
        "scanned": 0,
        "leads_created": 0,
        "leads_skipped_existing": 0,
        "accounts_created": 0,
        "accounts_reused": 0,
        "errors": 0,
    }

    cursor = src.find({})
    if limit:
        cursor = cursor.limit(limit)

    for doc in cursor:
        stats["scanned"] += 1
        source_id = str(doc.get("_id"))

        if source_id in migrated_ids:
            stats["leads_skipped_existing"] += 1
            continue

        try:
            email = doc.get("email") or doc.get("email_address")
            company = doc.get("company") or doc.get("company_name")
            first, last = _split_name(doc.get("name"))
            first = first or doc.get("firstName") or doc.get("first_name")
            last = last or doc.get("lastName") or doc.get("last_name")

            account_id = None
            if company:
                if dry_run:
                    existing = crm_service.find_account_by_name(company)
                    stats["accounts_reused" if existing else "accounts_created"] += 1
                    account_id = existing["_id"] if existing else None
                else:
                    domain = _domain_from_email(email)
                    account, created = crm_service.get_or_create_account(
                        company,
                        defaults={
                            "account_type": "client",
                            "website": f"https://{domain}" if domain else None,
                            "metadata": {"source": source_key},
                        },
                    )
                    account_id = account["_id"]
                    stats["accounts_created" if created else "accounts_reused"] += 1

            if not dry_run:
                crm_service.create(
                    "leads",
                    {
                        "email": email,
                        "firstName": first,
                        "lastName": last,
                        "company": company,
                        "source": doc.get("source"),
                        "status": "new",
                        "account_id": account_id,
                        "metadata": {
                            "source": source_key,
                            "source_id": source_id,
                            "title": doc.get("title"),
                            "industry": doc.get("industry"),
                            "country": doc.get("country"),
                            "business_unit": default_business_unit,
                        },
                    },
                )
            stats["leads_created"] += 1
            migrated_ids.add(source_id)
        except Exception as e:  # keep going; one bad record shouldn't abort the run
            stats["errors"] += 1
            print(f"  ⚠️ error on source_id={source_id}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy leads into the CRM spine.")
    parser.add_argument("--source-db", default="email_automation")
    parser.add_argument("--source-collection", default="leads")
    parser.add_argument("--execute", action="store_true", help="Write changes (default is dry-run).")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--business-unit", default=None, help="Tag migrated leads with a business unit (SFW/Cogentix/BIM).")
    args = parser.parse_args()

    stats = migrate_legacy_leads(
        source_db=args.source_db,
        source_collection=args.source_collection,
        dry_run=not args.execute,
        limit=args.limit,
        default_business_unit=args.business_unit,
    )
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Legacy lead migration [{mode}] ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
