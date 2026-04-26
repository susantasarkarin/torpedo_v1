#!/bin/bash
SID=$(curl -s -X POST http://localhost:8000/login/ -H 'Content-Type: application/json' -d @/tmp/login.json | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))")
echo "Session: $SID"
echo "Test 1 (should be cached):"
time curl -s -o /dev/null -w 'HTTP %{http_code} in %{time_total}s\n' -H "Authorization: $SID" 'http://localhost:8000/api/traffic/dashboard-stats?days=7'
echo "Test 2 (cached):"
time curl -s -o /dev/null -w 'HTTP %{http_code} in %{time_total}s\n' -H "Authorization: $SID" 'http://localhost:8000/api/traffic/dashboard-stats?days=7'
