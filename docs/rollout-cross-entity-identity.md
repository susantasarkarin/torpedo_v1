# Rollout — cross-entity identity remediation

Branch `fix/cross-entity-identity`. Ordered by risk. Nothing here has run
against production.

---

## 0. Expected volume drop — read this before resuming sends

**Three changes compose in one direction. Outbound will fall, and every part
of the fall is deliberate.**

A predicted drop that arrives as predicted is a working fix. The same drop
unannounced reads as "the remediation broke the pipeline", and the first
instinct is to loosen thresholds to recover volume — which unwinds the work.
So it is itemized here as a number, not a caveat.

### Contributors

| # | Change | Effect on the eligible pool |
|---|---|---|
| 1 | Dual-fit enrollment removed (basket D enrolls nobody) | **−55%** — 11,291 of 20,639 classified leads |
| 2 | Cross-bucket confidence ties resolve as ambiguous, not by ICP score | further reduction, size unknown |
| 3 | Review branch defaulted off → ambiguous leads do not send | all of (2) blocked, not queued |
| 4 | 90-day cross-entity cooldown | one-off reduction as history is honored for the first time |

Eligible pool falls from **20,639 → ~9,348** classified leads from (1) alone,
before (2) and (4).

### Which regime you are in matters

Sends are capped at `OUTREACH_SEND_DAILY_CAP` (200/day, currently shared
across all three entities).

- **Pool ≫ cap:** daily volume is unchanged; the drop shows up as the pool
  exhausting sooner. 9,348 at 200/day is ~47 days of runway.
- **Pool ≈ or < daily draw:** daily volume falls directly.

At present numbers the first regime applies, so **expect roughly flat
sends/day and a much shorter runway** — not an immediate cliff. That is the
opposite of most people's intuition and is the specific misread to pre-empt.

Once Phase 3 splits caps per entity, each entity draws from its own bucket
and the regime can differ per brand.

### ⛔ The verification gate takes outbound to ZERO, not "reduced"

**Measured, not projected.** Applying `check_email_verification` to the local
6,860-row `leads_enriched` copy:

```
PASS the verification gate              0   (0.00%)
  blocked: constructed_unverified          3,522
  blocked: email_verification_unknown      3,338

runway at 200/day cap:  0.0 days
```

**There is not one verified email address in the dataset.** Every address is
either constructed from a Hunter domain pattern (`Predicted`) or carries no
provenance label at all. The pipeline has never sent to a confirmed mailbox —
which is the direct explanation for why `bounce_recovery.py` needed to exist,
and for the 45% bounce episode.

So `OUTREACH_REQUIRE_VERIFIED_EMAIL=1` is not a filter. **It is a full stop.**

That is the correct posture right now — all three entities are paused, and
resuming sends to unverified guesses is what damaged the domains in the first
place. But it changes the dependency order:

> **Resuming outbound is blocked on building the verification step, not on
> finishing the identity work.** Verification is a prerequisite for sending,
> not an optimization. Until it exists, the honest state is "we cannot send",
> not "we send less".

This supersedes the runway arithmetic below, which assumed the pre-Phase-4
pool. With the gate on, runway is **0 days** regardless of cap.

**Do not resolve this by setting the flag to 0.** That reopens the exact hole
the phase exists to close, and the flag defaulting strict is what makes the
problem visible instead of silent.

### Phase 5 requirement: ship pool depth as RUNWAY IN DAYS

Because the drop is invisible in send rate, the monitoring has to watch the
pool — and the units decide whether anyone acts.

> `eligible_pool = 9,348` reads as healthy to everyone.
> `runway = 47 days at current cap` gets attention at 30 and forces a
> decision at 10.

Same data, one behaves like a warning. Emit
`runway_days = eligible_pool / effective_daily_cap` per entity, alert on
thresholds in days, and never surface the raw count alone.

This is the specific failure being designed against: a cap-bound system shows
**nothing** while the pool drains, then hits a cliff whose cause is six weeks
in the past and which nobody will connect to this remediation.

### Watch `blocked_review_capacity` once the branch is live

Its first firing is the classifier-vs-market signal arriving. If the Basket D
conversation (§4) has not happened by then, that is the trigger.

### What needs the replica

