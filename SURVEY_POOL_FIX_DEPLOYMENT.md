# Survey Pool Activation Fix - Deployment Guide

## Problem Fixed
Users were being continuously redirected to a hardcoded Zoho survey URL (`https://survey.zohopublic.in/zs/lTCyZz?rid=xxx`) instead of being randomly allocated to active surveys from the survey pool.

## Root Cause
The survey allocation system was failing because:
1. Surveys downloaded from CPX and CINT providers were stored with `is_active_in_pool: false` by default
2. The `SurveyActivationService.sync_and_activate_surveys()` method exists but was never being called automatically
3. Without active surveys in the pool, the allocation logic always failed and fell back to the hardcoded Zoho URL

## Solution Implemented

### 1. Automatic Survey Sync Background Job
Added a new background job `background_survey_sync()` that:
- Runs automatically every 10 minutes
- Evaluates all surveys against filter criteria (LOI, CPI, IR)
- Marks eligible surveys as `is_active_in_pool: true`
- Logs activation statistics

### 2. Startup Sync
- The sync job also runs immediately on application startup
- Ensures surveys are activated as soon as the backend starts

### 3. Filter Criteria
Surveys must meet these criteria to be activated:
- **LOI (Length of Interview)**: ≤ configured max (default: 20 minutes)
- **CPI (Cost Per Interview)**: ≥ configured min (default: $1.00)
- **IR (Incidence Rate)**: ≥ configured min (default: 5%)
- **Status**: Must be live/active (has entry link for CPX, is_live=true for CINT)

## Deployment Steps

### Option 1: Automatic (Recommended)
Simply restart the backend server. The sync job will run automatically on startup and every 10 minutes thereafter.

```bash
# Restart the backend service
sudo systemctl restart campaign-platform-backend
# Or if using PM2
pm2 restart backend
```

### Option 2: Manual Trigger (For Testing)
You can manually trigger a sync via the API endpoint:

```bash
# Trigger sync with default filters from database
curl -X POST http://localhost:8000/survey-pool/sync

# Or with custom filters
curl -X POST http://localhost:8000/survey-pool/sync \
  -H "Content-Type: application/json" \
  -d '{
    "max_loi": 30,
    "min_cpi": 0.75,
    "min_ir": 5
  }'
```

### Option 3: Check Current Status
Check the current pool statistics:

```bash
# Get pool stats
curl http://localhost:8000/survey-pool/stats

# Get active surveys
curl http://localhost:8000/survey-pool/active
```

## Verification

### 1. Check Logs
After deployment, check the backend logs for these messages:

```
✅ Survey pool sync job scheduled (every 10 minutes)
🚀 Initial survey pool sync scheduled (running in background)
🔄 [Survey Pool] Starting sync at 2026-01-27T08:59:38.647Z
✅ [Survey Pool] Sync complete: 45 surveys activated (CPX: 30, CINT: 15)
```

### 2. Monitor Survey Allocation
Test the traffic flow:
1. Visit the traffic entry page with parameters: `?vid=123&cc=US&rid=456789`
2. Click "Next"
3. You should be redirected to a random survey from the pool, NOT the hardcoded Zoho URL

### 3. Check Database
Verify surveys are activated in MongoDB:

```javascript
// CPX surveys
db.cpx_surveys.find({is_active_in_pool: true}).count()

// CINT surveys  
db.cint_surveys.find({is_active_in_pool: true}).count()
```

## Configuration

### Filter Settings
Filter settings are stored in MongoDB collection `torpedo_settings.app_settings` with ID `survey_filters`.

To update filters via API:

```bash
curl -X POST http://localhost:8000/survey-pool/filters \
  -H "Content-Type: application/json" \
  -d '{
    "max_loi": 25,
    "min_cpi": 1.25,
    "min_ir": 10
  }'
```

This will:
1. Save the new filter settings
2. Automatically trigger a re-sync with the new filters

### Default Values
If no filters are configured in the database:
- `max_loi`: 20 minutes
- `min_cpi`: $1.00 USD
- `min_ir`: 60% for CINT, 5% for CPX

## Troubleshooting

### No Surveys Being Activated
1. **Check if surveys exist in the database**:
   ```bash
   curl http://localhost:8000/survey-pool/stats
   ```

2. **Check filter settings**:
   ```bash
   curl http://localhost:8000/survey-pool/filters
   ```

3. **Check if filters are too strict**:
   - Lower `min_cpi` 
   - Increase `max_loi`
   - Lower `min_ir`

4. **Manually trigger sync**:
   ```bash
   curl -X POST http://localhost:8000/survey-pool/sync
   ```

### Still Redirecting to Zoho URL
1. **Verify surveys are active**: Check `/survey-pool/stats`
2. **Check survey allocation logs**: Look for "No active surveys available" message
3. **Verify country matching**: Ensure surveys exist for the requested country code
4. **Check entry links**: Ensure activated surveys have valid entry_link/live_link fields

### Background Job Not Running
1. Check if APScheduler is running in logs
2. Verify no exceptions during startup
3. Check system resources (memory, CPU)

## Rollback
If needed, you can disable the automatic sync:

1. Edit `backend/main.py`
2. Comment out the survey sync scheduler section (lines ~1420-1438)
3. Restart the backend

Or manually deactivate all surveys:
```bash
# Via MongoDB
db.cpx_surveys.updateMany({}, {$set: {is_active_in_pool: false}})
db.cint_surveys.updateMany({}, {$set: {is_active_in_pool: false}})
```

## Files Modified
- `backend/main.py`: Added `background_survey_sync()` function and scheduler job

## Files Created
- `test_survey_activation.py`: Test script to verify activation logic

## API Endpoints Used
- `POST /survey-pool/sync`: Trigger manual sync
- `GET /survey-pool/stats`: Get pool statistics
- `GET /survey-pool/active`: Get active surveys
- `GET /survey-pool/filters`: Get filter settings
- `POST /survey-pool/filters`: Update filter settings

## Support
For issues or questions, check:
1. Backend logs: `/var/log/campaign-platform/backend.log`
2. MongoDB collections: `cpx_research.cpx_surveys`, `cint_research.cint_surveys`
3. Settings collection: `torpedo_settings.app_settings`
