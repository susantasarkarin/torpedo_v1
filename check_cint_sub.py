#!/usr/bin/env python3
import requests
import json
import warnings
warnings.filterwarnings('ignore')

api_key = "C61C48A6-8154-4F9F-B616-8DFB66F452A7"
supplier_code = "6777"
base_url = "https://api.samplicio.us"

# Get current subscription
url = f"{base_url}/supply/opportunities/v1/subscriptions/{supplier_code}"
headers = {"Authorization": f"Bearer {api_key}"}

response = requests.get(url, headers=headers, verify=False)
print(f"Status: {response.status_code}")
data = response.json()
print(f"\nCallback URL in Cint: {data.get('callback')}")
print(f"Webhook Security Public Key: {data.get('public_key')[:50]}...")
print(f"Key ID: {data.get('key_id')}")
