# Cycle Analysis, Root Cause, and the 50-Lead Sample

Fourth doc in this investigation. Read `BOUNCE_DIAGNOSIS`, `RECOVERY_PLAN`,
and `HALT_AND_VERIFY_PLAN` first. **No production writes were made in
this session — everything below is a read, a code change sitting
uncommitted in this checkout, or a real (but blocked/incomplete) attempt
at one of the three things you authorized.**

**Authorization status, upfront:**
- **py-spy**: already installed on the VM, used it, real findings below.
- **Bouncer purchase**: **could not execute — no account, no API key, no
  payment mechanism available to me.** See Priority 3.
- **Seed-inbox test send**: **could not execute — no seed inbox address
  was given.** See Priority 4. What I *could* check for free, I did.

---

## PRIORITY 1 — Cycle analysis: this correction changes the picture

You asked whether the clean stretch reflects the pipeline improving or
being down. **Neither, exactly — and the real answer reframes the whole
investigation: the historical bounce cycle is mostly not about the
AI web-search pipeline at all.**

### What actually drove sends, week by week

Joined `outreach_sends_v2` to `leads_raw` by email, all 60,309 historical
sends, grouped by week with source mix and average lead-age-at-send:

```
W15  sends=1938  bounce=64.3%  sources: NOT_FOUND_IN_LEADS_RAW=1243, csv_import=499, gmail=117
W18  sends=8619  bounce=53.3%  sources: csv_import=5021, NOT_FOUND_IN_LEADS_RAW=2434, gmail=826
W21  sends=1291  bounce=47.6%  sources: csv_import=1058, NOT_FOUND_IN_LEADS_RAW=205
W25  sends=2057  bounce= 5.3%  sources: csv_import=1061, NOT_FOUND_IN_LEADS_RAW=624, gmail=227
W29  sends= 737  bounce= 1.5%  sources: NOT_FOUND_IN_LEADS_RAW=540, csv_import=100
W30  sends= 524  bounce= 0.8%  sources: NOT_FOUND_IN_LEADS_RAW=447, csv=45
W32  sends=13856 bounce=20.3%  sources: csv_import=7658, NOT_FOUND_IN_LEADS_RAW=4704
W35  sends= 194  bounce= 0.0%  sources: csv=82, gmail_reply=50, websearch=23
```
(Full 21-week table available on request — this is the load-bearing
subset.) `NOT_FOUND_IN_LEADS_RAW` means the sent email's originating
`leads_raw` doc couldn't be located by exact match — likely older records
predating some schema/field change, or promoted-from-reply records; not
`websearch`.

**`csv_import` is the dominant source across nearly the entire 21-week
history — websearch (the pipeline this whole investigation has focused
on) barely registers except in the last few weeks.** This means my prior
sessions' root-cause work (the fabricated-domain/AI-hallucination
diagnosis) correctly explains **this month's** problem, but does **not**
explain the four-month cyclical pattern you're asking about now — that's
a different mechanism.

**Email verification status at send time**, same weeks: the majority of
sends every single week carry `email_status: None` or `"unknown"` —
meaning most historically-sent addresses, across the whole cycle, were
never verified or classified *at all* before being emailed, regardless
of source. That's a third, independent data-quality gap alongside the
AI-hallucination one, on the bulk-import path specifically.

### Was the pipeline actually improving, or just off?

**Direct evidence it was off, not improved — found in the deploy log,
not inferred:**
```
2026-07-12  fix(leads): restore web_search_enrichment — enrichment was a silent no-op
2026-04-07  fix: consolidate MongoDB connections to singleton pool, fix startup regression
```
The July 12 commit message says outright that `web_search_enrichment`
was a **silent no-op** before that date — meaning through most of the
clean period (W25-27 at minimum, since this fix landed W28), the AI
pipeline wasn't producing addresses at all. The clean weeks were clean
because they were dominated by `csv_import` batches that happened to be
better lists, and/or lower volume overall (737-2057 sends/week vs.
8619-13856 in the bad weeks) — **not because any pipeline got fixed.**
Then W28 restored web_search_enrichment, and by W31-34 (August) bounce
rates climbed back to 13-20%, and the `predicted`/`pattern_derived`
email_status values start appearing again in the send mix around W29-30
and W34-35 — consistent with the restored (but still domain-unverified,
until my prior-session fix) AI pipeline contributing to the renewed rise,
layered on top of whatever CSV batches were also going out.

