# Why Are There So Many INCOMPLETE Records?

## Quick Answer

Your INCOMPLETE records have **no assigned survey ID** because **survey allocation is failing**. The system tries to allocate surveys from CPX and CINT, but both providers are returning failures for various reasons.

## What the Data Shows

From your provided records (2/17/2026, 2:03 PM - 4:04 PM):

| Field | Observation | Meaning |
|-------|------------|---------|
| **Survey ID** | All show "—" (NULL) | No survey was allocated |
| **Status** | All show "INCOMPLETE" | Allocation process didn't complete |
| **Respondent ID** | Many duplicates | Users are retrying multiple times |
| **Countries** | UK and IN only | Limited geographic scope |
| **Vendor ID** | All 4738 | Single vendor experiencing issues |

## Root Causes (Likely Scenarios)

### 1. **No Surveys Available** (Most Likely)
- Neither CPX nor CINT have matching surveys for your users
- Possible reasons:
  - Survey inventory depleted for UK/IN countries
  - Surveys closed or quota-filled
  - User demographics don't match available surveys
  - Time of day issues (surveys may be paused)

### 2. **WebView Blocking** (Common)
- Users clicking links from in-app browsers (Facebook, Instagram, LinkedIn)
- CPX blocks WebView traffic to prevent fraud
- This is legitimate fraud prevention, but affects real users

### 3. **Entry Guard Blocks** (Fraud Prevention)
- Same user trying multiple times rapidly
- IP-based duplicate detection
- Device fingerprint matching
- This explains the duplicate Respondent IDs you're seeing

### 4. **API/Configuration Issues**
- CPX or CINT service temporarily down
- API credentials expired or invalid
- Network connectivity problems
- Rate limiting from providers

### 5. **Geographic Limitations**
- Limited survey inventory for India (IN) and UK
- Country-specific survey availability issues
- Time zone mismatches

## How to Diagnose

### Step 1: Check Current Failure Patterns
After deploying the fix, run:
```bash
python3 analyze_incompletes.py
```

This will show you the **exact breakdown** of why allocations are failing:
```
📌 Allocation Failure Reasons:
  No active CINT surveys for country: in        45 (37.5%)
  WebView blocked: FB_IAB                       30 (25.0%)
  Entry guard block: duplicate_attempt          20 (16.7%)
  CPX service not available                     15 (12.5%)
  ...
```

### Step 2: Query MongoDB Directly
```javascript
// Check failure reasons for recent records
db.url_parameters.aggregate([
  {
    $match: {
      status: "INCOMPLETE",
      assignedSurveyId: null,
      createdAt: { $gte: new Date("2026-02-17") }
    }
  },
  {
    $group: {
      _id: "$allocationFailureReason",
      count: { $sum: 1 }
    }
  },
  { $sort: { count: -1 } }
])
```

### Step 3: Check Survey Inventory
```javascript
// Check active CPX surveys for UK/IN
db.cpx_surveys.countDocuments({ 
  is_active: true,
  country_code: { $in: ["UK", "IN"] }
})

// Check active CINT surveys for UK/IN
db.cint_surveys.countDocuments({ 
  is_active_in_pool: true,
  country_language: { $in: [/eng_gb$/, /eng_in$/] }
})
```

## Immediate Actions to Reduce INCOMPLETE Rates

### 1. **Increase Survey Inventory** (If inventory is low)
- Add more CPX surveys for UK/IN
- Activate more CINT surveys
- Consider expanding to more countries

### 2. **Handle WebView Users Better** (If WebView blocking is high)
- Show message: "Please open this link in your default browser"
- Provide fallback survey options
- Consider relaxing WebView restrictions (with fraud monitoring)

### 3. **Adjust Entry Guard Settings** (If blocking legitimate users)
- Review duplicate detection thresholds
- Increase time window between retries
- Whitelist known-good IPs/users

### 4. **Add Retry Logic** (For temporary failures)
- Implement automatic retry after 30 seconds
- Exponential backoff for API errors
- Cache survey inventory to reduce API calls

### 5. **Improve User Communication**
- Show specific error messages instead of generic "no surveys"
- Suggest best times to return
- Offer email notifications when surveys become available

## What the Fix Does

The implemented solution adds **diagnostic tracking** so you can:

1. ✅ **See exactly why each allocation fails**
   - Provider name (CPX/CINT)
   - Specific failure reason
   - Timestamp of each attempt

2. ✅ **Identify patterns over time**
   - Which failure reasons are most common
   - Which providers have better success rates
   - Peak failure times

3. ✅ **Make data-driven decisions**
   - Should you get more surveys?
   - Should you adjust fraud settings?
   - Should you add more providers?

## Expected Results After Fix

### Before (Your Current State)
```
Status: INCOMPLETE
Survey ID: —
Failure Reason: (unknown)
```

### After (With New Tracking)
```
Status: INCOMPLETE
Survey ID: —
Failure Reason: "No active CINT surveys for country: in"
Allocation Attempts:
  ❌ CPX: WebView blocked: FB_IAB
  ❌ CINT: No active CINT surveys for country: in
```

Now you can:
- **Prioritize fixes** based on most common failures
- **Monitor improvements** as you make changes
- **Predict issues** before they become critical

## Next Steps

1. **Deploy the fix** to start collecting failure data
2. **Run analysis** after 24 hours to see patterns
3. **Address top 3 failure reasons** based on actual data
4. **Monitor daily** until INCOMPLETE rate drops to acceptable level (<20%)

## Questions to Answer (After Data Collection)

1. **What % are WebView blocks?** → Consider user education or relaxing rules
2. **What % are "no surveys"?** → Need more inventory for UK/IN
3. **What % are duplicate blocks?** → Adjust entry guard thresholds
4. **What % are API errors?** → Check provider status and credentials
5. **Are there time patterns?** → Adjust survey scheduling

## Success Metrics

Track these weekly:
- **Allocation Success Rate**: Target >80%
- **INCOMPLETE Rate**: Target <20%
- **Top Failure Reason**: Should not exceed 30% of failures
- **Provider Balance**: CPX vs CINT should be roughly equal

---

**Bottom Line**: Your INCOMPLETE records are caused by survey allocation failures. With the new tracking, you can now diagnose exactly why and take targeted action to fix it.
