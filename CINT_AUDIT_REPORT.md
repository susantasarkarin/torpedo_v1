# CINT IMPLEMENTATION AUDIT REPORT

**Date:** February 3, 2026  
**Status:** AUDIT PHASE - No production implementation yet  
**Scope:** Comparison of CPX vs Cint API integration patterns  

---

## EXECUTIVE SUMMARY

**Current State:**
- ✅ **Cint service partially implemented** with skeleton code for subscriptions, opportunity ingestion, and entry links
- ✅ **Cint models defined** in Pydantic (CintOpportunity, SupplierLink, etc.)
- ✅ **Callback routing in place** at `/cint-response` endpoint
- ⚠️ **Critical gaps identified** that must be fixed before production use
- ❌ **CPX and Cint are NOT interchangeable** - they have fundamentally different architectures

---

## PART 1: CPX IMPLEMENTATION AUDIT

### Correct/Complete Implementation

**CPX Entry Link Generation (CORRECT)**
- **Location:** `cpx_service.py` lines 152-210 (`generate_respondent_entry_link()`)
- **How it works:**
  - CPX API returns surveys with encrypted `href` (click.cpx-research.com/?k=<encrypted>&...)
  - The `k=` parameter is already encrypted by CPX for our app_id/ext_user_id
  - We append `subid_1=respondent_id` to the href for respondent tracking
  - Entry links are **generated dynamically per allocation** (not pre-cached)
- **Why this is correct:**
  - CPX validates the respondent_id via subid_1 callback
  - The href encryption validates that the API call was legitimate
  - No pre-generation needed; links are stateless

**CPX Survey Filtering (CORRECT)**
- **Location:** `cpx_service.py` lines 238-293 (`_apply_filters()`, `sync_active_status_by_filters()`)
- **How it works:**
  - Filter by max_loi, min_cpi, min_ir
  - Store ALL surveys, apply filters at query/display time
  - `is_active_in_pool` flag marks surveys that pass current filters
- **Why this is correct:**
  - Allows dynamic filter changes without re-fetching
  - Keeps history of all returned surveys for analytics
  - Scalable to large inventory

**CPX Callback Handling (MOSTLY CORRECT)**
- **Location:** `traffic.py` lines 173-226 (`cpx_callback()`)
- **How it works:**
  - Maps CPX response types to internal statuses (complete/terminate)
  - Finds traffic record by trans_id or sfwid (subid_1)
  - Updates status and redirects
- **Minor issue:** Doesn't validate that trans_id actually came from CPX (no signature verification), but CPX callback is deterministic so risk is low

---

## PART 2: CINT IMPLEMENTATION AUDIT

### What IS Implemented (Skeleton)

| Feature | Location | Status | Notes |
|---------|----------|--------|-------|
| API Authentication | `cint_service.py` L618-623 | ✅ Correct | Uses `Authorization` header with API key |
| Webhook Signature Validation | `cint_service.py` L632-643 | ✅ Correct | HMAC-SHA256 validation implemented |
| Opportunity Webhook Processing | `cint_service.py` L1003-1094 | ⚠️ Partial | Parses webhooks but doesn't validate all fields |
| Entry Link Storage | `cint_service.py` L1165-1180 | ✅ Correct | Stores supplier links from Cint API |
| Respondent Outcome Processing | `cint_service.py` L835-915 | ⚠️ Incomplete | Status mapping present but callback verification missing |
| Legacy Fulcrum API (polling) | `cint_service.py` L462-550 | ⚠️ Deprecated | Implemented but should not be primary path |
| Filter Settings | `cint_service.py` L229-297 | ✅ Correct | Same as CPX (max_loi, min_cpi, min_incidence) |
| Survey Queries | `cint_service.py` L1309-1448 | ⚠️ Incomplete | Queries work but qualification filtering missing |

### What IS MISSING (Blockers)

