# CPX Integration Redirect URL - Before/After Examples

## 📊 Complete Parameter Flow Comparison

### BEFORE: Old Format
```
Survey Entry:
  URL: https://offers.cpx-research.com/index.php?...&sfwid=12345&rid=respondent_123
  Parameters: sfwid (traffic ID), rid (respondent ID)

CPX Callback:
  Request: /cpx-response?msg=complete&rid=respondent_123
  Parameters: msg (status), rid (respondent ID)

Vendor Redirect (OLD):
  URL: [old_format_with_different_parameters]
  Unknown parameter structure

Result:
  ❓ Unclear how parameters mapped
  ❓ Inconsistent naming (rid, sfwid, msg)
```

### AFTER: New Format
```
Survey Entry:
  URL: https://offers.cpx-research.com/index.php?...&subid_1=605d5c3c9a8f4e0001abcdef
  Parameters: subid_1 (traffic record ObjectId)

CPX Callback:
  Request: /cpx-response?message_id=complete&subid_1=605d5c3c9a8f4e0001abcdef
  Parameters: message_id (status), subid_1 (traffic record ID)

Vendor Redirect (NEW):
  Base URL: https://torpedo.cogentixresearch.com/cpx-research
  Template: ?message_id={message_id}&subid={subid_1}
  Final: https://torpedo.cogentixresearch.com/cpx-research?message_id=complete&subid=605d5c3c9a8f4e0001abcdef

Result:
  ✅ Clear, consistent parameter naming
  ✅ Direct mapping from callback to redirect
  ✅ Standardized URL structure
```

## 🔄 Detailed Parameter Transformation

### Parameter 1: Status/Message Type

**OLD**: `msg=complete` or `msg=out`
```
- msg=complete → Survey completed successfully
- msg=out → Survey terminated/quit by user
```

**NEW**: `message_id=complete` or `message_id=out`
```
- message_id=complete → Survey completed successfully
- message_id=out → Survey terminated/quit by user
```

**Mapping**: `msg` → `message_id` (same values, clearer naming)

---

### Parameter 2: Respondent/Traffic Identifier

**OLD**: Multiple options
```
Option A: rid=unique_respondent_id (CPX respondent ID)
Option B: sfwid=traffic_record_id (traffic ObjectId)
Option C: Mixed usage causing confusion
```

**NEW**: Unified approach
```
Single format: subid_1=traffic_record_id (MongoDB ObjectId)
- Standard across all references
- Directly identifies traffic record in system
- Enables proper deduplication
```

**Mapping**: `rid` (CPX ID) + `sfwid` (traffic ID) → `subid_1` (traffic ID)

---

## 📋 MongoDB Document Structure Comparison

### BEFORE
```json
{
  "_id": ObjectId("..."),
  "vendorName": "CPX Research",
  "completeRD": ["https://example.com/callback?..."],  // Format unclear
  "terminateRD": ["https://example.com/quit?..."],     // Format unclear
  "vendorVariable": "rid"                              // Legacy variable name
}
```

### AFTER
```json
{
  "_id": ObjectId("..."),
  "vendorName": "CPX Research",
  "completeRD": [
    "https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"
  ],
  "terminateRD": [
    "https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"
  ],
  "quotaFullRD": [
    "https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"
  ],
  "vendorVariable": "rid"
}
```

---

## 🔗 Complete Call Flow Examples

### Example 1: Survey Completion (Complete)

#### BEFORE
```
1. Traffic created: traffic_id = "5f3d8c2a1b9e4f0001abc123"
   
2. Survey URL built: 
   https://offers.cpx-research.com/index.php?...&sfwid=5f3d8c2a1b9e4f0001abc123
   
3. User completes survey
   
4. CPX calls back:
   GET /cpx-response?msg=complete&rid=respondent_789
   
5. System processes callback:
   ⚠️  Which ID is which? msg vs rid vs sfwid?
   ⚠️  How to correlate back to traffic?
   
6. Vendor redirect (?):
   GET https://vendor.example.com/callback?...
```

#### AFTER
```
1. Traffic created: traffic_id = "5f3d8c2a1b9e4f0001abc123"
   
2. Survey URL built: 
   https://offers.cpx-research.com/index.php?...&subid_1=5f3d8c2a1b9e4f0001abc123
   
3. User completes survey
   
4. CPX calls back:
   GET /cpx-response?message_id=complete&subid_1=5f3d8c2a1b9e4f0001abc123
   
5. System processes callback:
   ✅ message_id = "complete" → new_status = "COMPLETE"
   ✅ subid_1 = "5f3d8c2a1b9e4f0001abc123" → find traffic record
   
6. Vendor redirect:
   Base URL: https://torpedo.cogentixresearch.com/cpx-research
   Template: ?message_id={message_id}&subid={subid_1}
   Final: GET https://torpedo.cogentixresearch.com/cpx-research?message_id=complete&subid=5f3d8c2a1b9e4f0001abc123
```

