# Torpedo v2 — Automated Lead Generation Specification

> Generated: 2026-09-05 | Phase 0 deliverable, written ahead of the Endpoint Catalogue (§31) and Screen Catalogue (§32) so both can be built against a settled contract rather than retrofitted to one.
> Depends on: [v2_locked_principles.md](v2_locked_principles.md) (invariants I-1–I-6), [entity_map.md](entity_map.md) (§2.4 promotion paths, §2.3 brand), [data_lineage_map.md](data_lineage_map.md) (Domain 1 identity sequencing), [business_rules_register.md](business_rules_register.md) (§4, B-04, B-08, D-19)

## 0. What this replaces

v1's lead generation is not one pipeline. It is five to nine partial stores, five or six independently-weighted scoring implementations, four non-communicating dedup mechanisms, and a promotion model where "becoming a vendor" means copying 4 of 17 fields into a new collection. Every one of those was found and dispositioned in Phase 0's earlier artifacts. This document turns those findings into one canonical pipeline and states, for each stage, which v1 behavior is preserved, which is corrected, and which is new construction.

```
Lead Sources                                     Canonical Person/Account
  web/API, CSV, email-derived,                              │
  external research, enrichment                             │
  providers, referral, manual,                               │
  panel/traffic promotion, future                            │
       │                                                      │
       ▼                                                      │
  Source Ingestion  ──────────────────────────────────────────┤
       │ (RawLeadEvent, staged, I-6 validated)                │
       ▼                                                      │
  Identity Resolution  ◄────────────────────────────────────────
       │
       ├── matched ──► existing Person + Account
       └── unmatched ─► new Person + Account
       │
       ▼
  Enrichment (provenance-tagged: PROVIDER_FACT / TORPEDO_DERIVED / AI_INFERRED)
       │
       ▼
  Qualification (one canonical ICP scorer, per B-04)
       │
       ▼
  LeadRelationship (attached to Person + Account — never a copy of either)
       │
   ┌───┴────────────────┐
   │                    │
Assignment          Contactability gate
   │                    │  (evaluated live, never frozen onto the lead)
   └────────┬───────────┘
            ▼
    Outreach Enrollment (per AccountBrandRelationship, through the ONE send facade)
            │
            ▼
        Activity (one stream, every transition recorded)
```

## 1. Sources

Every source gets a canonical `source_type` from a closed enum — no wildcard sources, per spec §31's closed-capability-list principle. Each ingested item carries `source_type` + `source_record_id` (opaque, source-native) + `ingested_at`.

| `source_type` | v1 precedent | v2 disposition |
|---|---|---|
| `web_form` | web-to-lead endpoint (rate-limited per TOR-10 remediation) | `KEEP` — already has a working rate limit and a required token |
| `csv_import` | multiple ad-hoc importers per domain | `REPLACE` — one importer, one validation path, not one per module |
| `email_derived` | mail-pool scanning, `email_leads`, `vendor_leads` extraction | `REPLACE` — collapses three v1 extraction paths into one |
| `external_research` | Google/LinkedIn search, "web_search_enrichment.py" (currently disabled) | `EXTRACT` — confirm intended scope before rebuilding; v1's own `LeadSource` enum defines this and 4 siblings but **nothing in v1 ever references it** (register/entity_map model-catalogue finding) |
| `enrichment_provider` | Skrapp, Clay-style workbooks | `MERGE` — one provider-adapter boundary (spec §17), not per-provider domain logic |
| `referral` | **does not exist in v1** | New construction. `[DECIDE — B-16]` whether this is in v2 scope |
| `manual` | staff-entered leads | `KEEP` |
| `panel_traffic_promotion` | traffic→panelist promotion (entity_map §2.4) | `KEEP`, corrected — v1's version records no source id at all; v2 must |
| *(future connector)* | — | Registry-based, not hardcoded — adding a source must not require touching the identity-resolution or qualification code |

## 2. Ingestion contract

- Every source writes exactly one `RawLeadEvent`: `{source_type, source_record_id, payload, received_at}`. This is staging, not an entity — matches the entity map's disposition of `leads_raw` as pre-validation staging, TTL'd, never a persisted `Person`.
- **No source writes directly to `Person`, `Account`, or `LeadRelationship`.** Every event passes through identity resolution first. This is the single structural fix for v1's core defect (§0 above): a source cannot create a duplicate person because it cannot create a person at all.
- The write is schema-validated per **I-6** — no `Dict[str, Any]` body reaches Mongo unvalidated. This is not optional given the lineage map found 96% of v1's writes bypass validation entirely.
- Idempotency key = `(source_type, source_record_id)`, atomic on insert, per **I-3**. A replayed ingestion event is a no-op, not a duplicate.

## 3. Identity resolution

This is where v1 has no working answer (data_lineage_map.md Domain 1: no store shares a surrogate id; every join is a string match on lowercased email or normalized company name).

