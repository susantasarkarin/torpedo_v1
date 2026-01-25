# 🧪 MANUAL TESTING GUIDE - 2026-01-25

## Browser Testing (Unable to Automate)

Unfortunately, the browser automation tool is not available in the current environment. Please follow this manual testing guide.

---

## Test 1: Auto-Click Removal ✅

### URL to Test
```
https://torpedo.cogentixresearch.com/takesurvey?vid=1234&cc=US&rid=12345
```

### Steps
1. Open the URL in your browser
2. Wait for the page to load
3. **Observe for 5-10 seconds**

### Expected Results
✅ **PASS**: Page loads and shows "Next" button  
✅ **PASS**: Button does NOT auto-click  
✅ **PASS**: Button remains visible and clickable  
❌ **FAIL**: Button auto-clicks and redirects immediately

### What to Look For
- The page should display:
  - SurveyFieldwork logo
  - "Thank You for Agreeing To Participate In Our Survey" heading
  - "Next" button (blue/green button)
- The button should **stay visible** and **not click automatically**

---

## Test 2: Survey Allocation (CPX/CINT) ✅

### Steps
1. After confirming no auto-click (Test 1)
2. **Manually click the "Next" button**
3. Wait for redirect (may take 2-5 seconds)
4. Note the final URL

### Expected Results

#### ✅ SUCCESS - CPX Survey
- URL contains: `cpx-research.com` or similar CPX domain
- You see a CPX survey page

#### ✅ SUCCESS - CINT Survey
- URL contains: `cint.com` or `samplicio.us` or similar CINT domain
- You see a CINT survey page

#### ❌ FAILURE - Zoho Fallback
- URL contains: `survey.zohopublic.in/zs/lTCyZz`
- This means allocation failed (should NOT happen)

### What to Check
- Copy the final URL after redirect
- Check if it's a CPX or CINT survey
- If it's Zoho, something is wrong

---

## Test 3: Multiple Allocations

### Steps
1. Test with different country codes:
   ```
   https://torpedo.cogentixresearch.com/takesurvey?vid=1234&cc=US&rid=test001
   https://torpedo.cogentixresearch.com/takesurvey?vid=1234&cc=GB&rid=test002
   https://torpedo.cogentixresearch.com/takesurvey?vid=1234&cc=IN&rid=test003
   ```

2. For each URL:
   - Verify no auto-click
   - Click "Next" manually
   - Note the final destination

### Expected Results
- All should allocate to CPX or CINT surveys
- CPX should work for all countries (CPX handles routing)
- CINT may vary by country availability

---

## Troubleshooting

### If Auto-Click Still Happens
**Problem**: Frontend not deployed properly

**Solution**:
```bash
# SSH into VM
ssh root@139.59.32.72

# Check if frontend was deployed
ls -la /var/www/html/

# Rebuild and redeploy frontend
cd /var/www/campaign_platform/Campaign_platform
git pull origin main
npm install --legacy-peer-deps
npm run build
sudo cp -r dist/* /var/www/html/

# Clear browser cache and try again
```

### If Redirects to Zoho
**Problem**: No active surveys or allocation failing

**Check Backend Logs**:
```bash
ssh root@139.59.32.72 "pm2 logs campaign-backend --lines 100 | grep -E '(📊|🎯|✅|⚠️|❌)'"
```

**Expected Log Output**:
```
📊 Found 50 active CPX surveys (all countries - CPX handles routing)
📊 Found 50 active CINT surveys (before country filter)
📊 Total active surveys in pool: 100
🎯 Selected CPX/CINT survey: {survey_id}
✅ Allocated CPX/CINT survey {survey_id} to SFWID={traffic_id}
```

**If No Surveys Found**:
```bash
# Re-activate surveys
ssh root@139.59.32.72 "bash /tmp/activate-cpx.sh"
```

### If Page Doesn't Load
**Problem**: Nginx or backend issue

**Check Services**:
```bash
# Check Nginx
ssh root@139.59.32.72 "sudo systemctl status nginx"

# Check Backend
ssh root@139.59.32.72 "pm2 status"

# Restart if needed
ssh root@139.59.32.72 "pm2 restart campaign-backend"
ssh root@139.59.32.72 "sudo systemctl restart nginx"
```

---

## Verification Checklist

### Frontend
- [ ] Page loads successfully
- [ ] "Next" button is visible
- [ ] No auto-click occurs (wait 10 seconds)
- [ ] Button can be clicked manually

### Backend Allocation
- [ ] After clicking "Next", page redirects
- [ ] Redirect is to CPX or CINT survey (NOT Zoho)
- [ ] Backend logs show allocation messages
- [ ] Traffic record created in database

### Survey Pool
- [ ] CPX surveys: 1,481 active
- [ ] CINT surveys: 61,416 active
- [ ] Total: 62,897 active surveys

---

## Quick Status Check Commands

### Check Active Surveys
```bash
# CPX active count
ssh root@139.59.32.72 "mongosh localhost:27017/cpx_research --quiet --eval 'db.cpx_surveys.countDocuments({is_active_in_pool: true})'"

# CINT active count
ssh root@139.59.32.72 "mongosh localhost:27017/cint_research --quiet --eval 'db.cint_surveys.countDocuments({is_active_in_pool: true})'"
```

### Check Backend Status
```bash
ssh root@139.59.32.72 "pm2 status campaign-backend"
```

### View Recent Logs
```bash
ssh root@139.59.32.72 "pm2 logs campaign-backend --lines 50"
```

---

## Test Results Template

Please test and report results using this template:

```
TEST RESULTS - 2026-01-25

Test 1: Auto-Click Removal
- Page loaded: YES/NO
- Auto-click occurred: YES/NO
- Button visible: YES/NO
- Status: PASS/FAIL

Test 2: Survey Allocation
- Clicked "Next": YES/NO
- Redirected to: [URL]
- Survey type: CPX/CINT/ZOHO
- Status: PASS/FAIL

Test 3: Multiple Countries
- US (rid=test001): CPX/CINT/ZOHO
- GB (rid=test002): CPX/CINT/ZOHO
- IN (rid=test003): CPX/CINT/ZOHO

Backend Logs:
[Paste relevant log lines here]

Issues Found:
[List any issues]

Overall Status: PASS/FAIL
```

---

## Expected Final State

After successful testing, you should see:

1. ✅ **No auto-click** - Button stays visible
2. ✅ **Manual click works** - Redirects after clicking
3. ✅ **CPX/CINT allocation** - Not Zoho fallback
4. ✅ **Backend logs** - Show allocation messages
5. ✅ **Multiple countries** - All work (CPX handles routing)

---

## Support

If you encounter any issues during testing:

1. **Check backend logs** first
2. **Verify active surveys** count
3. **Clear browser cache** and retry
4. **Report specific error messages**

---

**Testing Guide Created**: 2026-01-25 14:00 IST  
**Status**: Ready for manual testing
