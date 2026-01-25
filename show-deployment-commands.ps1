# Simple VM Deployment Commands
# Copy and paste these commands one by one into your terminal

Write-Host "=" -NoNewline; for ($i = 0; $i -lt 60; $i++) { Write-Host "=" -NoNewline }; Write-Host ""
Write-Host "VM DEPLOYMENT COMMANDS - Copy and Paste Each Command"
Write-Host "=" -NoNewline; for ($i = 0; $i -lt 60; $i++) { Write-Host "=" -NoNewline }; Write-Host ""
Write-Host ""

Write-Host "STEP 1: SSH into VM" -ForegroundColor Cyan
Write-Host "ssh root@139.59.32.72"
Write-Host ""

Write-Host "STEP 2: Navigate to project (try these paths)" -ForegroundColor Cyan
Write-Host "cd /var/www/campaign_platform"
Write-Host "# OR"
Write-Host "cd /home/susanta/campaign_platform"
Write-Host "# OR"
Write-Host "cd /root/campaign_platform"
Write-Host ""

Write-Host "STEP 3: Pull latest code" -ForegroundColor Cyan
Write-Host "git pull origin main"
Write-Host ""

Write-Host "STEP 4: Navigate to backend" -ForegroundColor Cyan
Write-Host "cd backend"
Write-Host ""

Write-Host "STEP 5: Install dependencies" -ForegroundColor Cyan
Write-Host "pip install -r requirements.txt"
Write-Host ""

Write-Host "STEP 6: Restart backend" -ForegroundColor Cyan
Write-Host "pm2 restart campaign-backend"
Write-Host ""

Write-Host "STEP 7: Check status" -ForegroundColor Cyan
Write-Host "pm2 status"
Write-Host ""

Write-Host "STEP 8: View logs" -ForegroundColor Cyan
Write-Host "pm2 logs campaign-backend --lines 50"
Write-Host ""

Write-Host "=" -NoNewline; for ($i = 0; $i -lt 60; $i++) { Write-Host "=" -NoNewline }; Write-Host ""
Write-Host "ALTERNATIVE: Run all commands at once" -ForegroundColor Yellow
Write-Host "=" -NoNewline; for ($i = 0; $i -lt 60; $i++) { Write-Host "=" -NoNewline }; Write-Host ""
Write-Host ""
Write-Host 'ssh root@139.59.32.72 "cd /var/www/campaign_platform && git pull origin main && cd backend && pip install -r requirements.txt && pm2 restart campaign-backend && pm2 status"'
Write-Host ""
Write-Host "OR if project is in different location:"
Write-Host ""
Write-Host 'ssh root@139.59.32.72 "cd /home/susanta/campaign_platform && git pull origin main && cd backend && pip install -r requirements.txt && pm2 restart campaign-backend && pm2 status"'
Write-Host ""

Write-Host "=" -NoNewline; for ($i = 0; $i -lt 60; $i++) { Write-Host "=" -NoNewline }; Write-Host ""
Write-Host "After deployment, test the parsing page:" -ForegroundColor Green
Write-Host "https://torpedo.cogentixresearch.com/takesurvey?vid=1234&cc=US&rid=12345"
Write-Host "=" -NoNewline; for ($i = 0; $i -lt 60; $i++) { Write-Host "=" -NoNewline }; Write-Host ""
