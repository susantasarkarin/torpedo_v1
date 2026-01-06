#!/bin/bash

# Auto-pull script for campaign_platform with auto-deployment
REPO_DIR="/var/www/campaign_platform"
LOG_FILE="$HOME/auto_pull.log"

cd $REPO_DIR || exit 1

# Fetch latest from remote
git fetch origin main --quiet

# Get local and remote commit hashes
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] New commits detected. Pulling..." >> $LOG_FILE
    git pull origin main >> $LOG_FILE 2>&1
    
    # Rebuild frontend
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rebuilding frontend..." >> $LOG_FILE
    cd $REPO_DIR/Campaign_platform
    npm run build >> $LOG_FILE 2>&1
    
    # Copy to web server directory
    sudo rm -rf /var/www/html/assets
    sudo cp -r $REPO_DIR/Campaign_platform/dist/* /var/www/html/
    sudo chown -R www-data:www-data /var/www/html
    
    # Restart backend
    sudo systemctl restart campaign-backend
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deployment complete. Now at: $(git rev-parse --short HEAD)" >> $LOG_FILE
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No new commits." >> $LOG_FILE
fi
