# Incident Record — Guessed-Address Cold Outreach

Date compiled: 2026-08-28. Factual record only — no remediation plan or
recommendations included here (see the engineering session notes for those).
Companion documents in this directory, same investigation, different angle:
`BOUNCE_DIAGNOSIS_2026-08-28.md` and `RECOVERY_PLAN_2026-08-28.md` (a
separate, concurrent session's findings — cross-referenced below where
relevant, not duplicated).

---

## 1. What was sent

- **4,734** total leads carry `email_source: "bounce_recovery_alt"` — an
  address rendered from one of 6 fixed name/domain templates
  (`firstname.lastname@domain`, `firstnamelastname@domain`, etc.), never
  observed or verified anywhere, only guessed.
- Of those, **947 distinct people** were actually enrolled and sent to via
  the live cold-outreach pipeline, carrying an `email_status` of
  Delivered/Valid/Catch-All/Unknown (i.e. not already flagged as bounced).
- Of those 947, **531 distinct people** received at least one message that
  did not register as bounced.
- **Date range**: sends to this population ran from **2026-04-10** to
  **2026-08-21**. (The outreach pipeline as a whole kept sending after that,
  through **2026-08-25**, when all three campaigns were paused — see §4.)
- **Messages per recipient** (of the 531): 527 received exactly 4 (a
  complete 4-step drip sequence), 2 received 7, 1 received 11, 1 received 3.
- **By campaign/brand**:

  | Campaign | Sending domain | Sends to the 531 |
  |---|---|---:|
  | Survey Fieldwork Cold Outreach | surveyfieldwork.com | 12 |
  | Cogentix Research Cold Outreach | cogentixresearch.com | 37 |
  | BIMwave Cold Outreach | bimwavesolutions.com | 2,087 (98%) |

---

## 2. Three independent defects, and what each means for whether mail reached the intended recipient

### 2.1 Unreliable address provenance

The pipeline's outreach-qualification gate checked *whether an email was
labeled "Predicted"* but not *what actually produced it* — a guess and a
verified address could carry the same downstream label. 2,888 leads whose
`email_source` marked them as machinery-guessed carried a *different*
status label (Delivered/Valid/Catch-All/Unknown/bounced) and passed
unchecked. Separately, a second, structurally identical gate inside the
send engine itself (`cold_outreach_router.py`) had the same blind spot.

**What it means**: a guessed local-part (`firstname.lastname`,
`firstnamelastname`, etc.) at a real, working domain may or may not be the
actual mailbox of the named person — nothing in this system verified it
either way before sending.

### 2.2 Non-existent / non-routable domains

Live DNS check (2026-08-28) of the 531 recipients' domains: **54/531
(10.2%)** currently return NXDOMAIN or have no mail-routing (MX or A)
record at all. A broader sample (2,000 of 9,703 distinct domains across all
enriched leads) found the same pattern at roughly **4.9%** of domains.
Independently, the companion diagnosis doc found domain non-existence
explained **40%** of a separate, smaller (n=60) bounce sample from
newly-created leads — a related but not identical population to the 531.

**What it means**: mail to these specific 54+ addresses could not have
reached anyone — the domain itself cannot receive mail, full stop. This is
a different, independent failure mode from provenance (§2.1): a "sourced"
non-guessed address can still sit on a domain that was itself fabricated
earlier in the pipeline (at company-enrichment time), and a guessed address
can sit on a perfectly real domain.

### 2.3 Email authentication gaps on the sending domains

Live DNS check (2026-08-28), independently confirmed against the companion
diagnosis doc:

| Domain | SPF | DKIM | DMARC |
|---|---|---|---|
| surveyfieldwork.com | **Two conflicting SPF TXT records** (RFC 7208 violation — permanent SPF error) | None | `p=none` (monitor only) |
| cogentixresearch.com | Single, valid SPF record | Valid | `p=none`, with reporting address |
| **bimwavesolutions.com** | **None** | **None** | **None** |

**What it means**: surveyfieldwork.com's broken SPF can cause outright
rejection by receiving mail servers, indistinguishable in this system's
data from "wrong guessed mailbox." bimwavesolutions.com has no
authentication policy configured at all — mail from it is not
cryptographically vouched for in any way, which can affect whether a
receiving server delivers it to the inbox, the spam folder, or rejects it,
depending entirely on that receiving server's own heuristics. Which of
those happened for any given message cannot be determined from data this
system captures (§3).

---

## 3. Known / Inferred / Unknowable

Kept visually separate on purpose — the unknowable column is as load-bearing
as the other two for anyone deciding what to do next.

### KNOWN — directly measured, not interpreted

- Exact counts and date range in §1, from `torpedo.outreach_sends_v2` and
  `email_automation.leads_enriched`.
- Zero addresses on the real bounce-suppression list
  (`torpedo.outreach_bounce_suppression`, 11,508 entries) were ever mailed
  *after* being added to it.
- No SES complaint/delivery/reject event data exists anywhere in this
  system. Verified, not assumed: `outreach_bounce_suppression.reason` only
  ever contains `"gmail_bounce"`, and its `source` only `"bounce_scanner"`
  — bounce detection works by scanning a Gmail inbox for mailer-daemon auto
  -replies, because sending goes through the Gmail API, not SES. SES event
  publishing was never configured for this pipeline; there is nothing to
  read.
- Open/click tracking is a real, self-hosted 1×1 pixel
  (`GET /track/open/{send_id}`), live on 100% of the 60,309 recorded sends
  (all three domains). It records only that an open happened and when — no
  user-agent, no IP address, on any send.
