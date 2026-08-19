# SFW / Cogentix classifier separation

**Filed from:** cross-entity identity remediation (`fix/cross-entity-identity`)
**Status:** open — needs a business answer before engineering starts
**Blocks:** enabling `ARBITRATION_REVIEW_BRANCH_ENABLED`

---

## The observation

`compute_icp_basket` assigns **basket D ("Dual Fit: SFW + Cogentix") to 11,291
of 20,639 classified leads — 55%.**

A classifier placing the majority of leads in "fits two of our three
businesses" is not describing a market. It is failing to separate SFW from
Cogentix.

This surfaced while removing dual-fit enrollment, which was mailing one human
from two brands 33 days apart against a 90-day cross-entity cooldown.

---

## The question that has to be answered first

This is **not an engineering ticket yet.** It becomes one only under one of two
answers, and they lead to opposite work.

> **To the business owners:** we found that a majority of qualified leads look
> like a fit for both SFW and Cogentix. Is that two brands chasing one market,
> or a labelling problem on our side? If it's the former, which brand should
> own that overlap?

| Answer | What the work becomes |
|---|---|
| **Labelling problem** | Genuine classifier work. Sharpen the SFW/Cogentix boundary — better features, better prompt, better training examples. Convergence is measurable (below). |
| **Real market overlap** | No classifier work converges, because there is nothing to separate. The arbitration tie-break becomes a **commercial rule** — "brand X owns this segment" — decided by a person and encoded as configuration, not inferred from a confidence score. |

Encoding a commercial decision as a confidence threshold is how you get a
system nobody can explain and nobody can override.

---

## The metric that distinguishes them

**Review-queue depth over time**, once the review branch is enabled.

- A **fixable classifier converges**: as it improves, fewer leads land inside
  `ARBITRATION_AMBIGUITY_MARGIN` and the queue drains.
- A **genuine market overlap does not**: the queue refills at the same rate
  regardless of classifier work, because the ambiguity is real.

Two supporting signals already being collected, so no backfill is needed when
someone asks:

1. **Runner-up distribution.** `leads.arbitration` records the runner-up on
   every `lost_arbitration`. If SFW wins and Cogentix is runner-up across most
   of the ~11k, that is a market overlap wearing a confidence score.
2. **`dual_fit` flag** retained on `lead_interests` though it no longer drives
   enrollment. If the true SFW+Cogentix pair count comes back large against
   the prod replica, that is the evidence for reopening this.

---

## Interim posture — already in place

Nothing is waiting on this ticket to stay safe:

- Dual-fit enrollment **removed**. Basket D enrolls nobody; arbitration owns
  the decision.
- Ambiguous leads (top two within 0.15 confidence) **do not send**. With the
  review branch off they are recorded as `review_branch_disabled`.
- The review-queue cap is **500 and fails closed**, reported as
  `blocked_review_capacity` — deliberately a distinct reason, because
  "capacity" would point at raising a cap that is not the problem.

The cap is an **instrument, not backpressure**. Filling it *is* the
measurement. If the classifier cannot tell which entity should contact
someone, not contacting them is the correct output — you do not know who
should email them.

**Watch for the first `blocked_review_capacity` firing.** That is this
question arriving on its own, and it is the trigger to have the conversation
if it has not happened by then.

---

## Out of scope here

Scoring weights, ICP definitions, the coverage matrix, and synonym learning
were explicitly excluded from the remediation and remain excluded. This ticket
covers the SFW/Cogentix boundary only.
