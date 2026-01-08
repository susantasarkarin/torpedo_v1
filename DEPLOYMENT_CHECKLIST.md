# 🚀 Production Deployment Checklist - GCP VM (34.41.181.74)

**Deployment Date**: January 8, 2026  
**Git Commit**: 6e41ae5 (Complete Cint API integration)  
**Target**: surveyieldwork.com (34.41.181.74)

---

## Pre-Deployment (Local) ✅

- [x] All code committed to GitHub
- [x] Deployment guide created (DEPLOYMENT.md)
- [x] Environment variables documented
- [x] Cint credentials verified
- [x] Webhook secret verified
- [x] Backend tested locally
- [x] Entry link CRUD endpoints implemented
- [x] Webhook signature validation implemented
- [x] MongoDB collections schema created
- [x] Dependency injection wired

---

## SSH & Access Setup

**Required**: SSH access to GCP VM  
**User**: susanta  
**Host**: 34.41.181.74  
**Port**: 22

### Connection Test
```bash
# Run on your local machine
ssh susanta@34.41.181.74 "echo 'SSH Access OK'"
```

**Status**: ☐ SSH Access Verified

---

## GCP VM Prerequisites

### System Packages
- [ ] Python 3.8+ installed
  ```bash
  ssh susanta@34.41.181.74 "python3 --version"
  ```

- [ ] Git installed
  ```bash
  ssh susanta@34.41.181.74 "git --version"
  ```

- [ ] MongoDB running (or URI available)
  ```bash
  ssh susanta@34.41.181.74 "mongod --version"
  ```

- [ ] npm/Node.js installed (for PM2)
  ```bash
  ssh susanta@34.41.181.74 "npm --version || echo 'Install npm'"
  ```

---

## Step-by-Step Deployment

### Phase 1: Clone/Update Code
- [ ] SSH into VM
- [ ] Navigate to project directory
  ```bash
  cd /home/susanta/campaign_platform
  ```
- [ ] Clone or pull latest code
  ```bash
  git clone https://github.com/sristi3227/campaign_platform.git . || git pull origin main
  cd backend
  ```

**Checkpoint 1**: Code updated to commit 6e41ae5

---

### Phase 2: Dependencies
- [ ] Install Python packages
  ```bash
  pip install -r requirements.txt
  ```
- [ ] Verify critical packages
  ```bash
  python3 -c "import fastapi, httpx, pymongo, pydantic; print('✅ All dependencies installed')"
  ```

**Checkpoint 2**: All dependencies installed

---

### Phase 3: Environment Configuration
- [ ] Create/update `.env` file in backend directory
  ```bash
  cat > .env << 'EOF'
MONGO_URI=mongodb://localhost:27017/
CINT_API_KEY=C61C48A6-8154-4F9F-B616-8DFB66F452A7
CINT_SUPPLIER_CODE=6777
CINT_ENVIRONMENT=sandbox
CINT_WEBHOOK_SECRET=M7jTY9DGoXEC3AG8tAJ289l57U6e9hpT2q5xN7n88UbpiYInITVU35MHTFRB8520syiC4WQA7oS2LN90PRuD7
API_BASE=https://surveyieldwork.com
CORS_ORIGINS=https://surveyieldwork.com,https://www.surveyieldwork.com,http://34.41.181.74
EOF
  ```

**Checkpoint 3**: Environment variables configured

---

### Phase 4: Start Backend with PM2
- [ ] Install PM2 globally (if not already installed)
  ```bash
  sudo apt-get update && sudo apt-get install npm -y
  npm install -g pm2
  ```

- [ ] Stop existing backend process (if running)
  ```bash
  pm2 stop campaign-backend || true
  ```

- [ ] Start backend with PM2
  ```bash
  pm2 start "python3 -m uvicorn main:app --host 0.0.0.0 --port 8000" --name "campaign-backend"
  ```

