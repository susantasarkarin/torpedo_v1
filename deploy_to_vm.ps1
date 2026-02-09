# PowerShell deployment script for Cint Integration fixes
# Usage: .\deploy_to_vm.ps1

param(
    [string]$VMHost = "torpedo.cogentixresearch.com",
    [string]$VMUser = "root",
    [string]$VMPath = "/var/www/torpedo/backend",
    [string]$ServiceName = "torpedo-backend"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Cint Integration Deployment ===" -ForegroundColor Green
Write-Host "Target: ${VMUser}@${VMHost}:${VMPath}"
Write-Host ""

# Check if SCP is available (requires OpenSSH on Windows or WSL)
try {
    $scpTest = Get-Command scp -ErrorAction Stop
} catch {
    Write-Host "Error: SCP not found. Please install OpenSSH or use WSL." -ForegroundColor Red
    Write-Host "Install OpenSSH: Settings > Apps > Optional Features > Add OpenSSH Client" -ForegroundColor Yellow
    exit 1
}

# Check SSH connection
Write-Host "[1/6] Checking SSH connection..." -ForegroundColor Yellow
try {
    ssh -o ConnectTimeout=5 "${VMUser}@${VMHost}" "echo 'SSH connection successful'" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "SSH connection failed" }
    Write-Host "✓ SSH connection verified" -ForegroundColor Green
} catch {
    Write-Host "Error: Cannot connect to VM. Please check:" -ForegroundColor Red
    Write-Host "  1. VM credentials are correct"
    Write-Host "  2. SSH key is configured"
    Write-Host "  3. VM is accessible"
    exit 1
}

# Create backup on VM
Write-Host "[2/6] Creating backup on VM..." -ForegroundColor Yellow
$backupScript = @"
cd ${VMPath}
BACKUP_DIR=\"backups/`$(date +%Y%m%d_%H%M%S)\"
mkdir -p `$BACKUP_DIR/app/routers
mkdir -p `$BACKUP_DIR/app/services

[ -f app/routers/cint.py ] && cp app/routers/cint.py `$BACKUP_DIR/app/routers/
[ -f app/services/cint_service.py ] && cp app/services/cint_service.py `$BACKUP_DIR/app/services/

echo \"Backup created at `$BACKUP_DIR\"
"@

ssh "${VMUser}@${VMHost}" $backupScript
Write-Host "✓ Backup created" -ForegroundColor Green

# Deploy files
Write-Host "[3/6] Deploying modified files..." -ForegroundColor Yellow

$LocalDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "  - Deploying backend/app/routers/cint.py"
scp "${LocalDir}\backend\app\routers\cint.py" "${VMUser}@${VMHost}:${VMPath}/app/routers/cint.py"

Write-Host "  - Deploying backend/app/services/cint_service.py"
scp "${LocalDir}\backend\app\services\cint_service.py" "${VMUser}@${VMHost}:${VMPath}/app/services/cint_service.py"

Write-Host "✓ Files deployed" -ForegroundColor Green

# Deploy documentation (optional)
Write-Host "[4/6] Deploying documentation files..." -ForegroundColor Yellow
ssh "${VMUser}@${VMHost}" "mkdir -p ${VMPath}/docs"

try {
    scp "${LocalDir}\CINT_STATUS_REPORT.md" `
        "${LocalDir}\CINT_DIAGNOSTIC_GUIDE.md" `
        "${LocalDir}\CINT_INTEGRATION_COMPLETE.md" `
        "${LocalDir}\CINT_INTEGRATION_FIXES.md" `
        "${LocalDir}\DEPLOYMENT_CHECKLIST.md" `
        "${VMUser}@${VMHost}:${VMPath}/docs/"
    Write-Host "✓ Documentation deployed" -ForegroundColor Green
} catch {
    Write-Host "  (Documentation upload optional - skipped)" -ForegroundColor Yellow
}

# Restart service
Write-Host "[5/6] Restarting backend service..." -ForegroundColor Yellow
$restartScript = @"
if systemctl is-active --quiet ${ServiceName}; then
    echo 'Restarting via systemd...'
    sudo systemctl restart ${ServiceName}
    sleep 3
    sudo systemctl status ${ServiceName} --no-pager
elif command -v supervisorctl &> /dev/null; then
    echo 'Restarting via supervisor...'
    supervisorctl restart torpedo || supervisorctl restart all
elif [ -f docker-compose.yml ]; then
    echo 'Restarting via docker-compose...'
    docker-compose restart backend
else
    echo 'Warning: Could not detect service manager. Please restart manually.'
    exit 1
fi
"@

ssh "${VMUser}@${VMHost}" $restartScript
Write-Host "✓ Service restarted" -ForegroundColor Green

# Verify deployment
Write-Host "[6/6] Verifying deployment..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

Write-Host "  - Testing diagnostic endpoint..."
try {
    $response = Invoke-WebRequest -Uri "https://${VMHost}/api/cint/diagnostic" -UseBasicParsing -ErrorAction Stop
    $statusCode = $response.StatusCode
} catch {
    $statusCode = $_.Exception.Response.StatusCode.Value__
}

if ($statusCode -eq 200) {
    Write-Host "✓ Diagnostic endpoint responding (HTTP 200)" -ForegroundColor Green
    Write-Host ""
    Write-Host "=== Deployment Successful! ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:"
    Write-Host "  1. Check diagnostic output:"
    Write-Host "     curl https://${VMHost}/api/cint/diagnostic | jq"
    Write-Host ""
    Write-Host "  2. Monitor webhook activity:"
    Write-Host "     ssh ${VMUser}@${VMHost} 'tail -f /var/log/torpedo/backend.log | grep \"Received opportunities webhook\"'"
    Write-Host ""
    Write-Host "  3. Check entry link debug logs:"
    Write-Host "     ssh ${VMUser}@${VMHost} 'tail -f /var/log/torpedo/backend.log | grep \"ENTRY LINK DEBUG\"'"
} else {
    Write-Host "✗ Diagnostic endpoint returned HTTP ${statusCode} (expected 200)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Troubleshooting:"
    Write-Host "  1. Check service logs:"
    Write-Host "     ssh ${VMUser}@${VMHost} 'journalctl -u ${ServiceName} -n 50'"
    Write-Host ""
    Write-Host "  2. Check if service is running:"
    Write-Host "     ssh ${VMUser}@${VMHost} 'systemctl status ${ServiceName}'"
}
