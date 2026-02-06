# CPX Integration Fix - Comprehensive Implementation Report

## Executive Summary

This document details the comprehensive fix for the CPX Research integration that was rejecting 100% of traffic. The root causes were:
1. **Identity Reuse**: Same `ext_user_id` being used multiple times
2. **Redirect Loops**: Multiple redirects to same survey href
3. **WebView Traffic**: CPX blocks WebView traffic
4. **Wrong URL**: Using `href_new` instead of `href`

## Implemented Fixes

### TASK 1 & 2: Audit and Flow Mapping (READ ONLY)
**Status**: ✅ Completed

Mapped the complete CPX entry flow:
```
Frontend (TrafficFlowParser.jsx)
    ↓ POST /api/store
Backend (traffic.py)
    ↓ create SFWID
    ↓ call cpx_service.fetch_and_allocate_for_respondent()
CPX API (cpx_service.py)
    ↓ GET https://offers.cpx-research.com/index.php
    ↓ with ext_user_id=SFWID, subid_1=SFWID
    ↓ returns href (entry link)
Backend returns entry_link
    ↓
Frontend redirects to href
```

### TASK 3: Single-Use ext_user_id Guard
**Status**: ✅ Completed

**Files Modified**:
- [backend/main.py](backend/main.py) - Added `cpx_entry_guards` collection setup
- [backend/routers/traffic.py](backend/routers/traffic.py) - Added guard functions

**Implementation**:
```python
# New MongoDB collection: traffic_db.cpx_entry_guards
{
    "ext_user_id": "SFWID_12345",
    "status": "CREATED" | "REDIRECTED" | "LOCKED",
    "created_at": ISODate(),
    "client_ip": "1.2.3.4",
    "user_agent": "Mozilla/5.0...",
    "survey_id": "12345",
    "entry_link": "https://click.cpx-research.com/...",
    "duplicate_attempt_count": 0,
    "duplicate_attempts": []
}
```

**Guard Flow**:
1. When `/api/store` receives a request, check if `ext_user_id` exists in guards
2. If exists → BLOCK (return existing status)
3. If new → Register with status `CREATED`
4. After successful allocation → Update to `REDIRECTED`
5. On error or API failure → Update to `LOCKED`

### TASK 4: Lock CPX Redirects One-Time
**Status**: ✅ Completed

**Files Modified**:
- [backend/routers/traffic.py](backend/routers/traffic.py)

**Implementation**:
- Status transitions: `CREATED` → `REDIRECTED` → `LOCKED`
- Once redirected, the ext_user_id is locked for that survey
- Prevents retry loops that cause CPX to reject with `already_clicked`

### TASK 5: Block WebView Traffic
**Status**: ✅ Completed

**Files Modified**:
- [backend/routers/traffic.py](backend/routers/traffic.py)

**Implementation**:
```python
WEBVIEW_SIGNATURES = [
    "wv",           # Android WebView generic marker
    "webview",      # Generic WebView
    "fbav",         # Facebook App WebView
    "fban",         # Facebook App Native
    "instagram",    # Instagram WebView
    "twitter",      # Twitter WebView
    "line/",        # LINE app
    "kakaotalk",    # KakaoTalk app
    "timebucks",    # TimeBucks app (specific to CPX)
    ";wv)",         # Android WebView pattern
    "micromessenger",  # WeChat
    "snapchat",     # Snapchat
    "tiktok",       # TikTok
]

def is_webview_user_agent(user_agent: str) -> tuple:
    # Returns (is_webview: bool, detected_signature: str)
```

**Flow**:
1. Check user agent before CPX API call
2. If WebView detected → Block immediately (no API call)
3. Log the blocked attempt for monitoring

### TASK 6: Switch to href (NOT href_new)
**Status**: ✅ Completed

**Files Modified**:
- [backend/app/services/cpx_service.py](backend/app/services/cpx_service.py) - 5 locations

**Changes**:
```python
# BEFORE (WRONG):
href = survey.get("href_new") or survey.get("href") or ""

# AFTER (CORRECT):
href = survey.get("href") or ""
```

**Locations Fixed**:
1. Line ~316 - Cache lookup
2. Line ~799 - Filter check
3. Line ~822 - Selection
4. Line ~938 - live_link generation
5. Line ~1136 - raw_data extraction

### TASK 7: secure_hash & Parameter Hygiene
**Status**: ✅ Completed (Already Implemented)

The API call already includes all required parameters:
```python
params = {
    "app_id": self.app_id,
    "ext_user_id": internal_tracking_id,
    "subid_1": internal_tracking_id,
    "subid_2": "",
    "output_method": "api",
    "ip_user": user_ip,
    "user_agent": user_agent,
    "limit": self.fetch_limit,
    "secure_hash": secure_hash,  # ✅ MD5(ext_user_id + "-" + secure_hash_key)
    "user_country_code": country_iso2,  # ✅ ISO2 format
}
```

### TASK 8: Frontend Click Safety
**Status**: ✅ Completed

**Files Modified**:
- [Campaign_platform/src/pages/user/TrafficFlowParser.jsx](Campaign_platform/src/pages/user/TrafficFlowParser.jsx)

