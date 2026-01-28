# PowerShell Deployment Scripts for AI Cold Outreach Platform

This directory contains production-ready PowerShell scripts for deploying and managing the Campaign Platform on Windows systems.

## 📋 Scripts Overview

### 1. **deploy.ps1** - Master Deployment Script
**Main orchestrator for complete deployment process**

```powershell
.\deploy.ps1 [-SkipServices]
```

**What it does:**
- ✅ Displays beautiful ASCII art banner
- ✅ Verifies system prerequisites (Python 3.9+, Node.js 18+, npm, Git)
- ✅ Checks/creates .env configuration file
- ✅ Installs all dependencies (Python & Node packages)
- ✅ Runs database migrations
- ✅ Offers to start all services
- ✅ Creates logs in `logs/` directory

**Features:**
- Color-coded output (Green=success, Red=error, Yellow=warning, Cyan=info)
- Comprehensive version checking
- Detailed logging to `logs/deployment_YYYY-MM-DD_HH-mm-ss.log`
- Exit codes for automation (0=success, 1=error)

**Use when:** Starting fresh deployment or updating your system

---

### 2. **setup_environment.ps1** - Environment Configuration
**Creates and configures .env file**

```powershell
.\setup_environment.ps1 [-Interactive]
```

**What it does:**
- ✅ Copies .env.example template to .env
- ✅ Validates configuration keys
- ✅ Backs up existing .env files with timestamp
- ✅ Supports interactive mode for custom configuration

**Required variables in .env:**
- `MONGO_URI` - MongoDB connection string
- `API_BASE` - API base URL
- `CORS_ORIGINS` - Allowed CORS origins
- `SESSION_SECRET` - Session signing secret
- `DEFAULT_ADMIN_USERNAME` - Admin username
- `DEFAULT_ADMIN_PASSWORD` - Admin password

**Use when:** 
- Setting up a new environment
- Configuring different deployment stages
- Updating configuration variables

---

### 3. **install_dependencies.ps1** - Dependency Installer
**Installs all project dependencies**

```powershell
.\install_dependencies.ps1 [-Force] [-SkipPlaywright] [-Verbose]
```

**What it does:**
- ✅ Creates Python virtual environment (`backend/venv`)
- ✅ Upgrades pip to latest version
- ✅ Installs Python packages from `backend/requirements.txt`
  - FastAPI, PyMongo, Pydantic, Uvicorn, Google Generative AI, OpenAI, BeautifulSoup4
- ✅ Installs Node.js packages from `Campaign_platform/package.json` via npm
- ✅ Installs Playwright browsers (optional via `-SkipPlaywright`)
- ✅ Verifies installations

**Options:**
- `-Force`: Recreate virtual environment (deletes existing)
- `-SkipPlaywright`: Skip browser installation
- `-Verbose`: Show detailed debug output

**Use when:**
- Initial setup
- Adding/updating dependencies
- Troubleshooting installation issues

---

### 4. **start_services.ps1** - Service Startup
**Starts all platform services in parallel**

```powershell
.\start_services.ps1 [-NoFrontend] [-NoCelery] [-OpenBrowser] [-Verbose]
```

**Services started:**
1. **Backend API** (Uvicorn on port 8000)
   - FastAPI application
   - Runs with auto-reload enabled
   - Logs to `logs/services/backend.log`

2. **Frontend** (Vite dev server on port 5173)
   - React/Vue development server
   - Logs to `logs/services/frontend.log`
   - Optional with `-NoFrontend`

3. **Celery Worker** (Background job processor)
   - Processes async tasks
   - Logs to `logs/services/celery.log`
   - Optional with `-NoCelery`

**Options:**
- `-NoFrontend`: Skip frontend startup
- `-NoCelery`: Skip Celery worker startup
- `-OpenBrowser`: Automatically open browser to frontend URL
- `-Verbose`: Show detailed output

**Service URLs:**
- Backend: `http://localhost:8000`
- Frontend: `http://localhost:5173`

**Features:**
- Waits for ports to be available before considering service ready
- 30-second timeout for each service
- Captures output to individual log files
- Graceful shutdown on Ctrl+C
- Process monitoring

**Use when:** 
- Ready to run the platform
- Daily development/testing
- Restarting services

---

### 5. **stop_services.ps1** - Service Shutdown
**Gracefully stops all running services**

```powershell
.\stop_services.ps1 [-Force] [-CleanLogs] [-Verbose]
```

**What it does:**
- ✅ Finds all running services (uvicorn, npm, celery)
- ✅ Sends graceful shutdown signal
- ✅ Waits 10 seconds for graceful termination
- ✅ Force-kills if graceful shutdown fails
- ✅ Reports shutdown status
- ✅ Optionally cleans old log files

**Options:**
- `-Force`: Immediately force-terminate all processes
- `-CleanLogs`: Delete log files older than 10 most recent
- `-Verbose`: Show detailed output

**Features:**
- Graceful shutdown with timeout
- Process verification
- Detailed logging
- Safe cleanup

**Use when:**
- Ending development session
- Troubleshooting service issues
- Deploying updates
- System maintenance

---

### 6. **health_check.ps1** - System Health Verification
**Checks health status of all services and resources**

```powershell
.\health_check.ps1 [-Monitor] [-Interval 10] [-Verbose]
```

**Checks performed:**
- ✅ Backend API port (8000) and health endpoint
- ✅ Frontend port (5173) availability
- ✅ MongoDB port (27017) connectivity
- ✅ Disk space usage
- ✅ System memory usage

