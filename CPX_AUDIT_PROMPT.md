# CPX Integration Audit Prompt

**Purpose:** Conduct a comprehensive audit of the CPX Research API integration to identify all issues causing instant screenouts (`api_standart_screen_out`).

**Context:** This is a production survey platform where users are getting instant screenouts (0 seconds) when attempting to access CPX surveys. 36 out of 36 users from India experienced immediate rejection with status `api_standart_screen_out`.

---

## 🎯 AUDIT OBJECTIVE

Systematically analyze the entire CPX integration flow from frontend to backend, validate all parameters, check API calls, and identify the root cause of instant screenouts.

---

## 📋 AUDIT CHECKLIST

### Phase 1: Environment & Configuration Validation

**Task:** Verify all environment variables and configuration settings are correct.

#### 1.1 Check Environment Variables
- [ ] Read `.env` file and verify these variables exist:
  - `CPX_APP_ID`
  - `CPX_SECURE_HASH_KEY`
  - `CPX_EXT_USER_ID`
  - `MONGO_URI`
  - `FRONTEND_URL`
  - `API_BASE_URL`

- [ ] Validate values are not empty or placeholder text
- [ ] Check if `CPX_APP_ID` looks valid (numeric, reasonable length)
- [ ] Check if `CPX_SECURE_HASH_KEY` looks valid (alphanumeric hash)

**Questions to Answer:**
1. Are all required CPX credentials configured?
2. Are the credentials valid format (not "YOUR_APP_ID_HERE")?
3. Is the MONGO_URI correctly formatted?

**Files to Check:**
- `backend/.env`
- `backend/.env.example`
- `backend/main.py` (lines where env vars are loaded)

---

### Phase 2: Frontend Data Collection Audit

**Task:** Verify the frontend is correctly collecting all required parameters.

#### 2.1 URL Parameters Extraction
- [ ] Check `TrafficFlowParser.jsx` lines 156-163
- [ ] Verify URL parameters are extracted: `vid`, `cc`, `rid`
- [ ] Check validation logic (lines 212-220)

**Test Case:**
```
URL: https://site.com/survey?vid=123&cc=IN&rid=TEST001
Expected: All three parameters extracted correctly
```

**Questions:**
1. Are URL parameters being extracted correctly?
2. Is there validation that rejects missing parameters?
3. Are parameters being logged for debugging?

#### 2.2 User Profiling Form Data
- [ ] Check form fields in `TrafficFlowParser.jsx` lines 424-600
- [ ] Verify mandatory fields: email, birthday (day/month/year), gender, zip_code
- [ ] Check validation logic (lines 223-252)

**Test Case:**
```
Input:
- Email: test@example.com
- DOB: Day=15, Month=6, Year=1990
- Gender: m
- Zip: 110001

Expected: All fields validated and collected
```

**Questions:**
1. Are all profiling fields marked as mandatory?
2. Is email format validated?
3. Is DOB validated (realistic dates)?
4. Is gender restricted to "m" or "f"?

#### 2.3 IP Address Collection
- [ ] Check `fetchClientIP()` function (lines 19-49)
- [ ] Check `fetchClientIPv4()` function (lines 53-91)
- [ ] Verify IP services: ipify.org, ipinfo.io
- [ ] Check fresh IP fetch on button click (lines 265-288)

**Test Case:**
```
Scenario: User clicks "Next" button
Expected: Fresh IP fetched from external service
Expected Log: "✅ Using FRESH IP: X.X.X.X"
```

**Questions:**
1. Is IP being fetched successfully?
2. Is the IP a valid public IPv4 address?
3. Is IP rotation being detected on mobile networks?
4. Are fallbacks working if primary service fails?

#### 2.4 Device Fingerprint Generation
- [ ] Check `generateDeviceFingerprint()` function (lines 94-126)
- [ ] Verify all components are collected (8 total)
- [ ] Check SHA-256 hashing implementation
- [ ] Verify fallback hash for browsers without crypto.subtle

**Test Case:**
```
Expected Components:
- userAgent (non-empty string)
- language (e.g., "en-US")
- platform (e.g., "Win32")
- timeZone (e.g., "Asia/Kolkata")
- screen (e.g., "1920x1080x24")
- hardwareConcurrency (number > 0)
- deviceMemory (number, may be 0)
- maxTouchPoints (number)

Expected Output: Hash starting with "fp_"
```

