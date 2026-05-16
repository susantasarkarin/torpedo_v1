# LinkedIn Automation Deployment Guide

**Last Updated**: March 3, 2026  
**Module**: Marketing - LinkedIn Automation  
**Version**: 1.0

## 📋 Overview

This guide covers deploying the LinkedIn Automation module to your Torpedo VM.

For your setup:
- **VM Host**: 139.59.32.72
- **SSH User**: root
- **VM Path**: /var/www/torpedo
- **Deployment Type**: Systemd Services (recommended) or Docker

## 🚀 Quick Start

### Option 1: PowerShell (Windows)

```powershell
.\deploy\scripts\deploy_linkedin_automation.ps1 `
    -VMHost "139.59.32.72" `
    -VMUser "root"
```

### Option 2: Bash (Linux/Mac)

```bash
chmod +x deploy/scripts/deploy_linkedin_automation.sh
./deploy/scripts/deploy_linkedin_automation.sh \
    --host 139.59.32.72 \
    --user root
```

## 📦 What Gets Deployed

### Core Files
```
backend/linkedin_automation/
  ├── __init__.py           # Module exports
  ├── models.py             # Pydantic schemas
  ├── service.py            # Business logic & encryption
  ├── job.py                # Selenium bot implementation
  ├── router.py             # FastAPI endpoints
  ├── jobs_queue.py         # Job queuing utility
  └── database.py           # MongoDB setup & indexes

backend/tasks/
  └── linkedin_tasks.py     # Celery tasks & beat schedule

backend/
  ├── celery_app.py         # Updated with LinkedIn queue
  └── main.py               # Updated with router import
```

### Configuration Files
```
vm_config/
  ├── linux-automation.env.example  # Environment template
  └── systemd/
      ├── torpedo-linkedin-beat.service    # Celery scheduler
      └── torpedo-linkedin-worker.service  # Celery worker
```

## ⚙️ Configuration

### 1. Generate Encryption Key

SSH to your VM and generate a Fernet encryption key:

```bash
ssh root@139.59.32.72

# In the VM
python3 << 'EOF'
from cryptography.fernet import Fernet
key = Fernet.generate_key()
print(f"LINKEDIN_ENCRYPTION_KEY={key.decode()}")
EOF
```

Save the output for use in the next step.

### 2. Create Environment File

```bash
# On VM
sudo nano /etc/torpedo/linkedin-automation.env
```

Example content:

