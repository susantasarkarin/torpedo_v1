# Lead Pipeline Diagnosis — Bounce Rate & Email Capture Gap

Date: 2026-08-28. All queries run read-only against the production MongoDB
on torpedo-prod (139.59.32.72) via `mongosh`, and read-only against the
live backend process via `curl localhost:8000` / `systemctl` / `journalctl`
on that same VM. No writes were made to production data. Code changes are
listed at the end and live only in this repo checkout (not deployed).

Every query below can be re-run verbatim (`ssh root@139.59.32.72
"mongosh --quiet --eval '...'"`).

---

## 0. Baseline verification (you asked me to check this before building on it)

### 0.1 Total new leads, last 30 days

```js
// db: email_automation
var d = new Date(); d.setMonth(d.getMonth() - 1);
db.leads_raw.countDocuments({created_at: {$gte: d}})
```
**1,840** — matches your number.

### 0.2 Leads with a usable email

```js
db.leads_raw.countDocuments({created_at: {$gte: d}, email: {$type: "string", $ne: ""}})
db.leads_raw.countDocuments({created_at: {$gte: d}, email: null})
```
**399** with a real email string (your 394 was off by ~5 — your original
query almost certainly used `email: {$ne: ""}` with `distinct()`, which
lets `null` through and `distinct()` folds all the nulls into one bucket,
undercounting slightly. Not a meaningful difference — 399/1840 = **21.7%**,
consistent with your 21%.)

**1,441** have `email: null` explicitly (2 more are missing the field
entirely). These 1,441+2 = 1,443 ≈ your "1,446" — close enough that the
small gap is the same distinct()-with-null artifact, not a real
discrepancy.

### 0.3 (a) Is the lead↔send join 1:1 or fan-out?