#### 🔴 BLOCKER 1: Subscription Correctness Not Validated
- **Location:** `cint_service.py` L649-712 (`create_opportunities_subscription()`)
- **Issue:** 
  - Code assumes webhook URL structure is correct but doesn't validate response
  - No persistent storage of subscription status
  - No retry logic if subscription creation fails
  - Webhook callback URL is hardcoded in service code, not configurable per deployment
- **Impact:** Opportunities may never be received from Cint
- **Fix Required:** 
  - Store subscription creation response and validate status
  - Make callback URLs configurable via environment/settings
  - Implement subscription health checks

#### 🔴 BLOCKER 2: Entry Link Generation NOT Implemented for Respondents
- **Location:** `cint_service.py` L1268-1285 (`build_entry_link()`)
- **Issue:**
  - Code builds a URL with params, but **never calls Cint API to create the link**
  - CPX-style parameterized links do NOT work with Cint
  - Cint requires calling `Supply/v1/SupplierLinks/Create` endpoint with specific config
  - Current code assumes live_link is already set, but it's not created per-respondent
- **Impact:** Respondents cannot enter surveys through Cint
- **Fix Required:**
  - Entry links must be created ONCE per survey (not per respondent)
  - Per-respondent links use built-in parameters from Cint, NOT custom URL construction
  - Reference: `SupplierLink` model has `live_link` (from Cint API) which is the actual entry point

#### 🔴 BLOCKER 3: Qualification/Precodes NOT Implemented
- **Location:** Missing entirely
- **Issue:**
  - Cint provides qualifications via `survey_qualifications` in opportunities webhook
  - These use standard qualification IDs + precodes (e.g., "q23-1" for age 18-24)
  - No logic to validate respondent profile against qualifications
  - No mapping between respondent attributes and Cint standard quals
- **Impact:** Survey allocations will fail or return disqualified respondents
- **Fix Required:**
  - Implement qualification validator using Cint standard IDs
  - Map respondent attributes (age, income, etc.) to qualification precodes
  - Fail fast if respondent doesn't qualify before routing

#### 🔴 BLOCKER 4: Callback Verification NOT Implemented
- **Location:** `traffic.py` L88-172 (`cint_callback()`)
- **Issue:**
  - Callback endpoint doesn't verify that callback came from Cint
  - No HMAC signature validation (unlike webhook validation)
  - Respondent outcomes should be verified before marking as complete
- **Impact:** Fraudulent callbacks could credit false completes
- **Fix Required:**
  - Add webhook signature validation to callback endpoint
  - Verify respondent_id matches session in outcomes collection
  - Implement idempotency (same callback twice = one credit)

#### 🔴 BLOCKER 5: Status Mapping is Oversimplified
- **Location:** `cint_service.py` L840-858
- **Issue:**
  - Only maps marketplace_status codes 10, 20, 30, 40, 50
  - Doesn't handle client_status variations
  - Missing statuses: survey_closed (code 50), supplier_terminate vs quality_terminate distinction
- **Impact:** Incorrect status reporting in analytics
- **Fix Required:**
  - Map both marketplace_status AND client_status per Cint docs
  - Handle all 5+ status codes correctly
  - Store both original and mapped status for debugging

#### 🔴 BLOCKER 6: No Yield Management / Traffic Control
- **Location:** Missing entirely
- **Issue:**
  - CPX can handle 500+ simultaneous starts (stateless)
  - Cint tracks per-respondent state and recontacts
  - No quota pacing, ranking, or incidence rate management
  - Opportunities are not deprioritized as quota fills
- **Impact:** Will over-allocate and waste quota
- **Fix Required:**
  - Implement basic ranking (sort by conversion > CPI > LOI)
  - Integrate with survey_allocation_service for metrics
  - TODO: Full yield management deferred to Phase 2

#### 🔴 BLOCKER 7: Entry Link Creation Flow is Incomplete
- **Location:** `cint_service.py` L1146-1211 (`create_entry_link()`, `get_entry_link()`)
- **Issue:**
  - Code calls Cint API correctly to create entry links
  - BUT: `_auto_create_entry_link()` (L1082-1106) assumes this works
  - Entry links are created ONCE per survey, not per respondent
  - After creation, `live_link` is retrieved from response and stored
  - BUT: allocation code at L1268 uses `build_entry_link()` instead of retrieving stored link
