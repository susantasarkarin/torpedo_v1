#!/bin/bash
SID="ImFkbWluIg.adX47Q.RyVRmAfNwbqpXCr6SRvZp4N5cWY"
echo "Testing traffic dashboard-stats..."
time curl -s -w '\nHTTP %{http_code} in %{time_total}s\n' -H "Authorization: $SID" 'http://localhost:8000/api/traffic/dashboard-stats?days=7' 2>&1 | tail -n 5
echo "---"
echo "Testing recent-activity..."
time curl -s -w '\nHTTP %{http_code} in %{time_total}s\n' -H "Authorization: $SID" 'http://localhost:8000/api/operations/recent-activity' 2>&1 | tail -n 5
echo "---"
echo "Testing rfq..."
time curl -s -w '\nHTTP %{http_code} in %{time_total}s\n' -H "Authorization: $SID" 'http://localhost:8000/api/rfq/' 2>&1 | tail -n 5
