# CPX Postback Redirect Logging Investigation - FINDINGS & RESOLUTION

## Root Cause Identified ✅

### **The Issue: Router Inclusion Order**

In `backend/main.py`:
- **OLD Line 627**: `app.include_router(traffic_router.router)` - Router registered with FastAPI
- **OLD Lines 690-706**: CPX collections injected into traffic router (cpx_callback_logs_collection, cpx_postback_logs_collection)

**THE PROBLEM:** The router was included BEFORE the CPX collections were injected!

When FastAPI processes `app.include_router()`, all route handlers are compiled and registered. If the global variable `cpx_callback_logs_collection` is `None` at that point, the handler's reference to that global is captured as `None`.

Later injections update the global variable, BUT the already-registered route handler still references the original `None` value in its closure/captured scope.

## Evidence

### Code Path Analysis Passed ✅
- ✅ CPX callback logs collection properly initialized
- ✅ Properly injected into traffic_router
- ✅ /cpx-response endpoint has complete logging code
- ✅ Error logging also implemented
- ✅ Field names match between postback (subid) and callback lookup
- ✅ Entire redirect flow is complete

### But Collection was not available when handler registered
```python
# OLD BROKEN CODE
# main.py line 627 - BEFORE CPX setup
app.include_router(traffic_router.router)

# main.py lines 690-706 - CPX setup happens AFTER (TOO LATE!)
cpx_callback_logs_collection = traffic_db["cpx_callback_logs"]
traffic_router.set_cpx_callback_logs_collection(cpx_callback_logs_collection)
```

## Solution ✅ IMPLEMENTED

Moved the CPX collection initialization and injection **BEFORE** the router is included:

```python
# NEW CORRECT CODE
# main.py lines 625-655 (BEFORE router inclusion)

# ============================================
# CPX Callback/Postback Collections (MUST be before router inclusion)
# ============================================
# Inject vendors collection into traffic router for CPX callback handling
try:
    traffic_router.set_vendors_collection(vendors_collection)
    print("✅ Vendors collection injected into traffic router")
except Exception as e:
    print(f"⚠️ Vendors collection injection issue: {e}")

# Initialize CPX callback logs collection and inject into traffic router
try:
    cpx_callback_logs_collection = traffic_db["cpx_callback_logs"]
    traffic_router.set_cpx_callback_logs_collection(cpx_callback_logs_collection)
    print("✅ CPX callback logs collection initialized")
except Exception as e:
    print(f"⚠️ CPX callback logs collection issue: {e}")

# Initialize CPX S2S postback logs collection for redirect verification
try:
    cpx_postback_logs_for_traffic = traffic_db["cpx_postback_logs"]
    traffic_router.set_cpx_postback_logs_collection(cpx_postback_logs_for_traffic)
    print("✅ CPX postback logs injected into traffic router for S2S verification")
except Exception as e:
    print(f"⚠️ CPX postback logs injection issue: {e}")

# NOW the router is included with all collections properly set
app.include_router(traffic_router.router)
```

## Changes Made

1. **File**: [backend/main.py](backend/main.py)
2. **Change 1**: Moved vendors collection injection before router inclusion (lines 625-630)
3. **Change 2**: Moved CPX callback logs collection setup before router inclusion (lines 632-637)
4. **Change 3**: Moved CPX postback logs collection setup before router inclusion (lines 639-645)
5. **Change 4**: Router now included AFTER all collections are injected (line 647)
6. **Cleanup**: Removed duplicate CPX setup blocks that were after the router inclusion

## Expected Outcome

Once the fix is deployed to production:

1. ✅ When `/cpx-response` endpoint is called, `cpx_callback_logs_collection` will be properly set
2. ✅ Log entries will be inserted into the database correctly
3. ✅ The discrepancy between postback logs (2 records) and callback logs (0 records) will be resolved
4. ✅ New CPX user redirects will be properly logged to `cpx_callback_logs` collection
5. ✅ Full redirect flow verification and logging will work end-to-end

## Deployment Instructions

1. Replace [backend/main.py](backend/main.py) with the updated version
2. Restart the backend service on the production VM
3. Verify startup logs show:
   - `✅ Vendors collection injected into traffic router`
   - `✅ CPX callback logs collection initialized`
   - `✅ CPX postback logs injected into traffic router for S2S verification`
   - `✅ Traffic router included` (or similar)
4. Test with a CPX user redirect to confirm logging works
5. Check `cpx_callback_logs` collection for new entries

## Verification Steps

```bash
# Check MongoDB for callback logs
mongo traffic_flow_db
db.cpx_callback_logs.find().pretty()

# Should see entries like:
# {
#   "_id": ObjectId(...),
#   "timestamp": ISODate("2026-01-31T..."),
#   "callback_key": "sfwid:COMPLETE:2026013113",
#   "callback_url": "/cpx-response?msg=complete&...",
#   "success": true,
#   ...
# }
```

