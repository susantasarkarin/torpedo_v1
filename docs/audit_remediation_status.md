# Torpedo Teardown — remediation status

Against the architecture review of `main @ 2f84ae1` (1 Sep 2026).
Branch: `fix/audit-remediation`.

## Closed

| ID | Finding | How |
|---|---|---|
| TOR-02 | Logout did not revoke | Session store is authoritative; signature is only the first filter. Degrades to signature-only **with a loud warning** if Redis is down, so an outage cannot mass-logout. Per-user token epoch invalidates every token on password change. |
| TOR-03 | Finance unauthenticated | `FINANCE_AUTH_ENABLED` defaults true. The blocker in its own comment — five pages sending no header — was already resolved: all twelve finance pages use `authFetch`, and the three remaining raw fetches set the header themselves. |
| TOR-04 | Two RBAC defaults | One reader (`rbac/flags.py`). Added `scripts/seed_rbac_roles.py`, the missing prerequisite — enforcement stays **off** until roles are seeded, because `decorators.py` locks out anyone without one. |
| TOR-05 | Mounts swallowed failure | 51 mounts raise; the two that also do DB setup stay tolerant and are covered by a startup route-manifest check. **Found four routers dead in production** — see below. |
| TOR-06 | 13 send paths, 1 counted | `backend/messaging/` — one suppression list (fails closed), one per-identity budget across all channels, one log, a kill switch. Suppression reads are read-through so migration can only suppress *more*, never less. |
| TOR-08 | Async handlers doing sync I/O | 132 handlers that never await are now plain `def`, AST-verified, skipping any called with `await` elsewhere. |
| TOR-09 | Indexes never applied | Startup audits coverage on a background thread and logs what's missing. Creation stays opt-in — the original comment was right that 130+ foreground builds would lock collections on every boot. |
| TOR-10 | Public write, no rate limit | App-level limiter + nginx `limit_req`. `WEB_LEAD_TOKEN` is now required; it defaulted to empty, which skipped the check entirely. |
| TOR-11 | 338 import fallbacks | Collapsed to one convention. Found `clay_routes` importing five siblings as top-level modules, and a test patching a module identity the code never uses. `scripts/check_imports.py` in CI keeps it closed. |
| TOR-12 | 101 MongoClients | 56 constructions across 52 modules share the pool. Measured: **101 import-time → 5 live clients**. |
| TOR-13 | Silent spine drift | Mirror failures counted and persisted with source id; `GET /api/crm/spine-health`. |
| TOR-14 | CI tested a quarter | Full suite (701 tests) + import check + AI-gateway ratchet + a job that fails on tracked credentials or PII exports. |
| TOR-15 | nginx snapshot, no headers | Repo copy is the deployed artifact. HSTS, nosniff, frame-options, referrer-policy — repeated inside the static/SPA locations, because nginx `add_header` does **not** inherit into a location with its own. |
| TOR-16 | Could not clear a field | `UNSET` sentinel; `None` now means clear. This also fixed the service's own broken `loss_reason` clearing. |
| TOR-17 | Wrong close timestamp | `closed_at` stamped and measured against. |
| TOR-18 | Delete orphaned references | Generic DELETE soft-deletes, matching what the reconcile already assumed. Hard delete moved to `/purge`, which clears references. |
| TOR-19 | Duplicate session systems | `main.py`'s copies deleted; insecure `"supersecretkey"` default removed. |
| TOR-20 | Unbounded reports | `$group` aggregation, projected dedupe scan, genuinely streamed export. |
| TOR-26 | Unmounted routers | Moved to `deprecated/routers/` with a note on how to bring one back. |
| TOR-28 | Bare excepts | 100 converted; none remain. Not cosmetic — bare `except:` swallows `KeyboardInterrupt`/`SystemExit`. |
| TOR-29 | Encoding corruption | 15 files repaired, 32 BOMs stripped, UTF-8 pinned in `.editorconfig`. |
| TOR-30 | README wrong | Rewritten; dead `frontend/` deleted; `codebase_inventory.md` linked as the map. |
| TOR-31 | Dead CORS guard | Shadowing reassignment removed. |

### Four routers that were dead in production