**And the April 7 commit is the same "consolidate MongoDB connections to
a singleton pool" fix I'd want to make today** (see Priority 2) —
someone already fixed this exact anti-pattern once, at the very start of
the bad period, and it's back: 99 in-function `MongoClient()`
instantiation sites exist in the codebase today (confirmed by grep), and
49 live simultaneously in one process snapshot (confirmed by py-spy).
Either the original fix was incomplete, or four months of subsequent
feature work reintroduced it call-site by call-site. I didn't dig into
which — not enough time budget left in this session, and it doesn't
change the fix (see Priority 2).

### What causes the recurrence, and does the plan survive it?

**Two independent bad-data sources, not one:**
1. Periodic large, unverified CSV-import batches (the dominant volume
   driver across the whole cycle — W18's 8619 sends and W32's 13856
   sends are both csv_import-heavy spikes).
2. The AI web-search pipeline, when it's actually running (which it
   wasn't for a chunk of the "clean" period), producing
   unverified/fabricated addresses — this month's specific problem,
   already diagnosed and partially fixed in prior sessions.

**Does the current fix plan survive a future spike from either source?
Yes, structurally — and this is worth being confident about, not just
hopeful:** the `sendable` flag gate (Part 3, prior session) is enforced
in the actual send-fetch query in `cold_outreach_router.py`, independent
of which pipeline or import path produced the `outreach_leads_v2` record.
A future bad CSV batch or a future AI-pipeline regression both have to
get past the same chokepoint before anything sends. **What the plan does
NOT yet do**: add ingestion-time validation specifically to the CSV
import path itself (I only patched `web_search_enrichment.py`) — so nothing
stops someone from uploading a bad CSV, it just stops that CSV's contents
from being sendable until verified. That's the correct minimum bar per
your "enforce in the query, not convention" instruction from last
session, and it holds. If you also want CSV imports to get a "this list
looks bad" warning *at upload time* rather than only being silently
blocked from sending later, that's separate, unscoped work — flagging it,
not doing it.

---

## PRIORITY 2 — Crash diagnosis, finished

### Root cause, with the profile

`py-spy dump --pid <MainPID>` on the live process:
```
49 threads named "pymongo_server_monitor_thread"
49 threads named "pymongo_kill_cursors_thread"  (same count, paired)
49 threads named "pymongo_server_rtt_thread"    (same count, paired)
= 147 of the ~165-169 total threads, from MongoDB client monitoring alone
```
**Each of those triples belongs to one separate, still-alive
`pymongo.MongoClient()` instance.** A correctly-pooled app has exactly
one (the shared client from `db_pools.py`). This process had **49 live
simultaneously** at the moment of the dump. Also present: multiple
distinct `ThreadPoolExecutor` pools (`ThreadPoolExecutor-0`, `-1`, `-2`,
each spawning their own numbered workers) — same anti-pattern, a second
symptom of the same root habit (create-fresh-instead-of-reuse).

**Why**: `grep -rn "= MongoClient("` across `backend/` finds **99
call sites inside function bodies** (not at module load time) — e.g.
`routers/campaign_automation.py` alone has **8 separate function-local
`MongoClient(mongo_uri)` instantiations** (lines 378, 445, 523, 582, 654,
748, 828, 940), one per endpoint, none reusing a shared client. Every
call to any of these functions creates a brand-new client with its own
connection pool and 3 background threads, and none of them are ever
`.close()`'d. In CPython these get garbage-collected *eventually*, but
under real request/job load, new ones get created faster than old ones
get collected, and each live one holds real memory (connection pool
buffers, socket state) on top of its threads — that's the accumulation
that walks the process into its 2GB `MemoryMax` and gets SIGKILLed.

