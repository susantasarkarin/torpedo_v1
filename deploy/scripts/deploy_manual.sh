#!/bin/bash
# Manual SSH Deployment Commands for Cint Integration
# Run these commands step by step

set -e

echo "=== Cint Integration - Manual Deployment ==="
echo ""
echo "Follow these steps to deploy to your VM:"
echo ""

# Step 1: Test SSH connection
echo "STEP 1: Test SSH Connection"
echo "----------------------------"
echo "Command to run:"
echo '  ssh root@torpedo.cogentixresearch.com "echo Connected successfully"'
echo ""
read -p "Press Enter after you've verified SSH connection works..."
echo ""

# Step 2: Create backup on VM
echo "STEP 2: Create Backup on VM"
echo "----------------------------"
echo "Run this command to backup existing files:"
cat << 'EOF'
ssh root@torpedo.cogentixresearch.com "
cd /var/www/torpedo/backend
BACKUP_DIR=\"backups/\$(date +%Y%m%d_%H%M%S)\"
mkdir -p \$BACKUP_DIR/app/routers
mkdir -p \$BACKUP_DIR/app/services
[ -f app/routers/cint.py ] && cp app/routers/cint.py \$BACKUP_DIR/app/routers/
[ -f app/services/cint_service.py ] && cp app/services/cint_service.py \$BACKUP_DIR/app/services/
echo Backup created at \$BACKUP_DIR
"
EOF
echo ""
read -p "Press Enter after backup is created..."
echo ""

# Step 3: Deploy cint.py
echo "STEP 3: Deploy backend/app/routers/cint.py"
echo "-------------------------------------------"
LOCAL_PATH="$(cd "$(dirname "$0")" && pwd)"
echo "Command to run:"
echo "  scp \"${LOCAL_PATH}/backend/app/routers/cint.py\" root@torpedo.cogentixresearch.com:/var/www/torpedo/backend/app/routers/cint.py"
echo ""
read -p "Press Enter after file is copied..."
echo ""

# Step 4: Deploy cint_service.py
echo "STEP 4: Deploy backend/app/services/cint_service.py"
echo "----------------------------------------------------"
echo "Command to run:"
echo "  scp \"${LOCAL_PATH}/backend/app/services/cint_service.py\" root@torpedo.cogentixresearch.com:/var/www/torpedo/backend/app/services/cint_service.py"
echo ""
read -p "Press Enter after file is copied..."
echo ""

# Step 5: Restart service
echo "STEP 5: Restart Backend Service"
echo "--------------------------------"
echo "Run this command to restart the service:"
cat << 'EOF'
ssh root@torpedo.cogentixresearch.com "
if systemctl is-active --quiet torpedo-backend; then
    echo 'Restarting via systemd...'
    sudo systemctl restart torpedo-backend
    sleep 3
    sudo systemctl status torpedo-backend --no-pager
elif command -v supervisorctl &> /dev/null; then
    echo 'Restarting via supervisor...'
    supervisorctl restart torpedo
else
    echo 'Please restart your backend service manually'
fi
"
EOF
echo ""
read -p "Press Enter after service is restarted..."
echo ""

# Step 6: Verify deployment
echo "STEP 6: Verify Deployment"
echo "-------------------------"
echo "Wait 5 seconds for service to start..."
sleep 5
echo ""
echo "Testing diagnostic endpoint..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" https://torpedo.cogentixresearch.com/api/cint/diagnostic)

if [ "$RESPONSE" = "200" ]; then
    echo "✓ SUCCESS! Diagnostic endpoint is working (HTTP 200)"
    echo ""
    echo "Now checking diagnostic data..."
    curl -s https://torpedo.cogentixresearch.com/api/cint/diagnostic | python -m json.tool || \
    curl -s https://torpedo.cogentixresearch.com/api/cint/diagnostic | jq '.'
else
    echo "✗ WARNING: Diagnostic endpoint returned HTTP $RESPONSE"
    echo "Check service logs: ssh root@torpedo.cogentixresearch.com 'journalctl -u torpedo-backend -n 50'"
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Next steps:"
echo "1. Check diagnostic output above"
echo "2. Monitor webhook activity:"
echo "   ssh root@torpedo.cogentixresearch.com 'tail -f /var/log/torpedo/backend.log | grep \"Received opportunities webhook\"'"
echo ""
echo "3. Check entry link debug logs:"
echo "   ssh root@torpedo.cogentixresearch.com 'tail -f /var/log/torpedo/backend.log | grep \"ENTRY LINK DEBUG\"'"
