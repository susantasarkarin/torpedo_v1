# Halt, Fix, Verify — Parts 1-4

Third doc in this investigation (after `BOUNCE_DIAGNOSIS_2026-08-28.md`
and `RECOVERY_PLAN_2026-08-28.md`). Read those first for the underlying
numbers. This one covers: the halt (done, verified), the pipeline fix
(partially — root cause not fully isolated, stated honestly), the
hallucination-rate measurement (a real proxy, not the exact metric asked
for — explained), the verification-provider comparison + cost, and the
warm-up plan with the automatic halt actually implemented and tested.

**One write was made to production in this session, and only one:**
`torpedo.outreach_kill_switch` was set to `{paused: true}` (see Part 1).
Everything else is either a read, or a code change sitting in this repo
checkout, uncommitted and undeployed.

---

## PART 1 — Halt and assess

### 1.1 Pause, verified at the send layer

Checked before touching anything: **all 5 campaigns already have
`is_active: false`**, and the last real send in `outreach_sends_v2` was
**2026-08-25 04:10 UTC — 3.5+ days before this check**. Sending was
already halted, likely by your team in response to the earlier findings.
I did not need to newly pause anything to satisfy "no sends" — I verified
it holds.

That said, you specifically asked for enforcement "at the send layer, not
just the campaign scheduler," so I added a second, independent gate and
turned it on:

- **New:** `torpedo.outreach_kill_switch` — a single doc, checked as the
  literal first line of `_process_one_outreach_lead()` in
  `cold_outreach_router.py` (the function that actually calls the send),
  before it even looks at `campaign.is_active`. **Fails safe**: if the
  doc is missing or unreadable, sending is refused — so once this code
  ships, a fresh deploy defaults to paused with no action needed.
- **Set to `paused: true` in production right now** (the doc, not the
  code — the code isn't deployed yet). Verify/toggle with
  `backend/scripts/outreach_kill_switch.py status|pause|resume`.
- **Enforced in the fetch query too, not just inside the send function**:
  the query that pulls "due" leads now requires `"sendable": True`
  (Part 3) — a field nothing has yet, so today's leads_raw/outreach_leads
  data can't be picked up even if someone manually flips `is_active`
  back on. Two independent gates, both fail closed.

Verified the 24h halt-check script (Part 4) sees **0 sends in the last
24h**, confirming the pause is actually holding, not just configured.

### 1.2 Reputation assessment

**Historical bounce rate by week**, full send history (`outreach_sends_v2`,
week of first record = W15 / mid-April 2026):

```
W15  sends=1938   bounced=1247  rate=64.3%
W16  sends=1983   bounced= 443  rate=22.3%
W17  sends= 660   bounced=  68  rate=10.3%
W18  sends=8619   bounced=4593  rate=53.3%
W19  sends=4202   bounced= 474  rate=11.3%
W20  sends= 658   bounced= 296  rate=45.0%
W21  sends=1291   bounced= 615  rate=47.6%
W22  sends= 999   bounced= 496  rate=49.6%
W23  sends=1265   bounced= 532  rate=42.1%
W24  sends=1797   bounced= 319  rate=17.8%
W25  sends=2057   bounced= 108  rate= 5.3%
W26  sends=1773   bounced= 109  rate= 6.1%
W27  sends=1062   bounced=  45  rate= 4.2%
W28  sends= 288   bounced=  14  rate= 4.9%
W29  sends= 737   bounced=  11  rate= 1.5%
W30  sends= 524   bounced=   4  rate= 0.8%
W31  sends=5182   bounced= 858  rate=16.6%
W32  sends=13856  bounced=2806  rate=20.3%
W33  sends=7151   bounced= 970  rate=13.6%
W34  sends=4073   bounced= 226  rate= 5.5%
W35  sends= 194   bounced=   0  rate= 0.0%  (partial week — the halt)
```

**Two distinct bad periods, one real recovery in between.** Weeks 15-23
(~9 weeks, mid-April to late May) ran 42-64% bounce rates — severe,
sustained. Then weeks 25-30 (early June to mid-July) recovered to
0.8-6.1% and **held there for six straight weeks**. Then weeks 31-34
(August) degraded again to 13.6-20.3%, which is when this investigation
started and the halt landed in W35.

**That mid-year recovery is the load-bearing piece of evidence for my
recommendation.** A domain doesn't drop from 64% bounces to under 1% and
hold it for six weeks unless the receiving mail providers' reputation
systems are still willing to reconsider it — that's inconsistent with
"permanently burned." I read this as: **warm up the existing domain,
don't move to a new one** — but see the honest gap right below before
you act on that.

**What I could not check, and why:**
- **Google Postmaster Tools and Microsoft SNDS — no access.** Both
  require an authenticated account tied to the domain (Postmaster Tools:
  a verified Google account with domain ownership; SNDS: Microsoft
  account with the sending IP range delegated to it). I have neither. If
  you want this checked, you'd need to either grant access or pull the
  numbers yourself and hand them to me.
- **SNDS specifically may not even apply here.** You send through
  Gmail's own infrastructure (`gmail_message_id`/`gmail_thread_id` on
  every send record — confirmed in the prior diagnosis), not from your
  own IP. SNDS monitors reputation for organizations sending directly
  off their own IP block; Gmail-relayed mail rides on Google's shared
  sending reputation, which Postmaster Tools (Gmail-specific) is the
  right tool for, not SNDS.