- Per-domain open/reply counts, all sends, all-time: surveyfieldwork.com
  25,405 sends / 7,432 opens (29.3%) / 61 replies; cogentixresearch.com
  16,833 / 3,803 (22.6%) / 23 replies; bimwavesolutions.com 18,071 / 5,604
  (31.0%) / **0 replies**.
- The three sending domains' SPF/DKIM/DMARC records, live DNS, 2026-08-28
  (§2.3).
- The domain-existence status of the 531's addresses and a 2,000-domain
  sample of the wider population (§2.2).
- All three real outreach campaigns (SFW, Cogentix, BIMwave) were paused at
  **2026-08-25 06:45:38**, by a prior automated session (recorded as
  `paused_by: "claude-code-session"`), citing a 23.6% bounce rate as the
  reason. A later, independent recalculation (companion diagnosis doc)
  found the true rate for that specific cohort was 41.9%, and a trailing
  30-day, all-campaigns bounce-rate check found 26.9% (SFW), 26.3%
  (Cogentix), 2.4% (BIMwave).
- `torpedo-backend.service` has been forcibly killed (OOM, `status=9/KILL`)
  at least 7 times in the trailing 36 hours, capped at `MemoryMax≈2GB` on a
  3.8GB VM; the AI-classification/enrichment backlog has recorded zero
  attempts in the same window.

### INFERRED — a reading of the data that is plausible but not proven

- The domain-non-existence problem (§2.2) most likely originates upstream,
  at company-domain enrichment (an LLM producing a free-form domain string
  with no existence check before it's trusted) — traced by the companion
  diagnosis doc for its own 60-address sample; consistent with, but not
  independently re-derived against, the 531/9,703-domain populations here.
- A theory that bimwavesolutions.com's mail was landing in recipients'
  spam folders (rather than inboxes) — **tested against the engagement
  data in this document and not corroborated**. Spam placement would
  predict suppressed opens (most spam filters strip remote images); the
  data shows the opposite — bimwavesolutions.com has the *highest* open
  rate of the three domains. This inference should be treated as
  unconfirmed, likely incorrect as originally framed.
- A different candidate explanation for bimwavesolutions.com's pattern
  (elevated opens, zero replies across 18,071 sends) is automated
  pre-fetching by corporate email security gateways, which is known to
  trigger tracking pixels without human involvement. Plausible, and
  consistent with the shape of the data, but **cannot be confirmed**
  because the tracking pixel captures no user-agent or IP data to
  distinguish a bot fetch from a human open (verified directly in the
  code, not assumed).

### UNKNOWABLE — cannot be determined from any data this system has captured

- Whether any specific non-bounced, guessed-address send actually reached
  the *named* intended person, a different real person at that mailbox
  (departed employee, catch-all alias, wrong individual entirely), or
  simply sat unread. Zero of the 531 show a reply or any other positive
  human-attributable signal, but "no evidence of human engagement" is not
  the same as "did not reach a human" — the tracking data cannot
  distinguish those.
- Whether any given open (on any of the three domains) represents a human
  or an automated scanner — no distinguishing metadata was ever captured.
- Hard-bounce vs. soft-bounce, and any SMTP-level diagnostic/rejection
  code, for any bounce this system has ever recorded. Not captured
  anywhere, for any send, historically. This means the exact split between
  "wrong guessed local-part" and "receiving-side block due to
  authentication/reputation" cannot be determined for any address that
  bounced on a domain that does otherwise resolve.

---

## 4. Current containment state (as of 2026-08-28, this session)

**Paused, not by this session**: all three real outreach campaigns
(Survey Fieldwork, Cogentix Research, BIMwave) have `is_active: false`,
set 2026-08-25 by a prior automated session. No new sends have gone out
under any of them since.

**Live and deployed** (this session, `main` branch, confirmed running on
production):
- The send engine (`cold_outreach_router.py`) now blocks both new
  enrollment and any pre-send attempt for a lead whose `email_source`
  marks it as machinery-guessed/derived and whose confidence is missing or
  below 0.5 — covers the same population as §2.1, at both the point where
  a lead is added to a campaign and the point right before a message goes
  out, for leads enrolled before the fix existed.
- The separate outreach-qualification gate used by other parts of the
  pipeline (`outreach_qualification.py`) has the same provenance-aware,
  fail-closed-on-missing-confidence check, and now correctly reads the
  real bounce-suppression collection (previously pointed at an empty,
  unused one).

**Written, verified via dry-run, not executed**: a script to null out and
re-derive the 4,657 still-unconfident `bounce_recovery_alt` addresses
through the same verified-lookup pipeline used elsewhere (no re-guessing).

**Not yet addressed by anything deployed**:
- Domain non-existence (§2.2) has no live gate anywhere in this pipeline
  today. A fix for it — at enrichment time and at send time — exists as
  uncommitted code from the concurrent session referenced above; not yet
  shipped.
- The authentication gaps (§2.3) on surveyfieldwork.com and
  bimwavesolutions.com are unchanged; no DNS records have been modified.
- The `is_previously_contacted()` half of the suppression gate fix is
  written and locally committed but intentionally not deployed, pending a
  decision on the right predicate (541 of the leads it would affect are
  currently mid-sequence elsewhere; blocking them risks a different kind
  of harm than an unverified address does).
- `torpedo-backend.service`'s memory-cap/OOM cycle (above) is unchanged;
  the classification/enrichment backlog remains stalled independent of any
  fix in this document.

**On hold, not started**: AI-provider key rotation, live end-to-end
pipeline verification, bulk retry of previously-failed leads, and the
null-out script's live run.
