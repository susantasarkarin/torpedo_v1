# Cint Integration - Completion Summary

## Overview
The Cint integration has been reviewed and all critical issues identified from the email correspondence with Cint support have been resolved.

---

## Redirect Configuration (Cint Supplier Portal)

Redirects are managed in the **Cint Supplier Portal** under record **SR-0721**.

**DO NOT** send redirect URLs in API entry link creation calls - they are configured portal-side.

| Redirect Type | Base URL |
|---------------|----------|
| Complete | `https://torpedo.cogentixresearch.com/cint-response?status=complete&pid=[%PID%]&mid=[%MID%]&revenue=[%REVENUE%]` |
| Termination | `https://torpedo.cogentixresearch.com/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]` |
| Over Quota | `https://torpedo.cogentixresearch.com/cint-response?status=quota_full&pid=[%PID%]&mid=[%MID%]` |
| Quality Term | `https://torpedo.cogentixresearch.com/cint-response?status=quality_terminate&pid=[%PID%]&mid=[%MID%]` |

**Appended Parameters** (configured in portal): Survey ID (`[%RSFN%]`), demographics (AGE, GENDER, HHI, STATE, DMA, ETHNICITY, etc.), and status info (`[%InitialStatus%]`, `[%ClientStatus%]`).

---

## Issues Fixed

### ✅ Issue 1: Webhook Error Handling
**Problem:** Webhook endpoint returned HTTP 200 with `{"success": false}` on errors, preventing Cint retry logic.

**Fix Applied:** `backend/app/routers/cint.py:176-184`
- Changed error handling to raise `HTTPException(status_code=500)` instead of returning JSON
- Added traceback logging for debugging
- Cint servers will now properly retry on failures

**Impact:** Ensures no survey opportunities are lost due to temporary processing errors.

---

### ✅ Issue 2: Entry Link 404 Error Handling
**Problem:** When creating entry links for inactive surveys, 404 errors weren't properly detected or reported.

**Fixes Applied:**
1. **Create Entry Link:** `backend/app/routers/cint.py:319-334`
   - Checks `result.get("success")` instead of truthy check
   - Extracts `status_code` from service response
   - Returns proper 404 with clear message: "Survey not found or no longer active"

2. **Update Entry Link:** `backend/app/routers/cint.py:372-387`
   - Same pattern as create
   - Clear error messages for debugging

**Impact:** Provides clear feedback when attempting to create entry links for expired/inactive surveys.

---

### ✅ Issue 3: Survey Activity Check
**Problem:** Auto-create entry link function attempted to create links for all surveys, including inactive ones.

**Fix Applied:** `backend/app/routers/cint.py:412-431`
- Added `"is_live": True` filter to MongoDB query
- Added double-check before processing each survey
- Logs skipped surveys for monitoring

**Impact:** Reduces unnecessary API calls and prevents 404 errors during bulk operations.

---

### ✅ Issue 4: Entry Link Creation Improvements (2026-02-17)

**409 Conflict Handling**
- `create_entry_link()` now handles HTTP 409 (already exists) gracefully
- On 409: automatically fetches and returns existing entry link
- Ensures idempotency - calling create multiple times is safe

**Cache-First Flow Optimization**
- `_auto_create_entry_link()` now checks MongoDB cache before API call
- Validates cached entry link has valid `live_link` before returning
- Added `force_refresh` parameter to bypass cache when needed
- Supports `force_refresh=true` query param in `/survey-link/{survey_id}` endpoint

**Debug Logging**
- Downgraded `[ENTRY LINK DEBUG]` logs from `info` to `debug` level
- Reduces log noise in production while keeping debug capability

**Impact:** Improved idempotency, reduced redundant API calls, cleaner logs.

---

## Configuration Verified

### Environment Variables (.env)
```bash
# Cint API Credentials (from support email)
CINT_API_KEY=C61C48A6-8154-4F9F-B616-8DFB66F452A7
CINT_SUPPLIER_CODE=6777
CINT_ENVIRONMENT=production
CINT_WEBHOOK_SECRET=M7jTY9DGoXEC3AG8tAJ289l57U6e9hpT2q5xN7n88UbpiYInITVU35MHTFRB8520syiC4WQA7oS2LN90PRuD7

# Webhook Configuration (confirmed working with Cint team)
CINT_WEBHOOK_CALLBACK_URL=https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities

# MongoDB
MONGO_URI=mongodb://localhost:27017/
```

### Current Webhook Subscription Settings
- **Callback URL:** https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities
- **Send Interval:** 30 seconds
- **Languages:** eng_us, eng_gb, eng_ca, eng_au
- **Include Quotas:** true
- **Status:** Active ✅

---

## API Endpoints Available

### Webhook Endpoints
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/cint/webhooks/opportunities` | Receive survey opportunities from Cint |
| POST | `/api/cint/webhooks/respondent-outcomes` | Receive completion/termination status |

### Survey Management
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/cint/opportunities` | List cached survey opportunities |
| GET | `/api/cint/opportunities/{survey_id}` | Get specific survey details |
| POST | `/api/cint/opportunities/refresh` | Manually sync surveys (fallback) |

### Entry Link Management
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/cint/entry-links/{survey_id}` | Create entry link for survey |
| PUT | `/api/cint/entry-links/{survey_id}` | Update entry link |
| GET | `/api/cint/entry-links/{survey_id}` | Get entry link details |
| POST | `/api/cint/auto-create-entry-links` | Bulk create for active surveys |

### Subscription Management
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/cint/subscription/opportunities` | Create/update webhook subscription |
| GET | `/api/cint/subscription/opportunities` | Get subscription status |
| DELETE | `/api/cint/subscription/opportunities` | Delete subscription |

