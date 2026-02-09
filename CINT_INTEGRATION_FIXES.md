# Cint Integration - Issues & Fixes

## Current Status
Based on email correspondence, the Cint integration has the following status:

### ✅ Resolved Issues
1. **403 Authentication Errors** - Subscription working with correct API key
2. **404 Apache Proxy Errors** - Fixed by correcting proxy to preserve `/api` prefix
3. **Webhook Subscription** - Successfully created and active

### ❌ Outstanding Issues

## Issue 1: Entry Link 404 Errors for Inactive Surveys

**Problem:**
When trying to create entry links for surveys that are no longer active, Cint API returns 404. The current code doesn't properly handle this failure.

**Root Cause:**
- `cint_service.py:1136-1138` - Returns `{"success": False, "error": str(e)}` on HTTP errors
- `cint.py:316` - Checks `if not result:` which doesn't catch `{"success": False}` (dict is truthy)
- Result: No error is raised, entry link creation silently fails

**Fix Location:** `backend/app/routers/cint.py:316`

**Current Code:**
```python
if not result:
    raise HTTPException(status_code=404, detail=f"Failed to create entry link for survey {survey_id}")
```

**Fixed Code:**
```python
if not result or not result.get("success"):
    error_msg = result.get("error", "Unknown error") if result else "No response"
    status_code = result.get("status_code", 500) if result else 500
    raise HTTPException(status_code=status_code, detail=f"Failed to create entry link for survey {survey_id}: {error_msg}")
```

**Same Fix Needed:**
- `cint.py:356` - update_entry_link endpoint (same pattern)

---

## Issue 2: Webhook Endpoint Returns 200 on Errors

**Problem:**
When webhook processing fails, the endpoint returns HTTP 200 with `{"success": false}`. This causes Cint servers to think the webhook succeeded, stopping retries.

**Root Cause:**
`cint.py:178-181` returns JSON response instead of raising HTTP error

**Fix Location:** `backend/app/routers/cint.py:176-181`

**Current Code:**
```python
except Exception as e:
    logger.error(f"Error processing opportunities webhook: {str(e)}")
    return {
        "success": False,
```

**Fixed Code:**
```python
except Exception as e:
    logger.error(f"Error processing opportunities webhook: {str(e)}")
    raise HTTPException(
        status_code=500,
        detail=f"Failed to process webhook: {str(e)}"
    )
```

---

## Issue 3: Survey Activity Check Before Entry Link Creation

**Problem:**
No check to verify survey is still active before attempting to create entry links.

**Recommendation:**
Add validation in `auto_create_entry_links_for_all()` to skip inactive surveys.

**Fix Location:** `backend/app/routers/cint.py:372-414`

**Add Before Line 390:**
```python
# Skip if survey is not live
if not survey.get("is_live", False):
    logger.info(f"Skipping survey {survey_id} - not live")
    skipped += 1
    continue
```

---

## Configuration Verification

### Environment Variables Needed:
```bash
# Cint API Credentials (from email)
CINT_API_KEY=C61C48A6-8154-4F9F-B616-8DFB66F452A7
CINT_SUPPLIER_CODE=6777
CINT_ENVIRONMENT=production
CINT_WEBHOOK_SECRET=M7jTY9DGoXEC3AG8tAJ289l57U6e9hpT2q5xN7n88UbpiYInITVU35MHTFRB8520syiC4WQA7oS2LN90PRuD7

# Webhook URL (confirmed working)
CINT_WEBHOOK_CALLBACK_URL=https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities

# MongoDB
MONGO_URI=mongodb://localhost:27017/
```

### Webhook Subscription Config:
- **Callback URL:** https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities
- **Send Interval:** 30 seconds
- **Languages:** eng_us, eng_gb, eng_ca, eng_au
- **Include Quotas:** true

---

## Testing Checklist

### 1. Webhook Flow
- [ ] Verify webhook endpoint responds with 200 on success
- [ ] Verify webhook endpoint returns 500 on processing errors (not 200)
- [ ] Check MongoDB for new surveys being stored
- [ ] Monitor logs for "Received opportunities webhook" messages

### 2. Entry Link Creation
- [ ] Test creating entry link for ACTIVE survey (should succeed)
- [ ] Test creating entry link for INACTIVE survey (should return proper 404)
- [ ] Verify entry links are stored in MongoDB
- [ ] Check auto-create skips inactive surveys

### 3. End-to-End
- [ ] Confirm surveys appear in dashboard after webhook delivery
- [ ] Verify entry links are automatically created for new surveys
- [ ] Test respondent redirect flow through entry links

---

## Priority Order

1. **HIGH:** Fix webhook error handling (Issue 2) - Prevents lost survey data
2. **HIGH:** Fix entry link 404 handling (Issue 1) - Proper error messaging
3. **MEDIUM:** Add survey activity check (Issue 3) - Prevents unnecessary API calls

---

## Implementation Notes

- All fixes are in existing files, no new files needed
- Changes are backward compatible
- Focus on proper HTTP status codes for Cint retry logic
- Log all errors for debugging

---

## Support Contacts

**Cint Team:**
- Sheik Sikkander <sheik.sikkander@cint.com> - Senior Consultant
- Sushmita Sen <sushmita.sen@cint.com> - Senior Manager Platform Integrations

**Documentation:**
- API Docs: https://developer.lucidhq.com/
- Entry Links: https://developer.lucidhq.com/#entry-links
- Yield Management: https://support.lucidhq.com/s/article/Monetization-API-Yield-Management-Guide
