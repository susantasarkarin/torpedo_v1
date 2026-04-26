# GitHub Copilot Custom Instructions — Torpedo v1

## Project Overview
**Backend**: Python (FastAPI + Celery + MongoDB Motor/PyMongo + Redis)
**Frontend**: React 18 + Vite + Radix UI + Tailwind CSS 4 (in `Campaign_platform/`)
**Secondary frontend**: React in `frontend/src/pages/`
**Databases**: MongoDB (primary), Redis (sessions/broker)
**AI integrations**: OpenAI (email classification), Gemini (enrichment), Google Gmail API

## Model Selection Preference
- Prefer a Sonnet-class model for deep reasoning tasks: architecture changes, complex debugging, migration planning, and cross-module refactors.
- Prefer a lighter/faster model for routine tasks: simple edits, small refactors, formatting, basic search, and straightforward test fixes.
- Escalate to Sonnet when requirements are ambiguous, risk is high, or a change spans multiple services.

## Agent Quick Start (High Signal)
- Start with `README.md` for layout and startup commands.
- Use deployment docs in `docs/deployment/` for environment/server workflows.
- Use integration docs in `docs/integrations/cint/` and `docs/integrations/cpx/` before changing survey providers.
- Use `.github/copilot/repo-notes/api-prefix-routing.md` for API prefix and router behavior.
- Use `.github/copilot/repo-notes/router_route_order.md` before touching React routing.
- Use `.github/copilot/repo-notes/frontend-architecture.md` for frontend module boundaries.
- Use `.github/copilot/repo-notes/vm-deployment.md` for VM deploy expectations.

---

## Agent Skills Available

Skills are stored in `.github/copilot/skills/`. When a task matches, **read the relevant SKILL.md** and follow its instructions.

### Skill Index

| Skill | Trigger | Location |
|-------|---------|----------|
| **webapp-testing** | Writing Playwright tests, browser automation, testing React pages, debugging UI behavior, capturing screenshots | `.github/copilot/skills/webapp-testing/SKILL.md` |
| **frontend-design** | Building React components, pages, dashboards, UI redesigns, styling, Tailwind layouts, landing pages | `.github/copilot/skills/frontend-design/SKILL.md` |
| **claude-api** | Integrating Anthropic Claude API, replacing OpenAI calls with Claude, building LLM features, tool use, streaming, prompt caching | `.github/copilot/skills/claude-api/SKILL.md` |
| **mcp-builder** | Creating MCP servers to expose backend APIs (campaigns, leads, surveys) to LLMs, TypeScript or Python MCP tools | `.github/copilot/skills/mcp-builder/SKILL.md` |
| **xlsx** | Creating Excel reports from campaign data, survey results, lead exports; editing or analyzing .xlsx files | `.github/copilot/skills/xlsx/SKILL.md` |
| **skill-creator** | Creating a new agent skill, improving an existing SKILL.md, running skill evaluations | `.github/copilot/skills/skill-creator/SKILL.md` |
| **web-artifacts-builder** | Building self-contained React HTML artifacts with shadcn/ui (same stack as Campaign_platform) | `.github/copilot/skills/web-artifacts-builder/SKILL.md` |

---

## Key Conventions

### API Routes
- All backend API endpoints are prefixed with `/api/` (enforced in nginx + FastAPI routers)
- Router files live in `backend/routers/` and `backend/app/routers/`
- See `.github/copilot/repo-notes/api-prefix-routing.md` for the routing pattern

### Frontend API Calls
- Use `Campaign_platform/src/utils/api.js` for all API calls (handles caching, retry, auth)
- Production uses relative URLs (nginx proxies `/api` to backend) — never hardcode production URLs
- Session token stored in `localStorage` as `session_id`

### MongoDB Collections
- Primary databases: `email_automation`, `traffic_flow_db`, `qre_otc_discovery`
- Use `backend/database.py` (`DatabaseManager` singleton) for all DB access — never create new `MongoClient` instances
- Async routes: use `get_async_collection()`; sync routes/Celery tasks: use `get_collection()`

### Task Queue (Celery)
- Background tasks in `backend/tasks/`
- Route survey tasks to `surveys` queue, LinkedIn tasks to `linkedin_automation` queue
- Import `celery_app` from `backend/celery_app.py`

### Authentication
- Session-based auth via Redis (`backend/session_store.py`)
- Password hashing via `backend/auth.py` — never store plain text passwords
- Use `validate_redirect_url()` from `backend/utils.py` to sanitize redirect targets

### React Frontend (`Campaign_platform/src/`)
- Pages in `pages/` organized by module: `sales/`, `finance/`, `analytics/`, `operations/`
- Use Radix UI + Tailwind + shadcn/ui component primitives
- Route order matters — see `.github/copilot/repo-notes/router_route_order.md`

---

## Helper Scripts

| Script | Purpose |
|--------|---------|
| `.github/copilot/skills/webapp-testing/scripts/with_server.py` | Start dev server + run Playwright test in one command |
| `.github/copilot/skills/xlsx/scripts/recalc.py` | Recalculate Excel formulas via LibreOffice after openpyxl edits |