**This is not an unbounded-batch-size or full-collection-load problem —
I looked for that too and it's not what's driving this.** It's
specifically the MongoClient-per-call anti-pattern, and it's systemic
(99 sites), not one bad function.

**I am not recommending raising the memory cap.** The profile doesn't
show a legitimately large working set — it shows 49 duplicate client
objects that shouldn't exist. The fix is structural: route every one of
those 99 call sites through the existing `db_pools.get_db()` singleton
(which `web_search_enrichment.py` and a handful of other files already do
correctly) instead of instantiating `MongoClient()` locally. **I did not
make this change** — 99 call sites across a live, already-fragile
production service is a large, blast-radius-heavy refactor that needs
real review and testing, not a blind sweep edit in the same session I
found the bug. Flagging it as the concrete next step, with the evidence
to justify it, rather than doing a rushed version of it.

### Restart policy + alert

**Not applied** (systemd unit changes are a production infra change I
didn't get explicit sign-off for this session — py-spy and Bouncer and
seed-sends were authorized, this wasn't). Proposed, unchanged from last
session:
```ini
[Service]
Restart=always
RestartSec=30
StartLimitIntervalSec=600
StartLimitBurst=5
```
**Alert — implemented and tested.** New:
`backend/scripts/crash_loop_alert.py` — checks `journalctl` for restart
count in a trailing window (default 60 min, threshold >3), exits non-zero
if the service looks like it's in a crash loop. Ran it live just now:
```
Restarts: 2
SIGKILLs (OOM-pattern): 0
OK — restart count within normal range.
```
Wire it into cron/systemd-timer alongside `bounce_rate_monitor.py` and
this becomes visible in under an hour, not a month.

---

## PRIORITY 3 — Verification: blocked, stating why rather than working around it

**I cannot purchase Bouncer credits.** I have no Bouncer account, no API
key, and no payment mechanism available in this session — there's no
Bouncer/ZeroBounce/NeverBounce connector configured for me to use, and I
have no way to create an account or enter payment details (that needs a
browser and a human, or an existing account's API credentials handed to
me). Checked the tools actually available to me this session — Apollo is
connected (checked last session, free credits only), ZoomInfo and Clay
need you to authorize them via claude.ai connector settings, and none of
the three verification providers you named have any connector at all.

**What I need from you to proceed**: either (a) an existing Bouncer
account + API key, so I can integrate and run it, or (b) you create the
account and buy the credits yourself (their pricing page is public,
sign-up is self-serve), then hand me the API key. I'm not going to guess
around this or substitute a different spend without checking with you
first — this is exactly the kind of thing last session's "two correct
refusals" pattern applies to.

**What's ready and waiting**: `backend/scripts/verification_gate.py` has
the full chain built — free checks already tested live, `paid_verify()`
stubbed with the exact endpoint for all three providers noted in the
docstring, `sendable` flag wired into the send query. The moment I have
a key, running all three cohorts (staged → candidates → sent-clean, your
specified order) is a single command, not new development.

**Cohort pass rates — free-check portion only, since that's all I can
run:**
```
Staged (n=249):        90.0% pass free checks (25 fail, all no_mx_records)
Candidates (n=196):    100.0% pass free checks — structurally can't fail;
                        this is exactly the cohort that needs the paid
                        step and I can't give you that number yet
Sent-clean (n=82):     98.8% pass free checks (1 role_address)
```
Zero addresses in any cohort have a `sendable: true` flag today.

---

## PRIORITY 4 — Auth validation: partially blocked, same honesty as before

**Re-checked live, same defect, unfixed**: `surveyfieldwork.com` still
has two SPF TXT records, still no `google._domainkey`. **I do not have
DNS provider access**, so the fix I proposed last session was never
applied — there's nothing to "confirm" yet because the underlying record
hasn't changed. If you have DNS access, apply the merge I proposed
(`RECOVERY_PLAN`/`HALT_AND_VERIFY_PLAN`, Part 1) and I'll re-verify
immediately after — that's a 30-second DNS lookup on my end once it's
live.

**Seed-inbox test send: not sent.** You authorized this ("seed inboxes I
control only") but didn't give me an address, and I'm not guessing one.
Send me the seed inbox address (and confirm which sending mailbox —
`indira@surveyfieldwork.com` or whichever you want tested) and I'll send
exactly one test email, log it, and report the raw headers back
(`Authentication-Results` will show SPF/DKIM/DMARC pass/fail/none
directly — that's the actual end-to-end confirmation you asked for,
which a DNS lookup alone can't give you, since DNS only proves the
records exist, not that the sending path is using them correctly).

**Google Postmaster Tools: still no access, same as last session.**
Named again as what this leaves unverified: actual inbox-placement
reputation as Gmail's own reputation system sees it, as opposed to what
public DNS/blocklist checks can show. If you can get me read access to
the Postmaster Tools property for these domains, that closes this gap;
otherwise it stays open.

---

## PRIORITY 5 — Enrichment rebuilt, sample run, and a hard stop

### What changed in the code (all four requirements)

1. **Source URL logged for every claim** — `ai_governance/claude_gateway.py`'s
   `web_search()` previously discarded every non-text content block from
   the Anthropic response, which is why no citation data has ever existed
   anywhere in this system (confirmed by reading the code, not guessing —
   this is the literal line: `text = " ".join(b.text for b in
   response.content if b.type == "text")`, silently dropping the
   `web_search_tool_result` blocks that carry the actual URLs). Fixed to
   also extract and return those URLs. `web_search_enrichment.py`'s
   prompt now lists the retrieved source URLs and requires the model to
   cite one for `email` and `company_domain` specifically.
2. **Null instead of a constructed guess when it can't cite one** —
   enforced **server-side**, not just prompted: after parsing, if the
   model claims an email or domain but its cited `*_source_url` isn't
   actually one of the URLs the web_search tool retrieved, that field is
   nulled out. This doesn't trust the model's honesty about citing
   correctly — it checks.
3. **Null treated as successful "not found," not a retry trigger** —
   verified by reading the code path: the function only returns
   `success: False` when *both* `company_domain` and `company_industry`
   are empty; a null email with other fields present still returns
   `success: True`, and `_log_attempt(..., success=True)` is called. This
   was already true before my prior-session domain-validation change and
   remains true now — confirmed, not re-implemented.
4. **Hard-fail on MX** — already added in the prior session
   (`_domain_is_real()` check before trusting `company_domain`), still in
   place, unaffected by this session's citation changes.

### The 50-lead sample — run, and it surfaced a blocker more urgent than everything else in Part 5

Pulled 50 real `AwaitingEnrichment` leads from the backlog, ran the
*actual* (now citation-instrumented) `enrich_company_with_websearch()`
against each, live, on production data, using your existing
already-provisioned API budget (no new purchase):

```
50/50 failed identically:
  Error code: 401 - {'type': 'authentication_error', 'message': 'Invalid bearer token'}
```

**Every single attempt failed on an expired/invalid API credential — not
on data quality, not on the rebuilt logic.** This is the same 401 I
flagged as a minor "secondary issue, check later" note in the very first
session of this investigation — it turns out to be the actual, current,
total blocker on the entire pipeline, more fundamental than the
crash-loop. **Zero of 50 produced an address; zero cited a source; the
Bouncer pass rate on the output is not computable because there is no
output.** I'm reporting this as the sample result, not treating it as a
failed test — you told me not to run the full backlog on my say-so, and
this is exactly the kind of thing that justifies that caution: had I
skipped the sample and gone straight to "the fix looks right, run it on
1,386," it would have burned through the backlog attempt-count (many of
these leads already show prior `classification_attempts`) for zero
result.

**Where the credential lives, so it can be rotated**: `_get_anthropic_api_key()`
in `backend/ai_governance/ai_gateway.py` reads from
`torpedo_settings.app_settings` (doc `_id: "app_config"`, fields
`bedrock_api_key` / `anthropic_api_key`), falling back to the
`AWS_BEARER_TOKEN_BEDROCK` / `ANTHROPIC_API_KEY` environment variables if
that doc doesn't have a value. I did not read or print the actual key
value — checking that field triggered this session's own write-safety
guard, appropriately, since it's a credential. **You (or whoever manages
the Bedrock/Anthropic account) need to check whether this key expired,
was rotated elsewhere without updating this app, or was revoked, and
replace it in one of those two places.**

