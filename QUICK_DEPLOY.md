# 🚀 Quick Deployment Commands - Copy & Paste

**For GCP VM (139.59.32.72) - Ubuntu/Linux**

---

## One-Time Setup (Run Once)

```bash
# SSH into VM
ssh root@139.59.32.72

# Navigate to project
cd /home/susanta/campaign_platform
git clone https://github.com/sristi3227/campaign_platform.git . || git pull origin main
cd backend

# Install Python dependencies
pip install -r requirements.txt

# Install PM2 (Node.js package manager for Python processes)
sudo apt-get update
sudo apt-get install npm -y
npm install -g pm2

# Configure environment
cat > .env << 'EOF'
MONGO_URI=mongodb://localhost:27017/
CINT_API_KEY=C61C48A6-8154-4F9F-B616-8DFB66F452A7
CINT_SUPPLIER_CODE=6777
CINT_ENVIRONMENT=sandbox
CINT_WEBHOOK_SECRET=M7jTY9DGoXEC3AG8tAJ289l57U6e9hpT2q5xN7n88UbpiYInITVU35MHTFRB8520syiC4WQA7oS2LN90PRuD7
API_BASE=https://surveyieldwork.com
CORS_ORIGINS=https://surveyieldwork.com,https://www.surveyieldwork.com,http://139.59.32.72
EOF

# Start backend
pm2 start "python3 -m uvicorn main:app --host 0.0.0.0 --port 8000" --name "campaign-backend"
pm2 save
pm2 startup

# Install and configure Nginx
sudo apt-get install nginx -y

# Create Nginx config
sudo bash -c 'cat > /etc/nginx/sites-available/campaign-api << "EOF"
server {
    listen 80;
    server_name surveyieldwork.com www.surveyieldwork.com 139.59.32.72;

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

# Enable Nginx site
sudo ln -s /etc/nginx/sites-available/campaign-api /etc/nginx/sites-enabled/ || true
sudo nginx -t
sudo systemctl start nginx
sudo systemctl enable nginx
```

---

## Update Code (Run When New Version Available)

```bash
# SSH into VM
ssh root@139.59.32.72

# Update code
cd /home/susanta/campaign_platform/backend
git pull origin main
pip install -r requirements.txt

# Restart backend
pm2 restart campaign-backend

# View logs
pm2 logs campaign-backend
```

---

## Status & Monitoring

```bash
# Check if backend is running
ssh root@139.59.32.72 "pm2 status"

# View logs
ssh root@139.59.32.72 "pm2 logs campaign-backend --lines 50"

# Test health endpoint
curl http://139.59.32.72/health

# Test after DNS propagates
curl https://surveyieldwork.com/health
```

---

## Stop/Restart

```bash
# Stop backend
ssh root@139.59.32.72 "pm2 stop campaign-backend"

# Restart backend
ssh root@139.59.32.72 "pm2 restart campaign-backend"

# View detailed logs
ssh root@139.59.32.72 "pm2 logs campaign-backend --lines 100"
```

---

## Testing Webhooks

**Manually send test webhook:**

```bash
#!/bin/bash
# Test webhook with proper signature

HOST="http://139.59.32.72"  # Change to https://surveyieldwork.com after DNS propagates
WEBHOOK_SECRET="M7jTY9DGoXEC3AG8tAJ289l57U6e9hpT2q5xN7n88UbpiYInITVU35MHTFRB8520syiC4WQA7oS2LN90PRuD7"

BODY='{"survey_id": 123, "supplier_id": 6777, "message_reason": "new"}'

# Generate HMAC-SHA256 signature
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -hex | cut -d' ' -f2)

echo "Sending webhook..."
echo "Signature: $SIG"
echo "Body: $BODY"

curl -X POST "$HOST/api/cint/webhooks/opportunities" \
  -H "Content-Type: application/json" \
  -H "X-Cint-Signature: $SIG" \
  -d "$BODY"

echo ""
echo "Done!"
```

---

## MongoDB Verification

