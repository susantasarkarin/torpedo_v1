#!/bin/bash

# ===========================================
# SurveyFieldwork.com Deployment Script
# ===========================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="surveyfieldwork-website"
APP_DIR="/var/www/surveyfieldwork-nextjs"
REPO_URL="git@github.com:YOUR_USERNAME/surveyfieldwork-nextjs.git"  # Update this
BRANCH="main"

echo -e "${GREEN}=== Starting Deployment ===${NC}"

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check for required tools
echo -e "${YELLOW}Checking requirements...${NC}"
for cmd in git node npm pm2; do
    if ! command_exists $cmd; then
        echo -e "${RED}Error: $cmd is not installed${NC}"
        exit 1
    fi
done

echo -e "${GREEN}✓ All requirements met${NC}"

# Create app directory if it doesn't exist
if [ ! -d "$APP_DIR" ]; then
    echo -e "${YELLOW}Creating application directory...${NC}"
    sudo mkdir -p $APP_DIR
    sudo chown $USER:$USER $APP_DIR
fi

# Clone or pull the repository
if [ ! -d "$APP_DIR/.git" ]; then
    echo -e "${YELLOW}Cloning repository...${NC}"
    git clone $REPO_URL $APP_DIR
    cd $APP_DIR
else
    echo -e "${YELLOW}Pulling latest changes...${NC}"
    cd $APP_DIR
    git fetch origin
    git reset --hard origin/$BRANCH
fi

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
npm ci --only=production

# Build the application
echo -e "${YELLOW}Building application...${NC}"
npm run build

# Copy environment file if it doesn't exist
if [ ! -f "$APP_DIR/.env.local" ]; then
    echo -e "${YELLOW}Creating .env.local from example...${NC}"
    cp $APP_DIR/.env.example $APP_DIR/.env.local
    echo -e "${RED}⚠ Please update .env.local with your production values${NC}"
fi

# Restart PM2
echo -e "${YELLOW}Restarting PM2 process...${NC}"
pm2 stop $APP_NAME 2>/dev/null || true
pm2 delete $APP_NAME 2>/dev/null || true
pm2 start ecosystem.config.js --env production
pm2 save

echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo -e "${GREEN}Website is now running at http://localhost:3001${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Update .env.local with production values"
echo "2. Configure Nginx reverse proxy"
echo "3. Set up SSL certificate with Let's Encrypt"
