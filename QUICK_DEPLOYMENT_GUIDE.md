# Quick Deployment Guide

## Overview
This guide will help you deploy the Cint integration fixes to your production VM at **torpedo.cogentixresearch.com**.

## What Gets Deployed
- **backend/app/routers/cint.py** - Fixed webhook error handling, entry link 404 detection, diagnostic endpoint
- **backend/app/services/cint_service.py** - Enhanced logging for entry link debugging
- **Documentation files** - Status reports, diagnostic guides, integration docs

## Prerequisites

1. **SSH Access** to your VM
   - Have your SSH key configured for passwordless login
   - Test: `ssh user@torpedo.cogentixresearch.com`

2. **Environment Variables** (set these before running scripts)
   ```bash
   # Required
   export VM_USER="root"                          # Your SSH username
   export VM_PATH="/var/www/torpedo/backend"      # Backend path on VM
   export SERVICE_NAME="torpedo-backend"          # Systemd service name
   ```

3. **Tools Installed**
   - **Linux/Mac/WSL**: bash, ssh, scp
   - **Windows**: PowerShell + OpenSSH Client
     - Install OpenSSH: Settings → Apps → Optional Features → Add "OpenSSH Client"

## Deployment Methods

### Method 1: Automated Script (Recommended)

#### On Linux/Mac/WSL:
```bash
# Make script executable
chmod +x deploy_to_vm.sh verify_deployment.sh

# Set your VM credentials
export VM_USER="root"
export VM_PATH="/var/www/torpedo/backend"
export SERVICE_NAME="torpedo-backend"

# Run deployment
./deploy_to_vm.sh

# Verify deployment
./verify_deployment.sh
```

#### On Windows (PowerShell):
```powershell
# Run deployment
.\deploy_to_vm.ps1 -VMUser "root" -VMPath "/var/www/torpedo/backend" -ServiceName "torpedo-backend"

# Verify deployment (requires WSL or Git Bash)
bash verify_deployment.sh
```

### Method 2: Manual Deployment

Follow the steps in **DEPLOYMENT_CHECKLIST.md**:

```bash
# 1. Commit changes locally
git add backend/app/routers/cint.py backend/app/services/cint_service.py
git commit -m "Fix: Cint integration webhook error handling and diagnostics"
git push origin main

# 2. SSH to VM and pull changes
ssh user@torpedo.cogentixresearch.com
cd /path/to/backend
git pull origin main

# 3. Restart service
sudo systemctl restart torpedo-backend

# 4. Verify
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic
```

## Post-Deployment Verification

### Step 1: Check Diagnostic Endpoint
```bash
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic | jq
```

**Expected Output:**
```json
{
  "timestamp": "2026-02-08T20:00:00",
  "surveys": {
    "total": 150,
    "active": 120,
    "live": 95
  },
  "entry_links": {
    "total": 95,
    "with_live_link": 95,
    "without_live_link": 0
  },
  "issues": [],
  "recommendations": []
}
```

### Step 2: Monitor Webhook Activity
```bash
# SSH to VM
ssh user@torpedo.cogentixresearch.com

# Watch for incoming webhooks (should appear every 15 seconds)
tail -f /var/log/torpedo/backend.log | grep "Received opportunities webhook"
```

**Expected:**
```
2026-02-08 20:00:15 INFO: Received opportunities webhook with 25 surveys
2026-02-08 20:00:30 INFO: Received opportunities webhook with 23 surveys
2026-02-08 20:00:45 INFO: Received opportunities webhook with 28 surveys
```

### Step 3: Check Entry Link Debug Logs
```bash
tail -f /var/log/torpedo/backend.log | grep "ENTRY LINK DEBUG"
```

**Expected:**
```
[ENTRY LINK DEBUG] Cint API response for survey 123456: {"SupplierLink": {"LiveLink": "...", "TestLink": "..."}}
[ENTRY LINK DEBUG] Response keys: ['SupplierLink', 'Status']
[ENTRY LINK DEBUG] SupplierLink has live_link: True
[ENTRY LINK DEBUG] Created SupplierLink object with live_link: https://...
```