**Resolution priority**, ported from the one piece of v1 dedup logic mature enough to keep (register §4.7's hash-index priority order: LinkedIn 1.0 → email 0.95 → name+company 0.85), reimplemented as the **one** canonical resolver rather than one of four non-communicating ones:

1. Normalized LinkedIn URL (highest confidence)
2. Normalized email (lowercase, trim, provider-alias folding)
3. Domain + normalized name (company matching — per entity_map §2.2, domain is the safer key where available)
4. No match → mint new `person_id` / `account_id`

**Every resolution is recorded**, not just applied: which rule matched, at what confidence, against which existing id. This is provenance applied to identity resolution, not only to AI output — the same principle, a different subsystem. Without this, a future audit of "why did this event attach to person X" is unanswerable, which is exactly the complaint the identity-tracing pass made about v1.

**No silent merge.** A resolution that finds a candidate match below a confidence threshold routes to a review queue, not an automatic merge — merge capability itself is gated by the entity-wide merge design required by locked principle 9 (still open per D-18: v1's only merge function doesn't update external references and is undone by its own reconcile job). Lead generation cannot outrun the merge capability it depends on.

## 4. Enrichment contract

Every enriched field carries an explicit provenance class — this closes the audit/provenance gap the model catalogue found (0 of 48 v1 models carry `updated_by`; 1 of 48 carries any version field):

| Class | Example | Required metadata |
|---|---|---|
| `PROVIDER_FACT` | `company.industry` from an enrichment API | `source`, `observed_at` |
| `TORPEDO_DERIVED` | a computed field (e.g. engagement score) | `formula_version`, `computed_at` — never the only copy of a fact, always recomputable (this is `DERIVED` in the lineage map's classification, applied here) |
| `AI_INFERRED` | ICP-adjacent classification, persona | `model`, `model_version`, `prompt_version`, `confidence`, `generated_at` (spec §29) |

**A field with no provenance class is not a valid v2 field.** This is stricter than v1, deliberately — v1's own audit found this exact gap and it is a direct cause of several defects already in the register (D-22 identity, the classification-precedence gap in §4.2).

**AI outage handling follows I-4**, using `bucket_classifier.py`'s pattern as the reference implementation (register §4.6, explicitly cited there as the correct one): an outage is a distinct, disjoint state — never a silently-persisted low-confidence verdict, never a fabricated mid-range score. Ten consecutive failures aborts the batch as an outage signal, not a business classification.

## 5. Canonical ICP scoring

Locked by **B-04**: `icp_config.py`'s 3/2/2/1 scale (title 3, industry 2, country 2, seniority 1, qualifying at ≥4) is canonical. The other two scorers are `REMOVE` — **but not before** their two incident-tested fixes are ported to the canonical implementation:

1. The empty-industry guard (`"" in kw` previously matched everything, per `canonical_ingestion.py`'s documented incident)
2. Tie-breaking to unqualified rather than list order (prevented 10,790 leads from landing in the wrong ICP on no evidence)

Score is **`DERIVED`**, per the lineage map's Domain 1 classification — recomputed, never copied at migration, and versioned (`icp_config_version`) so a historical score remains interpretable even as the scorer's weights evolve. A lead's score is a function of `(person, account, config_version)` at read time, not a frozen number.

## 6. AI scoring / provenance

Same provenance requirement as §4, applied specifically to qualification-adjacent AI output. Per spec §28's pipeline (`Prompt → Model → raw output → parser → schema validation → business validation → confidence check → Proposal → human approval or approved auto-apply → write`): **AI never writes directly to qualification state.** It produces a Proposal; qualification state changes through the same state machine in §7 regardless of who or what proposed the transition.

## 7. Qualification state machine

**Persisted states** (each a written value on `LeadRelationship.state`, each transition a stored fact with its own Activity record):

```
DISCOVERED → ENRICHING → QUALIFIED ──► ASSIGNED ──► ENROLLED ──► CONVERTED
                  │
                  └──► DISQUALIFIED (reason code, closed enum, terminal — re-entry requires a new DISCOVERED event, not a status flip)
```

`CONTACTABLE` is deliberately **not** in this diagram, and that is not an omission — see the correction below.

- `DISQUALIFIED` requires a reason from a closed enum. v1's own qualification gate order — email → ICP score/bracket → bucket confidence → suppression, first-failing-reason-wins (register §4.4) — is preserved as the **content** of the gate logic; what's fixed is that it now writes to one state field instead of being scattered across `outreach_bucket`, `classification`, and `category` with no defined precedence (the still-open **B-08**).
- The TOR-57 "no_email" finding becomes the most common `DISQUALIFIED` reason code, and because reason codes are now structural, "how many leads die at which gate" (register §4.4's noted gap — no maintained metric exists, only point-in-time incident numbers in code comments) becomes a live queryable fact instead of something that requires running a script.
- `ENROLLED` is a genuine persisted state, reached only after the `CONTACTABLE` gate (§9) passes at the moment of the `ASSIGNED → ENROLLED` transition. **Earlier drafts of this section drew `CONTACTABLE` as a state node between `ASSIGNED` and `ENROLLED`, which directly contradicted §9's rule that contactability is never frozen onto the lead — a node in this diagram is, by definition, a stored value.** Corrected: `CONTACTABLE` is a live-evaluated gate *condition* checked at this transition and again at send time (§10), never a value written to `LeadRelationship.state`. The endpoint catalogue's `GET /leads/{id}/contactability` and `POST /leads/{id}/enroll` already implement it this way; this section's diagram was the one document that drifted from that and has been brought back in line.

## 8. Ownership / assignment

`owner`, `team` fields on `LeadRelationship`. **This is new design, not migration** — the identity-tracing pass found no clean assignment audit trail anywhere in v1 worth preserving. Assignment changes are Activity events (§13), which gives v2 something v1 never had: an answerable "who owned this lead when it converted."

## 9. Contactability — "found" is not "allowed to contact"

This is the decision most worth protecting from erosion, because v1's failure mode here is well-documented and easy to repeat: `classification_basket` was a point-in-time decision baked onto the lead record, recomputed on every enrichment pass, and the drift between "baked value" and "current truth" produced the 41,746-enrollment, 9,747-people-in-three-brands incident (register §4.5).

**Contactability must never be a field frozen onto the `LeadRelationship`.** It is evaluated **live**, at the moment of enrollment and again at the moment of send, against the canonical suppression/contactability layer (the merged suppression store from data_lineage_map.md Domain 3.1). A lead that was contactable yesterday and got suppressed this morning must not send this afternoon because a stale flag said otherwise.

This also means: `QUALIFIED` answers "is this a good lead," and `CONTACTABLE` answers "are we currently allowed to reach them" — two different facts, evaluated by two different subsystems, that v1 collapsed into one classification field and paid for.

## 10. Outreach enrollment

Enrollment requires `QUALIFIED` + `ASSIGNED` + `CONTACTABLE` simultaneously, evaluated at enrollment time, not inherited from an earlier state check.

- **Enrollment must go through the one canonical send facade** — invariant I-1, register §5.1. No enrollment path may construct its own transport, the way v1's Pipeline 4 and Pipeline 5 do today (both `[DEFECT · P0]` in the register, D-05/D-06).
- Which brand's facade and suppression scope applies is resolved through `AccountBrandRelationship` (locked principle 5, D-19) — **not** a single recomputed field. This is the one place where v2 deliberately does *not* inherit v1's "first brand wins" restriction: since the relationship is now real, an account can legitimately be enrolled with multiple brands' outreach independently, each gated by its own contactability check. v1 had to forbid multi-brand outreach because it had no way to represent it correctly; v2 removes the restriction because it fixes what the restriction was covering for.

## 11. Deduplication / idempotency

One dedup mechanism — not the four found in register §4.7 (a hash index, a live regex scan on an unpooled client, a SQLite store, and a stub that always returns "no duplicate"). Identity resolution (§3) **is** the dedup boundary: a duplicate `RawLeadEvent` for an already-resolved identity merges into the existing `LeadRelationship`'s history, never creates a second `Person`.

## 12. Failure / retry / DLQ

- Enrichment/AI failures: I-4, as in §4.
- Ingestion failures: dead-letter with retry and bounded chain depth, per spec §35 — a source integration that fails must land in a DLQ, not silently drop the event or fail open.
- **No source integration may fail open into `QUALIFIED` or `CONTACTABLE`.** A failure is always a failure state, never a passing default — this is I-4's logic generalized past AI specifically to the whole pipeline.

## 13. Audit / activity requirements

Every state transition in §7 is exactly one `Activity` record, in the one canonical activity stream (register §2.7 found four competing audit stores in v1 — two same-named `audit_log` collections in different databases, both live, plus two orphaned governance logs). Every automated decision — identity resolution match, ICP score, AI classification — must be reconstructable after the fact: "why does this value exist, and what produced it" (spec §29), answerable without grepping logs, which is what v1's production path required (register §2.5).

## 14. Rate / cost limits

One configured daily cap per source, not per-module hardcoded constants. v1 has three uncoordinated caps (1000/500/200) across three files with no shared source of truth (register §4.7) — that pattern does not carry forward. AI cost is tracked per spec §53 (cost per 1,000 requests, cost per accepted proposal), consistent with the on-demand GPU broker work already in progress for this project.

---

## Open decisions this spec surfaces

| # | Decision | Owner |
|---|---|---|
| B-16 | Is a referral source in v2 scope? Does not exist in v1 in any form. | Business owner |
| B-17 | Which `external_research` connectors are actually in scope for launch vs. aspirational? v1's own `LeadSource` enum names five that nothing ever implemented. | Business owner |
| — | B-08 (classification taxonomy precedence, already open) is directly resolved by this spec's §7 — the qualification state machine *is* the resolution. No new decision needed, but B-08 should be marked satisfied once this spec is approved. | — |

## What this unblocks

The Endpoint Catalogue (§31) can now define ingestion, resolution, enrichment, qualification, and enrollment endpoints against a settled state machine instead of inventing one inline. The Screen Catalogue (§32) can define pipeline-visibility screens (funnel view, per-lead provenance view, contactability status) against the same states. Both proceed next.
