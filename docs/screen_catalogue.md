# Torpedo v2 — Screen Catalogue (spec §32)

> Generated: 2026-09-05 | Phase 0 deliverable
> Depends on: [endpoint_catalogue.md](endpoint_catalogue.md) (every screen action references a named endpoint), [schema_catalogue.md](schema_catalogue.md), [docs/frontend_inventory.md](frontend_inventory.md) (v1's real route list — dated 2026-05-16; two of its findings, the Finance double-prefix bug and the secondary frontend's broken auth, are confirmed **already fixed** in the current codebase and are not carried forward as open defects here)
> Precedes: the six-document reconciliation pass.

## 0. Source-of-truth correction

`frontend_inventory.md` is five months old. Before using it as the v1 screen inventory, two of its "confirmed bugs" were spot-checked against current code:

| Finding (2026-05-16) | Current status |
|---|---|
| Finance double-`/finance/finance/` route prefix, breaking all Finance CRUD | **Fixed** — `finance.py` decorators no longer carry the redundant prefix |
| Secondary frontend (`frontend/src/pages/`) sends an always-empty auth header | **Moot** — that directory no longer exists (register TOR-30: "dead `frontend/` deleted") |

The remaining ~95-route inventory in `Campaign_platform/src/` is treated as current for route *existence*; individual bug claims from that document are cited as-of-2026-05-16, not asserted as live without a fresh check.

## 1. Governing rules (apply to every screen unless overridden)

Stated once, per the same reasoning as the endpoint catalogue's §0 — a convention repeated 95 times is a convention that erodes on the 96th screen.

| Rule | Statement |
|---|---|
| **Loading state** | Every data-bearing screen shows a skeleton matching its final layout shape, never a bare spinner replacing the whole screen — v1 had no consistent pattern (frontend_inventory.md §14 notes ad-hoc over-fetching with client-side pagination as the norm, not the exception). |
| **Empty state** | Every list/table screen has an explicit empty state with a next action, not a bare "no results" — especially load-bearing for the Lead Gen and Rewards domains, where v1's empty state was frequently *the actual production state* (rewards: nothing to show, ever, because nothing was ever written — data_lineage_map.md §2.1) rather than a genuinely empty query result. v2 screens must distinguish "no data because nothing has happened yet" from "no data because a dependency is broken." |
| **Error state** | RFC 9457 `problem+json` (endpoint_catalogue.md §0) renders as a specific, actionable message — never a generic "something went wrong." A `403` from a permission check renders differently from a `409` concurrency conflict, which renders differently from a `503` (e.g. kill switch active). |
| **Confirmation** | Any destructive or irreversible action (delete, merge, send, approve, reverse) requires an explicit confirmation step naming what will happen — not a bare "Are you sure?". Approval-gated actions (endpoint_catalogue.md §0) show the approval requirement *before* the confirm step, not as a surprise 403 after. |
| **Permission-aware rendering** | An action the caller cannot perform is either hidden or visibly disabled with the reason shown on hover/focus — never present-but-silently-403-on-click, which was v1's default (no endpoint-level permission check meant the UI had no reliable signal to hide anything on, per register §5.6's finding that RBAC defaults off). |
| **Responsive baseline** | Staff screens: usable down to 1024px (operational tool, not a marketing site). Panel portal screens: usable down to 360px (real panelists use phones — v1's panel signup/dashboard already had to be mobile-first; that constraint carries forward unchanged). |
| **Accessibility baseline** | WCAG 2.1 AA: keyboard-navigable, focus-visible, form errors announced to screen readers, color is never the only signal for state (v1 used bare color-coded status badges throughout with no text/icon backup — carries forward as a fix, not a preference). |
| **Design system** | One component library, one data-table pattern, one form pattern, one modal pattern (spec §39). v1 had Radix UI + Tailwind used inconsistently across ~95 routes with no documented shared pattern set (frontend_inventory.md has no design-system section at all — a gap in itself). |

---

## 2. Screen inventory by domain

Each table lists v1's route(s), the v2 disposition, and the endpoint(s) it now calls by name rather than by ad-hoc `fetch()` (frontend_inventory.md §4 found the v1 primary frontend had at least four different call patterns coexisting — a centralized client, direct `fetch()`, direct `axios`, and the secondary frontend's broken client).

