# Frontend Inventory
**Date**: 2026-05-16  
**Scope**: Both active frontends — `Campaign_platform/src/` (primary) and `frontend/src/pages/` (secondary, live in production)  
**Purpose**: Phase 1 living reference — do not modify code before this document exists

---

## 1. FRONTEND TOPOLOGY

| Frontend | Location | Framework | Status |
|---|---|---|---|
| Primary | `Campaign_platform/src/` | React 18 + Vite + Radix UI + Tailwind CSS 4 | Active, primary |
| Secondary | `frontend/src/pages/` | React (standalone pages, no router file) | Active, live in production |

---

## 2. ALL ROUTES — Campaign_platform (Primary)

### Public / Survey Routes (no auth)
| Route | Component | Notes |
|---|---|---|
| `/` | Navigate → `/admin/login` | |
| `/takesurvey` | `TrafficFlowParser.jsx` | |
| `/survey-start` | `TrafficFlowParser.jsx` | |
| `/survey-error` | `SurveyError.jsx` | |
| `/nosurvey` | `SurveyError.jsx` | |
| `/response` | `SurveyResponse.jsx` | |
| `/survey-response` | `SurveyResponse.jsx` | |
| `/admin/login` | `Login.jsx` | |

### Panel Routes (public)
| Route | Component |
|---|---|
| `/panel/login` | `PanelLogin.jsx` |
| `/panel/signup` | `PanelSignup.jsx` |
| `/panel/forgot-password` | `PanelForgotPassword.jsx` |
| `/panel/why-join` | `WhyJoin.jsx` |
| `/panel/rewards-info` | `RewardsInfo.jsx` |
| `/panel/terms` | `Terms.jsx` |
| `/panel/privacy` | `Privacy.jsx` |
| `/panel/faq` | `FAQ.jsx` |

### Panel Routes (protected by PanelProtectedRoute)
| Route | Component |
|---|---|
| `/panel/dashboard` | `PanelDashboard.jsx` |
| `/panel/profile` | `PanelProfile.jsx` |
| `/panel/rewards` | `PanelRewards.jsx` |

### Admin Routes (protected by ProtectedRoute + LeadAgentProvider)

**Core**
| Route | Component |
|---|---|
| `/admin/dashboard` | `Dashboard.jsx` |
| `/admin/settings` | `Settings.jsx` |
| `/admin/profile` | `MyProfile.jsx` |
| `/admin/mail-pool` | `MailPool.jsx` |
| `/admin/gmail-setup` | `GmailSetup.jsx` |
| `/admin/logs` | `LogsPage.jsx` |

**Sales (17 routes)**
| Route | Component | Notes |
|---|---|---|
| `/admin/sales` | `SalesDashboard.jsx` | |
| `/admin/sales/campaign` | `Campaign.jsx` | |
| `/admin/sales/leads` | `Leads.jsx` | |
| `/admin/sales/leads/import` | `LeadsImport.jsx` | |
| `/admin/sales/contacts` | `Contacts.jsx` | |
| `/admin/sales/contacts/import` | `ContactsImport.jsx` | |
| `/admin/sales/companies/:companyName` | `CompanyDetail.jsx` | |
| `/admin/sales/rfq` | `RFQ.jsx` | |
| `/admin/sales/campaign/list` | `List.jsx` | |
| `/admin/sales/campaign/ai-leads` | `AILeads.jsx` | |
| `/admin/sales/campaign/ai-leads/:leadId` | `AILeadDetail.jsx` | |
| `/admin/sales/campaign/email-patterns` | `EmailPatterns.jsx` | |
| `/admin/sales/campaign/workflow` | `Workflow.jsx` | |
| `/admin/sales/outreach` | `ColdOutreach.jsx` (alias: Outreach.jsx) | |
| `/admin/sales/company-upload` | `CompanyUpload.jsx` | |
| `/admin/sales/agent-dashboard` | `AgentDashboard.jsx` | |
| `/admin/sales/agent-settings` | `AgentSettings.jsx` | |

**Marketing**
| Route | Component | Notes |
|---|---|---|
| `/admin/marketing` | `Marketing.jsx` | |
| `/admin/marketing/linkedin` | `LinkedInAutomationPage.jsx` | ⚠️ Backend router NOT registered |

