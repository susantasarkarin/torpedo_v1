#!/bin/bash
##
# VM Connection Script - Get Last Cint Respondent Payloads
#
# This script connects to the VM via SSH and retrieves the last N
# respondent payloads sent to Cint.
#
# Usage:
#   ./scripts/vm_get_cint_payloads.sh [limit]
#
# Examples:
#   ./scripts/vm_get_cint_payloads.sh       # Get last 10 payloads (default)
#   ./scripts/vm_get_cint_payloads.sh 20    # Get last 20 payloads
##

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
LIMIT=${1:-10}
SCRIPT_TYPE="${2:-auto}"  # auto, python, or js

# VM Configuration - Update these values for your VM
VM_USER="${VM_USER:-root}"
VM_HOST="${VM_HOST:-your-vm-host}"
VM_PATH="${VM_PATH:-/root/campaign_platform}"

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Cint Payload Retrieval Tool${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# Check if VM_HOST is configured
if [ "$VM_HOST" == "your-vm-host" ]; then
    echo -e "${RED}Error: VM_HOST not configured${NC}"
    echo ""
    echo "Please set the VM_HOST environment variable:"
    echo "  export VM_HOST=your-actual-vm-host.com"
    echo ""
    echo "Or edit this script and update the VM_HOST variable."
    echo ""
    echo "Optional environment variables:"
    echo "  VM_USER  - SSH user (default: root)"
    echo "  VM_PATH  - Path to campaign_platform on VM (default: /root/campaign_platform)"
    exit 1
fi

echo -e "${YELLOW}Configuration:${NC}"
echo "  VM Host: $VM_HOST"
echo "  VM User: $VM_USER"
echo "  VM Path: $VM_PATH"
echo "  Limit:   $LIMIT payloads"
echo ""

# Test SSH connection
echo -e "${YELLOW}[1/3] Testing SSH connection...${NC}"
if ! ssh -o ConnectTimeout=5 "${VM_USER}@${VM_HOST}" "echo 'Connected'" 2>/dev/null | grep -q "Connected"; then
    echo -e "${RED}Error: Cannot connect to VM${NC}"
    echo ""
    echo "Please check:"
    echo "  1. VM_HOST is correct: $VM_HOST"
    echo "  2. VM_USER is correct: $VM_USER"
    echo "  3. SSH key is configured for passwordless access"
    echo "  4. VM is accessible from your network"
    echo ""
    echo "Test connection manually:"
    echo "  ssh ${VM_USER}@${VM_HOST}"
    exit 1
fi
echo -e "${GREEN}✓ SSH connection successful${NC}"
echo ""

# Determine which script to use
echo -e "${YELLOW}[2/3] Detecting available runtime...${NC}"
if [ "$SCRIPT_TYPE" == "auto" ]; then
    # Auto-detect: try Python first, then Node.js
    if ssh "${VM_USER}@${VM_HOST}" "command -v python3 >/dev/null 2>&1"; then
        SCRIPT_TYPE="python"
        echo -e "${GREEN}✓ Python3 detected${NC}"
    elif ssh "${VM_USER}@${VM_HOST}" "command -v node >/dev/null 2>&1"; then
        SCRIPT_TYPE="js"
        echo -e "${GREEN}✓ Node.js detected${NC}"
    else
        echo -e "${RED}Error: Neither Python3 nor Node.js found on VM${NC}"
        exit 1
    fi
else
    echo -e "${BLUE}Using specified runtime: $SCRIPT_TYPE${NC}"
fi
echo ""

# Execute the script on VM
echo -e "${YELLOW}[3/3] Retrieving Cint payloads from VM...${NC}"
echo ""

if [ "$SCRIPT_TYPE" == "python" ]; then
    ssh "${VM_USER}@${VM_HOST}" "cd ${VM_PATH} && python3 scripts/get_last_cint_payloads.py --limit ${LIMIT}"
else
    ssh "${VM_USER}@${VM_HOST}" "cd ${VM_PATH} && node scripts/get_last_cint_payloads.js ${LIMIT}"
fi

SSH_EXIT_CODE=$?

echo ""
if [ $SSH_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Successfully retrieved payloads${NC}"
else
    echo -e "${RED}✗ Error retrieving payloads (exit code: $SSH_EXIT_CODE)${NC}"
    exit $SSH_EXIT_CODE
fi
