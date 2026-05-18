# API Contract Snapshot
**Captured**: 2026-05-17  
**Purpose**: Freeze the current runtime expectations between frontend and backend as of Phase 2.5 of the frontend stabilization effort. This document is the authoritative reference for what the frontend *currently expects*. Backend changes that alter these shapes must be coordinated with frontend consumers.

---

## 0. Global Transport Rules

| Rule | Value |
|------|-------|
| Auth header | `Authorization: {session_id}` (raw token, not `Bearer`) |
| Observability header | `X-Request-ID: {uuid}` (sent by `api.js` on every request) |
| Base URL (primary frontend, prod) | `""` — all paths are relative, nginx proxies |
| Base URL (secondary frontend, dev) | `http://localhost:8000` |
| 401 handling | `clearAuth()` → redirect to `/admin/login` |
| Content-Type | `application/json` for all non-file requests |

---

## 1. Authentication

Routes **do not** carry the `/api/` prefix. They hit nginx at root level and are proxied directly to the backend.

### POST /login/
**Request**
```json
{ "username": "string", "password": "string" }
```
**Response 201**
```json
{
  "message": "Login successful",
  "username": "string",
  "session_id": "string",
  "role": "string"
}
```
Frontend stores: `session_id`, `username`, `role` in `localStorage`.  
Errors: `400` missing fields · `401` bad credentials · `500` internal

### POST /logout/
**Request headers**: `Authorization: {session_id}`  
**Response 200**
```json
{ "message": "Logged out successfully" }
```
Frontend: `clearAuth()` removes `session_id`, `username`, `role` from `localStorage`.

### GET /health
**Response 200**
```json
{ "status": "healthy", "timestamp": "ISO8601", "version": "1.0.0" }
```

---

## 2. Finance

**Router prefix**: `/finance` (no `/api/` — nginx routes `/finance` directly to backend)  
**Source**: `backend/routers/finance.py`

### Pagination envelope (all list endpoints)
```json
{
  "<entity>s": [],
  "total": 0,
  "page": 1,
  "page_size": 100,
  "pages": 0
}
```
Default `page_size`: 100 · Max: 200  
Query params: `page`, `page_size`, `search`

### Mutation responses
All PUT/DELETE return:
```json
{ "message": "Entity action successfully" }
```
Bulk delete: `{ "message": "...", "deleted_count": int }`

### /finance/customers/
| Method | Path | Notes |
|--------|------|-------|
| GET | `/finance/customers/` | Paginated list |
| GET | `/finance/customers/{id}` | Single record |
| POST | `/finance/customers/` | Create |
| PUT | `/finance/customers/{id}` | Update |
| DELETE | `/finance/customers/{id}` | Soft delete |
| POST | `/finance/customers/bulk-delete` | `{ "ids": ["string"] }` |
| GET | `/finance/customers/export/csv` | CSV attachment |
| POST | `/finance/customers/import/csv` | `{ "imported": int, "errors": [] }` |

**Customer fields**: `_id, name, customer_type, company_name, email, phone, gst_treatment, gstin, pan, billing_address, payment_terms, credit_limit, currency, opening_balance, status, notes, created_at, updated_at`

### /finance/vendors/
| Method | Path | Notes |
|--------|------|-------|
| GET | `/finance/vendors/` | Paginated list |
| GET | `/finance/vendors/{id}` | Single record |
| POST | `/finance/vendors/` | Create |
| PUT | `/finance/vendors/{id}` | Update |
| DELETE | `/finance/vendors/{id}` | Soft delete |
| GET | `/finance/vendors/panel-vendors` | `[{_id, vid, name, email, type}]` |
| POST | `/finance/vendors/{id}/link-panel-vendor` | `{ "success": true, "finance_vendor_id": "...", "panel_vendor_id": "..." }` |
| DELETE | `/finance/vendors/{id}/unlink-panel-vendor` | `{ "success": true, "message": "..." }` |
| GET | `/finance/vendors/export/csv` | CSV attachment |
| POST | `/finance/vendors/import/csv` | `{ "imported": int, "errors": [] }` |