**Finance (18 routes)**
| Route | Component |
|---|---|
| `/admin/finance` | `Finance.jsx` |
| `/admin/finance/customers` | `FinanceCustomersPage.jsx` |
| `/admin/finance/customers/import` | `FinanceCustomersImport.jsx` |
| `/admin/finance/vendors` | `FinanceVendorsPage.jsx` |
| `/admin/finance/invoices` | `InvoicesPage.jsx` |
| `/admin/finance/invoices/import` | `InvoicesImport.jsx` |
| `/admin/finance/bills` | `BillsPage.jsx` |
| `/admin/finance/bills/import` | `BillsImport.jsx` |
| `/admin/finance/expenses` | `ExpensesPage.jsx` |
| `/admin/finance/purchase-orders` | `PurchaseOrdersPage.jsx` |
| `/admin/finance/purchase-orders/import` | `PurchaseOrdersImport.jsx` |
| `/admin/finance/payments` | `PaymentsPage.jsx` |
| `/admin/finance/payments/import` | `PaymentsImport.jsx` |
| `/admin/finance/reports` | `ReportsPage.jsx` |
| `/admin/finance/items` | `FinanceItems.jsx` |
| `/admin/finance/estimates` | `EstimatesPage.jsx` |
| `/admin/finance/estimates/import` | `EstimatesImport.jsx` |
| `/admin/finance/settings` | Inline placeholder — "Coming Soon" |

**Operations (13 routes)**
| Route | Component |
|---|---|
| `/admin/operations` | `Operations.jsx` |
| `/admin/operations/dashboard` | `Operations.jsx` (same) |
| `/admin/operations/accounts` | `AccountsPage.jsx` |
| `/admin/operations/clients` | `ClientsPage.jsx` |
| `/admin/operations/vendors` | `VendorsPage.jsx` |
| `/admin/operations/projects` | `ProjectsPage.jsx` |
| `/admin/operations/projects/:projectId` | `ProjectDetail.jsx` |
| `/admin/operations/survey-pool` | `SurveyPool.jsx` |
| `/admin/operations/potential-clients` | `PotentialClients.jsx` |
| `/admin/operations/rate-card` | `RateCard.jsx` |
| `/admin/operations/yield-management` | `YieldManagement.jsx` |
| `/admin/operations/traffic` | `TrafficManagement.jsx` |
| `/admin/operations/reports` | `CPXCallbackLogs.jsx` |
| `/admin/operations/qre` | `QREPage.jsx` |

**Vendor (5 routes)**
| Route | Component |
|---|---|
| `/admin/vendor` | `VendorDashboard.jsx` |
| `/admin/vendor/leads` | `VendorLeadsPage.jsx` |
| `/admin/vendor/all` | `VendorVendorsPage.jsx` |
| `/admin/vendor/billing` | `VendorBillingPage.jsx` |
| `/admin/vendor/payments` | `VendorPaymentsPage.jsx` |

**Other Admin**
| Route | Component | Notes |
|---|---|---|
| `/admin/hr` | `HR.jsx` | |
| `/admin/panel-admin` | `PanelAdminDashboard.jsx` | |
| `/admin/panel-admin/panelists` | `PanelistManagement.jsx` | |
| `/admin/panel-admin/rewards` | `RewardsPoints.jsx` | |
| `/admin/panel-admin/settings` | `PanelSettings.jsx` | |
| `/admin/projects` | `Projects.jsx` | |
| `/admin/support` | `Support.jsx` | |

**Catch-all**: `*` → Navigate to `/`

### Orphaned / Unrouted Pages (files exist but not in App.jsx)
| File | Status | Backend |
|---|---|---|
| `Campaign_platform/src/pages/sales/AIConfig.jsx` | Not routed — to be archived | `/api/sales-outreach/bu-configs` exists |
| `Campaign_platform/src/pages/sales/AIDatabase.jsx` | Not routed | `/leads/ai-database/*` exists |
| `Campaign_platform/src/pages/sales/Deliverability.jsx` | Not routed | `/deliverability/*` exists |

