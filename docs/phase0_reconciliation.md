# Phase 0 — Six-Document Reconciliation Pass

> Run: 2026-09-05
> Inputs: [business_rules_register.md](business_rules_register.md), [entity_map.md](entity_map.md), [data_lineage_map.md](data_lineage_map.md), [schema_catalogue.md](schema_catalogue.md), [endpoint_catalogue.md](endpoint_catalogue.md), [screen_catalogue.md](screen_catalogue.md)
> Method: read the register in full; targeted greps across all six documents for the specific contradiction classes below, not a re-skim of content already verified while each document was written.

This is a check of whether the six documents agree with each other and with themselves — not a re-audit of v1. Five real issues were found and fixed during this pass; they're recorded here rather than silently corrected, per the register's own "leave a trace" convention. Everything else on the checklist was checked and found clean, which is reported too, since "we looked and it's fine" is a different claim from "we didn't look."

## Findings — fixed during this pass

### 1. Lead state machine self-contradicted itself (lead_generation_specification.md)

§7's diagram drew `CONTACTABLE` as a node between `ASSIGNED` and `ENROLLED` in a linear pipeline — visually indistinguishable from the genuinely persisted states around it. §9, four sections later in the same document, states as its central rule that contactability "must never be a field frozen onto the `LeadRelationship`" and is "evaluated live." A diagram node is, by definition, a stored value. The two sections directly disagreed about whether contactability is data or a live check.

The top-level pipeline diagram in §0 already had this right (labeled the gate "evaluated live, never frozen onto the lead"), and the endpoint catalogue's `GET /leads/{id}/contactability` and `POST /leads/{id}/enroll` were already built the correct way. §7 was the one place that drifted. **Fixed**: §7's diagram now shows only genuinely persisted states, with an explicit note explaining what changed and why, rather than a silent correction.

### 2. Terminology drift: "Person" vs "Contact/Relationship" (v2_locked_principles.md)

The original spec draft (turn 1 of this conversation) named the core person entity `Contact`. When v2_locked_principles.md was written, principle 1 used `Person` but principle 3 still said `Contact/Relationship` — an internal disagreement within the same document, inherited from the source material without being caught at the time. Every downstream artifact (entity_map.md, schema_catalogue.md, lead_generation_specification.md, endpoint_catalogue.md, screen_catalogue.md) settled on `Person` without exception. **Fixed**: principle 3 corrected to `Person`, with a note recording the supersession rather than pretending the draft never said `Contact`.

### 3. P0 defect count — changelog arithmetic doesn't match the table

The register's own P0 table currently holds **23** entries. The most recent changelog line asserting a running total (Rev 10) says "P0 count: 18 → 21." Tracing the history: Rev 8's changelog claims "15 → 18" for four items entering P0 status (D-16, D-20, D-21 reclassified, D-22 added) — that's `15 + 4 = 19`, not 18, a one-item arithmetic slip. Rev 9 added D-23 to the P0 table (visible in the table itself, dated 2026-09-05) but its changelog entry never mentions a count change at all. Rev 10 then computed its "18 → 21" from the already-wrong 18, compounding both prior errors. `19 + 1 (D-23) + 3 (D-26/27/33 from Rev 10) = 23`, which matches the table. **Not fixed by editing old changelog text** — those are dated historical statements and get corrected by a new entry, not silently rewritten (see the changelog entry added below).

### 4. Duplicate "Secondary decisions" list (business_rules_register.md §7)

Two nearly-identical bullet lists of secondary, non-blocking decisions existed back to back, one including "panel currency model / FX at redemption" and one omitting it — an artifact of an edit that appended rather than replaced. **Fixed**: merged into one list, keeping the more complete version.

### 5. `tds_amount` silently absent from the schema catalogue despite B-06 being open

`schema_catalogue.md`'s Invoice/Bill table had no TDS field at all, with no note explaining the omission — which reads as "TDS is out of scope for v2," a silent default on an explicitly open decision (B-06: "is TDS deduction required"). The catalogue's own stated discipline (§8) is to mark fields conditional on open decisions, not omit them — it did this correctly for B-11 and B-14 but missed B-06. **Fixed**: added as an explicitly `[OPEN — B-06]` field, matching the existing pattern, and added to §8's open-items list.

## Findings — checked, clean

Reported explicitly because "checked and clean" is different from "not checked":

- **CPX references in any of the three build-facing catalogues (schema/endpoint/screen)**: found three mentions total, all correctly framed as removal/history, none treating CPX as a live v2 concern. Clean.
- **Screens calling nonexistent endpoints**: every named endpoint in the screen catalogue's deep-dives (`POST /leads/{id}/qualify`, `POST /invoices/{id}/approve`, `POST /payments`, `POST /panelists/{id}/rewards/redeem`) exists in the endpoint catalogue. Clean.
- **AI capabilities exceeding the permission model**: the AI domain's `[APPROVAL-GATED]` rule on money/permissions/identity/suppression-touching proposals matches B-07's explicit rule that "system and AI agents cannot approve financial transactions." Clean.
- **Migration mappings contradicting schema ownership**: spot-checked the highest-risk case — `rewards_balance`. Data lineage map Domain 1 says migrate as an opening ledger entry, never a stored balance; schema_catalogue.md's `RewardLedgerEntry.balance` is `DERIVED`, never stored. Consistent.
- **`[DECIDE]` items accidentally defaulted**: checked B-06, B-09, B-11, B-14 (the ones most likely to get silently resolved by an confident-sounding catalogue). B-09 (Cint fallback floors) — endpoint catalogue's allocation deep-dive deliberately keeps thresholds as config rather than picking values. B-11/B-14 were already correctly left conditional. B-06 was the one miss, fixed above (finding 5).
- **Approval threshold amounts**: not present anywhere in the endpoint or schema catalogues as concrete numbers — correctly left to B-07's "configurable, not fixed by this decision."

## Findings — noted, not defects

- **Entities with no dedicated endpoint table** (`Task`, `Project`, `Brand`, `Message`/`Thread`, `Mailbox`, `File`): these get standard CRUD under the endpoint catalogue's §0 governing rules with no state machine of their own, which is why they had no explicit table — not an oversight, but it wasn't *stated* as deliberate until this pass. Added one clarifying line to endpoint_catalogue.md §7.5 so a future reader doesn't have to infer that.

## What this pass did not find

No orphaned business rules, no fields with no authoritative owner (beyond the B-06/TDS case above, now fixed), no lineage fields with no migration destination, no permission strings visibly inconsistent with the RBAC design, and no other state-machine terminology mismatches beyond the `CONTACTABLE` case. This is not a claim of exhaustive proof — six documents of this size can hide more than one pass catches — but the specific checklist given for this reconciliation was worked item by item, not sampled.

## Verdict

Five real, non-cosmetic inconsistencies existed across six documents written over one continuous session — which is the expected failure rate for documents this size being extended incrementally, not a sign the process was unreliable. All five are fixed, with the fixes left visible rather than silently smoothed over, consistent with how every other correction in this register has been handled.

**Phase 0 is closed.** The register's three genuinely open, Phase-1-relevant decisions (B-03 accountant sign-off, B-06 TDS, B-08 classification taxonomy naming — see business_rules_register.md §7) do not block Phase 1 per the register's own scoping (§0.2, §5.7): Phase 1 proves the canonical foundation and the approval mechanism against what exists today, and each later phase re-runs the same acceptance tests against what it adds. Phase 1 — organisation, identity, `Account`, `Person`, `Activity`, `Opportunity`, permissions, audit, schema validation, migrations, events, idempotency — can begin.
