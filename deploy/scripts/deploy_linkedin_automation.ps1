#!/usr/bin/env pwsh
# LinkedIn Automation Deployment Script for Torpedo VM
# Usage: .\deploy_linkedin_automation.ps1 -VMHost "139.59.32.72" -VMUser "root"

param(
    [Parameter(Mandatory=$false)]
    [string]$VMHost = "139.59.32.72",
    [string]$VMUser = "root",
    [string]$VMPath = "/var/www/torpedo",
    [string]$ServiceName = "torpedo-linkedin-beat",
    [string]$WorkerServiceName = "torpedo-linkedin-worker",
    [bool]$RestartServices = $true,
    [bool]$UseDocker = $false
)

$ErrorActionPreference = "Stop"

# Color output
function Write-Step { Write-Host $args -ForegroundColor Yellow }
function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Error { Write-Host $args -ForegroundColor Red }

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Write-Host "`n===== LinkedIn Automation Deployment =====" -ForegroundColor Cyan
Write-Host "Target: ${VMUser}@${VMHost}:${VMPath}" -ForegroundColor Cyan
Write-Host "Deployment Type: $(if ($UseDocker) { 'Docker' } else { 'Systemd Services' })" -ForegroundColor Cyan
Write-Host ""

# Step 1: Verify SSH connectivity
Write-Step "[1/7] Verifying SSH connection..."
try {
    ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${VMUser}@${VMHost}" "echo 'SSH OK'" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "SSH connection failed"
    }
    Write-Success "✓ SSH connection verified"
} catch {
    Write-Error "✗ Cannot connect to VM at ${VMHost}"
    Write-Host "  Please ensure:"
    Write-Host "  1. VM is running and accessible"
    Write-Host "  2. SSH key is configured"
    Write-Host "  3. Network access is available"
    exit 1
}

# Step 2: Create backup
Write-Step "[2/7] Creating backup on VM..."
$backupScript = @"
#!/bin/bash
set -e
cd ${VMPath}
BACKUP_DIR="backups/linkedin-\$(date +%Y%m%d_%H%M%S)"
mkdir -p \$BACKUP_DIR/backend/linkedin_automation
mkdir -p \$BACKUP_DIR/backend/tasks

# Backup LinkedIn module
[ -d backend/linkedin_automation ] && cp -r backend/linkedin_automation \$BACKUP_DIR/backend/ || true

# Backup LinkedIn tasks
[ -f backend/tasks/linkedin_tasks.py ] && cp backend/tasks/linkedin_tasks.py \$BACKUP_DIR/backend/tasks/ || true

# Backup systemd services
[ -d /etc/systemd/system ] && sudo mkdir -p \$BACKUP_DIR/systemd && \
  (sudo cp /etc/systemd/system/torpedo-linkedin*.service \$BACKUP_DIR/systemd/ 2>/dev/null || true)

echo "Backup created at \$BACKUP_DIR"
ls -la \$BACKUP_DIR
"@

ssh "${VMUser}@${VMHost}" "bash -s" <<< $backupScript
Write-Success "✓ Backup created successfully"

# Step 3: Deploy LinkedIn automation module
Write-Step "[3/7] Deploying LinkedIn automation module..."

# Create remote directories
ssh "${VMUser}@${VMHost}" "mkdir -p ${VMPath}/backend/linkedin_automation ${VMPath}/backend/tasks ${VMPath}/backend/routers"
Write-Host "  - Created remote directories"

# Deploy LinkedIn module files
$linkedInFiles = @(
    "linkedin_automation/__init__.py",
    "linkedin_automation/models.py",
    "linkedin_automation/service.py",
    "linkedin_automation/job.py",
    "linkedin_automation/router.py",
    "linkedin_automation/jobs_queue.py",
    "linkedin_automation/database.py",
    "tasks/linkedin_tasks.py"
)

foreach ($file in $linkedInFiles) {
    $sourcePath = Join-Path $projectRoot "backend" $file
    $remoteDir = Split-Path -Parent $file
    ssh "${VMUser}@${VMHost}" "mkdir -p ${VMPath}/backend/${remoteDir}"
    Write-Host "  - Uploading $file"
    scp -o StrictHostKeyChecking=no -q $sourcePath "${VMUser}@${VMHost}:${VMPath}/backend/${file}"
}

Write-Success "✓ LinkedIn automation module deployed"

# Step 4: Deploy configuration files
Write-Step "[4/7] Deploying configuration files..."

