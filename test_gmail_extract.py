#!/usr/bin/env python3
"""Test Gmail extraction endpoint"""
import requests
import json

response = requests.post(
    'http://localhost:8000/leads/emails/extract',
    json={
        'account_emails': ['indira@surveyfieldwork.com'],
        'max_emails': 1000
    }
)

print(f"Status: {response.status_code}")
print(json.dumps(response.json(), indent=2))
