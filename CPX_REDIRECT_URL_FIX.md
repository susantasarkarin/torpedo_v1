# CPX Integration Redirect URL Fix

## Overview
This document describes the fix for the CPX integration redirect URL to use the correct parameter format.

**Correct URL Format:**
```
https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}
```

## Problem Statement
The CPX redirect URL used for survey completion callbacks needs to be updated from the old format to use `message_id` and `subid_1` parameters instead of the legacy parameters.

## Solution

### Step 1: Run the Fix Script
Execute the provided Python script to automatically update the CPX vendor's redirect URLs:

```bash
# Make sure MONGO_URI environment variable is set
export MONGO_URI="mongodb://localhost:27017/"

# Run the fix script
python fix_cpx_redirect_url.py
```

The script will:
1. Connect to MongoDB
2. Locate the CPX vendor record
3. Update `completeRD` array with the correct URL
4. Update `terminateRD` array with the correct URL
5. Display before/after configuration

### Step 2: Verify the Update
After running the script, verify in MongoDB:

```javascript
// Connect to campaign_platform database
use campaign_platform;

// Find CPX vendor and check the URLs
db.vendors.findOne({vendorName: {$regex: "CPX", $options: "i"}})

// Expected output:
{
  "_id": ObjectId(...),
  "vendorName": "CPX Research",
  "vid": "cpx",
  "completeRD": ["https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"],
  "terminateRD": ["https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"],
  ...
}
```

## Technical Details

### CPX Callback Flow

When a respondent completes or terminates a CPX survey, the flow is:

1. **CPX Callback Request** arrives at the `/cpx-response` endpoint with:
   ```
   GET /cpx-response?message_id=complete&subid_1={traffic_record_id}
   ```

2. **Parameter Parsing** in [traffic.py](./backend/routers/traffic.py):
   - `message_id` or `msg`: Response type ("complete" or "out")
   - `subid_1` or `rid`: Traffic record ID (SFWID)

3. **Vendor Lookup** retrieves the CPX vendor document from MongoDB:
   - Finds vendor by `vid="cpx"`
   - Extracts `completeRD` or `terminateRD` URL array

4. **URL Construction**:
   - Takes the first URL from the array
   - Appends the original respondent ID (if needed)
   - Redirects the respondent to the vendor's callback URL

### Parameter Mapping

| Parameter | Purpose | From CPX | Stored In |
|-----------|---------|----------|-----------|
| `message_id` | Response status ("complete" or "out") | CPX callback | Traffic record |
| `subid_1` | SFWID (traffic record ObjectId) | Generated when traffic created | URL in CPX survey |
| `subid` | Alternative to `subid_1` | N/A | Vendor redirect URL |
| `rid` | Legacy respondent ID | CPX | Vendor redirect URL (if `vendorVariable=rid`) |

### Vendor Document Structure

```json
{
  "_id": ObjectId,
  "vendorName": "CPX Research",
  "vid": "cpx",
  "vendorType": "Panel",
  "status": "Active",
  "completeRD": [
    "https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"
  ],
  "terminateRD": [
    "https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"
  ],
  "quotaFullRD": [
    "https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"
  ],
  "vendorVariable": "rid",
  "created_at": ISODate,
  "updated_at": ISODate
}
```

## Files Modified

### New Files:
- `fix_cpx_redirect_url.py` - Automated script to update CPX vendor redirect URLs

### Files Referenced (No Changes Required):
- `backend/routers/traffic.py` - CPX callback handler (lines 170-370)
- `backend/main.py` - Vendor CRUD operations (lines 3200+)

## Testing the Fix

### Manual Testing Steps:

1. **Verify vendor configuration** in MongoDB
2. **Create a test traffic record** with CPX survey
3. **Generate survey URL** with the traffic record ID as `subid_1`
4. **Complete survey** - CPX will callback with `message_id=complete&subid_1={traffic_id}`
5. **Verify redirect** - Check that user is redirected to:
   ```
   https://torpedo.cogentixresearch.com/cpx-research?message_id=complete&subid={traffic_id}
   ```

### Test Survey URL Format:
```
https://offers.cpx-research.com/index.php?app_id={APP_ID}&ext_user_id={EXT_USER_ID}&secure_hash={HASH}&survey_id={SURVEY_ID}&subid_1={TRAFFIC_RECORD_ID}
```

## Rollback (If Needed)

If you need to revert to the old URL format:

```javascript
use campaign_platform;
db.vendors.updateOne(
  {vid: "cpx"},
  {$set: {
    "completeRD": ["[OLD_URL_HERE]"],
    "terminateRD": ["[OLD_URL_HERE]"],
    "updated_at": new Date()
  }}
)
```

## Parameters Explained

### `message_id` Parameter
- Values: `complete` (survey completed) or `out` (survey terminated/quit)
- Replaces deprecated `msg` parameter
- Indicates the survey outcome

### `subid_1` Parameter
- Contains the SFWID (traffic record MongoDB ObjectId)
- Primary identifier for tracking the respondent through the system
- Used to correlate callback with the original traffic record

### `subid` Parameter (in redirect URL)
- Placeholder in the vendor redirect URL
- Gets replaced with the actual SFWID value from `subid_1`
- Allows vendor to track which respondent completed the survey

## Configuration Summary

### Before Fix:
```
completeRD: [<old_format_url>]
terminateRD: [<old_format_url>]
```

### After Fix:
```
completeRD: ["https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"]
terminateRD: ["https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"]
```

## Support

For questions about this fix, refer to:
- CPX callback handler: `backend/routers/traffic.py` (lines 170-230)
- Vendor configuration: `backend/main.py` (lines 3200-3250)
- API documentation: `temp_api.json` (/cpx-response endpoint)
