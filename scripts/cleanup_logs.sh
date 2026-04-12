#!/bin/bash
# Log cleanup script for campaign_platform VM
# Truncates large logs, vacuums journal, flushes PM2 logs, and deletes old rotated logs

# Truncate MongoDB log if > 100MB
MONGO_LOG="/var/log/mongodb/mongod.log"
if [ -f "$MONGO_LOG" ]; then
  size=$(stat -c%s "$MONGO_LOG")
  if [ "$size" -gt $((100*1024*1024)) ]; then
    echo "Truncating $MONGO_LOG (was $((size/1024/1024)) MB)"
    cat /dev/null > "$MONGO_LOG"
  fi
fi

# Vacuum systemd journal to 500MB
journalctl --vacuum-size=500M

# Flush PM2 logs
if command -v pm2 >/dev/null 2>&1; then
  pm2 flush
fi

# Truncate app logs if > 50MB
APP_LOG="/var/log/campaign_platform/backend.log"
if [ -f "$APP_LOG" ]; then
  size=$(stat -c%s "$APP_LOG")
  if [ "$size" -gt $((50*1024*1024)) ]; then
    echo "Truncating $APP_LOG (was $((size/1024/1024)) MB)"
    cat /dev/null > "$APP_LOG"
  fi
fi

# Delete old rotated/compressed logs
find /var/log -type f \( -name '*.gz' -o -name '*.1' -o -name '*.old' \) -delete

# Optionally, rotate nginx logs
if [ -f /var/log/nginx/access.log ]; then
  cat /dev/null > /var/log/nginx/access.log
fi
if [ -f /var/log/nginx/error.log ]; then
  cat /dev/null > /var/log/nginx/error.log
fi

echo "Log cleanup complete: $(date)"