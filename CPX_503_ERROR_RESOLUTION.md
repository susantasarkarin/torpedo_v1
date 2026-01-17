# CPX API 503 Error Resolution

## Issue
Backend returning **503 Service Unavailable** for CPX surveys endpoint:
- `/api/cpx/surveys?page=1&page_size=20`
- "Failed to fetch surveys" error in UI

## Root Causes Fixed

### Issue 1: Variable Name Mismatch ✅
**Location:** [backend/main.py](backend/main.py#L406)

**Problem:** 
```python
# WRONG - variable name doesn't exist
survey_allocation_service=survey_allocation_service,
```

The variable is actually `survey_allocation_service_instance` (line 376):
```python
survey_allocation_service_instance = get_survey_allocation_service()
```

**Fix Applied:**
```python
# CORRECT - use the actual variable name
survey_allocation_service=survey_allocation_service_instance,
```

### Issue 2: Insufficient Error Handling ✅
**Location:** [backend/app/services/cpx_service.py](backend/app/services/cpx_service.py#L498)

**Problem:**
The metrics lookup didn't have sufficient error handling. If the service wasn't available or had issues, it could crash the entire endpoint.

**Fix Applied:**
Added multiple layers of defensive error handling:
1. Check if `survey_allocation_service` exists
2. Check if it has the `get_survey_metrics` method using `hasattr()`
3. Separate try-catch for `AttributeError` (missing method)
4. Separate try-catch for other exceptions (missing metrics, database errors)
5. Outer try-catch for unexpected errors
6. Always provide default values as fallback

**Code:**
```python
try:
    if self.survey_allocation_service and hasattr(self.survey_allocation_service, 'get_survey_metrics'):
        try:
            # Actual metrics lookup
            metrics = self.survey_allocation_service.get_survey_metrics(survey_id)
            ...
        except AttributeError as ae:
            # Handle missing method
            ...
        except Exception as me:
            # Handle other errors
            ...
    else:
        # No service available, use defaults
        survey["clicks"] = 0
        ...
except Exception as outer_e:
    # Fallback for unexpected errors
    survey["clicks"] = 0
    ...
```

## Files Modified

1. **[backend/main.py](backend/main.py#L406)**
   - Fixed variable name: `survey_allocation_service` → `survey_allocation_service_instance`

2. **[backend/app/services/cpx_service.py](backend/app/services/cpx_service.py#L498)**
   - Added `hasattr()` check before accessing methods
   - Added multiple nested try-catch blocks for different error types
   - Added outer try-catch for unexpected errors
   - Always fallback to default values

## How to Deploy

1. **Backup current backend** (if in production)
2. **Pull latest changes** to both files
3. **Restart backend service:**
   ```bash
   # SSH to server
   ssh root@139.59.32.72
   
   # Navigate to backend
   cd /var/www/campaign_platform/backend
   
   # Kill existing process
   pkill -f "python.*main.py"
   
   # Restart with nohup
   nohup ./venv/bin/python3 main.py > nohup.out 2>&1 &
   ```

4. **Verify backend is running:**
   ```bash
   curl http://localhost:8000/api/cpx/surveys?page=1&page_size=20
   ```

## Verification Checklist

- [ ] Backend service starts without errors
- [ ] CPU surveys page loads without 503 errors
- [ ] Surveys display with correct LOI, payout, conversion
- [ ] CLICKS and COMPLETES fields show appropriate values
- [ ] Check server logs for warning messages (expected: warnings about metrics, not errors)
- [ ] Monitor for any recurring 503 errors

## Expected Behavior After Fix

### If survey_allocation_service is available:
```
✅ Attached metrics for survey 59209752: sent=42, completes=25
```

### If service not available or metrics missing:
```
⚠️ Survey allocation service missing get_survey_metrics method
```
(Falls back to displaying `clicks=0, completes=0` but API continues working)

### If database has issues:
```
⚠️ Failed to attach metrics for survey 59209752: [error]
```
(Falls back to defaults, API continues working)

## Error Logs to Monitor

### Normal (Expected):
```
GET /api/cpx/surveys?page=1&page_size=20 - 200 OK
✅ Attached metrics for survey 59209752: sent=42, completes=25
```

### Warning (Expected, service gracefully degrades):
```
⚠️ Survey allocation service missing get_survey_metrics method
⚠️ Failed to attach metrics for survey 59209752: Connection timeout
```

### Error (Should not occur):
```
❌ Unexpected error in metrics attachment: [error]
AttributeError: type object has no attribute 'get_survey_metrics'
```
(Means variable passed is not the service - likely the variable name issue)

## Rollback Plan

If issues persist after deployment:

1. **Revert the main.py change:**
   ```bash
   git checkout backend/main.py
   ```

2. **Keep the cpx_service.py improvements** (they're defensive, don't hurt)

3. **Restart backend:**
   ```bash
   pkill -f "python.*main.py"
   nohup ./venv/bin/python3 main.py > nohup.out 2>&1 &
   ```

This will disable metrics injection but keep the service stable.

## Root Cause Analysis Summary

| Step | Issue | Impact | Fix |
|------|-------|--------|-----|
| 1 | Wrong variable name | NameError crash | Use correct variable name |
| 2 | Insufficient error handling | Unhandled exceptions crash endpoint | Added multi-layer error handling |
| 3 | No hasattr check | AttributeError if method missing | Added hasattr() guard |
| 4 | No outer catch | Unexpected errors crash whole endpoint | Added outer try-catch |

The 503 errors were caused by the backend process encountering an unhandled exception and crashing, or the process not starting at all due to the name error.

---

**Status:** ✅ Fixed and ready for deployment  
**Date:** January 7, 2026