**Vendor fields**: `_id, name, vendor_type, company_name, email, phone, gst_treatment, gstin, pan, billing_address, payment_terms, currency, bank_name, account_number, ifsc_code, opening_balance, status, notes`

### /finance/items/
**Item fields**: `_id, name, sku, description, type, unit, selling_price, purchase_price, tax_rate, hsn_sac_code, track_inventory, stock_quantity, low_stock_threshold, status`

### /finance/invoices/
**Invoice fields**: `_id, invoice_number, customer_id, customer_name, invoice_date, due_date, items[], subtotal, tax_amount, discount_type, discount_value, total, balance_due, status, payment_status, notes`

### /finance/estimates/
**Estimate fields**: `_id, estimate_number, customer_id, estimate_date, expiry_date, reference, currency_code, items[], subtotal, tax_amount, discount_type, discount_value, total, status, notes, terms`

### /finance/bills/
**Bill fields**: `_id, bill_number, vendor_id, bill_date, due_date, items[], subtotal, tax_amount, total_amount, balance_due, status, notes`

---

## 3. Leads

**Router prefix**: `/leads` (registered under `/api/leads/` via nginx)  
**Source**: `backend/leads/router.py`

### GET /leads/ (list)
**Query params**: `page`, `page_size`, `search`, filters  
**Response**
```json
{
  "leads": [
    {
      "_id": "string",
      "name": "string",
      "email": "string",
      "title": "string",
      "linkedin_url": "string",
      "created_at": "ISO8601",
      "updated_at": "ISO8601",
      "status": "pending|classified|matched",
      "classification": {},
      "engagement_status": "string"
    }
  ],
  "total": 0,
  "page": 1,
  "page_size": 50,
  "pages": 0
}
```

### POST /leads/import/web-search
**Request**: `{ "query": "string", "num_results": int, "target_count": int }`  
**Response**: `{ "success": true, "job_id": "string", "status_url": "string" }`

### GET /leads/import/web-search/status/{job_id}
**Response**
```json
{
  "job_id": "string",
  "status": "running|completed|stopped|error",
  "target_count": int,
  "total_imported": int,
  "total_duplicates": int,
  "progress_percent": 0,
  "eta_minutes": int,
  "errors": []
}
```

### POST /leads/import/csv
**Form data**: `file: UploadFile, delimiter: string` (default `,`)  
**Response**: `{ "parsed": int, "imported": int, "duplicates": int, "errors": [] }`

---

## 4. Cold Outreach

**Router prefix**: `/api/cold-outreach` (owns its own `/api/` prefix — set in the router itself)  
**Source**: `backend/routers/cold_outreach_router.py`

### Mailboxes
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/cold-outreach/mailboxes` | List mailboxes |
| POST | `/api/cold-outreach/mailboxes` | Add mailbox (201) |
| DELETE | `/api/cold-outreach/mailboxes/{mailbox_id}` | Remove mailbox |

### Campaigns
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/cold-outreach/campaigns` | List campaigns |
| POST | `/api/cold-outreach/campaigns` | Create campaign (201) |
| POST | `/api/cold-outreach/campaigns/{id}/launch` | Launch |
| POST | `/api/cold-outreach/campaigns/{id}/pause` | Pause |
| POST | `/api/cold-outreach/campaigns/{id}/resume` | Resume |
| GET | `/api/cold-outreach/campaigns/{id}/stats` | Campaign stats |
| GET | `/api/cold-outreach/campaigns/{id}/leads-by-status` | Leads grouped by status |

### Campaign Steps
| Method | Path | Notes |
|--------|------|-------|
| PUT | `/api/cold-outreach/campaigns/{id}/steps/{step_number}` | Save step |
| POST | `/api/cold-outreach/campaigns/{id}/steps/{step_number}/generate` | AI generate step |
| POST | `/api/cold-outreach/campaigns/{id}/steps/{step_number}/test` | Send test email |
| POST | `/api/cold-outreach/campaigns/{id}/steps/{step_number}/attachments` | Upload attachment |
| DELETE | `/api/cold-outreach/campaigns/{id}/steps/{step_number}/attachments/{filename}` | Remove attachment |