---

### Example 2: Survey Termination (Out)

#### BEFORE
```
CPX calls back: GET /cpx-response?msg=out&rid=respondent_789
Vendor redirect: GET https://vendor.example.com/quit?... [unclear format]
```

#### AFTER
```
CPX calls back: GET /cpx-response?message_id=out&subid_1=5f3d8c2a1b9e4f0001abc123
Vendor redirect: GET https://torpedo.cogentixresearch.com/cpx-research?message_id=out&subid=5f3d8c2a1b9e4f0001abc123
```

---

## 📝 URL Template Expansion

### Template Components
```
Base:      https://torpedo.cogentixresearch.com/cpx-research
Params:    ?message_id={message_id}&subid={subid_1}
Variables: {message_id} and {subid_1}
```

### Expansion Examples

**Survey Complete**:
```
Input:  message_id=complete, subid_1=605d5c3c9a8f4e0001abcdef
Output: https://torpedo.cogentixresearch.com/cpx-research?message_id=complete&subid=605d5c3c9a8f4e0001abcdef
```

**Survey Terminated**:
```
Input:  message_id=out, subid_1=605d5c3c9a8f4e0001abcdef
Output: https://torpedo.cogentixresearch.com/cpx-research?message_id=out&subid=605d5c3c9a8f4e0001abcdef
```

**Quota Full**:
```
Input:  message_id=quota, subid_1=605d5c3c9a8f4e0001abcdef
Output: https://torpedo.cogentixresearch.com/cpx-research?message_id=quota&subid=605d5c3c9a8f4e0001abcdef
```

---

## 🧪 Testing Examples

### Test Case 1: Happy Path (Complete)

**Setup**:
```bash
# Create test traffic
traffic_id = "test_605d5c3c9a8f4e0001abcdef"

# Generate survey URL
survey_url = "https://offers.cpx-research.com/index.php?app_id=10754&ext_user_id=PANEL_88921&secure_hash=abc123&survey_id=57572480&subid_1=test_605d5c3c9a8f4e0001abcdef"
```

**Test Flow**:
```bash
1. User completes survey in CPX
2. CPX redirects to: /cpx-response?message_id=complete&subid_1=test_605d5c3c9a8f4e0001abcdef
3. System processes:
   - Status → COMPLETE
   - Fetch traffic record
   - Look up vendor
4. Expected redirect: https://torpedo.cogentixresearch.com/cpx-research?message_id=complete&subid=test_605d5c3c9a8f4e0001abcdef
5. User arrives at destination
```

**Verification**:
```javascript
// Check traffic record was updated
db.traffic.findOne({_id: "test_605d5c3c9a8f4e0001abcdef"})
// Should have status: "COMPLETE"

// Check callback log
db.cpx_callback_logs.findOne({traffic_id: "test_605d5c3c9a8f4e0001abcdef"})
// Should have success: true
```

---

### Test Case 2: Termination (Out)

**Test Flow**:
```bash
1. User quits survey in CPX (before completion)
2. CPX redirects to: /cpx-response?message_id=out&subid_1=test_605d5c3c9a8f4e0001abcdef
3. System processes:
   - Status → TERMINATED
   - Fetch traffic record
   - Look up vendor
4. Expected redirect: https://torpedo.cogentixresearch.com/cpx-research?message_id=out&subid=test_605d5c3c9a8f4e0001abcdef
5. User arrives at destination
```

---

## ✅ Validation Checklist

- [ ] **Parameter Naming**: `message_id` and `subid_1` used consistently
- [ ] **URL Structure**: Base URL is `https://torpedo.cogentixresearch.com/cpx-research`
- [ ] **Query String**: Format is `?message_id={message_id}&subid={subid_1}`
- [ ] **Placeholder Format**: Curly braces `{}` used for placeholders
- [ ] **Traffic Correlation**: All references use traffic ObjectId, not CPX respondent ID
- [ ] **Status Values**: `complete` and `out` are the two primary status values
- [ ] **MongoDB Update**: Both `completeRD` and `terminateRD` updated
- [ ] **Array Format**: URLs stored as arrays in MongoDB `[url]`
- [ ] **No Mixed Formats**: All instances use new format consistently

---

**Format Change Date**: 2025-01-03  
**Status**: Deprecated old format, Active new format
