# Unmounted routers (TOR-26)

These files define complete FastAPI endpoint sets that **no `include_router`
call ever reached**. They were live-looking dead code sitting next to mounted
routers, so every reader had to work out for themselves which was which.

Moved here 2026-09-01 rather than deleted, because two of them describe
features somebody clearly intended:

| File | Lines | What it implements |
|---|---|---|
| `marketing.py` | 846 | Website/SEO tracking, marketing dashboard |
| `team.py` | 628 | Lead assignment, per-user activity feed |
| `intelligence.py` | 275 | Thread analysis, sentiment, needs-attention queue |
| `autopilot.py` | 233 | Campaign auto-optimisation |
| `app_outreach_api.py` | — | Was `app/routers/outreach_api.py`; superseded by `leads/outreach_mailer.py` |

To bring one back: move it into `backend/routers/`, add the `include_router`
call in `main.py`, add its prefix to `REQUIRED_ROUTE_PREFIXES` in
`backend/startup_checks.py`, and add the prefix to the nginx location regex in
`/nginx_config.conf`. All four steps — a router that is mounted but not in the
nginx list is served the SPA's `index.html` instead.