---

## 3. ROUTES — Secondary Frontend (frontend/src/pages/)

No router configuration file found. Pages are standalone React components likely embedded or linked directly.

| File | Endpoints Called |
|---|---|
| `MailOperations.jsx` | `/api/mail/segregation-stats`, `/api/mail/segregate`, `/api/mail/summary`, `/api/mail/extracted-contacts` |
| `ProfileSettings.jsx` | `/api/prompts`, `/api/prompts/{id}`, `/api/prompts/{id}/versions`, `/api/prompts/create` |
| `analytics/Reports.jsx` | `/api/analytics/reports` (axios) |
| `sales/Predictions.jsx` | `/api/predictions/reply-probability` |
| `sales/ExecutiveDashboard.jsx` | Sales dashboard aggregate endpoint |

---

## 4. API CLIENTS & CALL PATTERNS

### Primary Frontend (Campaign_platform/src/)

#### Centralized Client — `Campaign_platform/src/utils/api.js`
- Methods: `api.get()`, `api.post()`, `api.put()`, `api.delete()`, `api.patch()`
- Caching: 2-minute TTL, request deduplication
- Retry: 3x automatic retry
- Timeout: 30 seconds
- Auth: auto-injects `Authorization: {session_id}` from localStorage
- 401 handling: calls `clearAuth()` then `window.location.href = "/login"` ⚠️ **BUG: should be `/admin/login`**
- Base URL: empty string in production (nginx proxy), `http://localhost:8000` in dev

#### Custom Hook — `Campaign_platform/src/hooks/useApi.js`
- Wraps api.js with React state (loading, data, error)
- Supports caching, TTL, transforms
- Usage: `const { data, loading, error, refetch } = useApi('/endpoint', options)`

#### Direct fetch() Still in Use (bypasses api.js)
These files use direct `fetch()` with `buildApiUrl()` from config.js:
- `pages/Login.jsx` — intentional (pre-auth)
- `components/Navbar.jsx` — logout
- `pages/MailPool.jsx`
- `pages/GmailSetup.jsx`
- Various Finance pages
- Various Sales pages

#### Direct axios Usage
- `frontend/src/pages/analytics/Reports.jsx` — `axios.get('/api/analytics/reports')`

### Secondary Frontend (frontend/src/pages/)

**All files use direct fetch() — no centralized client.**

```javascript
// Pattern in every secondary frontend file:
const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
// ⚠️ process.env.REACT_APP_API_URL is a CRA variable — will not resolve in Vite builds
// Falls back to hardcoded localhost:8000 always in production if served via Vite

// Auth pattern — WRONG key:
'Authorization': localStorage.getItem('sessionToken') || ''
// ⚠️ Primary frontend uses 'session_id' — 'sessionToken' will always be null
```

**sessionToken occurrences**: 17 in `MailOperations.jsx` + `ProfileSettings.jsx`  
**API_BASE_URL occurrences**: 2 files (`MailOperations.jsx`, `ProfileSettings.jsx`)

---

## 5. WEBSOCKET CONNECTIONS

| Channel | URL | Hook/File | Reconnect Strategy |
|---|---|---|---|
| CINT Surveys | `/api/cint/ws/surveys` | `useSurveyWebSocket.js` | Exponential backoff: 2s→5s→10s→20s→30s, max 5 retries |
| CPX Surveys | `/cpx/ws/surveys` | `useSurveyWebSocket.js` | Same as above |
| Lead Agent | `/api/leads/ws/agent` | `useLeadAgentWebSocket.js` + `LeadAgentContext.jsx` | Yes — details in hook |

**WebSocket message types**:
- Inbound: `surveys_update`, `connected`, `heartbeat`
- Outbound: `ping` (response to heartbeat)

⚠️ **Note**: WebSocket connections do not send auth headers in the URL or Upgrade request. Verify if backend `/api/leads/ws/agent` requires session validation.

---

## 6. POLLING INTERVALS

