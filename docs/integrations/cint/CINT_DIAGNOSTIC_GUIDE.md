# Cint Integration - Diagnostic & Testing Guide

## Quick Diagnostic Check

Run this endpoint to check the current status of your Cint integration:

```bash
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic
```

This will tell you:
1. ✅ How many surveys are in the database
2. ✅ How many entry links have been created
3. ✅ Whether live_link field is populated
4. ✅ Current webhook subscription status
5. ✅ Specific issues and recommendations

---

## Question 1: Are Cint inventories getting downloaded?

### Check Method:

**Option A: Via Diagnostic Endpoint (Recommended)**
```bash
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic | jq '.surveys'
```

**Expected Output if Working:**
```json
{
  "total": 150,
  "active": 120,
  "live": 95,
  "collection_name": "cint_surveys",
  "samples": [ ... 5 sample surveys ... ]
}
```

**Output if NOT Working:**
```json
{
  "total": 0,
  "active": 0,
  "live": 0,
  "collection_name": "cint_surveys"
}
```

---

**Option B: Via MongoDB Direct Query**
```javascript
use cint_research

// Count total surveys
db.cint_surveys.countDocuments({})

// Count active surveys
db.cint_surveys.countDocuments({"is_live": true})

// See last 5 surveys received
db.cint_surveys.find().sort({created_at: -1}).limit(5)
```

---

### If No Surveys (total = 0):

**Possible Causes:**
1. Webhook subscription not active
2. Webhook URL not reachable by Cint servers
3. Webhook signature validation failing
4. Processing errors returning HTTP 500

**Solutions:**

**Step 1: Check Webhook Subscription**
```bash
curl https://torpedo.cogentixresearch.com/api/cint/subscription/opportunities
```

If subscription is inactive, create it:
```bash
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/subscription/opportunities" \
  -H "Content-Type: application/json" \
  -d '{
    "callback_url": "https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities",
    "include_quotas": true,
    "send_interval_seconds": 30,
    "opportunities_filters": [
      {
        "country_language": {"in": ["eng_us", "eng_gb", "eng_ca", "eng_au"]},
        "revenue_per_interview": {"gte": 1}
      }
    ]
  }'
```

**Step 2: Check Backend Logs**
```bash
# Look for webhook reception logs
tail -f /path/to/logs | grep "Received opportunities webhook"

# Look for errors
tail -f /path/to/logs | grep "Error processing opportunities"
```

**Step 3: Test Webhook URL Manually**
```bash
# Test if webhook endpoint is accessible
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities" \
  -H "Content-Type: application/json" \
  -d '[{"survey_id": 12345, "survey_name": "Test", "is_live": true}]'
```

---

## Question 2: Are entry links getting created?

### Check Method:

**Option A: Via Diagnostic Endpoint (Recommended)**
```bash
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic | jq '.entry_links'
```

**Expected Output if Working:**
```json
{
  "total": 120,
  "with_live_link": 120,
  "without_live_link": 0,
  "collection_name": "cint_entry_links",
  "samples": [
    {
      "survey_id": 123456,
      "live_link": "https://samplicio.us/s/default.aspx?SID=abc123&PID=",
      "test_link": "https://samplicio.us/s/default.aspx?SID=test456&SUMSTAT=1",
      "supplier_link_type_code": "OWS",
      "created_at": "2026-02-08T10:30:00"
    }
  ]
}
```

**Output if Entry Links Missing live_link:**
```json
{
  "total": 50,
  "with_live_link": 0,
  "without_live_link": 50,
  "collection_name": "cint_entry_links"
}
```

---

### If NO Entry Links (total = 0):

**Cause:** Auto-create is not running or surveys are not active.

**Solution:**
```bash
# Manually trigger auto-create for all active surveys
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/auto-create-entry-links?limit=100"
```

**Expected Response:**
```json
{
  "success": true,
  "created": 25,
  "skipped": 10,
  "errors": []
}
```

---

### If Entry Links Exist But live_link is NULL:

**This is the CRITICAL issue!**

**Possible Causes:**
1. Cint API response structure changed
2. API response uses different field names (e.g., `LiveLink` vs `live_link`)
3. API credentials don't have permission to generate entry links
4. Survey IDs are invalid/expired

**Diagnostic Steps:**

**Step 1: Check Backend Logs for Entry Link Creation**
```bash
tail -f /path/to/logs | grep "ENTRY LINK DEBUG"
```

