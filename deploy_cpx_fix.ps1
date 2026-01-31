# CPX Logging Fix - Production Deployment Script (PowerShell)
# Usage: .\deploy_cpx_fix.ps1 -TargetVM <vm-ip-or-host> [-Restart] [-SSHKey <path>]

param(
    [Parameter(Mandatory=$true)]
    [string]$TargetVM,
    
    [switch]$Restart,
    
    [string]$SSHKey = "$env:USERPROFILE\.ssh\id_rsa",
    
    [string]$RemoteUser = "campaign_admin"
)

$ErrorActionPreference = "Stop"

# Colors
$Green = "`e[32m"
$Yellow = "`e[33m"
$Red = "`e[31m"
$Reset = "`e[0m"

Write-Host "$Green========================================$Reset"
Write-Host "$Green CPX Callback Logging Fix - Deployment$Reset"
Write-Host "$Green========================================$Reset"
Write-Host ""
Write-Host "Target VM: $TargetVM"
Write-Host "Remote User: $RemoteUser"
Write-Host "Restart after deploy: $(if ($Restart) { 'YES' } else { 'NO (manual restart required)' })"
Write-Host ""

# Verify SSH connectivity
Write-Host "$Yellow[0/4] Verifying SSH connectivity...${Reset}"
try {
    ssh -o ConnectTimeout=5 "${RemoteUser}@${TargetVM}" "echo 'SSH connection successful'" | Out-Null
    Write-Host "$Green✅ SSH connection successful$Reset"
} catch {
    Write-Host "$Red❌ Cannot connect to VM. Verify:$Reset"
    Write-Host "  - VM hostname/IP: $TargetVM"
    Write-Host "  - SSH key: $SSHKey"
    Write-Host "  - Network connectivity"
    exit 1
}

# Step 1: Backup
Write-Host "$Yellow[1/4] Backing up current main.py on target VM...$Reset"
$BackupCmd = @'
    $BackupPath = "/home/campaign_admin/backups/main.py.backup.$(date +%Y%m%d_%H%M%S)"
    mkdir -p /home/campaign_admin/backups
    cp /home/campaign_admin/campaign_backend/backend/main.py "$BackupPath"
    echo "✅ Backup created: $BackupPath"
'@

ssh "${RemoteUser}@${TargetVM}" $BackupCmd | ForEach-Object { Write-Host $_ }

# Step 2: Copy fixed file
Write-Host "$Yellow[2/4] Copying fixed main.py to target VM...$Reset"
$LocalFile = "backend\main.py"
$RemotePath = "${RemoteUser}@${TargetVM}:/home/campaign_admin/campaign_backend/backend/main.py"

if (-Not (Test-Path $LocalFile)) {
    Write-Host "$Red❌ Error: File not found: $LocalFile$Reset"
    exit 1
}

scp $LocalFile $RemotePath
Write-Host "$Green✅ File uploaded successfully$Reset"

# Step 3: Verify syntax
Write-Host "$Yellow[3/4] Verifying Python syntax on target VM...$Reset"
$VerifyCmd = @'
    cd /home/campaign_admin/campaign_backend
    python3 -m py_compile backend/main.py
    if [ $? -eq 0 ]; then
        echo "✅ Syntax validation passed"
    else
        echo "❌ Syntax validation failed!"
        exit 1
    fi
'@

try {
    ssh "${RemoteUser}@${TargetVM}" $VerifyCmd | ForEach-Object { Write-Host $_ }
} catch {
    Write-Host "$Red❌ Syntax validation failed!$Reset"
    exit 1
}

# Step 4: Restart (optional)
if ($Restart) {
    Write-Host "$Yellow[4/4] Restarting backend service...$Reset"
    $RestartCmd = @'
        sudo systemctl restart campaign_backend
        sleep 3
        
        if sudo systemctl is-active --quiet campaign_backend; then
            echo "✅ Backend service restarted successfully"
            echo ""
            echo "Startup logs (last 20 lines):"
            sudo journalctl -u campaign_backend -n 20 --no-pager
        else
            echo "❌ Backend service failed to start!"
            exit 1
        fi
'@
    
    ssh "${RemoteUser}@${TargetVM}" $RestartCmd | ForEach-Object { Write-Host $_ }
} else {
    Write-Host "$Yellow[4/4] Manual restart required$Reset"
    Write-Host "On the production VM, run:"
    Write-Host "  sudo systemctl restart campaign_backend"
}

Write-Host ""
Write-Host "$Green✅ DEPLOYMENT COMPLETE$Reset"
Write-Host ""
Write-Host "Verification steps:"
Write-Host "  1. Check logs:"
Write-Host "     ssh ${RemoteUser}@${TargetVM} 'sudo journalctl -u campaign_backend -f'"
Write-Host ""
Write-Host "  2. Test endpoint:"
Write-Host "     curl 'http://${TargetVM}:8000/cpx-response?msg=test&sfwid=TEST123'"
Write-Host ""
Write-Host "  3. Query database:"
Write-Host "     mongo traffic_flow_db --eval 'db.cpx_callback_logs.countDocuments()'"
Write-Host ""