```bash
# Connect to MongoDB
ssh root@139.59.32.72 "mongosh localhost:27017/campaign_platform"

# In MongoDB shell:
use campaign_platform
db.cint_surveys.countDocuments()
db.cint_entry_links.countDocuments()
db.cint_metrics.find().pretty()
```

---

## Critical Environment Variables

Make sure these are in your GCP VM `.env` file:

```
MONGO_URI=mongodb://localhost:27017/
CINT_API_KEY=C61C48A6-8154-4F9F-B616-8DFB66F452A7
CINT_SUPPLIER_CODE=6777
CINT_ENVIRONMENT=sandbox
CINT_WEBHOOK_SECRET=M7jTY9DGoXEC3AG8tAJ289l57U6e9hpT2q5xN7n88UbpiYInITVU35MHTFRB8520syiC4WQA7oS2LN90PRuD7
```

---

## Common Issues & Fixes

### Issue: "Address already in use"
```bash
# Kill process on port 8000
ssh root@139.59.32.72 "lsof -i :8000 | grep LISTEN | awk '{print $2}' | xargs kill -9"
pm2 restart campaign-backend
```

### Issue: MongoDB connection refused
```bash
# Check if mongod is running
ssh root@139.59.32.72 "ps aux | grep mongod"

# Start MongoDB if not running
ssh root@139.59.32.72 "mongod --fork --logpath /var/log/mongodb.log"
```

### Issue: Nginx not forwarding
```bash
# Check Nginx status
ssh root@139.59.32.72 "sudo systemctl status nginx"

# Check logs
ssh root@139.59.32.72 "sudo tail -f /var/log/nginx/error.log"

# Test Nginx config
ssh root@139.59.32.72 "sudo nginx -t"
```

### Issue: Backend won't start
```bash
# Check what's wrong
ssh root@139.59.32.72 "pm2 logs campaign-backend"

# Check if all dependencies installed
ssh root@139.59.32.72 "python3 -c 'import fastapi, httpx, pymongo; print(\"OK\")'"
```

---

## API Endpoints Available

After deployment, these endpoints will be live:

### Core
- `GET /` - Root endpoint
- `GET /health` - Health check
- `GET /docs` - Swagger API documentation
- `GET /redoc` - ReDoc documentation

### Cint Integration
- `GET /api/cint/health` - Cint service health
- `GET /api/cint/opportunities` - List opportunities
- `POST /api/cint/entry-links/{survey_id}` - Create entry link
- `PUT /api/cint/entry-links/{survey_id}` - Update entry link
- `GET /api/cint/entry-links/{survey_id}` - Get entry link
- `POST /api/cint/webhooks/opportunities` - Receive webhook callbacks
- `POST /api/cint/webhooks/respondent-outcomes` - Receive respondent outcomes

### Other (25+ additional routers)
- CPX Research endpoints
- Lead ingestion endpoints
- Campaign management endpoints
- Email sync endpoints
- RBAC endpoints
- And more...

---

## Deployment Checklist

- [ ] SSH into GCP VM works
- [ ] Code cloned to /home/susanta/campaign_platform
- [ ] Python dependencies installed
- [ ] PM2 installed globally
- [ ] Backend started with PM2
- [ ] Nginx configured and running
- [ ] Health endpoint responds (200 OK)
- [ ] Cint endpoints accessible
- [ ] MongoDB collections created
- [ ] Environment variables configured
- [ ] DNS pointing to 139.59.32.72
- [ ] Webhook signature validation tested
- [ ] No errors in `pm2 logs campaign-backend`
- [ ] Cint dashboard webhook configured

---

## Support

**Last Updated**: January 8, 2026  
**Git Commit**: 6e41ae5  
**Status**: ✅ Ready for Deployment

For detailed information, see:
- [DEPLOYMENT.md](DEPLOYMENT.md) - Full deployment guide
- [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) - Step-by-step checklist
- [CINT_IMPLEMENTATION_GUIDE.md](CINT_IMPLEMENTATION_GUIDE.md) - API documentation
