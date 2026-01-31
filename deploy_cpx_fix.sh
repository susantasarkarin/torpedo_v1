#!/bin/bash
# CPX Logging Fix - Production Deployment Script
# Usage: bash deploy_cpx_fix.sh <target-vm> [--restart]

set -e  # Exit on error

TARGET_VM="${1:?Error: No target VM specified. Usage: bash deploy_cpx_fix.sh <vm-ip-or-host> [--restart]}"
RESTART_FLAG="${2:-}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}CPX Callback Logging Fix - Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Target VM: $TARGET_VM"
echo "Restart after deploy: $([ "$RESTART_FLAG" = "--restart" ] && echo "YES" || echo "NO (manual restart required)")"
echo ""

# Step 1: Backup
echo -e "${YELLOW}[1/4] Backing up current main.py on target VM...${NC}"
ssh "campaign_admin@$TARGET_VM" << 'EOF'
    set -e
    BACKUP_PATH="/home/campaign_admin/backups/main.py.backup.$(date +%Y%m%d_%H%M%S)"
    mkdir -p /home/campaign_admin/backups
    cp /home/campaign_admin/campaign_backend/backend/main.py "$BACKUP_PATH"
    echo "✅ Backup created: $BACKUP_PATH"
EOF

# Step 2: Copy fixed file
echo -e "${YELLOW}[2/4] Copying fixed main.py to target VM...${NC}"
scp "backend/main.py" "campaign_admin@$TARGET_VM:/home/campaign_admin/campaign_backend/backend/main.py"
echo "✅ File uploaded successfully"

# Step 3: Verify syntax
echo -e "${YELLOW}[3/4] Verifying Python syntax on target VM...${NC}"
ssh "campaign_admin@$TARGET_VM" << 'EOF'
    cd /home/campaign_admin/campaign_backend
    python3 -m py_compile backend/main.py
    if [ $? -eq 0 ]; then
        echo "✅ Syntax validation passed"
    else
        echo "❌ Syntax validation failed!"
        exit 1
    fi
EOF

# Step 4: Restart (optional)
if [ "$RESTART_FLAG" = "--restart" ]; then
    echo -e "${YELLOW}[4/4] Restarting backend service...${NC}"
    ssh "campaign_admin@$TARGET_VM" << 'EOF'
        sudo systemctl restart campaign_backend
        sleep 3
        
        # Check if service started successfully
        if sudo systemctl is-active --quiet campaign_backend; then
            echo "✅ Backend service restarted successfully"
            
            # Show startup logs
            echo ""
            echo "Startup logs (last 20 lines):"
            sudo journalctl -u campaign_backend -n 20 --no-pager
        else
            echo "❌ Backend service failed to start!"
            exit 1
        fi
EOF
else
    echo -e "${YELLOW}[4/4] Manual restart required${NC}"
    echo "On the production VM, run:"
    echo "  sudo systemctl restart campaign_backend"
fi

echo ""
echo -e "${GREEN}✅ DEPLOYMENT COMPLETE${NC}"
echo ""
echo "Verification steps:"
echo "  1. Check logs: ssh campaign_admin@$TARGET_VM 'sudo journalctl -u campaign_backend -f'"
echo "  2. Test endpoint: curl 'http://$TARGET_VM:8000/cpx-response?msg=test&sfwid=TEST123'"
echo "  3. Query database: mongo traffic_flow_db --eval 'db.cpx_callback_logs.countDocuments()'"
echo ""
