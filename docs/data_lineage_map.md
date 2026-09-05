# Torpedo V1 → V2 Data Lineage Map

> Started: 2026-09-05 | Phase 0 final artifact
> Depends on: [v2_locked_principles.md](v2_locked_principles.md) (all ten principles locked), [entity_map.md](entity_map.md) (store-level dispositions), [business_rules_register.md](business_rules_register.md) (defects and business decisions)
> Status: **all six domains populated.** Sixteen new defects (D-24–D-39) and six new business decisions (B-10–B-15) surfaced by this pass are recorded in [business_rules_register.md](business_rules_register.md), not duplicated here. Two open items block nothing in Phase 1 but should not wait for Phase 4: confirm whether `outreach_kill_switch` exists in production (D-28 — it may be the real cause of the outreach pause since 2026-08-25), and confirm no off-system rewards liability exists beyond SFW (B-13) before treating rewards as greenfield.

---

## 0. Governing rules

> **Every retained v1 field must have exactly one v2 owner and an explicit lineage classification.**

> **No field is retained merely because it exists in v1.** Retention must be justified by one of: a verified business requirement, an audit/legal obligation, a migration dependency, or an explicitly approved historical need. A field with no justification is `REJECTED`, and the reason is recorded.

The second rule is the load-bearing one. Without it this exercise becomes a v1 schema migration wearing v2 clothing — which is precisely the failure mode `v2_locked_principles.md` §0 exists to prevent. The default answer for any v1 field is **not** "carry it across."

### Classifications

| Class | Meaning | Implication for v2 |
|---|---|---|
| `AUTHORITATIVE` | v2 canonical source of truth for this fact | Exactly one field per fact may hold this. Two authoritative copies is a defect (I-1). |
| `DERIVED` | Recomputable from authoritative data | Must be recomputable on demand; never the only copy of a fact. Stale derived data is a bug, not a state. |
| `PROJECTION` | Operational/read model | Explicitly labelled as such; never authoritative; may be rebuilt from scratch at any time. |
| `HISTORICAL` | Retained for audit/reconciliation, not active business state | Immutable. Not read by live business logic. Retention period stated. |
| `MIGRATED` | Retained with an explicit transformation | The transformation is specified and testable, not "copy across." |
| `REJECTED` | Deliberately not carried into v2 | Reason recorded. This is the expected default. |
| `OPEN` | Blocked on a remaining Phase 0 decision | Must name the decision (B-xx) it's waiting on. |

### Entry schema

Each row answers, in order:

`V1 DB → V1 collection → field → V2 entity → V2 field → classification → transformation → authority → migration treatment → reconciliation requirement → disposition`

For readability the tables below group `V1 DB → collection` as a heading and carry the remaining columns per row.

### Standing exclusions

Three categories are `REJECTED` wholesale, so they don't clutter every table:

1. **CPX** — removed entirely per locked principle 10. *Exception:* `traffic_flow_db.survey_transactions` payout history is `HISTORICAL` (see Domain 6).
2. **Dead-code stores** — the unused `survey_allocation` engine, `backend/deprecated/**`, the `linkedin_db`/`linkedin_*` subsystem, `gmail_archive`, the phantom databases. Nothing migrates from a store production never wrote to. Each still needs a one-line confirmation it was genuinely unused before deletion.
3. **Caches** — `company_cache`, `search_cache`, `company_enrichment_cache`, MX caches, offerwall caches. All `REJECTED`; v2 rebuilds them empty. A cache that must be migrated is not a cache.

---

## Domain 1 — Identity

**Why first:** every other domain references a person or an account. Getting this wrong propagates everywhere, and per D-22 there is currently no stable identity to inherit — v2 mints it.

**V2 target entities:** `Person` (permanent `person_id`), `Account` (permanent `account_id`), with role facets (`LeadState`, `PanelistProfile`, `CustomerBilling`, `VendorProfile`, `EmployeeRecord`, `AuthIdentity`) and `AccountBrandRelationship`.

**The migration-wide problem, stated once:** no v1 store carries a surrogate person or account id. The only available join keys are lowercased email (people) and normalized company name (companies), and neither is unique or reliably present. Every row below inherits this. **Migration sequence is therefore: (1) mint `person_id`/`account_id` in a crosswalk table, (2) resolve duplicates *before* loading any domain data, (3) load facets against resolved ids.** No domain 2-6 migration can begin until the crosswalk is built and reconciled.

### `email_automation.leads_enriched` → `Person` + `LeadState`

*The store the UI actually reads. ~22K rows. Richest lead record; also the most polluted.*