## Diagnostic Questions Answered

### Question 1: Are Cint inventories getting downloaded?

**Check:**
```bash
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic | jq '.surveys'
```

- **surveys.total > 0**: ✅ Yes, inventories are being downloaded
- **surveys.total = 0**: ❌ No, check webhook subscription or wait 5-10 minutes

### Question 2: Are entry links created with live_link?

**Check:**
```bash
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic | jq '.entry_links'
```

- **with_live_link > 0**: ✅ Yes, entry links have live_link populated
- **without_live_link > 0**: ❌ Entry links exist but live_link is NULL (API mapping issue)
- **total = 0**: ⚠️ No entry links created yet (may need to trigger auto-create)

## Troubleshooting

### Issue: surveys.total = 0 (No inventories)

**Possible Causes:**
1. No surveys available from Cint for your criteria (eng_us/gb/ca/au)
2. Webhooks arriving but failing to process
3. Not enough time passed (wait 5-10 minutes)

**Solutions:**
```bash
# 1. Check webhook subscription
curl https://torpedo.cogentixresearch.com/api/cint/subscription/opportunities

# 2. Test webhook manually
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities" \
  -H "Content-Type: application/json" \
  -d '[{"survey_id": 999999, "survey_name": "Test", "is_live": true}]'

# 3. Check server logs for errors
ssh user@torpedo.cogentixresearch.com 'tail -100 /var/log/torpedo/backend.log | grep -i error'

# 4. If still no surveys after 24 hours, contact Cint support
```

### Issue: Entry links without live_link (API mapping problem)

**Check debug logs for field names:**
```bash
ssh user@torpedo.cogentixresearch.com 'tail -f /var/log/torpedo/backend.log | grep "SupplierLink data keys"'
```

If you see `['LiveLink', 'TestLink']` (PascalCase), you need to update the model:

**File:** `backend/app/models/cint.py`
```python
from pydantic import Field

class SupplierLink(SupplierLinkBase):
    live_link: Optional[str] = Field(None, alias="LiveLink")
    test_link: Optional[str] = Field(None, alias="TestLink")

    class Config:
        populate_by_name = True
```

### Issue: Diagnostic endpoint returns 404

**Cause:** Service not restarted or files not copied correctly.

**Solution:**
```bash
ssh user@torpedo.cogentixresearch.com

# Check if file exists and is recent
ls -la /path/to/backend/app/routers/cint.py

# Force restart
sudo systemctl stop torpedo-backend
sleep 2
sudo systemctl start torpedo-backend

# Check service status
sudo systemctl status torpedo-backend
```

## Contact Cint Support

If still no surveys after 24 hours:

**Email:**
- sheik.sikkander@cint.com
- sushmita.sen@cint.com

**Include:**
1. Your supplier code: **6777**
2. Diagnostic output: `curl https://torpedo.cogentixresearch.com/api/cint/diagnostic`
3. Webhook subscription status
4. Question: "Are surveys available for eng_us/gb/ca/au?"

## Documentation Files

After deployment, these files are available on the VM at `${VM_PATH}/docs/`:

- **CINT_STATUS_REPORT.md** - Current status analysis
- **CINT_DIAGNOSTIC_GUIDE.md** - Detailed troubleshooting steps
- **CINT_INTEGRATION_COMPLETE.md** - Full integration documentation
- **CINT_INTEGRATION_FIXES.md** - Details of all fixes applied
- **DEPLOYMENT_CHECKLIST.md** - Manual deployment steps

## Next Steps

1. **Deploy the fixes** using one of the methods above
2. **Run verification script** to check if deployment succeeded
3. **Wait 5-10 minutes** for webhooks to arrive
4. **Check diagnostic output** to answer the two key questions
5. **Monitor logs** for 24 hours
6. **Contact Cint support** if still no surveys

---

**Questions?** Refer to the comprehensive guides in the docs folder or check server logs for detailed error messages.
