# CPX Research Integration - Complete Guide

**Version:** 1.0
**Last Updated:** 2026-02-08
**Status:** Production

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Critical CPX Rules](#critical-cpx-rules)
3. [Integration Flow](#integration-flow)
4. [Device Fingerprinting](#device-fingerprinting)
5. [Common Issues & Solutions](#common-issues--solutions)
6. [Debugging Procedures](#debugging-procedures)
7. [API Parameter Reference](#api-parameter-reference)
8. [Screenout Analysis](#screenout-analysis)

---

## Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER JOURNEY                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  1. User lands on survey page                                    │
│     URL: ?vid=123&cc=IN&rid=VENDOR_USER_001                     │
│     Page: TrafficFlowParser.jsx                                  │
│                                                                   │
│  2. Profiling form displayed                                     │
│     - Email (mandatory)                                          │
│     - Date of Birth (mandatory)                                  │
│     - Gender (mandatory)                                         │
│     - Zip/Postal Code (mandatory)                               │
│                                                                   │
│  3. User clicks "Next"                                          │
│     Frontend:                                                    │
│     - Collects fresh IP (fetchClientIP)                         │
│     - Generates device fingerprint                              │
│     - Validates profiling data                                  │
│     - Calls /api/store                                          │
│                                                                   │
│  4. Backend processes request                                    │
│     Endpoint: POST /api/store                                    │
│     File: backend/routers/traffic.py                            │
│     - Creates traffic record (SFWID)                            │
│     - Validates ext_user_id (CPX entry guard)                   │
│     - Blocks WebView traffic                                    │
│     - Calls CPX API with profiling data                         │
│                                                                   │
│  5. CPX API Call                                                │
│     Service: cpx_service.fetch_and_allocate_for_respondent()    │
│     File: backend/app/services/cpx_service.py                   │
│     Parameters:                                                  │
│     - ext_user_id (vendor's rid)                               │
│     - ip_user (fresh browser IP)                               │
│     - user_agent (real browser UA)                             │
│     - user_country_code (ISO2: IN, US, etc)                    │
│     - email, birthday, gender, zip_code                        │
│                                                                   │
│  6. CPX Response                                                │
│     Success: Returns survey href with encrypted k= parameter    │
│     Failure: "No surveys available" or screenout                │
│                                                                   │
│  7. Redirect to Survey                                          │
│     Via: GET /cpx/redirect?id={SFWID}                          │
│     Pure HTTP 302 redirect to CPX survey page                  │
│                                                                   │
│  8. User completes survey                                       │
│     CPX sends S2S postback to:                                 │
│     POST /cpx-api/cpx-postback                                 │
│                                                                   │
│  9. Callback processing                                         │
│     - Validates postback hash                                   │
│     - Updates traffic status                                    │
│     - Forwards to vendor redirect URL                          │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose | Critical Functions |
|------|---------|-------------------|
| `Campaign_platform/src/pages/user/TrafficFlowParser.jsx` | Survey profiling form | `fetchClientIP()`, `generateDeviceFingerprint()`, `handleStore()` |
| `backend/routers/traffic.py` | Traffic flow API | `/api/store`, `/cpx/redirect`, entry guards |
| `backend/app/services/cpx_service.py` | CPX API integration | `fetch_and_allocate_for_respondent()` |
| `backend/routers/cpx_api.py` | CPX callbacks | `/cpx-postback` (S2S), callback logging |

---

## Critical CPX Rules

### ⚠️ NEVER VIOLATE THESE RULES

#### 1. **ext_user_id MUST Be Stable**
```python
# CORRECT: Use vendor's respondent ID
ext_user_id = respondent_id  # From URL parameter 'rid'

# WRONG: Using internal traffic ID
ext_user_id = traffic_id  # Generated by our system
```

**Why:** CPX tracks users by `ext_user_id`. If you generate new IDs for the same user, CPX will reject as duplicate traffic.

**Current Implementation:** ✅ Lines 1080-1082 in traffic.py
```python
vendor_user_id=respondent_id,        # Use vendor rid as ext_user_id
internal_tracking_id=traffic_id,     # Use SFWID as subid_1
```

#### 2. **IP Address MUST Match Click IP**
```javascript
// CORRECT: Fetch fresh IP right before CPX API call
let ipResult = await fetchClientIP();  // Uses ipify.org, ipinfo.io

// WRONG: Use cached IP from page load (mobile carriers rotate IPs)
let ipResult = prefetchedIpRef.current;  // May be stale!
```

**Why:** CPX validates that the IP used in the API call matches the IP when the user clicks the survey link. Mobile carriers (Jio, Airtel) rotate IPs every 30-60 seconds.

**Current Implementation:** ✅ Lines 265-288 in TrafficFlowParser.jsx
- Fetches fresh IP on button click
- Detects IP rotation
- Logs warnings if IP changed

#### 3. **User-Agent MUST Be Real Browser UA**
```python
# CORRECT: Pass actual browser User-Agent
user_agent = request.headers.get("User-Agent")

# WRONG: Generic or fabricated UA
user_agent = "python-requests/2.28.0"  # CPX will reject
```

**Why:** CPX fingerprints devices. Generic UAs cause fingerprint mismatch.

**Current Implementation:** ✅ Line 952 in traffic.py
```python
client_user_agent = data.get('userAgent') or request.headers.get("User-Agent") or ""
```

#### 4. **Single-Use ext_user_id (Entry Guard)**
```python
# Each ext_user_id can ONLY be used ONCE
# Duplicate usage causes: already_clicked, api_standart_screen_out

# Implementation: cpx_entry_guards collection
# Status flow: CREATED → REDIRECTED → LOCKED
```

**Current Implementation:** ✅ Lines 1066-1072 in traffic.py
- Checks guard before CPX API call
- Blocks duplicate ext_user_id attempts
- Logs duplicate attempts for monitoring

#### 5. **WebView Traffic MUST Be Blocked**
```python
# CPX explicitly rejects WebView traffic
# Block before calling API to save resources

WEBVIEW_SIGNATURES = [
    "wv", "webview", "fbav", "instagram", "twitter",
    "timebucks", ";wv)", "micromessenger"
]
```

**Current Implementation:** ✅ Lines 1056-1062 in traffic.py
- Detects WebView signatures in User-Agent
- Blocks before CPX API call
- Logs blocked attempts

---

## Integration Flow

### 1. Frontend: User Profiling & IP Collection

**File:** `TrafficFlowParser.jsx`

```javascript
// Step 1: Collect profiling data from form
const email = "user@example.com";
const birthdayDay = 15;
const birthdayMonth = 6;
const birthdayYear = 1990;
const gender = "m";  // or "f"
const zipCode = "110001";

// Step 2: Fetch fresh IP (CRITICAL for CPX)
const ipResult = await fetchClientIP();
// Uses external services:
// - https://api.ipify.org?format=json
// - https://ipinfo.io/json

// Step 3: Generate device fingerprint
const fingerprint = await generateDeviceFingerprint();
// Includes: userAgent, language, platform, timeZone, screen, hardware

// Step 4: Submit to backend
await fetch('/api/store', {
  method: 'POST',
  body: JSON.stringify({
    params: { vid, cc, rid },
    clientIp: ipResult.ip,
    userAgent: navigator.userAgent,
    email: email,
    birthday_day: birthdayDay,
    birthday_month: birthdayMonth,
    birthday_year: birthdayYear,
    gender: gender,
    zip_code: zipCode,
    deviceFingerprint: fingerprint.hash,
    fingerprintComponents: fingerprint.components
  })
});
```

### 2. Backend: Traffic Record Creation

**File:** `traffic.py` - `/api/store` endpoint

```python
# Extract parameters
vendor_id = params.get('vid')        # Vendor ID
country_code = params.get('cc')      # Country code (e.g., "IN")
respondent_id = params.get('rid')    # Vendor's respondent ID (ext_user_id)

# Extract profiling data
user_email = data.get('email')
birthday_day = data.get('birthday_day')
birthday_month = data.get('birthday_month')
birthday_year = data.get('birthday_year')
gender = data.get('gender')          # "m" or "f"
zip_code = data.get('zip_code')

# Extract device data
client_ip = data.get('clientIp')     # Fresh IP from browser
user_agent = data.get('userAgent')   # Real browser UA
device_fingerprint = data.get('deviceFingerprint')

# Create traffic record (SFWID)
traffic_id = traffic_service.create_traffic_record(
    vendor_id=vendor_id,
    country_code=country_code,
    respondent_id=respondent_id,
    client_ip=client_ip,
    user_agent=user_agent,
    email=user_email
)
```

### 3. Backend: CPX Entry Guards

**File:** `traffic.py` - Lines 1066-1072

```python
# Check if ext_user_id can be used
guard_result = check_cpx_entry_guard(respondent_id, client_ip, user_agent)

if not guard_result["allowed"]:
    allocation_error = f"ext_user_id guard blocked: {guard_result['reason']}"
    # Block duplicate ext_user_id - prevents "already_clicked" screenout
    return error_response
```

**Entry Guard Collection:** `cpx_entry_guards`

| Field | Type | Purpose |
|-------|------|---------|
| `ext_user_id` | String | Vendor's respondent ID (unique index) |
| `status` | String | CREATED, REDIRECTED, LOCKED |
| `created_at` | DateTime | When first registered |
| `client_ip` | String | IP address at registration |
| `user_agent` | String | Browser UA at registration |
| `survey_id` | String | Allocated survey ID |
| `entry_link` | String | CPX entry URL |
| `duplicate_attempt_count` | Integer | Number of duplicate attempts |

### 4. Backend: CPX API Call

**File:** `cpx_service.py` - `fetch_and_allocate_for_respondent()`

```python
# Build CPX API parameters
params = {
    "app_id": self.app_id,                    # From .env CPX_APP_ID
    "ext_user_id": vendor_user_id,            # Vendor's rid (STABLE)
    "subid_1": internal_tracking_id,          # Our SFWID (for tracking)
    "output_method": "api",
    "ip_user": user_ip,                       # Fresh browser IP
    "user_agent": user_agent,                 # Real browser UA
    "user_country_code": country_iso2,        # "IN", "US", etc.
    "limit": self.fetch_limit,                # Default: 1000
    "secure_hash": secure_hash,               # MD5 hash

    # User profiling parameters (CRITICAL for survey matching)
    "email": email,
    "birthday_day": birthday_day,             # 1-31
    "birthday_month": birthday_month,         # 1-12
    "birthday_year": birthday_year,           # 4 digits
    "gender": gender,                         # "m" or "f"
    "zip_code": zip_code                      # User's postal code
}

# Call CPX API
response = requests.get(
    "https://live-api.cpx-research.com/api/get-surveys.php",
    params=params,
    timeout=30
)

data = response.json()

# Parse response
surveys = data.get("surveys", [])
if not surveys:
    return {"success": False, "error": "No surveys available from CPX"}

# Apply filters
max_loi = filter_settings.get("max_loi", 20)      # Max 20 minutes
min_cpi = filter_settings.get("min_cpi", 1.0)     # Min $1 payout
min_ir = filter_settings.get("min_ir", 0)         # Min incidence rate

filtered_surveys = [
    s for s in surveys
    if s.get("loi", 0) <= max_loi
    and s.get("payout_publisher_usd", 0) >= min_cpi
    and s.get("conversion_rate", 0) >= min_ir
]

# Randomly select one survey
selected_survey = random.choice(filtered_surveys)
entry_link = selected_survey.get("href")  # CPX click URL with k= parameter

return {
    "success": True,
    "entry_link": entry_link,
    "survey_id": selected_survey["id"]
}
```

### 5. Backend: Redirect to Survey

**File:** `traffic.py` - `/cpx/redirect` endpoint

```python
@router.get("/cpx/redirect")
async def cpx_redirect(id: str):
    # Get traffic record
    record = url_parameters_collection.find_one({"_id": ObjectId(id)})
    entry_link = record.get("redirectUrl")

    # Validate CPX domain
    if not entry_link.startswith("https://click.cpx-research.com/"):
        raise HTTPException(400, "Invalid CPX entry link")

    # Pure HTTP 302 redirect (preserves CPX parameters)
    return RedirectResponse(url=entry_link, status_code=302)
```

### 6. CPX Postback (S2S Callback)

**File:** `cpx_api.py` - `/cpx-postback` endpoint

```python
@router.post("/cpx-postback")
async def cpx_postback(request: Request):
    # Extract parameters
    ext_user_id = request.query_params.get("ext_user_id")
    trans_id = request.query_params.get("trans_id")
    status = request.query_params.get("status")  # completed, screenout, reversed
    reward = request.query_params.get("reward")
    subid_1 = request.query_params.get("subid1")  # Our SFWID

    # Validate hash
    hash_string = f"cpx-{ext_user_id}-{trans_id}-{status}-{secret}"
    expected_hash = hashlib.sha256(hash_string.encode()).hexdigest()
    received_hash = request.query_params.get("hash")

    if expected_hash != received_hash:
        return {"status": "error", "message": "Invalid hash"}

    # Update traffic record
    traffic_service.update_traffic_status(
        traffic_id=subid_1,
        status="COMPLETE" if status == "completed" else "TERMINATED"
    )

    # Forward to vendor
    vendor_redirect = get_vendor_redirect_url(ext_user_id, status)

    return {"status": "ok"}
```

---

## Device Fingerprinting

### Overview

Device fingerprinting helps CPX detect fraud and ensure the same device/browser is used throughout the survey journey.

**File:** `TrafficFlowParser.jsx` - Lines 94-126

### Components Collected

```javascript
const components = {
    userAgent: navigator.userAgent,           // Browser + OS
    language: navigator.language,             // "en-US", "hi-IN"
    platform: navigator.platform,             // "Win32", "Linux"
    timeZone: Intl.DateTimeFormat()
        .resolvedOptions().timeZone,          // "Asia/Kolkata"
    screen: `${window.screen.width}x
             ${window.screen.height}x
             ${window.screen.colorDepth}`,    // "1920x1080x24"
    hardwareConcurrency: navigator.hardwareConcurrency,  // CPU cores
    deviceMemory: navigator.deviceMemory,     // RAM in GB
    maxTouchPoints: navigator.maxTouchPoints  // Touch support
};
```

### Fingerprint Generation

```javascript
// Hash the components using SHA-256
const raw = JSON.stringify(components);
const data = new TextEncoder().encode(raw);
const digest = await window.crypto.subtle.digest("SHA-256", data);
const hashArray = Array.from(new Uint8Array(digest));
const hashHex = hashArray.map(b => b.toString(16).padStart(2, "0")).join("");

const fingerprint = `fp_${hashHex}`;
// Result: fp_a3f5c8d9e2b4f1a7c6d8e9f0b1c2d3e4f5...
```

### Storage & Usage

```python
# Backend stores fingerprint in traffic record
traffic_record = {
    "_id": traffic_id,
    "deviceFingerprint": "fp_a3f5c8d9...",
    "fingerprintComponents": {
        "userAgent": "Mozilla/5.0...",
        "language": "en-US",
        "platform": "Win32",
        "timeZone": "Asia/Kolkata",
        "screen": "1920x1080x24",
        "hardwareConcurrency": 8,
        "deviceMemory": 16,
        "maxTouchPoints": 0
    },
    "fingerprintSource": "client"
}
```

### CPX's Use of Fingerprinting

CPX may use fingerprinting to:

1. **Fraud Detection:** Detect if multiple users share the same device
2. **Bot Detection:** Identify automated traffic (bots have generic fingerprints)
3. **Consistency Validation:** Ensure the device at API call time matches the device at survey click time
4. **Quality Scoring:** Flag suspicious patterns (e.g., VMs, emulators)

**Important:** While we collect fingerprints, CPX primarily relies on:
- IP address consistency
- User-Agent consistency
- ext_user_id uniqueness

Our fingerprint is stored for **our own fraud detection** and analytics, not directly sent to CPX.

### Fingerprint Fraud Patterns

| Pattern | Detection | Action |
|---------|-----------|--------|
| **Generic Fingerprint** | All zeros, no hardware info | Flag as bot |
| **Duplicate Fingerprint** | Same hash across many users | Flag as device farm |
| **Inconsistent Fingerprint** | Changes mid-survey | Flag as fraud |
| **WebView Fingerprint** | Contains WebView signatures | Block before CPX call |

### Device Fingerprint Debugging

```python
# Check fingerprint in traffic record
record = url_parameters_collection.find_one({"_id": ObjectId(traffic_id)})

print(f"Device Fingerprint: {record.get('deviceFingerprint')}")
print(f"Components: {record.get('fingerprintComponents')}")

# Check for suspicious patterns
components = record.get('fingerprintComponents', {})
if components.get('hardwareConcurrency', 0) == 0:
    print("⚠️ Suspicious: No CPU cores reported (possible bot)")

if components.get('maxTouchPoints', 0) > 10:
    print("⚠️ Suspicious: Unusual touch points (possible emulator)")

if 'wv' in components.get('userAgent', '').lower():
    print("🚫 WebView detected - CPX will reject")
```

---

## Common Issues & Solutions

### Issue 1: "api_standart_screen_out" (Instant Screenout at 0 seconds)

**Symptoms:**
- User clicks "Next" button
- Gets screened out immediately (0min 0sec)
- Backend logs show CPX API was called
- Status: `api_standart_screen_out`

**Root Causes & Solutions:**

#### A. No Surveys Available for Demographics

**Diagnosis:**
```bash
# Check backend logs for:
"📥 CPX FULL RESPONSE: ..."
# Look for:
"count_available_surveys": 0
"message_not_found": "No surveys available"
```

**Solution:**
- CPX may not have surveys for your demographic (Country, Age, Gender)
- Contact CPX support to verify survey availability
- Try different test profiles (different age ranges, genders)

**Verification Test:**
```python
# Add this test endpoint to traffic.py
@router.get("/api/test-cpx")
async def test_cpx_api():
    # Test with multiple profiles
    profiles = [
        {"age": 25, "gender": "m", "country": "IN"},
        {"age": 35, "gender": "f", "country": "IN"},
        {"age": 45, "gender": "m", "country": "US"}
    ]

    results = []
    for profile in profiles:
        result = cpx_service.fetch_and_allocate_for_respondent(
            vendor_user_id=f"TEST_{profile['age']}_{profile['gender']}",
            internal_tracking_id="TEST_SFWID",
            user_ip="49.37.51.191",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            country_code=profile['country'],
            email="test@example.com",
            birthday_year=2024 - profile['age'],
            birthday_month=6,
            birthday_day=15,
            gender=profile['gender'],
            zip_code="110001"
        )
        results.append({"profile": profile, "success": result.get("success")})

    return {"test_results": results}
```

#### B. Country Code Not Being Passed

**Diagnosis:**
```python
# Check logs for:
"🌍 Country code from URL: {country_code}"
# If blank or wrong, the URL parameter is missing
```

**Solution:**
```javascript
// Frontend: Ensure URL has cc parameter
const urlParams = new URLSearchParams(window.location.search);
const cc = urlParams.get('cc');
if (!cc) {
    alert("Missing country code (cc) parameter in URL");
}
```

**Backend Validation:**
```python
# traffic.py - Add validation
country_code = params.get('cc', '')
if not country_code:
    raise HTTPException(400, "Missing country code (cc) parameter")

# Normalize to ISO2
country_iso2 = cpx_service.normalize_country_code(country_code)
if not country_iso2:
    raise HTTPException(400, f"Invalid country code: {country_code}")
```

#### C. IP Address Mismatch

**Diagnosis:**
```python
# Check logs for:
"⚠️ IP MISMATCH DETECTED:"
"   Browser IP (from ipify.org): X.X.X.X"
"   Server IP (from CF-Connecting-IP): Y.Y.Y.Y"
```

**Why This Happens:**
- Mobile carrier NAT (Jio, Airtel rotate IPs)
- VPN usage
- Proxy/CGNAT

**Solution:**
✅ **Already implemented** - Lines 265-288 in TrafficFlowParser.jsx
- Fetches FRESH IP right before API call
- Uses browser-based collection (ipify.org)
- Logs IP rotation warnings

**Verification:**
```javascript
// Check console logs when user clicks "Next"
// You should see:
console.log(`✅ Using FRESH IP: ${ipResult.ip}`);
// If you see rotation warning, that's expected on mobile
console.warn(`⚠️ IP ROTATION DETECTED: Prefetch=${prefetchedIp}, Fresh=${ipResult.ip}`);
```

#### D. Duplicate ext_user_id (Entry Guard Block)

**Diagnosis:**
```python
# Check logs for:
"🚫 CPX ENTRY GUARD: ext_user_id 'XXX' already exists with status 'YYY'"
```

**Solution:**
- Each ext_user_id can only be used ONCE
- Vendor must send unique rid for each respondent
- Check if vendor is recycling respondent IDs

**Reset Entry Guard (for testing only):**
```python
# DANGEROUS - Only use in dev/staging
cpx_entry_guards_collection.delete_one({"ext_user_id": "TEST_USER_001"})
```

#### E. WebView Traffic

**Diagnosis:**
```python
# Check logs for:
"🚫 WEBVIEW DETECTED: User agent contains 'wv'"
"🚫 CPX rejects WebView traffic - blocking locally"
```

**Solution:**
✅ **Already implemented** - Lines 1056-1062 in traffic.py
- Blocks before CPX API call
- Saves API quota

**User Education:**
- Inform users to use regular browsers (Chrome, Safari, Edge)
- Don't open surveys from in-app browsers (Facebook, Instagram, Twitter)

---

### Issue 2: "already_clicked" Error

**Symptoms:**
- User gets redirected to CPX survey
- Sees error: "This survey has already been clicked"
- Status in screenout report: `already_clicked`

**Root Cause:**
- Same ext_user_id used multiple times
- User clicked survey link twice
- Vendor sent duplicate respondent IDs

**Solution:**

✅ **Already implemented** - Entry Guards (Lines 1066-1072 in traffic.py)

**Additional Protection:**
Add frontend debounce protection:

```javascript
// TrafficFlowParser.jsx - Already implemented at lines 152-154
const isClickProcessingRef = useRef(false);
const lastClickTimeRef = useRef(0);
const CLICK_DEBOUNCE_MS = 2000;  // 2 second debounce

const handleStore = async () => {
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

    isClickProcessingRef.current = true;
    lastClickTimeRef.current = now;

    // ... rest of function
};
```

---

### Issue 3: Slow Response Time

**Symptoms:**
- User waits 5-10 seconds after clicking "Next"
- Eventually gets survey or "no surveys available" message

**Root Cause:**
- External IP service calls (ipify.org, ipinfo.io) are slow
- CPX API is slow (rare)
- Network latency

**Solution:**

✅ **Partially implemented** - Lines 168-180 in TrafficFlowParser.jsx

**Optimization:**
```javascript
// Current: Prefetch on page load (good)
useEffect(() => {
    const prefetchIp = async () => {
        const ipData = await fetchClientIP();
        prefetchedIpRef.current = ipData;
    };
    prefetchIp();
}, []);

// BUT: Still fetches fresh IP on click (necessary for mobile)
// This causes 3-9 second delay

// Improvement: Parallel IP fetch
const handleStore = async () => {
    // Start IP fetch immediately
    const ipPromise = fetchClientIP();
    const fingerprintPromise = generateDeviceFingerprint();

    // Wait for both in parallel
    const [ipResult, fingerprint] = await Promise.all([
        ipPromise,
        fingerprintPromise
    ]);

    // Continue with API call...
};
```

**Monitoring:**
```python
# Add timing logs to cpx_service.py
import time

def fetch_and_allocate_for_respondent(...):
    start_time = time.time()

    # ... API call

    elapsed = time.time() - start_time
    print(f"⏱️ CPX API call took {elapsed:.2f} seconds")

    if elapsed > 5:
        print(f"⚠️ SLOW CPX API: Request took {elapsed:.2f}s (expected < 3s)")
```

---

### Issue 4: Missing User Profiling Data

**Symptoms:**
- All surveys return "No surveys available"
- CPX dashboard shows low match rates
- Backend logs show profiling params as `None`

**Diagnosis:**
```python
# Check logs for:
"📅 User DOB: ..."
"⚧ User gender: ..."
"📮 User zip/postal code: ..."

# If these are missing, profiling data not collected
```

**Solution:**

✅ **Already implemented** - TrafficFlowParser.jsx has mandatory profiling form

**Frontend Validation:**
```javascript
// Lines 236-252 - Already validates profiling data before submit
if (!birthdayDay || !birthdayMonth || !birthdayYear) {
    setProfileError("Please enter your complete date of birth");
    return;
}
if (!gender) {
    setProfileError("Please select your gender");
    return;
}
if (!zipCode || !zipCode.trim()) {
    setProfileError("Please enter your postal/zip code");
    return;
}
```

**Backend Validation:**
```python
# Add this to traffic.py after line 977
if not user_email:
    raise HTTPException(400, "Email is required")
if not gender or gender not in ['m', 'f']:
    raise HTTPException(400, "Gender must be 'm' or 'f'")
if not birthday_day or not birthday_month or not birthday_year:
    raise HTTPException(400, "Date of birth is required")
if not zip_code:
    raise HTTPException(400, "Zip/postal code is required")
```

---

## Debugging Procedures

### Debug Flow: User Gets Instant Screenout

```
┌─────────────────────────────────────────────────────────────┐
│ User clicks "Next" → Gets screened out immediately          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: Check Browser Console (F12)                         │
├─────────────────────────────────────────────────────────────┤
│ Look for:                                                    │
│ ✅ "✅ Fetched client IP: X.X.X.X from https://..."         │
│ ✅ "🔐 Device fingerprint: fp_..."                          │
│ ✅ "🆔 Generated trans_id: ..."                             │
│ ❌ "🚫 Click blocked: ..." (indicates debounce issue)       │
│ ❌ "❌ Could not fetch client IP" (IP collection failure)   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 2: Check Backend Logs (Python console)                 │
├─────────────────────────────────────────────────────────────┤
│ Search for traffic_id or respondent_id:                     │
│                                                              │
│ A. Traffic Record Creation                                  │
│    ✅ "✅ Created traffic record (SFWID): 67abc..."         │
│    ❌ "Missing required parameters" (validation failure)    │
│                                                              │
│ B. Entry Guard Check                                        │
│    ✅ "✅ CPX ENTRY GUARD: Registered new ext_user_id..."   │
│    ❌ "🚫 CPX ENTRY GUARD BLOCK: ..." (duplicate usage)    │
│                                                              │
│ C. WebView Detection                                        │
│    ❌ "🚫 CPX WEBVIEW BLOCK: User agent '...' contains..." │
│                                                              │
│ D. CPX API Request                                          │
│    ✅ "🔄 Fetching CPX surveys for tracking_id=..."        │
│    ✅ "📤 CPX REQUEST URL: ..." (show params)               │
│                                                              │
│ E. CPX API Response                                         │
│    ✅ "📥 CPX FULL RESPONSE: ..." (JSON response)           │
│    Look for:                                                 │
│      "count_available_surveys": 0  → No surveys available   │
│      "surveys": []  → Empty survey list                     │
│                                                              │
│ F. Allocation Result                                        │
│    ✅ "✅ Allocated CPX survey X to SFWID=Y"                │
│    ❌ "⚠️ Per-respondent CPX allocation failed: ..."        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 3: Check CPX API Response Details                      │
├─────────────────────────────────────────────────────────────┤
│ Copy the full "📥 CPX FULL RESPONSE" from logs              │
│                                                              │
│ Key fields:                                                  │
│ {                                                            │
│   "status": "success",                                       │
│   "count_available_surveys": 0,  ← KEY: 0 = no surveys!    │
│   "count_returned_surveys": 0,                              │
│   "surveys": [],                 ← KEY: empty array!        │
│   "message_not_found": "No surveys available for profile"   │
│ }                                                            │
│                                                              │
│ If count_available_surveys = 0:                             │
│   → CPX has no surveys for this demographic                 │
│   → NOT a technical issue!                                  │
│   → Contact CPX support                                     │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 4: Verify Parameters Sent to CPX                       │
├─────────────────────────────────────────────────────────────┤
│ From "📤 CPX REQUEST URL" log:                              │
│                                                              │
│ app_id=YOUR_APP_ID                                          │
│ ext_user_id=VENDOR_RID_0001      ← Must be vendor's rid    │
│ ip_user=49.37.51.191             ← Must be real public IP  │
│ user_agent=Mozilla/5.0...        ← Must be real browser UA │
│ user_country_code=IN             ← Must be ISO2 code       │
│ email=user@example.com           ← Must be valid email     │
│ birthday_day=15                  ← 1-31                     │
│ birthday_month=6                 ← 1-12                     │
│ birthday_year=1990               ← 4 digits                 │
│ gender=m                         ← "m" or "f"               │
│ zip_code=110001                  ← User's postal code       │
│                                                              │
│ Common issues:                                               │
│ ❌ user_country_code missing or wrong                       │
│ ❌ ip_user is private IP (127.0.0.1, 192.168.x.x)          │
│ ❌ email, gender, birthday missing                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 5: Check CPX Dashboard                                 │
├─────────────────────────────────────────────────────────────┤
│ Login to: https://publisher.cpx-research.com                │
│                                                              │
│ Navigate to:                                                 │
│ 1. Statistics → Traffic Overview                            │
│    - Check if API calls are being logged                    │
│    - Look for rejection reasons                             │
│                                                              │
│ 2. Available Surveys                                        │
│    - Check if surveys exist for your target country (IN)    │
│    - Check demographic filters (age, gender)                │
│                                                              │
│ 3. API Logs (if available)                                  │
│    - Search for your ext_user_id                            │
│    - Check rejection reasons                                │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 6: Test with Known Working Profile                     │
├─────────────────────────────────────────────────────────────┤
│ Create test URL:                                             │
│ https://yoursite.com/survey?vid=123&cc=US&rid=TEST_US_001  │
│                                                              │
│ Fill profiling form:                                         │
│ - Email: test@example.com                                   │
│ - DOB: 1990-06-15 (34 years old)                           │
│ - Gender: Male                                              │
│ - Zip: 10001 (New York)                                     │
│                                                              │
│ If US works but IN doesn't:                                 │
│   → CPX has no surveys for India                            │
│   → Contact CPX support to add India surveys                │
└─────────────────────────────────────────────────────────────┘
```

### Debug Command: Quick Health Check

Add this endpoint to test all components:

```python
# traffic.py
@router.get("/api/debug/cpx-health")
async def cpx_health_check(request: Request):
    """
    Quick health check for CPX integration
    Returns diagnostics for all critical components
    """
    diagnostics = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }

    # Check 1: CPX Service Available
    diagnostics["checks"]["cpx_service"] = {
        "available": cpx_service is not None,
        "status": "ok" if cpx_service else "error"
    }

    # Check 2: Collections Available
    diagnostics["checks"]["collections"] = {
        "url_parameters": url_parameters_collection is not None,
        "cpx_entry_guards": cpx_entry_guards_collection is not None,
        "vendors": vendors_collection is not None,
        "status": "ok" if all([
            url_parameters_collection,
            cpx_entry_guards_collection,
            vendors_collection
        ]) else "error"
    }

    # Check 3: Environment Variables
    diagnostics["checks"]["environment"] = {
        "cpx_app_id": bool(os.getenv("CPX_APP_ID")),
        "cpx_secure_hash": bool(os.getenv("CPX_SECURE_HASH_KEY")),
        "frontend_url": bool(os.getenv("FRONTEND_URL")),
        "status": "ok" if all([
            os.getenv("CPX_APP_ID"),
            os.getenv("CPX_SECURE_HASH_KEY")
        ]) else "error"
    }

    # Check 4: Test CPX API (with dummy data)
    if cpx_service:
        try:
            test_result = cpx_service.fetch_and_allocate_for_respondent(
                vendor_user_id="HEALTH_CHECK_TEST",
                internal_tracking_id="TEST_SFWID",
                user_ip="8.8.8.8",  # Google DNS (public IP)
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                country_code="US",
                email="test@example.com",
                birthday_day=15,
                birthday_month=6,
                birthday_year=1990,
                gender="m",
                zip_code="10001"
            )
            diagnostics["checks"]["cpx_api"] = {
                "status": "ok" if test_result.get("success") else "warning",
                "success": test_result.get("success"),
                "error": test_result.get("error")
            }
        except Exception as e:
            diagnostics["checks"]["cpx_api"] = {
                "status": "error",
                "error": str(e)
            }

    # Check 5: Recent Traffic Stats
    if url_parameters_collection:
        total_traffic = url_parameters_collection.count_documents({})
        recent_traffic = url_parameters_collection.count_documents({
            "createdAt": {"$gte": datetime.utcnow() - timedelta(hours=24)}
        })
        diagnostics["checks"]["traffic"] = {
            "total_records": total_traffic,
            "last_24h": recent_traffic,
            "status": "ok"
        }

    # Check 6: Entry Guard Stats
    if cpx_entry_guards_collection:
        total_guards = cpx_entry_guards_collection.count_documents({})
        blocked_attempts = cpx_entry_guards_collection.count_documents({
            "duplicate_attempt_count": {"$gt": 0}
        })
        diagnostics["checks"]["entry_guards"] = {
            "total_entries": total_guards,
            "blocked_duplicates": blocked_attempts,
            "status": "ok"
        }

    # Overall Status
    all_checks = [v.get("status", "unknown") for v in diagnostics["checks"].values()]
    if "error" in all_checks:
        diagnostics["overall_status"] = "error"
    elif "warning" in all_checks:
        diagnostics["overall_status"] = "warning"
    else:
        diagnostics["overall_status"] = "ok"

    return diagnostics
```

**Usage:**
```bash
# Call from browser or curl
curl https://yoursite.com/api/debug/cpx-health
```

**Expected Output:**
```json
{
  "timestamp": "2026-02-08T10:30:00.000Z",
  "overall_status": "ok",
  "checks": {
    "cpx_service": {"available": true, "status": "ok"},
    "collections": {"url_parameters": true, "cpx_entry_guards": true, "status": "ok"},
    "environment": {"cpx_app_id": true, "cpx_secure_hash": true, "status": "ok"},
    "cpx_api": {"status": "ok", "success": true},
    "traffic": {"total_records": 1523, "last_24h": 342, "status": "ok"},
    "entry_guards": {"total_entries": 1523, "blocked_duplicates": 45, "status": "ok"}
  }
}
```

---

## API Parameter Reference

### CPX API Request Parameters

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `app_id` | String | ✅ Required | Your CPX App ID | "12345" |
| `ext_user_id` | String | ✅ Required | Vendor's stable respondent ID | "VENDOR_RID_001" |
| `subid_1` | String | ✅ Recommended | Your internal tracking ID (SFWID) | "67abc123..." |
| `output_method` | String | ✅ Required | Must be "api" | "api" |
| `ip_user` | String | ✅ Required | User's real public IP address | "49.37.51.191" |
| `user_agent` | String | ✅ Required | User's real browser User-Agent | "Mozilla/5.0..." |
| `user_country_code` | String | ⚠️ Recommended | ISO2 country code | "IN", "US" |
| `limit` | Integer | Optional | Max surveys to return | 1000 |
| `secure_hash` | String | ⚠️ Recommended | MD5 hash for security | (computed) |
| **User Profiling** | | | | |
| `email` | String | ⚠️ Recommended | User's email address | "user@example.com" |
| `birthday_day` | Integer | ⚠️ Recommended | Day of birth (1-31) | 15 |
| `birthday_month` | Integer | ⚠️ Recommended | Month of birth (1-12) | 6 |
| `birthday_year` | Integer | ⚠️ Recommended | Year of birth (4 digits) | 1990 |
| `gender` | String | ⚠️ Recommended | "m" or "f" | "m" |
| `zip_code` | String | ⚠️ Recommended | Postal/zip code | "110001" |

### CPX API Response Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `status` | String | Response status | "success", "error" |
| `count_available_surveys` | Integer | Number of surveys available | 5 |
| `count_returned_surveys` | Integer | Number of surveys in response | 5 |
| `surveys` | Array | Array of survey objects | [...] |
| `message_not_found` | String | Message when no surveys | "No surveys available" |

### Survey Object Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `id` | String | CPX survey ID | "57572480" |
| `loi` | Integer | Length of interview (minutes) | 9 |
| `payout` | Float | Publisher payout (local currency) | 0.50 |
| `payout_publisher_usd` | Float | Publisher payout (USD) | 0.81 |
| `conversion_rate` | Float | Completion rate (%) | 35.29 |
| `click_to_okay_rate` | Float | Qualification rate (%) | 10.15 |
| `quality_score` | Integer | Quality rating (higher = better) | 11 |
| `href` | String | Survey entry URL | "https://click.cpx-research.com/..." |
| `href_new` | String | Mobile-optimized entry URL | "https://click.cpx-research.com/..." |
| `top` | Integer | Top survey flag (1 = top) | 0 |
| `webcam` | Integer | Webcam required (1 = yes) | 0 |

---

## Screenout Analysis

### Understanding Screenout Reasons

From your screenout report, the most common status is `api_standart_screen_out`.

**What it means:**
- User rejected at API level (before entering survey)
- Rejection happens in 0 seconds
- No qualification questions shown

**Common Causes:**

1. **No Surveys Available** (Most Common)
   - CPX has no surveys for the demographic
   - Country/age/gender combination has no active studies
   - **Solution:** Contact CPX support

2. **Duplicate ext_user_id**
   - Same ext_user_id used before
   - Triggers: `already_clicked`, `already_do_internal`
   - **Solution:** Entry guards (already implemented)

3. **IP/Fingerprint Mismatch**
   - API call IP ≠ Click IP
   - User-Agent mismatch
   - **Solution:** Fresh IP collection (already implemented)

4. **WebView Traffic**
   - In-app browser detected
   - CPX blocks WebView
   - **Solution:** WebView detection (already implemented)

5. **Fraud Detection**
   - CPX internal fraud rules
   - Suspicious patterns detected
   - **Solution:** Ensure real traffic only

### Screenout Report Analysis

From your report (36 entries):

```
Total Screenouts: 36
- api_standart_screen_out: 34 (94%)
- early_screenout: 2 (6%)
- already_clicked: 2 (6%)

Average Duration: 0min 0sec (instant rejection)
Country: 100% India (IN)
Device Types:
  - Smartphone (Android): 80%
  - Desktop (Windows): 20%
ISPs:
  - Reliance Jio: 60%
  - Bharti Airtel: 25%
  - Vodafone Idea: 10%
  - Others: 5%

Risk Indicators:
  - 1 user with Proxy detected (Risk: 66)
  - 35 users with no proxy (Risk: 0)
```

**Key Findings:**

1. **Geographic Concentration**
   - 100% traffic from India
   - This suggests CPX may have limited India inventory

2. **Instant Rejection Pattern**
   - 94% reject at 0 seconds
   - This indicates API-level rejection, not qualification failure
   - Users never see survey questions

3. **Device Distribution**
   - Mix of mobile (80%) and desktop (20%)
   - Device type not the issue

4. **Low Fraud Risk**
   - Only 1 user flagged as proxy
   - 97% clean traffic

### Recommendations Based on Analysis

1. **Primary Issue: Survey Availability**
   - Contact CPX support: "Do you have surveys for India (IN)?"
   - Request survey inventory breakdown by country
   - Consider expanding to other countries (US, UK, CA)

2. **Test with US Traffic**
   - Change test URL to `?cc=US` instead of `?cc=IN`
   - Use US zip code (10001 instead of 110001)
   - See if surveys are available

3. **Monitor API Responses**
   - Add dashboard to track `count_available_surveys`
   - Alert when consistently 0 for extended period
   - Track by country/demographic

4. **Quality Score Filtering**
   - Your filters: `max_loi=20, min_cpi=1.0, min_ir=0`
   - Consider adding `min_quality_score=15`
   - This filters out low-quality surveys

---

## Environment Variables

Required environment variables in `.env`:

```bash
# CPX Configuration
CPX_APP_ID=your_app_id_here
CPX_SECURE_HASH_KEY=your_secure_hash_key_here
CPX_EXT_USER_ID=PANEL_88921  # Or your panel ID
CPX_API_TIMEOUT=30
CPX_FETCH_LIMIT=1000

# MongoDB
MONGO_URI=mongodb://localhost:27017/

# Frontend URL (for redirects)
FRONTEND_URL=https://surveyfieldwork.com

# Other
API_BASE_URL=https://api.surveyfieldwork.com
```

---

## Monitoring & Analytics

### Key Metrics to Track

1. **API Success Rate**
   - % of CPX API calls that return surveys
   - Target: >50%

2. **Allocation Success Rate**
   - % of traffic records that get allocated a survey
   - Target: >70%

3. **Completion Rate**
   - % of allocated surveys that complete
   - Target: >25% (varies by survey)

4. **Entry Guard Blocks**
   - Number of duplicate ext_user_id attempts
   - Target: <5% of traffic

5. **WebView Blocks**
   - Number of WebView users blocked
   - Target: Track for user education

6. **Average Response Time**
   - Time from button click to redirect
   - Target: <3 seconds

### MongoDB Queries for Analytics

```javascript
// 1. Survey availability by country
db.url_parameters.aggregate([
  {
    $group: {
      _id: "$countryCode",
      total: { $sum: 1 },
      allocated: {
        $sum: { $cond: [{ $ne: ["$assignedSurveyId", null] }, 1, 0] }
      }
    }
  },
  {
    $project: {
      country: "$_id",
      total: 1,
      allocated: 1,
      allocation_rate: {
        $multiply: [{ $divide: ["$allocated", "$total"] }, 100]
      }
    }
  }
]);

// 2. Entry guard blocks (duplicate ext_user_id)
db.cpx_entry_guards.aggregate([
  {
    $match: { duplicate_attempt_count: { $gt: 0 } }
  },
  {
    $group: {
      _id: null,
      total_blocks: { $sum: "$duplicate_attempt_count" },
      unique_users: { $sum: 1 }
    }
  }
]);

// 3. WebView traffic analysis
db.url_parameters.find({
  userAgent: { $regex: /wv|webview|fbav|instagram/i }
}).count();

// 4. Average completion rate
db.url_parameters.aggregate([
  {
    $group: {
      _id: null,
      total: { $sum: 1 },
      completed: {
        $sum: { $cond: [{ $eq: ["$status", "COMPLETE"] }, 1, 0] }
      }
    }
  },
  {
    $project: {
      completion_rate: {
        $multiply: [{ $divide: ["$completed", "$total"] }, 100]
      }
    }
  }
]);
```

---

## Contact & Support

### CPX Research Support
- **Publisher Dashboard:** https://publisher.cpx-research.com
- **Support Email:** support@cpx-research.com
- **Documentation:** https://docs.cpx-research.com

### Internal Team Contacts
- **Backend Lead:** [Your Name]
- **Frontend Lead:** [Your Name]
- **DevOps:** [Your Name]

---

## Changelog

### Version 1.0 (2026-02-08)
- Initial documentation
- Comprehensive architecture overview
- Device fingerprinting deep dive
- Screenout analysis based on production data
- Debugging procedures
- Common issues and solutions

---

## Appendix: Quick Reference

### Essential Log Searches

```bash
# Find specific traffic record
grep "SFWID=67abc123" backend.log

# Find CPX API responses
grep "📥 CPX FULL RESPONSE" backend.log

# Find entry guard blocks
grep "🚫 CPX ENTRY GUARD" backend.log

# Find WebView blocks
grep "🚫 WEBVIEW DETECTED" backend.log

# Find IP mismatches
grep "⚠️ IP MISMATCH" backend.log

# Find allocation failures
grep "⚠️ Per-respondent CPX allocation failed" backend.log
```

### Test URLs

```bash
# India test
https://yoursite.com/survey?vid=123&cc=IN&rid=TEST_IN_001

# US test
https://yoursite.com/survey?vid=123&cc=US&rid=TEST_US_001

# UK test
https://yoursite.com/survey?vid=123&cc=GB&rid=TEST_GB_001
```

### Quick API Tests

```bash
# Test CPX health
curl https://yoursite.com/api/debug/cpx-health

# Test IP collection
curl https://yoursite.com/api/prefetch-ip

# Get CPX callback logs
curl -H "Authorization: your_session_token" \
  https://yoursite.com/api/cpx-callback-logs?page=1&page_size=50
```

---

**End of Documentation**
