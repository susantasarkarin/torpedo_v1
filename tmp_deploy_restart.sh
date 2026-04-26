#!/bin/bash
pkill -f bulk_segregate 2>/dev/null
sleep 1
cd /var/www/campaign_platform
git pull origin fix/cint-waterfall-async
systemctl restart torpedo-backend
sleep 2
cd /var/www/campaign_platform/backend
nohup ./venv/bin/python /tmp/bulk_segregate.py > /tmp/bulk_segregate.log 2>&1 &
echo "started_pid=$!"