- [ ] Save PM2 configuration
  ```bash
  pm2 save
  pm2 startup
  ```

- [ ] Enable auto-restart on reboot
  ```bash
  sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u susanta --hp /home/susanta
  ```

- [ ] Verify backend is running
  ```bash
  pm2 status
  pm2 logs campaign-backend
  ```

**Checkpoint 4**: Backend running on port 8000

---

### Phase 5: Nginx Configuration
- [ ] Install Nginx (if not already installed)
  ```bash
  sudo apt-get install nginx -y
  ```

- [ ] Create Nginx config file
  ```bash
  sudo bash -c 'cat > /etc/nginx/sites-available/campaign-api << "EOF"
server {
    listen 80;
    server_name surveyieldwork.com www.surveyieldwork.com 34.41.181.74;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_connect_timeout 60s;
    }
}
EOF'
  ```

- [ ] Enable Nginx site
  ```bash
  sudo ln -s /etc/nginx/sites-available/campaign-api /etc/nginx/sites-enabled/ || true
  ```

- [ ] Test Nginx config
  ```bash
  sudo nginx -t
  ```

- [ ] Start Nginx
  ```bash
  sudo systemctl start nginx
  sudo systemctl enable nginx
  ```

**Checkpoint 5**: Nginx reverse proxy configured and running

---

### Phase 6: DNS Configuration
- [ ] Update DNS record for surveyieldwork.com
  - **Type**: A Record
  - **Value**: 34.41.181.74
  - **TTL**: 3600 (or lower for faster propagation)

- [ ] Test DNS resolution
  ```bash
  nslookup surveyieldwork.com
  # Should return 34.41.181.74
  ```

**Checkpoint 6**: DNS pointing to GCP VM (wait 5-15 minutes for propagation)

---

## Post-Deployment Verification

### Test 1: Health Check
```bash
curl http://34.41.181.74/health
# Expected: {"status": "healthy", ...}

curl http://surveyieldwork.com/health
# Expected: Same response (after DNS propagates)
```
- [ ] Health check passes

### Test 2: Cint Endpoints
```bash
curl http://34.41.181.74/api/cint/health
# Expected: {"status": "healthy", "supplier_code": "6777", ...}

curl http://34.41.181.74/api/cint/opportunities
# Expected: {"success": true, "opportunities": [...]}
```
- [ ] Cint endpoints accessible

### Test 3: API Documentation
```bash
# Visit in browser:
http://34.41.181.74/docs
# or
https://surveyieldwork.com/docs
```
- [ ] Swagger documentation accessible

### Test 4: MongoDB Verification
```bash
# On GCP VM:
mongo
> use campaign_platform
> db.cint_surveys.count()
> db.cint_entry_links.count()
# Should show collections created
```
- [ ] MongoDB collections initialized

### Test 5: Webhook Validation (Optional)
```bash
# Create test webhook with signature
WEBHOOK_SECRET="M7jTY9DGoXEC3AG8tAJ289l57U6e9hpT2q5xN7n88UbpiYInITVU35MHTFRB8520syiC4WQA7oS2LN90PRuD7"
BODY='{"survey_id": 123}'

# Compute signature (on Linux/Mac):
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -hex | cut -d' ' -f2)

curl -X POST http://34.41.181.74/api/cint/webhooks/opportunities \
  -H "Content-Type: application/json" \
  -H "X-Cint-Signature: $SIG" \
  -d "$BODY"

# Expected: {"success": true, "message": "Opportunities processed", "count": 1}
```
- [ ] Webhook signature validation works

---

## Cint Dashboard Configuration

### Step 1: Log into Cint Dashboard
- URL: https://partners.cint.com (or your sandbox environment)
- Username: (provided by Cint)
- Password: (provided by Cint)

