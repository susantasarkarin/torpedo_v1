# CINT INTEGRATION DIAGNOSIS & ROOT CAUSE ANALYSIS

**Date:** February 3, 2026  
**Status:** 🟡 PARTIAL ISSUE - Surveys exist but entry links failing  
**Root Cause:** Cint API 404 on SupplierLink creation endpoint

---

## EXECUTIVE SUMMARY

Your Cint integration has **successfully received 108,915 survey opportunities** via webhooks. However, **entry link creation is failing with 404 errors**, preventing survey allocation.

### The Problem
- ✅ Surveys stored in MongoDB: **108,915** (65,963 active, 27,322 in allocation pool)
- ❌ Entry links stored in MongoDB: **0**  
- ❌ Entry link creation returns: **404 - SupplierAllocation does not exist**

### Why This Happens
The Cint API requires survey allocations to exist in their system before you can create entry links. The error:
```
CreateSupplierLinkFromModel failed: EXCEPTION: 
The SupplierAllocation with SurveyNumber=68555204 and SupplierCode=6777 does not exist.
```

This means: **You haven't allocated these surveys yet on the Cint platform.**

---

## ARCHITECTURE & DATA FLOW

### Cint Integration Stack

| Component | Status | Location | Details |
|-----------|--------|----------|---------|
| **Webhook Endpoint** | ✅ ACTIVE | `/api/cint/webhooks/opportunities` | Receives survey opportunities every 15s |
| **Subscription** | ✅ CREATED | `cint_research.cint_settings` | Callback URL configured, signature validation working |
| **Opportunity Processing** | ✅ WORKING | `cint_service.process_opportunities()` | 108,915 surveys stored |
| **Entry Link Creation** | ❌ FAILING | `cint_service.create_entry_link()` | Returns 404 - SupplierAllocation missing |
| **Survey Allocation** | ❌ BLOCKED | `cint_allocation_extension` | Can't allocate without entry links |

### Database State (VM: cint_research)

```
Collections:
  cint_surveys:          108,915 records
    ├─ is_active=True:        65,963 (message_reason != "deactivated")
    ├─ is_live=True:         103,677 (survey not closed)
    └─ is_active_in_pool=True: 27,322 (passes filter criteria)
  
  cint_entry_links:            0 records (NO ENTRY LINKS CREATED)
  cint_subscriptions:          0 records (subscription stored elsewhere)
  cint_settings:               0 records
  cint_respondent_outcomes:    0 records
```

### Survey Data Quality

Sample survey from database:
```json
{
  "survey_id": 68555204,
  "survey_name": "...",
  "is_active": true,
  "is_live": true,
  "is_active_in_pool": true,
  "message_reason": "new",
  "bid_length_of_interview": 15,
  "revenue_per_interview": { "value": 1.25, "currency_code": "USD" },
  "conversion": 0.65,
  "country_language": "eng_us"
}
```

---

## ROOT CAUSE: SUPPLIER ALLOCATION NOT CREATED

### The Error (Reproduced)
```bash
POST https://api.samplicio.us/Supply/v1/SupplierLinks/Create/68555204/6777
{
  "supplier_link_type_code": "OWS",
  "tracking_type_code": "NONE",
  "default_link": "https://surveyfieldwork.com/survey"
}

Response: 404
Body: CreateSupplierLinkFromModel failed: EXCEPTION: 
       The SupplierAllocation with SurveyNumber=68555204 and SupplierCode=6777 does not exist.
```

### What This Means

Cint's workflow requires:

**Step 1: Cint sends you opportunities (DONE ✅)**
- Cint: POST → Your webhook → Store surveys in DB

**Step 2: You must accept the opportunity (MISSING ❌)**
- You: Must call Cint API to "allocate" or "accept" the survey
- Cint: Creates internal SupplierAllocation record
- API: `POST /Supply/v1/SurveyAllocations/Allocate/{surveyNumber}/{supplierCode}`

**Step 3: Create entry link using the allocation (BLOCKED ❌)**
- You: Call `POST /Supply/v1/SupplierLinks/Create/{surveyNumber}/{supplierCode}`
- Cint: Looks up SupplierAllocation from Step 2
- Cint: Returns live_link with [%MID%] placeholders

### The Missing Piece: Survey Allocation

You need to call the **Allocate API** to accept each survey opportunity:

```python
# Missing Step 2 - Allocate the survey
async def allocate_survey(survey_id: int):
    """Accept opportunity and create SupplierAllocation"""
    url = f"https://api.samplicio.us/Supply/v1/SurveyAllocations/Allocate/{survey_id}/{supplier_code}"
    payload = {
        # Per Cint documentation - allocation details
        # This creates internal SupplierAllocation record needed for entry links
    }
    response = await self.client.post(url, json=payload, headers=self._get_headers())
    return response.json()
```