# Create environment file
$envFilePath = "/etc/torpedo/linkedin-automation.env"
$envCreateScript = @"
#!/bin/bash
[ -d /etc/torpedo ] || sudo mkdir -p /etc/torpedo
[ -f ${envFilePath} ] || sudo touch ${envFilePath}
sudo chmod 600 ${envFilePath}
echo "Environment file ready: ${envFilePath}"
"@

ssh "${VMUser}@${VMHost}" "bash -s" <<< $envCreateScript

# Copy environment template
scp -o StrictHostKeyChecking=no -q `
    "$projectRoot\vm_config\linkedin-automation.env.example" `
    "${VMUser}@${VMHost}:${VMPath}/vm_config/linkedin-automation.env.example"

Write-Host "  ✓ Environment file template deployed"
Write-Host "  - Configure /etc/torpedo/linkedin-automation.env on VM"

Write-Success "✓ Configuration files deployed"

# Step 5: Update main application files
Write-Step "[5/7] Updating main application files..."

# Deploy updated celery_app.py
scp -o StrictHostKeyChecking=no -q `
    "$projectRoot\backend\celery_app.py" `
    "${VMUser}@${VMHost}:${VMPath}/backend/celery_app.py"
Write-Host "  - Updated celery_app.py"

# Deploy updated main.py
scp -o StrictHostKeyChecking=no -q `
    "$projectRoot\backend\main.py" `
    "${VMUser}@${VMHost}:${VMPath}/backend/main.py"
Write-Host "  - Updated main.py"

Write-Success "✓ Application files updated"

# Step 6: Deploy systemd services (if not using Docker)
if (-not $UseDocker) {
    Write-Step "[6/7] Installing systemd services..."
    
    $systemdScript = @"
#!/bin/bash
set -e

echo "Installing systemd services..."

# Copy service files
sudo cp ${VMPath}/vm_config/systemd/torpedo-linkedin-beat.service /etc/systemd/system/
sudo cp ${VMPath}/vm_config/systemd/torpedo-linkedin-worker.service /etc/systemd/system/

# Set correct permissions
sudo chmod 644 /etc/systemd/system/torpedo-linkedin-*.service

# Reload systemd
sudo systemctl daemon-reload
echo "✓ Systemd services installed"

# Show status
echo ""
echo "Service status:"
sudo systemctl status torpedo-linkedin-beat --no-pager || true
sudo systemctl status torpedo-linkedin-worker --no-pager || true
"@

    ssh "${VMUser}@${VMHost}" "bash -s" <<< $systemdScript
    Write-Success "✓ Systemd services installed"
} else {
    Write-Step "[6/7] Using Docker deployment..."
    Write-Host "  - Docker-compose will handle service deployment"
    Write-Host "  - Ensure docker-compose.yml includes linkedin_automation services"
    Write-Success "✓ Docker deployment ready"
}

# Step 7: Restart services
Write-Step "[7/7] Finalizing deployment..."

if ($RestartServices) {
    if ($UseDocker) {
        Write-Host "  - Restarting Docker containers..."
        $restartScript = @"
#!/bin/bash
cd ${VMPath}
docker-compose restart celery-beat celery-worker
docker-compose restart backend
echo "Services restarted"
"@
    } else {
        Write-Host "  - Enabling and starting systemd services..."
        $restartScript = @"
#!/bin/bash
sudo systemctl enable torpedo-linkedin-beat.service --now
sudo systemctl enable torpedo-linkedin-worker.service --now
sleep 3
echo ""
echo "Service Status:"
sudo systemctl status torpedo-linkedin-beat --no-pager
echo ""
sudo systemctl status torpedo-linkedin-worker --no-pager
"@
    }
    
    ssh "${VMUser}@${VMHost}" "bash -s" <<< $restartScript
    Write-Success "✓ Services restarted"
} else {
    Write-Host "  - Services will start on next boot"
}

Write-Success "`n===== Deployment Complete =====" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. SSH to VM: ssh ${VMUser}@${VMHost}"
Write-Host "2. Configure environment: sudo nano /etc/torpedo/linkedin-automation.env"
Write-Host "   - Set LINKEDIN_ENCRYPTION_KEY"
Write-Host "   - Set MongoDB and Redis credentials"
Write-Host "3. View logs:"
if ($UseDocker) {
    Write-Host "   docker-compose logs -f celery-beat"
} else {
    Write-Host "   sudo journalctl -u torpedo-linkedin-beat -f"
}
Write-Host "4. Add LinkedIn accounts via API:"
Write-Host "   POST /api/marketing/linkedin/accounts"
Write-Host ""
