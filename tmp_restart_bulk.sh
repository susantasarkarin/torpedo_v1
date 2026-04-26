#!/bin/bash
# Kill old bulk_segregate process
pkill -f bulk_segregate 2>/dev/null
sleep 1
# Update the script to use new code path
cd /var/www/campaign_platform/backend
nohup ./venv/bin/python /tmp/bulk_segregate.py > /tmp/bulk_segregate.log 2>&1 &
echo "started_pid=$!"
