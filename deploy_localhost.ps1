# ============================================================================
# AI Cold Outreach Platform - Localhost Deployment Script
# ============================================================================
# Quick start for local development
# Usage: .\deploy_localhost.ps1
# ============================================================================

param(
    [switch]$Production,
    [switch]$SkipInstall,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Continue"
$Script:ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:BackendDir = Join-Path $ProjectRoot "backend"
$Script:FrontendDir = Join-Path $ProjectRoot "Campaign_platform"
$Script:VenvPath = Join-Path $ProjectRoot ".venv"

# Colors
$Colors = @{Success = 'Green'; Warning = 'Yellow'; Error = 'Red'; Info = 'Cyan'; Progress = 'Magenta'}

function Write-Log {
    param([string]$Message, [string]$Type = "Info")
    $timestamp = Get-Date -Format "HH:mm:ss"
    switch ($Type) {
        "Success" { Write-Host "✅ [$timestamp] $Message" -ForegroundColor $Colors.Success }
        "Warning" { Write-Host "⚠️  [$timestamp] $Message" -ForegroundColor $Colors.Warning }
        "Error" { Write-Host "❌ [$timestamp] $Message" -ForegroundColor $Colors.Error }
        "Progress" { Write-Host "🔄 [$timestamp] $Message" -ForegroundColor $Colors.Progress }
        "Step" { Write-Host "`n📋 [$timestamp] $Message" -ForegroundColor $Colors.Info }
        default { Write-Host "ℹ️  [$timestamp] $Message" -ForegroundColor $Colors.Info }
    }
}

function Test-Prerequisites {
    Write-Log "Checking prerequisites..." "Step"
    
    # Python
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Log "Python not found! Please install Python 3.9+" "Error"
        return $false
    }
    $pythonVersion = & python --version 2>&1
    Write-Log "Python: $pythonVersion" "Success"
    
    # Node.js
    $node = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $node) {
        Write-Log "Node.js/npm not found! Please install Node.js 18+" "Error"
        return $false
    }
    $nodeVersion = & node --version 2>&1
    Write-Log "Node.js: $nodeVersion" "Success"
    
    # MongoDB check
    try {
        $mongoTest = & mongosh --eval "db.version()" --quiet 2>&1
        Write-Log "MongoDB: Available" "Success"
    } catch {
        Write-Log "MongoDB: Not detected locally (will use remote if configured in .env)" "Warning"
    }
    
    return $true
}

function Setup-Environment {
    Write-Log "Setting up environment..." "Step"
    
    # Check/create .env file
    $envFile = Join-Path $Script:ProjectRoot ".env"
    $envExample = Join-Path $Script:ProjectRoot ".env.example"
    
    if (-not (Test-Path $envFile)) {
        if (Test-Path $envExample) {
            Write-Log "Creating .env from .env.example..." "Progress"
            Copy-Item $envExample $envFile
            Write-Log ".env file created. Please update with your settings." "Warning"
        } else {
            Write-Log ".env file not found and no .env.example available" "Warning"
        }
    } else {
        Write-Log ".env file exists" "Success"
    }
}

function Setup-PythonVenv {
    if ($SkipInstall) {
        Write-Log "Skipping Python setup (-SkipInstall)" "Info"
        return $true
    }
    
    Write-Log "Setting up Python virtual environment..." "Step"
    
    if (-not (Test-Path $Script:VenvPath)) {
        Write-Log "Creating virtual environment..." "Progress"
        & python -m venv $Script:VenvPath
    }
    
    # Activate and install
    $activateScript = Join-Path $Script:VenvPath "Scripts\Activate.ps1"
    if (Test-Path $activateScript) {
        & $activateScript
        
        Write-Log "Upgrading pip..." "Progress"
        & pip install --upgrade pip | Out-Null
        
        $requirementsFile = Join-Path $Script:ProjectRoot "requirements.txt"
        if (Test-Path $requirementsFile) {
            Write-Log "Installing Python dependencies..." "Progress"
            & pip install -r $requirementsFile 2>&1 | Out-Null
            Write-Log "Python dependencies installed" "Success"
        }
    }
    
    return $true
}

function Setup-NodeModules {
    if ($SkipInstall -or $BackendOnly) {
        Write-Log "Skipping Node.js setup" "Info"
        return $true
    }
    
    Write-Log "Setting up Node.js dependencies..." "Step"
    
    if (-not (Test-Path $Script:FrontendDir)) {
        Write-Log "Frontend directory not found: $Script:FrontendDir" "Warning"
        return $true
    }
    
    Push-Location $Script:FrontendDir
    try {
        $nodeModules = Join-Path $Script:FrontendDir "node_modules"
        if (-not (Test-Path $nodeModules)) {
            Write-Log "Installing npm packages..." "Progress"
            & npm install 2>&1 | Out-Null
            Write-Log "npm packages installed" "Success"
        } else {
            Write-Log "node_modules exists" "Success"
        }
    } finally {
        Pop-Location
    }
    
    return $true
}

