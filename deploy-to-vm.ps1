# VM Deployment Script for Windows
# Run this script to deploy changes to the VM

Write-Host "🚀 Starting VM Deployment..." -ForegroundColor Cyan
Write-Host ""

# VM Configuration
$VM_IP = "139.59.32.72"
$VM_USER = "root"
$PROJECT_PATH = "/home/susanta/campaign_platform"

Write-Host "📋 Deployment Configuration:" -ForegroundColor Yellow
Write-Host "   VM IP: $VM_IP"
Write-Host "   User: $VM_USER"
Write-Host "   Project Path: $PROJECT_PATH"
Write-Host ""

# Step 1: Pull latest code
Write-Host "📥 Step 1: Pulling latest code from GitHub..." -ForegroundColor Green
$pullCmd = "cd $PROJECT_PATH/backend; git pull origin main"
ssh ${VM_USER}@${VM_IP} $pullCmd

if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ Code pulled successfully" -ForegroundColor Green
}
else {
    Write-Host "   ❌ Failed to pull code" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 2: Install dependencies
Write-Host "📦 Step 2: Installing Python dependencies..." -ForegroundColor Green
$pipCmd = "cd $PROJECT_PATH/backend; pip install -r requirements.txt"
ssh ${VM_USER}@${VM_IP} $pipCmd

if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ Dependencies installed" -ForegroundColor Green
}
else {
    Write-Host "   ⚠️  Warning: Dependency installation had issues (may be okay if no new deps)" -ForegroundColor Yellow
}
Write-Host ""

# Step 3: Restart backend
Write-Host "🔄 Step 3: Restarting backend service..." -ForegroundColor Green
$restartCmd = "pm2 restart campaign-backend"
ssh ${VM_USER}@${VM_IP} $restartCmd

if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ Backend restarted successfully" -ForegroundColor Green
}
else {
    Write-Host "   ❌ Failed to restart backend" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 4: Check status
Write-Host "📊 Step 4: Checking backend status..." -ForegroundColor Green
$statusCmd = "pm2 status campaign-backend"
ssh ${VM_USER}@${VM_IP} $statusCmd
Write-Host ""

# Step 5: View recent logs
Write-Host "📝 Step 5: Viewing recent logs..." -ForegroundColor Green
$logsCmd = "pm2 logs campaign-backend --lines 30 --nostream"
ssh ${VM_USER}@${VM_IP} $logsCmd
Write-Host ""

Write-Host "✅ Deployment Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "🧪 Next Steps:" -ForegroundColor Cyan
Write-Host "   1. Test parsing page: https://torpedo.cogentixresearch.com/takesurvey?vid=1234`&cc=US`&rid=12345"
Write-Host "   2. Verify manual click is required (no auto-click)"
Write-Host "   3. Check survey allocation in logs"
Write-Host "   4. Test Survey Pool active filter"
Write-Host ""
Write-Host "📋 Useful Commands:" -ForegroundColor Yellow
Write-Host "   View logs:    ssh ${VM_USER}@${VM_IP} 'pm2 logs campaign-backend'"
Write-Host "   Check status: ssh ${VM_USER}@${VM_IP} 'pm2 status'"
Write-Host "   Restart:      ssh ${VM_USER}@${VM_IP} 'pm2 restart campaign-backend'"
Write-Host ""
