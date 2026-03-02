# Deployment Script for Torpedo Platform
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
        Write-Host "[OK] SSH Connection verified" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] SSH Connection Failed" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[ERROR] SSH Connection Error: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 2: Git Pull on VM
Write-Host "[2/5] Pulling latest code from GitHub..." -ForegroundColor Yellow
try {
    ssh $VMUser@$VMHost @"
cd $VMPath
git fetch origin
git pull origin $Branch
git log -1 --oneline
"@
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Code updated from GitHub" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] Git pull failed" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[ERROR] Git pull error: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 3: Build Frontend
Write-Host "[3/5] Building frontend..." -ForegroundColor Yellow
try {
    ssh $VMUser@$VMHost @"
cd $VMPath/Campaign_platform
npm install --silent 2>&1 | tail -5
npm run build 2>&1 | tail -10
echo "Build completed"
"@
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Frontend build complete" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Frontend build may have completed with warnings" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[ERROR] Build error: $_" -ForegroundColor Red
}
Write-Host ""

# Step 4: Restart Services
Write-Host "[4/5] Restarting services..." -ForegroundColor Yellow
try {
    ssh $VMUser@$VMHost @"
cd $VMPath

if command -v systemctl &> /dev/null; then
    if systemctl is-active --quiet campaign-backend; then
        sudo systemctl restart campaign-backend
        sleep 2
        echo "Restarted campaign-backend"
    elif systemctl is-active --quiet torpedo-backend; then
        sudo systemctl restart torpedo-backend
        sleep 2
        echo "Restarted torpedo-backend"
    fi
elif [ -f docker-compose.yml ]; then
    echo "Restarting via docker-compose..."
    docker-compose restart backend frontend
    sleep 3
    echo "Service restart completed"
else
    echo "WARNING: Could not determine service manager"
fi
"@
    Write-Host "[OK] Services restart command sent" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Service restart error: $_" -ForegroundColor Red
}
Write-Host ""

# Step 5: Verify Deployment
Write-Host "[5/5] Verifying deployment..." -ForegroundColor Yellow
try {
    ssh $VMUser@$VMHost @"
cd $VMPath
echo "=== Deployment Status ==="
git log -1 --format="Latest commit: %h - %s (%ar)"

if [ -d Campaign_platform/dist ]; then
    echo "[OK] Frontend build exists"
else
    echo "[WARN] Frontend dist folder not found"
fi

echo "=== Verification Complete ==="
"@
    Write-Host "[OK] Verification complete" -ForegroundColor Green
} catch {
    Write-Host "[WARN] Verification issues: $_" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=============================" -ForegroundColor Green
Write-Host "Deployment Finished" -ForegroundColor Green
Write-Host "=============================" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  1. Check frontend: https://$VMHost"
Write-Host "  2. Check backend: curl https://$VMHost/health"
Write-Host "  3. View logs: ssh $VMUser@$VMHost"
Write-Host ""