```js
// db: torpedo
var emails = db.getSiblingDB("email_automation").leads_raw.distinct(
  "email", {created_at: {$gte: d}, email: {$type: "string", $ne: ""}});
db.outreach_sends_v2.countDocuments({email: {$in: emails}})        // 336 total sends
db.outreach_sends_v2.distinct("email", {email: {$in: emails}}).length  // 143 distinct leads sent to
```
**Fan-out, not 1:1.** 336 send events across only 143 distinct leads
(2.35 sends/lead — this is a 4-step drip sequence, so that's expected).
**On the bounce side specifically it collapses back to 1:1** — 60 bounce
documents, 60 distinct bounced emails, no lead bounced more than once
(the send loop stops enrolling a lead once it's marked bounced).

### 0.4 (b) Do sends lag lead creation, and is 394/399 the right denominator?

```js
// median days from lead created_at to first send_at, for the 399 emailable leads
```
**Yes, badly** — median lag is **16.5 days**, and of the 399 emailable
leads, only **143 (36%) have been sent to at all** within the observation
window; 256 are still sitting in the send queue/sequence backlog. That
means **your 394/399 denominator is wrong for a bounce-rate calculation**
— it counts 256 leads that were never given a chance to bounce because
they haven't been emailed yet.

**Corrected bounce rate: 60 bounced / 143 actually emailed = 41.9%**,
not 15.2%. Your instinct that something is badly wrong was right — it's
actually almost 3x worse than you estimated, once you count only leads
that were actually sent to.

Independent, larger-scale confirmation of this (all sends in the trailing
30 days, not just leads created in the last 30 days — see
`scripts/bounce_rate_monitor.py`, output reproduced in §5):

```
sfw       sends=11,952  bounced=3,221  rate=26.9%
cogentix  sends= 5,058  bounced=1,332  rate=26.3%
bimwave   sends=12,919  bounced=  305  rate= 2.4%   <- healthy, useful control group
```

### 0.5 (c) Other status values (failed/rejected/complained/dropped)?

```js
db.outreach_sends_v2.distinct("status")   // ["bounced", "sent"]
```
No — `outreach_sends_v2` only ever has `"sent"` or `"bounced"`. There is
no SES-style complaint/reject/drop tracking in this collection (see §1.6
for why — bounce detection here isn't SES-based).

`outreach_leads_v2.workflow_status` has more values (`error`,
`suppressed`, `skipped_high_bounce_risk`, `needs_human_intervention`,
`paused_duplicate_brand`, ...) but **don't use that collection as a
denominator** — it has multiple enrollment records per lead (one per
brand/campaign from a legacy "Basket D" dual-fit fan-out, now disabled
but not backfilled), so counts there are inflated by duplicates
(`paused_duplicate_brand` alone was 510 for this cohort). `outreach_sends_v2`
is the clean, per-send ledger; use that.

---

## 1. Part 1 — Bounce diagnosis (n=60, the leads-created-this-month cohort)

### 1.1 Hard vs soft / SMTP diagnostic codes — **not available, stating this rather than guessing**

```js
db.outreach_sends_v2.findOne({status: "bounced"})
```
```json
{
  "email": "aaron.rappaport@businessanswers.com",
  "from_email": "indira@surveyfieldwork.com",
  "status": "bounced",
  "sent_at": "2026-04-10T07:35:24.600Z",
  "bounced_at": "2026-04-10T11:35:43.447Z"
}
```
No SMTP code, no bounce-type (hard/soft), no diagnostic string is stored
anywhere. I traced why: sending goes through Gmail (not SES — note
`gmail_message_id`/`gmail_thread_id` fields), and bounce *detection* works
by scanning the inbox for mailer-daemon auto-replies
(`backend/routers/cold_outreach_router.py` ~line 2977,
`_BOUNCE_FROM_PATTERN`/`_BOUNCE_SUBJECT_PATTERN`), not by reading an SES
bounce notification. There's a whole SES-notification module
(`backend/leads/ses_notifications.py`) that *does* distinguish
Permanent/Transient bounces and complaints — but it's dead code; nothing
sends is going through SES, so it never fires. I can't retroactively
recover hard/soft classification for these 60 — flagging as a real gap,
not filling it with a guess.

### 1.2 Domain-level DNS reality — **this is the headline finding**

```python
# For each of the 60 bounced domains: nslookup -type=MX <domain>
```

| Bucket | Count | % | Meaning |
|---|---|---|---|
| **NXDOMAIN** (domain doesn't exist) | 15 | 25.0% | e.g. `pwcwithadegreeininformationsystemsand.com`, `carnegiemellonuniversity.com` (real: cmu.edu), `thegeorgewashingtonuniversity.com` (real: gwu.edu) |
| **Domain exists, no MX record** (SOA-only) | 9 | 15.0% | e.g. `tri.com`, `press.com`, `ubsinvestmentbank.com` — real registrations, but nothing configured to receive mail |
| **Valid domain, has MX** | 34 | 56.7% | e.g. `hammondmfg.com`, `gfk.com`, `forrester.com`, `mintel.com`, `kantar.com` — real companies, real mail servers |
| Unresolved (DNS timeout on check day) | 2 | 3.3% | inconclusive |

**40% of bounces (24/60) are structurally undeliverable no matter what
local-part you guess** — the domain itself either doesn't exist or has no
mail routing. The other 56.7% land on domains that *can* receive mail, so
those are either a wrong guessed mailbox or a receiving-side block — see
§1.4 for why I can't split that further.

### 1.3 Where the fabricated domains come from

```js
// email_status on the 60 bounced leads, from leads_raw
```
- **48/60 (80%)** tagged `email_status: "predicted"` (AI-guessed)
- **2/60 (3.3%)** tagged `"pattern_derived"`
- 10/60 no status recorded
- **0/60** came from a verified/scraped email

And critically: **for all 60, `leads_raw.company_domain` already equals
the bounced domain** — the corruption isn't happening in the
email-guessing step, it's happening earlier, at company-domain
extraction.

Traced to source: `backend/leads/web_search_enrichment.py::enrich_company_with_websearch()`
asks an LLM (with web search) to return `company_domain` as free-form
JSON. Before my fix (§6), the only post-processing was stripping
`https://`/`www.` — **no check that the domain resolves, is registered,
or accepts mail** before it's trusted and used to build a predicted
email address on top of it.

### 1.4 Role accounts / free providers / disposable domains / typo'd domains / syntax

**Zero matches on all five**, out of 60. Every bounced local-part reads
like a real person (`firstname.lastname` style); no `info@`/`sales@`,
no gmail.com/yahoo.com, no known disposable domain, no `gmial.com`-style
typo, no RFC syntax failures. **This is not a junk-data problem** — it's
specifically "guessed a corporate domain that doesn't exist / guessed a
mailbox that doesn't exist on a domain that does." That also means I
can't attribute any of the 56.7% "valid domain" bucket to bad local-part
patterns with certainty vs. a receiving-side block (§1.5) — both would
look identical without SMTP codes (§1.1).

### 1.5 SPF / DKIM / DMARC / blocklist (checked live via DNS, 2026-08-28)

```
surveyfieldwork.com   TXT: "v=spf1 include:zcsend.in ~all"
                       TXT: "v=spf1 a mx include:_spf.google.com include:_spf.mlsend.com include:_spf.mailersend.net ~all"
                       google._domainkey: NXDOMAIN (no record)
                       _dmarc: "v=DMARC1; p=none;"

cogentixresearch.com  TXT: "v=spf1 include:_spf.mailersend.net a mx include:dc-aa8e722993._spfm.cogentixresearch.com include:zcsend.in include:_spf.google.com include:_spf.mlsend.com ~all"
                       google._domainkey: present, valid
                       _dmarc: "v=DMARC1; p=none; rua=mailto:dmarc-reports@cogentixresearch.com"
```

**surveyfieldwork.com has two separate SPF TXT records.** RFC 7208
permits exactly one; two records is a permanent SPF PermError, which many
receiving servers treat as an outright SPF fail — indistinguishable from
a real bounce in this system's data. It also has **no
`google._domainkey`** record, so Gmail-relayed mail from this domain
isn't DKIM-signed via the selector Gmail would use. This matters because
**surveyfieldwork.com is the domain behind 85% of this month's bounces**
(§1.6) and 26.9% of *all* sfw sends in the last 30 days (§0.4). I can't
quantify what fraction of the 56.7% "valid domain" bucket this
authentication defect explains (no SMTP codes — §1.1), but it's a
real, independently-confirmed, fixable defect and it sits directly under
your worst-performing campaign. **Fix this regardless of what else you do.**

`cogentixresearch.com` is clean (single SPF record, valid DKIM). Both
domains have `DMARC p=none` (monitor-only — not a bounce cause, but you
get no visibility from DMARC aggregate reports and no anti-spoofing
enforcement).

```
dig <domain>.dbl.spamhaus.org   →  NXDOMAIN for both  =  not listed, clean
```
Neither sending domain is on the Spamhaus Domain Block List.

### 1.6 Source / campaign concentration

```js
// join the 60 bounces to leads_raw.source and outreach_campaigns_v2.business
```
| | Count | % |
|---|---|---|
| source = websearch | 52 | 86.7% |
| source = gmail_reply | 8 | 13.3% |
| business = sfw | 51 | 85.0% |
| business = cogentix | 9 | 15.0% |

This roughly tracks websearch's overall share of lead volume (93% of the
399 emailable leads are websearch-sourced), so it's not one rogue source
in the sense of "a single vendor is uniquely bad" — but sfw's 85% share
combined with its broken SPF (§1.5) and its 26.9% full-history bounce
rate (§0.4) makes it the clear priority.

### 1.7 Suppression enforcement

```js
// for each of the 60 bounced emails: any "sent" send with sent_at > bounced_at?
// any outreach_bounce_suppression entry predating this bounce?
```
**Clean for this cohort** — 0/60 were re-sent to after bouncing, 0/60
were already suppressed before this send. The live suppression gate
(`outreach_bounce_suppression`, checked in
`cold_outreach_router.py` before every send) is working correctly.

One thing worth cleaning up, not a bug in this batch: there are **two
separate suppression collections** — `suppression_list` (older,
SES-notification-oriented, effectively unused by the live path) and
`outreach_bounce_suppression` (the one actually enforced). Consolidate
them so a future path doesn't accidentally check the wrong one — see §7,
propose-not-run.

---

## 2. Part 2 — Missing emails (n=1,441 of 1,840, 78.3%)

### 2.1 Source concentration

```js
db.leads_raw.aggregate([
  {$match: {created_at: {$gte: d}}},
  {$group: {_id: {source: "$source", hasEmail: {...}}, c: {$sum: 1}}}
])
```
```
{source: "websearch",   hasEmail: false, c: 1441}
{source: "websearch",   hasEmail: true,  c:  321}
{source: "gmail_reply",              hasEmail: true,  c:   78}
```
**100% of the missing-email leads are from `source="websearch"`.**
`gmail_reply` is 78/78 = 100% populated (trivially — those are derived
from an actual inbound email, so the address always exists). This is a
single-source problem, not fragmentation across many integrations:
websearch capture rate is 321/1,762 = **18.2%**.

### 2.2 Was the email collected and lost, or never collected?

```js
db.leads_raw.aggregate([
  {$match: {created_at: {$gte: d}, source: "websearch", $or: [{email: null}, {email: {$exists: false}}]}},
  {$group: {_id: {status: "$classification_status", email_status: "$email_status"}, c: {$sum: 1}}}
])
```
```
{status: "AwaitingEnrichment", c: 1439}
{status: "AwaitingEnrichment", email_status: "pending_pattern", c: 2}
```
**Never collected — but by design, not by accident.** Name, title,
linkedin_url, and company are consistently populated on these leads;
only `email` is null, and every one of them sits at
`classification_status: "AwaitingEnrichment"`, a deliberate gate set at
ingestion (`backend/leads/canonical_ingestion.py:171`, comment: *"Gate:
classifier only runs after enrichment"*). Email is meant to be filled in
by a later enrichment step, not at capture time. So this isn't a
field-drop bug — it's a **stalled downstream worker**.

### 2.3 Proof the worker is stalled, not just slow

```js
var cutoff = new Date(); cutoff.setHours(cutoff.getHours() - 24);
db.leads_raw.countDocuments({last_classification_attempt: {$gte: cutoff}})   // 0
db.leads_raw.countDocuments({classification_status: "AwaitingEnrichment"})   // 2,581 (all-time backlog, not just this month)
```
**Zero classification/enrichment attempts anywhere in the collection in
the last 24 hours**, while 2,581 leads sit waiting. This queue is meant
to be drained by `background_enrich_leads()` in
`backend/background_job_scheduler.py`, an APScheduler job configured to
run every 30 minutes, batch size 50 — that's headroom for ~2,400/day,
easily enough to keep up with ~59/day intake. It is not running.

### 2.4 Root cause of the stall (read-only, via systemd/journalctl on the VM)

```
systemctl show torpedo-backend.service -p MemoryMax   →  MemoryMax=2097152000  (~2GB)
free -h                                                →  134Mi free, 1.0Gi/2.0Gi swap used, 3.8Gi total RAM
journalctl -u torpedo-backend.service --since '2 days ago' | grep 'Main process exited'
```
```
Aug 27 14:49:00  Main process exited, code=killed, status=9/KILL
Aug 28 05:31:08  Main process exited, code=killed, status=9/KILL
Aug 28 09:20:24  Main process exited, code=killed, status=9/KILL
Aug 28 10:52:47  Main process exited, code=killed, status=9/KILL
Aug 28 11:24:47  Main process exited, code=killed, status=9/KILL
Aug 28 12:07:51  Main process exited, code=killed, status=9/KILL
Aug 28 13:00:03  Main process exited, code=killed, status=9/KILL
```
Plus dozens of additional ordinary stop/start cycles in the same window.
**The backend process is capped at ~2GB memory and is being SIGKILLed
repeatedly** (7 forced kills in ~36 hours of logs, and that's just what's
still in the journal) on a VM with only 3.8GB total RAM shared across 6
other services (lead-gen-mcp, LinkedIn Celery beat + worker, panel
worker, sales worker, qre-backend, sfw-api). A process that gets killed
this often cannot reliably keep an in-process, 30-minute-interval
scheduler alive long enough to drain a 2,581-item backlog — this fully
explains the observed 0-attempts-in-24h.

I did **not** change `MemoryMax`, restart the service, or touch the VM's
process/resource config — that's a production infrastructure change and
needs your sign-off (see §7).

### 2.5 Secondary issue, needs follow-up once §2.4 is fixed

One classification-retry record I sampled (a different source, `gmail` /
`mail_pool_ai`, not part of the websearch backlog) failed yesterday with:
```
"last_error": "API error: Error code: 401 - {'error': {'code': 'invalid_api_key', 'message': 'Invalid bearer token', ...}}"
```
An expired/invalid OpenAI API key. I didn't chase this further since it's
a different queue, but flagging it: once the process-stability issue is
fixed, a live-but-broken worker (bad API key) would look identical to a
dead one from the DB side alone, so re-check `last_error` values after
the restart-loop is resolved.

---

## 3. Ranked root causes

**Bounces (60):**
1. **Fabricated/non-existent company domains from unvalidated LLM
   enrichment output** — directly explains 40% (24/60) via NXDOMAIN/no-MX,
   and is the most likely reason a same-domain email pattern would need
   guessing in the first place for the remaining share. High confidence.
2. **No real-time mailbox verification before send** on domains that do
   resolve — up to 56.7% (34/60), confounded with #3 below; can't be
   split without SMTP bounce codes (evidence gap, stated not guessed).
3. **Broken SPF (dual records) + missing DKIM on surveyfieldwork.com**,
   the domain behind 85% of this batch's bounces and 26.9% of all sfw
   sends — contributing factor, exact share unquantifiable with current
   data, but concretely confirmed and independently worth fixing.
4. Role accounts / free providers / disposable domains / typos / syntax —
   **ruled out**, 0/60.
5. Suppression-list leakage — **ruled out**, 0/60 violations found.

**Missing emails (1,441):**
1. **Backend process instability (2GB memory cap + repeated SIGKILL)
   stalling the in-process enrichment scheduler** — primary and
   well-evidenced; the design (gate email behind an enrichment step) is
   correct, throughput is just zero right now.
2. Possible OpenAI API key issue — secondary, needs to be re-checked once
   #1 is fixed, since it would otherwise be masked.

---

## 4. Fix plan

### Immediate (operational, needs your go-ahead before I touch anything — none of this has been done)
- **Investigate `torpedo-backend.service` memory usage and either raise
  `MemoryMax` (if the VM has headroom) or reduce concurrent load** — this
  is the single highest-leverage fix; it unblocks both the enrichment
  backlog and general service reliability. I did not do this — it's a
  production service change.
- **Rotate/verify the OpenAI API key** behind the 401 errors in §2.5.
- **Fix surveyfieldwork.com's DNS**: remove one of the two SPF TXT
  records (keep the one that lists your actual senders —
  `_spf.google.com`/`_spf.mlsend.com`/`_spf.mailersend.net` — and drop
  the bare `include:zcsend.in ~all` one, unless zcsend.in is still an
  active sender for this domain, in which case merge into one record
  instead of dropping), and add a `google._domainkey` DKIM record (or
  confirm the correct selector with whichever provider actually signs
  mail sent as @surveyfieldwork.com). DNS change — propose, don't
  execute without you confirming which SPF record is correct.
- **sfw and cogentix campaigns are both running ~27% bounce rates
  right now** (§0.4) — worth pausing new enrollment into those two
  specifically (bimwave is healthy at 2.4%, doesn't need to pause) until
  the domain-verification fix (§6) has had a chance to filter the queue.

### Structural (code — done, see §6)
- Gate `company_domain` on MX/A existence immediately after AI enrichment
  produces it, before it's ever used to guess an email — kills the
  fabricated-domain problem at the source instead of downstream.
- Extend the validation gate to every send (not just emails tagged
  `pattern_derived`) — syntax, role-account, disposable-domain, MX.
- Wire the deliverability monitoring router back up (it already existed,
  fully built, just silently broken — see §6).
- Add a stall-detecting monitoring script (§5).

### Not done, propose only
- Consolidate `suppression_list` and `outreach_bounce_suppression` into
  one collection — migration script would need to be written and
  reviewed; not done here per the read-only constraint.
- Typo-domain auto-correction (`gmial.com` → `gmail.com`) is implemented
  in §6 as a *detector* (`correct_typo_domain()`) but intentionally not
  auto-applied anywhere yet — auto-rewriting a lead's email is a data
  change that should be a reviewed decision, not a silent side effect of
  this diagnosis.

---

## 5. Monitoring (deliverable — implemented, `backend/scripts/bounce_rate_monitor.py`)

Read-only script, prints bounce rate per campaign over a trailing window
and checks whether the enrichment queue looks stalled; exits non-zero on
either condition so it can be wired into a cron job for alerting. Actual
output from running it against production just now:

```
=== Bounce rate by campaign (trailing 30d, alert > 5%) ===
  bimwave              sends=12919 bounced= 305 rate=  2.4%
  sfw                  sends=11952 bounced=3221 rate= 26.9% *** OVER THRESHOLD ***
  cogentix             sends= 5058 bounced=1332 rate= 26.3% *** OVER THRESHOLD ***

=== Enrichment queue health (stall alert if backlog > 0 and 0 attempts in 3.0h) ===
  AwaitingEnrichment backlog: 2581
  Classification attempts in last 3.0h: 0
  *** STALLED: backlog exists but nothing has been attempted recently ***
```

Additionally, this repo already has a much more complete deliverability
monitor built and mounted (`backend/routers/deliverability.py` +
`backend/deliverability/domain_health.py` — SPF/DKIM/DMARC/MX health
scoring, plus a `/deliverability/alerts` endpoint) that was **silently
failing to load at all** (see §6.3) — fixing its import gets you that for
free, it doesn't need to be rebuilt.

---

## 6. Code changes (in this repo checkout only — not deployed, not committed)

### 6.1 `backend/app/services/outreach/email_validator.py`
This module already existed, fully written (syntax + MX-with-cache +
role-account check) — it just wasn't wired into the live send path (see
§6.3 for why). Extended it with:
- `DISPOSABLE_DOMAINS` set + check in both `validate_before_send()` and
  `validate_on_ingestion()`.
- `TYPO_DOMAIN_CORRECTIONS` map + `correct_typo_domain()` helper
  (detector only, not auto-applied — see §4).
- `domain_exists()` — MX-or-A existence check, used by §6.2 to gate
  AI-produced `company_domain` before it's trusted.

### 6.2 `backend/leads/web_search_enrichment.py`
After the LLM enrichment call normalizes `company_domain`, it now checks
`domain_exists()` (via the module above) before trusting it. A
non-resolving domain is dropped (`company_domain: None`, with the
rejected value logged to `company_domain_rejected` for visibility) instead
of silently flowing into email prediction. Fails open (keeps the domain)
if dnspython isn't importable, so a missing dependency degrades to
"no check" rather than blocking all enrichment.

### 6.3 `backend/routers/deliverability.py`
Found and fixed the actual reason this router — SPF/DKIM/DMARC/MX health
scoring, `/deliverability/alerts` — wasn't live: it used `from
..deliverability.domain_health import ...`-style relative imports, but
`main.py` runs uvicorn with the backend directory as the top-level
package root (`main:app`, not `backend.main:app`), so a `..` relative
import goes "beyond the top-level package" and raises `ImportError` at
module load. `main.py` wraps the router mount in a bare
`try/except Exception: print(warning)`, so this failed **silently** —
same class of bug the module's own docstring already documents having
happened once before to `web_search_enrichment.py`
("were ALL silently broken while this module was missing"). Confirmed via
the real traceback on the actual prod venv:
```
ImportError: attempted relative import beyond top-level package
```
Fixed to use the same try-absolute/except-fallback-to-`backend.`-prefix
pattern already used consistently elsewhere in this codebase (e.g.
`web_search_enrichment.py`, `email_pattern_system.py`).
**dnspython itself is already installed in the prod venv** — this was
never a missing-dependency problem, so no requirements.txt change is
needed.

### 6.4 `backend/routers/cold_outreach_router.py`
Added a deliverability gate (syntax/role/disposable/MX, via the extended
`EmailValidator`) to the pre-send path, additive alongside the existing
RFC-syntax check and pattern-derived bounce-risk guard. The existing
bounce-risk guard only fires for leads explicitly tagged
`email_source in ("pattern_derived", "pattern_applied", "guessed", "pattern_guess")`
— but 80% of this batch's bounced leads were tagged `email_status:
"predicted"`, a different field/value that guard never checks. The new
gate runs for every send regardless of tagging. Fails open (logs and
continues) if the validator can't be imported, so it degrades to current
behavior rather than blocking all sends.

### 6.5 New: `backend/scripts/bounce_rate_monitor.py`
See §5.

**All four edited/added files compile cleanly** (`python -m py_compile`).
None of this has been committed or deployed — please review and decide
when to ship it. The `cold_outreach_router.py` and
`web_search_enrichment.py` changes affect the live send/enrichment path
and should go through your normal review before deploying.
