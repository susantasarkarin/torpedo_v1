# 🚀 Deployment Scripts - Quick Reference

## Windows PowerShell Commands

```powershell
# Full deployment (recommended for first-time setup)
.\deploy.ps1

# Setup configuration variables
.\setup_environment.ps1

# Install/update dependencies
.\install_dependencies.ps1
.\install_dependencies.ps1 -Update          # Force update packages
.\install_dependencies.ps1 -Playwright:$false # Skip Playwright

# Start all services
.\start_services.ps1
.\start_services.ps1 -BackendOnly           # Start only backend
.\start_services.ps1 -FrontendOnly          # Start only frontend
.\start_services.ps1 -NoOpen                # Don't open browser
.\start_services.ps1 -SkipRedis             # Skip Redis

# Check system health
.\health_check.ps1
.\health_check.ps1 -Verbose                 # Detailed output
.\health_check.ps1 -Deep                    # Test connectivity
.\health_check.ps1 -Verbose -Deep           # Full diagnostics
```

## Linux/macOS Bash Commands

```bash
# Make scripts executable (first time only)
chmod +x *.sh

# Full deployment
./deploy.sh

# Setup configuration variables
./setup_environment.sh

# Install/update dependencies
./install_dependencies.sh
./install_dependencies.sh --update          # Update packages
./install_dependencies.sh --no-playwright   # Skip Playwright

# Start all services
./start_services.sh
./start_services.sh --backend-only          # Start only backend
./start_services.sh --frontend-only         # Start only frontend
./start_services.sh --no-open               # Don't open browser
./start_services.sh --skip-redis            # Skip Redis

# Check system health
./health_check.sh
./health_check.sh --verbose                 # Detailed output
./health_check.sh --deep                    # Test connectivity
./health_check.sh --verbose --deep          # Full diagnostics
```

## Common Workflows

### Initial Setup
```powershell
# Step 1: Run full deployment
.\deploy.ps1

# Step 2: Configure environment
.\setup_environment.ps1

# Step 3: Verify everything
.\health_check.ps1 -Verbose

# Step 4: Start services
.\start_services.ps1
```

### Daily Development
```powershell
# Check system health
.\health_check.ps1

# Start services
.\start_services.ps1

# Services are now running at:
#   Frontend: http://localhost:5173
#   Backend: http://localhost:8000
#   API Docs: http://localhost:8000/docs
```

### Update Dependencies
```powershell
# Update all packages
.\install_dependencies.ps1 -Update

# Verify installation
.\health_check.ps1 -Verbose

# Restart services
.\start_services.ps1
```

### Troubleshooting
```powershell
# Run comprehensive diagnostics
.\health_check.ps1 -Verbose -Deep

# Check specific services
Test-Port 8000    # Backend
Test-Port 5173    # Frontend
Test-Port 6379    # Redis
```

## Services & Ports

| Service | Port | URL |
|---------|------|-----|
| Backend API | 8000 | http://localhost:8000 |
| API Documentation | 8000 | http://localhost:8000/docs |
| Frontend | 5173 | http://localhost:5173 |
| Redis | 6379 | localhost:6379 |
| MongoDB | 27017 | Via MONGO_URI |

## Environment Variables

**Required:**
- `MONGO_URI` - MongoDB connection string
- `API_BASE` - Backend URL (usually http://localhost:8000)
- `SESSION_SECRET` - Session signing key

**Optional but Recommended:**
- `OPENAI_API_KEY` - OpenAI API key
- `GEMINI_API_KEYS` - Comma-separated Gemini keys
- `REDIS_URL` - Redis connection string

**View/Edit Configuration:**
```powershell
# View .env file
Get-Content .env

# Edit .env file
notepad .env
```

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| `Python not found` | Install Python 3.9+ from python.org |
| `Node.js not found` | Install Node.js 18+ from nodejs.org |
| `Port 8000 in use` | Kill process: `Stop-Process -Id <PID> -Force` |
| `Module not found` | Run `.\install_dependencies.ps1` |
| `.env file not found` | Run `.\setup_environment.ps1` |
| `MongoDB connection failed` | Check MONGO_URI in .env |
| `API not responding` | Check backend logs in backend directory |

## PowerShell Setup (First Time)

```powershell
# Check execution policy
Get-ExecutionPolicy

# If restricted, set it (one-time)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Or run script with bypass
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

## Development Tips

**Start with fresh dependencies:**
```powershell
# Remove and reinstall
Remove-Item -Recurse -Force venv
Remove-Item -Recurse -Force "Campaign_platform\node_modules"
.\install_dependencies.ps1
```

**Clear backend builds:**
```powershell
# Remove Python cache
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem -Recurse -Filter *.pyc | Remove-Item -Force
```

**Test API connectivity:**
```powershell
# In another PowerShell terminal
while($true) {
    try {
        Invoke-WebRequest http://localhost:8000/docs | Out-Null
        Write-Host "✅ API is up"
    } catch {
        Write-Host "❌ API is down"
    }
    Start-Sleep -Seconds 5
}
```

## File Locations

```
project/
├── deploy.ps1                      # Main deployment (Windows)
├── deploy.sh                       # Main deployment (Linux)
├── setup_environment.ps1           # Env config (Windows)
├── setup_environment.sh            # Env config (Linux)
├── install_dependencies.ps1        # Install deps (Windows)
├── install_dependencies.sh         # Install deps (Linux)
├── start_services.ps1              # Start services (Windows)
├── start_services.sh               # Start services (Linux)
├── health_check.ps1                # Health check (Windows)
├── health_check.sh                 # Health check (Linux)
├── .env                            # Configuration (⚠️ don't commit)
├── .env.example                    # Template
├── backend/                        # Python API
│   ├── requirements.txt
│   └── main.py
├── Campaign_platform/              # React frontend
│   └── package.json
└── DEPLOYMENT_SCRIPTS_README.md    # Full documentation
```

## Quick Status Check

```powershell
# All-in-one status check
Write-Host "🔍 Platform Status Check" -ForegroundColor Cyan
Write-Host ""
Write-Host "Backend (port 8000):" -ForegroundColor Yellow
if ((Test-Port 8000) -eq $true) { Write-Host "✅ Running" -ForegroundColor Green } else { Write-Host "❌ Not running" -ForegroundColor Red }

Write-Host "Frontend (port 5173):" -ForegroundColor Yellow
if ((Test-Port 5173) -eq $true) { Write-Host "✅ Running" -ForegroundColor Green } else { Write-Host "❌ Not running" -ForegroundColor Red }

Write-Host "Redis (port 6379):" -ForegroundColor Yellow
if ((Test-Port 6379) -eq $true) { Write-Host "✅ Running" -ForegroundColor Green } else { Write-Host "❌ Not running" -ForegroundColor Red }
```

---

**For detailed documentation, see:** `DEPLOYMENT_SCRIPTS_README.md`