- **Impact:** Incorrect entry points used for respondent allocation
- **Fix Required:**
  - After entry link created via API, always retrieve via `get_entry_link()`
  - Use the stored `live_link` from that response
  - Per-respondent parameters appended to live_link, NOT replacing it

---

## PART 3: CPX vs CINT ARCHITECTURAL COMPARISON

### Key Differences (MUST NOT confuse these)

| Aspect | CPX | Cint |
|--------|-----|------|
| **Inventory Model** | Polling (getAllSurveys every N minutes) | Subscription (push webhook with opportunities) |
| **Link Type** | Dynamic URL composition per respondent | Static link + per-respondent parameters |
| **Link Generation** | Stateless (no API call needed) | Stateful (must call Create endpoint first) |
| **Authentication** | App-level (app_id, secure_hash) | API-key level (Authorization header) |
| **Respondent Tracking** | subid_1 & subid_2 parameters | [%MID%], [%REVENUE%] placeholders |
| **Status Codes** | Custom (0=complete, 1=screenout, etc.) | Standard (10=complete, 20=terminate, etc.) |
| **Callback Validation** | Callback URL hardcoded in entry link | Signature-verified webhook + outcomes webhook |
| **Recontact** | Not supported natively | Built-in via survey_group_ids |
| **Quotas** | Implicit in total_remaining | Explicit survey_quotas array with details |
| **Qualifications** | Not in API response | Full survey_qualifications with precodes |

### Reusable Patterns (CPX → Cint)

✅ **Filter Logic** - Same structure:
```python
# Both use: max_loi, min_cpi, min_incidence
# Both store ALL surveys, filter at query time
# Both support dynamic filter changes
```

✅ **MongoDB Schema** - Similar structure:
```python
# Both track: survey_id, title, payout, loi, country, created_at, click_count
# Both use $setOnInsert for immutable fields
# Both use is_active_in_pool for activation status
```

✅ **Metrics Tracking** - Same pattern:
```python
# Both increment click_count on allocation
# Both store last_clicked_at timestamp
# Both integrate with survey_allocation_service
```

### Anti-Patterns (CPX ≠ Cint)

❌ **DO NOT reuse CPX entry link generation**
- CPX: `generate_respondent_entry_link()` (append subid_1 to href)
- Cint: Must use Cint-provided live_link + parameter format

❌ **DO NOT poll Cint like CPX**
- CPX: fetch_cpx_surveys() called on schedule
- Cint: Always use webhook subscription (legacy API only for fallback)

❌ **DO NOT use CPX security model**
- CPX: HMAC-MD5 of secure_hash_key
- Cint: API key in Authorization header + HMAC-SHA256 for webhooks

---

## PART 4: CINT-SPECIFIC REQUIREMENTS FROM DOCUMENTATION

### Subscription Rules (MUST IMPLEMENT)

1. **Callback URL Structure**
   - Must be HTTPS (no HTTP in production)
   - Must include protocol, domain, and path
   - Example: `https://torpedo.cogentixresearch.com/webhooks/cint-opportunities`
   
2. **Webhook Payload**
   - May contain 1-N opportunities in array
   - May be batched (multiple updates in single webhook)
   - Must validate HMAC-SHA256 signature from X-Cint-Signature header

3. **Retry Logic**
   - Cint retries webhook delivery up to 48 hours
   - Must return HTTP 200 within 30 seconds
   - Duplicate deliveries possible (idempotency required)

### Entry Link Rules (MUST IMPLEMENT)

1. **Link Creation**
   - POST /Supply/v1/SupplierLinks/Create/{SurveyNumber}/{SupplierCode}
   - Must specify: default_link, success_link, failure_link, over_quota_link, quality_termination_link
   - Each URL must be < 2999 characters
   - Returns live_link (what respondent actually clicks)
   - Returns test_link (for QA)

