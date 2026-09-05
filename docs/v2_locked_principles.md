# Torpedo v2 — Locked Architecture Principles

> Generated: 2026-09-05 | Phase 0 deliverable, sits above [business_rules_register.md](business_rules_register.md) and [entity_map.md](entity_map.md)
> Status: **all ten principles LOCKED** (owner, 2026-09-05).
> Locked means: Phase 1 design proceeds from these, and any v2 code or schema that violates one is a defect by definition, not a trade-off to be argued per-case.

## 0. The directive this document exists to enforce

> **Do not rebuild the v1 database structure.**
>
> The v1 database inventory (`entity_map.md`) is forensic evidence, not a target architecture. Every v1 database, collection, model, index, mirror, cache, projection, environment-selected store, and runtime-selected store is untrusted until explicitly classified against the principles below.
>
> The objective is not to preserve the number of databases or collections. It is to preserve verified business behaviour while eliminating duplicated identity, competing sources of truth, lossy conversions, split-brain writes, unsafe runtime database selection, and unreconciled external state.

This reframes what `entity_map.md` already showed but is worth stating as its own conclusion: **`crm_db` is not a canonical source of truth. It is one of several derived representations that happens to be labelled canonical.** Its own reconcile job copies data *backward* into the collections it's supposed to supersede, because the UI reads those instead. Nothing in v1 is currently trustworthy as "the" answer for identity, and v2's job is to build that, not to inherit whichever store currently has the most callers.

---

## 1. The ten principles

Each maps to what's already in the register/entity-map, or is flagged as genuinely new below.

### 1. One canonical identity
`Person` gets a permanent `person_id`; `Account` gets a permanent `account_id`. Auth identity, employee, panelist, vendor, client, and lead become facets/relationships on that id, never separate people. No business identity may depend on email or normalized company name as a matching key.
— Directly restates entity_map.md §0.1/§2.1-2.2 and register invariant-shaped finding "identity is a string, everywhere." Not new; now stated as a build requirement rather than an observation.

### 2. One canonical database topology
No `get_database()` with caller-controlled names (D-15, fixed this session). No environment variable silently relocating a subsystem (D-16). No runtime-selected databases (the `leads`/`ai_enrichment` import-time probe; the four phantom databases where a collection name was passed as a database name — see §4, not yet fixed). No independent `MongoClient` construction outside the shared pool (~150 in-code instantiation sites per the collection inventory). Database names and collection ownership declared centrally, in code, not by convention.
— D-15 and D-16 are already in the register. The phantom-database and independent-MongoClient findings existed in the source collection-inventory report but were **not** individually promoted to the register — see §4.

### 3. One canonical entity store
`Person`, `Account`, `Opportunity`, `Activity`, etc., with every operational projection or cache explicitly labelled as a projection, never presented as a competing source.
— Matches spec §6 and entity_map.md §2's per-entity disposition tables directly. **Terminology note (reconciliation pass, 2026-09-05):** the original spec draft (turn 1 of this conversation) named this entity `Contact`; this principle's first draft still used `Contact/Relationship` here even though principle 1 already used `Person`. Every downstream artifact — entity_map.md, schema_catalogue.md, lead_generation_specification.md, endpoint_catalogue.md, screen_catalogue.md — settled on `Person` without exception, so `Person` is the retroactively-confirmed canonical name and this principle is corrected to match rather than left as the one document disagreeing with the rest.

### 4. Roles become composable, not copied
`Person → lead facet → panelist facet → vendor relationship → employee relationship → client/contact relationship`, replacing v1's `lead → copy → vendor` pattern. A person can hold multiple relationships simultaneously.
— This is entity_map.md §2.4's finding, generalized into a rule: every v1 promotion path is lossy specifically because it copies a subset of fields into a new collection instead of attaching a facet to the same record.

### 5. Brand becomes a relationship
`Person ↔ Account ↔ Brand ↔ Relationship`, not a field on the person. The same person/company must be able to interact with SFW, Cogentix, and BIMwave without overwriting history or duplicating identity.
— Already D-19 and entity_map.md §2.3. Explicitly: v1's "first brand wins" policy is **not** a v2 invariant to preserve — it was a workaround for a missing entity, and the entity is what v2 builds.