**Implementation**:
```javascript
// New refs for click protection
const isClickProcessingRef = useRef(false);
const lastClickTimeRef = useRef(0);
const CLICK_DEBOUNCE_MS = 2000; // 2 second debounce window

// In handleStore:
const now = Date.now();
const timeSinceLastClick = now - lastClickTimeRef.current;

if (isClickProcessingRef.current) {
    console.log('🚫 Click blocked: Another request is already processing');
    return;
}

if (timeSinceLastClick < CLICK_DEBOUNCE_MS) {
    console.log(`🚫 Click blocked: Debounce active`);
    return;
}
```

### TASK 9: Validation & Monitoring
**Status**: ✅ Completed

**New File**: [CPX_FIX_VERIFICATION.py](CPX_FIX_VERIFICATION.py)

Run this script to verify all fixes are in place:
```bash
python CPX_FIX_VERIFICATION.py
```

Output includes:
- Check for each task implementation
- Color-coded PASS/FAIL results
- Summary with deployment instructions

### TASK 10: Final Documentation
**Status**: ✅ Completed (This Document)

---

## Deployment Instructions

### 1. Verify Fixes
```bash
cd /path/to/campaign_platform-main
python CPX_FIX_VERIFICATION.py
```

### 2. Deploy Backend
```bash
# On VM 139.59.32.72
cd /var/www/campaign_platform
git pull origin main
pm2 restart campaign-backend
```

### 3. Build & Deploy Frontend
```bash
cd Campaign_platform
npm install
npm run build
# Copy dist to web server or use existing deployment
```

### 4. Monitor Logs
```bash
pm2 logs campaign-backend | grep -E "(CPX|GUARD|WEBVIEW)"
```

---

## Expected Log Output

### Successful Entry:
```
✅ CPX ENTRY GUARD: Registered new ext_user_id 'SFWID_12345' with status CREATED
🔄 Fetching CPX surveys for tracking_id=SFWID_12345
✅ CPX ENTRY GUARD: Updated ext_user_id 'SFWID_12345' status to 'REDIRECTED'
✅ Allocated CPX survey 67890 to SFWID=SFWID_12345
```

### Blocked Duplicate:
```
🚫 CPX ENTRY GUARD: ext_user_id 'SFWID_12345' already exists with status 'REDIRECTED'
🚫 CPX ENTRY GUARD BLOCK: ext_user_id_already_used_redirected
```

### Blocked WebView:
```
🚫 WEBVIEW DETECTED: User agent contains 'wv' - CPX will reject this traffic
🚫 CPX WEBVIEW BLOCK: User agent 'Mozilla/5.0 (Linux; Android... wv)' contains WebView signature 'wv'
```

---

## Troubleshooting

### Issue: Still Getting `already_clicked`
**Cause**: Old ext_user_ids still in CPX system
**Solution**: Wait 24 hours for CPX cache to clear, or use new ext_user_id format

### Issue: `api_standart_screen_out`
**Cause**: User doesn't qualify for survey (demographic mismatch)
**Solution**: This is expected - CPX filters by IP/region/profile

### Issue: No Surveys Available
**Cause**: CPX inventory depleted for user's region/profile
**Solution**: Normal behavior - check CPX dashboard for inventory

### Issue: Guard Collection Growing Too Fast
**Cause**: High traffic volume
**Solution**: TTL index auto-expires entries after 7 days

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `backend/main.py` | Added `cpx_entry_guards` collection, indexes, injection |
| `backend/routers/traffic.py` | Added guard functions, WebView detection, guard checks |
| `backend/app/services/cpx_service.py` | Changed 5 locations from `href_new` to `href` |
| `Campaign_platform/src/pages/user/TrafficFlowParser.jsx` | Added debounce/click protection |
| `CPX_FIX_VERIFICATION.py` | NEW - Validation script |
| `CPX_FIX_COMPREHENSIVE_REPORT.md` | NEW - This document |

---

## CPX API Reference

### Required Parameters
| Parameter | Value | Notes |
|-----------|-------|-------|
| `app_id` | 10754 | CPX App ID |
| `ext_user_id` | SFWID | Unique per respondent |
| `subid_1` | SFWID | Same as ext_user_id |
| `secure_hash` | MD5(ext_user_id + "-" + secret_key) | Required |
| `ip_user` | Real client IP | For targeting |
| `user_agent` | Real client UA | For fingerprinting |
| `user_country_code` | ISO2 (e.g., "IN") | For targeting |

### Response Processing
- Use `href` field only (NOT `href_new`)
- Append `subid_1` if not present
- Redirect user to this URL exactly once

### Postback Handling
- Verify hash: `MD5(trans_id + "-" + secret_key)`
- Status codes: 1=complete, 2=terminate, 3=quality fail

---

## Contact

For issues with this implementation:
- Check logs first: `pm2 logs campaign-backend`
- Run verification: `python CPX_FIX_VERIFICATION.py`
- Review this document for expected behavior

**Implementation Date**: $(date)
**Implementation Agent**: Agent Session
