# Cint Integration - Deployment Checklist

## Files to Deploy

### Modified Files (Copy to Production):
```
backend/app/routers/cint.py                    # Added diagnostic endpoint + fixes
backend/app/services/cint_service.py           # Added entry link debug logging
backend/app/integrations/cint_integration.py   # Already up to date
backend/main.py                                 # Already up to date
```

### New Documentation Files (Reference Only):
```
CINT_STATUS_REPORT.md          # Current status analysis
CINT_DIAGNOSTIC_GUIDE.md       # Troubleshooting guide
CINT_INTEGRATION_COMPLETE.md   # Full integration docs
CINT_INTEGRATION_FIXES.md      # Details of fixes
.env.lucid.example             # Environment variable template
```

---

## Deployment Steps

### Option A: Git Deployment (Recommended)

```bash
# On your local machine
cd "d:\Code\03. Projects\01. torpedo wip\01. Torpedo v1 (python reacy)\campaign_platform-main\campaign_platform-main"

# Commit changes
git add backend/app/routers/cint.py
git add backend/app/services/cint_service.py
git add CINT_*.md
git commit -m "Fix: Cint integration webhook error handling and add diagnostics

- Fix webhook endpoint to return HTTP 500 on errors (not 200)
- Fix entry link 404 error detection
- Add survey activity check before entry link creation
- Add /api/cint/diagnostic endpoint for troubleshooting
- Add enhanced logging for entry link API responses

Resolves issues from Cint support correspondence"

# Push to repository
git push origin main

# SSH into production server
ssh user@torpedo.cogentixresearch.com

# Pull latest changes
cd /path/to/torpedo/backend
git pull origin main

# Restart service (choose method based on your setup)
sudo systemctl restart torpedo-backend
# OR
supervisorctl restart torpedo
# OR
docker-compose restart backend
```

---

### Option B: Manual File Copy

```bash
# Copy modified files to production
scp "d:\Code\03. Projects\01. torpedo wip\01. Torpedo v1 (python reacy)\campaign_platform-main\campaign_platform-main\backend\app\routers\cint.py" user@torpedo.cogentixresearch.com:/path/to/backend/app/routers/

scp "d:\Code\03. Projects\01. torpedo wip\01. Torpedo v1 (python reacy)\campaign_platform-main\campaign_platform-main\backend\app\services\cint_service.py" user@torpedo.cogentixresearch.com:/path/to/backend/app/services/

# SSH and restart
ssh user@torpedo.cogentixresearch.com
sudo systemctl restart torpedo-backend
```

---

## Post-Deployment Verification

### 1. Check Server Started Successfully
```bash
# Check service status
sudo systemctl status torpedo-backend

# OR
tail -f /var/log/torpedo/backend.log
```

**Look for:**
```
✅ Cint integration active (Supplier Code: 6777)
INFO:     Application startup complete
```

---

### 2. Test Diagnostic Endpoint
```bash
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic
```

**Expected:** JSON response with surveys/entry_links data, NOT 404

---

### 3. Monitor Webhook Activity
```bash
# Watch for incoming webhooks (every 15 seconds)
tail -f /var/log/torpedo/backend.log | grep "Received opportunities webhook"
```

**Expected:** Messages appearing every 15 seconds if Cint is sending surveys

---

### 4. Check Entry Link Debug Logs
```bash
tail -f /var/log/torpedo/backend.log | grep "ENTRY LINK DEBUG"
```

**Expected:** Logs showing API response structure when entry links are created

---

## Troubleshooting Deployment

### Issue: Server Won't Start

**Check:**
```bash
# View full error log
journalctl -u torpedo-backend -n 50

# OR
tail -100 /var/log/torpedo/backend.log
```

**Common Causes:**
- Syntax error in modified files
- Missing dependencies
- MongoDB connection failure

---

### Issue: Diagnostic Still Returns 404

**Causes:**
1. Files not copied to correct location
2. Service not restarted
3. Code not reloaded (if using --reload flag)

**Solution:**
```bash
# Verify file exists
ls -la /path/to/backend/app/routers/cint.py

# Check modification time (should be recent)
stat /path/to/backend/app/routers/cint.py

# Force restart
sudo systemctl stop torpedo-backend
sleep 2
sudo systemctl start torpedo-backend
```

---

### Issue: No Webhook Activity in Logs

**Check:**
1. Is webhook subscription still active?
```bash
curl https://torpedo.cogentixresearch.com/api/cint/subscription/opportunities
```

2. Test webhook manually:
```bash
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities" \
  -H "Content-Type: application/json" \
  -d '[{"survey_id": 99999, "survey_name": "Test", "is_live": true}]'
```

3. Check firewall/proxy settings - ensure Cint can reach your server

---

## Quick Reference Commands

```bash
# Deploy and restart (full sequence)
cd /path/to/backend
git pull
sudo systemctl restart torpedo-backend

# Verify deployment
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic | jq

# Monitor logs
tail -f /var/log/torpedo/backend.log

# Check webhook subscription
curl https://torpedo.cogentixresearch.com/api/cint/subscription/opportunities | jq

# Manual entry link creation test
curl -X POST "https://torpedo.cogentixresearch.com/api/cint/auto-create-entry-links?limit=10"
```

---

## Expected Timeline

| Time | Activity |
|------|----------|
| T+0 | Deploy code and restart server |
| T+1min | Verify diagnostic endpoint works |
| T+5min | Watch logs for webhook activity |
| T+15sec | First webhook should arrive (if surveys available) |
| T+1hour | Should have accumulated some surveys |
| T+24hours | Good sample size for analysis |

---

## Success Criteria

After deployment, you should see:

✅ Diagnostic endpoint returns data (not 404)
✅ Webhook logs appearing every 15 seconds
✅ Surveys accumulating in database
✅ Entry links being created automatically
✅ `[ENTRY LINK DEBUG]` logs showing API responses

---

## If Still No Surveys After 24 Hours

Contact Cint support with:
- Diagnostic output
- Log excerpt showing webhook reception (or lack thereof)
- Question about survey availability for your criteria

**Email:** sheik.sikkander@cint.com, sushmita.sen@cint.com
**Subject:** Cogentix Research (6777) - No Surveys in Webhook Feed

---

## Need Help?

Refer to:
- **CINT_STATUS_REPORT.md** - Current status analysis
- **CINT_DIAGNOSTIC_GUIDE.md** - Detailed troubleshooting
- **CINT_INTEGRATION_COMPLETE.md** - Full API reference
