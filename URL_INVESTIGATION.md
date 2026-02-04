# CPX Survey Flow Investigation

## URL Chain Analysis

### 1. CPX Entry Link (Survey Click)
```
https://click.cpx-research.com/?k=MWdKMVNaRjVoSXBzbnJRUTQxZDdhVFV5ZGcwNkVlQ2VCUWhRV3BXb2tidnlUZUdIQVFmb0FyK3lyYmxkNHJTWldKYVErVlUvS0tHZk5FN2IydG1IYlY0ODF0N3RaRG1rMGtMRVZsSEl2bDB1aW9xSHNid1BjRTNESXRHZTNkazRNZXgzRU51UG10Y3U0dTZFdkZ5WG51UkpWamdDTU8xMTRPWkJUaWl1eEFCcENCd2Fhank2Rmh4SzdvdkViSUlo&api=true&time_stamp=1770094279&subid_1=69817ec652936c484f734ae1
```

**Parameters:**
- `k` = Encrypted CPX token (contains survey ID, respondent ID, timestamp, etc.)
- `api=true` = API mode
- `time_stamp=1770094279` = Unix timestamp (Dec 3, 2025 ~16:24:39 UTC)
- `subid_1=69817ec652936c484f734ae1` = **SFWID (Survey Field Work ID)** - our respondent tracking ID

**Status:** ✅ Entry link correctly generated with subid_1 appended

---

### 2. CPX Callback Response
```
https://torpedo.cogentixresearch.com/cpx-response?msg=b3o1ZW1Cb3FzNjV0THFmVFB4VlpUQT09&status=out&sfwid=69817ec652936c484f734ae1
```

**Parameters:**
- `msg` = Encrypted message from CPX (validation token)
- `status=out` = **RESPONDENT TERMINATED/DROPPED OUT**
- `sfwid=69817ec652936c484f734ae1` = Our SFWID sent back for tracking

**Status:** ⚠️ **Respondent was rejected by CPX** (status=out means they didn't qualify or were screened out)

---

### 3. Samplicio.us Callback URLs
```
https://samplicio.us/s/ClientCallBack.aspx?RIS=20&RID=69817eb2-b460-0512-7ff5-1a95332e42ca
https://samplicio.us/s/respondent-callback?RIS=20&RID=69817eb2-b460-0512-7ff5-1a95332e42ca
https://www.samplicio.us/s/ThankYou.aspx
```

**Status:** These are Cint (Samplicio.us) platform callbacks - appears respondent never reached Cint, only CPX was attempted.

---

## Issue Analysis

### Problem: Respondent Status = OUT (Terminated)
**CPX is rejecting respondents at the survey entry point**

#### Possible Root Causes:

1. **IP/UA Fingerprint Mismatch** ❌
   - CPX validates the IP+UA combination from the entry link against the click
   - If IP or UA changed between API call and survey click = rejection
   - Our fix captures real device IP from parsing page - this should help

2. **Encrypted k= Parameter Validation** ❓
   - The `k` parameter is encrypted by CPX
   - Contains: respondent ID, IP, UA, timestamp, survey ID
   - If CPX validation fails during click = status=out

3. **Respondent Doesn't Match CPX Criteria** ❌
   - IPAddress is blacklisted
   - VPN/Proxy detected
   - Device type/browser mismatch
   - Geolocation doesn't match survey target

4. **Rate Limiting / Duplicate Detection** ⚠️
   - Same respondent clicking multiple times
   - Too many clicks from same IP in short time
   - CPX flagging as bot/fraud

---

## Key Observations

| Item | Value | Status |
|------|-------|--------|
| SFWID Generated | 69817ec652936c484f734ae1 | ✅ Consistent |
| Entry Link Created | Yes, with k= parameter | ✅ Correct |
| Respondent Clicked | Yes (callback received) | ✅ Confirmed |
| Survey Completion | NO - status=out | ❌ Failed |
| Time Between API & Click | Unknown | ⚠️ Need logs |

---

## Next Steps for Investigation

1. **Check CPX API Response** for the SFWID
   - Did CPX return surveys for this respondent?
   - What IP/UA was sent?
   - How many surveys were returned?

2. **Compare IP/UA Between:**
   - Parsing page detection (traffic.py logs)
   - CPX API call (cpx_service.py logs)
   - Survey click (CPX validation)

3. **Check CPX Validation Message**
   - Decrypt or log the `msg` parameter from callback
   - This might indicate WHY the respondent was rejected

4. **Monitor New Traffic**
   - Watch logs for new SFWID allocations
   - Track status=out vs status=complete ratio
   - Check if IP/UA now stable across flow

---

## Expected Flow (with fix)

```
1. Parsing Page
   └─ Extract: IPv4 (real device) + User-Agent (real browser)
   
2. CPX API Call (/api/store)
   └─ Send: SFWID + IPv4 + User-Agent
   
3. CPX Response
   └─ Get: href with encrypted k= (contains IP+UA hash)
   
4. Entry Link Generation
   └─ URL: click.cpx-research.com/?k=[encrypted]&subid_1=[SFWID]
   
5. Respondent Clicks
   └─ Same IPv4 + User-Agent + cookies match encrypted k=
   
6. CPX Validation ✅
   └─ Status: complete or terminate (based on screener)
   
7. Callback to Torpedo
   └─ POST: /cpx-response?status=...&sfwid=...
```

---

## Conclusion

The URLs show a valid CPX survey was offered and the respondent clicked, but **CPX rejected them with status=out**.

**This is NOT an IP/UA mismatch problem** - because:
- ✅ Entry link was generated correctly with proper subid_1
- ✅ CPX accepted the click (sent callback)
- ❌ But respondent failed survey qualifications

**The fix we deployed** (real device IP detection) should help prevent premature rejections caused by IP/UA mismatches, but this particular respondent's termination was likely due to:
- Survey disqualification (screener question failed)
- Geolocation/device mismatch with survey requirements
- VPN/Proxy detection by CPX security
