# Torpedo

<!-- deploy-pipeline-test: torpedo_v1 auto-deploy verification, 2026-09-16-retry2 -->


The in-house market-research business platform: lead generation, cold outreach,
an AI mail desk over the company inbox, a canonical CRM, quoting and invoicing,
project delivery, survey-panel routing, and a respondent panel.

**The authoritative structural map is [`docs/codebase_inventory.md`](docs/codebase_inventory.md)** —
every mounted router, Celery task, scheduled job and environment variable.
Update it when you add or move a router. This README is the orientation; that
file is the reference.

## Layout

```
backend/                FastAPI application (one uvicorn process serves everything)
  main.py               App entry point — router mounts and APScheduler jobs
  routers/              HTTP surface, one module per domain
  app/services/         CRM spine (crm_service, spine_connector) + CINT/CPX
  leads/                Lead generation: ICP -> search -> enrich -> classify
  sales/                Mail-pool AI desk, outreach pipeline
  services/             Panel acquisition, drips, funnel, health
  campaigns/ outreach/ outreach_engine/
                        Three superseded outreach generations; current path is
                        leads/outreach_mailer.py + sales/outreach_pipeline.py
  tasks/                Celery tasks (schedule lives in celery_app.py)
  tests/                pytest; `-m smoke` needs a running server
  deprecated/           Kept for history, mounted by nothing

Campaign_platform/      The React SPA (Vite). This is the frontend.
qre_frontend/           Respondent survey UI (served at /survey/)
qre_cx_frontend/        IDFC CX survey UI (served at /cx-survey/)
qre_backend/            Separate survey backend, port 8001, run under pm2

docs/                   Documentation; codebase_inventory.md is the map
deploy/                 systemd units and deployment scripts
scripts/                Operational scripts by domain
nginx_config.conf       The deployed nginx config (not a snapshot — the artifact)
RUNBOOK.md              Lead pipeline + deployment runbook
```

## Running it

Backend — note the working directory. The app runs with `backend/` as the
current directory, so `routers`, `database` and friends are top-level packages:

```bash
cd backend
python -m uvicorn main:app --reload
```

Frontend:

```bash
cd Campaign_platform
npm install
npm run dev
```

Required environment (see `.env.example`): `MONGO_URI`, `SESSION_SECRET`,
`CORS_ORIGINS`. The app refuses to start without a real `SESSION_SECRET` and
will not accept `*` for `CORS_ORIGINS`.

## Tests

```bash
pytest backend/tests -m "not smoke"     # everything that runs without a server
pytest backend/tests -m smoke           # needs a server on BASE_URL
```

`backend/tests/smoke/test_backend_startup.py` imports the app the way uvicorn
does and asserts every router mounted. It is the check that catches a deploy
that would come up with a module missing — router mount failures raise rather
than warn, so a broken import stops the boot instead of quietly removing a
section of the product.

## Deploying

Push to `main`. GitHub Actions runs CI and, on green, deploys to the VM
(`.github/workflows/deploy.yml`). **This is the only deploy path** — see
`RUNBOOK.md` §6 for what it does and how to recover it.

nginx is deployed separately and deliberately:

```bash
sudo cp nginx_config.conf /etc/nginx/sites-available/campaign-platform
sudo nginx -t && sudo systemctl reload nginx
```

## Conventions

- Conventional commits (`feat:` / `fix:` / `chore:` / `docs:`).
- Never commit credentials or data exports. CI fails the build on tracked
  `token.json`, `credentials.json`, `.env` or `leads_export/` paths.
- New router? Mount it in `main.py`, add its prefix to
  `REQUIRED_ROUTE_PREFIXES` in `backend/startup_checks.py`, and add it to the
  nginx location regex. A router that is mounted but missing from nginx is
  served the SPA's `index.html` instead of reaching the backend.
