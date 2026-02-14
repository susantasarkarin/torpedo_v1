# Windows PowerShell - Cint Integration Deployment Commands
# Copy and paste these commands one at a time

Write-Host "=== Cint Integration Deployment ===" -ForegroundColor Green
Write-Host ""

# Configuration
$VMHost = "torpedo.cogentixresearch.com"
$VMUser = "root"
$VMPath = "/var/www/torpedo/backend"
$LocalPath = "d:\Code\03. Projects\01. torpedo wip\01. Torpedo v1 (python reacy)\campaign_platform-main\campaign_platform-main"

Write-Host "Target: ${VMUser}@${VMHost}:${VMPath}" -ForegroundColor Yellow
Write-Host ""

# Step 1: Test SSH
Write-Host "[Step 1/5] Testing SSH connection..." -ForegroundColor Cyan
ssh ${VMUser}@${VMHost} "echo 'SSH connection successful'"
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ SSH connection verified" -ForegroundColor Green
} else {
    Write-Host "✗ SSH connection failed. Check your SSH key setup." -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 2: Create backup
Write-Host "[Step 2/5] Creating backup on VM..." -ForegroundColor Cyan
$backupCmd = @"
cd ${VMPath}
BACKUP_DIR=`"backups/`$(date +%Y%m%d_%H%M%S)`"
mkdir -p `$BACKUP_DIR/app/routers
mkdir -p `$BACKUP_DIR/app/services
[ -f app/routers/cint.py ] && cp app/routers/cint.py `$BACKUP_DIR/app/routers/
[ -f app/services/cint_service.py ] && cp app/services/cint_service.py `$BACKUP_DIR/app/services/
echo `"Backup created at `$BACKUP_DIR`"
"@

ssh ${VMUser}@${VMHost} $backupCmd
Write-Host "✓ Backup created" -ForegroundColor Green
Write-Host ""

# Step 3: Deploy cint.py
Write-Host "[Step 3/5] Deploying backend/app/routers/cint.py..." -ForegroundColor Cyan
scp "${LocalPath}\backend\app\routers\cint.py" "${VMUser}@${VMHost}:${VMPath}/app/routers/cint.py"
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ cint.py deployed" -ForegroundColor Green
} else {
    Write-Host "✗ Failed to deploy cint.py" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 4: Deploy cint_service.py
Write-Host "[Step 4/5] Deploying backend/app/services/cint_service.py..." -ForegroundColor Cyan
scp "${LocalPath}\backend\app\services\cint_service.py" "${VMUser}@${VMHost}:${VMPath}/app/services/cint_service.py"
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ cint_service.py deployed" -ForegroundColor Green
} else {
    Write-Host "✗ Failed to deploy cint_service.py" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 5: Restart service
Write-Host "[Step 5/5] Restarting backend service..." -ForegroundColor Cyan
$restartCmd = @"
if systemctl is-active --quiet torpedo-backend; then
    echo 'Restarting torpedo-backend service...'
    sudo systemctl restart torpedo-backend
    sleep 3
    sudo systemctl status torpedo-backend --no-pager | head -20
elif command -v supervisorctl &> /dev/null; then
    echo 'Restarting via supervisor...'
    supervisorctl restart torpedo
elif [ -f docker-compose.yml ]; then
    echo 'Restarting via docker-compose...'
    cd ${VMPath}/../
    docker-compose restart backend
else
    echo 'Could not detect service manager. Please restart manually.'
fi
"@

ssh ${VMUser}@${VMHost} $restartCmd
Write-Host "✓ Service restarted" -ForegroundColor Green
Write-Host ""

# Step 6: Verify deployment
Write-Host "Verifying deployment..." -ForegroundColor Cyan
Start-Sleep -Seconds 5

Write-Host "Testing diagnostic endpoint..." -ForegroundColor Cyan
try {
    $response = Invoke-WebRequest -Uri "https://${VMHost}/api/cint/diagnostic" -UseBasicParsing
    Write-Host "✓ Diagnostic endpoint is accessible (HTTP 200)" -ForegroundColor Green
    Write-Host ""

    # Display diagnostic data
    Write-Host "Diagnostic Data:" -ForegroundColor Yellow
    $response.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10

    Write-Host ""
    Write-Host "=== DEPLOYMENT SUCCESSFUL ===" -ForegroundColor Green

} catch {
    $statusCode = $_.Exception.Response.StatusCode.Value__
    Write-Host "✗ Diagnostic endpoint returned HTTP $statusCode" -ForegroundColor Red
    Write-Host ""
    Write-Host "Check service logs:" -ForegroundColor Yellow
    Write-Host "  ssh ${VMUser}@${VMHost} 'journalctl -u torpedo-backend -n 50'" -ForegroundColor White
}

Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Monitor webhook activity:" -ForegroundColor White
Write-Host "   ssh ${VMUser}@${VMHost} 'tail -f /var/log/torpedo/backend.log | grep \"Received opportunities webhook\"'" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Check entry link debug logs:" -ForegroundColor White
Write-Host "   ssh ${VMUser}@${VMHost} 'tail -f /var/log/torpedo/backend.log | grep \"ENTRY LINK DEBUG\"'" -ForegroundColor Gray
Write-Host ""
Write-Host "3. View full diagnostic:" -ForegroundColor White
Write-Host "   curl https://${VMHost}/api/cint/diagnostic | jq" -ForegroundColor Gray
