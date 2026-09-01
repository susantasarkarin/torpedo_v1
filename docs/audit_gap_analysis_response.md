# Response to the gap analysis (TOR-32 … TOR-63)

Verification of the second-round findings against the code, and what changed as
a result. Written 2026-09-01, after the first remediation shipped (`9b85514`).

The critique is largely correct. Two of its hits land on the original audit's
method rather than on the code, and both are fair:

- **TOR-50.** The original review read `app/security.py`, described the
  `X-Service-Token` bypass in the process flow, and never questioned it — while
  in the same document flagging committed OAuth tokens, disabled RBAC and
  unauthenticated finance. Reading a bypass and describing it is not auditing it.
- **TOR-57.** "All ~6,886 leads failing at the `no_email` gate" was filed as
  *known state* under module 2, not as a finding. The largest module in the
  codebase currently produces zero mailable leads; that is a finding.

---

## Verified against the code, and fixed

### TOR-50 — service-token bypass · **confirmed, fixed**

Three things were true:

| | |
|---|---|
| Fails closed when unset | ✅ already — `if not token: return False` |
| nginx strips the header | ❌ it did not |
| Constant-time comparison | ❌ plain `==` |

`INTERNAL_SERVICE_TOKEN` is **not set** in the local `.env` (see TOR-63 below),
so the bypass was almost certainly inert rather than live — the gap analysis's
"one-header auth bypass from the internet" is the correct description of the
risk, but it required the variable to be set first. It would have become live
the moment anyone configured it.

Fixed in code:

- `nginx_config.conf` now sets `proxy_set_header X-Service-Token "";` on **all
  five** backend proxy blocks. This is free: `lead_gen_mcp/crm_writer.py`
  defaults `CRM_BASE_URL` to `http://localhost:8000`, so the only legitimate
  caller talks to the backend on loopback and never traverses nginx.
- `secrets.compare_digest` replaces `==`.
- Tokens shorter than 32 characters are refused and logged at ERROR, so a
  placeholder cannot quietly become production auth.

### TOR-41 — Celery redelivery · **confirmed, fixed. The sharpest finding in the set.**

```
task_acks_late          = True     (set)
task_reject_on_worker_lost = True  (set)
task_time_limit         = 3600s    (set)
broker visibility_timeout = 3600s  (Redis DEFAULT — never configured)
```

`broker_transport_options` did not appear in `celery_app.py` at all. With
`acks_late`, the ack only lands when the task finishes, so a task still running
as the visibility timeout expires is **redelivered to a second worker while the
first is still executing** — and the timeout was set to exactly the task time
limit.

This is not theoretical for this codebase: `send_daily_panel_invitations` is a
paced, concurrent batch loop (`_send_batch_concurrently`, `time.sleep`) whose
runtime scales with recipient count, and `last_invited_at` is evaluated at
selection time. A duplicate delivery re-sends to everyone whose write had not
yet committed. The gap analysis is right that this is the most plausible
mechanism for repeating the August over-send *even after* the send facade
exists.

Fixed: `visibility_timeout` set to 7200s, twice the hard task limit. The global
send budget in `backend/messaging` is the backstop if this is ever wrong again —
that mitigation shipped in `fc12733` and does now cover this case, which is the
one piece of good news in this finding.

### TOR-44 — money as float · **confirmed, not fixed**

Zero uses of `Decimal` in `routers/finance.py`. Monetary values are Python
floats throughout, including at the points where error accumulates:

```
finance.py:2934  subtotal  = sum(float(item.get("amount", 0) or 0) for item in items)
finance.py:2935  tax_total = sum(float(item.get("tax_amount", 0) or 0) for item in items)
```

This is a real correctness defect for a ledger. It is **not** fixed here, and
deliberately: a correct fix stores `Decimal128` in Mongo and converts at every
boundary, which is a data migration across invoices, bills, estimates, payments
and purchase orders plus their CSV importers. Half-fixing money — converting
the arithmetic but not the storage — produces a system that is wrong in a new
and less obvious way. It needs its own change with reconciliation against the
existing figures.

The gap analysis's sharper question stands and is unanswered: **is Torpedo the
system of record, or a second ledger shadowing an accounting package?** If the
latter, the first task is a reconciliation report, not a refactor.

### TOR-51 — dependency health · **confirmed, and the frontend is not clean**

Python — `requirements-ci.txt` was clean, but the **production** set
(`requirements-outreach.txt`) was not:

```
jinja2 3.1.4   PYSEC-2026-1471, 1472, 1475   -> fixed in 3.1.6
ecdsa  0.19.2  PYSEC-2026-1325               -> no fix available
```

The jinja2 pin was **introduced by this remediation** — `3d1282d` added
`jinja2==3.1.4` when closing TOR-05, and pinned a version with three
advisories. Bumped to `>=3.1.6` in both requirements files. Auditing only the
CI subset would have missed it entirely, which is why the CI step below runs
against both.

`ecdsa` has no fix version: its maintainers have declined to address
side-channel attacks in pure-Python. It arrives transitively; worth confirming
whether anything actually uses it for signing.

Frontend (`npm audit --omit=dev`, i.e. shipped code only):

```
total 17   —   high 14   moderate 2   low 1

high      brace-expansion, flatted, js-yaml, lodash, minimatch,
          nanoid, next, picomatch
moderate  ajv, dompurify
low       @babel/core
```

