"""
Phase 3 migration adapter: legacy vendors + clients -> canonical Accounts.

Implements the master-plan rule that a vendor is simply an Account with
account_type="vendor" (and a client an Account with account_type="client").
READ-ONLY on the source collections.

  email_automation.vendors -> crm_db.accounts (account_type="vendor")
  email_automation.clients -> crm_db.accounts (account_type="client")

Deduped by normalized account name (via crm_service.get_or_create_account), so
re-runs reuse existing accounts (idempotent, no duplicates). Provenance stored
under metadata.source / metadata.source_id.

Usage:
    python -m backend.migrations.003_migrate_legacy_accounts            # dry-run
    python -m backend.migrations.003_migrate_legacy_accounts --execute
"""

import argparse
from typing import Optional, Dict, Any

try:
    from ..database import get_database
    from ..app.services import crm_service
except ImportError:  # pragma: no cover - absolute import / CLI fallback
    from database import get_database
    from app.services import crm_service


def _upsert_account(name, account_type, email, source_key, source_id, meta, dry_run, stats):
    if not name:
        stats["skipped_no_name"] += 1
        return
    if dry_run:
        existing = crm_service.find_account_by_name(name)
        stats["accounts_reused" if existing else "accounts_created"] += 1
        return
    metadata = {"source": source_key, "source_id": source_id}
    metadata.update({k: v for k, v in (meta or {}).items() if v is not None})
    _account, created = crm_service.get_or_create_account(
        name,
        defaults={"account_type": account_type, "email": email, "metadata": metadata},
    )
    stats["accounts_created" if created else "accounts_reused"] += 1


def migrate_legacy_accounts(
    source_db: str = "email_automation",
    dry_run: bool = True,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Project legacy vendors + clients onto canonical accounts. Returns stats."""
    db = get_database(source_db)
    stats = {
        "source_db": source_db,
        "dry_run": dry_run,
        "scanned": 0,
        "vendors": 0,
        "clients": 0,
        "accounts_created": 0,
        "accounts_reused": 0,
        "skipped_no_name": 0,
        "errors": 0,
    }

    # --- Vendors -> account_type="vendor" ---
    cur = db["vendors"].find({})
    if limit:
        cur = cur.limit(limit)
    for v in cur:
        stats["scanned"] += 1
        stats["vendors"] += 1
        try:
            _upsert_account(
                name=v.get("vendorName") or v.get("name"),
                account_type="vendor",
                email=v.get("vendorEmail") or v.get("email"),
                source_key=f"{source_db}.vendors",
                source_id=str(v.get("_id")),
                meta={
                    "vendor_no": v.get("vendorNo"),
                    "vendor_type": v.get("vendorType"),
                    "vid": v.get("vid"),
                    "status": v.get("status"),
                },
                dry_run=dry_run,
                stats=stats,
            )
        except Exception as e:
            stats["errors"] += 1
            print(f"  ⚠️ vendor error {v.get('_id')}: {e}")

    # --- Clients -> account_type="client" ---
    cur = db["clients"].find({})
    if limit:
        cur = cur.limit(limit)
    for c in cur:
        stats["scanned"] += 1
        stats["clients"] += 1
        try:
            _upsert_account(
                name=c.get("name") or c.get("clientName"),
                account_type="client",
                email=c.get("email"),
                source_key=f"{source_db}.clients",
                source_id=str(c.get("_id")),
                meta={
                    "client_no": c.get("clientNo"),
                    "client_type": c.get("clientType"),
                    "contact_person": c.get("contactPerson"),
                    "currency": c.get("currency"),
                    "status": c.get("status"),
                },
                dry_run=dry_run,
                stats=stats,
            )
        except Exception as e:
            stats["errors"] += 1
            print(f"  ⚠️ client error {c.get('_id')}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy vendors + clients into canonical accounts.")
    parser.add_argument("--source-db", default="email_automation")
    parser.add_argument("--execute", action="store_true", help="Write changes (default is dry-run).")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    stats = migrate_legacy_accounts(source_db=args.source_db, dry_run=not args.execute, limit=args.limit)
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Legacy account migration [{mode}] ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
