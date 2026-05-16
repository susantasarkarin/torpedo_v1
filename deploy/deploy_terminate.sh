#!/bin/bash
set -e
cd /var/www/campaign_platform
git pull

# Restart backend
PIDS=$(ps aux | grep 'uvicorn main:app.*8000' | grep -v grep | awk '{print $2}')
if [ -n "$PIDS" ]; then
  echo "Killing backend PIDs: $PIDS"
  kill $PIDS 2>/dev/null || true
  sleep 3
fi
cd backend
nohup venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 >> /var/log/torpedo-backend.log 2>&1 &
echo "Backend restarted with PID $!"

# Rebuild frontend
echo "Rebuilding frontend..."
cd /var/www/campaign_platform/Campaign_platform
npm run build 2>&1 | tail -5
echo "Frontend built."

echo "Waiting 25s for backend startup..."
sleep 25
echo "Done. Backend and frontend deployed."