### Campaign Context
| Method | Path | Notes |
|--------|------|-------|
| PUT | `/api/cold-outreach/campaigns/{id}/context` | Save AI context |

### Suppression
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/cold-outreach/suppression` | List suppressions |
| GET | `/api/cold-outreach/suppression/stats` | Stats summary |
| POST | `/api/cold-outreach/suppression/manual` | Add suppression (201) |
| DELETE | `/api/cold-outreach/suppression/{email}` | Remove suppression |

### Dual Fit
| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/cold-outreach/dual-fit/enroll` | Enroll leads in Dual Fit sequence |

### Tracking (server-side, not frontend-called)
- `GET /api/cold-outreach/track/open/{send_id}` — pixel tracking
- `GET /api/cold-outreach/track/click/{send_id}?url=...` — click redirect

### Operational
- `POST /api/cold-outreach/process-due` — trigger due sends
- `POST /api/cold-outreach/reset-stuck-leads` — ops recovery
- `GET /api/cold-outreach/sender-status` — mailbox health
- `POST /api/cold-outreach/scan-bounces-replies` — scan mailboxes
- `POST /api/cold-outreach/sync-replies-to-leads` — sync reply state to leads

---

## 5. CINT Integration

**Router prefix**: `/api/cint`  
**Source**: `backend/routers/cint.py`

### WebSocket /api/cint/ws/surveys
Unauthenticated broadcast. Frontend connects for live survey pool updates.

**On connect** (server sends immediately):
```json
{
  "type": "connected",
  "message": "Connected to CINT survey updates",
  "timestamp": "ISO8601"
}
```

**Survey update broadcast**:
```json
{
  "type": "surveys_update",
  "surveys": [
    {
      "survey_id": 0,
      "country_language": "string",
      "length_of_interview": 0,
      "payout": 0.0,
      "conversion_rate": 0.0,
      "is_active": true,
      "is_active_in_pool": true
    }
  ],
  "count": 0,
  "source": "webhook"
}
```

### GET /api/cint/surveys
**Query params**: `min_loi`, `max_loi`, `min_cpi`, `country`, `page` (default 1), `page_size` (default 20, max 1000), `active_only`, `show_all`  
**Response**
```json
{
  "success": true,
  "surveys": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "filtered": false
}
```

### POST /api/cint/webhooks/opportunities
**Headers**: `X-Cint-Signature` (HMAC-SHA256)  
**Response 200**: `{ "success": true, "message": "Opportunities processed", "count": int }`  
**Response 401**: invalid signature · **Response 500**: processing error

### POST /api/cint/webhooks/respondent-outcomes
**Headers**: `X-Cint-Signature`, `X-Cint-Timestamp`  
**Response 200**: `{ "success": true, "message": "Outcomes processed", "count": int }`

---

## 6. Known Gaps (Frontend Expects — Backend Not Yet Wired)

| Frontend consumer | Expected endpoint | Status |
|-------------------|-------------------|--------|
| `useLeadAgentWebSocket.js` | `WS /leads/agents/ws/{jobId}` | ❌ No backend WebSocket handler exists |
| `/admin/marketing/linkedin` | LinkedIn automation router | ❌ Router not registered in `main.py` |

---

## 7. Routing Summary

| Prefix | Where it lives | nginx passthrough |
|--------|----------------|-------------------|
| `/login/`, `/logout/` | `backend/routers/auth_handler.py` | Root — no prefix strip |
| `/health` | `backend/main.py` | Root — no prefix strip |
| `/finance/...` | `backend/routers/finance.py` | Direct — no `/api/` |
| `/api/cold-outreach/...` | `backend/routers/cold_outreach_router.py` | Has `/api/` in its own prefix |
| `/api/leads/...` | `backend/leads/router.py` | Via `/api/` |
| `/api/cint/...` | `backend/routers/cint.py` | Via `/api/` |

> **Critical**: Finance uses `/finance/...` not `/api/finance/...`. This distinction is enforced by `backend/routers/finance.py` (`prefix="/finance"`) and the nginx routing config. Any code using `/api/finance/` will 404 in production.