**Questions:**
1. Are all 8 components being collected?
2. Is the hash being generated correctly?
3. Are there any null/undefined values?

#### 2.5 Request Payload Construction
- [ ] Check `/api/store` request body (lines 306-329)
- [ ] Verify all fields are included in payload

**Required Fields in Payload:**
```javascript
{
  url: string,
  params: {vid, cc, rid},
  userAgent: string,
  clientIp: string,
  ipSource: string,
  deviceFingerprint: string,
  fingerprintComponents: object,
  trans_id: string,
  email: string,
  birthday_day: number,
  birthday_month: number,
  birthday_year: number,
  gender: string,
  zip_code: string
}
```

**Test Case:**
Create a test that logs the full payload before sending to backend.

**Questions:**
1. Are all fields present in the payload?
2. Are types correct (numbers vs strings)?
3. Is any field null or undefined?

---

### Phase 3: Backend Request Processing Audit

**Task:** Verify the backend correctly processes the frontend request.

#### 3.1 Traffic Record Creation
- [ ] Check `/api/store` endpoint in `traffic.py` (lines 884-1286)
- [ ] Verify parameter extraction (lines 901-904)
- [ ] Check profiling data extraction (lines 965-977)

**Test Case:**
```python
# Log extraction
print(f"Extracted params: vid={vendor_id}, cc={country_code}, rid={respondent_id}")
print(f"User email: {user_email}")
print(f"Birthday: {birthday_year}-{birthday_month}-{birthday_day}")
print(f"Gender: {gender}")
print(f"Zip: {zip_code}")
```

**Questions:**
1. Are parameters being extracted correctly from request body?
2. Are any parameters None or empty string?
3. Is country_code being normalized correctly?

#### 3.2 IP Address Validation
- [ ] Check client IP extraction (lines 926-949)
- [ ] Verify IP validation logic

**Test Case:**
```python
# Check if IP is valid public IP
if client_ip in ['127.0.0.1', 'localhost', '0.0.0.0', '::1']:
    print("❌ INVALID: Private IP detected")
if client_ip.startswith('192.168.') or client_ip.startswith('10.'):
    print("❌ INVALID: Private IP range")
```

**Questions:**
1. Is the IP a valid public IP?
2. Is it IPv4 or IPv6?
3. Does it match the IP from the browser?

#### 3.3 Entry Guard Validation
- [ ] Check `check_cpx_entry_guard()` function (lines 108-176)
- [ ] Verify entry guard collection exists
- [ ] Check duplicate detection logic

**Test Case:**
```python
# Test with known ext_user_id
guard_result = check_cpx_entry_guard("TEST_USER_001", client_ip, user_agent)
print(f"Guard allowed: {guard_result['allowed']}")
print(f"Reason: {guard_result['reason']}")
```

**Questions:**
1. Is the entry guard collection initialized?
2. Are duplicate ext_user_ids being blocked?
3. Is the guard status being updated correctly?

#### 3.4 WebView Detection
- [ ] Check `is_webview_user_agent()` function (lines 238-257)
- [ ] Verify WebView signatures list (lines 221-235)
- [ ] Check detection logic in `/api/store` (lines 1056-1062)

**Test Case:**
```python
# Test WebView detection
test_uas = [
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.0.0 Mobile Safari/537.36",  # WebView
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/144.0.0.0",  # Normal browser
]

for ua in test_uas:
    is_wv, sig = is_webview_user_agent(ua)
    print(f"UA: {ua[:50]}... → WebView: {is_wv}")
```

**Questions:**
1. Are WebView user agents being detected?
2. Is traffic being blocked before CPX API call?
3. Are blocks being logged?

---

### Phase 4: CPX API Call Audit

**Task:** Verify the CPX API call is constructed and executed correctly.

#### 4.1 CPX Service Initialization
- [ ] Check `cpx_service.py` initialization (lines 19-74)
- [ ] Verify constructor parameters
- [ ] Check if service is being injected into router

