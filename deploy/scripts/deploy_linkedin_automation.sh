#!/bin/bash
# LinkedIn Automation Deployment Script for Torpedo VM
# Usage: ./deploy_linkedin_automation.sh [-h HOST] [-u USER] [-p PATH]

set -e

# Default values
VM_HOST="${VM_HOST:-139.59.32.72}"
VM_USER="${VM_USER:-root}"
VM_PATH="${VM_PATH:-/var/www/torpedo}"
USE_DOCKER="${USE_DOCKER:-false}"
RESTART_SERVICES="${RESTART_SERVICES:-true}"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--host) VM_HOST="$2"; shift 2 ;;
        -u|--user) VM_USER="$2"; shift 2 ;;
        -p|--path) VM_PATH="$2"; shift 2 ;;
        -d|--docker) USE_DOCKER=true; shift ;;
        -no-restart) RESTART_SERVICES=false; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}===== LinkedIn Automation Deployment =====${NC}"
echo -e "Target: ${VM_USER}@${VM_HOST}:${VM_PATH}"
echo -e "Deployment Type: $([ "$USE_DOCKER" = "true" ] && echo "Docker" || echo "Systemd Services")"
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Step 1: Verify SSH
echo -e "${YELLOW}[1/7] Verifying SSH connection...${NC}"
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${VM_USER}@${VM_HOST}" "echo 'SSH OK'" &>/dev/null; then
    echo -e "${GREEN}✓ SSH connection verified${NC}"
else
    echo -e "${RED}✗ Cannot connect to VM${NC}"
    exit 1
fi

# Step 2: Create backup
echo -e "${YELLOW}[2/7] Creating backup on VM...${NC}"
ssh "${VM_USER}@${VM_HOST}" bash << 'BACKUP_EOF'
set -e
cd /var/www/torpedo
BACKUP_DIR="backups/linkedin-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR/backend/linkedin_automation"
mkdir -p "$BACKUP_DIR/backend/tasks"

[ -d backend/linkedin_automation ] && cp -r backend/linkedin_automation "$BACKUP_DIR/backend/" || true
[ -f backend/tasks/linkedin_tasks.py ] && cp backend/tasks/linkedin_tasks.py "$BACKUP_DIR/backend/tasks/" || true

echo "Backup created at $BACKUP_DIR"
BACKUP_EOF
echo -e "${GREEN}✓ Backup created${NC}"

# Step 3: Deploy files
echo -e "${YELLOW}[3/7] Deploying LinkedIn automation module...${NC}"

FILES=(
    "backend/linkedin_automation/__init__.py"
    "backend/linkedin_automation/models.py"
    "backend/linkedin_automation/service.py"
    "backend/linkedin_automation/job.py"
    "backend/linkedin_automation/router.py"
    "backend/linkedin_automation/jobs_queue.py"
    "backend/linkedin_automation/database.py"
    "backend/tasks/linkedin_tasks.py"
)

ssh "${VM_USER}@${VM_HOST}" "mkdir -p ${VM_PATH}/backend/linkedin_automation ${VM_PATH}/backend/tasks"

for file in "${FILES[@]}"; do
    echo "  - Uploading $file"
    scp -o StrictHostKeyChecking=no -q "$PROJECT_ROOT/$file" "${VM_USER}@${VM_HOST}:${VM_PATH}/$file"
done

echo -e "${GREEN}✓ Module deployed${NC}"

# Step 4: Deploy configuration
echo -e "${YELLOW}[4/7] Deploying configuration files...${NC}"

ssh "${VM_USER}@${VM_HOST}" bash << 'CONFIG_EOF'
[ -d /etc/torpedo ] || sudo mkdir -p /etc/torpedo
[ -f /etc/torpedo/linkedin-automation.env ] || sudo touch /etc/torpedo/linkedin-automation.env
sudo chmod 600 /etc/torpedo/linkedin-automation.env
echo "Environment file ready"
CONFIG_EOF

scp -o StrictHostKeyChecking=no -q \
    "$PROJECT_ROOT/vm_config/linkedin-automation.env.example" \
    "${VM_USER}@${VM_HOST}:${VM_PATH}/vm_config/linkedin-automation.env.example"

echo -e "${GREEN}✓ Configuration deployed${NC}"

# Step 5: Update application files
echo -e "${YELLOW}[5/7] Updating application files...${NC}"

scp -o StrictHostKeyChecking=no -q "$PROJECT_ROOT/backend/celery_app.py" \
    "${VM_USER}@${VM_HOST}:${VM_PATH}/backend/celery_app.py"
echo "  - Updated celery_app.py"

scp -o StrictHostKeyChecking=no -q "$PROJECT_ROOT/backend/main.py" \
    "${VM_USER}@${VM_HOST}:${VM_PATH}/backend/main.py"
echo "  - Updated main.py"

echo -e "${GREEN}✓ Application files updated${NC}"

# Step 6: Deploy services
echo -e "${YELLOW}[6/7] Setting up services...${NC}"

if [ "$USE_DOCKER" = "false" ]; then
    echo "Installing systemd services..."
    
    ssh "${VM_USER}@${VM_HOST}" bash << 'SERVICE_EOF'
set -e
sudo cp /var/www/torpedo/vm_config/systemd/torpedo-linkedin-beat.service /etc/systemd/system/
sudo cp /var/www/torpedo/vm_config/systemd/torpedo-linkedin-worker.service /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/torpedo-linkedin-*.service
sudo systemctl daemon-reload
echo "✓ Systemd services installed"
SERVICE_EOF
    
    echo -e "${GREEN}✓ Systemd services installed${NC}"
else
    echo "Docker deployment: Update docker-compose.yml if needed"
    echo -e "${GREEN}✓ Docker ready${NC}"
fi

# Step 7: Restart services
echo -e "${YELLOW}[7/7] Finalizing deployment...${NC}"

if [ "$RESTART_SERVICES" = "true" ]; then
    if [ "$USE_DOCKER" = "false" ]; then
        ssh "${VM_USER}@${VM_HOST}" bash << 'RESTART_EOF'
sudo systemctl enable torpedo-linkedin-beat.service --now
sudo systemctl enable torpedo-linkedin-worker.service --now
sleep 3
echo ""
echo "Service Status:"
sudo systemctl status torpedo-linkedin-beat --no-pager
echo ""
sudo systemctl status torpedo-linkedin-worker --no-pager
RESTART_EOF
    else
        ssh "${VM_USER}@${VM_HOST}" "cd ${VM_PATH} && docker-compose restart celery-beat celery-worker backend"
    fi
    echo -e "${GREEN}✓ Services restarted${NC}"
fi

echo ""
echo -e "${GREEN}===== Deployment Complete =====${NC}"
echo ""
echo -e "${CYAN}Next Steps:${NC}"
echo "1. SSH to VM: ssh ${VM_USER}@${VM_HOST}"
echo "2. Configure environment: sudo nano /etc/torpedo/linkedin-automation.env"
echo "3. View logs:"
if [ "$USE_DOCKER" = "true" ]; then
    echo "   docker-compose logs -f celery-beat"
else
    echo "   sudo journalctl -u torpedo-linkedin-beat -f"
fi
echo "4. Add LinkedIn accounts via API:"
echo "   POST /api/marketing/linkedin/accounts"
echo ""