**Does the sample decide whether the remaining 1,386 are recoverable
through this mechanism? Not yet — the sample didn't test the mechanism,
it tested the credential.** Once the key is fixed, I'd want to re-run
this exact same 50-lead sample (not the full backlog) before touching
the other 1,336, per your instruction — that re-run is a single command
away and costs whatever 50 web-search + extraction calls cost against
your existing plan, nothing new to authorize.

---

## Deliverables

1. **Cycle analysis**: Priority 1. Recurrence has two independent causes
   (unverified CSV batches — the dominant historical driver — and the AI
   pipeline when running); the "clean" period was substantially the AI
   pipeline being silently off, not fixed, confirmed by the July 12 commit
   message itself. The `sendable`-flag gate structurally survives a
   future spike from either source.
2. **Crash root cause + profile**: Priority 2. 49 simultaneous
   `MongoClient()` instances (99 in-code instantiation sites) leaking
   threads and connection-pool memory until the 2GB cap kills the
   process. Not a working-set-size problem — did not raise the cap.
   Restart-backoff proposed, not applied (no sign-off this session);
   crash-loop alert implemented and tested.
3. **Bouncer pass rates**: blocked — no account/API access. Free-check
   portion reported per cohort; candidates called out as the cohort that
   needs the paid step most and that I can't give you yet.
