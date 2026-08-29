# Lead Pipeline Recovery — Bad Addresses & Missing Emails

Companion to `backend/scripts/BOUNCE_DIAGNOSIS_2026-08-28.md` (root-cause
diagnosis, same day, same investigation — read that first for the domain
NXDOMAIN/SPF/enrichment-stall findings; this doc focuses on the recovery
waterfall). All queries below re-run read-only against production just
now to confirm the diagnosis doc's numbers still hold. No writes were
made to `leads_raw` or any other production collection. Apollo's
read-only credit-stats endpoint was called (no cost, no data sent) to get
real pricing instead of guessing market rates — nothing else was spent.

---

## 0. Baseline re-verification (re-run fresh, same day)

```
1,840 leads created (last 30d)                — confirmed, matches
399 have a real email string                  — your 394 was off by ~5
                                                  (a distinct()-with-null
                                                  artifact — see prior doc §0.2)
1,441 have email explicitly null               — your 1,446 ≈ same, small
                                                  rounding from the same artifact
```

**(a) Join is fan-out, not 1:1.** 336 send events across only 143 distinct
emailed leads (2.35 sends/lead — a 4-step drip sequence). On the bounce
side it collapses to 1:1 (60 bounce docs = 60 distinct bounced emails, no
lead bounced twice — the send loop stops enrolling once bounced).

**(b) Sends lag lead creation badly, and 394/399 is the wrong
denominator.** Median lag from lead creation to first send: 16.5 days.
Of the 399 emailable leads, only 143 (36%) have been sent to at all;
256 are still queued. **Corrected bounce rate: 60/143 = 41.9%**, not
15.2% — worse than you estimated, not better.

**(c) Other status values.** `outreach_sends_v2.status` only ever has
`"sent"` or `"bounced"` — confirmed again just now. No
failed/rejected/complained/dropped tracked there (there's a dead SES
notification module built for exactly that, but nothing sends through
SES — see prior doc §1.1).

All of §0 matches the prior investigation exactly — nothing has changed
since.

---

## 1. Part 1 diagnosis — summary (full detail + every raw query output in the prior doc)

- **40% of the 60 bounces (24/60)** hit a domain that either doesn't
  exist (NXDOMAIN, 25%) or exists with no MX record (15%) — traced to
  `web_search_enrichment.py` trusting an LLM's `company_domain` output
  with zero existence check before using it to guess an email.
- **56.7% (34/60)** hit a domain with valid MX — can't split
  wrong-local-part vs receiving-side block without SMTP codes, which
  this system doesn't capture anywhere (bounce detection is Gmail
  inbox-scanning for mailer-daemon replies, not SES; stated as a gap,
  not guessed).
- **0/60** are role accounts, free providers, disposable domains,
  typo'd domains, or syntax failures.
- **surveyfieldwork.com (85% of bounces) has two conflicting SPF TXT
  records and no `google._domainkey` DKIM record** — a real,
  independently confirmed authentication defect, live-checked via DNS.
  cogentixresearch.com is clean. Neither domain is on the Spamhaus DBL.
- **Suppression enforcement is clean** — 0/60 were re-sent to after
  bouncing, 0/60 were suppressed before this send.
- **Missing-email root cause: not data loss.** All 1,441 sit at
  `classification_status: "AwaitingEnrichment"` by design, waiting on
  `background_enrich_leads()`. That job has made **zero attempts in the
  last 24h** (re-confirmed just now) against a 2,581-lead all-time
  backlog, because `torpedo-backend.service` is capped at `MemoryMax≈2GB`
  and is being SIGKILLed repeatedly (7+ forced kills in the last 36h of
  journal logs) on a 3.8GB VM running 6+ other services. This is an
  operational fix, not a data fix — I did not touch it (see prior doc §4).

---

## 2. Part 2 — recovery waterfall, run read-only against production just now

### Step 1 — re-parse raw payload / notes / free-text for a stuffed email

```js
// regex-scanned source_detail, notes, subject, snippet, title across
// all 1,441 for an embedded email address
```
**0 recovered.** For `source="websearch"` (100% of the gap), the "raw
payload" *is* a LinkedIn search-result snippet (job title + company
history text) — it structurally never contains an email address; LinkedIn
doesn't expose one in public search results. This isn't a parsing bug to
fix — there's nothing there to re-parse. (I'd expect a different answer
for a form/webhook source; this pipeline doesn't have one contributing to
the current gap — see §1's source-concentration finding.)

### Step 2 — internal cross-match (phone / LinkedIn URL / name+domain)

