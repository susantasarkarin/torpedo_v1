# Git-Based Deployment Guide

If SSH port 22 is not accessible, you can deploy via Git push + pull on the VM.

## Step 1: Commit Changes Locally
```bash
cd "d:\Code\03. Projects\01. torpedo wip\01. Torpedo v1 (python reacy)\campaign_platform-main\campaign_platform-main"

git add backend/app/routers/cint.py backend/app/services/cint_service.py
git commit -m "Fix: Cint integration webhook error handling and diagnostics

- Fixed webhook error handling to return HTTP 500 for retry logic
- Fixed entry link 404 detection with result.get('success') check
- Added is_live filter for auto-create entry links
- Added comprehensive diagnostic endpoint
- Enhanced logging for entry link debugging"

git push origin main
```

## Step 2: Login to VM via Console/RDP/Alternative Access
If you have console access, RDP, or another way to access the VM:

1. SSH to VM using alternative method (console, web SSH, etc.)
2. Run these commands on the VM:

```bash
cd /var/www/torpedo/backend

# Create backup
BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p $BACKUP_DIR/app/routers $BACKUP_DIR/app/services
[ -f app/routers/cint.py ] && cp app/routers/cint.py $BACKUP_DIR/app/routers/
[ -f app/services/cint_service.py ] && cp app/services/cint_service.py $BACKUP_DIR/app/services/

# Pull latest changes
git pull origin main

# Restart service
sudo systemctl restart torpedo-backend

# Verify deployment
sleep 5
curl http://localhost:8000/api/cint/diagnostic
```

## Step 3: Verify from Your Machine
```bash
curl https://torpedo.cogentixresearch.com/api/cint/diagnostic
```

## Option 3: Manual File Upload
If you have access to a file manager (FTP, SFTP GUI, cloud storage):

1. Upload these files to the VM:
   - `backend/app/routers/cint.py` → `/var/www/torpedo/backend/app/routers/cint.py`
   - `backend/app/services/cint_service.py` → `/var/www/torpedo/backend/app/services/cint_service.py`

2. Restart the backend service via web panel or console

## Troubleshooting SSH Access

Check which port SSH is running on:
```bash
curl -v https://torpedo.cogentixresearch.com 2>&1 | grep -i ssh
```

Or check if SSH is on a different port:
```bash
ssh -p 2222 root@torpedo.cogentixresearch.com
```

Common alternate SSH ports: 2222, 2200, 22000
