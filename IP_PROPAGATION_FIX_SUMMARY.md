# IP Address Propagation Fix - Complete Implementation

## Problem
The user's IP address was not being propagated through the survey allocation service chain. The CPX API was receiving the hardcoded Indian IP (103.21.124.1) instead of the user's real IP, causing CPX's fraud detection to reject the session with `api_standart_screen_out` errors.

## Root Cause
The allocation flow was broken:
- ✅ Traffic router extracted real IP from request headers
- ✅ CPXService.fetch_and_allocate_for_respondent() accepts user_ip parameter
- ❌ SurveyAllocationService methods didn't pass user_ip through the chain

## Changes Made

### 1. survey_allocation_service.py - _try_atomic_allocation() (Line 490)
**Updated:** Pass request.ip_address to _build_entry_link()

```python
entry_link = self._build_entry_link(
    survey=survey,
    respondent_id=respondent_id,
    allocation_id=allocation_id,
    user_ip=request.ip_address  # ← NEW
)
```

### 2. survey_allocation_service.py - _build_entry_link() (Line 597)
**Updated:** Add user_ip parameter and pass to _build_cpx_entry_link()

```python
def _build_entry_link(
    self, 
    survey: dict, 
    respondent_id: str,
    allocation_id: str,
    user_ip: Optional[str] = None  # ← NEW
) -> str:
    # ...
    if provider == "CPX":
        return self._build_cpx_entry_link(
            survey=survey,
            respondent_id=respondent_id,
            user_ip=user_ip  # ← NEW
        )
```

### 3. survey_allocation_service.py - _build_cpx_entry_link() (Line 628)
**Updated:** Add user_ip parameter and pass to CPX service

```python
def _build_cpx_entry_link(
    self,
    survey: dict,
    respondent_id: str,
    user_ip: Optional[str] = None  # ← NEW
) -> str:
    """
    Args:
        survey: Survey document from allocation pool
        respondent_id: Respondent's SFWID
        user_ip: Optional IP address of the respondent (passed from request)  # ← NEW
    """
    # ...
    result = cpx_service.fetch_and_allocate_for_respondent(
        respondent_id=respondent_id,
        user_ip=user_ip  # ← NEW - Pass to CPX API
    )
```

## Complete Flow (Fixed)

```
Request (traffic.py)
    ↓
    Extract client IP: request.client.host
    ↓
AllocationRequest(ip_address=real_ip)
    ↓
allocate_respondent(request)
    ↓
_try_atomic_allocation(request)
    ↓
_build_entry_link(user_ip=request.ip_address)
    ↓
_build_cpx_entry_link(user_ip=...)
    ↓
CPXService.fetch_and_allocate_for_respondent(user_ip=real_ip)
    ↓
CPX API gets correct IP in ip_user parameter ✅
```

## Expected Impact

- CPX API now receives the actual user's IP address instead of hardcoded 103.21.124.1
- CPX's fraud detection can properly validate the session (allocation IP = click IP)
- Should resolve `api_standart_screen_out` errors and 100% rejection rates
- Survey completion rates should improve significantly

## Testing Checklist

- [ ] Verify traffic.py correctly extracts request.client.host
- [ ] Monitor CPX API logs for correct IP in allocation requests
- [ ] Check for reduction in api_standart_screen_out errors
- [ ] Confirm click-to-completion conversion rates improve
- [ ] Test with multiple IPs to ensure propagation works correctly

## Files Modified

1. `backend/app/services/survey_allocation_service.py` (3 methods updated)
   - _try_atomic_allocation() - passes user_ip
   - _build_entry_link() - accepts and passes user_ip
   - _build_cpx_entry_link() - accepts and passes user_ip to CPX service

## Status

✅ **COMPLETE** - IP address propagation chain is now fully connected from request → CPX API
