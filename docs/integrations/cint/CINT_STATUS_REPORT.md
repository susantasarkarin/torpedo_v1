# Cint Integration - Current Status Report
**Generated:** 2026-02-08 19:50 UTC

---

## ✅ FINDINGS

### 1. Production Server Status
**Server:** https://torpedo.cogentixresearch.com
**Status:** 🟢 ONLINE and responding

**Tested Endpoints:**
- ✅ `/api/cint/opportunities` - Returns empty list
- ✅ `/api/cint/subscription/opportunities` - Returns active subscription
- ❌ `/api/cint/diagnostic` - Not deployed yet (404)

---

### 2. Webhook Subscription Status
**Status:** 🟢 **ACTIVE**

```json
{
  "account": "2686",
  "supplier_code": "6777",
  "callback": "https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities",
  "send_interval_seconds": 15,
  "include_quotas": false,
  "countries": ["eng_us", "eng_gb", "eng_ca", "eng_au"],
  "max_survey_count": 1000,
  "payload_max_size_mb": 8
}
```

**✅ Configuration is correct!** Cint should be sending surveys every 15 seconds.

---

### 3. Survey Inventory Status
**Endpoint:** `GET /api/cint/opportunities`
**Result:**
```json
{
  "success": false,
  "count": 0,
  "opportunities": []
}
```

**❌ NO SURVEYS FOUND**

This indicates one of three scenarios:
1. **Cint has no surveys available** matching your filter criteria
2. **Webhooks are failing** to process/store surveys
3. **MongoDB connection issue** preventing storage

---

## 🔍 DIAGNOSIS

### Most Likely Issue: No Live Surveys Matching Criteria

Given that:
- ✅ Webhook subscription is active
- ✅ Server is responding
- ✅ Configuration looks correct
- ❌ No surveys returned

**Primary Hypothesis:** Cint may not have surveys currently available that match your criteria (eng_us/gb/ca/au, minimum payout).

**Secondary Hypothesis:** Webhooks are arriving but failing to store (need to check logs).

---

## 📋 ACTION ITEMS

### Priority 1: Deploy Code Updates ⚠️

The fixes and diagnostic tools I added are NOT deployed to production yet. You need to deploy:

**Files Modified:**
1. `backend/app/routers/cint.py` - Added `/diagnostic` endpoint + fixes
2. `backend/app/services/cint_service.py` - Added debug logging for entry links
3. `backend/app/integrations/cint_integration.py` - Already correct
4. `backend/main.py` - Already correct

**Deployment Steps:**
```bash
# 1. Pull your latest changes from git or copy files to server
cd /path/to/production/backend

# 2. Restart the application
# (Method depends on your deployment - systemd, supervisor, docker, etc.)
sudo systemctl restart torpedo-backend
# OR
supervisorctl restart torpedo
# OR
docker-compose restart backend
```

---

### Priority 2: Check Server Logs

Once deployed, check logs for:

```bash
# Check for webhook reception
tail -f /var/log/torpedo/backend.log | grep "Received opportunities webhook"

# Check for entry link creation
tail -f /var/log/torpedo/backend.log | grep "ENTRY LINK DEBUG"

# Check for errors
tail -f /var/log/torpedo/backend.log | grep -iE "error|exception"
```

**What to look for:**
- ✅ "Received opportunities webhook with X surveys" - Webhooks arriving
- ✅ "[ENTRY LINK DEBUG]" messages - Entry link processing details
- ❌ Error messages - Processing failures

---

### Priority 3: Run Diagnostic (After Deployment)

```bash
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic | python -m json.tool
```

This will tell you:
- How many surveys are in MongoDB
- How many entry links exist
- Whether live_link fields are populated
- Specific issues detected
- Recommended actions

---

### Priority 4: Contact Cint Support

If no surveys appear even after 24 hours:

**Email:** sheik.sikkander@cint.com, sushmita.sen@cint.com