You should see logs like:
```
[ENTRY LINK DEBUG] Cint API response for survey 123456: {"SupplierLink": {"LiveLink": "..."}}
[ENTRY LINK DEBUG] Response keys: ['SupplierLink', 'Status']
[ENTRY LINK DEBUG] SupplierLink data keys: ['LiveLink', 'TestLink', 'RPI', ...]
[ENTRY LINK DEBUG] SupplierLink has live_link: True
[ENTRY LINK DEBUG] Created SupplierLink object with live_link: https://...
```

**If you see:**
```
[ENTRY LINK DEBUG] No 'SupplierLink' key in response
```
→ API response structure changed. Check full response in logs.

---

**Step 2: Test Entry Link Creation Manually**
```bash
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/entry-links/123456" \
  -H "Content-Type: application/json" \
  -d '{
    "supplier_link_type_code": "OWS",
    "tracking_type_code": "NONE",
    "default_link": "https://surveyfieldwork.com/survey",
    "success_link": "https://torpedo.cogentixresearch.com/cint-response?status=complete&mid=[%MID%]",
    "failure_link": "https://torpedo.cogentixresearch.com/cint-response?status=terminate&mid=[%MID%]",
    "over_quota_link": "https://torpedo.cogentixresearch.com/cint-response?status=quota_full&mid=[%MID%]",
    "quality_termination_link": "https://torpedo.cogentixresearch.com/cint-response?status=quality_terminate&mid=[%MID%]"
  }'
```

**Replace 123456 with actual LIVE survey_id from diagnostic.**

**Expected Success:**
```json
{
  "success": true,
  "message": "Entry link created successfully",
  "data": {
    "success": true,
    "link": {
      "survey_id": 123456,
      "live_link": "https://samplicio.us/s/default.aspx?SID=abc123&PID=",
      "test_link": "https://samplicio.us/s/default.aspx?SID=test456&SUMSTAT=1",
      ...
    }
  }
}
```

**Expected Failure (404):**
```json
{
  "detail": "Survey 123456 not found or no longer active. Cannot create entry link."
}
```

---

**Step 3: Check Cint API Response Field Names**

The issue might be that Cint returns `LiveLink` (PascalCase) but our model expects `live_link` (snake_case).

**Check backend/app/models/cint.py - SupplierLink model:**

```python
class SupplierLink(SupplierLinkBase):
    # Generated by Cint
    live_link: Optional[str] = None  # ← This might need Field(alias="LiveLink")
    test_link: Optional[str] = None  # ← This might need Field(alias="TestLink")
```

**If Cint uses PascalCase, update model:**

```python
from pydantic import Field

class SupplierLink(SupplierLinkBase):
    live_link: Optional[str] = Field(None, alias="LiveLink")
    test_link: Optional[str] = Field(None, alias="TestLink")

    class Config:
        populate_by_name = True  # Allow both snake_case and PascalCase
```

---

## Common Issues & Solutions

### Issue 1: "0 surveys in database"
**Solution:** Create webhook subscription (see Question 1)

### Issue 2: "Entry links created but live_link is null"
**Solution:** Check logs for API response format, may need to update field aliases

### Issue 3: "Entry link creation returns 404"
**Solution:** Survey is no longer active. Only create links for `is_live: true` surveys

### Issue 4: "Webhook returns 500 error"
**Solution:** Check backend logs for exact error, likely MongoDB connection or processing issue

---

## Contact Cint Support

If issues persist after following this guide:

**Email:**
- Sheik Sikkander: sheik.sikkander@cint.com
- Sushmita Sen: sushmita.sen@cint.com

**Information to Provide:**
1. Output of `/api/cint/diagnostic` endpoint
2. Sample survey_id that exists in database
3. Error message when creating entry link for that survey_id
4. Backend logs showing `[ENTRY LINK DEBUG]` messages
5. Confirmation that webhook subscription is active

---

## Next Steps

1. **Run Diagnostic:** `curl https://torpedo.cogentixresearch.com/api/cint/diagnostic`
2. **Check Logs:** Look for `[ENTRY LINK DEBUG]` messages
3. **Test Entry Link Creation:** For one live survey from diagnostic
4. **Report Findings:** Share diagnostic output and logs

The enhanced logging will show us exactly what Cint API returns, allowing us to fix any field mapping issues.