function Run-Migrations {
    Write-Log "Running database migrations..." "Step"
    
    $migrationsDir = Join-Path $Script:BackendDir "migrations"
    $migrationsScript = Join-Path $migrationsDir "run_migrations.py"
    
    if (Test-Path $migrationsScript) {
        Push-Location $Script:BackendDir
        try {
            $pythonExe = Join-Path $Script:VenvPath "Scripts\python.exe"
            if (Test-Path $pythonExe) {
                & $pythonExe $migrationsScript 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
            } else {
                & python $migrationsScript 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
            }
            Write-Log "Migrations completed" "Success"
        } catch {
            Write-Log "Migration error (may be OK if no changes needed): $_" "Warning"
        } finally {
            Pop-Location
        }
    } else {
        Write-Log "No migrations script found" "Info"
    }
}

function Start-Backend {
    if ($FrontendOnly) {
        Write-Log "Skipping backend (-FrontendOnly)" "Info"
        return
    }
    
    Write-Log "Starting backend server..." "Step"
    
    $pythonExe = Join-Path $Script:VenvPath "Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }
    
    $logDir = Join-Path $Script:ProjectRoot "logs"
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
    
    $backendLog = Join-Path $logDir "backend.log"
    
    Push-Location $Script:BackendDir
    try {
        $process = Start-Process -FilePath $pythonExe `
            -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000", "--reload") `
            -RedirectStandardOutput $backendLog `
            -RedirectStandardError $backendLog `
            -NoNewWindow `
            -PassThru
        
        Write-Log "Backend started (PID: $($process.Id))" "Success"
        Write-Log "Backend log: $backendLog" "Info"
        
        # Wait for backend to be ready
        Write-Log "Waiting for backend to be ready..." "Progress"
        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            try {
                $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/docs" -TimeoutSec 2 -ErrorAction SilentlyContinue
                if ($response.StatusCode -eq 200) {
                    $ready = $true
                    break
                }
            } catch {}
        }
        
        if ($ready) {
            Write-Log "Backend is ready at http://127.0.0.1:8000" "Success"
        } else {
            Write-Log "Backend may still be starting. Check logs: $backendLog" "Warning"
        }
    } finally {
        Pop-Location
    }
}

function Start-Frontend {
    if ($BackendOnly) {
        Write-Log "Skipping frontend (-BackendOnly)" "Info"
        return
    }
    
    Write-Log "Starting frontend server..." "Step"
    
    if (-not (Test-Path $Script:FrontendDir)) {
        Write-Log "Frontend directory not found" "Warning"
        return
    }
    
    $logDir = Join-Path $Script:ProjectRoot "logs"
    $frontendLog = Join-Path $logDir "frontend.log"
    
    Push-Location $Script:FrontendDir
    try {
        $process = Start-Process -FilePath "npm" `
            -ArgumentList @("run", "dev") `
            -RedirectStandardOutput $frontendLog `
            -RedirectStandardError $frontendLog `
            -NoNewWindow `
            -PassThru
        
        Write-Log "Frontend started (PID: $($process.Id))" "Success"
        Write-Log "Frontend log: $frontendLog" "Info"
        
        # Wait for frontend
        Start-Sleep -Seconds 5
        Write-Log "Frontend should be ready at http://127.0.0.1:5173" "Success"
    } finally {
        Pop-Location
    }
}

function Open-Browser {
    if ($NoBrowser) {
        return
    }
    
    Write-Log "Opening browser..." "Progress"
    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:5173"
}

function Show-Summary {
    Write-Host @"

╔════════════════════════════════════════════════════════════════════════════╗
║                    LOCALHOST DEPLOYMENT COMPLETE                          ║
╚════════════════════════════════════════════════════════════════════════════╝

🌐 Access Points:
   Frontend:     http://127.0.0.1:5173
   Backend API:  http://127.0.0.1:8000
   API Docs:     http://127.0.0.1:8000/docs

📁 Project Structure:
   Backend:      $Script:BackendDir
   Frontend:     $Script:FrontendDir
   Logs:         $Script:ProjectRoot\logs

🔧 Useful Commands:
   Stop all:     .\stop_services.ps1
   Health check: .\health_check.ps1
   View logs:    Get-Content logs\backend.log -Tail 50 -Wait

⚠️  Keep this terminal open to keep services running.
    Press Ctrl+C to stop all services.

"@ -ForegroundColor Cyan
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

function Main {
    Write-Host "`n╔════════════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║               LOCALHOST DEPLOYMENT - AI Cold Outreach                     ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan
    
    if (-not (Test-Prerequisites)) {
        exit 1
    }
    
    Setup-Environment
    Setup-PythonVenv
    Setup-NodeModules
    Run-Migrations
    
    Start-Backend
    Start-Sleep -Seconds 2
    Start-Frontend
    
    Open-Browser
    Show-Summary
    
    # Keep running
    Write-Log "Services are running. Press Ctrl+C to stop." "Info"
    try {
        while ($true) { Start-Sleep -Seconds 30 }
    } catch {
        Write-Log "Shutting down..." "Progress"
    }
}

# Run
Main
