#!/usr/bin/env pwsh
# LinkedIn Automation Deployment Script for Torpedo VM
# Usage: .\deploy-linkedin-automation.ps1 -VMHost "139.59.32.72" -VMUser "root"

param(
    [Parameter(Mandatory=$false)]
    [string]$VMHost = "139.59.32.72",
    [string]$VMUser = "root",
    [string]$VMPath = "/var/www/torpedo"
)

$ErrorActionPreference = "Stop"

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)

Write-Host "`n╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   LinkedIn Automation Deployment to Torpedo VM             ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "Target: ${VMUser}@${VMHost}:${VMPath}" -ForegroundColor Yellow
Write-Host ""

# Step 1: Verify SSH
Write-Host "[1/5] Verifying SSH connection..." -ForegroundColor Yellow
try {
    $result = ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${VMUser}@${VMHost}" "echo OK" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ SSH connection successful" -ForegroundColor Green
    } else {
        throw "SSH failed"
    }
} catch {
    Write-Host "✗ SSH connection failed to ${VMHost}" -ForegroundColor Red
    Write-Host "  Check: Host is reachable, SSH key configured, user is correct" -ForegroundColor Red
    exit 1
}

# Step 2: Create backup
Write-Host "[2/5] Creating backup on VM..." -ForegroundColor Yellow
$backupCmd = @"
cd ${VMPath}
BACKUP_DIR="backups/linkedin-`$(date +%Y%m%d_%H%M%S)"
mkdir -p `$BACKUP_DIR/backend/linkedin_automation
mkdir -p `$BACKUP_DIR/backend/tasks
[ -d backend/linkedin_automation ] && cp -r backend/linkedin_automation `$BACKUP_DIR/backend/ || true
[ -f backend/tasks/linkedin_tasks.py ] && cp backend/tasks/linkedin_tasks.py `$BACKUP_DIR/backend/tasks/ || true
echo "Backup at `$BACKUP_DIR"
"@

ssh "${VMUser}@${VMHost}" $backupCmd | ForEach-Object { Write-Host "  $_" }
Write-Host "✓ Backup created" -ForegroundColor Green

# Step 3: Deploy files
Write-Host "[3/5] Deploying LinkedIn automation module..." -ForegroundColor Yellow

$files = @(
    "backend/linkedin_automation/__init__.py",
    "backend/linkedin_automation/models.py",
    "backend/linkedin_automation/service.py",
    "backend/linkedin_automation/job.py",
    "backend/linkedin_automation/router.py",
    "backend/linkedin_automation/jobs_queue.py",
    "backend/linkedin_automation/database.py",
    "backend/tasks/linkedin_tasks.py"
)

# Create directories
ssh "${VMUser}@${VMHost}" "mkdir -p ${VMPath}/backend/linkedin_automation ${VMPath}/backend/tasks" | Out-Null

# Deploy files
foreach ($file in $files) {
    $sourcePath = Join-Path $projectRoot $file
    $remoteFile = "${VMPath}/${file}"
    
    if (Test-Path $sourcePath) {
        Write-Host "  ↑ $file" -ForegroundColor Gray
        scp -o StrictHostKeyChecking=no -q $sourcePath "${VMUser}@${VMHost}:${remoteFile}" 2>&1 | Out-Null
    } else {
        Write-Host "  ! Missing: $file" -ForegroundColor Yellow
    }
}

Write-Host "✓ Module deployed" -ForegroundColor Green

# Step 4: Update application files
Write-Host "[4/5] Updating main application files..." -ForegroundColor Yellow

$appFiles = @(
    "backend/celery_app.py",
    "backend/main.py"
)

foreach ($file in $appFiles) {
    $sourcePath = Join-Path $projectRoot $file
    $remoteFile = "${VMPath}/${file}"
    
    Write-Host "  ↑ $file" -ForegroundColor Gray
    scp -o StrictHostKeyChecking=no -q $sourcePath "${VMUser}@${VMHost}:${remoteFile}" 2>&1 | Out-Null
}