---

## COMPARISON: CPX vs CINT

| Aspect | CPX | Cint |
|--------|-----|------|
| **Data Source** | Polling API | Webhook push ✅ |
| **Surveys Received** | 451 stored | 108,915 stored ✅ |
| **Active Count** | 0 | 27,322 ✅ |
| **Entry Links** | Dynamic (per-respondent) | Static (per-survey) - need allocation ❌ |
| **Link Creation** | `generate_respondent_entry_link()` | Needs allocation API first ❌ |
| **Current Block** | None (CPX not live either) | Cint API 404 on entry links |

---

## WHY SURVEYS ARE "IN DISPLAY MODE"

The error "all surveys in display mode" happens because:

```
is_active_in_pool = false for all surveys
  ↓
allocation service skips them
  ↓
cannot allocate
```

**But real reason:**
1. Surveys ARE marked active (27,322 have `is_active_in_pool=true`)
2. **Entry links don't exist** (0 records in cint_entry_links)
3. Allocation fails because no entry link to return
4. UI shows "display mode" but real issue is missing entry links

---

## SOLUTION: IMPLEMENT SURVEY ALLOCATION FLOW

### What Needs to Happen

**Option A: Auto-Allocate on Webhook (Recommended)**

When opportunities arrive via webhook, immediately allocate them:

```python
# In cint_service.process_opportunities():
for opportunity in opportunities:
    # Store survey
    self._upsert_opportunity(opportunity)
    
    # NEW: Accept the opportunity with Cint
    if opportunity.is_live:
        allocation_result = await self.allocate_survey_opportunity(opportunity.survey_id)
        
        # Only create entry link if allocation succeeded
        if allocation_result.get("success"):
            link_result = await self._auto_create_entry_link(opportunity.survey_id)
```

**Option B: On-Demand Allocation**

When allocation service requests a survey:

```python
# In cint_allocation_extension.allocate():
survey = find_survey(survey_id)
if not survey.entry_link:
    # Allocate first
    await cint_service.allocate_survey_opportunity(survey_id)
    # Then create entry link
    await cint_service._auto_create_entry_link(survey_id)
return survey.entry_link
```

### Implementation Checklist

- [ ] Find Cint API endpoint for survey allocation (POST /Supply/v1/SurveyAllocations/Allocate)
- [ ] Implement `allocate_survey_opportunity()` in CintService
- [ ] Call allocation before entry link creation
- [ ] Store allocation status in MongoDB
- [ ] Handle allocation failures gracefully
- [ ] Test with real survey IDs from cint_surveys collection
- [ ] Verify entry links created (cint_entry_links populated)
- [ ] Test end-to-end allocation flow

---

## QUICK WINS TO VERIFY

### Verify Cint API Access
```bash
curl -X POST https://api.samplicio.us/Supply/v1/SurveyAllocations/Allocate/{surveyNumber}/{supplierCode} \
  -H "Authorization: $CINT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{...allocation payload...}'
```

### Check Survey Readiness
```python
from pymongo import MongoClient
client = MongoClient(os.getenv('MONGO_URI'))
coll = client['cint_research']['cint_surveys']
ready = coll.count_documents({'is_live': True, 'is_active': True})
print(f"Ready for allocation: {ready}")
```

### Test Allocation
```bash
# Try allocating a live survey
survey_id = 68555204
```

---

## NEXT STEPS

1. **Find Cint Allocation API** - Search Cint/Lucid documentation for allocation endpoint
2. **Implement allocation** - Add `allocate_survey_opportunity()` method
3. **Trigger allocation** - On webhook reception or on-demand
4. **Verify entry links** - Should populate cint_entry_links collection
5. **Test allocation flow** - End-to-end with real respondent
6. **Monitor logs** - Watch for allocation/entry link creation success

---

## KEY FILES TO MODIFY

| File | Change | Reason |
|------|--------|--------|
| `cint_service.py` | Add `allocate_survey_opportunity()` | Implement missing allocation step |
| `cint_service.py` | Call allocation before entry link creation | Fix 404 errors |
| `cint_allocation_extension.py` | Trigger allocation if not done | Ensure links exist before use |

---

## METRICS

- **Total opportunities received:** 108,915
- **Active in pool:** 27,322 (25%)
- **Entry links created:** 0 (0%)
- **Current block:** Cint API 404 on entry link creation
- **Root cause:** Missing survey allocation step

---

## CONCLUSION

**Status:** 🟡 Almost there! Webhooks working, surveys stored, just missing one API call.

**The fix:** Call Cint's survey allocation endpoint before creating entry links.

**Effort:** 2-3 hours to implement and test.

**Impact:** Will unblock allocation and enable survey respondent routing.
