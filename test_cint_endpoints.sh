#!/bin/bash

# Test Cint Integration Endpoints

BASE_URL="http://localhost:8000"
API_BASE="$BASE_URL/api/cint"

echo "=== Testing Cint Integration Endpoints ==="
echo ""

# Test 1: Health check
echo "1. Testing /api/cint/health"
curl -s -X GET "$API_BASE/health" | jq . || echo "FAILED"
echo ""

# Test 2: List opportunities
echo "2. Testing /api/cint/opportunities"
curl -s -X GET "$API_BASE/opportunities?limit=5" | jq . || echo "FAILED"
echo ""

# Test 3: Test webhook (POST without signature for now)
echo "3. Testing /api/cint/webhooks/opportunities"
curl -s -X POST "$API_BASE/webhooks/opportunities" \
  -H "Content-Type: application/json" \
  -d '{
    "survey_id": 123456,
    "survey_name": "Test Survey",
    "country_language": "eng_us",
    "bid_length_of_interview": 15,
    "revenue_per_interview": {"value": 1.50, "currency_code": "USD"},
    "total_remaining": 100,
    "is_live": true,
    "message_reason": "new"
  }' | jq . || echo "FAILED"
echo ""

# Test 4: Build entry link URL
echo "4. Testing /api/cint/build-entry-link/123456"
curl -s -X POST "$API_BASE/build-entry-link/123456?respondent_id=RESP123&country_code=us" | jq . || echo "FAILED"
echo ""

echo "=== Tests Complete ==="
