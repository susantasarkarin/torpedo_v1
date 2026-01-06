#!/bin/bash

# Auto-pull script for campaign_platform
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
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pull complete. Now at: $(git rev-parse --short HEAD)" >> $LOG_FILE
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No new commits." >> $LOG_FILE
fi
