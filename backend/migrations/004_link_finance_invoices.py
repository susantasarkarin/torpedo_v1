"""
Phase 3 migration adapter: legacy finance invoices -> canonical CRM spine.

Links existing finance records to the canonical layer (the master-plan goal:
"invoices linked to Account/Project/Opportunity"):

  finance_db.invoices -> crm_db.invoices, each linked to a canonical Account
  (matched/created from the invoice's customer name).

READ-ONLY on the source. Deduped by provenance (metadata.source/source_id), so
re-runs are idempotent. Accounts are matched via crm_service.get_or_create_account
(normalized-name dedupe), so finance customers reconcile with vendor/client/lead
accounts already in the spine.

Usage:
    python -m backend.migrations.004_link_finance_invoices            # dry-run
    python -m backend.migrations.004_link_finance_invoices --execute
"""

import argparse
from typing import Optional, Dict, Any, List

try:
    from ..database import get_database
    from ..app.services import crm_service
except ImportError:  # pragma: no cover - absolute import / CLI fallback
    from database import get_database
    from app.services import crm_service

# Field-name variants observed in the finance import mappings.
_CUSTOMER_KEYS = ["customer_name", "customer", "client_name", "client",
                  "company_name", "company", "bill_to", "name"]
_TOTAL_KEYS = ["total", "total_amount", "grand_total", "amount", "invoice_amount"]
_INVNO_KEYS = ["invoice_number", "invoice_no", "invoice", "inv_number", "inv_no"]
_BALANCE_KEYS = ["balance_due", "balance", "due_amount", "outstanding"]


def _first(doc: Dict[str, Any], keys: List[str], default=None):
    for k in keys:
        v = doc.get(k)
        if v not in (None, ""):
            return v
    return default


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def migrate_finance_invoices(
    source_db: str = "finance_db",
    source_collection: str = "invoices",
    dry_run: bool = True,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Link finance invoices to canonical accounts in crm_db. Returns stats."""
    source_key = f"{source_db}.{source_collection}"
    src = get_database(source_db)[source_collection]

    migrated_ids = set()
    for doc in crm_service._col("invoices").find(
        {"metadata.source": source_key}, {"metadata.source_id": 1}
    ):
        sid = (doc.get("metadata") or {}).get("source_id")
        if sid:
            migrated_ids.add(sid)

    stats = {
        "source": source_key,
        "dry_run": dry_run,
        "scanned": 0,
        "invoices_created": 0,
        "invoices_skipped_existing": 0,
        "accounts_created": 0,
        "accounts_reused": 0,
        "no_customer": 0,
        "errors": 0,
    }

    cursor = src.find({})
    if limit:
        cursor = cursor.limit(limit)

    for doc in cursor:
        stats["scanned"] += 1
        source_id = str(doc.get("_id"))
        if source_id in migrated_ids:
            stats["invoices_skipped_existing"] += 1
            continue
        try:
            customer = _first(doc, _CUSTOMER_KEYS)
            amount = _to_float(_first(doc, _TOTAL_KEYS, 0))

            account_id = None
            if customer:
                if dry_run:
                    existing = crm_service.find_account_by_name(customer)
                    stats["accounts_reused" if existing else "accounts_created"] += 1
                    account_id = existing["_id"] if existing else None
                else:
                    account, created = crm_service.get_or_create_account(
                        customer, defaults={"account_type": "client", "metadata": {"source": source_key}}
                    )
                    account_id = account["_id"]
                    stats["accounts_created" if created else "accounts_reused"] += 1
            else:
                stats["no_customer"] += 1

            if not dry_run:
                crm_service.create(
                    "invoices",
                    {
                        "account_id": account_id,
                        "amount": amount,
                        "status": doc.get("status") or "imported",
                        "metadata": {
                            "source": source_key,
                            "source_id": source_id,
                            "invoice_number": _first(doc, _INVNO_KEYS),
                            "customer_name": customer,
                            "balance_due": _to_float(_first(doc, _BALANCE_KEYS, 0)),
                        },
                    },
                )
            stats["invoices_created"] += 1
            migrated_ids.add(source_id)
        except Exception as e:  # keep going on bad records
            stats["errors"] += 1
            print(f"  ⚠️ error on source_id={source_id}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Link legacy finance invoices into the CRM spine.")
    parser.add_argument("--source-db", default="finance_db")
    parser.add_argument("--source-collection", default="invoices")
    parser.add_argument("--execute", action="store_true", help="Write changes (default is dry-run).")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    stats = migrate_finance_invoices(
        source_db=args.source_db,
        source_collection=args.source_collection,
        dry_run=not args.execute,
        limit=args.limit,
    )
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Finance invoice linkage [{mode}] ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
