# Traffic Dashboard Deployment Guide

## Summary of Changes
This deployment includes the Traffic Management Dashboard consolidation to show only:
- Total entrants (sum of all records)
- Complete
- Incomplete (merged from terminated, fallback statuses)
- Quota Full

### Files Modified
- `backend/app/services/traffic_service.py` - Added status normalization logic
- `Campaign_platform/src/pages/operations/TrafficManagement.jsx` - Updated UI to show 4 categories

### Git Commit
- Commit Hash: `51d0a0e`
- Branch: `fix/cint-waterfall-async`
- Status: ✅ Pushed to GitHub

---

## Deployment Instructions

### Option 1: Azure VM (campaign-vm.eastus.cloudapp.azure.com)

#### 1. Connect to VM
```bash
ssh azureuser@campaign-vm.eastus.cloudapp.azure.com
cd /home/azureuser/campaign_platform
```

#### 2. Pull Latest Changes
```bash
git pull origin fix/cint-waterfall-async
# Or if you want to merge to main:
git checkout main
git pull origin main
git merge fix/cint-waterfall-async
```

#### 3. Rebuild Frontend
```bash
cd Campaign_platform
npm install
npm run build
```

#### 4. Restart Backend Service
```bash
cd ..
sudo systemctl restart campaign-backend
# Verify status:
sudo systemctl status campaign-backend
```

#### 5. Verify Deployment
```bash
curl http://localhost:5000/api/health
```

---

### Option 2: Torpedo VM (torpedo.cogentixresearch.com)

#### 1. Connect to VM
```bash
ssh root@torpedo.cogentixresearch.com
cd /var/www/torpedo
```

#### 2. Pull Latest Changes
```bash
git pull origin fix/cint-waterfall-async
```

#### 3. Update Python Dependencies
```bash
cd backend
pip install -r requirements.txt
```

#### 4. Rebuild Frontend
```bash
cd ../Campaign_platform
npm install
npm run build
```

#### 5. Restart Services
```bash
# If using Docker:
docker-compose restart backend frontend

# If using systemd:
sudo systemctl restart torpedo-backend
```

---

### Option 3: Using PowerShell Script (Windows)

```powershell
# From your local machine:
cd "D:\Code\03. Projects\01. torpedo wip\01. Torpedo v1 (python reacy)"

# For Azure VM:
.\deploy\scripts\sync-to-vm.ps1

# For Torpedo VM:
.\deploy\scripts\deploy_to_vm.ps1 -VMHost "torpedo.cogentixresearch.com" -VMUser "root"
```

---

## Post-Deployment Checks

### 1. Verify Backend API
```bash
# Check traffic stats endpoint
curl -H "Authorization: YOUR_SESSION_ID" http://localhost:5000/api/traffic/stats

# Should return:
# {
#   "total": 1234,
#   "by_status": {
#     "Complete": 567,
#     "Incomplete": 543,
#     "Quota Full": 124
#   }
# }
```

### 2. Check Frontend UI
1. Navigate to: `http://your-vm:5173/operations`
2. Look for "Traffic Management" section
3. Verify stats cards show:
   - Total Records
   - Complete
   - Incomplete
   - Quota Full
4. Verify status filter dropdown shows only these 4 options

### 3. Monitor Logs
```bash
# Docker logs:
docker-compose logs -f backend

# Systemd logs:
sudo journalctl -u campaign-backend -f

# Frontend build logs:
cd Campaign_platform && npm run build
```

---

## Rollback Instructions (If Needed)

### Option 1: Revert Commit
```bash
git revert 51d0a0e
git push origin fix/cint-waterfall-async
# Then redeploy with above steps
```

### Option 2: Go Back to Previous Version
```bash
git checkout main  # if you merged to main
git reset --hard HEAD~1
git push origin main --force
```

---

## Documentation

For more information on the changes:
- **Backend changes**: See `_normalize_status()` method in `backend/app/services/traffic_service.py` (line ~497)
- **Frontend changes**: See status color mapping in `Campaign_platform/src/pages/operations/TrafficManagement.jsx` (line ~8)

## Support

If deployment fails:
1. Check VM SSH/network connectivity
2. Verify git credentials are configured
3. Ensure required ports are open (5000 for backend, 5173 for frontend)
4. Check disk space: `df -h`
5. Review logs from services