| V1 field | V2 entity.field | Class | Transformation | Authority | Migration | Reconciliation |
|---|---|---|---|---|---|---|
| `email` | `Person.primary_email` | `MIGRATED` | lowercase, trim; becomes crosswalk join key, **not** the identity | Authoritative for the address; **not** for identity | Load after `person_id` minted | Count of distinct lowercased emails vs. persons created must match exactly |
| `first_name`, `last_name`, `name` | `Person.given_name`, `.family_name` | `MIGRATED` | Three overlapping fields collapse to two; prefer split fields, fall back to parsing `name` | `AUTHORITATIVE` | Transform + manual review queue where parsing is ambiguous | Non-null name coverage before vs. after |
| `linkedin_url` | `Person.linkedin_url` | `MIGRATED` | Normalize (strip protocol/www/country-subdomain/query). **Reject `mailto:` values** — `crm_promote.py` wrote synthetic `mailto:{email}` values here to satisfy a unique index | `AUTHORITATIVE` | Filter synthetic values to `REJECTED` with reason | Count of `mailto:` values excluded, reported not silently dropped |
| `title`, `phone`, `location`, `timezone` | `Person.*` | `MIGRATED` | Direct | `AUTHORITATIVE` | Direct | Null-rate comparison |
| `email_status` | `LeadState.email_verification_status` | `MIGRATED` | 7-member v1 enum → v2 enum; **`Predicted` and guessed-provenance values must map to unverified**, per the register §4.4 incident where 2,888 guessed addresses sat under clean statuses | `AUTHORITATIVE` | Explicit mapping table, no default-passthrough | Every v1 value must appear in the mapping or fail the migration |
| `email_pattern_confidence`, `email_source` | `LeadState.email_provenance` | `MIGRATED` | Collapse into one provenance object; **missing confidence fails closed** (unverified) | `AUTHORITATIVE` | Direct | Count of fail-closed rows |
| `seniority_level`, `department`, `persona`, `buying_role`, `company_size`, `region` | `LeadState.classification.*` | `MIGRATED` | Each is a v1 enum with 2-3 conflicting definitions across modules (register C2) — one canonical enum per concept, explicit mapping | `AUTHORITATIVE` | Mapping table per enum | Unmapped value = migration failure, not a null |
| `gender` | — | `REJECTED` | — | — | Not migrated | **Reason: AI-inferred protected characteristic, never consented, no business requirement identified.** Retaining inferred special-category data by default is exactly what rule 2 exists to prevent. Flag for legal review if any consumer is found. |
| `confidence_score` | `LeadState.classification.confidence` | `MIGRATED` | Unconstrained float in v1 → constrained 0-1 | `DERIVED` | Direct, clamp + report out-of-range | Out-of-range count must be 0 after |
| `icp_segment`, `classification_basket`, `classification_basket_name` | `LeadState.icp_segment` (single) | `MIGRATED` | Three overlapping fields → one. **Recompute on the canonical `icp_config.py` 3/2/2/1 scale per decision B-04** — do not copy stored scores; the three v1 scorers used incompatible scales | `DERIVED` (recomputable) | Recompute, don't copy | Distribution comparison v1 vs. recomputed, with drift explained not just measured |
| *(brand, implied by basket)* | `AccountBrandRelationship` | `MIGRATED` | **Field → relationship.** Last-known basket becomes one relationship row; the v1 "first brand wins" restriction is **not** carried forward (D-19) | `AUTHORITATIVE` | Construct relationships | Count of accounts with >1 brand relationship — expected to be non-zero, and that is correct, not an error |
| `email_threads[]` (full bodies embedded) | `Activity` (separate collection) | `MIGRATED` | **Unembed.** Full email bodies inside the lead document are unbounded growth + PII concentration | `AUTHORITATIVE` (as Activity) | Extract to Activity stream | Message count preserved; body byte-count preserved |
| `engagement_score`, `engagement_status`, `sequence_stage`, `outreach_history[]`, `last_outreach_date`, `reengagement_*` | `LeadState.engagement.*` | `DERIVED` | Recomputable from the Activity stream and send log | `DERIVED` | **Recompute from Activities, don't migrate** | Recomputed vs. stored must agree within a stated tolerance; disagreement is a finding about v1, not a migration bug |
| `campaign_ids[]`, `rfq_ids[]` | Relationships | `MIGRATED` | Arrays of ids → join rows | `AUTHORITATIVE` | Direct | Referential integrity: every id must resolve |
| `raw_lead_id`, `enriched_lead_id`, `crm_lead_id` | Crosswalk table only | `HISTORICAL` | Retained in the migration crosswalk for traceability, **not** on the v2 entity | — | Crosswalk only | Every v1 row traceable to its v2 `person_id` |
| `classification_version`, `classified_at`, `enriched_at`, `enrichment_source` | `LeadState.provenance.*` | `MIGRATED` | Direct | `HISTORICAL` | Direct | — |
| `company_*` (14 fields, denormalized) | `Account.*` | `MIGRATED` | **Denormalized company data → the Account entity.** `company_last_funding_round_amount` is typed `str` in v1 — parse to money or reject | `AUTHORITATIVE` (on Account) | Extract, dedupe by domain then name | One Account per resolved company; count reported |
| `assigned_to`, `last_touched_by`, `team_id` | `LeadState.ownership.*` | `MIGRATED` | Direct; resolve to v2 user ids | `AUTHORITATIVE` | Direct | Every owner id must resolve to a real user |
| `snippet`, `added_on`, `source` | `LeadState.source_metadata.*` | `MIGRATED` | Direct | `HISTORICAL` | Direct | — |

