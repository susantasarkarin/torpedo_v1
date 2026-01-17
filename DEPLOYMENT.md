# 🚀 Cint Integration - Production Deployment Guide

**Deployment Target**: GCP VM (139.59.32.72)  
**Domain**: surveyieldwork.com  
**Timeline**: ~15 minutes

---

## Phase 1: Pre-Deployment Checks (Local)

### 1. Verify Backend Status
```bash
# Terminal: Navigate to project root
cd "d:\Code\03. Projects\01. torpedo wip\02. 20 dec\campaign_platform-main\campaign_platform-main"

# Check git status
git status

# Should show all changes ready to commit
```

### 2. Commit All Changes
```bash
git add -A
git commit -m "feat: Implement Cint entry link CRUD endpoints and webhook signature validation

- Add Entry Link CRUD endpoints (POST/PUT/GET)
- Implement HMAC-SHA256 webhook signature validation
- Wire CintService and CintAllocationExtension via dependency injection
- Add comprehensive error handling and logging
- Support respondent outcome tracking"

git push origin main
```

---

## Phase 2: Deploy to GCP VM

### Prerequisites Check
Before deploying, ensure on your GCP VM:
- ✅ Python 3.8+ installed
- ✅ MongoDB running (or connection URI available)
- ✅ SSH access working
- ✅ Git installed

### Deployment Steps

#### Step 1: SSH into GCP VM
```bash
ssh root@139.59.32.72
```

#### Step 2: Navigate to Project & Update Code
```bash
# Go to project directory
cd /home/susanta/campaign_platform

# If first time cloning
git clone https://github.com/YOUR_USERNAME/campaign_platform.git .

# Or if already cloned, just pull latest
git pull origin main
cd backend
```

#### Step 3: Install/Update Python Dependencies
```bash
# Ensure pip is up to date
python3 -m pip install --upgrade pip

# Install all backend requirements
pip install -r requirements.txt

# Verify critical packages
python3 -c "import fastapi, httpx, pymongo, pydantic; print('✅ All dependencies installed')"
```

#### Step 4: Update Environment Variables
```bash
# Create/update .env file with production settings
cat > .env << 'EOF'
# MongoDB - Change if using remote MongoDB
MONGO_URI=mongodb://localhost:27017/

# API Configuration
API_BASE=https://surveyieldwork.com
CORS_ORIGINS=https://surveyieldwork.com,https://www.surveyieldwork.com,http://139.59.32.72

# Cint API Configuration (Already set in code)
CINT_API_KEY=C61C48A6-8154-4F9F-B616-8DFB66F452A7
CINT_SUPPLIER_CODE=6777
CINT_ENVIRONMENT=sandbox
CINT_WEBHOOK_SECRET=M7jTY9DGoXEC3AG8tAJ289l57U6e9hpT2q5xN7n88UbpiYInITVU35MHTFRB8520syiC4WQA7oS2LN90PRuD7

# Optional: CPX Research Configuration
CPX_APP_ID=
CPX_EXT_USER_ID=
CPX_SECURE_HASH_KEY=
CPX_API_TIMEOUT=30
EOF
```

#### Step 5: Start/Restart Backend with PM2
```bash
# If PM2 not installed, install globally
npm install -g pm2
# or
sudo apt-get update && sudo apt-get install npm -y && npm install -g pm2

# Stop existing process if running
pm2 stop campaign-backend || true

# Start backend with PM2
pm2 start "python3 -m uvicorn main:app --host 0.0.0.0 --port 8000" --name "campaign-backend"

# Save PM2 configuration for auto-restart
pm2 save

# Enable startup on reboot
pm2 startup
sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u susanta --hp /home/susanta

# Verify running
pm2 status
pm2 logs campaign-backend
```

#### Step 6: Setup Nginx Reverse Proxy (If Not Already Done)
```bash
# Install nginx
sudo apt-get install nginx -y

# Create configuration
sudo bash -c 'cat > /etc/nginx/sites-available/campaign-api << "EOF"
server {
    listen 80;
    server_name surveyieldwork.com www.surveyieldwork.com 139.59.32.72;

    # Redirect HTTP to HTTPS (after SSL is set up)
    # return 301 https://$server_name$request_uri;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_connect_timeout 60s;
    }

    # Webhook endpoint (no auth needed)
    location /api/cint/webhooks/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF'

# Enable the site
sudo ln -s /etc/nginx/sites-available/campaign-api /etc/nginx/sites-enabled/ || true

# Test nginx configuration
sudo nginx -t

# Start/restart nginx
sudo systemctl start nginx
sudo systemctl enable nginx
```

