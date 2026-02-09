@echo off
REM Deployment batch file for Cint Integration
echo === Cint Integration Deployment ===
echo.

echo [Step 1/5] Testing SSH connection...
ssh root@torpedo.cogentixresearch.com "echo SSH connection successful"
if %errorlevel% neq 0 (
    echo ERROR: SSH connection failed. Please check your SSH key setup.
    pause
    exit /b 1
)
echo SUCCESS: SSH connected
echo.

echo [Step 2/5] Creating backup on VM...
ssh root@torpedo.cogentixresearch.com "cd /var/www/torpedo/backend && BACKUP_DIR=backups/$(date +%%Y%%m%%d_%%H%%M%%S) && mkdir -p $BACKUP_DIR/app/routers $BACKUP_DIR/app/services && [ -f app/routers/cint.py ] && cp app/routers/cint.py $BACKUP_DIR/app/routers/ || true && [ -f app/services/cint_service.py ] && cp app/services/cint_service.py $BACKUP_DIR/app/services/ || true && echo Backup created at $BACKUP_DIR"
echo SUCCESS: Backup created
echo.

echo [Step 3/5] Deploying cint.py...
scp "backend\app\routers\cint.py" root@torpedo.cogentixresearch.com:/var/www/torpedo/backend/app/routers/cint.py
if %errorlevel% neq 0 (
    echo ERROR: Failed to deploy cint.py
    pause
    exit /b 1
)
echo SUCCESS: cint.py deployed
echo.

echo [Step 4/5] Deploying cint_service.py...
scp "backend\app\services\cint_service.py" root@torpedo.cogentixresearch.com:/var/www/torpedo/backend/app/services/cint_service.py
if %errorlevel% neq 0 (
    echo ERROR: Failed to deploy cint_service.py
    pause
    exit /b 1
)
echo SUCCESS: cint_service.py deployed
echo.

echo [Step 5/5] Restarting backend service...
ssh root@torpedo.cogentixresearch.com "sudo systemctl restart torpedo-backend && sleep 3 && systemctl status torpedo-backend --no-pager | head -20"
echo SUCCESS: Service restarted
echo.

echo Waiting 5 seconds for service to start...
timeout /t 5 /nobreak >nul
echo.

echo [Verification] Testing diagnostic endpoint...
curl -s https://torpedo.cogentixresearch.com/api/cint/diagnostic
echo.
echo.

echo === DEPLOYMENT COMPLETE ===
echo.
echo Next steps:
echo 1. Check the diagnostic output above
echo 2. Look for "surveys.total" - if ^> 0, inventories are downloading
echo 3. Look for "entry_links.with_live_link" - if ^> 0, entry links have live_link
echo.
echo To monitor webhook activity:
echo   ssh root@torpedo.cogentixresearch.com "tail -f /var/log/torpedo/backend.log | grep 'Received opportunities webhook'"
echo.
pause
