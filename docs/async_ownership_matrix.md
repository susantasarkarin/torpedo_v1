# Async Ownership Matrix

Captured: 2026-05-17

Purpose: Define single-owner async execution boundaries to prevent duplicate polling, duplicate websocket transports, and stale-state overwrites during frontend stabilization.

## Ownership Rules

1. Transport ownership must be singular per domain.
2. Shared state ownership belongs to context for cross-page domains; page/component state for local domains.
3. Retry/backoff/cancellation policy belongs to centralized orchestration utilities.
4. Payload semantics are frozen to the API contract snapshot while ownership is normalized.

## Matrix

| Domain | Transport | Polling | WebSocket | Retry/Backoff Owner | Cancellation Owner | State Owner | Primary Files |
|---|---|---|---|---|---|---|---|
| Lead Agent | WebSocket | Conditional (job refresh while active) | Yes | `asyncOperations` for polling + context reconnect policy | `asyncOperations` (poll) + context for socket lifecycle | `LeadAgentContext` | `Campaign_platform/src/contexts/LeadAgentContext.jsx`, `Campaign_platform/src/hooks/useLeadAgentWebSocket.js`, `Campaign_platform/src/components/AgentProgress.jsx` |
| MailPool Recategorize | HTTP status endpoint | Yes | No | `asyncOperations` | `asyncOperations` with per-task poll keys | Page local (`MailPool`) | `Campaign_platform/src/pages/MailPool.jsx`, `Campaign_platform/src/utils/asyncOperations.js` |
| MailPool Classify | HTTP status endpoint | Yes | No | `asyncOperations` | `asyncOperations` with per-task poll keys | Page local (`MailPool`) | `Campaign_platform/src/pages/MailPool.jsx`, `Campaign_platform/src/utils/asyncOperations.js` |
| Email Sync Progress | HTTP snapshot endpoints | Yes (continuous refresh) | No | `asyncOperations` | `asyncOperations` via component poll key | Component local (`EmailSyncProgress`) | `Campaign_platform/src/components/EmailSyncProgress.jsx`, `Campaign_platform/src/utils/asyncOperations.js` |
| CINT Survey Updates | WebSocket + REST fallback | Optional fallback | Yes | Hook reconnect policy | Hook lifecycle cleanup | Page local (`SurveyPool`) | `Campaign_platform/src/hooks/useSurveyWebSocket.js`, `Campaign_platform/src/pages/operations/surveyPool/SurveyPool.jsx` |
| Logs Page Auto Refresh | HTTP list endpoint | Yes | No | Local interval (pending normalization) | Local cleanup | Page local (`LogsPage`) | `Campaign_platform/src/pages/LogsPage.jsx` |

## Invariants

1. Do not introduce a second transport owner for an existing domain.
2. All long-running polling loops must have explicit cancellation keys.
3. Hidden tab behavior should reduce network load for continuous-refresh domains.
4. No payload renames, enum changes, or envelope normalization during this phase.

## Current High-Risk Watchpoints

1. Stale-result overwrite risk where older request responses arrive after newer state.
2. Cross-tab state drift for domains with local-only state owners.
3. Domain-specific reconnect behavior divergence between websocket implementations.

## Next Normalization Candidates

1. `Campaign_platform/src/pages/LogsPage.jsx` auto-refresh interval.
2. Survey pool mixed websocket/fallback ownership audit in `Campaign_platform/src/pages/operations/surveyPool/`.
3. Add request-version guards for domains with competing async updates.

---

## Backend: `async def` vs `def` on route handlers (added 2026-09-01, TOR-08)

820 route handlers were declared `async def` while only 251 awaited anything.
The rest ran blocking `pymongo` calls directly on the event loop, so any slow
query — the CRM pipeline report, a finance CSV import, a large export — froze
**every** concurrent request in the single uvicorn process, including WebSocket
heartbeats and the CINT webhook path. On a 1-vCPU box under a 1 GB cgroup that
is the most likely cause of user-visible stalls and 502s.

**The rule now:** a route handler is `async def` only if its body actually
awaits. Otherwise it is a plain `def`, and FastAPI runs it in the threadpool
where blocking I/O belongs.

Converted so far (132 handlers, the hot paths):

| File | Converted |
|---|---|
| `routers/finance.py` | 59 |
| `routers/crm.py` | 21 |
| `routers/panel_admin.py` | 19 |
| `routers/traffic.py` | 15 |
| `routers/sales_accounts.py` | 13 |
| `routers/sales_dashboard.py` | 5 |

Two handlers in `finance.py` (`create_customer`, `get_vendor`) were left
`async` because other code calls them directly with `await`; converting those
needs the call sites changed in the same commit.

Async dependencies (`verify_session`, the RBAC `require(...)` gates) work
unchanged against sync endpoints — FastAPI resolves those on the loop and then
hands the handler to the threadpool.

Converting to Motor is a separate, much larger project and is **not** required
to fix this. Do not start it as a side effect of touching a router.