### 2.1 Platform / Auth

| v1 route(s) | v2 disposition | Notes |
|---|---|---|
| `/admin/login` | `KEEP`, rebuilt | Session model changes with D-01's fix — no more auth-fallback role hardcoding to defend against |
| `/admin/dashboard`, `/admin/settings`, `/admin/profile` | `KEEP` | |
| `/admin/logs` | `MERGE` into the one canonical Activity view (schema_catalogue.md §2.3) — v1 had this alongside 3-4 competing audit-adjacent screens across other domains | |
| `/admin/mail-pool`, `/admin/gmail-setup` | `KEEP`, rebuilt against one mail-pool store (data_lineage_map.md §3, the three-way `email_metadata` writer split) | |
| `/admin/hr` | `EXTRACT` — `EmployeeRecord` is new construction (schema_catalogue.md §1.6); this screen has no real backing entity in v1 or v2 yet | |

### 2.2 CRM / Sales — 17 v1 routes

| v1 route(s) | v2 disposition | Primary endpoint(s) | Notes |
|---|---|---|---|
| `/admin/sales`, `/admin/sales/leads`, `/leads/import` | `REPLACE` | `POST /leads/ingest`, `GET /leads`, `POST /leads/{id}/qualify` | See deep-dive — this is the screen where the lead-gen state machine (lead_generation_specification.md §7) becomes visible |
| `/admin/sales/contacts`, `/contacts/import` | `MERGE` with the Leads screen's underlying `Person` entity — v1 kept contacts and leads as visually and structurally separate pages over separate stores; v2 has one `Person` with facets, so "Contacts" becomes a filtered view of the same screen, not a separate one | `GET /people` | |
| `/admin/sales/companies/:companyName` | `REPLACE` | `GET /accounts/{id}` | Company detail keyed by name in v1 (a company-name-string URL param) — v2 keys by `account_id`, closing the same name-matching fragility found throughout entity_map.md §2.2 |
| `/admin/sales/rfq` | `MERGE` into Opportunity screens — v1's RFQ was a parallel, partially-synced concept to `crm_db.opportunities` (entity_map.md §2.9) | `GET /opportunities` | |
| `/admin/sales/campaign`, `/campaign/list`, `/campaign/workflow` | `REPLACE` | `POST /campaigns`, endpoint_catalogue.md §6 | |
| `/admin/sales/campaign/ai-leads`, `/ai-leads/:leadId` | `MERGE` into the main Leads screen — v1 split "AI-discovered leads" into a separate page/pipeline from regular leads with a separate detail view; v2 has one `LeadRelationship` regardless of source, so this becomes a `source_type` filter | `GET /leads?source_type=external_research` | |
| `/admin/sales/campaign/email-patterns` | `KEEP` | | |
| `/admin/sales/outreach` (`ColdOutreach.jsx`) | `REPLACE` | `POST /outreach/send`, `GET /suppressions/{email}` | See deep-dive |
| `/admin/sales/company-upload` | `MERGE` into Account import, one CSV import pattern for the whole system, not per-module | | |
| `/admin/sales/agent-dashboard`, `/agent-settings` | `KEEP`, rebuilt against `AiProposal` (schema_catalogue.md §7.1) — v1's agent dashboard drove direct writes; v2's drives proposals | `GET /ai/proposals`, `POST /ai/proposals/{id}/apply` | |

### 2.3 Finance — 18 v1 routes

