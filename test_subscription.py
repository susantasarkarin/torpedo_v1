#!/usr/bin/env python3
"""Test script to create Cint webhook subscription"""
import requests
import json
import sys

data = {
    "callback_url": "https://surveyieldwork.com/api/cint/webhooks/opportunities",
    "include_quotas": True,
    "payload_max_size_mb": 10,
    "payload_max_survey_count": 1000,  # Min: 1000
    "send_interval_seconds": 30,  # Max: 30
    "opportunities_filters": []
}

print("Attempting to create Cint webhook subscription...")
print(f"Callback URL: {data['callback_url']}")

try:
    response = requests.post(
        "http://localhost:8000/api/cint/subscription/opportunities",
        json=data,
        headers={"Content-Type": "application/json"},
        timeout=10
    )
    
    print(f"\nResponse Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    
    if response.status_code == 200:
        print("\n✅ Subscription created successfully!")
    else:
        print("\n❌ Subscription creation failed")
        sys.exit(1)
        
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
