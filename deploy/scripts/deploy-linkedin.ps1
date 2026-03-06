#!/usr/bin/env pwsh
# LinkedIn Automation Deployment for VM
# Usage: .\deploy-linkedin-automation.ps1

param(
    [string]$VMHost = "139.59.32.72",
    [string]$VMUser = "root",
    [string]$VMPath = "/var/www/torpedo"
)

$projectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

Write-Host ""
Write-Host "===== LinkedIn Automation Deployment =====" -ForegroundColor Cyan
Write-Host "Target: ${VMUser}@${VMHost}:${VMPath}" -ForegroundColor Yellow
Write-Host ""

# Step 1: SSH Check
Write-Host "[1/5] Checking SSH connection..." -ForegroundColor Yellow
try {
    ssh -o ConnectTimeout=5 "${VMUser}@${VMHost}" "echo Connected" | Out-Null
    Write-Host "OK: SSH connection verified" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Cannot connect to ${VMHost}" -ForegroundColor Red
    exit 1
}

# Step 2: Backup
Write-Host "[2/5] Creating backup..." -ForegroundColor Yellow
ssh "${VMUser}@${VMHost}" "cd ${VMPath} && mkdir -p backups && tar -czf backups/linkedin-\$(date +%s).tar.gz backend/linkedin_automation backend/tasks/linkedin_tasks.py 2>/dev/null || echo 'First deployment'" | Out-Null
Write-Host "OK: Backup created" -ForegroundColor Green

# Step 3: Deploy Module
Write-Host "[3/5] Deploying module files..." -ForegroundColor Yellow
ssh "${VMUser}@${VMHost}" "mkdir -p ${VMPath}/backend/linkedin_automation ${VMPath}/backend/tasks" | Out-Null

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

foreach ($file in $files) {
    $src = Join-Path $projectRoot $file
    scp -o StrictHostKeyChecking=no -q $src "${VMUser}@${VMHost}:${VMPath}/${file}"
}

Write-Host "OK: Module files deployed" -ForegroundColor Green

# Step 4: Update App Files
Write-Host "[4/5] Updating application files..." -ForegroundColor Yellow
scp -o StrictHostKeyChecking=no -q "$projectRoot\backend\celery_app.py" "${VMUser}@${VMHost}:${VMPath}/backend/"
scp -o StrictHostKeyChecking=no -q "$projectRoot\backend\main.py" "${VMUser}@${VMHost}:${VMPath}/backend/"
Write-Host "OK: Application files updated" -ForegroundColor Green

# Step 5: Deploy Config
Write-Host "[5/5] Deploying configuration..." -ForegroundColor Yellow
ssh "${VMUser}@${VMHost}" "mkdir -p ${VMPath}/vm_config/systemd" | Out-Null
scp -o StrictHostKeyChecking=no -q "$projectRoot\vm_config\systemd\torpedo-linkedin-beat.service" "${VMUser}@${VMHost}:${VMPath}/vm_config/systemd/"
scp -o StrictHostKeyChecking=no -q "$projectRoot\vm_config\systemd\torpedo-linkedin-worker.service" "${VMUser}@${VMHost}:${VMPath}/vm_config/systemd/"
scp -o StrictHostKeyChecking=no -q "$projectRoot\vm_config\linkedin-automation.env.example" "${VMUser}@${VMHost}:${VMPath}/vm_config/"
Write-Host "OK: Configuration deployed" -ForegroundColor Green

# Summary
Write-Host ""
Write-Host "✓ DEPLOYMENT COMPLETE" -ForegroundColor Green
Write-Host ""
Write-Host "NEXT STEPS:" -ForegroundColor Cyan
Write-Host "1. SSH to VM: ssh ${VMUser}@${VMHost}"
Write-Host "2. Generate encryption key:"
Write-Host "   python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
Write-Host "3. Edit config: sudo nano /etc/torpedo/linkedin-automation.env"
Write-Host "4. Copy service files:"
Write-Host "   sudo cp ${VMPath}/vm_config/systemd/*.service /etc/systemd/system/"
Write-Host "   sudo systemctl daemon-reload"
Write-Host "5. Start services:"
Write-Host "   sudo systemctl enable torpedo-linkedin-beat.service --now"
Write-Host "   sudo systemctl enable torpedo-linkedin-worker.service --now"
Write-Host "6. Check status: sudo systemctl status torpedo-linkedin-beat" -ForegroundColor White
Write-Host ""