(2) and (4) cannot be sized locally — they need the multi-interest
distribution and real contact history. **Re-run the projection against the
replica before resuming.** The mechanism above is validated; the magnitudes
of (2) and (4) are not.

---

## 1. Today — independent, additive, both urgent

Neither waits for the other.

1. **Pause all three entities + drain the queue.** Pausing the campaign does
   not stop entries already enqueued by `scheduler.enqueue_send()`.
   > Frame it accurately to whoever has VM access: if the 9,747 multi-brand
   > enrollments were never retired — commit `6c97319` explicitly deferred
   > that cleanup and no evidence of follow-up exists — this is **stopping
   > ongoing sends to a population identified as harmed on 2026-08-06**, not
   > preventing future damage.

2. **Suppression: capture, merge, verify.**
   ```
   python -m leads.suppression_drift          # BEFORE — clean before-picture
   <run the union merge>
   python -m leads.suppression_drift          # AFTER — must exit 0
   ```
   Verification must exercise the **read** side: confirm a known-unsubscribed
   address is now rejected at `sending_engine.py:201`. "The merge ran" is not
   the same claim.

3. **Exposure count for legal.** Unsubscribes in `suppression_list`
   cross-referenced against `outreach_sends_v2` for sends *after* the
   unsubscribe timestamp. This determines whether this is a bug fix or a
   disclosure event, and it is the critical path.
   > Provenance is resolved: `6c97319` is `Co-Authored-By: Claude Opus 5`, a
   > human-driven session. The number was in the third line of the commit
   > body and the remaining exposure was named as deferred. Accurate framing:
   > **it was written down, acknowledged as incomplete, and the follow-up did
   > not happen** — not "review failed to surface it".
   > The window is **open, not closed at 2026-08-06**.

---

## 2. Next — needs the replica, no production writes

4. `python -m backend.migrations.003_person_identity` (dry run by default).
   Read **DUPLICATES collapsed**, not any ratio — see the module docstring.
5. Review field-level conflicts before applying. High `company`/`title`
   conflict rates would be a SERP-parsing signal worth having first.
6. `--apply` against the restored copy. Index creation asserts and refuses to
   complete if uniqueness is not achieved.

---

## 3. Then — code, already written and tested

7. Arbitration auto-pick. Ships now; review branch stays off.
8. Repair `leads_raw` UNIQUE(email) — absent live, its creation failure
   swallowed by a `logger.warning`. Not load-bearing for the invariant any
   more, but duplicate rows inflate per-ICP yield counts feeding the coverage
   matrix's exhaustion rule, so a dry cell looks productive.
9. Assert-on-startup for the uniqueness-guarding subset of the 48 swallowed
   `create_index` calls.

---

## 4. Gated on a human, not on code

| Gate | Blocks |
|---|---|
| **Named review-queue owner** | enabling `ARBITRATION_REVIEW_BRANCH_ENABLED` |
| **Basket D answer from the business owners** | whether Phase 2 is finishable |

> *We found that a majority of qualified leads look like a fit for both SFW
> and Cogentix. Is that two brands chasing one market, or a labelling problem
> on our side? If it's the former, which brand should own that overlap?*

If it is a genuine market overlap, no confidence threshold separates them, the
queue fills and stays full, and the tie-break becomes a commercial rule rather
than a score. Queue depth over time distinguishes the two: a fixable
classifier converges as it improves, a market overlap does not.

---

## 5. Domain separation — do not do this quickly

All three entities currently share one sender identity
(`OUTREACH_SENDER_EMAIL`, one postal address, one unsubscribe URL, one cap
pair). **Reputation damage from the 2,402 triple-mailed addresses has pooled
across all three brands.**

Separating domains means three cold domains inheriting damaged reputation with
no warm-up history. A cold domain sending at current volume lands in spam.
Warm up over weeks — low volume to engaged recipients first, ramping — and do
not switch sending domains without one. The bounce-rate circuit breaker
(Phase 4, 2% default) should be live before any ramp.

---

## Do not run

`backend/scripts/dedupe_enriched.py` — **deleted** in `1aef0bb`. Grouped by
raw `$email` with no null filter, so all email-less leads collapsed into one
`_id: null` bucket and `delete_many` removed all but one: **3,337 documents
destroyed** against a 6,860-document copy. Noted here because someone
archaeologizing this incident may find it in history and mistake it for the
fix.
