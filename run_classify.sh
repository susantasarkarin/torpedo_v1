#!/bin/bash
curl -s --max-time 900 -X POST "http://localhost:8000/gemini/classify-batch-sync" \
  -H "Content-Type: application/json" \
  -d '{"limit": 100}'