| v1 route(s) | v2 disposition | Primary endpoint(s) | Notes |
|---|---|---|---|
| `/admin/finance/customers`, `/vendors`, `+/import` | `MERGE` — both become filtered views of `Account` with `CustomerBilling`/`VendorProfile` facets (schema_catalogue.md §1.5), not separate collections behind separate screens | `GET /accounts?facet=customer_billing` | |
| `/admin/finance/invoices`, `/bills`, `/estimates`, `/purchase-orders` (+ import for each) | `REPLACE` | `POST/PATCH /invoices` etc. (endpoint_catalogue.md §3) | See deep-dive — the state-machine visibility is the whole point of this rebuild |
| `/admin/finance/payments`, `/import` | `REPLACE` | `POST /payments`, `POST /payments/{id}/reverse` | The reversal action is genuinely new — v1 had no delete/void UI because no such endpoint existed |
| `/admin/finance/expenses` | `REPLACE` | `POST /expenses` | Approval status is never an editable form field in v2 — closes D-37 at the UI layer too, not just the API |
| `/admin/finance/reports` | `REPLACE` | `GET /accounts/{id}/statement` and equivalent derived-reporting endpoints | v1's dashboard aggregated inconsistent filters across its own three legs (register §1.8) — v2's reports read from `DERIVED` fields computed one way, not reassembled per-report |
| `/admin/finance/items` | `KEEP` | | |
| `/admin/finance/settings` | `EXTRACT` — v1 shipped this as an inline "Coming Soon" placeholder; no backing functionality exists to migrate | — | |

### 2.4 Operations — 13 v1 routes