`dompurify` matters more than its "moderate" rating suggests here: it is an
XSS sanitiser, and TOR-25 is precisely about a session token in
`localStorage` being one XSS away from theft, with the CSP still
report-only. A vulnerable sanitiser compounds both.

The gap analysis is right that nobody was running these. `npm audit fix`
resolves most without a major bump; `next` appearing at all in a Vite project
is worth a look on its own.

Both audits are now CI steps — reporting, not gating, so a new advisory in a
transitive dependency surfaces without blocking an unrelated deploy.

### TOR-43 — timezone / day boundary · **checked, no change needed**

`messaging/budget.py` uses a **rolling** 24-hour window
(`now - timedelta(days=1)`), not a calendar day. That is strictly more
conservative than a calendar boundary — it cannot be gamed by a burst either
side of midnight — so the cap does cap.

The residual gap is real but smaller than stated: the rolling window does not
*align* with SES's daily quota reset, so the two measure different things and
our cap will always bind first. That is the safe direction. Documented rather
than changed.

---

## Verified partially — the environment, in lieu of production access

### TOR-63 — production was never observed · **the most important finding in the set**

Correct, and it applies to the remediation as much as to the audit. What the
local `.env` actually sets (values redacted) answers several questions that
were previously inferences:

| Variable | Present? | Consequence |
|---|---|---|
| `FINANCE_AUTH_ENABLED` | **not set** | The default governs. The first remediation flipped it to `true`, so finance is now gated — *provided prod's `.env` also omits it*. |
| `RBAC_ENABLED` | **not set** | Enforcement off, as the audit said. |
| `INTERNAL_SERVICE_TOKEN` | **not set** | TOR-50 was inert, not live. |
| `WEB_LEAD_TOKEN` | **not set** | `/api/crm/web-to-lead` returns 503 until set. |
| `SENDING_ENABLED`, `SEND_BUDGET_*` | **not set** | New defaults govern: 1500/day, 200/hour per identity. |
| `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEYS` | all present | Confirms the four-provider sprawl of TOR-22 empirically. |

**One new finding this turned up, not in either register:**

> **TOR-64 · `AWS_SESSION_TOKEN` is set — temporary STS credentials on the
> sending path. High.** An `AWS_SESSION_TOKEN` alongside the access key means
> these are short-lived STS credentials, not long-lived IAM ones. They expire —
> typically in 1–12 hours. If production carries the same shape, SES sending and
> Bedrock calls fail at expiry with an auth error that looks like a
> misconfiguration rather than an expiry. Either move to an instance role (the
> right answer on a VM) or to long-lived credentials with a rotation process.

This is exactly the class of thing the gap analysis predicted static review
would miss, and it was found by reading one config file. **The hour on the box
is still owed** — this is not a substitute for it. The local `.env` is evidence
about prod, not prod.

---

## Accepted, not actioned, with reasons

These are correct and I am not attempting them, because each needs either
infrastructure access I do not have or a decision that is not mine:

**TOR-32 / TOR-33 / TOR-34 — backups, PITR, rebuildability.** The gap analysis
is right that these outrank most of the original register, and right that
TOR-33 (single-node replica set) is the best value-per-hour item on the
combined list — it buys point-in-time recovery *and* the transactions TOR-40
needs. All three require VM access and an operational decision about acceptable
data loss. They cannot be closed from the repository.

**TOR-35 — no alerting.** Correct, and correctly identified as the multiplier:
TOR-05, TOR-06 and TOR-13 are dangerous *because* nothing watches. Worth adding
that the first remediation made two of these louder without making them
observed — mount failures now crash the boot, and mirror failures are counted
at `/api/crm/spine-health` — but a counter nobody reads is not monitoring.

**TOR-40 — non-atomic spine flows.** Correct and not covered by TOR-13. Blocked
on TOR-33: without a replica set there are no multi-document transactions, so
the only available fix today is idempotency with a correlation id.

**TOR-48 / TOR-49 — `qre-backend` and the SFW panel.** Correct that the
original review declared these out of scope by silence. `qre-backend` is
public-facing, handles real respondents' data, and was never opened.

**TOR-54 / TOR-55 / TOR-56 — erasure, lawful basis, employee mail.** Correct,
and TOR-54 is the one with teeth: the same un-deletability the original audit
identified in git exists in production across five lead stores, the spine, the
mail pool, the panel and the AI logs, with no subject index. These are policy
decisions before they are engineering ones.

**TOR-57 — the lead engine produces nothing.** Correct, and correctly promoted
from a note to a finding. Every downstream outreach investment is blocked on a
gate that nothing currently passes.

**TOR-58 — no performance baseline.** Fair, and it partially indicts work
already shipped: TOR-08's async refactor was executed on a diagnosis
("blocking I/O is the most likely cause of stalls") that no measurement
supports. The change is defensible on its own terms — sync handlers in a
threadpool is simply correct — but the gap analysis is right that a day of
slow-query logs should have come first, and might have shown a missing index
was the real cause.

---

## Where I would put these

Merging both registers, the "today" window becomes:

1. **TOR-63** — the hour on the box. It tells you whether TOR-03 was ever live
   exposure, whether indexes exist, and whether prod's `.env` matches the
   assumptions every other finding rests on.
2. **TOR-01** — revoke the Google tokens. Still outstanding.
3. **TOR-32/33** — establish that a restore works, then convert to a
   single-node replica set.

Then TOR-35 (alerting), because it is what makes everything else survivable.