- **Blocklists**: re-checked `surveyfieldwork.com` and
  `cogentixresearch.com` against Spamhaus DBL just now — still clean,
  same as the prior check.
- **Sending IP blocklist check**: not meaningful for the same reason —
  Gmail's sending IPs are shared and rotating across all Gmail/Workspace
  senders, not something scoped to your domain's reputation specifically.

**My recommendation, with the confidence level stated honestly:** warm up
the existing domain rather than migrate. Medium-high confidence — backed
by the real recovery pattern above, not by Postmaster/SNDS data I don't
have. If you can pull even a few weeks of Postmaster Tools domain
reputation history before restarting, that would either confirm this or
change it, and it's a five-minute check on your end if you have the
Google account access.

### 1.3 SPF / DKIM / DMARC — fix proposed, not executed (no DNS access)

Re-confirmed live, same defect as before:
```
surveyfieldwork.com:  TWO SPF TXT records (RFC 7208 violation — permanent
                       PermError on lookup)
                         "v=spf1 include:zcsend.in ~all"
                         "v=spf1 a mx include:_spf.google.com include:_spf.mlsend.com include:_spf.mailersend.net ~all"
                       No google._domainkey DKIM record
cogentixresearch.com: Clean — single SPF, valid DKIM
```
**Proposed fix** (needs your DNS provider access — I don't have it):
merge into **one** SPF record. If `zcsend.in` is still an active sender
for this domain, merge everything into:
```
v=spf1 include:zcsend.in a mx include:_spf.google.com include:_spf.mlsend.com include:_spf.mailersend.net ~all
```
If `zcsend.in` is legacy/unused, just delete that record and keep the
second one as-is. **Confirm which senders are actually live for this
domain before applying** — I inferred from the SPF includes, not from an
account inventory. Add a `google._domainkey` DKIM record (or whichever
selector your actual Gmail-relay provider uses — check the sending
account's DKIM setup, since I can only see what's published in DNS, not
which selector was configured on the sending side).

**"Verify with an actual test send to a seed inbox" — flagging a
conflict, not doing it.** Your constraint says "no sends of any kind
until Part 4 is signed off," and a test send, even to a seed inbox you
control, is still a send. I'm not sending anything without you explicitly
carving out an exception for a controlled test — say the word and I'll
either do it or tell you exactly what to run yourself (e.g., a
mail-tester.com or Postmark seed-test check) once SPF is fixed.

---

## PART 2 — Fix the pipeline

### 2.1 Crash-loop root cause — partially isolated, not fully proven

What I confirmed:
- `torpedo-backend.service` is capped at `MemoryMax=2097152000` (~2GB),
  `Restart=always`, no backoff (`RestartSec` unset = immediate restart).
- Journal shows repeated `Main process exited, code=killed, status=9/KILL`
  — a cgroup or kernel OOM kill, not a clean crash (no Python traceback
  precedes it in the journal, consistent with SIGKILL rather than an
  unhandled exception).
- **Live process snapshot just now**: RSS 582-647MB, actually *trending
  down* slightly over a 30-second window, **165-167 threads** — high for
  a single uvicorn worker (expect a few dozen at most: uvicorn's own pool
  + APScheduler's default 10-worker executor). 3.8GB VM, 6+ other
  services competing for the same memory.
- **12 files spawn raw `threading.Thread()` directly**
  (`background_job_scheduler.py`, `email_sync/*`, `leads/imap_idle_service.py`,
  `leads/imap_leads_service.py`, `leads/parallel_email_sync.py`, `main.py`,
  `outreach_engine/scheduler.py`, `routers/cold_outreach_router.py`,
  `routers/gmail.py`, `routers/panel_invitations.py`) — a plausible thread
  (and therefore memory) accumulation source if any of them don't
  properly join/bound their pool.
- **Ruled out**: IMAP IDLE watchers specifically —
  `imap_accounts.is_active: true` count is currently **0**, so that
  mechanism (which does spawn 2 threads/mailbox, by design, with a
  correct dedup guard) isn't contributing right now.
- **Could not go further**: getting past "165 threads exist" to "here's
  which function created them" needs an in-process thread dump with
  actual Python-level names/stacks (e.g. `py-spy dump --pid <pid>`).
  `py-spy` isn't installed on the venv and I didn't install it — that's a
  new package on an already-unstable production box, which I'm not doing
  without your sign-off even though it's a read-only introspection tool.
  Linux's raw `/proc/<pid>/task/*/comm` just shows "python" for every
  thread (Python doesn't set OS thread names by default), so it couldn't
  tell me more.

**Honest bottom line: I found the mechanism (SIGKILL under memory
pressure) and a real, unresolved red flag (165+ threads, well above
what's expected), but not the specific line of code causing it.** I did
NOT raise the memory limit, and I'm not recommending that as the fix —
you were right to ask for the root cause instead. **My concrete next
step, which needs your approval since it touches the live process:**
`pip install py-spy` (read-only sampling profiler, does not pause or
restart the process) in the venv, then `py-spy dump --pid <pid>` at two
points a few minutes apart to get actual named thread stacks. That would
turn "165 threads, unknown source" into an actual answer. I'm stopping
here rather than guess which of the 12 files it is.

**Restart policy + alerting:**
- Proposed systemd change (not applied — infra change, needs your
  sign-off): add `RestartSec=30` and `StartLimitIntervalSec=600` /
  `StartLimitBurst=5` so repeated crashes back off and eventually stop
  auto-restarting instead of hot-looping, surfacing as a clearly "down"
  service instead of a silent crash-loop.
- **Alert — implemented, not just proposed.** See §5.

### 2.2 Output-quality: hallucination rate

**What you asked for — "does this exact address appear in a retrievable
source" — I can't measure.** No source URL or snippet is recorded
alongside any produced address anywhere in this data. `web_search_enrichment.py`
logs success/failure/latency to `lead_enrichment_logs`, but not the
citation the model used. Without that, there's nothing to check the
address against retroactively, and re-running the original searches to
reconstruct citations would mean spending on web-search API calls I
haven't been authorized to spend on. Stating this as a real gap, not
estimating around it.

**What I could measure for free, as a lower-bound proxy: domain-level
fabrication rate across all 399 currently-held addresses** (not just the
60 that already bounced):
```
393 distinct emails, 306 distinct domains checked via MX/A lookup:
  244 domains (79.7%) — HAS_MX, plausible real domain
   33 domains (10.8%) — NXDOMAIN, does not exist
   22 domains (7.2%)  — exists, no MX record, cannot receive mail
    7 domains (2.3%)  — DNS timeout / inconclusive

Per email (weighted by how many addresses share a domain):
  330/393 (84.0%) — sit on a plausible/real domain
   55/393 (14.0%) — sit on a domain that is fabricated or dead
    8/393 (2.0%)  — unresolved
```
**14.0% is a hard floor on the hallucination rate — these 55 addresses
are wrong regardless of what local-part was guessed, because the domain
itself can't receive mail.** It is not the full rate: a domain existing
doesn't mean the specific person's address on it is real, and the actual
measured bounce rate on sent addresses (41.9%) is much higher than 14% —
meaning wrong-local-part-on-a-real-domain is doing a lot of additional
damage on top of pure domain fabrication. Both numbers are real,
neither is the full "was this address ever actually seen anywhere"
answer you asked for.

**Change made, matching your instruction exactly:** the enrichment step
now refuses to emit a `company_domain` that fails an MX/A check — added
in the prior turn of this investigation (`web_search_enrichment.py`,
still in this checkout). A non-resolving domain is dropped
(`company_domain: None`, with the rejected value kept in
`company_domain_rejected` for visibility) instead of being trusted. Per
your "return null, treat null as a successful not-found, not a retry
failure" instruction: I checked — `_log_attempt(..., success=True)` is
still called on that path (the enrichment call itself succeeded; it just
found no trustworthy domain), so this doesn't trip the retry-on-failure
logic. Confirmed by reading, not by a live test (no enrichment is
running to observe right now — see §2.1).

**Not yet done: instrumenting every future address with its source
URL/snippet**, which is what would let you compute the exact metric you
asked for going forward. That's a real, scoped code change to
`web_search_enrichment.py`'s LLM prompt/parse step (ask the model to
return a `source_url` alongside each field, store it) — I didn't write
it in this pass given everything else in scope; flagging it as the
natural next piece of Part 2 if you want it.

---

## PART 3 — Verification gate

### 3.1 Provider comparison and cost (researched live, nothing purchased)

| Provider | Price per check (volume-dependent) | Catch-all handling | Notes |
|---|---|---|---|
| **Bouncer** | ~$0.002-0.008 (as low as $1,000/500k credits, never expire) | Rated "strong" | Fastest quoted response (~100ms), cheapest at volume |
| **NeverBounce** | ~$0.002-0.008, starts at $0.008/check pay-as-you-go | Rated "medium" | Mid-priced, slower (~200ms) |
| **ZeroBounce** | $39/2,000 credits ($0.0195/check) at entry tier; drops to ~$0.007-0.013 at bulk; subscription $99/mo for 25k (~$79/mo annual) | Rated "strong" | Free tier: 100 credits/month |

*(Pulled from two independent pricing-comparison sources today, which
disagreed on exact numbers within the same rough range — treat this as
"confirm on the vendor's actual pricing page before buying," not a
locked quote. See sources at the end of this doc.)*

**Cost for ~1,800 checks:**
- **Bouncer: ~$4-14** (cheapest at this volume, strong catch-all
  handling, fastest — my recommendation if the "strong" catch-all rating
  holds up, given ~14%+ of your addresses will hit dead/fabricated
  domains where catch-all vs. hard-invalid distinction matters)
- **NeverBounce: ~$14**
- **ZeroBounce: ~$39** (2,000-credit minimum bundle covers it in one
  purchase, but priciest per-check at this volume)

**Not integrated. No API key exists, no account was created, nothing
was purchased.** `backend/scripts/verification_gate.py` has the chain
built (syntax → role → disposable → MX, all free and already tested
live) with an explicit `paid_verify()` stub that returns `None` — never
a fabricated valid/invalid — until you pick a provider and I get a key.

### 3.2 `sendable` flag — enforced in the query, not convention

Per your instruction, this isn't a suggestion anywhere in code — it's a
hard filter. `cold_outreach_router.py`'s fetch-due-leads query now
requires `"sendable": True`:
```python
camp_due = list(db["outreach_leads_v2"].find({
    "campaign_id": cid,
    "workflow_status": {"$in": [...]},
    "next_send_at": {"$lte": now},
    "sendable": True,   # <-- new, hard requirement
}).limit(2))
```
No `outreach_leads_v2` doc has this field set yet, so **nothing is
pickable right now regardless of the kill switch or campaign is_active**
— triple-gated. Only `verification_gate.py`, once wired to a real
provider, would ever set it to `True` (and only off a "valid" result,
per your spec — catch-all/unknown/invalid never set it).

### 3.3 Backfill verification — free-check pass rates (paid step not run)

Ran the free half of the chain (syntax/role/disposable/MX) against all
three cohorts, live, just now:

```
Staged-but-unsent (n=249, ~256 stated — small diff from timing/dedup):
  Pass free checks:  224 (90.0%)
  Fail:               25 (10.0%) — all no_mx_records
  Paid verification: NOT RUN
  Sendable:           0

Sent, did not bounce (n=82, ~83 stated):
  Pass free checks:   81 (98.8%)
  Fail:                1 (1.2%) — role_address (slipped through despite
                                   having actually sent successfully once)
  Paid verification: NOT RUN
  Sendable:            0

Pattern-derived candidates (n=196):
  Pass free checks:  196 (100.0%)
  Fail:                0
  Paid verification: NOT RUN
  Sendable:            0
```
**The candidates cohort passing 100% of free checks is expected, not
reassuring** — a candidate only gets generated for a domain that already
has ≥3 confirmed real addresses, so the domain necessarily has MX; the
local part is a clean programmatic guess, so it always passes syntax.
Free checks structurally can't fail this cohort. **This is exactly the
cohort where the paid step matters most** — it's the one where "does
this specific inferred local part actually exist" is genuinely unknown,
and it's the one you specifically said you expect a high failure rate
on. I can't give you that number without a provider — see §3.1.

**Zero addresses across all three cohorts are verified sendable today.**
That's correct and expected given nothing has passed the paid step yet —
not a bug, the gate working as designed.

---

## PART 4 — Warm-up plan

### 4.1 Proposed schedule

Given the recovery evidence in §1.2 (the domain has proven it can climb
back under 1% within ~6 weeks once given clean input), and given the
2% halt threshold you specified:

| Day | Daily cap (per sending domain) | Gate to advance |
|---|---|---|
| 1-3 | 20 | 24h bounce rate < 2% each day |
| 4-7 | 50 | 3-day trailing rate < 2% |
| 8-14 | 150 | 7-day trailing rate < 2% |
| 15-21 | 400 | 7-day trailing rate < 2%, no manual halts triggered |
| 22+ | Back to normal campaign volume | sustained < 2% for 2 full weeks |

Every single address in every one of these batches must already carry
`sendable: True` (§3.2) — the warm-up caps are a volume throttle on top
of the verification gate, not a substitute for it. **Do not resume sfw
and cogentix at the same cap as bimwave** — bimwave's history (2.4%
bounce, never spiked above single digits) doesn't carry the same risk
profile as the other two (26-27% average, both had the SPF defect and
the fabricated-domain problem concentrated there); consider running
bimwave's warm-up a stage ahead of the other two, or holding sfw/cogentix
back an extra week regardless of what their early numbers look like,
given their worse track record.

### 4.2 Automatic halt — implemented and tested, not just proposed

`backend/scripts/bounce_rate_monitor.py --enforce-halt`: checks trailing
24h bounce rate per campaign (min 20 sends to avoid noise on a tiny
sample), and if any campaign exceeds 2%, writes
`outreach_kill_switch: {paused: true}` — the same doc §1.1's new gate
checks before every send. **Tested live just now** (without
`--enforce-halt`, since there's nothing to halt — 0 sends in the last
24h): correctly reported "No campaign over threshold." The write path
itself was exercised earlier in this session (the manual pause in §1.1
used the identical update), so the mechanism is proven, not just written.

This script can only ever pause, never resume — resuming after a halt is
`outreach_kill_switch.py resume`, a deliberate action, on purpose.

**Suppression enforcement**: already confirmed working (0 violations
found across the 60 bounced, prior diagnosis §1.7) — no change needed,
carries forward into warm-up automatically since it's checked in the
same function.

**Hard bounces suppress the address, not the lead**: already true in the
current design — `outreach_bounce_suppression` keys on `email`, and the
60 bounced *leads* remain fully eligible for re-enrichment once the
pipeline produces a different, verified address for the same person.
Nothing needed to change here; confirming it as designed, not adding it.

**Soft-bounce capped retry**: still blocked on the same gap as before —
no hard/soft distinction exists in this system's bounce data (prior
diagnosis §1.1). Cannot implement a soft-bounce-specific policy without
that signal existing first.

---

## Deliverables

1. **Reputation assessment + recommendation**: §1.2. Warm up the
   existing domain — medium-high confidence, based on the proven W15→W30
   recovery pattern; Postmaster Tools access would raise that confidence
   further but I don't have it.
2. **Crash-loop root cause + evidence**: §2.1. Mechanism confirmed
   (cgroup OOM kill under the 2GB cap), specific code-level cause not
   isolated — 165+ threads is the concrete lead, py-spy is the proposed
   next diagnostic step, pending your approval to install it.
3. **Hallucination rate, measured**: §2.2. 14.0% domain-level fabrication
   rate (hard floor, free to compute) across all 399 held addresses; the
   stricter "cited in a retrievable source" metric you asked for isn't
   computable with current data — no citations were ever logged.
4. **Verification integration + cost**: §3.1-3.2. Bouncer recommended
   (~$4-14 for 1,800 checks), gate code built and enforced in the query,
   no provider wired up, nothing purchased.
5. **Backfill pass rates**: §3.3. Free-check results for all three
   cohorts; paid step (and therefore real sendable counts) blocked on
   §3.1's decision.
6. **Warm-up plan + automatic halt**: §4. Schedule proposed; halt
   mechanism implemented and live-tested (currently a no-op since nothing
   is sending).

## Where evidence is thin (stated, not guessed)

- Postmaster Tools / SNDS reputation data — no access.
- Exact code location of the thread/memory growth — mechanism confirmed,
  specific culprit not isolated without an in-process profiler.
- True hallucination rate (citation-verified) — no citation data exists
  to check against.
- Exact current verification-provider pricing — two sources disagreed
  within a plausible range; confirm on the vendor page before buying.
- SPF fix — proposed record change is my best read of the existing SPF
  includes, not confirmed against your actual list of authorized senders
  for that domain.

## Sources (provider pricing research)
- [Neverbounce API: Pros, Cons, Pricing (2026)](https://www.usebouncer.com/neverbounce-api/)
- [ZeroBounce Pricing (2026): Credits, Plans & Real Cost](https://www.usebouncer.com/zerobounce-pricing/)
- [Bouncer vs ZeroBounce vs NeverBounce 2026: Email Verification 3-Way](https://puzzleinbox.com/blog/bouncer-vs-zerobounce-vs-neverbounce-2026-three-way/)
