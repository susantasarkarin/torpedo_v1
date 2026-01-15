#!/usr/bin/env python3
import requests

print("Testing Gemini classification...")
r = requests.post(
    "http://localhost:8000/gemini/classify-batch-sync", 
    json={"limit": 3}
)
print("Status:", r.status_code)
print("Response:", r.text[:2000])