**Information to provide:**
1. Your supplier code: **6777**
2. Webhook URL: https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities
3. Current filter settings (from subscription JSON above)
4. Question: "Are there any surveys available matching our criteria?"

Ask them to:
- Confirm surveys are being sent to your webhook
- Check if there are available surveys for eng_us/gb/ca/au
- Verify webhook delivery logs on their side

---

## 🛠️ TROUBLESHOOTING GUIDE

### Scenario A: Still No Surveys After Deployment

**Check:**
1. MongoDB connection - Can the server write to database?
2. Webhook logs - Are webhooks being received?
3. Processing errors - Are webhooks failing silently?

**Test webhook manually:**
```bash
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities" \
  -H "Content-Type: application/json" \
  -d '{
    "survey_id": 999999,
    "survey_name": "Test Survey",
    "is_live": true,
    "total_remaining": 100,
    "revenue_per_interview": {"value": 1.5, "currency_code": "USD"},
    "message_reason": "new"
  }'
```

If this works and creates a survey, the issue is with Cint delivery.

---

### Scenario B: Surveys Exist But No Entry Links

**Run:**
```bash
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/auto-create-entry-links?limit=50"
```

This will create entry links for all active surveys.

**Check logs for:**
```
[ENTRY LINK DEBUG] Cint API response for survey X
```

This shows the exact API response structure from Cint.

---

### Scenario C: Entry Links Exist But live_link is NULL

**Check logs for field name mismatch:**

If logs show:
```
[ENTRY LINK DEBUG] SupplierLink data keys: ['LiveLink', 'TestLink', ...]
[ENTRY LINK DEBUG] SupplierLink has live_link: False
```

This means Cint uses `LiveLink` (PascalCase) but model expects `live_link` (snake_case).

**Fix:** Update `backend/app/models/cint.py`:
```python
class SupplierLink(SupplierLinkBase):
    live_link: Optional[str] = Field(None, alias="LiveLink")
    test_link: Optional[str] = Field(None, alias="TestLink")

    class Config:
        populate_by_name = True
```

---

## 📊 CURRENT STATUS SUMMARY

| Component | Status | Notes |
|-----------|--------|-------|
| **Production Server** | 🟢 Online | Responding to requests |
| **Webhook Subscription** | 🟢 Active | Configured correctly (15s interval) |
| **Survey Inventory** | 🔴 Empty | 0 surveys in database |
| **Entry Links** | ⚠️ Unknown | Can't check without diagnostic endpoint |
| **Code Updates** | 🔴 Not Deployed | Fixes not in production |
| **Logs Access** | ❓ Unknown | Need server access to check |

---

## 🎯 IMMEDIATE NEXT STEPS

1. **Deploy updated code** to production server
2. **Restart backend application**
3. **Run diagnostic:** `curl .../api/cint/diagnostic`
4. **Check logs** for webhook activity
5. **Wait 24 hours** for survey accumulation
6. **Contact Cint** if still no surveys

---

## 📞 SUPPORT CONTACTS

**Cint Team:**
- Sheik Sikkander: sheik.sikkander@cint.com
- Sushmita Sen: sushmita.sen@cint.com

**Your Supplier Details:**
- Account: 2686
- Supplier Code: 6777
- Supplier Name: Cogentix Research Pvt Ltd - Feed

---

## ✅ CODE CHANGES SUMMARY

All critical fixes have been implemented in your local codebase:

1. ✅ Webhook error handling (returns HTTP 500 on failure)
2. ✅ Entry link 404 detection and reporting
3. ✅ Survey activity check before entry link creation
4. ✅ Diagnostic endpoint for troubleshooting
5. ✅ Enhanced logging for entry link API responses

**These just need to be deployed to see the benefits!**

---

**Report Generated:** 2026-02-08 19:50 UTC
**Status:** Awaiting deployment and log analysis
