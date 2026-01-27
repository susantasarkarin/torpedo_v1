# Survey Pool Activation Fix - Summary

## Problem Statement
Users were being continuously redirected to a hardcoded Zoho survey URL (`https://survey.zohopublic.in/zs/lTCyZz?rid=xxx`) instead of being randomly allocated to active surveys from the survey pool.

## Root Cause
The survey allocation system in `backend/routers/traffic.py` queries for surveys with `is_active_in_pool: true`. However:

1. **Surveys downloaded but never activated**: CPX and CINT services download surveys and store them with `is_active_in_pool: false` by default
2. **No automatic activation**: The `SurveyActivationService.sync_and_activate_surveys()` method existed but was never being called automatically
3. **Empty pool = fallback URL**: When the query for active surveys returns 0 results, the frontend code (TrafficFlowParser.jsx line 72) falls back to the hardcoded Zoho URL

## Solution Implemented

### Core Fix: Automatic Survey Sync Background Job
Added a background job that automatically activates surveys by:
1. Evaluating all downloaded surveys against filter criteria
2. Marking eligible surveys as `is_active_in_pool: true`
3. Running every 10 minutes to keep the pool current
4. Running on startup for immediate activation

### Technical Implementation

#### File: `backend/main.py`

**1. New Background Job Function (line 1138-1167)**
```python
def background_survey_sync():
    """
    Background job to sync and activate surveys from CPX/CINT pools.
    Runs every 10 minutes to ensure surveys are properly activated.
    """
    try:
        print(f"🔄 [Survey Pool] Starting sync at {datetime.utcnow().isoformat()}")
        
        from app.services.activation_service import get_activation_service
        
        service = get_activation_service()
        stats = service.sync_and_activate_surveys()
        
        cpx_activated = stats.get("cpx_activated", 0)
        cint_activated = stats.get("cint_activated", 0)
        total_activated = cpx_activated + cint_activated
        
        if total_activated > 0:
            print(f"✅ [Survey Pool] Sync complete: {total_activated} surveys activated")
        else:
            print(f"ℹ️ [Survey Pool] Sync complete: No new surveys to activate")
            
    except Exception as e:
        print(f"❌ [Survey Pool] Sync failed: {str(e)}")
        traceback.print_exc()
```

**2. Scheduler Job in Startup Event (line 1438-1455)**
```python
# Survey Pool Sync & Activation (every 10 minutes)
try:
    if scheduler.running:
        scheduler.add_job(
            background_survey_sync,
            IntervalTrigger(seconds=600),  # Every 10 minutes
            id="survey_pool_sync",
            name="Survey Pool Sync & Activation",
            replace_existing=True
        )
        print("✅ Survey pool sync job scheduled (every 10 minutes)")
        
        # Run initial sync on startup (non-blocking)
        import threading
        threading.Thread(target=background_survey_sync, daemon=True).start()
        print("🚀 Initial survey pool sync scheduled (running in background)")
except Exception as e:
    print(f"⚠️ Could not schedule survey pool sync job: {e}")
```

### Filter Criteria
Surveys are activated if they meet ALL of these criteria:

| Criterion | Field Name | Default Threshold | Description |
|-----------|------------|------------------|-------------|
| **LOI** | `loi` / `length_of_interview` | ≤ 20 minutes | Survey must not be too long |
| **CPI** | `payout` / `cpi` | ≥ $1.00 USD | Survey must pay enough |
| **IR** | `conversion_rate` / `bid_incidence` | ≥ 5% | Survey must have sufficient incidence rate |
| **Status** | `live_link` / `is_live` | Must be live | Survey must be currently active |