**Test Case:**
```python
# Check if CPX service is available
if cpx_service is None:
    print("❌ ERROR: CPX service not initialized")
else:
    print("✅ CPX service available")
    print(f"App ID: {cpx_service.app_id}")
    print(f"Timeout: {cpx_service.api_timeout}")
```

**Questions:**
1. Is CPX service initialized in main.py?
2. Are credentials loaded from environment?
3. Is service being injected into traffic router?

#### 4.2 Parameter Construction
- [ ] Check `fetch_and_allocate_for_respondent()` function (lines 480-900)
- [ ] Verify parameter building (lines 639-669)
- [ ] Check secure hash generation (lines 97-109)

**Critical Parameters to Validate:**
```python
params = {
    "app_id": ?,              # Must be valid CPX app ID
    "ext_user_id": ?,         # Must be vendor's rid (not internal traffic_id)
    "subid_1": ?,             # Our internal tracking ID
    "ip_user": ?,             # Must be valid public IP
    "user_agent": ?,          # Must be real browser UA
    "user_country_code": ?,   # Must be ISO2 (e.g., "IN", not "India")
    "email": ?,               # Must be valid email
    "birthday_day": ?,        # 1-31
    "birthday_month": ?,      # 1-12
    "birthday_year": ?,       # 4 digits
    "gender": ?,              # "m" or "f"
    "zip_code": ?,            # Non-empty string
    "secure_hash": ?          # MD5 hash
}
```

**Test Case:**
Add logging before CPX API call:
```python
print(f"📤 CPX API PARAMETERS:")
for key, value in params.items():
    if key != 'secure_hash':  # Don't print hash for security
        print(f"   {key}: {value} (type: {type(value).__name__})")
```

**Questions:**
1. Are all required parameters present?
2. Is ext_user_id the vendor's rid (not our traffic_id)?
3. Is user_country_code an ISO2 code ("IN" not "India")?
4. Are profiling parameters included?
5. Is secure_hash being generated correctly?

#### 4.3 API Request Execution
- [ ] Check API call (lines 689-709)
- [ ] Verify endpoint URL
- [ ] Check timeout setting
- [ ] Verify response parsing

**Test Case:**
```python
# Log full request
print(f"🔗 CPX API Endpoint: {self.BASE_URL}")
print(f"⏱️ Timeout: {self.api_timeout}s")
print(f"📤 Full request URL: {full_url}")  # Without hash

# After response
print(f"📥 Response status: {response.status_code}")
print(f"📥 Response body: {response.text[:500]}...")
```