### Step 2: Configure Webhook
- [ ] Navigate to: Settings → Webhooks or Integration
- [ ] Add new webhook:
  - **Event**: Opportunities
  - **URL**: `https://surveyieldwork.com/api/cint/webhooks/opportunities`
  - **Secret**: `M7jTY9DGoXEC3AG8tAJ289l57U6e9hpT2q5xN7n88UbpiYInITVU35MHTFRB8520syiC4WQA7oS2LN90PRuD7`
  - **Frequency**: 15 seconds (or preferred)

### Step 3: Test Webhook
- [ ] Send test webhook from Cint dashboard
- [ ] Check backend logs:
  ```bash
  pm2 logs campaign-backend
  ```
- [ ] Should see 200 OK response

---

## SSL/HTTPS Setup (Recommended)

### Option A: Let's Encrypt (Free)
```bash
# Install Certbot
sudo apt-get install certbot python3-certbot-nginx -y

# Get certificate
sudo certbot certonly --standalone -d surveyieldwork.com -d www.surveyieldwork.com

# Update Nginx to use HTTPS
# (See DEPLOYMENT.md for full config)
```

### Option B: Use existing certificate
- [ ] Copy certificate files to /etc/nginx/ssl/
- [ ] Update Nginx config to reference cert paths

- [ ] Enable HTTPS in Nginx
- [ ] Test with: `curl https://surveyieldwork.com/health`

---

## Monitoring & Logs

### View Logs
```bash
pm2 logs campaign-backend --lines 100
```

### Monitor Status
```bash
pm2 status
pm2 monitor  # Real-time monitoring
```

### Restart if Needed
```bash
pm2 restart campaign-backend
```

---

## Success Criteria

- [x] Code committed to GitHub (commit 6e41ae5)
- [ ] SSH access to GCP VM working
- [ ] All dependencies installed on server
- [ ] Backend running with PM2
- [ ] Nginx reverse proxy operational
- [ ] DNS propagated to GCP IP
- [ ] Health endpoints responding (200 OK)
- [ ] Cint endpoints accessible
- [ ] API documentation available at /docs
- [ ] MongoDB collections created
- [ ] Webhook can receive data
- [ ] No errors in PM2 logs
- [ ] Cint webhook configured in dashboard

---

## Rollback Plan

If critical issues occur:

```bash
# Stop current version
pm2 stop campaign-backend

# Revert to previous commit
git reset --hard HEAD~1
git push origin main --force

# Reinstall dependencies
pip install -r requirements.txt

# Restart
pm2 start campaign-backend
```

---

## Support & Troubleshooting

### Backend Not Starting
```bash
pm2 logs campaign-backend
# Check for: Missing dependencies, MongoDB connection, port already in use
```

### MongoDB Connection Error
```bash
# Test connection
python3 -c "from pymongo import MongoClient; print(MongoClient('mongodb://localhost:27017/').server_info())"

# Or check if mongod is running
ps aux | grep mongod
```

### Webhook Not Received
```bash
# Check Nginx is forwarding
sudo tail -f /var/log/nginx/access.log

# Verify webhook URL in Cint dashboard
# Verify webhook secret matches .env
```

### DNS Not Resolving
```bash
# Wait 5-15 minutes for DNS to propagate
nslookup surveyieldwork.com

# Check DNS configuration in domain registrar
# Verify A record points to 34.41.181.74
```

---

## Next Steps After Deployment

1. **Monitor Cint Integration** - Check for incoming opportunities from Cint
2. **Test Entry Link Generation** - Create sample entry links for surveys
3. **Verify Respondent Allocation** - Ensure respondents can be allocated to Cint surveys
4. **Setup Monitoring** - Configure alerts for backend health
5. **Enable SSL/HTTPS** - Complete SSL certificate setup
6. **Configure Frontend** - Update frontend API base URL to production

---

**Deployment Status**: ☐ Not Started | 🔄 In Progress | ✅ Complete

**Deployed By**: (Your Name)  
**Date Deployed**: (Deployment Date)  
**Deployment Notes**: 
```
(Add any notes here during deployment)
```
