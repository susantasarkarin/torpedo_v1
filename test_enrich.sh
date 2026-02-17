#!/bin/bash
curl -s -X POST http://127.0.0.1:8000/operations/potential-clients/enrich \
  -H "Content-Type: application/json" \
  -d '{"company_name": "2Logical", "force_refresh": false}'