**Questions:**
1. Is the API endpoint correct (https://live-api.cpx-research.com/api/get-surveys.php)?
2. Is the request timing out?
3. Is the response status 200 OK?
4. What does the response JSON contain?

#### 4.4 Response Parsing
- [ ] Check response parsing logic (lines 714-753)
- [ ] Verify survey extraction
- [ ] Check error handling

**Expected Response Structure:**
```json
{
  "status": "success",
  "count_available_surveys": 0,
  "count_returned_surveys": 0,
  "surveys": [],
  "message_not_found": "No surveys available"
}
```

**Questions:**
1. What is the value of `count_available_surveys`?
2. Is the `surveys` array empty?
3. Is there a `message_not_found` field?
4. What is the full response JSON?

#### 4.5 Filter Application
- [ ] Check filter settings (lines 782-788)
- [ ] Verify filter logic (lines 790-815)
- [ ] Check filtered results

**Current Filters:**
```python
max_loi = 20        # Maximum 20 minutes
min_cpi = 1.0       # Minimum $1 payout
min_ir = 0          # Minimum 0% incidence rate (no filter)
```

**Test Case:**
```python
# Log filtering
print(f"🔍 Filters: max_loi={max_loi}, min_cpi={min_cpi}, min_ir={min_ir}")
print(f"📊 Surveys before filter: {len(surveys)}")
print(f"📊 Surveys after filter: {len(filtered_surveys)}")

# Log rejected surveys
for survey in surveys:
    if survey not in filtered_surveys:
        print(f"❌ Rejected: LOI={survey.get('loi')}, CPI={survey.get('payout_publisher_usd')}")
```

**Questions:**
1. Are any surveys being returned from CPX?
2. Are filters too strict (rejecting all surveys)?
3. What are the LOI and CPI values of available surveys?

---

### Phase 5: CPX Response Analysis

**Task:** Analyze actual CPX API responses to determine why no surveys are allocated.

#### 5.1 Capture Full Response
- [ ] Enable full response logging (already at line 703-709)
- [ ] Run a real test with actual user data
- [ ] Capture the full JSON response

**Test Users to Try:**
```
Test 1 - India Adult Male:
- vid=123, cc=IN, rid=TEST_IN_M_001
- Email: test_in_male@example.com
- DOB: 1990-06-15 (34 years old)
- Gender: m
- Zip: 110001 (Delhi)

Test 2 - India Adult Female:
- vid=123, cc=IN, rid=TEST_IN_F_001
- Email: test_in_female@example.com
- DOB: 1985-03-20 (39 years old)
- Gender: f
- Zip: 400001 (Mumbai)

Test 3 - US Adult Male:
- vid=123, cc=US, rid=TEST_US_M_001
- Email: test_us_male@example.com
- DOB: 1990-06-15 (34 years old)
- Gender: m
- Zip: 10001 (New York)

Test 4 - US Adult Female:
- vid=123, cc=US, rid=TEST_US_F_001
- Email: test_us_female@example.com
- DOB: 1992-08-10 (32 years old)
- Gender: f
- Zip: 90001 (Los Angeles)
```

**Questions:**
1. Does CPX return surveys for India (IN)?
2. Does CPX return surveys for US?
3. What is the `count_available_surveys` for each test?
4. Are there any error messages in the response?

#### 5.2 Survey Quality Analysis
If surveys are returned, analyze them:

**Survey Quality Metrics:**
```python
for survey in surveys:
    print(f"Survey ID: {survey.get('id')}")
    print(f"  LOI: {survey.get('loi')} minutes")
    print(f"  Payout: ${survey.get('payout_publisher_usd')}")
    print(f"  Conversion Rate: {survey.get('conversion_rate')}%")
    print(f"  Click-to-Okay Rate: {survey.get('click_to_okay_rate')}%")
    print(f"  Quality Score: {survey.get('quality_score')}")
    print(f"  Href: {survey.get('href')[:80]}...")
```

**Questions:**
1. Are survey quality scores acceptable (>15)?
2. Are conversion rates reasonable (>25%)?
3. Do surveys have valid href URLs?
4. Are surveys passing your filters?

---

### Phase 6: Database & State Verification

**Task:** Verify database collections and state management.

#### 6.1 Collections Check
- [ ] Verify MongoDB collections exist
- [ ] Check indexes

**Collections Required:**
```python
# Check these collections
collections_to_check = [
    "traffic_flow_db.url_parameters",       # Traffic records
    "torpedo_settings.cpx_entry_guards",    # Entry guards
    "cpx_research.cpx_surveys",             # Survey cache (optional)
    "torpedo_settings.vendors",             # Vendor config
    "cpx_postback_logs",                    # Callback logs
]

for coll_name in collections_to_check:
    count = collection.count_documents({})
    print(f"Collection {coll_name}: {count} documents")
```

**Questions:**
1. Do all required collections exist?
2. Are indexes created on critical fields?
3. Are there any recent traffic records?

#### 6.2 Entry Guards Analysis
- [ ] Check entry guard collection
- [ ] Count duplicate attempts
- [ ] Identify problematic ext_user_ids

**Query:**
```python
# Check for duplicate attempts
duplicates = cpx_entry_guards_collection.find({
    "duplicate_attempt_count": {"$gt": 0}
}).limit(10)

for guard in duplicates:
    print(f"ext_user_id: {guard.get('ext_user_id')}")
    print(f"  Attempts: {guard.get('duplicate_attempt_count')}")
    print(f"  Status: {guard.get('status')}")
    print(f"  Created: {guard.get('created_at')}")
```

**Questions:**
1. Are there many duplicate attempts?
2. Are vendors reusing ext_user_ids?
3. Are guards being locked after failed allocation?

#### 6.3 Recent Traffic Analysis
- [ ] Query recent traffic records
- [ ] Check status distribution
- [ ] Identify patterns

**Query:**
```python
# Get last 20 traffic records
recent_traffic = url_parameters_collection.find({
    "createdAt": {"$gte": datetime.utcnow() - timedelta(hours=24)}
}).sort("createdAt", -1).limit(20)

status_counts = {}
for record in recent_traffic:
    status = record.get("status", "UNKNOWN")
    status_counts[status] = status_counts.get(status, 0) + 1

    print(f"Traffic ID: {record.get('_id')}")
    print(f"  Status: {status}")
    print(f"  Country: {record.get('countryCode')}")
    print(f"  Survey Allocated: {record.get('assignedSurveyId', 'None')}")
    print(f"  Redirect URL: {record.get('redirectUrl', 'None')[:80]}")
    print()

print(f"Status Distribution: {status_counts}")
```

**Questions:**
1. How many records in last 24 hours?
2. What is the status distribution (NEW, ALLOCATED, COMPLETE, etc.)?
3. How many have assigned surveys?
4. Are allocation_error fields populated?

---

### Phase 7: End-to-End Testing

**Task:** Perform complete end-to-end tests with logging at every step.

#### 7.1 Create Test Script
Create this test endpoint:

```python
@router.get("/api/audit/end-to-end-test")
async def audit_end_to_end_test():
    """
    Comprehensive end-to-end test of CPX integration
    Simulates a real user journey with full logging
    """
    results = {
        "test_timestamp": datetime.utcnow().isoformat(),
        "steps": []
    }

    # Step 1: Environment Check
    step1 = {
        "step": "1_environment_check",
        "status": "pending"
    }
    try:
        step1["cpx_app_id_present"] = bool(os.getenv("CPX_APP_ID"))
        step1["cpx_hash_present"] = bool(os.getenv("CPX_SECURE_HASH_KEY"))
        step1["status"] = "pass" if step1["cpx_app_id_present"] and step1["cpx_hash_present"] else "fail"
    except Exception as e:
        step1["status"] = "error"
        step1["error"] = str(e)
    results["steps"].append(step1)

    # Step 2: Service Initialization Check
    step2 = {
        "step": "2_service_check",
        "status": "pending"
    }
    try:
        step2["cpx_service_available"] = cpx_service is not None
        step2["collections_available"] = all([
            url_parameters_collection,
            cpx_entry_guards_collection,
            vendors_collection
        ])
        step2["status"] = "pass" if step2["cpx_service_available"] and step2["collections_available"] else "fail"
    except Exception as e:
        step2["status"] = "error"
        step2["error"] = str(e)
    results["steps"].append(step2)

    # Step 3: Test Parameter Construction
    step3 = {
        "step": "3_parameter_construction",
        "status": "pending"
    }
    try:
        test_params = {
            "vendor_user_id": "AUDIT_TEST_001",
            "internal_tracking_id": "AUDIT_SFWID_001",
            "user_ip": "8.8.8.8",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "country_code": "US",
            "email": "audit@example.com",
            "birthday_day": 15,
            "birthday_month": 6,
            "birthday_year": 1990,
            "gender": "m",
            "zip_code": "10001"
        }
        step3["parameters"] = test_params
        step3["all_params_valid"] = all(test_params.values())
        step3["status"] = "pass"
    except Exception as e:
        step3["status"] = "error"
        step3["error"] = str(e)
    results["steps"].append(step3)

    # Step 4: Entry Guard Check
    step4 = {
        "step": "4_entry_guard_check",
        "status": "pending"
    }
    try:
        guard_result = check_cpx_entry_guard(
            "AUDIT_TEST_001",
            "8.8.8.8",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )
        step4["guard_allowed"] = guard_result["allowed"]
        step4["guard_reason"] = guard_result["reason"]
        step4["status"] = "pass" if guard_result["allowed"] else "blocked"
    except Exception as e:
        step4["status"] = "error"
        step4["error"] = str(e)
    results["steps"].append(step4)

    # Step 5: WebView Detection Check
    step5 = {
        "step": "5_webview_detection",
        "status": "pending"
    }
    try:
        test_ua_normal = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        test_ua_webview = "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.0.0 Mobile Safari/537.36"

        is_wv_normal, _ = is_webview_user_agent(test_ua_normal)
        is_wv_webview, sig = is_webview_user_agent(test_ua_webview)

        step5["normal_ua_correctly_allowed"] = not is_wv_normal
        step5["webview_ua_correctly_blocked"] = is_wv_webview
        step5["webview_signature_detected"] = sig
        step5["status"] = "pass" if step5["normal_ua_correctly_allowed"] and step5["webview_ua_correctly_blocked"] else "fail"
    except Exception as e:
        step5["status"] = "error"
        step5["error"] = str(e)
    results["steps"].append(step5)

    # Step 6: CPX API Call (Multiple Countries)
    step6 = {
        "step": "6_cpx_api_call",
        "status": "pending",
        "country_tests": []
    }

    if cpx_service:
        countries_to_test = ["IN", "US", "GB", "CA"]

        for country in countries_to_test:
            try:
                # Clean up guard for test
                if cpx_entry_guards_collection:
                    cpx_entry_guards_collection.delete_one({"ext_user_id": f"AUDIT_{country}_001"})

                result = cpx_service.fetch_and_allocate_for_respondent(
                    vendor_user_id=f"AUDIT_{country}_001",
                    internal_tracking_id="AUDIT_SFWID",
                    user_ip="8.8.8.8",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    country_code=country,
                    email="audit@example.com",
                    birthday_day=15,
                    birthday_month=6,
                    birthday_year=1990,
                    gender="m",
                    zip_code="10001"
                )

                country_result = {
                    "country": country,
                    "success": result.get("success"),
                    "error": result.get("error"),
                    "has_survey": bool(result.get("survey_id"))
                }

                step6["country_tests"].append(country_result)

            except Exception as e:
                step6["country_tests"].append({
                    "country": country,
                    "success": False,
                    "error": str(e)
                })

        # Check if at least one country has surveys
        any_success = any(t["success"] for t in step6["country_tests"])
        step6["status"] = "pass" if any_success else "fail"
        step6["summary"] = f"{sum(1 for t in step6['country_tests'] if t['success'])}/{len(countries_to_test)} countries have surveys"
    else:
        step6["status"] = "error"
        step6["error"] = "CPX service not available"

    results["steps"].append(step6)

    # Overall Status
    all_statuses = [s["status"] for s in results["steps"]]
    if "error" in all_statuses:
        results["overall_status"] = "error"
    elif "fail" in all_statuses:
        results["overall_status"] = "fail"
    elif "blocked" in all_statuses:
        results["overall_status"] = "blocked"
    else:
        results["overall_status"] = "pass"

    # Add recommendations
    results["recommendations"] = []

    if not results["steps"][0]["status"] == "pass":
        results["recommendations"].append("Fix environment variables - CPX credentials missing")

    if not results["steps"][1]["status"] == "pass":
        results["recommendations"].append("Fix service initialization - CPX service or collections not available")

    if not results["steps"][5]["status"] == "pass":
        results["recommendations"].append("CRITICAL: CPX API not returning surveys for any country - Contact CPX support")

    if results["steps"][5]["status"] == "pass":
        failed_countries = [t["country"] for t in results["steps"][5]["country_tests"] if not t["success"]]
        if failed_countries:
            results["recommendations"].append(f"CPX has no surveys for: {', '.join(failed_countries)}")

    return results
```

#### 7.2 Run Test and Analyze Results

**Execute:**
```bash
curl https://yoursite.com/api/audit/end-to-end-test
```

**Expected Output:**
```json
{
  "test_timestamp": "2026-02-08T10:30:00.000Z",
  "overall_status": "fail",
  "steps": [
    {"step": "1_environment_check", "status": "pass"},
    {"step": "2_service_check", "status": "pass"},
    {"step": "3_parameter_construction", "status": "pass"},
    {"step": "4_entry_guard_check", "status": "pass"},
    {"step": "5_webview_detection", "status": "pass"},
    {
      "step": "6_cpx_api_call",
      "status": "fail",
      "country_tests": [
        {"country": "IN", "success": false, "error": "No surveys available from CPX"},
        {"country": "US", "success": true, "has_survey": true},
        {"country": "GB", "success": true, "has_survey": true},
        {"country": "CA", "success": false, "error": "No surveys available from CPX"}
      ]
    }
  ],
  "recommendations": [
    "CPX has no surveys for: IN, CA"
  ]
}
```

---

### Phase 8: Logging & Monitoring Audit

**Task:** Verify logging is comprehensive and accessible.

#### 8.1 Required Log Messages
Verify these log messages exist at critical points:

**Frontend Logs (Browser Console):**
- [ ] IP collection: `"✅ Fetched client IP: X.X.X.X from https://..."`
- [ ] Fingerprint: `"🔐 Device fingerprint: fp_..."`
- [ ] Fresh IP: `"✅ Using FRESH IP: X.X.X.X"`
- [ ] IP rotation: `"⚠️ IP ROTATION DETECTED: ..."`

**Backend Logs (Python Console):**
- [ ] Traffic creation: `"✅ Created traffic record (SFWID): ..."`
- [ ] Entry guard: `"✅ CPX ENTRY GUARD: Registered new ext_user_id..."`
- [ ] CPX request: `"📤 CPX REQUEST URL: ..."`
- [ ] CPX response: `"📥 CPX FULL RESPONSE: ..."`
- [ ] Allocation: `"✅ Allocated CPX survey X to SFWID=Y"`
- [ ] Blocks: `"🚫 CPX ENTRY GUARD BLOCK: ..."` or `"🚫 WEBVIEW DETECTED: ..."`

#### 8.2 Log Verification Test
For each test user, verify you can trace the full journey in logs:

```
1. User lands on page → IP prefetch log
2. User fills form → No logs (client-side)
3. User clicks "Next" → Fresh IP fetch log
4. Request sent → Backend receives log
5. Traffic created → Traffic ID log
6. Entry guard check → Guard result log
7. CPX API call → Request URL log
8. CPX response → Full response log
9. Allocation → Success or failure log
10. Redirect → Redirect log
```

**Questions:**
1. Can you trace the full journey for a specific user?
2. Are there any gaps in logging?
3. Are error conditions being logged?

---

### Phase 9: Production Data Analysis

**Task:** Analyze actual production screenout data.

#### 9.1 Screenout Report Analysis
Using the provided screenout report:

**Data Points:**
- Total entries: 36
- Instant screenouts (0 sec): 34 (94%)
- Early screenouts: 2 (6%)
- Already clicked: 2 (6%)
- Country: 100% India
- Devices: 80% mobile, 20% desktop

**Query Traffic Database:**
```python
# Get all IN traffic from last 7 days
in_traffic = url_parameters_collection.find({
    "countryCode": "IN",
    "createdAt": {"$gte": datetime.utcnow() - timedelta(days=7)}
})

total = 0
allocated = 0
completed = 0

for record in in_traffic:
    total += 1
    if record.get("assignedSurveyId"):
        allocated += 1
    if record.get("status") == "COMPLETE":
        completed += 1

print(f"India Traffic Stats:")
print(f"  Total: {total}")
print(f"  Allocated: {allocated} ({allocated/total*100:.1f}%)")
print(f"  Completed: {completed} ({completed/total*100:.1f}%)")
```

**Questions:**
1. What percentage of India traffic gets allocated surveys?
2. What is the completion rate for India?
3. How does this compare to other countries (US, GB)?

#### 9.2 Compare with Working Countries
```python
# Compare allocation rates across countries
countries = ["IN", "US", "GB", "CA", "AU"]
stats = []

for country in countries:
    traffic = url_parameters_collection.find({
        "countryCode": country,
        "createdAt": {"$gte": datetime.utcnow() - timedelta(days=7)}
    })

    total = traffic.count()
    allocated = url_parameters_collection.count_documents({
        "countryCode": country,
        "assignedSurveyId": {"$ne": None},
        "createdAt": {"$gte": datetime.utcnow() - timedelta(days=7)}
    })

    stats.append({
        "country": country,
        "total": total,
        "allocated": allocated,
        "allocation_rate": (allocated/total*100) if total > 0 else 0
    })

for stat in stats:
    print(f"{stat['country']}: {stat['allocation_rate']:.1f}% allocation rate")
```

---

## 🎯 FINAL AUDIT REPORT FORMAT

After completing all phases, compile results in this format:

```markdown
# CPX Integration Audit Report
**Date:** [Date]
**Auditor:** [Name]
**System Version:** [Version]

## Executive Summary
- Overall Status: [PASS / FAIL / BLOCKED / ERROR]
- Critical Issues Found: [Number]
- Warnings: [Number]
- Root Cause: [Brief description]

## Phase Results

### Phase 1: Environment & Configuration ✅/❌
- Status: [PASS/FAIL]
- Issues: [List]
- Details: [Explanation]

### Phase 2: Frontend Data Collection ✅/❌
- Status: [PASS/FAIL]
- Issues: [List]
- Details: [Explanation]

### Phase 3: Backend Request Processing ✅/❌
- Status: [PASS/FAIL]
- Issues: [List]
- Details: [Explanation]

### Phase 4: CPX API Call ✅/❌
- Status: [PASS/FAIL]
- Issues: [List]
- CPX Response Summary:
  - India (IN): [count_available_surveys]
  - US: [count_available_surveys]
  - GB: [count_available_surveys]

### Phase 5: CPX Response Analysis ✅/❌
- Status: [PASS/FAIL]
- Survey Availability:
  - India: [Yes/No]
  - US: [Yes/No]
  - UK: [Yes/No]

### Phase 6: Database & State ✅/❌
- Status: [PASS/FAIL]
- Collections: [All present / Missing: X]
- Entry Guards: [Working / Issues]

### Phase 7: End-to-End Testing ✅/❌
- Test Results: [X/Y tests passed]
- Details: [Summary]

### Phase 8: Logging & Monitoring ✅/❌
- Status: [PASS/FAIL]
- Logging Coverage: [X%]

### Phase 9: Production Data Analysis ✅/❌
- India Allocation Rate: [X%]
- US Allocation Rate: [Y%]
- Comparison: [Analysis]

## Root Cause Analysis

### Primary Issue
[Detailed explanation of the main problem]

### Contributing Factors
1. [Factor 1]
2. [Factor 2]

### Evidence
- [Evidence 1]
- [Evidence 2]

## Recommendations

### Immediate Actions (Must Do)
1. [Action 1]
2. [Action 2]

### Short-term Improvements (Should Do)
1. [Action 1]
2. [Action 2]

### Long-term Enhancements (Nice to Have)
1. [Action 1]
2. [Action 2]

## Conclusion
[Final summary and next steps]
```

---

## 🔧 EXECUTION INSTRUCTIONS

**How to Use This Audit Prompt:**

1. **Provide this entire prompt to an AI assistant** (Claude, GPT-4, etc.)

2. **Give access to your codebase** via file reading tools

3. **Execute systematically:**
   - Start with Phase 1
   - Complete all checks in each phase before moving to next
   - Document findings in each phase
   - Stop if critical blocker found (e.g., missing credentials)

4. **Generate logs:**
   - Enable verbose logging
   - Capture all output
   - Save API responses

5. **Compile report:**
   - Use the provided report format
   - Include evidence (logs, screenshots, API responses)
   - Provide actionable recommendations

6. **Validate findings:**
   - Test recommendations
   - Verify fixes work
   - Re-run audit to confirm resolution

---

## ⚠️ CRITICAL SUCCESS CRITERIA

The audit is successful when you can answer these questions:

1. ✅ Can you trace a user's full journey from frontend to CPX API in logs?
2. ✅ Do you know exactly what CPX returns (count_available_surveys value)?
3. ✅ Can you identify which countries have surveys vs. which don't?
4. ✅ Do you know the exact parameters being sent to CPX?
5. ✅ Can you reproduce the issue with a test user?
6. ✅ Do you have concrete evidence of the root cause?

**If you can answer all 6 questions, you've found the issue.**

---

## 📞 SUPPORT

If the audit reveals issues beyond your understanding:

1. **CPX-specific issues:** Contact CPX support with audit findings
2. **Technical issues:** Review CPX_INTEGRATION_GUIDE.md
3. **Code issues:** Check implementation against documented best practices

---

**END OF AUDIT PROMPT**