2. **Link Parameters**
   - Cint provides standard parameter placeholders: [%MID%], [%REVENUE%], [%SID%], etc.
   - These are replaced by Cint when respondent clicks
   - DO NOT append custom parameters to live_link (Cint will reject)

3. **Link Callbacks**
   - success_link = respondent completed survey
   - failure_link = respondent started but terminated
   - over_quota_link = survey quota filled
   - quality_termination_link = Cint detected bot/fraud

### Respondent Outcome Rules (MUST IMPLEMENT)

1. **Status Codes**
   ```
   marketplace_status:
     10 = COMPLETE (paid)
     20 = TERMINATE (started, screened out)
     30 = OVER_QUOTA (survey full)
     40 = QUALITY_TERMINATE (fraud detected)
     50 = SURVEY_CLOSED (survey paused/ended)
   ```

2. **Callback Validation**
   - POST from Cint with respondent outcome
   - Signature validation required
   - Must handle duplicate deliveries (idempotent)
   - Must extract payout from rpi.value field

3. **Respondent Identification**
   - respondent_id = Cint's panelist ID
   - session_id = Cint's session ID (maps to [%MID%])
   - parent_session_id = Original session if recontact
   - These link outcomes back to respondent records

---

## PART 5: CURRENT BLOCKERS - PRIORITY ORDER

### P0 - MUST FIX BEFORE FIRST DEPLOYMENT

1. **Subscription Correctness** (L649-712)
   - Validate subscription creation response
   - Store subscription status persistently
   - Implement subscription health checks
   - Make webhook callback URL configurable

2. **Entry Link Creation & Retrieval** (L1082-1211)
   - Entry links must be created via Cint API, not dynamically built
   - Use `get_entry_link()` to retrieve stored live_link
   - Fix allocation code to use stored link, not build_entry_link()

3. **Callback Verification** (traffic.py L88-172)
   - Add webhook signature validation
   - Verify respondent_id against outcomes database
   - Implement idempotency check (no double-credits)

4. **Status Mapping Completeness** (cint_service.py L840-858)
   - Map ALL status codes (10, 20, 30, 40, 50)
   - Distinguish marketplace_status from client_status
   - Store both for debugging

### P1 - SHOULD FIX BEFORE PRODUCTION TRAFFIC

5. **Qualification Validation** (Missing)
   - Parse survey_qualifications from webhook
   - Map respondent attributes to standard qual IDs
   - Fail fast if respondent doesn't qualify

6. **Basic Traffic Control** (Missing)
   - Implement survey ranking (conversion > CPI > LOI)
   - Deprioritize surveys as quota fills
   - Integrate with SurveyAllocationService metrics

7. **Error Handling & Logging** (Partial)
   - Add detailed logging for each allocation step
   - Log all API errors with context
   - Add monitoring for webhook delivery failures

### P2 - DEFER TO PHASE 2

- Full yield management system
- Machine learning-based ranking
- Advanced recontact logic
- Cross-provider optimization

---

## PART 6: VERIFICATION CHECKLIST

Before moving to implementation phase, verify:

- [ ] Cint API credentials (api_key, supplier_code) are available
- [ ] Webhook callback URLs are defined (opportunities and outcomes)
- [ ] MongoDB collections created: cint_research.cint_surveys, cint_research.cint_entry_links, etc.
- [ ] SSL certificates valid for webhook callback URLs
- [ ] Entry link redirect URLs defined (success, failure, quota_full, quality_term)
- [ ] Test mode vs production mode environment configuration ready
- [ ] Integration tests can be run against Cint sandbox

---

## CONCLUSION

**Status:** ✅ Architecture sound, 🔴 **Critical blockers require immediate fixes**

The Cint integration has the right structure but is missing critical implementation pieces:
1. Subscription validation
2. Proper entry link flow (create via API, retrieve via API, use in allocation)
3. Callback verification
4. Qualification validation

**Next Steps:** Proceed to implementation phase in priority order (P0 → P1 → P2).

