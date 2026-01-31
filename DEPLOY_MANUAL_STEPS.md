# CPX Logging Fix - Manual Deployment Guide

## Quick Start

If you prefer to deploy manually instead of using the scripts:

### Step 1: Connect to Production VM

```powershell
# From your development machine (Windows)
ssh campaign_admin@<vm-ip-or-hostname>
```

Replace `<vm-ip-or-hostname>` with your production VM's IP or hostname.

### Step 2: Backup Current Version

```bash
# On the production VM
cd /home/campaign_admin/campaign_backend

# Create backup
mkdir -p backups
cp backend/main.py backups/main.py.backup.$(date +%Y%m%d_%H%M%S)
echo "✅ Backup created at: backups/main.py.backup.*"
```

### Step 3: Copy Fixed File

**Option A: Using SCP from Windows**

```powershell
# From your development machine
$vm = "campaign_admin@<vm-ip>"
scp "backend\main.py" "$vm`:/home/campaign_admin/campaign_backend/backend/main.py"
```

**Option B: Manual Edit on VM**

```bash
# On the production VM
nano backend/main.py
# (Copy-paste the fixed content from the local file)
```

### Step 4: Verify Syntax

```bash
# On the production VM
cd /home/campaign_admin/campaign_backend
python3 -m py_compile backend/main.py

# Should output nothing if successful, or show error if syntax issue
```

### Step 5: Restart Backend Service

```bash
# On the production VM
sudo systemctl restart campaign_backend

# Wait a moment for restart
sleep 3

# Verify it's running
sudo systemctl status campaign_backend

# Should show "active (running)"
```

### Step 6: Check Startup Logs

```bash
# View recent logs
sudo journalctl -u campaign_backend -n 30

# Should see these messages:
# ✅ Vendors collection injected into traffic router
# ✅ CPX callback logs collection initialized
# ✅ CPX postback logs injected into traffic router for S2S verification
# ✅ Traffic router included
```

### Step 7: Verify Fix

**Test the endpoint:**
```bash
# From VM or any machine that can reach the backend
curl "http://<vm-ip>:8000/cpx-response?msg=test&sfwid=TEST123"
```

**Check database for logs:**
```bash
# On the production VM (MongoDB must be accessible)
mongo traffic_flow_db

# Inside MongoDB shell:
db.cpx_callback_logs.countDocuments()    # Should show some count
db.cpx_postback_logs.countDocuments()     # Compare with before
```

---

## Detailed Step-by-Step

### Full Example Walkthrough

```bash
# 1. SSH into production VM
ssh campaign_admin@192.168.1.100

# 2. Navigate to project directory
cd /home/campaign_admin/campaign_backend

# 3. Create backup
mkdir -p backups
BACKUP_FILE="backups/main.py.backup.$(date +%Y%m%d_%H%M%S)"
cp backend/main.py "$BACKUP_FILE"
echo "Backup saved to: $BACKUP_FILE"

# 4. Copy the new file (paste content from the fixed main.py)
# Option: Use nano to manually edit
nano backend/main.py
# Ctrl+X to exit, Y to save

# Or paste directly from Windows:
# (This requires having the file contents ready)

# 5. Verify syntax
python3 -m py_compile backend/main.py
echo "Syntax check: $?"  # Should return 0

# 6. Check current status
sudo systemctl status campaign_backend

# 7. Restart
sudo systemctl restart campaign_backend
sleep 3

# 8. Verify restart
sudo systemctl status campaign_backend

# 9. Check logs
sudo journalctl -u campaign_backend -n 50 --no-pager | grep -i "cpx\|router"

# 10. Test the endpoint
curl -v "http://localhost:8000/cpx-response?msg=test&sfwid=TEST123" 2>&1 | head -20

# 11. Check database
mongo traffic_flow_db --eval "
  print('CPX Postback Logs: ' + db.cpx_postback_logs.countDocuments());
  print('CPX Callback Logs: ' + db.cpx_callback_logs.countDocuments());
"
```

---

## Rollback Instructions

If something goes wrong, rollback is simple:

```bash
# 1. SSH to production VM
ssh campaign_admin@<vm-ip>

# 2. List backups
ls -la /home/campaign_admin/campaign_backend/backups/

# 3. Restore from backup
BACKUP_FILE="/home/campaign_admin/campaign_backend/backups/main.py.backup.20260131_145230"
cp "$BACKUP_FILE" /home/campaign_admin/campaign_backend/backend/main.py

# 4. Verify syntax
cd /home/campaign_admin/campaign_backend
python3 -m py_compile backend/main.py

# 5. Restart
sudo systemctl restart campaign_backend
sleep 3

# 6. Verify
sudo systemctl status campaign_backend
echo "Rollback complete"
```

---

## Troubleshooting

### Service won't start

**Check the logs:**
```bash
sudo journalctl -u campaign_backend -n 100 --no-pager | tail -50
```

**Common issues:**
- Syntax error (check with `python3 -m py_compile backend/main.py`)
- MongoDB connection issue (verify MongoDB is running)
- Missing dependencies (check imports at top of main.py)

### No logs being recorded

**Check collection initialization:**
```bash
# On production VM
mongo traffic_flow_db

# Inside MongoDB shell:
show collections                          # Should see cpx_callback_logs
db.cpx_callback_logs.find().pretty()      # Should show recent entries
db.cpx_postback_logs.find().pretty()      # Compare
```

**Check if endpoint is being called:**
```bash
# Monitor logs while making a request
sudo journalctl -u campaign_backend -f &

# In another terminal:
curl "http://localhost:8000/cpx-response?msg=test&sfwid=SFWID123"

# Should see log messages like:
# 📥 CPX Callback received
# 📝 Logged CPX callback
```

### Connection refused

**Verify backend is running:**
```bash
sudo systemctl status campaign_backend

# If not running:
sudo systemctl restart campaign_backend
sleep 5
sudo systemctl status campaign_backend
```

**Check port:**
```bash
netstat -tulpn | grep 8000
# Should show listening on port 8000
```

---

## Verification Checklist

- [ ] SSH connection to VM works
- [ ] Backup created successfully
- [ ] New main.py copied to VM
- [ ] Python syntax validation passes
- [ ] Backend service restarted without errors
- [ ] Startup logs show CPX collections injected
- [ ] `/cpx-response` endpoint responds to requests
- [ ] `cpx_callback_logs` collection exists in MongoDB
- [ ] New test request appears in logs
- [ ] Database shows entries in both postback and callback collections

---

## Support

The fix has been validated with full syntax checking and code path analysis. It's production-ready.