### asyncOperations.js (Campaign_platform/src/utils/asyncOperations.js)
- Endpoint: `/api/operations/async/{operationId}/status` ✅ matches backend prefix `/api/operations` + route `/async/{id}/status`
- Strategy: exponential backoff, 1s min → 30s max, 1.5x multiplier, unlimited attempts
- Cancel endpoint: `/api/operations/async/{operationId}/cancel`
- List active: `/api/operations/async/active`
- Fallback poll URL: uses `response.poll_url` if provided by backend (backend includes it in response body)

### Manual Polling (ad-hoc, not using asyncOperations.js)
- Email recategorization: polls `/email-sync/recategorize-status/{taskId}` — uses raw `setInterval`, no backoff
- Gmail classify: polls `/gmail/mail-pool/classify/status/{taskId}`

---

## 7. AUTH / SESSION FLOWS

### Admin Session (primary frontend)
| Step | Detail |
|---|---|
| Login | `POST /login/` with `{username, password}` |
| On success | Store `session_id`, `username`, `role` in localStorage; set `auth=true` |
| Request auth | `Authorization: {session_id}` header (via api.js) |
| 401 handling | `clearAuth()` → `window.location.href = "/login"` ⚠️ wrong — should be `/admin/login` |
| Logout | `POST /logout/` → clear all localStorage keys → redirect to `/admin/login` |
| Route guard | `ProtectedRoute.jsx` — checks `localStorage.session_id` existence only |

**Auth routes (backend)**:
- `POST /login/` — `backend/routers/auth_handler.py` — no prefix, root level
- `POST /logout/` — same file

### Panel Session
| Step | Detail |
|---|---|
| Login | `POST /panel/login` |
| Token key | `panel_session_id` in localStorage |
| Header | `X-Panel-Session-Id: {panel_session_id}` |
| Route guard | `PanelProtectedRoute.jsx` |

### Secondary Frontend (BROKEN)
| Step | Detail |
|---|---|
| Token key used | `localStorage.getItem('sessionToken')` |
| Correct key | `session_id` |
| Impact | All API calls send empty `Authorization` header — requests are unauthenticated |

---

## 8. LOCALSTORAGE KEYS

| Key | Used by | Notes |
|---|---|---|
| `session_id` | Primary frontend, api.js | Admin session token |
| `username` | Primary frontend | Display only |
| `role` | Primary frontend | Role-based UI rendering |
| `auth` | Primary frontend (Login.jsx) | Boolean string `"true"` |
| `panel_session_id` | Panel pages | Panel user session |
| `panelist_data` | Panel pages | Panelist profile JSON |
| `syncStatus` | SyncStatusContext.jsx | Email sync state JSON — **DISABLED** |
| `sessionToken` | Secondary frontend ⚠️ | Wrong key — always empty in production |

---

## 9. ENVIRONMENT VARIABLES

| Variable | Location | Resolves in Vite? | Value |
|---|---|---|---|
| `VITE_QRE_API_URL` | `Campaign_platform/src/services/qreApi.js` | ✅ Yes | `/qre-api` (prod) or `http://localhost:8001` (dev) |
| `REACT_APP_API_URL` | `frontend/src/pages/MailOperations.jsx`, `ProfileSettings.jsx` | ❌ No (CRA variable) | Falls back to `http://localhost:8000` always |

---

## 10. HARDCODED URLS

| URL | File | Context |
|---|---|---|
| `http://localhost:8000` | `Campaign_platform/src/config.js` | Dev API base (correct — dev only) |
| `http://localhost:8001` | `Campaign_platform/src/services/qreApi.js` | Dev QRE base (correct — dev only) |
| `ws://localhost:8000` | `Campaign_platform/src/config.js` | Dev WebSocket base (correct) |
| `http://localhost:8000` | `frontend/src/pages/MailOperations.jsx` | Fallback (always used — broken env) |
| `http://localhost:8000` | `frontend/src/pages/ProfileSettings.jsx` | Same |

---

## 11. KNOWN ISSUES (Phase 2 Pre-Audit)

### CONFIRMED BUGS