4. **Auth validation**: SPF still broken (fix never applied — no DNS
   access), DKIM still missing, DMARC still `p=none`. Seed-inbox test
   not sent (no address given). Postmaster Tools still inaccessible.
5. **50-lead enrichment sample**: 0/50 succeeded — 100% failure on an
   invalid API credential, not on the rebuilt logic. Credential location
   identified for you to fix; re-run is one command once it's rotated.
6. **Go/no-go on resuming sends: NO-GO.** Unchanged from last session's
   posture, now with more reasons, not fewer: the verification gate has
   no live provider, the enrichment credential is dead so the pipeline
   can't even be tested end-to-end yet, SPF is still broken, and the
   crash-loop fix (99-site refactor) hasn't been attempted. Warm-up
   schedule from `HALT_AND_VERIFY_PLAN` stands as the plan for *when* you
   are ready — nothing about this session's findings changes that
   schedule's shape, they just confirm none of its preconditions are met
   yet.

## What I need from you to keep moving
- A Bouncer (or alternate provider) API key, or your own purchase.
- A seed inbox address + which sending mailbox to test from.
- DNS access for surveyfieldwork.com, or you apply the SPF merge
  yourself.
- Rotation of the Bedrock/Anthropic API key at the location named above.
- Sign-off to actually refactor the 99 MongoClient call sites (real
  effort, real regression risk on a fragile service — wanted your
  awareness before starting, not just doing it).

## Where evidence is thin (stated, not guessed)
- Why the April 7 MongoClient-pooling fix didn't hold — didn't dig into
  which specific commits reintroduced it; not needed to justify the fix,
  but worth knowing if you want the full history.
- Exact per-week split between "CSV batch was bad" vs. "AI pipeline was
  bad" — the source-mix data supports both contributing, not a precise
  attribution between them for every week.
- True end-to-end SPF/DKIM/DMARC pass/fail — DNS records are visible, but
  only an actual test send (blocked, see Priority 4) proves the sending
  path uses them correctly.