### 6. One canonical write path per concern
Email, suppression, finance, rewards, survey allocation, identity, and permissions each get exactly one implementation. No second implementation is permitted merely because an older module already exists.
— This is invariant **I-1**, already locked in the register (§0.1), extended here to explicitly name identity and permissions alongside the five domains already covered.

### 7. Transactions and reconciliation are first-class
The current spine's `write → swallow exception → hope the nightly reconcile fixes it` pattern is explicitly prohibited for coupled business state in v2.
— This is invariant **I-3** (atomic by construction) plus **I-5** (reconciliation for every external dependency), already locked. Newly sharpened by this session's identity-tracing finding: the reconcile doesn't just fail to catch drift, it runs *backward* and re-adopts merged-away accounts as fresh ones (D-18) — so "eventually consistent" was never actually true here, even before external failures are considered.

### 8. No lossy conversions
A conversion must create or link relationships while preserving the original entity and its provenance — never a partial-field copy into a new collection.
— Same finding as #4, stated as the negative rule.

### 9. Merge must be entity-wide
v1 has exactly one merge function, scoped to accounts, inside the spine only, and it doesn't update external references (D-18). v2 needs controlled merge/link/unmerge for every mergeable identity class, with cross-domain references updated atomically or through a durable reconciliation workflow — never silently, never one entity type only.
— D-18 plus entity_map.md §2.8, both already recorded. Extends the register's existing spec §9 requirement ("prevent accidental merging of unrelated people") by noting v1 currently has **no** merge capability for people at all, only for accounts.

### 10. CPX disappears entirely
**Confirmed by owner, 2026-09-05.** Every CPX database, collection, adapter, callback, credential, webhook, allocation path and business dependency is marked **`REMOVE`** — not migrated, not merged into the canonical survey-supply model. v2 has no CPX.

Scope of the removal, as inventoried:
- **Databases/collections:** `cpx_research` (`cpx_surveys`, `cpx_filters`, `cpx_diagnostic_logs`) · `traffic_flow_db.cpx_callback_logs`, `.cpx_postback_logs`, `.survey_transactions`, `.cpx_entry_guards`
- **Code paths:** `routers/cpx_api.py` · `app/routers/cpx.py` · `app/services/cpx_service.py` · the CPX-first allocation branch in `routers/traffic.py` · CPX postback/hash validation · CPX WebView-UA blocking · the CPX→CINT termination fallback
- **Models:** `schemas.CPXSurveyBase`/`CPXSurveyFilter` · `survey_transaction.*` (the entire module — `SurveyTransaction`, `CPXPostbackRequest`, `TransactionStatus`)
- **Credentials/config:** `CPX_SECRET_KEY`, `cpx_secure_hash_key`, CPX API timeout settings, `ENABLE_CPX_INTEGRATION`

**Two consequences that must not be lost in the removal:**

1. **v1 CPX defects still matter until CPX is actually switched off.** D-marked CPX findings (fail-open postback hash validation when `CPX_SECRET_KEY` is unset; forged completion/reversal signals being indistinguishable from genuine ones) describe a system that is *running today*. "Slated for removal in v2" is not a mitigation for a live fail-open on a payout signal. Either accept that risk explicitly with a date, or fix it in v1 — but don't let the v2 decision quietly close it.
2. **Respondent payout continuity.** `survey_transactions` carries real `amount_usd`/`amount_local` payout records. Removal is a *code and integration* removal; the historical transaction data still needs a migration or archival disposition for reconciliation and any outstanding panelist balances. That is a lineage-map row, not a delete.

---

## 2. P0 defects — reconciled against the existing register

Your message listed six P0s. Five already exist in the register (some under different framing); one is new. Rather than create duplicate entries, here's the mapping:

| Your P0 | Register status | Resolution |
|---|---|---|
| Database target injection | **D-15** | **Fixed this session** — see §4. Correction: this router was never mounted, so it was a real defect in unreachable code, not a live exposure. Fixed anyway as defense-in-depth. |
| Database topology ambiguity (one env var relocating dozens of collections) | **D-16** | **Raised to P0.** I initially argued for P1 on the grounds that P0 was reserved for security/money exposure; the owner's classification stands and the register's P0 convention was widened instead (see register's classification scheme). The widened convention is the better one: a defect that makes business state unsound is not lesser than one that makes it exploitable. |
| Cross-database shadow writes | Same finding as D-16 — this *is* D-16, not a separate defect | No separate entry; D-16's description covers Celery-vs-API split-brain explicitly. |
| Canonical identity absent | **D-22** (new) | Added as a numbered P0 defect rather than left as prose. My earlier reasoning — that it "doesn't fit the defect-register shape because there's no file:line to point at" — was wrong in a way worth recording: a defect register that can only hold defects with a line number will systematically under-report the largest architectural failures, which is exactly how v1 accumulated them. |
| Non-transactional canonical mirroring | **D-20** (new) | Added, **P0**. |
| Runtime database selection | **D-21** (new) | Added, **P0**. Covers the import-time probe, the four phantom databases, and CLI/env-selected stores; D-15 was the caller-controlled instance of the same family. |

### D-20 (new) — Non-transactional canonical mirroring, CRM spine

The spine (`crm_db`) is declared canonical while every write into it goes through eleven exception-swallowing, non-transactional mirror functions (`spine_connector.py`'s own docstring: *"Best-effort and NON-FATAL: a mirror failure must never break the legacy write path... Every public function swallows exceptions and returns None."*). Only 5 of the 11 mirror paths have any reconcile at all. The reconcile job itself runs *backward* — it copies spine accounts and contacts back out into the legacy collections, because the UI never migrated to reading the spine. A system that mirrors backward into the thing it's supposed to replace is not eventually consistent; it has no defined direction of truth. **Severity: P0** (under the widened convention — this is the mechanism that makes every other "the spine is canonical" claim in the codebase false).

### D-21 (new) — Runtime-selected databases outside the db_pools default

Distinct from D-16 (one env var relocating a whole subsystem), this is the narrower pattern of *individual* modules choosing their database at runtime rather than by static configuration:
- `agents/mail_segregation_agent.py:76-80` — a try/except probe at import time chooses between the `leads` and `ai_enrichment` databases depending on whether a connection check happens to succeed first.
- Four collection names passed where a database name was expected (`cpx_db`, `cint_db`, `cint_surveys`, `cpx_surveys` as db names) — each silently creates or reads an empty database rather than erroring. One instance checked this session (`leads/scheduler.py:712`, an `except ImportError` fallback) — not fixed, since it's a rarely-hit fallback branch and fixing it in isolation without checking the other three sites risked doing a shallow job of what should be one pass.
- `outreach/router.py` (D-15, fixed) was the caller-controlled instance of this same family.

**Severity: P0** (under the widened convention. None of the confirmed instances currently affect live-reachable code, but the pattern recurs across four to five independent sites, which makes it systemic rather than incidental — and a system where the *storage target* is a runtime variable cannot be reasoned about at all).

---

## 3. Status of open items

**Settled 2026-09-05:**
- Principles 1-9 — **locked**. Phase 1 design proceeds from these.
- Severity convention — **widened**; D-16/D-20/D-21 raised to P0, D-22 added at P0. See the register's classification scheme.

- CPX disposition — **confirmed REMOVE** (§1.10). No open items remain in this document.

**Two items this decision creates, tracked so they don't fall between the two systems:**

1. **v1 CPX defects are not closed by the v2 removal decision** (§1.10, consequence 1). They need either an explicit accepted-risk with a switch-off date, or a v1 fix.
2. **CPX payout history needs an archival/migration disposition** (§1.10, consequence 2) — a lineage-map row, not a delete.

**Next deliverable — now unblocked:**

The **`V1 → V2 Data Lineage Map`**. Distinct from `entity_map.md`: the entity map says *what* v1 has and where each store goes; the lineage map says, per retained **field**, its origin, its owning v2 entity, whether it is authoritative or derived, and how it is migrated and reconciled. Both inputs it was waiting on are now settled — principles 1-9 fix what "authoritative" means, and the CPX decision fixes its scope (CPX fields excluded except the payout-history rows above).
