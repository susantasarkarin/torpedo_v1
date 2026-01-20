#!/bin/bash

# ===========================================
# VM Setup Script for SurveyFieldwork.com
# Run this script on a fresh Ubuntu 22.04+ VM
# ===========================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== SurveyFieldwork.com VM Setup ===${NC}"

# Update system
echo -e "${YELLOW}Updating system packages...${NC}"
sudo apt update && sudo apt upgrade -y

# Install Node.js 20.x
echo -e "${YELLOW}Installing Node.js 20.x...${NC}"
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install PM2 globally
echo -e "${YELLOW}Installing PM2...${NC}"
sudo npm install -g pm2

# Install Nginx
echo -e "${YELLOW}Installing Nginx...${NC}"
sudo apt install -y nginx

# Install Certbot for SSL
echo -e "${YELLOW}Installing Certbot...${NC}"
sudo apt install -y certbot python3-certbot-nginx

# Install Git
echo -e "${YELLOW}Installing Git...${NC}"
sudo apt install -y git

# Create web directory
echo -e "${YELLOW}Creating web directories...${NC}"
sudo mkdir -p /var/www/surveyfieldwork-nextjs
sudo mkdir -p /var/www/certbot
sudo chown -R $USER:$USER /var/www/surveyfieldwork-nextjs

# Clone the repository
echo -e "${YELLOW}Cloning repository...${NC}"
git clone https://github.com/sristi3227/campaign_platform.git /tmp/campaign_platform
cp -r /tmp/campaign_platform/websites/surveyfieldwork-nextjs/* /var/www/surveyfieldwork-nextjs/
rm -rf /tmp/campaign_platform

# Install dependencies and build
echo -e "${YELLOW}Installing dependencies and building...${NC}"
cd /var/www/surveyfieldwork-nextjs
npm ci
npm run build

# Setup PM2
echo -e "${YELLOW}Setting up PM2...${NC}"
pm2 start ecosystem.config.js --env production
pm2 save
pm2 startup

# Copy Nginx config
echo -e "${YELLOW}Configuring Nginx...${NC}"
sudo cp nginx.conf /etc/nginx/sites-available/surveyfieldwork.com
sudo ln -sf /etc/nginx/sites-available/surveyfieldwork.com /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test Nginx config
sudo nginx -t

# Get SSL certificate
echo -e "${YELLOW}Obtaining SSL certificate...${NC}"
echo -e "${RED}Make sure your domain DNS is pointing to this server first!${NC}"
read -p "Press enter to continue with SSL setup (or Ctrl+C to skip)..."
sudo certbot --nginx -d surveyfieldwork.com -d www.surveyfieldwork.com

# Reload Nginx
sudo systemctl reload nginx

# Setup automatic certificate renewal
echo -e "${YELLOW}Setting up automatic SSL renewal...${NC}"
echo "0 12 * * * /usr/bin/certbot renew --quiet" | sudo crontab -

# Enable services on boot
sudo systemctl enable nginx

echo -e "${GREEN}=== Setup Complete! ===${NC}"
echo ""
echo -e "${GREEN}Your website should now be running at:${NC}"
echo "  https://surveyfieldwork.com"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Update /var/www/surveyfieldwork-nextjs/.env.local with production values"
echo "2. Restart PM2: pm2 restart all"
echo ""
echo -e "${YELLOW}Useful commands:${NC}"
echo "  pm2 status           - Check process status"
echo "  pm2 logs             - View application logs"
echo "  pm2 restart all      - Restart all processes"
echo "  sudo nginx -t        - Test Nginx config"
echo "  sudo systemctl reload nginx - Reload Nginx"