#### 1. Finance Double-Prefix
**Severity**: High — all Finance CRUD calls are broken in production  
**Backend**: `backend/routers/finance.py` — `router = APIRouter(prefix="/finance")` + routes `@router.get("/finance/customers/")` etc.  
**Result**: Full path = `/finance/finance/customers/` — all Finance API calls go to wrong path  
**Affected pages**: `FinanceCustomersPage.jsx`, `FinanceVendorsPage.jsx`, `BillsPage.jsx`, `InvoicesPage.jsx`, `PaymentsPage.jsx`, `PurchaseOrdersPage.jsx`, `EstimatesPage.jsx`, `ExpensesPage.jsx`  
**Fix needed**: Remove `/finance/` prefix from all route path decorators in `finance.py` (the router prefix already provides it), OR remove the `prefix="/finance"` from the router definition  

#### 2. Secondary Frontend — Wrong Auth Token Key
**Severity**: Critical — all secondary frontend API calls are unauthenticated  
**Files**: `frontend/src/pages/MailOperations.jsx` (4 calls), `frontend/src/pages/ProfileSettings.jsx` (13 calls)  
**Bug**: Uses `localStorage.getItem('sessionToken')` — key does not exist; primary frontend writes to `session_id`  
**Fix needed**: Replace `sessionToken` → `session_id` (17 occurrences)

#### 3. Secondary Frontend — CRA Env Variable in Vite Build
**Severity**: High — `API_BASE_URL` always resolves to `localhost:8000` in production  
**Files**: `frontend/src/pages/MailOperations.jsx`, `frontend/src/pages/ProfileSettings.jsx`  
**Bug**: `process.env.REACT_APP_API_URL` is a Create React App convention — undefined in Vite  
**Fix needed**: Replace with empty string (relative URL) or `import.meta.env.VITE_API_URL`

#### 4. api.js — Wrong 401 Redirect Target
**Severity**: Medium — redirect works via catch-all but creates unnecessary redirect chain  
**Location**: `Campaign_platform/src/utils/api.js` line ~134  
**Bug**: `window.location.href = "/login"` — app login is at `/admin/login`  
**Fix needed**: Change to `/admin/login`

### BACKEND INTEGRATION ISSUES

#### 5. LinkedIn Automation Router Not Registered
**Severity**: High — LinkedIn automation page (`/admin/marketing/linkedin`) calls 404 endpoints  
**Backend**: `backend/linkedin_automation/router.py` — not registered in `main.py`  
**Frontend**: `Campaign_platform/src/pages/marketing/LinkedInAutomationPage.jsx`  
**Fix needed**: Backend must register router; or page must show "service unavailable" state

#### 6. Vendor Stats Returns HTML
**Severity**: Medium — vendor stats endpoint returns 404 served as index.html fallback  
**Cause**: Nginx serves `index.html` for unmatched routes  
**Fix needed**: Backend registration or frontend graceful handling

### DISABLED INFRASTRUCTURE

#### 7. SyncStatusContext
**Status**: Commented out in `App.jsx` (line 10) and `Settings.jsx` (line 6)  
**Comment**: "temporarily disabled for debugging login issue"  
**Also**: `GlobalSyncStatus.jsx` imports from it — may render empty or throw  
**Decision**: Leave disabled — do not touch until cause is identified  
**Action needed**: Add null-safety check in `GlobalSyncStatus.jsx` if it references the context

### ORPHANED PAGES

#### 8. AIDatabase.jsx
**File**: `Campaign_platform/src/pages/sales/AIDatabase.jsx`  
**Status**: Not in App.jsx routes — unreachable  
**Backend**: `/leads/ai-database/*` endpoints exist  
**Decision**: Archive to `_archived/`

#### 9. AIConfig.jsx
**File**: `Campaign_platform/src/pages/sales/AIConfig.jsx`  
**Status**: Not in App.jsx routes — unreachable  
**Backend**: `/api/sales-outreach/bu-configs` exists  
**Decision**: Archive to `_archived/`

#### 10. Deliverability.jsx
**File**: `Campaign_platform/src/pages/sales/Deliverability.jsx`  
**Status**: Not in App.jsx routes — unreachable  
**Backend**: `/deliverability/*` endpoints exist  
**Decision**: Archive to `_archived/`

---

## 12. AI-RELATED FRONTEND FLOWS