**Service status indicators:**
- 🟢 ✅ Healthy (HTTP 200 response)
- 🟡 ⚠️ Running (port open, endpoint check failed)
- 🔴 ❌ Down (port not responding)

**Options:**
- `-Monitor`: Run continuous monitoring with auto-refresh
- `-Interval 10`: Refresh interval in seconds (default 10)
- `-Verbose`: Show debug information

**Features:**
- Real-time health status
- Color-coded output
- Continuous monitoring mode
- Resource threshold warnings
  - Disk: Warning at 90%, Critical at 95%
  - Memory: Warning at 80%, Critical at 90%

**Use when:**
- Verifying all services are running
- Troubleshooting issues
- Monitoring system during load testing
- Morning checks before starting work

---

## 🚀 Typical Workflow

### Initial Setup
```powershell
# 1. Deploy everything
.\deploy.ps1

# 2. If deploy.ps1 is interrupted, resume at dependency installation
.\install_dependencies.ps1

# 3. Setup environment (if not done in deploy.ps1)
.\setup_environment.ps1

# 4. Start all services
.\start_services.ps1
```

### Daily Development
```powershell
# Start services
.\start_services.ps1

# Check health
.\health_check.ps1

# ... development work ...

# When done, stop services
.\stop_services.ps1
```

### Monitoring Session
```powershell
# Start continuous health monitoring
.\health_check.ps1 -Monitor -Interval 5
```

### Updating Dependencies
```powershell
# Stop services first
.\stop_services.ps1

# Update dependencies
.\install_dependencies.ps1 -Force

# Start services again
.\start_services.ps1
```

---

## 📊 Output Examples

### deploy.ps1 output
```
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║                   🚀 AI COLD OUTREACH PLATFORM 🚀                        ║
║                                                                            ║
║                     Campaign Platform Deployment                         ║
║                                                                            ║
║                    Windows PowerShell Auto-Installer                     ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝

✅ [10:25:30] Checking system prerequisites...
✅ [10:25:30] Python version meets requirements (3.11.5 >= 3.9)
✅ [10:25:30] Node.js version meets requirements (18.17.1 >= 18.0.0)
```

### start_services.ps1 output
```
🚀 Starting Campaign Platform Services

🔄 [10:30:15] Starting Backend API service...
✅ [10:30:18] Backend API is ready
🔄 [10:30:18] Starting Frontend service...
✅ [10:30:22] Frontend is ready

╔════════════════════════════════════════════════════════════════════════════╗
║                           SERVICES RUNNING                                 ║
╚════════════════════════════════════════════════════════════════════════════╝

  Backend: ✓ Running (http://localhost:8000)
  Frontend: ✓ Running (http://localhost:5173)
  Celery: ✓ Running
```

### health_check.ps1 output
```
╔════════════════════════════════════════════════════════════════════════════╗
║                Campaign Platform Health Status Report                      ║
╚════════════════════════════════════════════════════════════════════════════╝

Check Time: 2026-01-28 10:35:42

🌐 SERVICES
─────────────────────────────────────────────────────────────────────────────
  Backend API: ✅ Healthy (http://localhost:8000)
  Frontend: ✅ Healthy (http://localhost:5173)
  MongoDB: ✓ Running
```

---

## 📁 Log Files Structure

```
logs/
├── deployment_2026-01-28_10-25-30.log
├── environment_setup_2026-01-28_10-26-00.log
├── install_2026-01-28_10-27-15.log
└── services/
    ├── backend.log
    ├── frontend.log
    └── celery.log
```

**View logs in real-time:**
```powershell
Get-Content logs/services/backend.log -Wait
```

---

## 🔍 Troubleshooting

### Port Already in Use
```powershell
# Check what's using a port
netstat -ano -p TCP | findstr ":8000"

# Kill the process (replace XXXX with PID)
Stop-Process -Id XXXX -Force
```

### Python Venv Issues
```powershell
# Recreate virtual environment
.\install_dependencies.ps1 -Force
```

### Cannot Run Scripts
```powershell
# Allow script execution (may need admin)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Services Not Starting
```powershell
# Check logs
Get-Content logs/services/backend.log
Get-Content logs/services/frontend.log

# Re-run installation
.\install_dependencies.ps1

# Try starting again
.\start_services.ps1 -Verbose
```

---

## ✅ Requirements

- **Windows PowerShell 5.1+** (PowerShell Core also supported)
- **Python 3.9+** (from https://www.python.org/)
- **Node.js 18+** (from https://nodejs.org/)
- **npm** (included with Node.js)
- **MongoDB** (for database, can be local or remote via .env)
- **Git** (optional, for version control)

---

## 🔒 Security Notes

- **Change `SESSION_SECRET`** in .env for production
- **Change `DEFAULT_ADMIN_PASSWORD`** immediately in production
- **Backup .env files** before modifications
- **Don't commit .env** to version control
- **Use environment variables** for sensitive data in production
- **Keep scripts updated** for security patches

---

## 📝 Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (check logs) |

---

## 🎯 Next Steps

1. Ensure prerequisites are installed
2. Run `.\deploy.ps1` to start fresh
3. Update `.env` with your configuration
4. Run `.\start_services.ps1` to launch services
5. Visit `http://localhost:5173` in your browser
6. Use `.\health_check.ps1` to monitor system

---

## 📞 Support

For issues or questions:
1. Check relevant log files in `logs/` directory
2. Run scripts with `-Verbose` flag for more details
3. Review this README for common scenarios
4. Check .env configuration for missing values

---

**Version:** 2.0  
**Last Updated:** January 28, 2026  
**Status:** Production Ready ✅