### `email_automation.leads_raw` → staging only

| V1 field | V2 | Class | Notes |
|---|---|---|---|
| *(all fields)* | — | `REJECTED` | Pre-validation staging. Its content is already reflected in `leads_enriched` via `enriched_lead_id`. **Exception:** rows with **no** `enriched_lead_id` are unpropagated leads — these need a one-time reconciliation report before deletion, because they may represent data that never made it downstream. That report is a migration deliverable, not the data itself. |

### `campaign_platform.panelists` → `Person` + `PanelistProfile`

*~190K rows — the largest person store, and the one with the strongest uniqueness guarantee (unique email index, added after 2,974 duplicates had already accumulated).*

| V1 field | V2 entity.field | Class | Transformation | Authority | Migration | Reconciliation |
|---|---|---|---|---|---|---|
| `email` | `Person.primary_email` | `MIGRATED` | Lowercase. **Join key against `leads_enriched`** — a person who is both a B2B lead and a panelist is currently two unrelated documents in two databases (entity_map §2.1); this migration is where they become one `Person` | `AUTHORITATIVE` | Merge into existing `person_id` where email matches | **Critical metric:** count of panelist↔lead identity merges. Expected non-zero. Each merge must be reviewable. |
| `first_name`, `last_name`, `country`, `language` | `Person.*` | `MIGRATED` | Direct | `AUTHORITATIVE` | Direct | — |
| `password_hash` | `AuthIdentity.credential` | `MIGRATED` | Direct, no rehash | `AUTHORITATIVE` | Direct | **223,951 of 224,002 have none** — registration happens on the external SFW system. Coverage must be reported, not silently accepted |
| `rewards_balance` | `PanelistProfile.balance` | `OPEN` | Blocked on the reward-ledger design (B-02 made Torpedo system of record; the ledger doesn't exist yet) | Will be `DERIVED` from the ledger, never authoritative (I-3) | **Do not migrate as a stored balance.** Migrate as an opening ledger entry | Sum of opening entries must equal the SFW-reported balance per panelist, reconciled before cutover |
| `status`, `double_opt_in_completed`, `verification_token*` | `PanelistProfile.*` | `MIGRATED` | Direct; **verification tokens with no TTL in v1 must get one in v2** | `AUTHORITATIVE` | Direct; expire stale tokens at migration | Count of tokens expired at migration |
| `sfw_*` (mirrored external state) | `PanelistProfile.external_state` | `PROJECTION` | Explicitly labelled as a mirror of the external SFW system | External system is authoritative | **Re-fetch, don't migrate** | Post-migration refresh must succeed for every panelist |
| `last_invited_at`, `invite_clicked_at`, `last_login_invite_sent_at` | `Activity` | `MIGRATED` | → Activity stream | `HISTORICAL` | Direct | — |

### Person stores that do not become people

| V1 store | Class | Reason |
|---|---|---|
| `email_automation.email_leads` | `MIGRATED` → `Activity` | Keyed on the *email message*, not the person. One row per email received, no person-level key. Becomes Activities linked to `Person`, never a person record. |
| `email_automation.leads` (legacy) | `MIGRATED` | Migration source only; superseded by `leads_enriched`. Rows with no `leads_enriched` counterpart need the same unpropagated-rows report as `leads_raw`. |
| `leads.leads` / `ai_enrichment.leads` | `REJECTED` | The database was chosen by an import-time try/except probe (D-21). Content must be verified as duplicated elsewhere before deletion — if it isn't, this becomes a real migration source and the probe bug means we don't currently know which database it's in. |
| `crm_db.leads`, `crm_db.contacts` | `MIGRATED` | The spine is a derived mirror (D-20), not authoritative. Use only where it holds data no source store has. |
| `email_automation.contacts` | `MIGRATED` | Merges with `crm_db.contacts` — already meant to be the same thing, kept in sync by a bidirectional patch. |
| `email_automation.users` | `MIGRATED` → `AuthIdentity` | Keyed on `username`, non-unique sparse email, **zero links to any other store**. Linking staff auth identities to `Person` records is new construction. |
| Employee records | — | **Does not exist in v1.** `EmployeeRecord` is new construction, not migration. |

### Account stores

| V1 store | Class | Transformation | Reconciliation |
|---|---|---|---|
| `crm_db.accounts` | `MIGRATED` | Primary account source. **No unique index in v1** — collisions prevented by code discipline only, so expect duplicates | Duplicate-detection report before load |
| `email_automation.sales_accounts` | `MIGRATED` | Merge by `crm_account_id` where present, else normalized name | Unlinked rows reported |
| `email_automation.accounts` ("Unified Account") | `MIGRATED` | A third unification attempt with **no `crm_account_id`** and never visited by the reconcile — likely holds links nothing else has (`finance_customer_id`, `operations_client_id`) | Every link it holds must be preserved or explicitly rejected |
| `finance_db.customers` / `.vendors` | `MIGRATED` | → `Account` + `CustomerBilling`/`VendorProfile` facet | Financial totals must reconcile — see Domain 2 |
| `email_automation.clients` | `MIGRATED` | Merge | — |
| `email_automation.vendors` vs `panel_vendors` | `OPEN` | **Two collections both called "panel vendors," read by different pages.** A vendor converted from a lead lands in one and is invisible on the page reading the other. Which is authoritative is unresolved | Blocked: needs the two reconciled before merge, not merged blind |
| Company caches (3) | `REJECTED` | Rebuilt empty | — |

### Domain 1 — open items

| Item | Blocking | Owner |
|---|---|---|
| Company match key — domain (where available) vs. normalized name | The whole Account merge. Over-collapse and under-collapse are both live risks at scale (entity_map §2.2) | Engineering, with a sample-based accuracy report |
| `panel_vendors` vs `vendors` authority | Vendor facet migration | Business owner |
| `rewards_balance` opening-entry design | Panel migration | Blocked on B-02's ledger design |
| Unpropagated `leads_raw` / legacy `leads` rows | Deletion of those stores | Reconciliation report first |

---

## Domain 4 — Survey allocation & Domain 6 — External-integration state

**V2 target entities:** `Survey`, `SurveyResponse`, `Supplier`, `TrafficSource`, provider adapters.

The governing distinction for these domains is **who owns the truth**. Most of what v1 stores about surveys is a *cache of Cint's state*, and migrating a cache of someone else's data imports staleness as fact. The split below is therefore between re-fetch and migrate, not between keep and drop.

### 4.1 Re-fetch, do not migrate — external-owned

| V1 store / fields | Class | Reason | Reconciliation |
|---|---|---|---|
| `cint_research.cint_surveys` — the entire provider-sourced block: `total_remaining`, `revenue_per_interview`, `revenue_per_click`, `conversion`, `mobile_conversion`, `completion_percentage`, `overall_completes`, `survey_quotas`, `survey_qualifications`, `is_live`, `message_reason` | `PROJECTION` | Cint owns every one of these. **Refresh guarantee: none.** The feed is push-only, so a survey that goes quota-full without a `deactivated` push stays "live" in Torpedo indefinitely. Migrating this imports a snapshot of a system that has moved on. | Post-cutover: re-subscribe the opportunities webhook, then compare inventory count and quota totals against the pre-cutover snapshot; explain differences rather than assume them |
| `cint_research.cint_entry_links` (all) | `REJECTED` | Every link is re-creatable, **and** the four callback URLs embed a hardcoded `torpedo.cogentixresearch.com` base that v2 must change anyway. Migrating them would carry v1's hostname into v2. | Link-generation smoke test per active survey |
| `cint_surveys.raw_data` (Fulcrum rows) | `REJECTED` | Stale provider blob. **Caveat before dropping:** `activation_service.py:236-241` reads `raw_data.RPI.value` as a money fallback — confirm no row depends on it. | Confirm zero rows rely on the fallback |
| Gmail sync cursors (`last_history_id`, `historic_sync_cursor`) | `REJECTED` | Google invalidates these independently; migrating them causes a 404-resync on first use regardless. Set null, let backfill run. | Backfill completes for every mailbox |
| `survey_allocation.*` (whole database — `respondents`, `surveys`, `survey_metrics`, `allocation_log`) | `REJECTED` | Dead engine, confirmed: `main.py` injects the service into the traffic router and **`traffic.py` never calls it**. `surveys` is 100% derived from `cint_surveys` anyway; `allocation_log` is TTL-30d so it isn't durable audit either. | One-line confirmation of non-use before deletion |

### 4.2 Migrate — genuinely Torpedo-owned

| V1 store / fields | V2 | Class | Transformation | Reconciliation |
|---|---|---|---|---|
| `traffic_flow_db.url_parameters` (the session spine) | `TrafficSource` / session record | `MIGRATED` | **Three normalizations are mandatory during migration, not after:** (1) `updatedAt` is written as `datetime` by one path and ISO **string** by five others — a sweep task already has to `$or` over both BSON types to work around it; (2) `status` is UPPERCASE from every current writer but **lowercase** from the legacy Flask writer (`complete`/`terminated`/`quotafull`); (3) `cint_revenue` is taken straight off a URL query string and **stored unparsed as a string** — money-as-string on the highest-volume collection in the system | Row count; type-uniformity assertion per field; sum of parsed `cint_revenue` vs. string-parsed original |
| `cint_research.cint_metrics` | `Survey.metrics` | `MIGRATED` | Torpedo-computed session accounting Cint cannot reproduce (`entrants_n`, `completions`, `terminations`, `overquota_n`, `quality_term_n`, `abandoned_n`, `internal_conversion`, `global_conv_at_deactivation`, `deactivation_reason`). **Fix the `survey_id` `str`/`int` split during migration** — it is written as `str` by four call sites and `int` by two, so the unique index admits two documents per survey | Document count per survey must be exactly 1 after; pre-migration duplicate count reported |
| `cint_research.cint_respondent_outcomes` | `SurveyResponse` | `MIGRATED` | **Cint's outcomes subscription is a push stream with no history endpoint — this is Torpedo's only copy of per-session payout.** Cannot be re-fetched at any price | Row count + payout sum preserved exactly |
| `cint_research.cint_buyer_stats` | `Supplier.performance` | `MIGRATED` | Rolling conversion computed purely from Torpedo's own callbacks; not re-derivable without replaying every callback. **Rekey off `buyer_id` (int) rather than the provider display-string `buyer_name`** — a buyer rename currently forks the stats into a new document silently | Conversion rates preserved; count of buyers where rekeying merged forked documents |
| `cint_surveys.is_active_in_pool`, `activated_at`, `manually_toggled`, `toggled_at` | `Survey.eligibility.*` | `MIGRATED` | Torpedo's own eligibility decisions (six distinct writers), not re-derivable — **migrate these fields even though the rest of the document is re-fetched** | Active-pool membership count preserved |
| `cint_surveys.predicted_score`, `_confidence`, `_reasoning`, `_task_id` | `Survey.cold_start_score.*` | `MIGRATED` | AI-generated cold-start scores. Irreproducible without re-running the model | Coverage count; or accept re-scoring cost and `REJECT` instead — an explicit choice either way |

### 4.3 Findings this extraction surfaced (added to the register)

- **D-24 (P1, live data-loss bug):** `cint_surveys.click_count` is seeded to `0` and the **only** code that increments it lives in the dead allocation engine. So in production it is permanently `0` — which means `cleanup_unclicked_surveys` deletes essentially every survey older than three days on the grounds that nothing clicked it. A cleanup job whose input is structurally always zero is deleting live inventory.
- **D-25 (P2, data destruction):** `length_of_interview` — the provider's *actual* LOI — is overwritten with `bid_length_of_interview` (the estimate) before validation. The real value is destroyed on ingest and cannot be recovered.
- **`amount_local` has no currency code field anywhere on the document** — recorded under the CPX payout-history retention below, because it makes those amounts uninterpretable in isolation.

---

## Domain 6 addendum — the CPX removal has a hard dependency chain

This extraction found a constraint that **materially changes how the locked CPX removal must be executed.** The decision stands; the execution plan does not survive contact with it unmodified.

### The chain

`survey_transactions.subid` → `url_parameters._id`. The CPX vendor-forwarding path resolves the CPX `subid_1` as an ObjectId against `url_parameters`, reads `vendorId` off it, then resolves the vendor record to build the postback.

**Therefore: retaining `survey_transactions` for audit (locked principle 10, consequence 2) *forces* retention of the matching `url_parameters` rows.** Purge the CPX-sourced sessions and every retained payout row loses its respondent and its vendor — the money becomes unattributable, which defeats the entire purpose of retaining it.

### Four further couplings into surviving data

| Coupling | Consequence of naive deletion | Required treatment |
|---|---|---|
| `url_parameters.assignedSurveyId` points at a **CPX survey `_id`** for historical CPX sessions, with `surveySource: "CPX"` as the discriminator | Deleting `cpx_research.cpx_surveys` orphans the pointer on every historical CPX session — FK target vanishes, pointer remains | **Explicit choice required:** null the pointer, or snapshot the CPX survey name onto the traffic row before deletion. Recommend the snapshot — it preserves readability of history |
| `url_parameters.status == "CPX_TERMINATED_CINT_FALLBACK"` — a **CPX-named value inside the surviving status enum** | v2's status vocabulary cannot simply drop the token or those sessions become unclassifiable | Keep for historical rows, or remap during migration. Not droppable |
| `traffic_flow_db.cpx_entry_guards` — despite the name, this is keyed on the **vendor's `rid`, not any CPX identifier**. It is a respondent-identity single-use fraud ledger carrying `client_ip`, `user_agent` and a `duplicate_attempts` array | Deleting it with CPX discards a **reusable, non-CPX-specific fraud control** that Cint will need in v2 | **Rename and keep the mechanism.** This is misfiled under CPX, not owned by it |
| `survey_transactions.vendor_id` → `email_automation.vendors.vid` | Billing-side FK on the payout row | Vendors survive; preserve the FK |

### CPX payout history — retention detail

`traffic_flow_db.survey_transactions` is `HISTORICAL`, immutable, read-only. Two problems to resolve at migration:

1. **`amount_local` has no currency-code field anywhere on the document.** A local-currency amount with no currency is not an auditable financial record. Either recover the currency from the CPX-side data before archiving, or explicitly annotate the archive as USD-only-interpretable.
2. **`ip_address` sits on a financial record** — a direct retention conflict: audit obligation says keep the money row, data-protection says purge the IP. **Recommend splitting the PII field off at migration**, keeping the financial row indefinitely and the IP under the normal retention clock.

Also retain **`cpx_postback_logs`** — the append-only receipt trail *including failed hash-validation attempts*, which is the fraud-side counterpart to the ledger and the evidence base for D-23.

---

## Domain 3 — Email, outreach & suppression

**V2 target entities:** `Message`, `Thread`, `Suppression`, `Campaign`, `SendLogEntry`, `Mailbox`.

### 3.1 Suppression — the merge is safe, the metadata is not

**The good news, and it is genuinely good:** the three suppression stores agree on exactly one field — `email` — and **no enforcement path reads any other field.** Every suppression check in the codebase tests existence only. So a union keyed on normalized `email` can be performed with **zero behavioural change**.

| Concept | canonical `suppression_list` | `panel_email_suppression` | `outreach_bounce_suppression` | Treatment |
|---|---|---|---|---|
| `email` | lower+strip, unique idx | lower+strip, unique idx | **`.lower()` only, no `.strip()`**, no unique index | `MIGRATED` — re-normalize torpedo rows; expect a tail of whitespace-duplicated addresses that currently never match |
| when suppressed | `suppressed_at` (naive UTC) | `suppressed_at` (**naive OR tz-aware** — SES supplies aware) | **`bounced_at`** (different name) | `MIGRATED` — rename to one field, normalize tz. **`bounced_at` is semantically wrong** for manual and unsubscribe rows, which are stamped with it anyway |
| why suppressed | `reason` — 5 values, unenforced (writer A) / 4-value `Literal`, enforced (writer B) | `reason` — free string; SES writes AWS vocabulary (`bounce`, not `bounced`) | `reason` — present on only 2 of 4 writers; `manual` is client-supplied free text | `OPEN` — **three disjoint vocabularies.** A naive union breaks on `bounce` vs `bounced` alone. See D-27 below |
| campaign link | `source_campaign_id` (writer B only) | — | `bounced_campaign_id` (one writer) | `MIGRATED` — same concept, two names, neither ever read. Pick one |
| actor | `suppressed_by` (default `"system"`) | absent | absent | `MIGRATED` — backfill `"legacy"` |
| `metadata` blob | `{}` | `{}` | — | `REJECTED` — orphaned in both, never read |
| `bounce_subject` | — | — | `str[:200]`, **PII** | `REJECTED` — orphaned; a real message subject line retained for no consumer |

**D-27, the finding that blocks a clean merge:** `messaging/suppression.py:184` `$set`s `reason` unconditionally. An address that **unsubscribed** and later **bounced** now reads `bounced`. The legal basis for the suppression has been overwritten by a deliverability fact. This is not a migration nuisance — it means "who opted out, and when" is currently unanswerable for any address that subsequently bounced.

> **Business decision required (B-10):** is `reason` a single current value, or an append-only list of suppression *events*? v2 must model it as events — an opt-out is a legal fact that a later bounce cannot revoke. Migration cannot reconstruct what was overwritten, so the answer also determines whether a one-time "unknown provenance" backfill flag is needed on every existing row.

### 3.2 Send log & outreach v2 — one collection, two incompatible schemas

`torpedo.outreach_sends_v2` has two writers with entirely different vocabularies for the same facts: the live router path (`email`, `gmail_message_id`, `gmail_thread_id`, `clicks[]` as dicts) and the validated `EmailSend.model_dump()` path (`to_email`, `provider_message_id`, `thread_id`, `clicked_links[]` as strings). Consequences:

| Finding | Class | Treatment |
|---|---|---|
| `mailbox_id` is written only by the model path, but `mailbox_manager.py:370-379` computes `bounce_rate_24h` by querying on it — against router-written docs the query matches **zero** documents, so **bounce-rate auto-pause never fires** (D-30) | — | Defect; v2 needs one shape and a test that the safety control actually triggers |
| `workflow_step` is **0-indexed** on the send record while `current_step` is **1-indexed** on the lead | `OPEN` | Every funnel metric depends on which convention v2 adopts. Off-by-one trap — must be decided, not inferred |
| `outreach_leads_v2.workflow_status` — **15+ free-string values across 17 write sites**, including four distinct "skipped" states that all mean "not sent, might retry" and one (`error`) that means "never again" | `OPEN` | Needs a canonical state machine before it can be typed. Highest-risk migration field in the domain |
| `reply_snippet` (300 chars of the customer's reply body) persisted into the send log | `MIGRATED` → `Message` | **Contradicts the no-bodies policy** the same domain states elsewhere. Belongs in the Message/Thread entity under one retention rule, not in a send record |
| `clicks[]` — unbounded array appended from an unauthenticated public endpoint (D-31) | `MIGRATED` → `Activity` | Click events belong in the Activity stream with a bounded write path, not as an unbounded array on the send document |
| `unsubscribed`, `sendable`, `dual_fit_sequence_index`, `personalization_level`, router-written `daily_sent_count`/`hourly_sent_count` (D-32) | `REJECTED` | All orphaned — written, never read by any path that matters, or permanently `0` due to a spelling divergence |

### 3.3 Email bodies — one policy decision that reshapes four collections

The codebase currently holds **three contradictory positions inside one domain**:

- `messaging/log.py:12-16` — deliberately stores **no** bodies, by explicit documented policy. *This is the reference pattern.*
- `email_sync.EmailDocument`, `gmail_workspace_service`, `outreach_engine.EmailSend` — persist **full `body_plain` + `body_html`**, unbounded, no TTL.
- `cold_outreach_router.py:3473` — persists a 300-char slice of inbound replies into the send log.

Plus `raw_headers` retains `Received:` chains containing **originating IP addresses** and User-Agent strings, described in the model as "for debugging."

> **Business decision required (B-11):** does v2 retain message bodies, and for how long? This is one decision that changes the shape of four collections and the entire PII surface of the platform. Note that "keep them" is a defensible answer — thread context has real product value — but it must be a decision with a retention period attached, not an accident of which service happened to write the row.

### 3.4 Mailbox registries & secrets

Three competing registries (`torpedo_gmail.mailboxes`, `torpedo_gmail.workspace_mailboxes`, `torpedo.outreach_mailboxes`), each declaring its own uniqueness, each holding a different subset of the same real mailboxes, with `is_active` able to disagree across them and nothing reconciling.

| Item | Class | Treatment |
|---|---|---|
| Which registry is canonical | `OPEN` | Business/ops decision — see B-12 |
| `smtp_password`, `aws_access_key_id`, `aws_secret_access_key`, OAuth `access_token`/`refresh_token`, service-account `private_key` | **`REJECTED`** | **Do not migrate secrets.** v2 forces re-authentication and stores credentials by reference (`credentials_id` — the indirection v1 already modelled and never used). Migrating them carries cleartext secrets into a new system and inherits D-26 |
| `token_expiry` sits beside `access_token` with **no TTL index** — expired tokens persist indefinitely | `REJECTED` | Dropped with the secrets |

### 3.5 The kill switch — a live operational finding

`outreach_kill_switch` is **read** as the global send gate and **fails safe to paused when the document is missing** — but **no code anywhere in the repository writes it** (D-28).

This has a direct operational reading worth checking against production immediately: if that document does not exist, **outreach sending is currently gated off**, and has been for as long as that has been true. Project memory records outreach campaigns as paused since 2026-08-25 with the cause attributed to a Bedrock/AI outage. These may be the same incident seen from two ends — or two separate causes that have been conflated. **Verifying whether `outreach_kill_switch` exists in production is a five-minute check that could explain a three-month pause.** It is not a migration question; it is a today question.

---

## Domain 2 — Finance & rewards

**V2 target entities:** `Invoice`, `Bill`, `Payment`, `CreditNote`, `Expense`, `PurchaseOrder`, `Estimate`, `RewardLedgerEntry`, `CustomerBilling`, `VendorProfile`.

### 2.1 Rewards — there is nothing to migrate

**Exhaustive search found zero write sites for `panel_rewards` anywhere in the codebase.** Every reference is a read. The collection is indexed, queried by six separate readers, and rendered in the panel UI — over an empty collection. Combined with `rewards_balance` being initialised to `0.0` by three writers and **never incremented or decremented by any code path**, the conclusion is unambiguous:

> **The rewards domain has no persisted state whatsoever.** `totalRewardsIssued`, `totalRedeemed`, `pendingRedemptions`, every panelist's history, and every balance return `0`/`[]` unconditionally.

| V1 source | Class | Treatment |
|---|---|---|
| `panel_rewards` (inferred schema: `panelist_id`, `type`, `amount`, `description`, `status`, `created_at`) | `REJECTED` | Nothing to migrate. The inferred schema is useful as *input to the v2 ledger design*, not as a migration source |
| `panelists.rewards_balance` | `REJECTED` | Permanently `0.0` for every panelist. Do not migrate a field that has never held a real value |

**This sharpens decision B-02 rather than changing it.** Torpedo becoming the system of record for rewards is not a migration — it is **100% greenfield construction**, and the opening balances must come from the external SFW service, not from anything in this database.

> **Confirm before building (B-13):** that no rewards liability exists off-system beyond what SFW holds. If panelists have accrued balances anywhere else, that source must be identified now, because this database will not reveal it.

### 2.2 Finance — the canonical-field problem

Four to five writers per collection, each with a different vocabulary. The migration cannot proceed until these are resolved, because they are not naming preferences — they change which rows appear in financial reports.

| Conflict | Consequence | Class |
|---|---|---|
| **`total` vs `total_amount`** — API path writes `total_amount`; CSV importers and `rfq.py` write `total`; Zoho seeders write both | The dashboard aggregates `$total_amount` only, so **every CSV- and RFQ-originated invoice and bill is invisible to revenue reporting** (D-36) | `OPEN` |
| **`tax_total` vs `tax_amount`** | Same shape of problem; the UI reads `tax_total ?? tax_amount` and papers over it | `OPEN` |
| **`items` vs `line_items`** — `rfq.py` writes `line_items`, everything else writes `items`, the UI reads only `items` | **RFQ-converted estimates and invoices display no line items today** | `OPEN` |
| **Date storage type** — `datetime` (CSV/seeders), `"YYYY-MM-DD"` string (`operations.py`, browser-posted API), `date` under a different name (`rfq.py`) | Sorts and range queries silently mis-order. The overdue query compares `due_date` against `today.isoformat()` — a string comparison that only works because some rows happen to be strings | `MIGRATED` — canonical type + backfill, mandatory |
| **`currency` vs `currency_code`** — the spine mirror reads `currency` defaulting to **`"USD"`**; every UI path uses `currency_code` defaulting to **`"INR"`** | Invoices mirrored to CRM without explicit currency are labelled USD | `MIGRATED` |

### 2.3 Finance — money fields

| V1 field | V2 | Class | Treatment |
|---|---|---|---|
| `subtotal`, `tax_total`, `total_amount`, `balance_due`, `amount_paid` (all collections) | `Invoice.*` / `Bill.*` as `{amount_minor: int, currency: ISO4217}` | `MIGRATED` | Float → integer minor units. **`balance_due` can currently go negative** (overpayment unguarded); those rows need explicit review, not silent conversion |
| `total_receivables`, `total_payables`, `total_paid` (customer/vendor running totals) | — | `DERIVED` | **Do not migrate.** Recompute from the invoice/payment ledger. These are `$inc`-maintained scalars that (a) start as `int 0` and become float, (b) are never adjusted on invoice update, and (c) sum **INR, USD and EUR together with no FX normalisation** (D-38). They are not recoverable as facts; they are recomputable as derivations |
| `opening_balance` (customers, vendors) | `OPEN` | — | Captured, never read, never folded into the running totals. **Every reported AR figure depends on whether a customer's true balance is `opening_balance + total_receivables` or just the latter.** Needs an accountant's answer (B-14) |
| `tds_amount` | `OPEN` | — | Present **only** on Zoho-seeded invoices; renderable in the UI but not enterable; absent entirely from bills. Ties directly to B-06 (is TDS required?). If yes, this is the only existing data and it is partial |
| `payments_received.amount` / `payments_made.amount` | `Payment.amount` | `MIGRATED` | **Audit before migrating** — the field is unvalidated raw JSON (D-33), so existing rows may contain strings or non-finite values. Type-scan first, quarantine anything non-numeric |

### 2.4 Finance — fields rejected

| V1 field | Reason |
|---|---|
| `customers.shipping_address`, `customers.same_as_billing` | Pure UI form state leaking into the database; zero readers |
| `customers.ai_summary` | LLM prose, zero readers |
| `zoho_customer_id`, `external_invoice_id`, `external_bill_id`, `customer_zoho_id` | Migration-provenance from a prior import, zero readers. **Retain in the migration crosswalk, not on the entity** |
| `items.low_stock_threshold`, `items.stock_quantity` | Inventory tracking is declared but never implemented — `stock_quantity` is never decremented by any invoice, bill or PO write |
| `expenses.vendor_id`, `expenses.is_billable` | Written, never joined or read; no re-billing path exists |
| `bills.items[].account` | Zoho GL account name; no writer other than the seeder, no reader |
| `branch` | A reporting dimension with no master data, no API path and no reporting. Needs a keep/discard decision (B-15) before it is dropped, since it *is* rendered in two detail pages |

### 2.5 Panel — duplicate and shadow state

`panelists` carries overlapping facts with no reconciliation rule: `country`/`sfw_country`, `last_login`/`sfw_last_login`, computed `profile_completion`/persisted `sfw_profile_complete`, and **four fields encoding one opt-out fact** (`status: "dnd"`, `dnd`, `unsubscribed`, `unsubscribed_at`).

- The `sfw_*` fields are `PROJECTION` — mirrored external state, **re-fetch, don't migrate**.
- The opt-out cluster collapses to one `Suppression` record (Domain 3), `MIGRATED`.
- **`drip_{stage}_count` / `drip_{stage}_last_sent_at` use dynamically constructed field names.** The complete field set is **not statically knowable** — it must be discovered by scanning production data before the v2 panelist schema can be finalised. This is a migration blocker, not a detail.
- `panel_sessions` — `REJECTED`. No index, no TTL (D-39). Purge on migration; force re-authentication rather than carrying live bearer credentials across.

---

## Domain 5 — Tenancy & brand

Covered in Domain 1 (`AccountBrandRelationship`). **No separate v1 source exists to map** — brand is not a stored relationship anywhere, only a recomputed classification field. This domain is entirely new construction (D-19).
