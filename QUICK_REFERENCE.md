# Cint P0 Fixes: Quick Reference

## What Was Fixed

### 1. Subscription Validation (P0-1)
- ✅ HTTPS enforcement in production
- ✅ Callback URL validation
- ✅ Error state tracking in MongoDB
- ✅ Health check method

**Files**: cint_service.py L649-910

### 2. Entry Link Flow (P0-2)
- ✅ Use stored live_link from Cint API directly
- ✅ NO custom parameter appending
- ✅ Cint placeholders ([%MID%]) work correctly

**Files**: cint_allocation_extension.py L150-177, cint.py L480-510

### 3. Callback Verification (P0-3)
- ✅ HMAC-SHA256 signature validation
- ✅ Idempotency check (no duplicate credits)
- ✅ All callbacks logged to outcomes

**Files**: traffic.py L88-250

### 4. Status Mapping (P0-4)
- ✅ All 5 Cint status codes handled (10, 20, 30, 40, 50)
- ✅ Fail fast on unknown codes
- ✅ Explicit error handling

**Files**: cint_service.py L1088-1140

---

## Critical Change: Entry Link Behavior

### OLD (Wrong for Cint) ❌
```python
complete_link = cint_service.build_entry_link(
    live_link="https://...?[%MID%]=...",
    respondent_id="123",
    country_code="US"
)
# Result: https://...?[%MID%]=...&rid=123&cc=US  ❌ BROKEN
```

### NEW (Correct for Cint) ✅
```python
if entry_link.live_link:
    return entry_link.live_link
# Result: https://...?[%MID%]=...  ✅ CORRECT
# Cint replaces [%MID%] automatically
```

---

## Cint Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 10 | Complete | Credit respondent |
| 20 | Terminate | Log but no credit |
| 30 | Over quota | Log, survey full |
| 40 | Quality term | Log, respondent disqualified |
| 50 | Survey closed | Log, survey ended |

---

## Testing Checklist

```
P0-1: Subscription
□ Callback URL must have https:// in production
□ Subscription status in MongoDB
□ Health check works

P0-2: Entry Link
□ live_link has [%MID%] placeholder
□ Respondent can click and reach survey
□ Cint replaces [%MID%]

P0-3: Callback
□ Signature validation works
□ Duplicate callbacks ignored (5 second window)
□ All callbacks logged

P0-4: Status
□ Codes 10, 20, 30, 40, 50 all handled
□ Unknown codes trigger error
□ No "unknown_99" fallback strings
```

---

## MongoDB Collections

```python
cint_settings              # Subscription status + errors
cint_entry_links          # Stored live_links
cint_surveys              # Survey inventory
cint_respondent_outcomes  # Callback audit trail
```

---

## Environment Variables

```bash
CINT_API_BASE_URL=https://api.samplicio.us  # Production, not sandbox
CINT_CALLBACK_URL=https://yourdomain.com/cint-response
CINT_API_KEY=<your-api-key>
CINT_SUPPLIER_CODE=<your-code>
```

---

## Key Differences: CPX vs Cint

| Aspect | CPX | Cint |
|--------|-----|------|
| Entry link | Dynamic (built per respondent) | Static (created once per survey) |
| Parameters | Custom (`rid`, `cc`) | Cint placeholders (`[%MID%]`) |
| Generation | No API call (just append params) | Requires API call (one-time) |
| Storage | Not stored (computed) | Stored in DB |
| Respondent ID | Appended to URL | Cint replaces placeholder |

---

## Deployment Status

✅ **All P0 blockers complete**
✅ **Ready for staging deployment**
⏳ **Requires MongoDB collections**
⏳ **Requires environment variables**

---

## Files Modified

1. **cint_service.py** - Subscription validation, health check, status mapping
2. **cint_allocation_extension.py** - Entry link retrieval (fixed)
3. **cint.py** - Entry link API (fixed)
4. **traffic.py** - Callback handler with signature verification

---

## Quick Test

```bash
# Check subscription health
curl -X GET http://localhost:8000/cint/health

# Check entry link exists
curl -X GET http://localhost:8000/cint/entry-link/<survey_id>

# Verify callback handler accepts status codes
curl "http://localhost:8000/cint-response?status=10&mid=123"
```

---

## Next: P1 Priorities

1. **P1-1**: Qualification validation
2. **P1-2**: Traffic control & survey ranking

See CINT_P0_BLOCKERS_COMPLETE.md for details.