### Flow Diagram
```
┌─────────────────────────────────────────────────────────────┐
│ Backend Startup                                             │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Scheduler Initialized                                       │
│ - Starts background_survey_sync() immediately (threading)   │
│ - Schedules job to run every 10 minutes                     │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ background_survey_sync() Executes                           │
│ 1. Gets SurveyActivationService instance                    │
│ 2. Calls sync_and_activate_surveys()                        │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ SurveyActivationService.sync_and_activate_surveys()         │
│ 1. Load filter settings from database                       │
│ 2. Query CPX surveys collection                             │
│ 3. Query CINT surveys collection                            │
│ 4. For each survey:                                         │
│    - Evaluate against filters (LOI, CPI, IR, Status)        │
│    - If eligible: set is_active_in_pool = true              │
│    - If not eligible: set is_active_in_pool = false         │
│ 5. Return activation statistics                             │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Database Updated                                            │
│ - cpx_research.cpx_surveys: {is_active_in_pool: true}       │
│ - cint_research.cint_surveys: {is_active_in_pool: true}     │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Traffic Allocation Can Now Succeed                          │
│ - Query finds surveys with is_active_in_pool: true          │
│ - Randomly selects one from pool                            │
│ - Returns entry_link to frontend                            │
│ - User redirected to random survey (NOT Zoho fallback)      │
└─────────────────────────────────────────────────────────────┘
```

## Files Changed
1. **backend/main.py** (52 lines added)
   - Added `background_survey_sync()` function
   - Added scheduler job in startup event

## Files Created
1. **test_survey_activation.py** (177 lines)
   - Unit tests for activation logic
   - 6 test scenarios covering all filter criteria
   - All tests passing ✅

2. **SURVEY_POOL_FIX_DEPLOYMENT.md** (252 lines)
   - Complete deployment guide
   - Troubleshooting procedures
   - API endpoint documentation

3. **SURVEY_POOL_FIX_SUMMARY.md** (this file)

## Testing Results
- ✅ Python syntax validation passed
- ✅ Unit tests passed (6/6)
- ✅ Code review completed (feedback addressed)
- ✅ Security scan passed (0 vulnerabilities)

## Deployment Steps
1. **Pull the changes** from this branch
2. **Restart the backend server** - the sync job will run automatically
3. **Verify in logs** - look for "✅ Survey pool sync job scheduled"
4. **Test allocation** - visit traffic page with `?vid=123&cc=US&rid=456789`

## Verification
After deployment, you should see in logs:
```
✅ Survey pool sync job scheduled (every 10 minutes)
🚀 Initial survey pool sync scheduled (running in background)
🔄 [Survey Pool] Starting sync at 2026-01-27T08:59:38.647Z
✅ [Survey Pool] Sync complete: 45 surveys activated (CPX: 30, CINT: 15)
```

## API Endpoints Available
- `POST /survey-pool/sync` - Manual sync trigger
- `GET /survey-pool/stats` - Get pool statistics
- `GET /survey-pool/active` - List active surveys
- `GET /survey-pool/filters` - Get filter settings
- `POST /survey-pool/filters` - Update filter settings

## Configuration
Filter settings are stored in: `torpedo_settings.app_settings` collection with ID `survey_filters`

Default values (if not configured):
```json
{
  "max_loi": 20,
  "min_cpi": 1.0,
  "min_ir": 5
}
```

## Impact
- ✅ **Users will now be randomly allocated** to active surveys from the pool
- ✅ **No more hardcoded Zoho redirect** (unless no surveys are available)
- ✅ **Automatic maintenance** - runs every 10 minutes
- ✅ **Quality control** - only activates surveys meeting quality thresholds

## Rollback Plan
If needed, disable by:
1. Comment out lines 1438-1455 in `backend/main.py`
2. Restart backend
3. Or manually deactivate surveys via MongoDB

## Support
For issues:
1. Check backend logs for sync job status
2. Use `GET /survey-pool/stats` to check pool status
3. Use `POST /survey-pool/sync` to manually trigger sync
4. Adjust filters if too strict via `POST /survey-pool/filters`

## Security Summary
✅ No security vulnerabilities detected by CodeQL scanner

## Next Steps
1. Deploy to production
2. Monitor logs for sync job execution
3. Verify user traffic is being allocated to random surveys
4. Adjust filter settings if needed based on available survey inventory
