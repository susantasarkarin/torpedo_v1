# CPX API Structures - Complete Documentation

## Overview
This document provides all API endpoint structures for the CPX (Consumer Perspective Exchange) integration in the campaign platform.

---

## Table of Contents
1. [CPX Router APIs (`/api/cpx/*`)](#cpx-router-apis)
2. [CPX API Router (`/cpx-api/*`)](#cpx-api-router)
3. [Traffic Flow Parser APIs](#traffic-flow-parser-apis)
4. [Survey Pool APIs](#survey-pool-apis)
5. [Data Models](#data-models)

---

## CPX Router APIs

### Base URL: `/api/cpx`

### 1. Get Surveys
**Endpoint:** `GET /api/cpx/surveys`

**Description:** Fetch CPX surveys with filters and pagination

**Query Parameters:**
```typescript
{
  min_loi?: number;           // Minimum length of interview
  max_loi?: number;           // Maximum length of interview
  min_payout?: number;        // Minimum payout amount
  country?: string;           // Filter by country code (e.g., "US")
  category?: string;          // Filter by category
  page?: number;              // Page number (default: 1)
  page_size?: number;         // Items per page (default: 20, max: 1000)
  active_only?: boolean;      // Only active surveys (default: false)
  show_all?: boolean;         // Show all surveys without filters (default: false)
}
```

**Headers:**
```
Authorization: <session_id>
```

**Response:**
```json
{
  "surveys": [
    {
      "survey_id": "57572480",
      "name": "Consumer Survey",
      "loi": 10,
      "cpi": 2.50,
      "ir": 75,
      "quota": 1000,
      "status": "active",
      "country": "US",
      "is_active_in_pool": true,
      "href": "https://click.cpx-research.com/...",
      "created_at": "2026-02-04T10:00:00Z"
    }
  ],
  "total": 245,
  "page": 1,
  "page_size": 20,
  "total_pages": 13
}
```

---

### 2. Save Filter Settings
**Endpoint:** `POST /api/cpx/filter-settings`

**Description:** Save user's filter preferences

**Headers:**
```
Authorization: <session_id>
Content-Type: application/json
```

**Request Body:**
```json
{
  "min_loi": 5,
  "max_loi": 15,
  "min_payout": 2.5,
  "country": "US",
  "category": "Technology",
  "auto_refresh": true
}
```

**Response:**
```json
{
  "message": "Filter settings saved successfully",
  "filters": {
    "min_loi": 5,
    "max_loi": 15,
    "min_payout": 2.5
  }
}
```

---

### 3. Get Filter Settings
**Endpoint:** `GET /api/cpx/filter-settings`

**Description:** Retrieve saved filter preferences

**Headers:**
```
Authorization: <session_id>
```

**Response:**
```json
{
  "filters": {
    "min_loi": 5,
    "max_loi": 15,
    "min_payout": 2.5,
    "country": "US"
  }
}
```

---

### 4. Sync Active Status
**Endpoint:** `POST /api/cpx/sync-active-status`

**Description:** Apply filter settings to ALL surveys and mark as active/inactive

**Headers:**
```
Authorization: <session_id>
```

**Response:**
```json
{
  "activated": 45,
  "deactivated": 12,
  "total_surveys": 57,
  "message": "Active status synced based on filters"
}
```

---

### 5. Assign Traffic to Survey
**Endpoint:** `POST /api/cpx/assign-traffic`

**Description:** Assign traffic batch to a specific survey

**Headers:**
```
Authorization: <session_id>
Content-Type: application/json
```

**Request Body:**
```json
{
  "survey_id": "57572480",
  "batch_size": 100
}
```

**Response:**
```json
{
  "success": true,
  "assigned_count": 100,
  "survey_id": "57572480",
  "entry_links": [
    {
      "traffic_id": "507f1f77bcf86cd799439011",
      "entry_link": "https://click.cpx-research.com/...&ext_subid1=507f1f77bcf86cd799439011"
    }
  ]
}
```

---

### 6. WebSocket - Real-time Survey Updates
**Endpoint:** `WS /api/cpx/ws/surveys`

**Description:** WebSocket connection for real-time survey updates

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:8000/api/cpx/ws/surveys');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.type); // 'connected', 'surveys_update', 'heartbeat'
};
```

**Messages Received:**
```json
// Connection confirmation
{
  "type": "connected",
  "timestamp": "2026-02-04T15:30:00Z"
}

// Survey update
{
  "type": "surveys_update",
  "surveys": [...],
  "count": 25,
  "source": "fetch"
}

// Heartbeat (every 35 seconds)
{
  "type": "heartbeat",
  "timestamp": "2026-02-04T15:30:35Z"
}
```

**Messages Sent:**
```json
// Ping
{
  "type": "ping"
}
```

---

### 7. WebSocket Status
**Endpoint:** `GET /api/cpx/ws/status`

**Description:** Get WebSocket connection status

**Response:**
```json
{
  "available": true,
  "connected_clients": 5,
  "channel": "cpx_surveys"
}
```

---

## CPX API Router

### Base URL: `/cpx-api`

### 1. CPX Postback Handler (S2S)
**Endpoint:** `GET /cpx-postback`

**Description:** Server-to-Server postback from CPX when survey is completed

**Query Parameters:**
```typescript
{
  trans_id: string;          // Transaction ID (REQUIRED)
  status: number;            // 1=completed, 2=canceled/fraud (REQUIRED)
  amount_usd?: number;       // Payout in USD
  amount_local?: number;     // Payout in local currency
  subid?: string;            // Primary sub ID (SFWID)
  subid_2?: string;          // Secondary sub ID (trans_id)
  ip?: string;               // User IP address
  offer_id?: string;         // CPX survey ID
  hash?: string;             // Security hash: md5(trans_id + status + secret_key)
}
```

**Example URL:**
```
GET /cpx-postback?trans_id=abc123-def456&status=1&amount_usd=2.50&subid=507f1f77bcf86cd799439011&offer_id=57572480
```

**Response:**
```json
{
  "status": "ok"
}
```

**Status Codes:** Always returns HTTP 200 (required by CPX)

---

### 2. Response Page
**Endpoint:** `GET /cpx-api/response`

**Description:** User-facing landing page after survey completion

**Query Parameters:**
```typescript
{
  trans_id: string;          // Transaction ID
  status?: string;           // 'success' or 'failed'
  subid?: string;            // Sub ID
}
```

**Response:** HTML page with completion status

---

### 3. Survey Status Polling
**Endpoint:** `GET /cpx-api/survey-status`

**Description:** Frontend polls this to check if postback arrived

**Query Parameters:**
```typescript
{
  trans_id: string;          // Transaction ID to check
}
```

**Response:**
```json
{
  "trans_id": "abc123-def456",
  "status": "completed",     // 'pending', 'completed', 'canceled', 'fraud'
  "completed": true,
  "redirect_url": "/response?trans_id=abc123-def456&status=success",
  "poll_again": false,
  "poll_interval_ms": 2000,
  "message": "Survey completed"
}
```

---

### 4. Create Transaction
**Endpoint:** `POST /cpx-api/transaction/create`

**Description:** Pre-register transaction before user starts survey

**Query Parameters:**
```typescript
{
  trans_id: string;          // Transaction ID (REQUIRED)
  user_id?: string;          // User/Respondent ID
  subid?: string;            // Sub ID
  survey_id?: string;        // Survey ID
  vendor_id?: string;        // Vendor ID
  country_code?: string;     // Country code
}
```

**Response:**
```json
{
  "success": true,
  "trans_id": "abc123-def456",
  "message": "Transaction created"
}
```

---

### 5. Get Transaction
**Endpoint:** `GET /cpx-api/transaction/{trans_id}`

**Description:** Get transaction details

**Response:**
```json
{
  "_id": "507f1f77bcf86cd799439011",
  "trans_id": "abc123-def456",
  "status": "completed",
  "cpx_status": 1,
  "amount_usd": 2.50,
  "amount_local": 2.50,
  "subid": "507f1f77bcf86cd799439011",
  "survey_id": "57572480",
  "ip_address": "192.168.1.1",
  "created_at": "2026-02-04T15:00:00Z",
  "completed_at": "2026-02-04T15:10:00Z",
  "postback_count": 1
}
```

---

### 6. Get Postback Logs
**Endpoint:** `GET /cpx-api/api/cpx-postback-logs`

**Description:** Get postback logs for monitoring

**Query Parameters:**
```typescript
{
  limit?: number;            // Number of logs (default: 100)
  trans_id?: string;         // Filter by transaction ID
}
```

**Response:**
```json
{
  "logs": [
    {
      "trans_id": "abc123-def456",
      "status": 1,
      "amount": 2.50,
      "subid": "507f1f77bcf86cd799439011",
      "success": true,
      "message": "Processed",
      "timestamp": "2026-02-04T15:10:00Z",
      "vendor_result": {
        "status_code": 200,
        "forwarded": true
      }
    }
  ],
  "count": 1
}
```

---

## Traffic Flow Parser APIs

### Base URL: `/api`

### 1. Prefetch IP
**Endpoint:** `GET /api/prefetch-ip`

**Description:** Get client IP from server-side headers (called on page load BEFORE button click)

**Response:**
```json
{
  "ip": "192.168.1.100",
  "source": "CF-Connecting-IP",
  "userAgent": "Mozilla/5.0..."
}
```

**Called:** Automatically on page load (line 150 in TrafficFlowParser.jsx)

---

### 2. Store Traffic & Allocate Survey
**Endpoint:** `POST /api/store`

**Description:** Store traffic data and allocate survey (called WHEN "Next" button is clicked)

**Headers:**
```
Content-Type: application/json
```

**Request Body:**
```json
{
  "url": "https://surveyfieldwork.com/?vid=123&cc=US&rid=456789",
  "params": {
    "vid": "123",
    "cc": "US",
    "rid": "456789"
  },
  "userAgent": "Mozilla/5.0...",
  "clientIp": "192.168.1.100",
  "ipSource": "CF-Connecting-IP",
  "deviceFingerprint": "fp_a1b2c3d4...",
  "fingerprintComponents": {
    "userAgent": "Mozilla/5.0...",
    "language": "en-US",
    "platform": "Win32",
    "timeZone": "America/New_York",
    "screen": "1920x1080x24"
  },
  "fingerprintSource": "client",
  "trans_id": "abc123-def456"
}
```

**Response:**
```json
{
  "id": "507f1f77bcf86cd799439011",
  "type": "cpx",
  "allocation_success": true,
  "entry_link": "https://click.cpx-research.com/...?ext_subid1=507f1f77bcf86cd799439011&ext_subid2=abc123-def456",
  "survey_id": "57572480",
  "message": "Survey allocated successfully"
}
```

---

## Survey Pool APIs

### Base URL: `/survey-pool`

### 1. Sync Survey Pool
**Endpoint:** `POST /survey-pool/sync`

**Description:** Trigger survey pool synchronization

**Headers:**
```
Content-Type: application/json
```

**Response:**
```json
{
  "success": true,
  "surveys_synced": 45,
  "message": "Survey pool synced successfully"
}
```

---

## Data Models

### Survey Transaction Model
```typescript
interface SurveyTransaction {
  _id: ObjectId;
  trans_id: string;              // Unique transaction ID
  cpx_status: number;            // 1=completed, 2=canceled/fraud
  status: string;                // 'pending', 'completed', 'canceled', 'fraud'
  amount_usd?: number;           // Payout in USD
  amount_local?: number;         // Payout in local currency
  subid?: string;                // Primary sub ID (SFWID)
  subid_2?: string;              // Secondary sub ID
  survey_id?: string;            // CPX survey ID
  ip_address?: string;           // User IP
  callback_url?: string;         // Original postback URL
  created_at: Date;
  updated_at: Date;
  completed_at?: Date;
  last_postback_at?: Date;
  postback_count: number;        // Number of postbacks received
  postback_hash: string;         // For deduplication
}
```

### CPX Survey Model
```typescript
interface CPXSurvey {
  _id: ObjectId;
  survey_id: string;             // CPX survey ID
  name?: string;                 // Survey name
  loi: number;                   // Length of interview (minutes)
  cpi: number;                   // Cost per interview
  ir?: number;                   // Incidence rate (0-100)
  quota?: number;                // Available completes
  status: string;                // 'active', 'inactive'
  country?: string;              // Country code
  category?: string;             // Survey category
  is_active_in_pool: boolean;    // Active for traffic routing
  href?: string;                 // CPX click tracking URL
  raw_data?: object;             // Original CPX data
  created_at: Date;
  updated_at: Date;
}
```

### Traffic Record Model
```typescript
interface TrafficRecord {
  _id: ObjectId;
  url: string;                   // Full URL with params
  params: {
    vid: string;                 // Vendor ID
    cc: string;                  // Country code
    rid: string;                 // Respondent ID
  };
  userAgent: string;
  clientIp?: string;
  ipSource?: string;
  deviceFingerprint?: string;
  fingerprintComponents?: object;
  trans_id?: string;             // Transaction ID
  status: string;                // 'NEW', 'INCOMPLETE', 'COMPLETE'
  survey_id?: string;            // Assigned survey
  entry_link?: string;           // Generated entry URL
  created_at: Date;
  updated_at: Date;
}
```

### Postback Log Model
```typescript
interface PostbackLog {
  _id: ObjectId;
  trans_id: string;
  status: number;                // CPX status code
  amount?: number;
  subid?: string;
  success: boolean;
  message: string;
  vendor_result?: {
    status_code: number;
    forwarded: boolean;
    vendor_url?: string;
    response?: string;
  };
  timestamp: Date;
}
```

---

## API Call Flow (CPX Integration)

### Before "Next" Button Click:
1. **Page Load**
   - `GET /api/prefetch-ip` - Prefetch client IP (automatic, line 150 in TrafficFlowParser.jsx)

### When "Next" Button Clicked:
1. **Traffic Storage**
   - `POST /api/store` - Store traffic and allocate survey
   
2. **If No Survey Allocated:**
   - `POST /survey-pool/sync` - Sync survey pool
   - Retry `POST /api/store`

3. **Survey Redirect**
   - User redirected to CPX survey with entry_link
   - Entry link includes trans_id for tracking

4. **Survey Completion (Backend)**
   - CPX sends `GET /cpx-postback` with status
   - Transaction updated in database
   - Vendor postback forwarded

5. **Frontend Polling**
   - `GET /cpx-api/survey-status` - Poll every 5 seconds
   - Check if postback received

6. **Redirect to Response**
   - `GET /cpx-api/response` - Show completion page

---

## Status Codes

### CPX Status Codes:
- `1` = COMPLETED (successful survey completion)
- `2` = CANCELED / FRAUD (user left or flagged)

### Transaction Status:
- `pending` = Waiting for completion
- `completed` = Successfully completed
- `canceled` = User canceled
- `fraud` = Flagged as fraud

### Traffic Status:
- `NEW` = Just created, no survey assigned
- `INCOMPLETE` = Survey assigned, not completed
- `COMPLETE` = Survey completed

---

## Security

### Hash Validation:
CPX sends security hash: `md5(trans_id + status + secret_key)`

Example:
```javascript
const hash = md5(`abc123-def456${1}${CPX_SECRET_KEY}`);
```

### Authentication:
Most endpoints require session authentication via `Authorization` header.

---

## Error Handling

All endpoints return appropriate HTTP status codes:
- `200` = Success
- `400` = Bad request (missing parameters)
- `401` = Unauthorized (missing/invalid session)
- `404` = Not found
- `500` = Internal server error
- `503` = Service unavailable

**Exception:** `/cpx-postback` ALWAYS returns 200 to prevent CPX retries.

---

## Notes

1. **trans_id is the PRIMARY identifier** - Never use message_id
2. **Postback is single source of truth** - All status updates come from postback
3. **Idempotent postback handling** - Duplicate postbacks are ignored using hash
4. **Zero-delay IP prefetch** - IP is fetched on page load to avoid 3-9 second delay
5. **S2S vendor forwarding** - Postbacks are automatically forwarded to vendor servers

---

## Summary

The CPX integration consists of:
- **7 CPX router endpoints** for survey management and traffic assignment
- **6 CPX API endpoints** for transaction tracking and postbacks
- **2 traffic flow endpoints** for IP prefetch and survey allocation
- **1 survey pool endpoint** for synchronization
- **1 WebSocket endpoint** for real-time updates

**API called BEFORE button click:** `GET /api/prefetch-ip`

**APIs called WHEN button clicked:** `POST /api/store`, optionally `POST /survey-pool/sync`
