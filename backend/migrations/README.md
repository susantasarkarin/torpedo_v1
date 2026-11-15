# Migrations

Run with `python run_migrations.py` (pending migrations), `--status`, or `--rollback` (last applied one, uses `down(db)`).

The runner globs `migrations/*.py` in sorted filename order, skips `run_migrations`, `rollback_migrations` and `__init__`, calls `up(db)` on each one, and records the result in the `migrations_log` collection. An applied name is skipped on the next run.

**Known problem:** the runner calls `up(db)` on every file it finds. Four files define no `up()`: `001_init_crm_collections.py`, `002_migrate_legacy_leads.py`, `003_migrate_legacy_accounts.py`, `004_link_finance_invoices.py`. On a fresh run the runner stops at `001_init_crm_collections` with an AttributeError (the failed attempt is logged in `migrations_log`). Those four are one-off scripts with `main()` or `ensure_indexes(db)`; run them by hand (`python -m backend.migrations.<name>`). Adding `up()` to them, or making the runner skip them, is the fix (not done here).

## Run order

Sorted filename order, as the runner sees it:

| # | file | target | defines |
|---|---|---|---|
| 1 | `001_add_engagement_fields.py` | leads (email_automation) | up, down |
| 2 | `001_init_crm_collections.py` | crm_db indexes | ensure_indexes (script) |
| 3 | `002_add_campaign_fields.py` | campaigns | up, down |
| 4 | `002_migrate_legacy_leads.py` | legacy leads -> crm_db | main (script) |
| 5 | `003_migrate_legacy_accounts.py` | legacy vendors/clients -> crm_db | main (script) |
| 6 | `004_create_deliverability_collections.py` | deliverability collections | up, down |
| 7 | `004_link_finance_invoices.py` | finance invoices -> crm_db | main (script) |
| 8 | `005_create_indexes.py` | email_automation leads, campaigns, linkedin_* | up, down (creates indexes) |
| 9 | `006_add_ad_tracking_fields.py` | traffic_flow_db | up, down |
| 10 | `007_sfw_quality_indexes.py` | traffic_flow_db | up, down (creates indexes) |
| 11 | `008_client_rejects.py` | traffic_flow_db | up, down |
| 12 | `009_survey_routing.py` | traffic_flow_db | up, down |

Numbers 001, 002 and 004 each appear twice. The runner orders by full filename, so within a number the names decide: `001_add_engagement_fields` before `001_init_crm_collections`, and so on. Renaming a file makes the runner treat it as new, because it tracks by name.

## Indexes

Index definitions do not belong in migrations. The single registry is `backend/indexes.py` (`INDEXES`, keyed by database then collection). Startup runs `ensure_indexes()` read-only; `python indexes.py` builds everything. Migrations 001_init_crm_collections, 005 and 007 still create indexes directly. Their entries are already in the registry. The remaining create_index call sites are listed in `docs/mongo_index_registry.md`.
