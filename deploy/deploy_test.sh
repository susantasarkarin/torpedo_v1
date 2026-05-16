#!/bin/bash
set -e
cd /var/www/campaign_platform
git pull

# Kill old backend
PIDS=$(ps aux | grep 'uvicorn main:app.*8000' | grep -v grep | awk '{print $2}')
if [ -n "$PIDS" ]; then
  echo "Killing PIDs: $PIDS"
  kill $PIDS 2>/dev/null || true
  sleep 3
fi

# Start with single worker to save memory
cd backend
nohup venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 >> /var/log/torpedo-backend.log 2>&1 &
echo "Backend restarted with PID $!"
echo "Waiting 25s for startup..."
sleep 25

# Test login
python3 -c "import json; open('/tmp/login.json','w').write(json.dumps({'username':'admin','password':'password123'}))"
SID=$(curl -s -X POST http://localhost:8000/login/ -H 'Content-Type: application/json' -d @/tmp/login.json | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))")
echo "Session: $SID"

if [ -n "$SID" ]; then
  echo "Testing traffic dashboard-stats..."
  time curl -s -o /tmp/traffic_result.json -w 'HTTP %{http_code} in %{time_total}s\n' -H "Authorization: $SID" 'http://localhost:8000/api/traffic/dashboard-stats?days=7'
  echo "Result preview:"
  python3 -c "import json; d=json.load(open('/tmp/traffic_result.json')); print('total:', d.get('total')); print('by_status:', d.get('by_status')); print('daily_count:', len(d.get('daily',[])));" 2>/dev/null || cat /tmp/traffic_result.json | head -c 500

  echo ""
  echo "Testing rfq..."
  time curl -s -o /dev/null -w 'HTTP %{http_code} in %{time_total}s\n' -H "Authorization: $SID" 'http://localhost:8000/api/rfq/'

  echo ""
  echo "Testing operations recent-activity..."
  time curl -s -o /dev/null -w 'HTTP %{http_code} in %{time_total}s\n' -H "Authorization: $SID" 'http://localhost:8000/api/operations/recent-activity'
else
  echo "Login failed!"
fi
