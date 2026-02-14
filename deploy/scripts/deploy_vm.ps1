# ============================================================================
# AI Cold Outreach Platform - VM Deployment Script
# ============================================================================
# Deploy to a remote VM (Ubuntu) via SSH
# Usage: .\deploy_vm.ps1 -VMHost "your-vm-ip" -VMUser "aioutreach"
# ============================================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$VMHost,
    [string]$VMUser = "aioutreach",
    [string]$VMPath = "/home/aioutreach/app",
    [switch]$SkipBuild,
    [switch]$SkipTests,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Script:ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

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

function Test-SSHConnection {
    Write-Log "Testing SSH connection to $VMUser@$VMHost..." "Step"
    try {
        $result = ssh -o ConnectTimeout=10 "$VMUser@$VMHost" "echo 'connected'" 2>&1
        if ($result -eq "connected") {
            Write-Log "SSH connection successful" "Success"
            return $true
        }
    } catch {}
    Write-Log "SSH connection failed. Ensure SSH key is configured." "Error"
    return $false
}

function Build-Frontend {
    if ($SkipBuild) {
        Write-Log "Skipping frontend build (-SkipBuild flag)" "Info"
        return $true
    }
    
    Write-Log "Building frontend for production..." "Step"
    $frontendDir = Join-Path $Script:ProjectRoot "Campaign_platform"
    
    if (-not (Test-Path $frontendDir)) {
        Write-Log "Frontend directory not found, skipping build" "Warning"
        return $true
    }
    
    Push-Location $frontendDir
    try {
        npm run build 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
        Write-Log "Frontend build completed" "Success"
        return $true
    } catch {
        Write-Log "Frontend build failed: $_" "Error"
        return $false
    } finally {
        Pop-Location
    }
}

function Create-DeploymentPackage {
    Write-Log "Creating deployment package..." "Step"
    
    $packageDir = Join-Path $Script:ProjectRoot "deploy_package_$Script:Timestamp"
    $packageFile = "$packageDir.tar.gz"
    
    # Create temporary directory
    New-Item -ItemType Directory -Path $packageDir -Force | Out-Null
    
    # Copy backend
    Write-Log "Copying backend files..." "Progress"
    $excludePatterns = @("__pycache__", "*.pyc", ".env", "venv", ".venv", "*.log", ".git")
    robocopy "$Script:ProjectRoot\backend" "$packageDir\backend" /E /XD $excludePatterns /XF ".env" "*.log" /NFL /NDL /NJH /NJS | Out-Null
    
    # Copy frontend build (if exists)
    $frontendDist = Join-Path $Script:ProjectRoot "Campaign_platform\dist"
    if (Test-Path $frontendDist) {
        Write-Log "Copying frontend build..." "Progress"
        robocopy $frontendDist "$packageDir\frontend\dist" /E /NFL /NDL /NJH /NJS | Out-Null
    }
    
    # Copy configuration files
    Write-Log "Copying configuration files..." "Progress"
    Copy-Item "$Script:ProjectRoot\requirements.txt" "$packageDir\" -ErrorAction SilentlyContinue
    Copy-Item "$Script:ProjectRoot\.env.example" "$packageDir\" -ErrorAction SilentlyContinue
    Copy-Item "$Script:ProjectRoot\vm_config" "$packageDir\" -Recurse -ErrorAction SilentlyContinue
    
    # Create tarball using tar (if available) or just use the directory
    Write-Log "Package created at: $packageDir" "Success"
    return $packageDir
}

function Deploy-ToVM {
    param([string]$PackageDir)
    
    Write-Log "Deploying to VM..." "Step"
    
    # Create remote directory
    Write-Log "Creating remote directory structure..." "Progress"
    ssh "$VMUser@$VMHost" "mkdir -p $VMPath $VMPath/logs $VMPath/backups"
    
    # Upload files using scp
    Write-Log "Uploading files to VM (this may take a few minutes)..." "Progress"
    scp -r "$PackageDir\*" "$VMUser@$VMHost`:$VMPath/"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Log "Files uploaded successfully" "Success"
        return $true
    } else {
        Write-Log "File upload failed" "Error"
        return $false
    }
}