```js
// matched linkedin_url against leads_raw (other docs), leads_enriched,
// torpedo.leads; checked phone field presence; checked contacts/persons
```
**0 recovered.**
- `phone` is null on **100%** of the 1,441 (websearch/LinkedIn scraping
  doesn't capture phone) — nothing to match on there.
- 0 of 1,441 `linkedin_url`s matched an existing email elsewhere in
  `leads_raw`, `leads_enriched`, or `torpedo.leads`.
- `contacts` and `persons` collections exist but are **completely
  empty (0 documents each)** — there's no populated CRM contact store to
  cross-match against yet. `rfqs` has 1,018 docs but no `linkedin_url`
  field to join on, and its `contact_email`s are from inbound RFQ
  submissions, not cold-outreach targets — checked, no realistic overlap
  path.

### Step 3 — deterministic repair (mailto:, whitespace, typo domains, bad TLDs)

**0 needed.** Scanned all 399 leads that do have an email: 0 have a
`mailto:` prefix, 0 have leading/trailing whitespace, 0 match a known
typo domain, 0 have a `.con`/`.cmo`/`.comm` TLD. These are
programmatically constructed (AI-predicted or pattern-derived), not
scraped from messy free text, so they're already clean. **Applies
instead to step 7** (the 60 bounced) — checked there too, same result:
0/60 need syntax repair (see prior doc §1.4).

### Step 4 — pattern-derive from company domain (≥3 confirmed addresses)

```js
// leads with email:null + company_domain set, joined against
// email_patterns where sample_count >= 3
```
**625** of the 1,441 already have `company_domain` populated (enrichment
partially ran before the current stall — or was inherited from an
earlier attempt). Of those, **42 distinct domains** have a pattern with
3+ confirmed samples, covering **55 leads within this month's cohort**.

Running the same method with no date restriction (i.e. against the full
2,581-lead all-time `AwaitingEnrichment` backlog, not just this month) —
which is arguably the more useful number since the backlog itself is
what needs draining — found **196 candidates**. Example output from the
actual recovery script (`backend/scripts/recover_missing_emails.py`, dry
run, no writes):
```
soumalya.talapatra@kantar.com   (pattern={first}.{last}@{domain}, n=114)
ranjan.kapoor@dynata.com        (pattern={first}.{last}@{domain}, n=17)
christophe.guillot@nielsen.com  (pattern={first}.{last}@{domain}, n=48)
jamie.liu@microsoft.com         (pattern={first}.{last}@{domain}, n=10)
raymond.zou@sanofi.com          (pattern={first}.{last}@{domain}, n=8)
```
That `raymond.zou` example is worth flagging: the lead's stored
`first_name` was literally `"(Raymond)"` (a parenthetical nickname from
a LinkedIn display name like "Xiaolei (Raymond) Zou"). My first version
of the script naively produced `(raymond).zou@sanofi.com` — a broken
address. I added a strict alphabetic-only token filter that rejects
(rather than guesses at) any name token with punctuation, so cases like
this correctly fall through to "no candidate" instead of producing
garbage. Worth knowing this class of name-quality issue exists in the
underlying data if you extend this further.

**These 55/196 are staged as `candidate_email` +
`email_status: "inferred_pending_verification"` — never written to the
primary `email` field, and not eligible to send until step 6.**

### Step 5 — third-party enrichment for the rest

**Not run — no money spent.** Checked what's actually usable from this
session (read-only, no cost):

| Provider | Status |
|---|---|
| **Apollo.io** | Connected and usable. Checked live credit balance (read-only call, $0): **`lead_credit` = 75 available this cycle, 0 consumed** (cycle just reset today, resets monthly). `direct_dial_credit` is separately exhausted (160/160, irrelevant to email). |
| **ZoomInfo** | Not currently authorized in this session — needs you to connect it via claude.ai connector settings before I can call it. |
| **Clay** | Same — not currently authorized. |
| **Explorium** | Not configured as a connector in this environment at all. |

**Reality check on scale: 75 Apollo credits covers 5.4% of the 1,386
leads still unrecovered after steps 1-4.** Even spending 100% of this
month's free Apollo allowance doesn't meaningfully dent the gap. I did
not check Apollo's overage/per-credit pricing beyond the included plan
allowance — that needs a deliberate decision from you, not a number I
should estimate.

**Proposed order, if you approve spend:**
1. **Apollo, 75 leads, $0 (within existing plan)** — spend this first,
   it's free. Prioritize the highest-value segment rather than
   round-robin: the 24 bounced leads whose company_domain turned out to
   be fabricated (§1) need a *real* domain rediscovered, which is
   exactly what Apollo's org lookup is good for — I'd point the 75
   credits there first, since getting the real company right fixes both
   a bounce and unlocks pattern-derivation for that domain going
   forward, rather than spending them on net-new missing-email leads
   where a plain search-enrichment resume might get there for free once
   §1's operational fix lands.
2. **Everything else — needs your decision**, both on which vendor
   (once ZoomInfo/Clay are connected, I can check whether either offers
   a per-credit price without committing spend) and on whether it's
   worth paying at all before first fixing the free path (§4's
   operational fix), which — if it just starts working again — recovers
   most of the same 1,386 at zero marginal cost via the enrichment
   pipeline you already built and are already paying for (Claude web
   search calls), rather than paying a second vendor for the same job.
   **My recommendation: fix §4 first, re-measure the gap, then decide
   how much paid enrichment is actually still needed** — spending on
   Apollo/ZoomInfo/Clay before that risks paying to solve a problem the
   existing pipeline would have solved for free once it's running.

### Step 6 — real-time verification (ZeroBounce / NeverBounce / equivalent)

**Not run — no such integration exists in this repo currently, and no
money spent.** I did not find a NeverBounce/ZeroBounce (or equivalent)
API key or client anywhere in the codebase. Before anything becomes
"sendable," every recovered/existing address needs syntax + MX +
disposable + role-account (all already free and already wired — see §3
of the prior findings doc) **plus** a real-time verification call, which
requires you to pick a provider and I'd need an API key. Proposing, not
doing: NeverBounce and ZeroBounce both offer pay-per-verification
pricing in the sub-cent-to-low-cent range per address at volume, but I'm
not going to quote you a specific number I can't confirm against your
actual account — get a quote from whichever you prefer before I wire
anything up. Until this exists, **all 196 pattern-derived candidates and
any future third-party-enrichment results stay in the
`inferred_pending_verification` pool** — not sendable, per your own
instruction.

### Step 7 — apply steps 1-6 to the 60 bounced

- **Hard vs soft split: not possible with current data** — no
  bounce-type or SMTP code is captured anywhere in this system (same gap
  as §1). Stated, not guessed.
- **24/60** — domain doesn't exist or has no MX. No address is correct
  here until the *real* company domain is found — that's a
  re-enrichment/lookup problem (steps 4/5 pointed at the *company*, not
  a local-part guess), not something steps 1-4 as currently scoped can
  fix (they assume `company_domain` is already correct).
- **8/60** land on a domain with a strong (≥3 sample) pattern. Checked
  each one against the domain's established pattern using the actual
  `first_name`/`last_name` on file: **7 already match the best-known
  pattern exactly** — meaning the guess wasn't wrong, so the bounce is
  something else (person changed jobs, wrong individual, transient
  block) that this data can't resolve. **1 (Forrester)** revealed a
  name-parsing artifact — the stored `last_name` was `"P. Gownder"`
  (a middle initial folded into the surname field), and cleaning it to
  the final token produces `jgownder@forrester.com` instead of the
  bounced `j.pgownder@forrester.com`. Flagged for human review per your
  instruction ("if the fix isn't deterministic, flag it") — this is one
  specific person, not a systemic fix, so I did not auto-apply it.
- **26/60** — valid domain, but fewer than 3 confirmed samples for that
  domain. Not enough internal data to derive a candidate without
  guessing the local part, which you explicitly said not to do. These
  route to step 5 (third-party) or wait for re-enrichment.
- **Suppression: all 60 are correctly suppressed today** (confirmed via
  the live send gate, 0 violations). Since hard/soft can't be
  distinguished, the current *and* correct-until-proven-otherwise
  default is to treat every recorded bounce as suppressing permanently
  (no retry) — that's what's already happening. A defined soft-bounce
  retry-with-cap policy needs the hard/soft signal first; I'm not
  proposing one blind.

---

## 3. Recovery table

### The 1,441 missing emails

| Method | Recovered | Notes |
|---|---:|---|
| Step 1 — re-parse raw payload/notes | 0 | source data structurally never contains an email (verified) |
| Step 2 — internal cross-match | 0 | zero matches on linkedin_url; phone 0% populated; contacts/persons empty |
| Step 3 — deterministic repair | 0 | n/a — these are null, not malformed |
| Step 4 — pattern-derived (≥3 samples) | **55** (this month) / **196** (full backlog) | staged as `candidate_email`, inferred, not sendable |
| Step 5 — third-party enrichment | 0 spent | 75 Apollo credits available free; proposal above, awaiting your go/no-go |
| Step 6 — real-time verification | 0 run | no provider wired up yet; nothing is "sendable" until this exists |
| **Verified sendable** | **0** | nothing has passed step 6 yet |
| **Remain unreachable (this month's cohort, cost-free)** | **1,386** | primary path: fix the enrichment-pipeline stall (§4 of prior doc, free); secondary: paid enrichment once you approve spend |

### The 60 bounced

| Outcome | Count | Notes |
|---|---:|---|
| Domain doesn't exist/no MX — needs real domain, not a local-part fix | 24 | route to re-enrichment |
| Address already matches best-known domain pattern — no better candidate from internal data | 7 | likely a non-address reason (job change, wrong person, transient) |
| Corrected candidate found (name-parsing fix) | 1 | Forrester case — flagged for human review, not auto-applied |
| Insufficient pattern data to derive without guessing | 26 | needs third-party or waits for more confirmed samples |
| Hard vs soft classified | 0 | not possible with current data — stated gap |
| Suppressed at send-gate (working correctly) | 60/60 | 0 violations found |
| **Verified sendable** | **0** | none have passed real-time verification (step 6 doesn't exist yet) |

---

## 4. Deliverables

**1. Findings doc** — this file + `BOUNCE_DIAGNOSIS_2026-08-28.md`
(diagnosis, every query + raw output).

**2. Ranked root causes** — see prior doc §3 for bounces; §1 above for
the recap.

**3. Recovery migration script** —
`backend/scripts/recover_missing_emails.py`. Defaults to `--dry-run`
(no writes). `--apply` writes step-3 repairs to `leads_raw.email`
(logging before/after to a new `email_recovery_log` collection first)
and step-4 candidates to `leads_raw.candidate_email` +
`email_status="inferred_pending_verification"` (never to `email`
directly). `--rollback <run_id>` undoes a specific `--apply` run using
that log. **I ran it in dry-run only** — the 55/196 numbers above are
its actual dry-run output against production; nothing was written.

**4. Ingestion-time validation code** — already implemented earlier in
this investigation and still in this checkout (uncommitted):
- `backend/app/services/outreach/email_validator.py` — extended with
  disposable-domain list, typo-domain correction, and a `domain_exists()`
  MX-or-A check.
- `backend/leads/web_search_enrichment.py` — now rejects a
  non-resolving `company_domain` before it can be used to predict an
  email (this is the fix for the 40%-of-bounces root cause in §1).
- `backend/routers/cold_outreach_router.py` — added a deliverability
  gate (syntax/role/disposable/MX) to the live pre-send path, running
  for every send, not just ones tagged `pattern_derived` (the existing
  guard missed 80% of this batch's bounces because they were tagged
  `email_status: "predicted"`, a different field the old guard doesn't
  check).
- `backend/routers/deliverability.py` — fixed a relative-import bug that
  was silently disabling the already-built SPF/DKIM/DMARC/MX monitoring
  router in production (confirmed via the real traceback on the prod
  venv).

**5. Recovery table** — §3 above.

**6. Monitoring** — `backend/scripts/bounce_rate_monitor.py`, extended
today with an email-capture-rate-by-source check alongside the existing
bounce-rate-by-campaign and enrichment-stall checks. Live output just now:
```
=== Bounce rate by campaign (trailing 30d, alert > 5%) ===
  cogentix   sends= 5058 bounced=1332 rate=26.3% *** OVER THRESHOLD ***
  sfw        sends=11952 bounced=3221 rate=26.9% *** OVER THRESHOLD ***
  bimwave    sends=12917 bounced= 305 rate= 2.4%

=== Email capture rate by source (trailing 30d, alert < 30%) ===
  websearch     leads=1677 with_email=313 rate=18.7% *** UNDER THRESHOLD ***
  gmail_reply   leads=  78 with_email= 78 rate=100.0%

=== Enrichment queue health (stall alert if backlog > 0 and 0 attempts in 3h) ===
  AwaitingEnrichment backlog: 2581
  Classification attempts in last 3h: 0
  *** STALLED ***
```
Exit code is non-zero on any breach — wire it into a cron/systemd timer
to get this alerted daily instead of discovered a month later.

---

## 5. Where evidence is thin (stated, not guessed)

- Hard vs soft bounce type, and SMTP diagnostic codes — not captured
  anywhere in this system's data. Can't be reconstructed retroactively.
- Exact split of the 56.7% "valid domain" bounce bucket between
  wrong-local-part vs receiving-side block (e.g. the surveyfieldwork.com
  SPF defect) — no data to allocate this with confidence.
- Apollo/ZoomInfo/Clay/Explorium match rates and per-credit overage cost
  for this specific lead population — not estimated; get a real quote
  before spending beyond the free 75 Apollo credits.
- ZeroBounce/NeverBounce (or equivalent) accuracy and pricing for this
  volume — no integration exists yet to measure against.
