#!/bin/bash
cd /var/www/campaign_platform
git fetch origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): Updates found, pulling..." >> /var/log/campaign_pull.log
    git pull origin main >> /var/log/campaign_pull.log 2>&1
    pm2 restart all 2>/dev/null
    echo "$(date): Services restarted" >> /var/log/campaign_pull.log
else
    echo "$(date): No updates" >> /var/log/campaign_pull.log
fi
