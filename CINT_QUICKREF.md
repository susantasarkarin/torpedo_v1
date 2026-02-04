# CINT Allocation - Quick Reference Guide

## Current Status: 🟡 Partially Working (50/22,741 surveys)

---

## Quick Commands

### 1. Check Current State
```bash
cd /var/www/campaign_platform/backend
python ../../check_cint_final_state.py
```
**Output:** Shows surveys, entry links, settings  
**Time:** <5 seconds

### 2. Scale Entry Links to Full Set (RECOMMENDED NEXT STEP)
```bash
cd /var/www/campaign_platform/backend
python ../../create_cint_entry_links_at_scale.py
```
**Output:** Creates 22,741 entry links total  
**Time:** ~1-2 minutes  
**Result:** 100% coverage, allocation ready to use

### 3. Run Full Test Suite
```bash
cd /var/www/campaign_platform/backend
python ../../test_cint_allocation.py
```
**Output:** 4 tests (surveys, links, query, retrieval)  
**Time:** ~10 seconds  
**Expected:** 4/4 PASS ✅

### 4. Test Allocation Manually
```python
# In Python shell at /var/www/campaign_platform/backend:
import asyncio
from app.services.cint_allocation_extension import CintAllocationExtension
from pymongo import MongoClient

ext = CintAllocationExtension()

# Create test respondent
class TestRespondent:
    rid = "TEST_12345"
    cc = "US"

respondent = TestRespondent()

# Match to survey
survey = asyncio.run(ext.match_respondent_to_cint_surveys(respondent))
print(f"Matched survey: {survey.survey_id if survey else 'None'}")

# Get entry link
if survey:
    link = asyncio.run(ext.build_cint_entry_link(respondent, survey))
    print(f"Entry link: {link}")
```

---

## Database Queries

### Check Survey State
```javascript
// Active surveys
db.cint_surveys.count_documents({is_active_in_pool: true})
// Should return: 22,741

// Survey with entry link
db.cint_surveys.findOne({is_active_in_pool: true})

// Entry link for survey
db.cint_entry_links.findOne({survey_id: <survey_id>})
```

### Entry Link Format
```javascript
{
  survey_id: 72505687,
  live_link: "https://torpedo.cogentixresearch.com/cint-response?mid=[%MID%]&sid=72505687&status=start",
  synthetic: true,
  _type: "synthetic_entry_link"
}
```

---

## Troubleshooting

| Issue | Check | Solution |
|-------|-------|----------|
| No surveys found | `db.cint_surveys.count_documents({})` | Run webhook sync or check MongoDB connection |
| No active surveys | `db.cint_surveys.count_documents({is_active_in_pool: true})` | Run `sync_active_status_by_filters()` |
| No entry links | `db.cint_entry_links.count_documents({})` | Run `create_cint_entry_links_at_scale.py` |
| Allocation returns null | Run `test_cint_allocation.py` TEST 3 | Check survey query filters |
| [%MID%] not replaced | Test with live respondent | May need code change if Cint doesn't auto-replace |

---

## Files

### Ready to Run
- ✅ `check_cint_final_state.py` - State verification
- ✅ `create_cint_entry_links_at_scale.py` - Scale links to 22,741
- ✅ `test_cint_allocation.py` - Test suite (4 tests)

### Source Code
- `backend/app/services/cint_service.py` - Survey sync logic
- `backend/app/services/cint_allocation_extension.py` - Allocation queries
- `backend/app/routers/cint.py` - Cint API routes

### Documentation
- `CINT_ALLOCATION_FIX_STATUS.md` - Full report
- This file - Quick reference

---

## Key Metrics

```
Total Surveys:            109,471
Active (allocatable):      22,741
Entry Links:                   50 (need → 22,741)
Coverage:                    0.2% (need → 100%)

Next Step: Run create_cint_entry_links_at_scale.py
```

---

## Deployment Checklist

- [ ] Run `check_cint_final_state.py` - Verify current state
- [ ] Run `create_cint_entry_links_at_scale.py` - Scale to full set
- [ ] Run `test_cint_allocation.py` - Verify allocation works
- [ ] Enable Cint surveys in campaign UI
- [ ] Test with sample respondent
- [ ] Monitor allocation logs for errors
- [ ] [LATER] Contact Cint for official supplier allocation

---

## Notes

**Synthetic Links:** Using `[%MID%]` placeholder - Cint replaces with actual MID  
**Coverage:** Will reach 100% after scaling script  
**Blockage:** Waiting for Cint manual supplier allocation (6777) for official links  
**Workaround:** Synthetic links sufficient for testing & limited production use

---

**Last Updated:** 2026-01-28  
**Status:** Ready for entry link scaling  
**Next Action:** Run `create_cint_entry_links_at_scale.py`