---

## Testing Guide

### 1. Verify Webhook Reception
```bash
# Check backend logs for incoming webhooks
tail -f /path/to/backend/logs

# Look for:
# "Received opportunities webhook with X surveys"
# "CINT WEBHOOK DEBUG - Raw payload keys: ..."
```

**Expected Behavior:**
- Webhooks arrive every 30 seconds
- Surveys are stored in MongoDB `cint_research.cint_surveys`
- WebSocket clients receive broadcasts (if enabled)

---

### 2. Test Entry Link Creation

#### For Active Survey:
```bash
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/entry-links/123456" \
  -H "Content-Type: application/json" \
  -d '{
    "supplier_link_type_code": "OWS",
    "tracking_type_code": "NONE",
    "complete_url": "https://surveyfieldwork.com/complete",
    "terminate_url": "https://surveyfieldwork.com/terminate",
    "overquota_url": "https://surveyfieldwork.com/overquota",
    "quality_term_url": "https://surveyfieldwork.com/quality-term"
  }'
```

**Expected:** 200 OK with `live_link` and `test_link`

#### For Inactive Survey:
```bash
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/entry-links/999999" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

**Expected:** 404 with message: "Survey 999999 not found or no longer active"

---

### 3. Test Auto-Create Entry Links
```bash
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/auto-create-entry-links?limit=50"
```

**Expected Response:**
```json
{
  "success": true,
  "created": 25,
  "skipped": 20,
  "errors": []
}
```

**Verification:**
- Only `is_live: true` surveys are processed
- Check logs for "Skipping survey X - not live"

---

### 4. Verify MongoDB Storage

```javascript
// Connect to MongoDB
use cint_research

// Count surveys received
db.cint_surveys.countDocuments({})

// Count active surveys
db.cint_surveys.countDocuments({"is_active": true, "is_live": true})

// Check entry links created
db.cint_entry_links.countDocuments({})

// Sample survey document
db.cint_surveys.findOne()
```

---

### 5. End-to-End User Flow

1. **Survey Opportunity Arrives** → Webhook receives opportunity
2. **Survey Cached** → Stored in MongoDB with `is_live: true`
3. **Entry Link Created** → Auto-created or manually via API
4. **User Redirect** → User clicks survey → Redirected to `live_link`
5. **Completion Tracked** → Outcome webhook received with status

---

## Monitoring & Logs

### Key Log Messages to Watch

✅ **Success Indicators:**
```
"✅ Cint integration active (Supplier Code: 6777)"
"Received opportunities webhook with X surveys"
"Entry link created for survey X"
"Opportunities processed successfully"
```

⚠️ **Warning Signs:**
```
"Invalid webhook signature"
"Failed to create entry link: 404"
"Survey X not found or no longer active"
"Error processing opportunities webhook"
```

---

## MongoDB Collections

### cint_research.cint_surveys
Stores survey opportunities from webhooks.

**Key Fields:**
- `survey_id` - Unique survey identifier
- `is_live` - Whether survey is accepting responses
- `is_active` - Internal active status
- `total_remaining` - Quota remaining
- `revenue_per_interview` - Payout amount
- `length_of_interview` - LOI in minutes
- `country_language` - Target locale (e.g., "eng_us")

### cint_research.cint_entry_links
Stores entry links for redirecting respondents.

**Key Fields:**
- `survey_id` - Links to survey
- `live_link` - Production URL with PID parameter
- `test_link` - Test URL for validation
- `rpi` - Revenue per interview

---

## Known Limitations & Recommendations

### 1. Survey Status Changes
**Limitation:** Surveys can become inactive between webhook delivery and entry link creation.

**Recommendation:** Always check `is_live` status before routing users.

### 2. Webhook Delivery Lag
**Limitation:** 30-second interval means surveys may not appear instantly.

**Recommendation:** Display "Refreshing surveys..." message in UI during webhook wait periods.

### 3. Entry Link 404 Handling
**Limitation:** Cint API returns 404 for expired surveys with no additional details.

**Recommendation:** Implemented proper error messages to distinguish between survey not found vs.survey expired.

---

## Support Escalation

If issues persist after applying these fixes:

1. **Check Logs First** - Backend logs will show exact API responses
2. **Verify Credentials** - Ensure API key and supplier code match email
3. **Test Webhook URL** - Confirm https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities is accessible
4. **Contact Cint Support:**
   - Sheik Sikkander: sheik.sikkander@cint.com
   - Sushmita Sen: sushmita.sen@cint.com
   - Include: Survey ID, error message, timestamp

---

## Next Steps (Optional Enhancements)

### 1. Add Retry Logic for Failed Entry Links
Implement automatic retry with exponential backoff for transient API errors.

### 2. Survey Health Dashboard
Create admin view showing:
- Active surveys count
- Entry links created
- Webhook delivery status
- API error rates

### 3. Webhook Signature Validation
Currently optional - enforce HMAC signature validation in production.

### 4. Rate Limiting
Monitor API usage and implement rate limiting if approaching Cint API limits.

---

## Summary

**All critical issues from email correspondence have been resolved:**
- ✅ Webhook endpoint properly handles errors (HTTP 500 vs 200)
- ✅ Entry link 404 errors are detected and reported correctly
- ✅ Auto-create only processes live surveys
- ✅ Clear error messages for debugging
- ✅ Configuration verified with Cint team

**Integration Status:** Ready for production testing with live survey traffic.

**Last Updated:** 2026-02-08
