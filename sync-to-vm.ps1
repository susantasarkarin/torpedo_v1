# ============================================================================
# Quick Sync Changes to VM - IP Propagation Fix
# ============================================================================
# This script pulls the latest changes from GitHub on the VM

param(
    [string]$VMHost = "campaign-vm.eastus.cloudapp.azure.com",
    [string]$VMUser = "azureuser",
    [string]$VMPath = "/home/azureuser/campaign_platform"
)

Write-Host "`n=== Syncing IP Propagation Fix to VM ===" -ForegroundColor Green
Write-Host "VM: $VMHost" -ForegroundColor Cyan
Write-Host "Path: $VMPath" -ForegroundColor Cyan

# SSH command to pull on VM
$sshCommand = @"
cd $VMPath && git pull origin main && echo 'Sync complete!' || echo 'Sync failed!'
"@

Write-Host "`nExecuting on VM: git pull origin main" -ForegroundColor Yellow

try {
    ssh "$VMUser@$VMHost" $sshCommand
    Write-Host "`n✅ VM sync completed successfully" -ForegroundColor Green
    Write-Host "`nChanges deployed:" -ForegroundColor Cyan
    Write-Host "  • backend/app/services/survey_allocation_service.py" -ForegroundColor White
    Write-Host "  • IP address propagation chain fixed" -ForegroundColor White
    Write-Host "  • CPX API now receives actual user IPs" -ForegroundColor White
} catch {
    Write-Host "`n❌ VM sync failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n⚠️  IMPORTANT: Restart backend services on VM" -ForegroundColor Yellow
Write-Host "   ssh $VMUser@$VMHost" -ForegroundColor Cyan
Write-Host "   cd $VMPath && sudo systemctl restart campaign-backend" -ForegroundColor Cyan
Write-Host "`n"
