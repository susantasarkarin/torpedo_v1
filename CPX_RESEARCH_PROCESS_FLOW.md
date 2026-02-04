# CPX Research Process Flow

## Overview
This document provides a graphical representation of the CPX Research survey integration process flow.

---

## 🔄 Complete Process Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CPX RESEARCH INTEGRATION FLOW                        │
└─────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: SURVEY INVENTORY SYNC (Background Process)                              │
├───────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  [Platform Server - CPXService.fetch_cpx_surveys()]                              │
│        │                                                                          │
│        ├─── 1. PREPARE API REQUEST                                               │
│        │    • Generate secure_hash = MD5(ext_user_id + secure_hash_key)          │
│        │    • Set ip_user = hardcoded Indian IP (103.21.124.1)                   │
│        │      → Ensures CPX returns India-relevant surveys regardless of         │
│        │        server location (US/EU/Asia VMs)                                 │
│        │    • Set user_agent = browser string                                    │
│        │    • Set limit = 1000 (max surveys to fetch)                            │
│        │                                                                          │
│        ├─── 2. CALL CPX API                                                      │
│        │    GET https://live-api.cpx-research.com/api/get-surveys.php            │
│        │    Query Parameters:                                                    │
│        │    • app_id = "10754" (CPX app identifier)                              │
│        │    • ext_user_id = "PANEL_88921" (platform panel ID)                    │
│        │    • subid_1 = "" (empty for inventory fetch)                           │
│        │    • subid_2 = "" (empty for inventory fetch)                           │
│        │    • output_method = "api" (JSON response)                              │
│        │    • ip_user = Indian IP for geo-targeting                              │
│        │    • user_agent = browser string                                        │
│        │    • limit = 1000                                                       │
│        │    • secure_hash = MD5 hash for authentication                          │
│        │    Timeout: 30 seconds                                                  │
│        │                                                                          │
│        ├─── 3. PARSE API RESPONSE                                                │
│        │    CPX API Response Formats (handled all 3):                            │
│        │    Format 1: { "surveys": [...] }                                       │
│        │    Format 2: { "count_available_surveys": N, "info": [...] }            │
│        │    Format 3: { "message_not_found": true } → No surveys                 │
│        │                                                                          │
│        │    Each survey contains:                                                │
│        │    {                                                                    │
│        │      "id": "12345",                                                     │
│        │      "survey_title": "Consumer Opinion Survey",                        │
│        │      "loi": 10,                        // Length in minutes            │
│        │      "payout_publisher_usd": 2.50,     // Payout in USD                │
│        │      "conversion_rate": 75,            // Success rate %               │
│        │      "survey_category": "Health",                                      │
│        │      "href": "https://click.cpx-research.com/?k=aB3fD...",             │
│        │      "href_new": "https://click.cpx-research.com/?k=xyz..."            │
│        │    }                                                                    │
│        │                                                                          │
│        ├─── 4. NORMALIZE SURVEY DATA                                             │
│        │    Map CPX fields to internal schema:                                   │
│        │    • _id = survey_id (MongoDB primary key)                              │
│        │    • loi: minutes → float                                               │
│        │    • payout: USD → float                                                │
│        │    • country: defaults to "ALL" (no filter)                             │
│        │    • href: CPX click URL with k= token (CRITICAL for tracking)          │
│        │    • href_new: mobile-optimized version                                 │
│        │    • raw_data: full CPX response (for debugging)                        │
│        │    • provider: "CPX"                                                    │
│        │    • last_updated: current UTC timestamp                                │
│        │                                                                          │
│        ├─── 5. UPSERT TO DATABASE                                                │
│        │    MongoDB: cpx_research.cpx_surveys                                    │
│        │    Operation: update_one with upsert=True                               │
│        │    • $set: all survey fields (overwrites on update)                     │
│        │    • $setOnInsert: fields set only on first insert:                     │
│        │      - created_at: UTC timestamp                                        │
│        │      - click_count: 0 (incremented by allocation)                       │
│        │      - last_clicked_at: null                                            │
│        │      - is_active_in_pool: false (must be activated manually)            │
│        │                                                                          │
│        │    IMPORTANT: NO filtering during ingestion - all surveys stored!       │
│        │    Filters are applied only during display/allocation.                  │
│        │                                                                          │
│        └─── 6. CREATE DATABASE INDEXES                                           │
│             Performance optimization for filtering/sorting:                      │
│             • last_updated (DESC) - for "newest first" sorting                   │
│             • loi (ASC) - for LOI range filters                                  │
│             • payout (DESC) - for payout filters                                 │
│             • country (ASC) - for country filtering                              │
│             • category (ASC) - for category filtering                            │
│             • Compound: (country, last_updated) - common filter + sort           │
│             • is_active_in_pool - for active survey queries                      │
│             All indexes created with background=True (no blocking)               │
│                                                                                   │
│  [SYNC TRIGGERS]                                                                  │
│  • Manual: Admin clicks "Refresh Surveys" in UI                                  │
│  • Scheduled: Celery/cron job (every 15-30 minutes recommended)                  │
│  • On-demand: API endpoint /api/cpx/refresh                                      │
│  • Result: 500-1000 surveys synced in ~5-10 seconds                              │
│                                                                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: RESPONDENT ALLOCATION (Real-time Request)                               │
├───────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  [Parsing Page - Frontend]                                                        │
│        │                                                                          │
│        ├─── 1. RESPONDENT CLICKS "PROCEED" BUTTON                                │
│        │    User Action: Click PROCEED button on parsing page                    │
│        │    TrafficFlowParser.jsx handles the click                              │
│        │                                                                          │
│        ├─── 2. PASSIVELY COLLECT IPv4 + DIGITAL FINGERPRINT                      │
│        │    Client-side JavaScript captures:                                     │
│        │    • IPv4 Address: Extracted from request headers                       │
│        │    • Device Fingerprint: Generated from:                                │
│        │      - User Agent (navigator.userAgent)                                 │
│        │      - Language (navigator.language)                                    │
│        │      - Platform (navigator.platform)                                    │
│        │      - Timezone (Intl.DateTimeFormat)                                   │
│        │      - Screen resolution (width × height × colorDepth)                  │
│        │      - Hardware concurrency (CPU cores)                                 │
│        │      - Device memory                                                    │
│        │      - Max touch points                                                 │
│        │    • Fingerprint Hash: SHA-256 of combined components                   │
│        │    • Example: fp_a3f2b8d91c7e5...                                       │
│        │                                                                          │
│        ├─── 3. SEND TO BACKEND                                                   │
│        │    POST /api/store                                                      │
│        │    Body: {                                                              │
│        │      url: full_url,                                                     │
│        │      params: { vid, cc, rid },                                          │
│        │      userAgent: navigator.userAgent,                                    │
│        │      deviceFingerprint: "fp_a3f2b8d91c7e5...",                          │
│        │      fingerprintComponents: { userAgent, language, ... },               │
│        │      fingerprintSource: "client"                                        │
│        │    }                                                                    │
│        │                                                                          │
│  [Backend - Step 2: CALL CPX API IMMEDIATELY]                                    │
│        │                                                                          │
│        ├─── 4. EXTRACT REAL CLIENT IP FROM HEADERS                               │
│        │    Priority order (prefer IPv4):                                        │
│        │    1. CF-Connecting-IP (CloudFlare direct client IP)                    │
│        │    2. X-Forwarded-For[0] (leftmost = original client)                   │
│        │    3. X-Real-IP (Nginx reverse proxy)                                   │
│        │    4. request.client.host (direct connection)                           │
│        │    Result: client_ip = "103.21.124.1" (IPv4 preferred)                  │
│        │                                                                          │
│        ├─── 5. CALL CPX API WITH IP + FINGERPRINT                                │
│        │    API Call: cpx_service.fetch_and_allocate_for_respondent()            │
│        │    • ext_user_id: "TEMP_{rid}_{timestamp}" (temporary ID)               │
│        │    • ip_user: "103.21.124.1" (real client IPv4)                         │
│        │    • user_agent: "Mozilla/5.0 ..." (real user agent)                    │
│        │                                                                          │
│        │    CPX API Request:                                                     │
│        │    GET https://live-api.cpx-research.com/api/get-surveys.php            │
│        │    Params:                                                              │
│        │    • app_id = "10754"                                                   │
│        │    • ext_user_id = "TEMP_456789_1738588800"                             │
│        │    • ip_user = "103.21.124.1"                                           │
│        │    • user_agent = "Mozilla/5.0 ..."                                     │
│        │    • secure_hash = MD5(ext_user_id + secure_hash_key)                   │
│        │                                                                          │
│        ├─── 6. CPX RETURNS AVAILABLE SURVEYS + HREF LINKS                        │
│        │    CPX Response: {                                                      │
│        │      "surveys": [                                                       │
│        │        {                                                                │
│        │          "id": "12345",                                                 │
│        │          "loi": 10,                                                     │
│        │          "payout_publisher_usd": 2.50,                                  │
│        │          "conversion_rate": 75,                                         │
│        │          "href": "https://click.cpx-research.com/?k=aB3fD..."           │
│        │        },                                                               │
│        │        { ... more surveys ... }                                         │
│        │      ]                                                                  │
│        │    }                                                                    │
│        │                                                                          │
│  [Backend - Step 3: APPLY FILTERS]                                               │
│        │                                                                          │
│        ├─── 7. FILTER SURVEYS BY LOI, CPI, IR                                    │
│        │    Get filter settings from database:                                   │
│        │    • max_loi = 20 (minutes)                                             │
│        │    • min_cpi = 1.0 (USD payout)                                         │
│        │    • min_ir = 0 (incidence rate / conversion_rate)                      │
│        │                                                                          │
│        │    Apply filters:                                                       │
│        │    for survey in surveys:                                               │
│        │      if survey.loi > max_loi: skip                                      │
│        │      if survey.payout < min_cpi: skip                                   │
│        │      if survey.conversion_rate < min_ir: skip                           │
│        │      if not survey.href: skip  # No href = can't allocate               │
│        │      filtered_surveys.append(survey)                                    │
│        │                                                                          │
│        │    Result: 50 surveys → 15 filtered surveys                             │
│        │                                                                          │
│  [Backend - Step 4: ALLOCATE RANDOM SURVEY]                                      │
│        │                                                                          │
│        ├─── 8. RANDOMLY SELECT ONE SURVEY                                        │
│        │    selected_survey = random.choice(filtered_surveys)                    │
│        │    survey_id = "12345"                                                  │
│        │    href = "https://click.cpx-research.com/?k=aB3fD..."                  │
│        │                                                                          │
│        ├─── 9. CREATE TRAFFIC RECORD (SFWID)                                     │
│        │    traffic_id = traffic_service.create_traffic_record(...)              │
│        │    Result: SFWID = ObjectId("67890abcdef...")                           │
│        │    MongoDB: survey_fieldwork.url_parameters                             │
│        │    {                                                                    │
│        │      "_id": ObjectId("67890abcdef..."),  // SFWID                       │
│        │      "vendorId": "VEN_001",                                             │
│        │      "countryCode": "US",                                               │
│        │      "respondentId": "RESP_999",                                        │
│        │      "clientIp": "103.21.124.1",                                        │
│        │      "ipSource": "CF-Connecting-IP",                                    │
│        │      "deviceFingerprint": "fp_a3f2b8d91c7e5...",                        │
│        │      "fingerprintSource": "client",                                     │
│        │      "fingerprintComponents": { ... },                                  │
│        │      "status": "INCOMPLETE",                                            │
│        │      "createdAt": ISODate("...")                                        │
│        │    }                                                                    │
│        │                                                                          │
│        ├─── 10. APPEND SUBID_1 = SFWID TO ENTRY LINK                             │
│        │    entry_link = cpx_service.generate_respondent_entry_link(             │
│        │      survey_id="12345",                                                 │
│        │      respondent_id="67890abcdef...",  // SFWID                          │
│        │      href="https://click.cpx-research.com/?k=aB3fD..."                  │
│        │    )                                                                    │
│        │                                                                          │
│        │    Final Entry Link:                                                    │
│        │    https://click.cpx-research.com/?k=aB3fD...&api=true&                 │
│        │    time_stamp=123456&ext_user_id=PANEL_88921&                           │
│        │    subid_1=67890abcdef...                                               │
│        │                                                                          │
│        ├─── 11. UPDATE TRAFFIC RECORD WITH SURVEY                                │
│        │    traffic_service.assign_survey_to_traffic(                            │
│        │      traffic_id="67890abcdef...",                                       │
│        │      survey_id="12345",                                                 │
│        │      redirect_url=entry_link                                            │
│        │    )                                                                    │
│        │                                                                          │
│        └─── 12. RETURN ENTRY LINK TO FRONTEND                                    │
│             Response: {                                                          │
│               "id": "67890abcdef...",                                            │
│               "type": "traffic",                                                 │
│               "entry_link": "https://click.cpx-research.com/...",                │
│               "allocation_success": true                                         │
│             }                                                                    │
│                                                                                   │
│  [Frontend - Redirect to CPX]                                                     │
│        │                                                                          │
│        └─── 13. REDIRECT RESPONDENT TO CPX SURVEY                                │
│             window.location.href = entry_link                                    │
│             Browser navigates to CPX survey with subid_1=SFWID                   │
│                                                                                   │
│  [CRITICAL FLOW NOTES]                                                            │
│  • Step 2 happens BEFORE traffic record creation                                 │
│  • CPX API called with real IP/fingerprint immediately on PROCEED click          │
│  • Filters applied server-side (LOI, CPI, IR)                                    │
│  • SFWID generated after survey selected                                         │
│  • subid_1 = SFWID enables postback matching (Step 5-6)                          │
│                                                                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: RESPONDENT TAKES SURVEY (User Journey)                                  │
├───────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  [Respondent Browser - Step 1: Entry]                                            │
│        │                                                                          │
│        ├─── 1. RESPONDENT CLICKS ENTRY LINK                                      │
│        │    Source: Email, dashboard, or direct link                             │
│        │    URL: https://click.cpx-research.com/?k=aB3fD...&api=true&            │
│        │         time_stamp=123456&ext_user_id=PANEL_88921&subid_1=SFWID_67890  │
│        │                                                                          │
│        │    Query Parameters Breakdown:                                          │
│        │    • k = aB3fD... (CPX encrypted survey token - unique per survey)      │
│        │    • api = true (indicates API-driven allocation)                       │
│        │    • time_stamp = 123456 (CPX request timestamp)                        │
│        │    • ext_user_id = PANEL_88921 (platform panel identifier)              │
│        │    • subid_1 = SFWID_67890 (respondent tracking - CRITICAL!)            │
│        │                                                                          │
│  [CPX Click Server - Step 2: Click Tracking]                                     │
│        │                                                                          │
│        ├─── 2. CPX RECORDS CLICK EVENT                                           │
│        │    CPX Internal Processing:                                             │
│        │    • Decrypt k= token to identify survey                                │
│        │    • Validate ext_user_id matches app_id                                │
│        │    • Log click event with timestamp                                     │
│        │    • Store subid_1 (SFWID_67890) for postback routing                   │
│        │    • Generate unique trans_id (CPX_TRANS_123456)                        │
│        │                                                                          │
│        │    IMPORTANT: CPX associates trans_id ↔ subid_1 for later postback      │
│        │    This is how CPX knows which respondent to notify on completion!      │
│        │                                                                          │
│        ├─── 3. VALIDATE & ROUTE                                                  │
│        │    CPX Validation Checks:                                               │
│        │    • Survey still available? (not at capacity)                          │
│        │    • ext_user_id authorized for this survey?                            │
│        │    • k= token not expired? (time-based validation)                      │
│        │    • No duplicate click from same subid_1? (fraud prevention)           │
│        │                                                                          │
│        │    If Validation Fails:                                                 │
│        │    → Redirect to error page                                             │
│        │    → Send postback with status=2 (fraud/canceled)                       │
│        │                                                                          │
│        ├─── 4. REDIRECT TO SURVEY PROVIDER                                       │
│        │    CPX redirects to actual survey:                                      │
│        │    HTTP 302 Redirect                                                    │
│        │    Location: https://surveymonkey.com/r/SURVEY123?cpx_trans=...         │
│        │              or                                                          │
│        │              https://qualtrics.com/jfe/form/SV_xxx?tx=...               │
│        │              or                                                          │
│        │              https://survicate.com/s/CPX_...                            │
│        │                                                                          │
│        │    CPX appends transaction ID to survey provider's URL for tracking     │
│        │                                                                          │
│  [Survey Provider Platform - Step 3: Survey Experience]                          │
│        │                                                                          │
│        ├─── 5. QUALIFICATION SCREENING                                           │
│        │    Survey Provider Shows:                                               │
│        │    • Welcome page with privacy notice                                   │
│        │    • Demographic screening questions:                                   │
│        │      - Age, gender, location                                            │
│        │      - Income bracket, employment status                                │
│        │      - Industry-specific criteria                                       │
│        │                                                                          │
│        │    Outcomes:                                                            │
│        │    ✅ QUALIFIED: Proceed to main survey                                  │
│        │    ❌ DISQUALIFIED: Terminate early                                      │
│        │       → Survey provider notifies CPX                                    │
│        │       → CPX sends postback: status=2 (canceled)                         │
│        │                                                                          │
│        ├─── 6. MAIN SURVEY QUESTIONS                                             │
│        │    If Qualified, Respondent Sees:                                       │
│        │    • Multiple choice questions                                          │
│        │    • Rating scales (1-5, 1-10)                                          │
│        │    • Open-ended text responses                                          │
│        │    • Matrix questions                                                   │
│        │    • Image/video-based questions                                        │
│        │                                                                          │
│        │    Survey Progress:                                                     │
│        │    • Progress bar: "Question 5 of 15"                                   │
│        │    • Estimated time remaining: "~7 minutes left"                        │
│        │    • Save & Resume option (some surveys)                                │
│        │                                                                          │
│        │    Quality Checks:                                                      │
│        │    • Attention check questions ("Select option C")                      │
│        │    • Speeding detection (too fast completion)                           │
│        │    • Straight-lining detection (same answer repeatedly)                 │
│        │    • Open-end validation (minimum character count)                      │
│        │                                                                          │
│        │    If Quality Check Fails:                                              │
│        │    → Survey terminated                                                  │
│        │    → Marked as fraud/poor quality                                       │
│        │    → CPX postback: status=2                                             │
│        │                                                                          │
│        ├─── 7. SURVEY COMPLETION                                                 │
│        │    Respondent Completes All Questions:                                  │
│        │    • Survey provider validates all required fields                      │
│        │    • Runs final quality checks                                          │
│        │    • Shows "Thank You" page                                             │
│        │    • Records completion timestamp                                       │
│        │                                                                          │
│        └─── 8. SURVEY PROVIDER NOTIFIES CPX                                      │
│             Survey Provider → CPX Server:                                        │
│             POST https://cpx-internal.com/completion-callback                    │
│             Body: {                                                              │
│               "transaction_id": "CPX_TRANS_123456",                              │
│               "status": "complete",                                              │
│               "quality_score": 95,                                               │
│               "completion_time_seconds": 612                                     │
│             }                                                                    │
│                                                                                   │
│  [CPX Internal Processing - Step 4: Completion Validation]                       │
│        │                                                                          │
│        ├─── 9. CPX VALIDATES COMPLETION                                          │
│        │    CPX Quality Checks:                                                  │
│        │    • Survey provider signature valid?                                   │
│        │    • Transaction ID exists in CPX system?                               │
│        │    • Completion time reasonable? (not too fast/slow)                    │
│        │    • Quality score above threshold? (e.g., >70)                         │
│        │    • No duplicate completion for same trans_id?                         │
│        │                                                                          │
│        │    Fraud Detection:                                                     │
│        │    • IP address consistency check                                       │
│        │    • Device fingerprint analysis                                        │
│        │    • Cross-reference with known fraud patterns                          │
│        │    • Survey provider's quality flags                                    │
│        │                                                                          │
│        │    Final Decision:                                                      │
│        │    ✅ APPROVED: status=1, calculate payout                               │
│        │    ❌ REJECTED: status=2, no payout                                      │
│        │                                                                          │
│        ├─── 10. CALCULATE PAYOUT                                                 │
│        │    If Approved:                                                         │
│        │    • Base payout: $2.50 (from survey inventory)                         │
│        │    • Currency conversion if needed (USD → local)                        │
│        │    • Apply any bonuses/penalties (quality score)                        │
│        │    • Final amount_usd: $2.50                                            │
│        │                                                                          │
│        └─── 11. PREPARE POSTBACK                                                 │
│             CPX Retrieves Stored Data:                                           │
│             • trans_id = "CPX_TRANS_123456"                                      │
│             • subid_1 = "SFWID_67890" (from click tracking)                      │
│             • status = 1 (complete) or 2 (fraud/canceled)                        │
│             • amount_usd = 2.50                                                  │
│             • Survey provider = "SurveyMonkey"                                   │
│             • Completion timestamp                                               │
│                                                                                   │
│             Ready to send postback → PHASE 4                                     │
│                                                                                   │
│  [TIMELINE BREAKDOWN]                                                             │
│  • Click → Redirect: <2 seconds (CPX processing)                                 │
│  • Qualification: 1-3 minutes (screening questions)                              │
│  • Main Survey: 5-15 minutes (based on LOI)                                      │
│  • Quality Checks: <30 seconds (automated)                                       │
│  • CPX Validation: <10 seconds (before postback)                                 │
│  • Total: ~10-20 minutes average per completion                                  │
│                                                                                   │
│  [FAILURE SCENARIOS]                                                              │
│  • Disqualified: ~15% (demographics don't match)                                 │
│  • Quality Fail: ~5% (attention checks, speeding)                                │
│  • Abandonment: ~30% (respondent leaves mid-survey)                              │
│  • Technical Error: ~2% (browser issues, connectivity)                           │
│  • Success Rate: ~48-50% (varies by survey)                                      │
│                                                                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: SERVER-TO-SERVER POSTBACK (Single Source of Truth)                      │
├───────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  [CPX Server - Initiates Postback]                                               │
│        │                                                                          │
│        ├─── 1. BUILD POSTBACK URL                                                │
│        │    CPX constructs platform callback URL:                                │
│        │    Base: https://surveyfieldwork.com/api/cpx-postback                   │
│        │    Query Parameters:                                                    │
│        │    • trans_id = "CPX_TRANS_123456" (PRIMARY identifier)                 │
│        │    • status = 1 (complete) or 2 (fraud/canceled)                        │
│        │    • amount_usd = 2.50 (payout in USD)                                  │
│        │    • amount_local = 200.00 (optional, in local currency)                │
│        │    • subid = "SFWID_67890" (from click tracking - CRITICAL!)            │
│        │    • ip = "192.168.1.1" (respondent's IP address)                       │
│        │    • offer_id = "12345" (CPX survey ID)                                 │
│        │    • hash = "a3f2b..." (security hash for validation)                   │
│        │                                                                          │
│        │    Hash Calculation: MD5(trans_id + status + secret_key)                │
│        │    Example: MD5("CPX_TRANS_1234561" + "my_secret_key")                  │
│        │                                                                          │
│        ├─── 2. SEND HTTP GET REQUEST                                             │
│        │    CPX → Platform:                                                      │
│        │    GET https://surveyfieldwork.com/api/cpx-postback?                    │
│        │        trans_id=CPX_TRANS_123456&                                       │
│        │        status=1&                                                        │
│        │        amount_usd=2.50&                                                 │
│        │        subid=SFWID_67890&                                               │
│        │        hash=a3f2b...                                                    │
│        │                                                                          │
│        │    Retry Logic (if platform doesn't respond):                           │
│        │    • Retry 1: after 1 minute                                            │
│        │    • Retry 2: after 5 minutes                                           │
│        │    • Retry 3: after 15 minutes                                          │
│        │    • Retry 4: after 1 hour                                              │
│        │    • Stops retrying after receiving HTTP 200                            │
│        │                                                                          │
│  [Platform Server - Postback Handler: cpx_postback_handler()]                    │
│        │                                                                          │
│        ├─── 3. RECEIVE & LOG POSTBACK                                            │
│        │    Endpoint: GET /api/cpx-postback                                      │
│        │    Log incoming request:                                                │
│        │    📥 CPX Postback: trans_id=CPX_TRANS_123456, status=1, amount=2.50    │
│        │                                                                          │
│        ├─── 4. VALIDATE SECURITY HASH                                            │
│        │    Extract parameters from request:                                     │
│        │    • trans_id, status, received_hash                                    │
│        │                                                                          │
│        │    Calculate expected hash:                                             │
│        │    expected_hash = MD5(trans_id + status + CPX_SECRET_KEY)              │
│        │                                                                          │
│        │    Compare: expected_hash == received_hash                              │
│        │    If INVALID:                                                          │
│        │    • Log warning: "⚠️ Invalid hash for trans_id=..."                     │
│        │    • Record in postback_logs with error                                 │
│        │    • STILL return HTTP 200 (prevent retries)                            │
│        │    • Do NOT process transaction                                         │
│        │                                                                          │
│        ├─── 5. CHECK FOR DUPLICATE POSTBACK (Idempotency)                        │
│        │    Generate postback_hash for deduplication:                            │
│        │    postback_hash = SHA256(trans_id + status + amount_usd)[:16]          │
│        │                                                                          │
│        │    Query existing transaction:                                          │
│        │    existing = survey_transactions.find_one({"trans_id": trans_id})      │
│        │                                                                          │
│        │    If exists AND postback_hash matches:                                 │
│        │    • Log: "⚠️ Duplicate postback ignored for trans_id=..."              │
│        │    • Return HTTP 200 immediately (idempotent operation)                 │
│        │    • Skip processing                                                    │
│        │                                                                          │
│        │    If exists BUT postback_hash different:                               │
│        │    • Status changed (complete → fraud, or vice versa)                   │
│        │    • Allow update (legitimate status change)                            │
│        │    • Increment postback_count                                           │
│        │                                                                          │
│        ├─── 6. CREATE/UPDATE TRANSACTION RECORD                                  │
│        │    MongoDB: survey_fieldwork.survey_transactions                        │
│        │                                                                          │
│        │    If NEW Transaction:                                                  │
│        │    survey_transactions.insert_one({                                     │
│        │      "trans_id": "CPX_TRANS_123456",      // PRIMARY KEY                │
│        │      "cpx_status": 1,                     // Raw CPX status             │
│        │      "status": "completed",               // Normalized status          │
│        │      "amount_usd": 2.50,                                                │
│        │      "amount_local": 200.00,                                            │
│        │      "subid": "SFWID_67890",              // Links to traffic record    │
│        │      "subid_2": null,                                                   │
│        │      "survey_id": "12345",                // CPX offer_id               │
│        │      "ip_address": "192.168.1.1",                                       │
│        │      "callback_url": "https://...",       // Full postback URL          │
│        │      "created_at": datetime.utcnow(),                                   │
│        │      "updated_at": datetime.utcnow(),                                   │
│        │      "last_postback_at": datetime.utcnow(),                             │
│        │      "completed_at": datetime.utcnow(),   // Only if status=1           │
│        │      "postback_count": 1,                                               │
│        │      "postback_hash": "f3a2b..."          // For duplicate detection    │
│        │    })                                                                   │
│        │                                                                          │
│        │    If EXISTING Transaction (status change):                             │
│        │    survey_transactions.update_one(                                      │
│        │      {"trans_id": trans_id},                                            │
│        │      {                                                                  │
│        │        "$set": {                                                        │
│        │          "cpx_status": status,                                          │
│        │          "status": "completed" if status==1 else "fraud",               │
│        │          "amount_usd": amount_usd,                                      │
│        │          "updated_at": datetime.utcnow(),                               │
│        │          "last_postback_at": datetime.utcnow(),                         │
│        │          "completed_at": datetime.utcnow() if status==1 else None,      │
│        │          "postback_hash": new_hash                                      │
│        │        },                                                               │
│        │        "$inc": {"postback_count": 1}                                    │
│        │      }                                                                  │
│        │    )                                                                    │
│        │                                                                          │
│        │    Status Mapping:                                                      │
│        │    • CPX status=1 → "completed" (successful survey completion)          │
│        │    • CPX status=2 → "fraud" (failed quality checks or canceled)         │
│        │                                                                          │
│        │    Log success:                                                         │
│        │    ✅ Created/Updated transaction: trans_id=CPX_TRANS_123456, status=1   │
│        │                                                                          │
│        ├─── 7. FORWARD TO VENDOR SERVER (Critical Step!)                         │
│        │    Function: _forward_to_vendor(sfwid, status, amount_usd, trans_id)   │
│        │                                                                          │
│        │    Step 7a: Find Traffic Record by SFWID                                │
│        │    traffic = url_parameters.find_one({"_id": ObjectId(SFWID_67890)})    │
│        │    Extract:                                                             │
│        │    • vendor_id = "VEN_001"                                              │
│        │    • respondent_id = "RESP_999" (vendor's respondent ID)                │
│        │                                                                          │
│        │    If traffic record NOT found:                                         │
│        │    • Log: "⚠️ Vendor postback skipped: Traffic record not found"        │
│        │    • Continue (still process CPX postback)                              │
│        │    • Return HTTP 200                                                    │
│        │                                                                          │
│        │    Step 7b: Look Up Vendor Configuration                                │
│        │    vendor = vendors.find_one({"vid": "VEN_001"})                        │
│        │    Extract:                                                             │
│        │    • completeRD = ["https://vendor.com/complete?..."] (for status=1)    │
│        │    • terminateRD = ["https://vendor.com/terminate?..."] (for status=2)  │
│        │    • vendorVariable = "rid" (parameter name for respondent_id)          │
│        │                                                                          │
│        │    Determine redirect URL based on status:                              │
│        │    redirect_type = "completeRD" if status==1 else "terminateRD"         │
│        │    base_url = vendor[redirect_type][0]                                  │
│        │                                                                          │
│        │    Step 7c: Build Vendor Postback URL                                   │
│        │    Example base_url: "https://vendor.com/complete?key=ABC&rid="         │
│        │    Append respondent_id:                                                │
│        │    vendor_url = f"{base_url}RESP_999"                                   │
│        │    Result: "https://vendor.com/complete?key=ABC&rid=RESP_999"           │
│        │                                                                          │
│        │    Step 7d: Make Async HTTP GET to Vendor                               │
│        │    async with httpx.AsyncClient(timeout=10.0) as client:                │
│        │      response = await client.get(vendor_url)                            │
│        │                                                                          │
│        │    Log result:                                                          │
│        │    📤 Forwarding postback to vendor: https://vendor.com/complete?...     │
│        │    ✅ Vendor postback successful: 200                                    │
│        │    or                                                                   │
│        │    ⚠️ Vendor postback returned: 404/500 (non-2xx status)                │
│        │                                                                          │
│        │    Step 7e: Update Traffic Record with Postback Info                    │
│        │    url_parameters.update_one(                                           │
│        │      {"_id": ObjectId(SFWID_67890)},                                    │
│        │      {                                                                  │
│        │        "$set": {                                                        │
│        │          "cpxPostbackReceived": true,                                   │
│        │          "cpxPostbackStatus": 1,                                        │
│        │          "cpxPostbackAt": datetime.utcnow(),                            │
│        │          "cpxTransId": "CPX_TRANS_123456",                              │
│        │          "status": "COMPLETE",            // Traffic status             │
│        │          "completedAt": datetime.utcnow(),                              │
│        │          "vendorPostbackUrl": vendor_url,                               │
│        │          "vendorPostbackSuccess": true,                                 │
│        │          "vendorPostbackStatus": 200                                    │
│        │        }                                                                │
│        │      }                                                                  │
│        │    )                                                                    │
│        │                                                                          │
│        ├─── 8. LOG POSTBACK EVENT                                                │
│        │    MongoDB: cpx_research.cpx_postback_logs                              │
│        │    cpx_postback_logs.insert_one({                                       │
│        │      "trans_id": "CPX_TRANS_123456",                                    │
│        │      "cpx_status": 1,                                                   │
│        │      "amount_usd": 2.50,                                                │
│        │      "subid": "SFWID_67890",                                            │
│        │      "success": true,                                                   │
│        │      "message": "Processed",                                            │
│        │      "timestamp": datetime.utcnow(),                                    │
│        │      "vendor_postback": {                                               │
│        │        "url": "https://vendor.com/complete?...",                        │
│        │        "success": true,                                                 │
│        │        "response_status": 200,                                          │
│        │        "error": null,                                                   │
│        │        "respondent_id": "RESP_999",                                     │
│        │        "vendor_id": "VEN_001"                                           │
│        │      }                                                                  │
│        │    })                                                                   │
│        │                                                                          │
│        └─── 9. RETURN HTTP 200 (ALWAYS!)                                         │
│             Response: { "status": "ok" }                                         │
│             HTTP Status: 200 OK                                                  │
│                                                                                   │
│             CRITICAL: ALWAYS return 200, even on errors!                         │
│             • Prevents CPX from retrying (retry storm)                           │
│             • Errors logged but not returned to CPX                              │
│             • Only exception: Platform completely down (infrastructure)          │
│                                                                                   │
│  [CPX Server - Receives Response]                                                │
│        │                                                                          │
│        └─── 10. CPX MARKS POSTBACK AS DELIVERED                                 │
│             • Receives HTTP 200 from platform                                    │
│             • Marks transaction as "postback_sent=true"                          │
│             • Stops retry loop                                                   │
│             • Updates internal CPX ledger                                        │
│             • Transaction complete from CPX perspective                          │
│                                                                                   │
│  [ERROR HANDLING & EDGE CASES]                                                    │
│                                                                                   │
│  Duplicate Postback:                                                              │
│  • Same trans_id + status + amount → Idempotent (ignore)                         │
│  • Same trans_id, different status → Legitimate update (status changed)          │
│  • postback_count tracks how many times postback received                        │
│                                                                                   │
│  Invalid Hash:                                                                    │
│  • Log warning, mark as suspicious                                               │
│  • Return 200 (don't retry bad postbacks)                                        │
│  • Alert admin for investigation                                                 │
│                                                                                   │
│  Vendor Postback Failure:                                                         │
│  • CPX transaction still processed (platform gets paid)                          │
│  • Vendor postback logged with error                                             │
│  • Manual retry option available in admin panel                                  │
│  • Vendor may need to reconcile manually                                         │
│                                                                                   │
│  Missing SFWID:                                                                   │
│  • CPX transaction created (trans_id as primary key)                             │
│  • Vendor postback skipped (can't find respondent)                               │
│  • Logged for manual resolution                                                  │
│                                                                                   │
│  [PERFORMANCE METRICS]                                                            │
│  • Postback processing time: ~50-200ms (excluding vendor forward)                │
│  • Vendor forward time: ~100-500ms (depends on vendor response)                  │
│  • Total postback handling: ~150-700ms                                           │
│  • Database writes: 2-3 (transaction + traffic + log)                            │
│  • Concurrency: Handles 100+ postbacks/second with proper indexing               │
│                                                                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 5: VENDOR NOTIFICATION & REPORTING (Downstream Integration)                │
├───────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  [Vendor Server - Receives Postback]                                             │
│        │                                                                          │
│        ├─── 1. RECEIVE COMPLETION NOTIFICATION                                   │
│        │    Platform → Vendor:                                                   │
│        │    GET https://vendor.com/complete?key=ABC&rid=RESP_999                 │
│        │                                                                          │
│        │    Query Parameters (vendor-specific):                                  │
│        │    • rid = "RESP_999" (or vendorVariable: uid, pid, respondent_id)      │
│        │    • status = "complete" (optional, vendor may infer from URL)          │
│        │    • payout = "2.50" (optional, vendor may track separately)            │
│        │    • trans_id = "CPX_TRANS_123456" (optional reference)                 │
│        │    • key = "ABC" (vendor's security token)                              │
│        │                                                                          │
│        ├─── 2. VALIDATE REQUEST                                                  │
│        │    Vendor Security Checks:                                              │
│        │    • Validate 'key' parameter matches expected secret                   │
│        │    • Check request originates from platform IP (whitelist)              │
│        │    • Verify respondent_id exists in vendor database                     │
│        │    • Check for duplicate postback (idempotency on vendor side)          │
│        │                                                                          │
│        │    If Validation Fails:                                                 │
│        │    → Return HTTP 400/401 (platform logs error)                          │
│        │    → Log suspicious request for investigation                           │
│        │                                                                          │
│        ├─── 3. UPDATE RESPONDENT RECORD                                          │
│        │    Vendor Database Update:                                              │
│        │    UPDATE respondents                                                   │
│        │    SET                                                                  │
│        │      survey_status = 'COMPLETED',                                       │
│        │      completed_at = NOW(),                                              │
│        │      payout_amount = 2.50,                                              │
│        │      payout_currency = 'USD',                                           │
│        │      source = 'CPX',                                                    │
│        │      source_trans_id = 'CPX_TRANS_123456',                              │
│        │      last_updated = NOW()                                               │
│        │    WHERE respondent_id = 'RESP_999'                                     │
│        │                                                                          │
│        ├─── 4. CREDIT RESPONDENT ACCOUNT                                         │
│        │    Vendor Business Logic:                                               │
│        │    • Calculate final payout (may differ from CPX amount):               │
│        │      - Apply vendor markup/discount                                     │
│        │      - Convert currency if needed                                       │
│        │      - Apply loyalty bonuses                                            │
│        │      - Deduct fees if applicable                                        │
│        │                                                                          │
│        │    • Update respondent balance:                                         │
│        │      UPDATE accounts                                                    │
│        │      SET balance = balance + 2.50                                       │
│        │      WHERE respondent_id = 'RESP_999'                                   │
│        │                                                                          │
│        │    • Create transaction record:                                         │
│        │      INSERT INTO transactions (                                         │
│        │        respondent_id, type, amount, source,                             │
│        │        description, created_at                                          │
│        │      ) VALUES (                                                         │
│        │        'RESP_999', 'CREDIT', 2.50, 'CPX',                               │
│        │        'Survey Completion', NOW()                                       │
│        │      )                                                                  │
│        │                                                                          │
│        ├─── 5. SEND NOTIFICATION TO RESPONDENT                                   │
│        │    Vendor Notification System:                                          │
│        │    • Email: "You earned $2.50 for completing a survey!"                 │
│        │    • SMS: "Survey complete! $2.50 added to your account."               │
│        │    • Push notification (mobile app)                                     │
│        │    • In-app notification (next login)                                   │
│        │    • Dashboard update (real-time via WebSocket)                         │
│        │                                                                          │
│        ├─── 6. RETURN SUCCESS RESPONSE                                           │
│        │    Vendor → Platform:                                                   │
│        │    HTTP 200 OK                                                          │
│        │    Response Body (optional):                                            │
│        │    {                                                                    │
│        │      "status": "success",                                               │
│        │      "respondent_id": "RESP_999",                                       │
│        │      "credited_amount": 2.50,                                           │
│        │      "balance": 127.50,                                                 │
│        │      "message": "Respondent credited successfully"                      │
│        │    }                                                                    │
│        │                                                                          │
│        └─── 7. LOG POSTBACK EVENT                                                │
│             Vendor Logging:                                                      │
│             • Store postback details for audit trail                             │
│             • Track source, amount, timestamp                                    │
│             • Enable reconciliation with platform reports                        │
│             • Generate billing records for accounting                            │
│                                                                                   │
│  [Platform Dashboard - Reporting & Analytics]                                    │
│        │                                                                          │
│        ├─── 8. REAL-TIME METRICS DASHBOARD                                       │
│        │    Admin Panel: Operations → CPX Analytics                              │
│        │                                                                          │
│        │    Today's Summary:                                                     │
│        │    • Total Clicks: 1,234                                                │
│        │    • Total Completions: 587                                             │
│        │    • Conversion Rate: 47.6%                                             │
│        │    • Total Revenue: $1,467.50                                           │
│        │    • Average Payout: $2.50                                              │
│        │    • Fraud Count: 47 (3.8%)                                             │
│        │                                                                          │
│        │    By Vendor Breakdown:                                                 │
│        │    • Vendor A: 287 completes, $717.50 revenue                           │
│        │    • Vendor B: 198 completes, $495.00 revenue                           │
│        │    • Vendor C: 102 completes, $255.00 revenue                           │
│        │                                                                          │
│        │    By Survey Breakdown:                                                 │
│        │    • Survey #12345: 89 completes, $222.50, 52% conversion               │
│        │    • Survey #12346: 67 completes, $167.50, 41% conversion               │
│        │    • Top performing: Health surveys (avg 58% conversion)                │
│        │                                                                          │
│        │    Query:                                                               │
│        │    SELECT                                                               │
│        │      DATE(completed_at) as date,                                        │
│        │      COUNT(*) as completions,                                           │
│        │      SUM(amount_usd) as revenue,                                        │
│        │      AVG(amount_usd) as avg_payout                                      │
│        │    FROM survey_transactions                                             │
│        │    WHERE status = 'completed'                                           │
│        │      AND completed_at >= CURDATE()                                      │
│        │    GROUP BY DATE(completed_at)                                          │
│        │                                                                          │
│        ├─── 9. TRANSACTION HISTORY VIEW                                          │
│        │    Endpoint: GET /api/cpx/transactions                                  │
│        │    Filters:                                                             │
│        │    • Date range: Last 7 days, Last 30 days, Custom                      │
│        │    • Vendor: Filter by vendor_id                                        │
│        │    • Status: completed, fraud, pending                                  │
│        │    • Survey: Filter by survey_id                                        │
│        │    • Search: trans_id, respondent_id                                    │
│        │                                                                          │
│        │    Table Columns:                                                       │
│        │    • Timestamp: 2026-02-03 14:30:15                                     │
│        │    • Trans ID: CPX_TRANS_123456                                         │
│        │    • Respondent: RESP_999 (Vendor A)                                    │
│        │    • Survey: #12345 - Consumer Opinion                                  │
│        │    • Status: ✅ Completed                                                │
│        │    • Payout: $2.50                                                      │
│        │    • Vendor Postback: ✅ Success (200)                                   │
│        │    • Actions: View Details, Resend Postback                             │
│        │                                                                          │
│        ├─── 10. POSTBACK LOGS VIEWER                                             │
│        │    Endpoint: GET /api/cpx-postback-logs                                 │
│        │    Purpose: Debug postback issues, audit trail                          │
│        │                                                                          │
│        │    Log Entry Example:                                                   │
│        │    {                                                                    │
│        │      "timestamp": "2026-02-03T14:30:15Z",                               │
│        │      "trans_id": "CPX_TRANS_123456",                                    │
│        │      "cpx_status": 1,                                                   │
│        │      "amount_usd": 2.50,                                                │
│        │      "subid": "SFWID_67890",                                            │
│        │      "success": true,                                                   │
│        │      "message": "Processed",                                            │
│        │      "vendor_postback": {                                               │
│        │        "url": "https://vendor.com/complete?...",                        │
│        │        "success": true,                                                 │
│        │        "response_status": 200,                                          │
│        │        "respondent_id": "RESP_999",                                     │
│        │        "vendor_id": "VEN_001"                                           │
│        │      }                                                                  │
│        │    }                                                                    │
│        │                                                                          │
│        ├─── 11. EXPORT & BILLING                                                 │
│        │    Generate Reports:                                                    │
│        │    • CSV Export: All transactions for date range                        │
│        │    • Excel Report: Pivot tables by vendor/survey                        │
│        │    • PDF Invoice: Vendor-specific billing                               │
│        │    • API Export: JSON format for integration                            │
│        │                                                                          │
│        │    Billing Calculation:                                                 │
│        │    • Platform Revenue: CPX payout × platform margin                     │
│        │    • Vendor Charge: CPX payout + platform fee                           │
│        │    • Net Profit: (Vendor charge - CPX payout)                           │
│        │                                                                          │
│        │    Example Monthly Report:                                              │
│        │    Vendor A - February 2026:                                            │
│        │    • Completions: 8,567                                                 │
│        │    • CPX Payout: $21,417.50                                             │
│        │    • Platform Fee (15%): $3,212.63                                      │
│        │    • Total Invoice: $24,630.13                                          │
│        │    • Payment Terms: Net 15 days                                         │
│        │                                                                          │
│        ├─── 12. ALERTING & MONITORING                                            │
│        │    Automated Alerts:                                                    │
│        │    • High fraud rate (>10%): Email admin                                │
│        │    • Vendor postback failures (>5%): Slack notification                 │
│        │    • Revenue drop (>20% vs yesterday): Dashboard alert                  │
│        │    • CPX API errors: PagerDuty incident                                 │
│        │    • Duplicate postbacks spike: Investigation alert                     │
│        │                                                                          │
│        │    Health Checks:                                                       │
│        │    • Postback processing time < 500ms (p95)                             │
│        │    • Database query time < 100ms (p95)                                  │
│        │    • Vendor forward success rate > 95%                                  │
│        │    • No postbacks older than 5 minutes unprocessed                      │
│        │                                                                          │
│        └─── 13. RECONCILIATION & AUDIT                                           │
│             Daily Reconciliation Process:                                        │
│             • Compare CPX transactions vs platform records                       │
│             • Match trans_id across systems                                      │
│             • Identify discrepancies (missing postbacks)                         │
│             • Flag unmatched SFWIDs (potential data loss)                        │
│             • Generate reconciliation report                                     │
│             • Schedule manual review for mismatches                              │
│                                                                                   │
│             Weekly Vendor Reconciliation:                                        │
│             • Aggregate completions per vendor                                   │
│             • Compare with vendor's reported numbers                             │
│             • Investigate discrepancies                                          │
│             • Adjust billing if needed                                           │
│             • Document resolution in audit log                                   │
│                                                                                   │
│  [VENDOR-SIDE REPORTING (Vendor's Dashboard)]                                    │
│        │                                                                          │
│        └─── VENDOR ANALYTICS                                                     │
│             Vendor's own dashboard shows:                                        │
│             • Respondent earnings history                                        │
│             • Survey completion stats                                            │
│             • Payout summaries by source (CPX, Cint, etc.)                       │
│             • Respondent engagement metrics                                      │
│             • Payment processing status                                          │
│             • Account balance per respondent                                     │
│                                                                                   │
│             API Integration (Optional):                                          │
│             • Vendor can query platform API for real-time data                   │
│             • GET /api/vendor/{vendor_id}/completions?date=2026-02-03            │
│             • Webhook option for proactive notifications                         │
│             • OAuth2 authentication for secure access                            │
│                                                                                   │
│  [KEY METRICS FOR BUSINESS INTELLIGENCE]                                         │
│                                                                                   │
│  Completion Metrics:                                                              │
│  • Completion Rate: (completions / clicks) × 100                                 │
│  • Average LOI: SUM(survey.loi × completions) / total_completions               │
│  • Revenue per Click: total_revenue / total_clicks                               │
│  • Fraud Rate: (fraud_count / total_postbacks) × 100                             │
│                                                                                   │
│  Performance Metrics:                                                             │
│  • Postback Processing Time: p50, p95, p99 latencies                             │
│  • Vendor Forward Success Rate: (successful_forwards / total_forwards) × 100     │
│  • Database Query Performance: avg execution time                                │
│  • API Response Time: avg time to serve requests                                 │
│                                                                                   │
│  Financial Metrics:                                                               │
│  • Daily Revenue: SUM(amount_usd WHERE status='completed')                       │
│  • Monthly Revenue: Aggregated by month                                          │
│  • Revenue by Vendor: GROUP BY vendor_id                                         │
│  • Revenue by Survey: GROUP BY survey_id                                         │
│  • Profit Margin: (vendor_charge - cpx_payout) / vendor_charge                   │
│                                                                                   │
│  Quality Metrics:                                                                 │
│  • Survey Quality Score: Based on conversion rate                                │
│  • Vendor Quality Score: Based on fraud rate, postback success                   │
│  • Respondent Quality: Based on completion history                               │
│  • Data Completeness: % of transactions with all fields                          │
│                                                                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔑 Key Identifiers

| Identifier | Purpose | Example | Source |
|-----------|---------|---------|--------|
| **survey_id** | CPX survey identifier | `"12345"` | CPX API |
| **trans_id** | CPX transaction ID (PRIMARY) | `"CPX_TRANS_123"` | CPX postback |
| **SFWID** | Survey Field Work ID (respondent tracking) | `"SFWID_67890"` | Platform generated |
| **subid_1** | Tracking parameter (contains SFWID) | Same as SFWID | Appended to entry link |
| **k parameter** | CPX encrypted survey token | `"aB3fD..."` | CPX href URL |
| **respondent_id** | Vendor's respondent identifier | `"RESP_999"` | Traffic record |

---

## 📊 Data Flow Between Collections

```
┌──────────────────────┐
│  cpx_surveys         │  ← Synced from CPX API
│  • survey_id (PK)    │  ← Contains href with k= token
│  • loi, payout       │  ← Metadata for filtering
│  • is_active_in_pool │  ← Pool activation flag
└──────────┬───────────┘
           │ (allocation)
           ▼
┌──────────────────────┐
│  url_parameters      │  ← Created on allocation
│  • _id = SFWID (PK)  │  ← Unique tracking ID
│  • vendorId          │  ← Links to vendor
│  • entry_link        │  ← Full CPX URL with subid_1
│  • respondent_id     │  ← Vendor's respondent ID
└──────────┬───────────┘
           │ (postback received)
           ▼
┌──────────────────────┐
│  survey_transactions │  ← Created/updated by postback
│  • trans_id (PK)     │  ← From CPX postback
│  • subid (SFWID)     │  ← Links to traffic record
│  • status            │  ← completed/fraud/canceled
│  • amount_usd        │  ← Payout amount
└──────────┬───────────┘
           │ (lookup for vendor postback)
           ▼
┌──────────────────────┐
│  vendors             │  ← Vendor configuration
│  • _id               │  ← Vendor ID
│  • postback_url      │  ← Where to send completion
│  • company_name      │  ← Display name
└──────────────────────┘
```

---

## 🎯 Status Codes

### CPX Status Codes
- **1** = COMPLETED (successful survey completion)
- **2** = CANCELED / FRAUD (user left early or flagged)

### Platform Status Mapping
- `"completed"` ← CPX status = 1
- `"fraud"` ← CPX status = 2
- `"canceled"` ← CPX status = 2 (alternative)

---

## ⚡ Critical Design Decisions

### 1. **trans_id is PRIMARY identifier**
   - Never use message_id (deprecated)
   - All postback lookups use trans_id
   - Idempotency check via postback_hash

### 2. **Postback is Single Source of Truth**
   - UI redirects are informational only
   - Transaction status ONLY updated by S2S postback
   - Always return HTTP 200 to prevent retries

### 3. **SFWID Tracking Flow**
   - Generated on allocation → stored as url_parameters._id
   - Appended to entry link as subid_1
   - CPX preserves it and returns in postback
   - Used to look up traffic record → vendor → respondent_id

### 4. **Entry Link Construction**
   - CPX href already contains k= token (survey-specific)
   - Platform only appends subid_1=SFWID
   - NO manual URL building - use CPX's href as base

### 5. **Idempotency & Fraud Handling**
   - postback_hash = sha256(trans_id:status:amount)[:16]
   - Duplicate postbacks ignored (same hash)
   - Status changes allowed (complete → fraud)
   - Postback count tracked for monitoring

---

## 🔐 Security & Validation

### CPX Postback Hash Validation
```python
expected = md5(trans_id + status + secret_key).hexdigest()
if received_hash != expected:
    log_warning("Invalid hash")
    return HTTP 200  # Still return 200 to prevent retries
```

### Vendor Postback Forwarding
```python
1. Look up traffic record: url_parameters.find_one({"_id": sfwid})
2. Get vendor: vendors.find_one({"_id": traffic.vendorId})
3. Build URL: f"{vendor.postback_url}?respondent_id={traffic.respondent_id}&status={status}&payout={amount}"
4. Make async GET request
5. Log result in cpx_postback_logs
```

---

## 📈 Monitoring & Logging

### Postback Logs Collection
```javascript
cpx_postback_logs: {
  trans_id: "CPX_TRANS_123",
  status: 1,
  amount_usd: 2.50,
  subid_1: "SFWID_123",
  received_at: ISODate("2026-02-03T..."),
  processed: true,
  error: null,
  vendor_postback_url: "https://vendor.com/postback?...",
  vendor_response_status: 200,
  vendor_forwarding_success: true
}
```

### Key Metrics
- **Completion Rate**: (status=1 count) / (total postbacks)
- **Fraud Rate**: (status=2 count) / (total postbacks)
- **Duplicate Rate**: (duplicate postbacks) / (total postbacks)
- **Average Payout**: avg(amount_usd where status=1)
- **Vendor Postback Success**: (vendor_response=200) / (total forwards)

---

## 🚀 API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/cpx/surveys` | GET | Fetch filtered CPX surveys from DB |
| `/api/cpx/allocate` | POST | Allocate survey to respondent, get entry link |
| `/api/cpx/filter-settings` | POST | Save filter preferences |
| `/api/cpx-postback` | GET | CPX server-to-server postback handler |
| `/api/cpx/response` | GET | CRM landing page (shows completion status) |
| `/api/cpx/survey-status` | GET | Polling endpoint for frontend status checks |

---

## 🔄 Entry Link Format

### CPX Href (from API)
```
https://click.cpx-research.com/?k=aB3fD...&api=true&time_stamp=123456&ext_user_id=user123
```

### Platform Entry Link (with tracking)
```
https://click.cpx-research.com/?k=aB3fD...&api=true&time_stamp=123456&ext_user_id=user123&subid_1=SFWID_67890
```

### Postback URL (configured in CPX dashboard)
```
https://surveyfieldwork.com/api/cpx-postback?trans_id={transaction_id}&status={status}&amount_usd={amount_local}&subid={subid_1}&hash={hash_value}
```

---

## 📝 Notes

- **Background Sync**: Platform periodically fetches new surveys from CPX API (configurable interval)
- **Pool Management**: Surveys can be activated/deactivated in pool without affecting CPX inventory
- **Multi-tenancy**: Each vendor has separate traffic records and postback URLs
- **Scalability**: MongoDB indexes enable fast filtering on large survey inventories (1000+ surveys)
- **Fault Tolerance**: Always return HTTP 200 on postback to prevent CPX retry storms

---

*Generated: 2026-02-03*
