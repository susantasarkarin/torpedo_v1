#!/bin/bash
# Deployment script for Cint Integration fixes to torpedo.cogentixresearch.com

set -e  # Exit on any error

# Configuration
VM_HOST="torpedo.cogentixresearch.com"
VM_USER="${VM_USER:-root}"  # Set VM_USER environment variable or defaults to root
VM_PATH="${VM_PATH:-/var/www/torpedo/backend}"  # Set VM_PATH or use default
SERVICE_NAME="${SERVICE_NAME:-torpedo-backend}"  # systemd service name

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Cint Integration Deployment ===${NC}"
echo "Target: ${VM_USER}@${VM_HOST}:${VM_PATH}"
echo ""

# Check if SSH key is configured
echo -e "${YELLOW}[1/6] Checking SSH connection...${NC}"
if ! ssh -o ConnectTimeout=5 "${VM_USER}@${VM_HOST}" "echo 'SSH connection successful'" 2>/dev/null; then
    echo -e "${RED}Error: Cannot connect to VM. Please check:${NC}"
    echo "  1. VM_USER and VM_HOST are correct"
    echo "  2. SSH key is configured"
    echo "  3. VM is accessible"
    exit 1
fi
echo -e "${GREEN}✓ SSH connection verified${NC}"

# Backup existing files on VM
echo -e "${YELLOW}[2/6] Creating backup on VM...${NC}"
ssh "${VM_USER}@${VM_HOST}" "
    cd ${VM_PATH}
    BACKUP_DIR=\"backups/\$(date +%Y%m%d_%H%M%S)\"
    mkdir -p \$BACKUP_DIR/app/routers
    mkdir -p \$BACKUP_DIR/app/services

    # Backup files we're about to modify
    [ -f app/routers/cint.py ] && cp app/routers/cint.py \$BACKUP_DIR/app/routers/
    [ -f app/services/cint_service.py ] && cp app/services/cint_service.py \$BACKUP_DIR/app/services/

    echo \"Backup created at \$BACKUP_DIR\"
"
echo -e "${GREEN}✓ Backup created${NC}"

# Deploy modified files
echo -e "${YELLOW}[3/6] Deploying modified files...${NC}"

LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "  - Deploying backend/app/routers/cint.py"
scp "${LOCAL_DIR}/backend/app/routers/cint.py" \
    "${VM_USER}@${VM_HOST}:${VM_PATH}/app/routers/cint.py"

echo "  - Deploying backend/app/services/cint_service.py"
scp "${LOCAL_DIR}/backend/app/services/cint_service.py" \
    "${VM_USER}@${VM_HOST}:${VM_PATH}/app/services/cint_service.py"

echo -e "${GREEN}✓ Files deployed${NC}"

# Deploy documentation files (optional)
echo -e "${YELLOW}[4/6] Deploying documentation files...${NC}"
ssh "${VM_USER}@${VM_HOST}" "mkdir -p ${VM_PATH}/docs"

scp "${LOCAL_DIR}/CINT_STATUS_REPORT.md" \
    "${LOCAL_DIR}/CINT_DIAGNOSTIC_GUIDE.md" \
    "${LOCAL_DIR}/CINT_INTEGRATION_COMPLETE.md" \
    "${LOCAL_DIR}/CINT_INTEGRATION_FIXES.md" \
    "${LOCAL_DIR}/DEPLOYMENT_CHECKLIST.md" \
    "${VM_USER}@${VM_HOST}:${VM_PATH}/docs/" 2>/dev/null || echo "  (Documentation upload optional - skipped)"

echo -e "${GREEN}✓ Documentation deployed${NC}"

# Restart backend service
echo -e "${YELLOW}[5/6] Restarting backend service...${NC}"
ssh "${VM_USER}@${VM_HOST}" "
    # Try systemd first
    if systemctl is-active --quiet ${SERVICE_NAME}; then
        echo 'Restarting via systemd...'
        sudo systemctl restart ${SERVICE_NAME}
        sleep 3
        sudo systemctl status ${SERVICE_NAME} --no-pager
    # Try supervisorctl
    elif command -v supervisorctl &> /dev/null; then
        echo 'Restarting via supervisor...'
        supervisorctl restart torpedo || supervisorctl restart all
    # Try docker-compose
    elif [ -f docker-compose.yml ]; then
        echo 'Restarting via docker-compose...'
        docker-compose restart backend
    else
        echo '${RED}Warning: Could not detect service manager. Please restart manually.${NC}'
        exit 1
    fi
"
echo -e "${GREEN}✓ Service restarted${NC}"

# Verify deployment
echo -e "${YELLOW}[6/6] Verifying deployment...${NC}"
sleep 5  # Wait for service to fully start

echo "  - Testing diagnostic endpoint..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "https://${VM_HOST}/api/cint/diagnostic")

if [ "$RESPONSE" = "200" ]; then
    echo -e "${GREEN}✓ Diagnostic endpoint responding (HTTP 200)${NC}"
    echo ""
    echo -e "${GREEN}=== Deployment Successful! ===${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Check diagnostic output:"
    echo "     curl https://${VM_HOST}/api/cint/diagnostic | jq"
    echo ""
    echo "  2. Monitor webhook activity:"
    echo "     ssh ${VM_USER}@${VM_HOST} 'tail -f /var/log/torpedo/backend.log | grep \"Received opportunities webhook\"'"
    echo ""
    echo "  3. Check entry link debug logs:"
    echo "     ssh ${VM_USER}@${VM_HOST} 'tail -f /var/log/torpedo/backend.log | grep \"ENTRY LINK DEBUG\"'"
    echo ""
    echo "  4. Review full diagnostics guide: ${VM_PATH}/docs/CINT_DIAGNOSTIC_GUIDE.md"
else
    echo -e "${RED}✗ Diagnostic endpoint returned HTTP ${RESPONSE} (expected 200)${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check service logs:"
    echo "     ssh ${VM_USER}@${VM_HOST} 'journalctl -u ${SERVICE_NAME} -n 50'"
    echo ""
    echo "  2. Check if service is running:"
    echo "     ssh ${VM_USER}@${VM_HOST} 'systemctl status ${SERVICE_NAME}'"
    echo ""
    echo "  3. Check application logs:"
    echo "     ssh ${VM_USER}@${VM_HOST} 'tail -100 /var/log/torpedo/backend.log'"
fi
