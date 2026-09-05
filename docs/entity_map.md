# Torpedo v1 → v2 Canonical Entity Map

> Generated: 2026-09-05 | Phase 0 deliverable
> Method: three parallel forensic passes — (1) every MongoDB database/collection and its read/write sites, (2) every Pydantic model, index, money field, PII field and audit-field gap, (3) how the same real-world person/company/brand is represented across stores and what (if anything) links them. Full citations live in the three source reports this document synthesizes; this file carries the dispositions and the findings that change the v2 design, not every individual citation.
>
> Companion document: [business_rules_register.md](business_rules_register.md) — this pass surfaced five new defects (D-15…D-19) and one new invariant (I-6), appended there, not duplicated here.

## Disposition legend

`KEEP` canonical, carries forward as-is · `MERGE` folds into another store, no independent v2 existence · `REPLACE` concept survives, storage/shape does not · `REMOVE` deleted, nothing carries forward · `EXTRACT` v1 behaviour must still be recovered/verified before a disposition can be assigned

---

## 0. Headline findings

Three findings should drive every decision below, in order of severity:

1. **v1 has no person entity and no company entity.** ~15 collections across 8 databases each hold a partial copy of a person; ~9 hold a partial copy of a company. Identity is matched by lowercased email string or normalized company-name string — never by a surrogate id. This is not a migration inconvenience; it means **there is no single query in v1 that can correctly answer "who is this."**
2. **There is no schema enforcement at the database boundary.** 96% of all Mongo writes (319 of 331 insert sites) construct and persist raw Python dicts from unvalidated `Dict[str, Any] = Body(...)` request bodies. The ~95 Pydantic models that exist are frequently decorative — several map to zero write sites — and are duplicated 2–5 times with incompatible field names, types, and enum members for the same concept. This is the root cause of the money-as-float defect (§1.1 of the register) and it is not confined to finance.
3. **Brand is not modeled as a relationship anywhere.** It is a single-valued, *recomputed* classification field on the lead document, overwritten on every enrichment pass. The production consequence is already documented in the register (§4.5): 41,746 enrollment rows across 18,682 people, 9,747 of them enrolled in all three brands simultaneously. The fix that shipped was "first brand wins, forbid the rest" — a policy patch over a missing entity, not a model of the real relationship (one account can legitimately deal with multiple brands; the register's §6-7 requirement for an explicit `AccountBrandRelationship` is not optional).

Everything below is organized to make these three facts actionable rather than to re-litigate them.

---

## 1. Database-level disposition

20 databases were found. Most of the chaos is *inter*-database, not intra-collection — collections with the same name and purpose exist in 2–4 different databases, disagreeing about which is authoritative.

| Database | What it holds | v2 disposition | Why |
|---|---|---|---|
| `crm_db` | The "spine" — accounts, contacts, leads, opportunities, activities, tasks, projects, invoices (mirror) | `REPLACE` | Concept (a canonical CRM store) survives; the current implementation is a best-effort, non-transactional mirror that is simultaneously declared authoritative and copied backward into legacy collections. v2's canonical entity store inherits the *role*, not the code. |
| `email_automation` | The legacy monolith — 4 of the 5 official lead stores, contacts, sales_accounts, suppression #1, campaigns v1, mail pool, RBAC users (one of two) | `MERGE`/`REMOVE` (per-collection, see §2) | No single disposition applies; this database is where most of the duplication concentrates. |
| `finance_db` | AR/AP ledger | `REPLACE` | Concept keeps; storage rebuilt per §1.1-§1.6 of the register (Decimal money, real state machine, credit notes). |
| `campaign_platform` | Panel (panelists, invites, rewards) **and**, by accident of `db_pools.py`'s default, shadow copies of most finance and lead collections that the Celery task layer writes to invisibly | `KEEP` (panel) / `REMOVE` (shadow copies) | The panel data is real and load-bearing (~190K rows). The shadow-copy behavior is D-16 below — it must not exist in v2 in any form; there is no legitimate reason for a background worker to see a different database than the API it supports. |
| `traffic_flow_db` | Survey session/redirect spine (`url_parameters`) | `KEEP`, rebuilt | The traffic session concept is real and necessary; the specific collection is duplicated into `campaign_platform` by the same `db_pools` default and needs the same fix. |
| `cpx_research` | CPX survey supply | **`REMOVE`** *(owner decision 2026-09-05 — see [v2_locked_principles.md](v2_locked_principles.md) §1.10)* | CPX does not exist in v2. Not merged, not adapted. Exception: CPX **payout history** in `traffic_flow_db.survey_transactions` needs an archival/migration disposition rather than a delete — real `amount_usd` records against real panelists. |
| `cint_research`, `survey_allocation` | Two remaining parallel survey-supply inventories | `MERGE` → one canonical survey-supply model with a provider adapter, matching register §2.0's finding that two allocation engines exist and production uses neither correctly | See §2.9. With CPX removed the merge is simpler — but the provider-adapter boundary still matters, since Cint remains and a second supplier may be added later. |
| `torpedo_settings` | Config, RBAC (the *other* users store), approvals, projects/tasks (a third copy), support desk, GPU leases, MCP ledger | `MERGE`/`REPLACE` (per-collection) | RBAC here is the one `RBACService` actually reads (register §5.6) — this is the canonical RBAC store, not `email_automation.users`. |
| `torpedo_gmail` | Gmail/IMAP sync — `email_metadata` is the de-facto real mail pool | `KEEP`, rebuilt | Real operational data; needs one canonical shape (currently mostly unvalidated, per finding 0.2). |
| `torpedo` | Cold-outreach v2 — sends, leads, campaigns, bounce suppression, kill switch | `KEEP`, rebuilt | This is the newest, best-architected send pipeline (register §5.1 Pipeline 2/3) and the closest thing to a v2-ready design already in the codebase. Its suppression collection is the one everything *should* read (register's suppression canonical store), but Pipeline 4 writes to a same-named collection in the wrong database (`campaign_platform`) — see D-07 in the register, confirmed at the mechanism level by this pass. |
| `ai_governance` | Cross-provider AI spend counter, one-classification-per-email guard | `KEEP` | Small, focused, not duplicated. Good model for what a v2 governance store should look like. |
| `linkedin_db` | LinkedIn automation | `REMOVE` or `MERGE` | Duplicates five `email_automation.linkedin_*` collections; the writer is under `backend/deprecated/` — this whole subsystem appears dead. Confirm before removing. |
| `prompt_management`, `operations_db`, `gmail_archive`, `qre_health_survey` | Single-purpose, low-collision | `KEEP` (prompt_management), `EXTRACT` (operations_db — single unpooled-client collection, confirm still used), `REMOVE` (gmail_archive — explicitly labelled legacy/read-only), `KEEP` (qre_health_survey — external system boundary) | — |
| `leads` / `ai_enrichment` | Chosen at runtime by a try/except probe (`mail_segregation_agent.py:76-80`) | `REMOVE` | This is not a database design, it's an accident. Whatever this agent does needs to write to the canonical lead store like everything else. |
| `marketing_db`, `mail_pool`, `email_automation_backup` | Deprecated-tree only | `REMOVE` | — |
| `crm_db_test`, `crm_db_connector_test`, `crm_db_features_test` | Throwaway test databases | `REMOVE` (not real inventory) | — |
| `cpx_db`, `cint_db`, `cint_surveys`, `cpx_surveys` (as database names) | Phantom databases — a collection name passed where a database name was expected | `REMOVE` | These are bugs, not inventory. Each silently creates/reads an empty database. Worth a one-line fix in v1 regardless of the v2 timeline, since they're currently masking failures silently. |

---

## 2. Canonical entity dispositions

### 2.1 Person (all roles)

The register's identity-tracing pass found **15 collections across 6 databases** representing a person in some role. Rather than list all 15 again, here is the disposition by role, since v1's role-as-collection pattern is itself the thing being replaced:

| v1 role-collection | v2 disposition | Becomes |
|---|---|---|
| `crm_db.leads` (declared canonical, but has **no unique index at all**) | `REPLACE` | `Contact` with a `LeadState` facet |
| `email_automation.leads_raw` | `MERGE` into ingestion pipeline, not a persisted entity | Pre-validation staging only, TTL'd |
| `email_automation.leads_enriched` (what the UI actually reads) | `REPLACE` | `Contact` + `LeadState` facet |
| `email_automation.leads` (legacy, still the default migration source) | `MERGE` | Migration source only |
| Store #4 ("outreach_leads") — **has three candidate physical locations depending on which of two conflicting env var defaults resolves**, and the diagnostic endpoint built to count it looks in a fourth | `EXTRACT` first | Cannot be dispositioned until it's established which physical collection is actually receiving writes. This is itself a finding: the codebase's own "how many leads do we have" endpoint (`routers/crm.py:133-179`) is answering the question incorrectly for one of its five rows. |
| `email_automation.email_leads` (keyed on the *email message*, not the person) | `REPLACE` | Becomes an `Activity` linked to a `Contact`, not a separate lead |
| `leads.leads` / `ai_enrichment.leads` (runtime-chosen database) | `REMOVE` | Fold into canonical ingestion once the runtime-selection bug is fixed |
| `email_automation.vendor_leads` | `MERGE` | `Contact` + `VendorProfile` facet |
| `email_automation.contacts` / `crm_db.contacts` | `MERGE` (they're already meant to be the same thing, kept in sync by a bidirectional patch) | `Contact` |
| `campaign_platform.panelists` (~190K rows, real unique index — added *after* 2,974 duplicates accumulated) | `REPLACE` | `Contact` + `PanelistProfile` facet |
| `finance_db.customers` (person subtype) | `MERGE` | `Contact` + `CustomerBilling` facet |
| `finance_db.vendors`, `email_automation.panel_vendors`, `email_automation.vendors` (**three vendor stores, two both called "panel vendors," disagreeing on which the Unified Vendors page reads**) | `MERGE` | `Contact` + `VendorProfile` facet — the two "panel vendors" collections must be reconciled before merge, not merged blind, since a vendor converted from a lead is currently invisible on the page that's supposed to show it |
| `email_automation.users` (auth) | `REPLACE` | `AuthIdentity` facet — currently keyed on `username` with a non-unique sparse email index and **zero links to any other store** |
| Employee | `EXTRACT`/build fresh | **No employee store exists in v1 at all.** Staff exist only as auth users. If v2 needs an `EmployeeRecord` facet distinct from generic auth, it is new construction, not migration. |

**Cross-cutting defect that blocks the merge regardless of order:** none of these stores share a surrogate id. Migration must mint the canonical `Contact._id` first and backfill it everywhere, using email (lowercased) as the only available join key — and email is not unique or even present in several of the stores above.

### 2.2 Company / Account

| v1 store | v2 disposition | Notes |
|---|---|---|
| `crm_db.accounts` | `REPLACE` | Declared canonical; matched by app-level normalized-name string with **no unique index** — collisions are prevented by code discipline, not the database |
| `email_automation.sales_accounts` | `MERGE` | Matched by regex on account_name/company_name |
| `email_automation.accounts` ("Unified Account" — a *third*, independent unification attempt) | `MERGE` | Has `finance_customer_id`/`finance_vendor_id`/`operations_client_id` but **no `crm_account_id`**, and the nightly reconcile never visits it — an orphaned parallel effort |
| `finance_db.customers`, `finance_db.vendors` (company subtype) | `MERGE` | `Account` + `CustomerBilling`/`VendorProfile` facet |
| `email_automation.clients` | `MERGE` | — |
| `ai_discovered_companies`, `company_cache`, `company_enrichment_cache` | `REMOVE` as entities | These are caches, not entities — v2 should not persist them as anything more than TTL'd lookup caches keyed on domain, which is the *only* place in v1 that already keys companies by domain rather than name string |

**The company-name-string matching problem is worse than the person one.** Every cross-store company match in v1 is `_normalize_name()`, a case-insensitive regex, or an exact `find_one({"name": ...})`. Domain is used as a key in exactly three places, all caches, never for the account itself. v2 must decide the canonical match key (domain, where available, with name as fallback) before migration, or the merge will either over-collapse (two different companies with normalized-identical names) or under-collapse (the same company with two name spellings) at scale.

### 2.3 Brand relationship — new entity, not a migration

Per finding 0.3, there is nothing to migrate here — `AccountBrandRelationship` (per the register's §6-7 requirement) does not exist in v1 in any form, field, or collection. The nearest artifacts are:

- `icp_segment` / `classification_basket` on the lead — a recomputed classification, not a relationship
- `business` on the campaign — describes the campaign, not the account
- Three free-text business-unit description files loaded at runtime and routed by an LLM

**v2 build requirement:** `AccountBrandRelationship(account_id, brand_id, relationship_type, status, owner, created_at, updated_at)` as specified in the register/spec §7, populated at migration by the *last known* brand classification per account (since the recomputation history is not preserved), with the "first brand wins" v1 policy explicitly **not** carried forward as a v2 invariant — v2 should allow the real-world case (one account, multiple brand relationships) that v1 had to forbid because it had no way to model it correctly.

### 2.4 Lead → Contact promotion paths (5+ competing implementations)

The identity-tracing pass found **five distinct promotion/conversion code paths** with no shared implementation, each losing different data:

| Path | What survives | Reversible? | v2 disposition |
|---|---|---|---|
| `crm_service.convert_lead` (the spine's own) | Company→account, email/name/title→contact, optional opportunity | No | `REPLACE` — closest to correct; becomes the model for the single v2 conversion path |
| `leads/router.py` "move-to-contacts" | **Nothing is created** — it flips a `stage` field on the same lead document; the "contact_ids" array it populates actually contains lead ids | N/A | `REMOVE` — this is not a conversion, it's a status flag masquerading as one |
| Vendor-leads transfer | ~17 hand-mapped fields; classification/ICP/engagement history all dropped | No | `REPLACE` — becomes attaching a `VendorProfile` facet to the existing `Contact`, not a copy to a new collection |
| `crm_promote.py` RFQ→customer | name/email/notes/AI summary | No | `REMOVE` — manual CLI script, never runs in the app; superseded by real-time facet attachment |
| Mail→RFQ chain (`mail_pool_ai.py`) | Writes 5 documents across 3 databases in one non-transactional sequence | No | `REPLACE` — must become one transactional operation against the canonical entity model |

**v2 invariant this section demonstrates the need for:** a "role" must become a facet attached to the canonical `Contact`/`Account`, never a copy into a role-specific collection. Every v1 promotion path is lossy specifically because it copies a subset of fields into a new place instead of attaching a facet to the same record.

### 2.5 Finance entities (Invoice, Bill, Payment, Customer, Vendor)

Covered in depth by the register (§1). This pass adds one structural finding: **every finance write is a raw dict** (register's C1b: 21 separate `Dict[str, Any] = Body(...)` endpoints in `routers/finance.py` alone) — the `schemas.InvoiceCreate` Pydantic model exists, has sensible field types, and **is never used at any write site**. The v2 rebuild is not "add validation to the existing finance model" — the existing model is decorative and the real behavior lives entirely in the unvalidated endpoint bodies documented in the register.

Disposition: `REPLACE` throughout, per the register's already-decided B-01/B-05 state machine and Decimal-money requirements.

### 2.6 Survey supply (Cint / CPX / allocation)

Three parallel inventories for one concept: `cint_research.cint_surveys`, `cpx_research.cpx_surveys`, `survey_allocation.surveys`. Per the register §2.0, only one allocation engine is architecturally correct (`SurveyAllocationService`) and production doesn't use it. This pass adds: even the *data model* is split three ways before you get to the engine question — `survey_id` is typed `int` in the Cint models and `str` everywhere else, and `SurveyBase.external_id` is a fourth name for the same concept.

Disposition:
- **CPX: `REMOVE` entirely** (owner decision 2026-09-05) — `cpx_surveys`, `cpx_filters`, `cpx_diagnostic_logs`, `cpx_callback_logs`, `cpx_postback_logs`, `cpx_entry_guards`, `routers/cpx_api.py`, `app/routers/cpx.py`, `app/services/cpx_service.py`, the CPX-first allocation branch in `routers/traffic.py`, and the `survey_transaction.*` model module. **Except** `survey_transactions` payout history — archival/migration disposition required, not delete.
- **Cint + allocation: `MERGE`** into one `Survey` entity with a provider-adapter pattern (spec §17: provider-specific behavior belongs in adapters, not parallel domain models), and `REPLACE` the allocation engine per the register's open item on wiring vs. retiring `SurveyAllocationService`.

**One removal-order caution:** the CPX-first allocation branch in `routers/traffic.py` currently *precedes* the Cint path, with Cint acting as the fallback when CPX fails or terminates (register §2.1). Removing CPX does not simply delete a branch — it promotes the fallback to the primary path, including its more permissive quality floors (`MIN_CINT_FALLBACK_IR=0`, `MIN_CINT_FALLBACK_CONV=0`, `MIN_CINT_FALLBACK_CPI=0.05`, adopted on the rationale that "any survey beats terminating the respondent"). Those relaxed floors were chosen for a fallback, not for a primary allocator. Re-deciding them is part of the CPX removal, not a follow-up.

### 2.7 Suppression, dedup, audit — the "prevention" stores

Three families of collections exist specifically to prevent something (duplicate people, duplicate sends, unauthorized changes), and all three families are themselves duplicated:

| Family | v1 stores | Disposition |
|---|---|---|
| Suppression | `email_automation.suppression_list` (canonical, per register), `campaign_platform.panel_email_suppression`, `torpedo.outreach_bounce_suppression` | `MERGE` into one, per register §5.2 — already decided there |
| Dedup | `dedup_index`, `dedup_logs`, `ingestion_log`, `ai_governance.email_classification_guard`, plus a live in-place regex scan with no index collection at all | `REPLACE` with one dedup service; register §4.7 already flags one of these four (`import_gating.py`) as a stub that never actually checks anything |
| Audit | `email_automation.audit_log`, `crm_db.audit_log` (same name, different database, both live), `email_automation.email_audit_log` (orphaned), `torpedo_settings.ai_governance_log` + `email_automation.ai_governance_log` (both orphaned, write-only) | `MERGE` into one append-only `Activity`/audit stream per spec §35 |

### 2.8 Merge capability

v1 has exactly one merge function (`crm_service.merge_accounts`), scoped to accounts only, inside the spine database only. It does not update the external `crm_account_id` back-references on the collections it merged away from, and the nightly reconcile job doesn't exclude `status:"merged"` accounts — so a merged-away account is silently **re-adopted as a fresh account** on the next reconcile run. This is not a gap to fill; it's an active defect (D-18, added to the register below) that would corrupt any migration that trusts the current merge state.

Disposition: `REPLACE`. v2 needs merge capability for every entity type (contacts, leads included, per spec §9 "prevent accidental merging of unrelated people" — currently there is no merge for people at all), and it must be transactional across every collection holding a reference to the merged record, not scoped to one database.

---

## 3. New findings surfaced by this pass

Full text and severity added to [business_rules_register.md](business_rules_register.md#6-defect-register--ranked) as D-15 through D-19, plus invariant I-6. Summarized here for context:

- **D-15 (P0)** — `backend/outreach/router.py:42` injects the database via `db=Depends(get_database)` against a dependency requiring a `db_name` string, which FastAPI exposes as a caller-supplied HTTP query parameter. Any request to that router can redirect writes for `outreach_leads`/`outreach_emails`/`outreach_sequences` and several other collections to an arbitrary database name. This is a write-target injection, not a data-integrity bug.
- **D-16 (P1)** — `db_pools.py` defaults the entire Celery/background task layer to `campaign_platform` via one env var, so ~40 collections written by background tasks are shadow copies invisible to the API layer. Very likely the mechanism behind the finance-reconciliation discrepancy already in the register (§1.8) — the "two different net-profit calculations" may literally be reading two different databases, not just using two different aggregation strategies.
- **D-17 (P1)** — 96% of Mongo writes bypass Pydantic validation entirely (finding 0.2 above). This generalizes the float-money defect beyond finance to the entire backend and is the most consequential single finding for how v2's write path must be built: model-then-persist has to be structurally enforced, not just adopted as a convention, or it will erode the same way it did in v1.
- **D-18 (P1)** — The only account-merge implementation doesn't update external references and is silently undone by the nightly reconcile re-adopting merged accounts as fresh ones.
- **D-19 (P1)** — Brand has no relationship model anywhere in v1; the existing "first brand wins" policy is a workaround for a missing entity, not a design decision to preserve (§2.3 above).

New invariant:

> **I-6 · No write path may persist data that has not passed through a canonical, collection-bound model.** A model that exists but isn't enforced at the write site (v1's `schemas.InvoiceCreate`, never called) provides zero protection. This must be structural — the persistence layer should make it impossible to call `insert_one` with a raw dict — not a lint rule or a review checklist item.

---

## 4. What this unblocks

The schema catalogue (spec §30) can now proceed per-canonical-entity rather than per-v1-collection, using:
- §2 of this document for the entity list and merge sources
- The model-catalogue pass's money-field table and PII-field table (both exhaustive, held in the source report, not reproduced here) as the starting field inventory for each canonical entity
- The register's audit/provenance coverage table (0/48 models have `updated_by`, 1/48 has any version field, 0/48 have a real `deleted_at`) as the gap list against the spec's mandatory six audit fields

Recommended next step: the endpoint catalogue (spec §31) and screen catalogue (spec §32) both depend on knowing the canonical entity list, which this document now provides — either can proceed next.