```bash
# LinkedIn Encryption
LINKEDIN_ENCRYPTION_KEY=your-key-from-step-1

# Selenium Configuration
CHROMEDRIVER_PATH=/usr/bin/chromedriver
LINKEDIN_BROWSER_HEADLESS=true
LINKEDIN_BROWSER_TIMEOUT=20

# Automation Limits
LINKEDIN_MAX_CONNECTIONS=10
LINKEDIN_MAX_MESSAGES=5
LINKEDIN_MAX_POSTS=100

# Scheduler
LINKEDIN_RUN_TIME=02:00
LINKEDIN_SCHEDULER_ENABLED=true

# Database (from main Torpedo config)
MONGODB_URI=mongodb://root:PASSWORD@localhost:27017/torpedo?authSource=admin
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

Set permissions:

```bash
# On VM
sudo chmod 600 /etc/torpedo/linkedin-automation.env
```

### 3. Copy systemd Service Files

```bash
# On VM (after deployment script)
sudo cp /var/www/torpedo/vm_config/systemd/*.service /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/torpedo-linkedin-*.service
sudo systemctl daemon-reload
```

## 🔧 Service Management

### Enable Services

```bash
# Start on boot
sudo systemctl enable torpedo-linkedin-beat.service
sudo systemctl enable torpedo-linkedin-worker.service

# Start immediately
sudo systemctl start torpedo-linkedin-beat.service
sudo systemctl start torpedo-linkedin-worker.service
```

### Monitor Services

```bash
# View status
sudo systemctl status torpedo-linkedin-beat
sudo systemctl status torpedo-linkedin-worker

# Follow logs
sudo journalctl -u torpedo-linkedin-beat -f
sudo journalctl -u torpedo-linkedin-worker -f

# Check both services
sudo systemctl list-units torpedo-linkedin-*
```

### Stop Services

```bash
sudo systemctl stop torpedo-linkedin-beat.service
sudo systemctl stop torpedo-linkedin-worker.service
```

### Restart Services

```bash
sudo systemctl restart torpedo-linkedin-beat.service
sudo systemctl restart torpedo-linkedin-worker.service
```

## 🐳 Docker Deployment (Alternative)

If you're using Docker:

### Update docker-compose.yml

Add to your existing docker-compose: configuration:

```yaml
  celery-linkedin-beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: torpedo-linkedin-beat
    environment:
      - LINKEDIN_ENCRYPTION_KEY=${LINKEDIN_ENCRYPTION_KEY}
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/1
      - MONGODB_URI=mongodb://root:PASSWORD@mongodb:27017/torpedo?authSource=admin
    volumes:
      - ./backend:/app
    depends_on:
      - redis
      - mongodb
    command: celery -A backend.celery_app beat --loglevel=info
    networks:
      - torpedo-network

  celery-linkedin-worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: torpedo-linkedin-worker
    environment:
      - LINKEDIN_ENCRYPTION_KEY=${LINKEDIN_ENCRYPTION_KEY}
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/1
      - MONGODB_URI=mongodb://root:PASSWORD@mongodb:27017/torpedo?authSource=admin
    volumes:
      - ./backend:/app
    depends_on:
      - redis
      - mongodb
    command: celery -A backend.celery_app worker -Q linkedin_automation --loglevel=info --concurrency=2
    networks:
      - torpedo-network
```

### Start Docker Services

```bash
cd /var/www/torpedo

# Set environment
export LINKEDIN_ENCRYPTION_KEY="your-key-here"

# Start services
docker-compose up -d celery-linkedin-beat celery-linkedin-worker

# Check logs
docker-compose logs -f celery-linkedin-beat
docker-compose logs -f celery-linkedin-worker
```

## 📱 Using the API

### Create a LinkedIn Account

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
      "days_of_week": null,
      "enabled": true
    }
  }'
```

### List Accounts

```bash
curl http://139.59.32.72:8000/api/marketing/linkedin/accounts
```

### Trigger Manual Automation

```bash
curl -X POST http://139.59.32.72:8000/api/marketing/linkedin/accounts/{account_id}/run
```

### Get Job History

```bash
curl http://139.59.32.72:8000/api/marketing/linkedin/accounts/{account_id}/jobs?limit=50
```

## 🔍 Troubleshooting

### Services Not Starting

```bash
# Check detailed error
sudo journalctl -u torpedo-linkedin-beat -n 50

# Verify environment file
sudo cat /etc/torpedo/linkedin-automation.env

# Check file permissions
su -l www-data -s /bin/bash
cd /var/www/torpedo/backend
python3 -c "from linkedin_automation import LinkedInService; print('✓ Import successful')"
```

### Selenium/Chrome Issues

```bash
# Install Chrome (if not installed)
sudo apt-get update
sudo apt-get install -y chromium-browser

# Install ChromeDriver
sudo apt-get install -y chromium-chromedriver
# Or download from: https://chromedriver.chromium.org/

# Verify installation
which chromium-browser
which chromedriver
```

### Redis Connection Issues

```bash
# Check Redis is running
redis-cli ping
# Should return: PONG

# Check connections
redis-cli info clients
```

### MongoDB Connection Issues

```bash
# Check MongoDB is running
sudo systemctl status mongodb

# Test connection
mongosh "mongodb://root:PASSWORD@localhost:27017/linkedin_db?authSource=admin"
```

## 📊 Monitoring

### View Celery Tasks

```bash
# Real-time monitoring (if Flower is running)
# Navigate to: http://139.59.32.72:5555

# Command line monitoring
celery -A backend.celery_app inspect active

# Check task stats
celery -A backend.celery_app inspect stats
```

### Job Logs in MongoDB

```bash
# Connect to MongoDB
mongosh "mongodb://root:PASSWORD@localhost:27017/linkedin_db?authSource=admin"

# View recent jobs
db.automation_jobs.find().sort({started_at: -1}).limit(10)

# View failed jobs
db.automation_jobs.find({status: "failed"})

# Count jobs by status
db.automation_jobs.aggregate([
  {$group: {_id: "$status", count: {$sum: 1}}}
])
```

## 🆘 Recovery

### Backup Before Changes

```bash
# On VM
cd /var/www/torpedo
tar -czf backups/linkedin-pre-change-$(date +%s).tar.gz backend/linkedin_automation/
```

### Restore from Backup

```bash
# Located in /var/www/torpedo/backups/
cd /var/www/torpedo
tar -xzf backups/linkedin-BACKUP_NAME.tar.gz
```

### Restart All Services

```bash
# Full restart
sudo systemctl restart torpedo-linkedin-beat torpedo-linkedin-worker

# Then verify
sudo systemctl status torpedo-linkedin-*
```

## 📝 Logs Location

| Component | Log Location |
|-----------|-------------|
| Celery Beat | `journalctl -u torpedo-linkedin-beat` |
| Celery Worker | `journalctl -u torpedo-linkedin-worker` |
| Application | `/var/www/torpedo/logs/` |
| Systemd | `/var/log/syslog` |

## 🔐 Security Notes

1. **Encryption Key**: Keep your `LINKEDIN_ENCRYPTION_KEY` secure
   - Store only in `/etc/torpedo/linkedin-automation.env`
   - Never commit to git
   - Restrict file permissions to 600

2. **Database Credentials**
   - Use environment variables, never hardcode
   - Rotate passwords periodically

3. **Selenium/Chrome**
   - Run in headless mode (default)
   - Runs as `www-data` user with limited privileges
   - Limited to 2 concurrent instances (avoids resource contention)

## ✅ Deployment Checklist

- [ ] SSH access to VM verified
- [ ] Environment file created: `/etc/torpedo/linkedin-automation.env`
- [ ] Encryption key generated and saved
- [ ] Files deployed to `/var/www/torpedo/`
- [ ] Systemd services installed
- [ ] MongoDB and Redis running
- [ ] Services enabled and started
- [ ] First LinkedIn account added via API
- [ ] Logs showing no errors
- [ ] Manual run triggered and succeeded
- [ ] Daily scheduler verified in Celery logs

## 📞 Support

For issues or questions:
1. Check logs: `sudo journalctl -u torpedo-linkedin-* -n 100`
2. Verify configuration: `cat /etc/torpedo/linkedin-automation.env`
3. Test API: `curl http://139.59.32.72:8000/health`
4. Check service status: `sudo systemctl status torpedo-linkedin-*`
