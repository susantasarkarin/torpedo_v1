# Deployment Instructions - Bug Fixes

## Date: 2026-01-25
## Changes Pushed to GitHub: ✅ Completed

**Commit Hash**: 8870d13  
**Branch**: main  
**Repository**: https://github.com/sristi3227/campaign_platform.git

---

## Changes Deployed

1. **Frontend**: TrafficFlowParser.jsx - Removed auto-click behavior
2. **Backend**: traffic.py - Fixed survey allocation (CPX + CINT active surveys with country matching)
3. **Backend**: cpx_service.py - Fixed CPX entry link parameters
4. **Documentation**: BUG_FIXES_2026-01-25.md - Complete bug fix documentation

---

## VM Deployment Commands

### Option 1: Quick Update (Recommended)

SSH into the VM and run these commands:

```bash
# SSH into VM
ssh root@139.59.32.72

# Navigate to project backend
cd /home/susanta/campaign_platform/backend

# Pull latest changes from GitHub
git pull origin main

# Install any new dependencies (if any)
pip install -r requirements.txt

# Restart backend service
pm2 restart campaign-backend

# Check status
pm2 status

# View logs to verify deployment
pm2 logs campaign-backend --lines 50
```

### Option 2: Full Deployment (If Issues Occur)

If the quick update doesn't work, run the full deployment:

```bash
# SSH into VM
ssh root@139.59.32.72

# Navigate to project root
cd /home/susanta/campaign_platform

# Pull latest changes
git pull origin main

# Navigate to backend
cd backend

# Reinstall dependencies
pip install -r requirements.txt

# Stop backend
pm2 stop campaign-backend

# Start backend fresh
pm2 start "python3 -m uvicorn main:app --host 0.0.0.0 --port 8000" --name "campaign-backend"

# Save PM2 configuration
pm2 save

# Check status
pm2 status

# View logs
pm2 logs campaign-backend
```

---

## Frontend Deployment (If Needed)

The frontend changes are in the React app. If you need to rebuild and deploy:

```bash
# SSH into VM
ssh root@139.59.32.72

# Navigate to frontend
cd /home/susanta/campaign_platform/Campaign_platform

# Install dependencies
npm install --legacy-peer-deps

# Build frontend
npm run build

# Copy to web server (if using Nginx/Apache)
sudo cp -r dist/* /var/www/html/

# Or if using a different web root, adjust the path accordingly
```

---

## Verification Steps

### 1. Test Parsing Page (Manual Click)
Visit: https://torpedo.cogentixresearch.com/takesurvey?vid=1234&cc=US&rid=12345

**Expected Behavior**:
- Page should load and show the "Next" button
- Button should NOT automatically click
- User must manually click "Next" to proceed
- After clicking, system should allocate a survey and redirect

### 2. Test Survey Allocation
Check backend logs for allocation messages:

```bash
ssh root@139.59.32.72 "pm2 logs campaign-backend --lines 100 | grep -E '(📊|🎯|✅)'"
```

**Expected Log Output**:
```
📊 Found X active CPX surveys for country US
📊 Found Y active CINT surveys (before country filter)
📊 Total active surveys in pool: Z (CPX: X, CINT: Y)
🎯 Selected CPX/CINT survey: {survey_id}
✅ Allocated CPX/CINT survey {survey_id} to SFWID={traffic_id}
```

### 3. Test Survey Pool Active Filter
Visit: https://torpedo.cogentixresearch.com/admin/survey-pool

**Expected Behavior**:
- Toggle "Show Active Only" filter
- Should display both CPX and CINT active surveys
- Inactive surveys should be hidden when filter is enabled

### 4. Check CPX Entry Links
In the backend logs, verify CPX entry links have the correct format:

```
{live_link}&ext_user_id={id}&app_id=10754&secure_hash={hash}&username=&email=&subid_1={id}&subid_2=
```

---

## Troubleshooting

### Issue: Backend won't restart
```bash
# Check if port 8000 is in use
ssh root@139.59.32.72 "lsof -i :8000"

# Kill the process if needed
ssh root@139.59.32.72 "lsof -i :8000 | grep LISTEN | awk '{print \$2}' | xargs kill -9"

# Restart backend
ssh root@139.59.32.72 "pm2 restart campaign-backend"
```

### Issue: No active surveys found
```bash
# SSH into VM
ssh root@139.59.32.72

# Connect to MongoDB
mongosh localhost:27017/campaign_platform

# Check CPX active surveys
db.cpx_surveys.countDocuments({ is_active_in_pool: true })

# Check CINT active surveys
db.cint_surveys.countDocuments({ is_active_in_pool: true })

# If no active surveys, run sync from Survey Pool page:
# Visit: https://torpedo.cogentixresearch.com/admin/survey-pool
# Click: "🔄 Sync & Activate Surveys" button
```

### Issue: Git pull fails
```bash
# SSH into VM
ssh root@139.59.32.72

# Navigate to project
cd /home/susanta/campaign_platform

# Check git status
git status

# If there are uncommitted changes, stash them
git stash

# Pull latest changes
git pull origin main

# Restore stashed changes if needed
git stash pop
```

---

## Post-Deployment Checklist

- [ ] SSH into VM successful
- [ ] Git pull completed without errors
- [ ] Backend restarted successfully
- [ ] PM2 shows "online" status for campaign-backend
- [ ] No errors in PM2 logs
- [ ] Parsing page loads correctly (manual click required)
- [ ] Survey allocation working (check logs)
- [ ] Both CPX and CINT active surveys visible in Survey Pool
- [ ] CPX entry links have correct format

---

## Important Notes

1. **Domain**: The parsing page is accessible at `https://torpedo.cogentixresearch.com/takesurvey`
2. **Backend Port**: Backend runs on port 8000, proxied through Nginx
3. **PM2**: Backend is managed by PM2 process manager
4. **MongoDB**: Ensure MongoDB is running on localhost:27017

---

## Contact Information

**VM IP**: 139.59.32.72  
**SSH User**: root  
**Backend Port**: 8000  
**Frontend URL**: https://torpedo.cogentixresearch.com  
**API Docs**: https://torpedo.cogentixresearch.com/docs

---

## Next Steps

1. Run the deployment commands above
2. Verify the parsing page behavior
3. Test survey allocation with different country codes
4. Monitor PM2 logs for any errors
5. Report any issues encountered

---

**Deployment Status**: ✅ Code pushed to GitHub, ready for VM deployment  
**Last Updated**: 2026-01-25 13:17 IST
