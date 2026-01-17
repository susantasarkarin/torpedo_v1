#!/bin/bash
echo "Starting full sync of 15000 emails..."
curl -s --max-time 7200 -X POST "http://localhost:8000/gmail-ws/mailboxes/696a4b0d3bac0fd584c6c72f/sync" \
  -H "Content-Type: application/json" \
  -d '{"full_sync": true, "max_results": 15000}'
echo ""
echo "Sync complete!"