#### Step 7: Verify Deployment
```bash
# Check backend is running
pm2 status campaign-backend

# Test health endpoint
curl http://localhost:8000/health

# Test Cint endpoints
curl http://localhost:8000/api/cint/health

# View logs
pm2 logs campaign-backend --lines 50
```

---

## Phase 3: Configure Cint Webhook in Cint Dashboard

1. **Log into Cint Dashboard**
2. **Navigate to**: Settings → Webhooks or Integration
3. **Configure Opportunities Webhook**:
   - **URL**: `https://surveyieldwork.com/api/cint/webhooks/opportunities`
   - **Secret Key**: `M7jTY9DGoXEC3AG8tAJ289l57U6e9hpT2q5xN7n88UbpiYInITVU35MHTFRB8520syiC4WQA7oS2LN90PRuD7`
   - **Frequency**: 15 seconds (or your preference)
   - **Test**: Send test webhook
4. **Verify**: Should see 200 OK response in logs

---

## Phase 4: SSL/HTTPS Setup (Recommended)

### Option A: Let's Encrypt (Free)
```bash
# Install Certbot
sudo apt-get install certbot python3-certbot-nginx -y

# Get certificate
sudo certbot certonly --standalone -d surveyieldwork.com -d www.surveyieldwork.com

# Update nginx config to use HTTPS
# Edit /etc/nginx/sites-available/campaign-api
# Uncomment the redirect line and add SSL block

# Renew cert automatically
sudo certbot renew --dry-run
```

### Option B: Use existing GCP certificate (if available)
Contact your DevOps team for certificate path.

---

## Monitoring & Troubleshooting

### Check Backend Status
```bash
pm2 status
pm2 logs campaign-backend --lines 100
```

### Test Endpoints
```bash
# Health check
curl https://surveyieldwork.com/health

# Cint endpoints
curl https://surveyieldwork.com/api/cint/health
curl https://surveyieldwork.com/api/cint/opportunities

# API documentation
curl https://surveyieldwork.com/docs
```

### Common Issues

**Issue: Backend not starting**
```bash
# Check logs
pm2 logs campaign-backend

# Verify Python and dependencies
python3 --version
pip list | grep -E "fastapi|httpx|pymongo"

# Restart
pm2 restart campaign-backend
```

**Issue: MongoDB connection error**
```bash
# Check MongoDB is running
mongod --version

# Verify connection URI in .env
# Test connection: 
python3 -c "from pymongo import MongoClient; print(MongoClient('mongodb://localhost:27017/').server_info())"
```

**Issue: Webhook not being received**
```bash
# Check nginx is forwarding correctly
sudo tail -f /var/log/nginx/access.log

# Verify Cint webhook URL is correct
# Check webhook secret matches environment variable

# Test webhook manually
curl -X POST https://surveyieldwork.com/api/cint/webhooks/opportunities \
  -H "Content-Type: application/json" \
  -d '{"survey_id": 123, "message_reason": "new"}'
```

---

## Rollback Plan

If issues occur:
```bash
# Stop current version
pm2 stop campaign-backend

# Revert to previous commit
git reset --hard HEAD~1
git push origin main --force

# Reinstall dependencies (if needed)
pip install -r requirements.txt

# Restart
pm2 start campaign-backend
```

---

## Success Checklist

After deployment, verify:
- [ ] Backend running: `pm2 status` shows "online"
- [ ] Health endpoint works: `curl https://surveyieldwork.com/health`
- [ ] API docs accessible: Visit `/docs`
- [ ] Cint endpoints accessible: `curl https://surveyieldwork.com/api/cint/health`
- [ ] Webhook can receive data (test from Cint dashboard)
- [ ] Logs show no errors: `pm2 logs campaign-backend`
- [ ] MongoDB collections created: Check with MongoDB Compass

---

## Post-Deployment Tasks

1. **Monitor Cint Webhook** - Check for incoming opportunities
2. **Test Entry Link Creation** - Create test entry links
3. **Verify Respondent Allocation** - Ensure respondents can be assigned to Cint surveys
4. **Check Metrics** - Monitor survey performance metrics
5. **Update Frontend** - Point frontend to new API URL if needed

---

**Need help? Check logs with:**
```bash
pm2 logs campaign-backend
```

**Questions?** Review the CINT_IMPLEMENTATION_GUIDE.md for detailed API documentation.
