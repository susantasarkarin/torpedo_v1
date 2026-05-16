# LinkedIn Automation - Quick Deployment

Deploy LinkedIn automation to your Torpedo VM in 5 minutes.

## VM Details
- **Host**: 139.59.32.72
- **User**: root
- **Path**: /var/www/torpedo

## Step 1: Run Deployment Script

### On Windows (PowerShell):
```powershell
cd .\deploy\scripts
.\deploy_linkedin_automation.ps1 -VMHost "139.59.32.72" -VMUser "root"
```

### On Linux/Mac:
```bash
chmod +x deploy/scripts/deploy_linkedin_automation.sh
./deploy/scripts/deploy_linkedin_automation.sh --host 139.59.32.72 --user root
```

## Step 2: Configure Environment

SSH to your VM:
```bash
ssh root@139.59.32.72
```

Generate encryption key:
```bash
python3 << 'EOF'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
EOF
```

Edit environment file:
```bash
sudo nano /etc/torpedo/linkedin-automation.env
```

Paste this and update with values from above:
```
LINKEDIN_ENCRYPTION_KEY=YOUR_KEY_HERE
CHROMEDRIVER_PATH=/usr/bin/chromedriver
LINKEDIN_BROWSER_HEADLESS=true
MONGODB_URI=mongodb://root:PASSWORD@localhost:27017/torpedo?authSource=admin
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
LINKEDIN_SCHEDULER_ENABLED=true
```

Save: `Ctrl+X`, `Y`, `Enter`

## Step 3: Start Services

```bash
# Copy systemd files
sudo cp /var/www/torpedo/vm_config/systemd/*.service /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/torpedo-linkedin-*.service
sudo systemctl daemon-reload

# Start services
sudo systemctl enable torpedo-linkedin-beat.service --now
sudo systemctl enable torpedo-linkedin-worker.service --now

# Verify
sudo systemctl status torpedo-linkedin-beat
sudo systemctl status torpedo-linkedin-worker
```

## Step 4: Add LinkedIn Account

From your local machine:
```bash
curl -X POST http://139.59.32.72:8000/api/marketing/linkedin/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your_account@linkedin.com",
    "password": "your_password",
    "account_name": "Account 1",
    "active": true,
    "schedule": {
      "frequency": "daily",
      "run_time": "02:00",
      "enabled": true
    }
  }'
```

## Step 5: Verify It Works

### Check service logs:
```bash
ssh root@139.59.32.72
sudo journalctl -u torpedo-linkedin-beat -f  # Monitor scheduler
sudo journalctl -u torpedo-linkedin-worker -f  # Monitor automation
```

### Check job status:
```bash
curl http://139.59.32.72:8000/api/marketing/linkedin/accounts
```

## Done! ✅

Your LinkedIn automation is now running on the VM and will execute daily at the configured time (default: 02:00 UTC).

### What Happens Daily:
1. **02:00 UTC**: Celery Beat triggers `run_daily_linkedin_automation()`
2. For each enabled account:
   - Browser launches (headless)
   - Logs into LinkedIn
   - Likes posts
   - Reposts
   - Comments
   - Results saved to MongoDB
3. Job history viewable via API

### Monitoring:
```bash
# View recent jobs
curl http://139.59.32.72:8000/api/marketing/linkedin/accounts/{account_id}/jobs

# View specific job
curl http://139.59.32.72:8000/api/marketing/linkedin/jobs/{job_id}

# View dashboard
curl http://139.59.32.72:8000/api/marketing/linkedin/dashboard
```

### Troubleshooting:
```bash
# Check services
sudo systemctl status torpedo-linkedin-*

# View logs
sudo journalctl -u torpedo-linkedin-beat -n 50
sudo journalctl -u torpedo-linkedin-worker -n 50

# Test connectivity
redis-cli ping  # Should respond: PONG
mongosh "mongodb://root:PASSWORD@localhost:27017/linkedin_db?authSource=admin"
```

For detailed guide, see: `LINKEDIN_AUTOMATION_DEPLOYMENT.md`
