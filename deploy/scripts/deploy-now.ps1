# Clean Deployment Script for Torpedo Platform
param(
    [string]$VMHost = "torpedo.cogentixresearch.com",
    [string]$VMUser = "root",
    [string]$VMPath = "/var/www/torpedo",
    [string]$Branch = "fix/cint-waterfall-async"
)

$ErrorActionPreference = "Continue"

Write-Host "================================" -ForegroundColor Green
Write-Host "Torpedo Deployment Script" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green
Write-Host ""
Write-Host "Configuration:" -ForegroundColor Cyan
Write-Host "  VM Host: $VMHost"
Write-Host "  VM User: $VMUser"
Write-Host "  VM Path: $VMPath"
Write-Host "  Branch: $Branch"
Write-Host ""

# Step 1: Test SSH Connection
Write-Host "[1/5] Testing SSH connection..." -ForegroundColor Yellow
try {
    $sshTest = ssh $VMUser@$VMHost "hostname" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ SSH Connection OK (hostname: $sshTest)" -ForegroundColor Green
    } else {
        Write-Host "X SSH Connection Failed" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "X SSH Connection Error: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 2: Git Pull on VM
Write-Host "[2/5] Pulling latest code from GitHub..." -ForegroundColor Yellow
try {
    ssh $VMUser@$VMHost @"
        cd $VMPath
        echo "Current branch: \$(git rev-parse --abbrev-ref HEAD)"
        git fetch origin
        git pull origin $Branch
        echo "Pull completed. Current HEAD:"
        git log -1 --oneline
"@
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Code updated" -ForegroundColor Green
    } else {
        Write-Host "X Git pull failed" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "X Git pull error: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 3: Build Frontend
Write-Host "[3/5] Building frontend..." -ForegroundColor Yellow
try {
    ssh $VMUser@$VMHost @"
        cd $VMPath/Campaign_platform
        echo "Installing npm dependencies..."
        npm install --silent 2>&1 | tail -20
        echo ""
        echo "Building frontend..."
        npm run build 2>&1 | tail -30
        echo "Build completed"
"@
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Frontend build complete" -ForegroundColor Green
    } else {
        Write-Host "X Frontend build failed" -ForegroundColor Red
    }
} catch {
    Write-Host "X Build error: $_" -ForegroundColor Red
}
Write-Host ""

# Step 4: Restart Services
Write-Host "[4/5] Restarting services..." -ForegroundColor Yellow
try {
    ssh $VMUser@$VMHost @"
        cd $VMPath
        
        # Try systemd first
        if systemctl is-active --quiet campaign-backend 2>/dev/null; then
            echo "Restarting campaign-backend..."
            sudo systemctl restart campaign-backend
            sleep 2
            sudo systemctl status campaign-backend --no-pager | head -10
        elif systemctl is-active --quiet torpedo-backend 2>/dev/null; then
            echo "Restarting torpedo-backend..."
            sudo systemctl restart torpedo-backend
            sleep 2
            sudo systemctl status torpedo-backend --no-pager | head -10
        # Try docker-compose
        elif [ -f docker-compose.yml ]; then
            echo "Restarting via docker-compose..."
            docker-compose restart backend frontend
        else
            echo "WARNING: Could not determine service manager"
        fi
        
        echo "Service restart completed"
"@
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Services restarted" -ForegroundColor Green
    } else {
        Write-Host "⚠ Service restart may have had issues (see above)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "X Service restart error: $_" -ForegroundColor Red
}
Write-Host ""

# Step 5: Verify Deployment
Write-Host "[5/5] Verifying deployment..." -ForegroundColor Yellow
try {
    ssh $VMUser@$VMHost @"
        cd $VMPath
        echo "=== Deployment Verification ==="
        echo ""
        echo "Git Status:"
        git log -1 --format="%h - %s (%ar)"
        echo ""
        echo "Backend Health:"
        curl -s http://localhost:8000/health || echo "Backend not responding at :8000"
        echo ""
        echo "Frontend Build Status:"
        [ -d Campaign_platform/dist ] && echo "✓ Frontend dist folder exists" || echo "X Frontend dist not found"
        echo ""
        echo "=== Deployment Complete ==="
"@
    Write-Host "✓ Verification complete" -ForegroundColor Green
} catch {
    Write-Host "⚠ Verification error: $_" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✅ Deployment finished!" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  • Check frontend: https://$VMHost or http://$VMHost:5173"
Write-Host "  • Check backend: curl https://$VMHost/health"
Write-Host "  • SSH in: ssh $VMUser@$VMHost"
Write-Host ""
