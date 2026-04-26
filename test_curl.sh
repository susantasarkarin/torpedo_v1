#!/bin/bash
curl -s -m 60 -X POST http://localhost:8000/api/cold-outreach/campaigns/a981bdcd-fbd5-497a-8522-e886e9c2f57c/steps/1/test \
  -H "Content-Type: application/json" \
  -d '{"recipient_email": "susantasarkar7447@gmail.com"}' 2>&1
echo ""
echo "EXIT_CODE=$?"