Write-Host "✓ Application files updated" -ForegroundColor Green

# Step 5: Deploy configuration
Write-Host "[5/5] Setting up configuration and services..." -ForegroundColor Yellow

$configCmd = @"
mkdir -p ${VMPath}/vm_config/systemd
sudo mkdir -p /etc/torpedo
sudo touch /etc/torpedo/linkedin-automation.env
sudo chmod 600 /etc/torpedo/linkedin-automation.env
echo "✓ Configuration prepared"
"@

ssh "${VMUser}@${VMHost}" $configCmd | ForEach-Object { Write-Host "  $_" }

# Copy systemd service files to VM
Write-Host "  ↑ Deploying systemd services..." -ForegroundColor Gray
scp -o StrictHostKeyChecking=no -q `
    "$projectRoot\vm_config\systemd\torpedo-linkedin-beat.service" `
    "${VMUser}@${VMHost}:${VMPath}/vm_config/systemd/" 2>&1 | Out-Null

scp -o StrictHostKeyChecking=no -q `
    "$projectRoot\vm_config\systemd\torpedo-linkedin-worker.service" `
    "${VMUser}@${VMHost}:${VMPath}/vm_config/systemd/" 2>&1 | Out-Null

# Deploy environment template
Write-Host "  ↑ Deploying configuration template..." -ForegroundColor Gray
scp -o StrictHostKeyChecking=no -q `
    "$projectRoot\vm_config\linkedin-automation.env.example" `
    "${VMUser}@${VMHost}:${VMPath}/vm_config/" 2>&1 | Out-Null

Write-Host "✓ Configuration deployed" -ForegroundColor Green

# Summary
Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║              ✓ Deployment Complete!                       ║" -ForegroundColor Green
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "📋 Next Steps:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1️⃣  SSH to your VM:"
Write-Host "   ssh ${VMUser}@${VMHost}"
Write-Host ""
Write-Host "2️⃣  Generate encryption key:"
Write-Host "   python3 << 'EOF'"
Write-Host "   from cryptography.fernet import Fernet"
Write-Host "   print(Fernet.generate_key().decode())"
Write-Host "   EOF"
Write-Host ""
Write-Host "3️⃣  Configure environment:"
Write-Host "   sudo nano /etc/torpedo/linkedin-automation.env"
Write-Host "   (Copy your encryption key and database credentials)"
Write-Host ""
Write-Host "4️⃣  Install systemd services:"
Write-Host "   sudo cp /var/www/torpedo/vm_config/systemd/*.service /etc/systemd/system/"
Write-Host "   sudo chmod 644 /etc/systemd/system/torpedo-linkedin-*.service"
Write-Host "   sudo systemctl daemon-reload"
Write-Host "   sudo systemctl enable torpedo-linkedin-beat.service --now"
Write-Host "   sudo systemctl enable torpedo-linkedin-worker.service --now"
Write-Host ""
Write-Host "5️⃣  Verify services are running:"
Write-Host "   sudo systemctl status torpedo-linkedin-beat"
Write-Host "   sudo systemctl status torpedo-linkedin-worker"
Write-Host ""
Write-Host "6️⃣  Add a LinkedIn account via API:"
Write-Host "   curl -X POST http://${VMHost}:8000/api/marketing/linkedin/accounts \"
Write-Host "     -H 'Content-Type: application/json' \"
Write-Host "     -d '{"
Write-Host "       ""email"": ""your_email@linkedin.com"","
Write-Host "       ""password"": ""your_password"","
Write-Host "       ""account_name"": ""Account 1"""
Write-Host "     }'"
Write-Host ""
Write-Host "📚 Documentation:"
Write-Host "   - Quick Start: LINKEDIN_AUTOMATION_QUICKSTART.md"
Write-Host "   - Full Guide: LINKEDIN_AUTOMATION_DEPLOYMENT.md"
Write-Host ""
