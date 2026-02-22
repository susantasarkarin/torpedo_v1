param(
    [string]$VMHost = "139.59.32.72",
    [string]$VMUser = "root"
)

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Deploying Traffic Dashboard to VM" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "VM: $VMHost" -ForegroundColor Yellow
Write-Host ""

Write-Host "Executing deployment..." -ForegroundColor Magenta

$cmd = 'cd /var/www/torpedo 2>/dev/null || cd /home/aioutreach/app 2>/dev/null || cd /root/campaign_platform 2>/dev/null; pwd; git pull origin fix/cint-waterfall-async 2>/dev/null || git pull origin main 2>/dev/null; if [ -d Campaign_platform ]; then cd Campaign_platform && npm install >/dev/null 2>&1 && npm run build >/dev/null 2>&1 && cd ..; fi; if [ -f docker-compose.yml ]; then docker-compose restart backend frontend 2>/dev/null; fi; sleep 2; echo "[DONE]"'

ssh -o ConnectTimeout=60 -o StrictHostKeyChecking=no $VMUser@$VMHost $cmd

Write-Host ""
Write-Host "Deployment Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Access your application:" -ForegroundColor Cyan
Write-Host "  Frontend: http://$VMHost`:5173" -ForegroundColor White
Write-Host "  Backend:  http://$VMHost`:5000" -ForegroundColor White
Write-Host "  Dashboard: http://$VMHost`:5173/operations" -ForegroundColor White