Turning mount warnings into failures surfaced these immediately. Each had
mounted "successfully" in the log for months:

- `leads/clay_routes.py` — used `Path` in 20+ signatures, never imported it (19 routes)
- `routers/email_campaigns.py` — imports `jinja2`, undeclared in any requirements file
- `routers/campaigns.py` — used `Body` without importing it
- `routers/campaign_automation.py` — the only bare `from ..campaigns...` in the tree. Resolves under pytest (where `backend/` is a package), raises under the real runtime. **Dead in production while a package-style import test passed.**

## Partially closed

**TOR-01 / TOR-07 — secrets and PII in git.** Files untracked, `.gitignore`
widened, CI fails on their return. **Two steps remain and need a human:**

1. **Revoke the Google tokens** at myaccount.google.com/permissions and rotate
   the OAuth client secret. Untracking does nothing while they remain in
   history — they are still live.
2. **Purge history** (`git filter-repo`) for both the tokens and the 52 MB of
   lead PII. This rewrites all 1,086 commits and force-pushes; every clone
   breaks. Not done without an explicit decision.

**TOR-21 — five lead stores.** `GET /api/crm/lead-sources` now reports every
store's count and purpose side by side, so the disagreement is explicable and
`crm_db.leads` is named canonical. Making the others genuinely feed it is a
data migration, not a code change.

**TOR-22 — AI gateway bypass.** The finding's "44 files" counted references;
only **four live modules** actually construct a client. Added
`AIGateway.complete()` so "my case isn't covered" stops being a reason to
bypass, plus `scripts/check_ai_gateway.py` as a CI ratchet against a baseline
of those four. Migrating them means rewriting request *and* response parsing
(they speak the Anthropic Messages API; the gateway speaks the
OpenAI-compatible Bedrock endpoint) — not safe to do without exercising it
against the live API.

**TOR-25 — token in localStorage.** The finding's own guidance was "add a CSP
and fix TOR-02 first, at a fraction of the cost". Both are done. The
`httpOnly` cookie migration remains, and the CSP is report-only until the SPA's
inline usage is removed — enforcing it today would white-screen the app.

## Open, with what each actually needs

**TOR-23 — two schedulers.** Moving the APScheduler jobs into Celery beat is
not a lift-and-shift. The CINT jobs close over an in-process `cint_integration`
object that would have to be reconstructed in the worker, and getting it wrong
means either double-running a job or silently running none. Needs its own
change with a period of running both and comparing.

**TOR-24 — 386 raw `fetch` calls.** Each carries bespoke error handling, so
this is per-page work, not a codemod. The finding's own advice — add the ESLint
ban "once the count is low enough to hold the line" — means the rule comes
last, not first.

**TOR-27 — delete the superseded outreach generations.** Explicitly blocked.
The finding's condition is "once the send facade exists, the older three have
no callers left". They still have callers: only `outreach_mailer` is wired to
the facade so far. Deleting them now would break sending.

## Deploy notes

Behaviour changes an operator should know about before this ships:

- **Finance now requires a session.** Any unauthenticated integration against
  `/finance/*` will start getting 401s. `FINANCE_AUTH_ENABLED=false` is the
  escape hatch, and leaving it there means the ledger is public again.
- **A router that fails to import now stops the boot.** That is the point — but
  it means a deploy fails loudly rather than shipping a half-loaded app. The
  four known-dead routers are fixed; `jinja2` is now in
  `requirements-outreach.txt` and the deploy's `pip install` must run.
- **`WEB_LEAD_TOKEN` must be set** or `/api/crm/web-to-lead` returns 503.
- **Sending is capped globally.** Defaults are 1500/day and 200/hour per
  identity, under Gmail's 2,000 hard limit. Set `SEND_BUDGET_*` if that is
  wrong for your volume, and know that `SENDING_ENABLED=false` stops everything
  immediately.
- **nginx must be redeployed separately** — `sudo cp nginx_config.conf
  /etc/nginx/sites-available/campaign-platform && sudo nginx -t && sudo
  systemctl reload nginx`. The rate-limit zones and security headers do nothing
  until it is.
- **Run the suppression migration** (`--dry-run` first). Until then the
  read-through covers correctness but the three lists stay split.
