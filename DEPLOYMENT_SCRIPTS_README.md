# 🚀 Deployment Automation Scripts

Complete automation scripts for deploying the AI Cold Outreach Platform on Windows (PowerShell) and Linux/macOS (Bash).

---

## Quick Start

### Windows (PowerShell)

```powershell
# 1. Full automated deployment
.\deploy.ps1

# 2. Configure environment variables
.\setup_environment.ps1

# 3. Install/update dependencies
.\install_dependencies.ps1

# 4. Start all services
.\start_services.ps1

# 5. Check system health
.\health_check.ps1
```

### Linux/macOS (Bash)

```bash
# 1. Full automated deployment
./deploy.sh --install-deps

# 2. Start all services
./start_services.sh

# 3. Check system health
./health_check.sh
```

---

## 📋 Script Overview

### Windows PowerShell Scripts

#### 1. **deploy.ps1** - Main Deployment Script
Complete deployment automation script that:
- ✅ Checks Python & Node.js prerequisites
- ✅ Sets up environment variables
- ✅ Installs backend dependencies (Python)
- ✅ Installs frontend dependencies (Node.js)
- ✅ Installs Playwright browsers
- ✅ Runs database migrations
- ✅ Verifies all installations

**Usage:**
```powershell
.\deploy.ps1
```

**Features:**
- Color-coded progress indicators
- Detailed error messages
- Automatic environment detection
- Comprehensive logging

---

#### 2. **setup_environment.ps1** - Environment Configuration
Interactive configuration wizard for setting up:
- 🗄️ MongoDB connection string
- 🔑 OpenAI API key
- 🤖 Gemini API keys
- 🔴 Redis URL (optional)
- 📊 CPX Research credentials (optional)
- 🔐 Session secrets & auth settings

**Usage:**
```powershell
.\setup_environment.ps1
```

**Features:**
- Interactive prompts with defaults
- Configuration validation
- Review before saving
- Creates/updates .env file
- Secure password input

---

#### 3. **install_dependencies.ps1** - Dependency Installer
Installs and verifies all project dependencies:
- 🐍 Python packages (FastAPI, PyMongo, etc.)
- 📦 Node.js packages (React, Vite, etc.)
- 🎭 Playwright browsers

**Usage:**
```powershell
# Install all dependencies
.\install_dependencies.ps1

# Update all packages to latest versions
.\install_dependencies.ps1 -Update

# Install without Playwright (faster)
.\install_dependencies.ps1 -Playwright:$false
```

**Parameters:**
- `-Update`: Force update all packages
- `-Playwright`: Include Playwright browser installation (default: true)

**Features:**
- Version validation (Python 3.9+, Node 18+)
- Package verification
- Progressive installation feedback
- Clear success/error reporting

---

#### 4. **start_services.ps1** - Service Starter
Launches all platform services:
- 🔧 Backend API (FastAPI/Uvicorn on port 8000)
- ⚛️ Frontend Dev Server (Vite on port 5173)
- 🎯 Celery Workers (optional)
- 🔴 Redis Server (optional)

**Usage:**
```powershell
# Start all services
.\start_services.ps1

# Start only backend
.\start_services.ps1 -BackendOnly

# Start only frontend
.\start_services.ps1 -FrontendOnly

# Don't open browser
.\start_services.ps1 -NoOpen

# Skip Redis startup
.\start_services.ps1 -SkipRedis
```

**Parameters:**
- `-BackendOnly`: Start backend only
- `-FrontendOnly`: Start frontend only
- `-NoOpen`: Don't open browser automatically
- `-SkipRedis`: Don't start Redis

**Access Points:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

---

#### 5. **health_check.ps1** - System Health Checker
Comprehensive system health verification:
- ✅ Tool versions (Python, Node.js, Git)
- ✅ Project structure validation
- ✅ Configuration files & environment variables
- ✅ Python package verification
- ✅ Node.js module verification
- ✅ Service connectivity (ports 8000, 5173, 6379)
- ✅ Database connection
- ✅ API endpoint validation

**Usage:**
```powershell
# Basic health check
.\health_check.ps1

# Verbose output
.\health_check.ps1 -Verbose

# Deep connectivity tests
.\health_check.ps1 -Deep

# Both
.\health_check.ps1 -Verbose -Deep
```

**Parameters:**
- `-Verbose`: Show detailed output for each check
- `-Deep`: Perform deep connectivity tests (slower)

**Output:**
- Color-coded results (✅ Pass, ❌ Fail, ⚠️ Warn)
- Summary with passed/failed/warning counts
- Overall health status
- Actionable next steps

---

### Linux/macOS Bash Scripts

All equivalent functionality to PowerShell scripts, written in Bash for Unix-like systems:

- **deploy.sh** - Main deployment (enhanced existing script)
- **setup_environment.sh** - Environment configuration
- **install_dependencies.sh** - Dependency installer
- **start_services.sh** - Service starter
- **health_check.sh** - System health checker

---

## 🔧 Configuration

### Environment File (.env)

Key variables required:

```env
# Database
MONGO_URI=mongodb://localhost:27017/campaign_platform

# Server
API_BASE=http://localhost:8000
CORS_ORIGINS=http://localhost:5173,http://localhost:5174,http://localhost:3000

# Authentication
SESSION_SECRET=your-secret-key-change-in-production
SESSION_TTL_SECONDS=86400
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=change-me

# AI Providers
OPENAI_API_KEY=your-openai-key
GEMINI_API_KEYS=key1,key2,key3

# Optional: Cache
REDIS_URL=redis://localhost:6379/0

# Optional: CPX Research
CPX_APP_ID=your-cpx-app-id
CPX_EXT_USER_ID=your-cpx-user-id
CPX_SECURE_HASH_KEY=your-cpx-hash-key
```

---

## 📊 System Requirements

### Python
- Version: 3.9 or higher
- Used for: Backend API, data processing, migrations

### Node.js
- Version: 18 or higher (20+ recommended)
- Used for: Frontend development & build

### Database
- MongoDB (local or cloud)
- Connection via MONGO_URI

### Optional Services
- Redis: For caching and task queues
- Playwright: For web automation (installed automatically)

---

## 🚀 Deployment Workflow

### First-Time Setup

```powershell
# 1. Clone/download the project
cd campaign_platform

# 2. Run deployment
.\deploy.ps1

# 3. Configure environment
.\setup_environment.ps1

# 4. Start services
.\start_services.ps1

# 5. Access platform
# Frontend: http://localhost:5173
# Backend: http://localhost:8000
```

### Updating Dependencies

```powershell
.\install_dependencies.ps1 -Update
```

### Troubleshooting

```powershell
# Check system health
.\health_check.ps1 -Verbose -Deep

# View specific configuration
Get-Content .env
```

---

## 📝 Script Execution Modes

### Windows PowerShell

**Execution Policy**: Scripts require appropriate execution policy:

```powershell
# Set for current user (recommended)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Or run with bypass for single execution
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

### Linux/macOS Bash

Make scripts executable:

```bash
chmod +x deploy.sh
chmod +x setup_environment.sh
chmod +x install_dependencies.sh
chmod +x start_services.sh
chmod +x health_check.sh

# Run directly
./deploy.sh
```

---

## 🔍 Monitoring & Logs

### Windows PowerShell

Services run in same console window. Use Ctrl+C to stop all services.

For production, consider:
- Running services as background jobs
- Using Task Scheduler for automated restarts
- Implementing log rotation

### Linux/macOS Bash

Services run in the foreground. Use Ctrl+C to stop.

For production, consider:
- systemd services
- supervisor for process management
- logrotate for log management

---

## 🚨 Troubleshooting

### Python Not Found
```
❌ Python not found. Please install Python 3.9+
```
**Solution:** Install Python from https://www.python.org/

### Node.js Not Found
```
❌ Node.js/npm not found!
```
**Solution:** Install Node.js from https://nodejs.org/

### Port Already in Use
```
⚠️  Backend did not respond within timeout
```
**Solution:** 
```powershell
# Check what's using port 8000
Get-NetTCPConnection -LocalPort 8000

# Kill the process
Stop-Process -Id <PID> -Force
```

### MongoDB Connection Failed
```
❌ MongoDB URI not configured
```
**Solution:** Run setup_environment.ps1 and provide valid MongoDB URI

### Playwright Installation Failed
```
⚠️  Failed to install Playwright browsers
```
**Solution:** Install manually:
```powershell
python -m playwright install chromium
```

---

## 📚 Additional Resources

- **Backend Documentation**: See `README_CAMPAIGN_AUTOMATION.md`
- **Environment Variables**: See `.env.example`
- **Architecture**: See `CAMPAIGN_AUTOMATION_DOCS.md`
- **Project Structure**: See `AGENT_WORK_LOCATION_GUIDE.md`

---

## 🤝 Contributing

To improve these scripts:
1. Test thoroughly on your platform
2. Document any changes
3. Update this README with new features
4. Share improvements with the team

---

## ⚠️ Security Notes

- Never commit `.env` file to version control
- Rotate API keys regularly
- Change default admin password immediately
- Use strong SESSION_SECRET in production
- Store credentials securely
- Review logs for security events

---

## 📞 Support

For issues or questions:
1. Check health with: `.\health_check.ps1 -Verbose -Deep`
2. Review relevant deployment script
3. Check error messages in .env and logs
4. Consult README files in project root

---

**Last Updated:** January 2026  
**Version:** 1.0  
**Status:** Production Ready ✅
