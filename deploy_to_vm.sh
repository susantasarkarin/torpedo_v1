#!/bin/bash
# Quick VM Deployment Script
# Usage: bash deploy_to_vm.sh [vm-host] [vm-user] [vm-path]

VM_HOST="${1:-campaign-vm.eastus.cloudapp.azure.com}"
VM_USER="${2:-azureuser}"
VM_PATH="${3:-/home/azureuser/campaign_platform}"

echo "========================================"
echo "🚀 Traffic Dashboard Deployment"
echo "========================================"
echo "VM: $VM_HOST"
echo "User: $VM_USER"
echo "Path: $VM_PATH"
echo ""

# Step 1: SSH and pull changes
echo "📍 Step 1: Pulling latest changes from GitHub..."
ssh "$VM_USER@$VM_HOST" << 'EOF'
cd $VM_PATH
git pull origin fix/cint-waterfall-async || git pull origin main
echo "✅ Git pull completed"
EOF

# Step 2: Rebuild frontend
echo ""
echo "📍 Step 2: Building frontend..."
ssh "$VM_USER@$VM_HOST" << 'EOF'
cd $VM_PATH/Campaign_platform
npm install
npm run build
echo "✅ Frontend build completed"
EOF

# Step 3: Restart services
echo ""
echo "📍 Step 3: Restarting services..."
ssh "$VM_USER@$VM_HOST" << 'EOF'
cd $VM_PATH

# Try docker-compose
if [ -f "docker-compose.yml" ]; then
    echo "Restarting via docker-compose..."
    docker-compose restart backend frontend
# Try systemd
elif systemctl is-active --quiet campaign-backend; then
    echo "Restarting via systemd..."
    sudo systemctl restart campaign-backend
else
    echo "⚠️ Could not determine service manager"
fi

sleep 3
echo "✅ Services restarted"
EOF

# Step 4: Verify
echo ""
echo "📍 Step 4: Verifying deployment..."
echo ""
echo "✅ Deployment Complete!"
echo ""
echo "📋 Next Steps:"
echo "  1. Check frontend: http://$VM_HOST:5173"
echo "  2. Check backend: curl http://$VM_HOST:5000/api/health"
echo "  3. Verify Traffic Dashboard: http://$VM_HOST:5173/operations"
echo "  4. Check logs: ssh $VM_USER@$VM_HOST 'docker-compose logs -f backend'"
echo ""