| v1 route(s) | v2 disposition | Notes |
|---|---|---|
| `/admin/operations/accounts`, `/clients`, `/vendors` | `MERGE` into the CRM domain's `Account` screens — v1 kept Operations' own account/client/vendor views structurally separate from Sales' and Finance's, which is exactly the 5-6-store duplication entity_map.md §2.2 found | |
| `/admin/operations/projects`, `/projects/:id` | `KEEP` | |
| `/admin/operations/survey-pool` | `REPLACE` | Rebuilt against the single `Survey` entity (schema_catalogue.md §5.1), replacing v1's view over two competing survey inventories |
| `/admin/operations/potential-clients` | `MERGE` into Leads (a `source_type` filter, same reasoning as AI-leads above) | |
| `/admin/operations/rate-card` | `KEEP` | |
| `/admin/operations/yield-management` | `REPLACE` | Rebuilt against `Survey.metrics` (schema_catalogue.md §5.1) — v1's yield dashboard had a documented Motor event-loop bug and 180k-survey scaling issue (project memory: cint-yield-management) |
| `/admin/operations/traffic` | `KEEP`, rebuilt against `TrafficSource` | |
| `/admin/operations/reports` (`CPXCallbackLogs.jsx`) | **`REMOVE`** | CPX is deleted entirely (locked principle 10) — this screen has no v2 referent. `traffic_flow_db.survey_transactions` retained as read-only audit history (per the CPX removal's payout-history carve-out) needs a *different*, purpose-built historical view, not this operational screen carried forward |
| `/admin/operations/qre` | `KEEP` — external system boundary, per entity_map.md's `qre_health_survey` disposition | |

### 2.5 Vendor Portal — 5 v1 routes

| v1 route(s) | v2 disposition | Notes |
|---|---|---|
| `/admin/vendor`, `/leads`, `/all`, `/billing`, `/payments` | `MERGE` — v1's vendor portal duplicates most of the CRM/Finance vendor views behind a separate permission scope rather than the same screens with a scoped view. v2: same `Account`+`VendorProfile` screens, permission-scoped per B-07's model, not a parallel screen set |

### 2.6 Panel Admin — 4 v1 routes (staff-facing)

| v1 route(s) | v2 disposition | Primary endpoint(s) | Notes |
|---|---|---|---|
| `/admin/panel-admin` | `KEEP` | | |
| `/admin/panel-admin/panelists` | `REPLACE` | `GET /people?facet=panelist_profile` | |
| `/admin/panel-admin/rewards` (`RewardsPoints.jsx`) | `REPLACE` — genuinely new backing data | `GET /panelists/{id}/rewards/balance`, `POST .../clawback` | **This screen currently renders over an empty collection** (data_lineage_map.md §2.1 — `panel_rewards` has zero writers). Every number this page has ever shown a staff member is `0`. The v2 version is the first version that will ever display real data |
| `/admin/panel-admin/settings` | `KEEP` | | |

### 2.7 Panel Portal — external, panelist-facing

| v1 route(s) | v2 disposition | Primary endpoint(s) | Notes |
|---|---|---|---|
| `/panel/login`, `/signup`, `/forgot-password` | `KEEP`, rebuilt | | |
| `/panel/why-join`, `/rewards-info`, `/terms`, `/privacy`, `/faq` | `KEEP` | Static/marketing content, low risk | |
| `/panel/dashboard`, `/profile` | `KEEP` | | |
| `/panel/rewards` (`PanelRewards.jsx`) | **`REPLACE`, ground-up rebuild** | See deep-dive | v1's redeem button has no click handler at all (register §3.4) — this is not a data problem, it's a UI element that has never worked, ever, for any panelist |

### 2.8 Survey / Traffic — public, respondent-facing

| v1 route(s) | v2 disposition | Notes |
|---|---|---|
| `/takesurvey`, `/survey-start`, `/survey-error`, `/nosurvey`, `/response`, `/survey-response` | `KEEP`, rebuilt against the single allocation path (`POST /traffic/{id}/allocate`, endpoint_catalogue.md §5) — no CPX branch |

### 2.9 Removed / archived outright

| v1 route/file | Disposition | Reason |
|---|---|---|
| `/admin/marketing/linkedin` | `REMOVE` | LinkedIn automation subsystem confirmed dead in production (entity_map.md §1: writer lives only under `backend/deprecated/`) |
| `AIDatabase.jsx`, `AIConfig.jsx`, `Deliverability.jsx` | `REMOVE` | Already unrouted/orphaned as of the 2026-05-16 inventory (frontend_inventory.md §11, items 8-10) |
| `/admin/operations/reports` (CPX callback logs) | `REMOVE` | Per §2.4 above — CPX removal |

---

## 3. Deep-dives

### 3.1 Leads screen (`/admin/sales/leads` → v2 unified Leads screen)

| Field | Value |
|---|---|
| Purpose | Single view over every `LeadRelationship`, regardless of source — replaces v1's split across `Leads.jsx`, `AILeads.jsx`/`AILeadDetail.jsx`, and `PotentialClients.jsx` |
| Data | `LeadRelationship` + the attached `Person`/`Account` summary, per lead_generation_specification.md's state machine |
| Actions | Qualify, disqualify (reason required, closed enum), assign, enroll — each maps to the named endpoint in endpoint_catalogue.md §2, never a raw status-field edit |
| Permissions | `lead.read` to view; `lead.qualify`/`lead.assign`/`lead.enroll` gate the respective actions, hidden/disabled per §1's rendering rule if absent |
| States | Filterable by every state in the qualification state machine (`DISCOVERED`→`CONVERTED`), including `DISQUALIFIED` broken down by reason code — this is the funnel-attrition view register §4.4 noted v1 could never produce without running a script |
| Filters/search | By `source_type`, ICP score range, brand relationship, owner, state |
| Loading/empty/error | Per §1. Empty state distinguishes "no leads match this filter" from "no leads have been ingested from this source yet" |
| Confirmation | Disqualify requires the reason; enrollment requires confirming the resolved brand/contactability status is current (not a stale cached value — lead_generation_specification.md §9) |
| Responsive | Staff baseline (1024px) |
| Accessibility | State badges carry a text label, not color alone — direct fix for v1's bare color-coded classification-basket badges |
| Design pattern | Standard data table + detail drawer, same pattern as every other entity list screen — not a bespoke layout the way `AILeads.jsx` was structurally separate from `Leads.jsx` in v1 |

### 3.2 Invoice detail/lifecycle screen (`/admin/finance/invoices` detail view)

| Field | Value |
|---|---|
| Purpose | Single invoice lifecycle view — draft through paid, replacing v1's flat CRUD form with no visible state machine |
| Data | `Invoice` + line items + linked `CreditNote`s + payment history |
| Actions | Submit, approve (**[APPROVAL-GATED]**, per endpoint_catalogue.md §3 deep-dive), send, record payment, issue credit note |
| Permissions | Per B-07's approval policy — the Approve button is only rendered for a caller who actually holds sufficient ceiling, not rendered-then-403'd |
| States | `draft`/`pending_approval`/`approved`/`sent`/`partially_paid`/`paid`, with `overdue` shown as a derived badge, never a stored status the user can accidentally set |
| Filters/search | Standard list-level filtering by status, customer, date range, amount |
| Loading/empty/error | Per §1. A `409` from a concurrent edit surfaces as "this invoice changed since you loaded it — refresh to see the latest," not a generic error |
| Confirmation | **Sending is confirmed with an explicit "this invoice becomes uneditable after sending" notice** — the UI-level enforcement of the immutability the endpoint already guarantees, so the user isn't surprised by the guarantee, they're informed by it |
| Responsive | Staff baseline |
| Accessibility | Approval-ceiling-exceeded and self-approval-blocked states are announced, not just visually indicated (these are exactly the two acceptance tests in register §5.7 — the UI needs to make both failure modes legible, not just the API reject them) |
| Design pattern | Standard state-machine detail view — the same pattern used for `Bill`, `Estimate`, `PurchaseOrder` (all share B-05's state machine shape), not four independently-designed screens the way v1 had |

### 3.3 Cold outreach send screen (`/admin/sales/outreach`)

| Field | Value |
|---|---|
| Purpose | Campaign creation and monitoring — replaces v1's `ColdOutreach.jsx`/`Outreach.jsx` alias pair |
| Data | `Campaign`, enrolled `LeadRelationship`s, `SendLogEntry` history |
| Actions | Create campaign, enroll leads, trigger send (always via `POST /outreach/send` — endpoint_catalogue.md §6) |
| Permissions | `outreach.campaign.*`, `outreach.send` | 
| States | Per-recipient send status (`sent`/`suppressed`/`budget_blocked`/`failed`) shown explicitly — v1's non-facade pipelines left no trace at all when a send bypassed suppression; v2 makes every outcome visible because every outcome is now recorded (endpoint_catalogue.md §6 deep-dive: "the outcome is always recorded, even when nothing was sent") |
| Filters/search | By campaign, status, date |
| Loading/empty/error | A `503` (kill switch active) renders as a distinct, named banner — not folded into a generic error, since this is an operationally meaningful state staff need to recognize immediately |
| Confirmation | Sending to a list requires confirming the recipient count and the budget check result **before** the call, not after a partial send |
| Responsive | Staff baseline |
| Accessibility | Standard |
| Design pattern | Standard, shares the campaign-monitoring pattern with any future channel (the design explicitly does not special-case "this is email" beyond the provider-adapter boundary already established in endpoint_catalogue.md §0) |

### 3.4 Panel Rewards screen (`/panel/rewards`) — the rebuild-from-nothing case

| Field | Value |
|---|---|
| Purpose | Panelist-facing balance, history, and redemption — **v1's version has no working redeem action and reads an always-empty collection.** This is not a UI polish task; it is building the feature v1 only ever mocked |
| Data | `RewardLedgerEntry` (derived balance, per schema_catalogue.md §4.1) |
| Actions | Redeem (`POST /panelists/{id}/rewards/redeem`, endpoint_catalogue.md §4 deep-dive) |
| Permissions | The panelist acting on their own record only | 
| States | `pending`/`approved`/`paid`/`rejected` per redemption; balance always shown as a live-computed figure | 
| Filters/search | History filterable by type (`earned`/`redeemed`/`clawback`) and date | 
| Loading/empty/error | The empty state here is meaningfully different from v1's: "you haven't earned any rewards yet" (a real, correct empty state) must be visually distinguishable from what v1 showed everyone unconditionally forever | 
| Confirmation | Redemption confirms the amount and method before submitting, and the balance check happens atomically server-side (no UI-side "you have enough" assumption that a race can invalidate) | 
| Responsive | Panel baseline (360px) — this is a phone-first screen | 
| Accessibility | Panel baseline | 
| Design pattern | Standard panel-portal card/list pattern, consistent with `/panel/dashboard` and `/panel/profile` | 

---

## 4. What this leaves open

- Exact wireframes/visual design are out of scope for Phase 0 — this catalogue fixes *contract* (data, actions, permissions, states), not pixels.
- `/admin/hr` has no backing entity design beyond the `EmployeeRecord` placeholder (schema_catalogue.md §1.6) — not blocking, since nothing else references it yet.

## What this unblocks

All six input documents referenced by the reconciliation pass now exist: business rules register, entity map, data lineage map, schema catalogue, endpoint catalogue, screen catalogue. The final cross-document reconciliation pass can run.