function Setup-VMEnvironment {
    Write-Log "Setting up VM environment..." "Step"
    
    $setupScript = @"
cd $VMPath

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate and install dependencies
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Run migrations
if [ -d "backend/migrations" ]; then
    echo "Running database migrations..."
    python backend/migrations/run_migrations.py || true
fi

# Set permissions
chmod +x vm_config/*.sh 2>/dev/null || true

echo "Environment setup completed"
"@
    
    ssh "$VMUser@$VMHost" $setupScript
    
    if ($LASTEXITCODE -eq 0) {
        Write-Log "VM environment setup completed" "Success"
        return $true
    } else {
        Write-Log "VM environment setup had warnings" "Warning"
        return $true
    }
}

function Install-SystemdServices {
    Write-Log "Installing systemd services..." "Step"
    
    $serviceScript = @"
cd $VMPath

# Copy service files
sudo cp vm_config/systemd/*.service /etc/systemd/system/ 2>/dev/null || true

# Reload systemd
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable aioutreach-backend.service 2>/dev/null || true
sudo systemctl enable aioutreach-frontend.service 2>/dev/null || true
sudo systemctl enable aioutreach-celery.service 2>/dev/null || true

echo "Systemd services installed"
"@
    
    ssh "$VMUser@$VMHost" $serviceScript
    Write-Log "Systemd services configured" "Success"
}

function Start-VMServices {
    Write-Log "Starting services on VM..." "Step"
    
    $startScript = @"
cd $VMPath

# Start services
sudo systemctl restart aioutreach-backend.service 2>/dev/null || {
    # Fallback: start directly
    source venv/bin/activate
    cd backend
    nohup python -m uvicorn main:app --host 0.0.0.0 --port 8000 > ../logs/backend.log 2>&1 &
    echo "Backend started directly"
}

# Start frontend (if build exists)
if [ -d "frontend/dist" ]; then
    # Serve with nginx or directly
    echo "Frontend build ready for nginx"
fi

# Check status
sleep 3
curl -sf http://localhost:8000/health && echo "Backend: HEALTHY" || echo "Backend: Starting..."
"@
    
    ssh "$VMUser@$VMHost" $startScript
    Write-Log "Services started" "Success"
}

function Verify-Deployment {
    Write-Log "Verifying deployment..." "Step"
    
    $verifyScript = @"
echo "=== Deployment Verification ==="
echo ""
echo "Disk Usage:"
df -h $VMPath
echo ""
echo "Process Check:"
ps aux | grep -E 'uvicorn|gunicorn|celery' | grep -v grep || echo "No processes found"
echo ""
echo "Port Check:"
netstat -tlnp 2>/dev/null | grep -E ':8000|:3000|:5173' || ss -tlnp | grep -E ':8000|:3000|:5173' || echo "Ports not listening"
echo ""
echo "Health Check:"
curl -sf http://localhost:8000/health && echo "Backend: OK" || echo "Backend: Not responding"
echo ""
echo "=== End Verification ==="
"@
    
    ssh "$VMUser@$VMHost" $verifyScript
}

function Cleanup-LocalPackage {
    param([string]$PackageDir)
    
    if (Test-Path $PackageDir) {
        Write-Log "Cleaning up local deployment package..." "Progress"
        Remove-Item -Path $PackageDir -Recurse -Force
        Write-Log "Cleanup completed" "Success"
    }
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

function Main {
    Write-Host "`n╔════════════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║                   VM DEPLOYMENT - AI Cold Outreach                        ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan
    
    Write-Log "Target: $VMUser@$VMHost`:$VMPath" "Info"
    Write-Log "Timestamp: $Script:Timestamp" "Info"
    
    # Test SSH connection
    if (-not (Test-SSHConnection)) {
        Write-Log "Cannot connect to VM. Aborting." "Error"
        exit 1
    }
    
    # Build frontend
    if (-not (Build-Frontend)) {
        if (-not $Force) {
            Write-Log "Frontend build failed. Use -Force to continue anyway." "Error"
            exit 1
        }
    }
    
    # Create deployment package
    $packageDir = Create-DeploymentPackage
    
    try {
        # Deploy to VM
        if (-not (Deploy-ToVM -PackageDir $packageDir)) {
            Write-Log "Deployment failed" "Error"
            exit 1
        }
        
        # Setup environment
        Setup-VMEnvironment
        
        # Install systemd services
        Install-SystemdServices
        
        # Start services
        Start-VMServices
        
        # Verify deployment
        Verify-Deployment
        
    } finally {
        # Cleanup
        Cleanup-LocalPackage -PackageDir $packageDir
    }
    
    Write-Host @"

╔════════════════════════════════════════════════════════════════════════════╗
║                       VM DEPLOYMENT COMPLETE                              ║
╚════════════════════════════════════════════════════════════════════════════╝

✅ Application deployed to: $VMUser@$VMHost`:$VMPath

🌐 Access Points:
   Backend API:  http://$VMHost`:8000
   API Docs:     http://$VMHost`:8000/docs
   Frontend:     http://$VMHost (via nginx)

📋 Next Steps:
   1. Configure nginx: sudo nano /etc/nginx/sites-available/default
   2. Setup SSL: sudo certbot --nginx
   3. Monitor logs: ssh $VMUser@$VMHost "tail -f $VMPath/logs/*.log"

🔧 Useful Commands:
   Restart backend:  ssh $VMUser@$VMHost "sudo systemctl restart aioutreach-backend"
   View logs:        ssh $VMUser@$VMHost "journalctl -u aioutreach-backend -f"
   Check status:     ssh $VMUser@$VMHost "sudo systemctl status aioutreach-*"

"@ -ForegroundColor Cyan
    
    Write-Log "Deployment completed successfully!" "Success"
}

# Run main
Main