| Flow | Page | Endpoint | Status |
|---|---|---|---|
| Lead discovery | `AILeads.jsx` | `GET /leads` with filters | ✅ Active |
| Lead enrichment | `AILeadDetail.jsx` | `GET /leads/enriched/{id}` | ✅ Active |
| Agent dashboard | `AgentDashboard.jsx` | WebSocket `/api/leads/ws/agent` + REST | ✅ Active |
| Agent settings | `AgentSettings.jsx` | `GET/POST /leads/agents/*` | ✅ Active |
| Web search import | `LeadsImport.jsx` | `POST /leads/import/web-search` | ✅ Active |
| Batch email classify | `MailPool.jsx` | `POST /gemini/classify-batch` | ✅ Active |
| AI outreach config | `AIConfig.jsx` | `/api/sales-outreach/bu-configs` | ❌ Orphaned |
| AI database import | `AIDatabase.jsx` | `/leads/ai-database/*` | ❌ Orphaned |
| Prompt management | `frontend/src/pages/ProfileSettings.jsx` | `/api/prompts/*` | ⚠️ Broken auth |

---

## 13. UPLOAD / DOWNLOAD FLOWS

| Operation | Page | Endpoint | Method |
|---|---|---|---|
| Lead CSV import | `LeadsImport.jsx` | `POST /leads/import/csv` | multipart/form-data |
| Contacts CSV import | `ContactsImport.jsx` | `POST /contacts/import/csv` | multipart/form-data |
| Finance entity imports (7 types) | `*Import.jsx` pages | `POST /finance/finance/{entity}/import/csv` ⚠️ double-prefix | multipart/form-data |
| Finance CSV exports | Finance pages | `GET /finance/finance/{entity}/export/csv` ⚠️ double-prefix | download |
| Company upload | `CompanyUpload.jsx` | `/leads/import/csv` | multipart/form-data |
| Cold outreach attachment upload | `Outreach.jsx` | `POST /api/cold-outreach/campaigns/{id}/steps/{n}/attachments` | multipart/form-data |

---

## 14. STATE MANAGEMENT

| Context / Store | File | Status | Notes |
|---|---|---|---|
| `LeadAgentContext` | `contexts/LeadAgentContext.jsx` | ✅ Active | Agent job lifecycle, used by AgentDashboard |
| `SyncStatusContext` | `contexts/SyncStatusContext.jsx` | ❌ Disabled | Commented out in App.jsx |

**No Redux or Zustand.** State is component-local or via Context.

**Over-fetching patterns** (flag for future optimization, do not change now):
- `Contacts.jsx`: fetches 200 records max, paginates locally (10/page)
- `BillsPage.jsx`: fetches all bills, paginates locally
- `Reports.jsx` (secondary): slices first 3 metrics client-side
- `Predictions.jsx` (secondary): fetches all, shows first 20

---

## 15. FEATURE FLAGS

None detected. No `VITE_FEATURE_*` variables, no `window.__flags` pattern, no LaunchDarkly or similar.

---

## SUMMARY STATISTICS

| Category | Count |
|---|---|
| Primary frontend routes | ~95 |
| Secondary frontend pages | 5 (MailOperations, ProfileSettings, Reports, Predictions, ExecutiveDashboard) |
| Active WebSocket channels | 3 |
| localStorage keys | 8 (1 broken: sessionToken) |
| Environment variables | 2 (1 broken: REACT_APP_API_URL) |
| Confirmed bugs | 4 |
| Orphaned/unrouted pages | 3 (AIDatabase, AIConfig, Deliverability) |
| Backend routers unregistered | 2 (linkedin_automation, outreach_api) |
| Disabled contexts | 1 (SyncStatusContext) |

---

## NEXT: Phase 2 — API Alignment Audit

Primary targets:
1. Fix Finance double-prefix in `backend/routers/finance.py`
2. Fix secondary frontend `sessionToken` → `session_id` (17 occurrences)
3. Fix secondary frontend `process.env.REACT_APP_API_URL` → relative URL
4. Fix `api.js` 401 redirect → `/admin/login`
5. Verify LinkedIn page behavior with unregistered backend router
6. Decide GlobalSyncStatus.jsx null-safety with disabled context
