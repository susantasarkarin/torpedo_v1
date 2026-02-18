# Example Output

This document shows example output from the `get_last_cint_payloads` scripts.

## Command
```bash
./scripts/vm_get_cint_payloads.sh 3
```

## Sample Output

```
================================
Cint Payload Retrieval Tool
================================

Configuration:
  VM Host: production-vm.example.com
  VM User: root
  VM Path: /root/campaign_platform
  Limit:   3 payloads

[1/3] Testing SSH connection...
✓ SSH connection successful

[2/3] Detecting available runtime...
✓ Python3 detected

[3/3] Retrieving Cint payloads from VM...

Connecting to MongoDB...
Retrieving last 3 Cint respondent payloads...

================================================================================
LAST 3 RESPONDENT PAYLOADS SENT TO CINT
================================================================================

[1] Timestamp: 2026-02-18 14:30:45 UTC
--------------------------------------------------------------------------------

Payload sent to Cint API:
  POST https://api.samplicio.us/supply/v1/entrylinks
    survey_id: 12345678
    supplier_code: 6777
    respondent_id: user_abc123_1708267845
    secure_hash: [HMAC-SHA256 hash - not stored]
    return_url: https://torpedo.cogentixresearch.com/api/cint/status

Metadata:
    allocation_id: 65d3f8a1b2c4e5f6a7b8c9d0
    vid: 1001
    cc: US
    ip_address: 192.168.1.100
    user_agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
    survey_name: US Consumer Survey Q1 2026
    survey_status: active

Cint Survey Details:
    survey_name: Consumer Preferences Study
    country_language: en-US
    loi: 15
    cpi: 2.50
    conversion: 0.75

================================================================================

[2] Timestamp: 2026-02-18 14:28:12 UTC
--------------------------------------------------------------------------------

Payload sent to Cint API:
  POST https://api.samplicio.us/supply/v1/entrylinks
    survey_id: 12345679
    supplier_code: 6777
    respondent_id: user_xyz456_1708267692
    secure_hash: [HMAC-SHA256 hash - not stored]
    return_url: https://torpedo.cogentixresearch.com/api/cint/status

Metadata:
    allocation_id: 65d3f8a1b2c4e5f6a7b8c9d1
    vid: 1002
    cc: UK
    ip_address: 192.168.1.101
    user_agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36
    survey_name: UK Shopping Habits Survey
    survey_status: active

Cint Survey Details:
    survey_name: Shopping Behavior Analysis
    country_language: en-GB
    loi: 10
    cpi: 3.00
    conversion: 0.82

================================================================================

[3] Timestamp: 2026-02-18 14:25:33 UTC
--------------------------------------------------------------------------------

Payload sent to Cint API:
  POST https://api.samplicio.us/supply/v1/entrylinks
    survey_id: 12345680
    supplier_code: 6777
    respondent_id: user_def789_1708267533
    secure_hash: [HMAC-SHA256 hash - not stored]
    return_url: https://torpedo.cogentixresearch.com/api/cint/status

Metadata:
    allocation_id: 65d3f8a1b2c4e5f6a7b8c9d2
    vid: 1003
    cc: CA
    ip_address: 192.168.1.102
    user_agent: Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)
    survey_name: Canada Tech Survey
    survey_status: active

Cint Survey Details:
    survey_name: Technology Adoption Survey
    country_language: en-CA
    loi: 12
    cpi: 2.75
    conversion: 0.68

================================================================================

Total payloads retrieved: 3

✓ Successfully retrieved payloads
```

## Explanation

### Payload Fields

Each payload shows exactly what was sent to Cint's API:

- **survey_id**: The Cint survey identifier (integer)
- **supplier_code**: Your Cint supplier account code (default: 6777)
- **respondent_id**: Your internal unique identifier for the respondent
- **secure_hash**: HMAC-SHA256 signature for security (computed at runtime, not stored)
- **return_url**: Callback URL where Cint sends completion/termination status

### Metadata Fields

Additional context about the allocation:

- **timestamp**: When the respondent was allocated to this survey
- **allocation_id**: Unique MongoDB ObjectId for this allocation
- **vid**: Vendor ID (traffic source)
- **cc**: Country code (2-letter ISO)
- **ip_address**: Respondent's IP address
- **user_agent**: Respondent's browser/device information
- **survey_name**: Your internal name for the survey
- **survey_status**: Current survey status (active/paused/inactive)

### Cint Survey Details

Information from Cint's opportunity feed (when available):

- **survey_name**: Cint's name for the survey
- **country_language**: Target country and language (e.g., en-US, en-GB)
- **loi**: Length of Interview in minutes
- **cpi**: Cost Per Interview in USD
- **conversion**: Historical conversion/completion rate (0-1)

## Use Cases

### 1. Debugging Respondent Issues

If a respondent reports issues, you can:
1. Search for their `respondent_id` in the output
2. Verify the correct `survey_id` was used
3. Check the timestamp to confirm when they were allocated
4. Use the `allocation_id` to trace through logs

### 2. Revenue Tracking

Track which surveys respondents were sent to:
- CPI values show potential revenue
- Conversion rates help predict completions
- Can aggregate by country, survey, or time period

### 3. Quality Assurance

Verify the allocation system is working:
- Confirm payloads have all required fields
- Check that country codes match survey requirements
- Verify timestamps are recent for active campaigns

### 4. API Auditing

Review what's being sent to Cint:
- Ensure `supplier_code` is correct
- Verify `return_url` is reachable
- Confirm `respondent_id` format is consistent

## Notes

- The `secure_hash` is computed at runtime using HMAC-SHA256 and is not stored in the database
- Allocation logs have a 30-day TTL (time-to-live) and are automatically deleted
- Timestamps are in UTC
- Cint survey details may be unavailable if the survey is no longer in the opportunity feed
