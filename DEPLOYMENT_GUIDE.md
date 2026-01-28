# AI Cold Outreach Platform - Deployment Guide

## 🚀 Quick Start

### Prerequisites
- **Python**: 3.9+ ([Download](https://www.python.org/downloads/))
- **Node.js**: 18+ ([Download](https://nodejs.org/))
- **MongoDB**: 5.0+ (local or [Atlas](https://www.mongodb.com/atlas))
- **Git**: Latest version

---

## 📍 Localhost Deployment (Development)

### Option 1: One-Command Deploy
```powershell
.\deploy_localhost.ps1
```

### Option 2: Manual Setup
```powershell
# 1. Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install frontend dependencies
cd Campaign_platform
npm install
cd ..

# 4. Copy environment file
Copy-Item .env.example .env
# Edit .env with your settings

# 5. Start services
.\start_services.ps1
```

### Access Points (Localhost)
| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

---

## 🖥️ VM Deployment (Production)

### Prerequisites on VM (Ubuntu 22.04)
```bash
# Run as root on fresh VM
curl -sSL https://raw.githubusercontent.com/your-repo/vm_config/vm_setup.sh | sudo bash
```

### Deploy from Windows
```powershell
# Deploy to VM
.\deploy_vm.ps1 -VMHost "your-vm-ip" -VMUser "aioutreach"

# With custom path
.\deploy_vm.ps1 -VMHost "192.168.1.100" -VMUser "aioutreach" -VMPath "/opt/campaign"
```

### Manual VM Setup
```bash
# 1. SSH to VM
ssh aioutreach@your-vm-ip

# 2. Clone repository
git clone https://github.com/your-username/campaign_platform.git /home/aioutreach/app
cd /home/aioutreach/app

# 3. Setup environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Configure
cp .env.example .env.production
nano .env.production  # Edit settings

# 5. Install systemd services
sudo cp vm_config/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aioutreach-backend aioutreach-frontend aioutreach-celery

# 6. Start services
sudo systemctl start aioutreach-backend
sudo systemctl start aioutreach-frontend
sudo systemctl start aioutreach-celery

# 7. Configure nginx
sudo cp vm_config/nginx.conf /etc/nginx/sites-available/default
sudo nginx -t
sudo systemctl restart nginx
```

### VM Service Management
```bash
# Check status
sudo systemctl status aioutreach-*

# View logs
journalctl -u aioutreach-backend -f
journalctl -u aioutreach-frontend -f

# Restart services
sudo systemctl restart aioutreach-backend

# Stop all
sudo systemctl stop aioutreach-*
```

---

## 📦 GitHub Deployment

### Push to GitHub
```powershell
# Simple push
.\push_to_github.ps1 -Message "Feature: Add new campaign types"

# Force push (use carefully!)
.\push_to_github.ps1 -Message "Hotfix" -Force

# Dry run (preview changes)
.\push_to_github.ps1 -DryRun

# Create release
.\push_to_github.ps1 -Message "Release v1.0" -CreateRelease -ReleaseTag "v1.0.0"
```

### Manual Git Commands
```bash
# Stage all changes
git add -A

# Commit
git commit -m "Your message"

# Push
git push origin main

# Create tag
git tag -a v1.0.0 -m "Version 1.0.0"
git push origin v1.0.0
```

### GitHub Actions (CI/CD)
Create `.github/workflows/deploy.yml`:
```yaml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          pytest backend/tests/ -v
      
      - name: Deploy to VM
        env:
          SSH_KEY: ${{ secrets.SSH_PRIVATE_KEY }}
          VM_HOST: ${{ secrets.VM_HOST }}
        run: |
          # Add deployment script here
          echo "Deploying to production..."
```

---

## 📁 Directory Structure

```
campaign_platform/
├── backend/               # Python FastAPI backend
│   ├── campaigns/         # Campaign management
│   ├── leads/             # Lead management
│   ├── linkedin/          # LinkedIn automation
│   ├── deliverability/    # Email deliverability
│   ├── agents/            # AI agents
│   ├── ml/                # Machine learning models
│   ├── routers/           # API routes
│   └── migrations/        # Database migrations
├── Campaign_platform/     # React frontend
│   ├── src/
│   │   ├── pages/         # Page components
│   │   └── components/    # Shared components
│   └── dist/              # Production build
├── vm_config/             # VM configuration files
│   ├── systemd/           # Service files
│   ├── nginx.conf         # Nginx config
│   └── vm_setup.sh        # VM setup script
├── logs/                  # Application logs
├── .env                   # Environment variables
├── requirements.txt       # Python dependencies
└── deploy_*.ps1           # Deployment scripts
```

---

## ⚙️ Environment Variables

### Required Variables
```env
# Database
MONGO_URI=mongodb://localhost:27017/campaign_platform

# API
API_BASE=http://localhost:8000
CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# Authentication
SESSION_SECRET=your-secret-key-here
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=change-me

# AI Services
OPENAI_API_KEY=sk-...
GEMINI_API_KEYS=key1,key2,key3
```

### Optional Variables
```env
# Redis (for caching/queues)
REDIS_URL=redis://localhost:6379/0

# Email
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...

# LinkedIn
LINKEDIN_EMAIL=...
LINKEDIN_PASSWORD=...
```

---

## 🔧 Troubleshooting

### Backend won't start
```powershell
# Check logs
Get-Content logs\backend.log -Tail 50

# Check port
netstat -an | findstr "8000"

# Kill existing process
Get-Process -Name python | Stop-Process -Force
```

### Frontend won't start
```powershell
# Check logs
Get-Content logs\frontend.log -Tail 50

# Reinstall dependencies
cd Campaign_platform
Remove-Item -Recurse node_modules
npm install
```

### MongoDB connection issues
```bash
# Check MongoDB status
mongosh --eval "db.serverStatus()"

# Test connection
python -c "from pymongo import MongoClient; print(MongoClient('mongodb://localhost:27017/').server_info())"
```

### VM SSH issues
```powershell
# Test connection
ssh -v aioutreach@your-vm-ip

# Add SSH key
ssh-copy-id aioutreach@your-vm-ip
```

---

## 📊 Health Checks

### Localhost
```powershell
.\health_check.ps1
```

### VM
```bash
# Quick check
curl http://localhost:8000/health

# Full monitoring
./vm_config/monitor.sh
```

---

## 📝 Useful Scripts

| Script | Purpose |
|--------|---------|
| `deploy_localhost.ps1` | Start local development |
| `deploy_vm.ps1` | Deploy to remote VM |
| `push_to_github.ps1` | Push changes to GitHub |
| `start_services.ps1` | Start all services |
| `stop_services.ps1` | Stop all services |
| `health_check.ps1` | Check system health |
| `install_dependencies.ps1` | Install all dependencies |
| `setup_environment.ps1` | Configure .env file |

---

## 🔐 Security Checklist

- [ ] Change default admin password
- [ ] Generate strong SESSION_SECRET
- [ ] Never commit .env files
- [ ] Use SSH keys (disable password auth)
- [ ] Configure firewall (UFW)
- [ ] Enable HTTPS with SSL certificate
- [ ] Set up automated backups
- [ ] Monitor logs for anomalies

---

## 📞 Support

- **Documentation**: See `README.md` and `CAMPAIGN_AUTOMATION_DOCS.md`
- **Testing**: Follow `TESTING_CHECKLIST.md`
- **Issues**: Create GitHub issue with logs attached
