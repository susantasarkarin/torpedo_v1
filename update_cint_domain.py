#!/usr/bin/env python3
import requests
import json
import warnings
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

api_key = "C61C48A6-8154-4F9F-B616-8DFB66F452A7"
supplier_code = "6777"
base_url = "https://api.samplicio.us"

# Update subscription with correct domain callback
payload = {
    "callback": "https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities",
    "payload_max_survey_count": 1000,
    "send_interval_seconds": 30,
    "payload_max_size_mb": 10,
    "include_quotas": True,
    "opportunities": [
        {
            "country_language": {
                "in": ["eng_us", "eng_gb", "eng_ca", "eng_au"]
            }
        }
    ]
}

url = f"{base_url}/supply/opportunities/v1/subscriptions/{supplier_code}"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

print(f"Updating Cint subscription with callback URL: {payload['callback']}")
response = requests.post(url, json=payload, headers=headers, verify=False)
print(f"Status: {response.status_code}")
print(f"Response: {json.dumps(response.json(), indent=2)}")
