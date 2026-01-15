#!/usr/bin/env python3
import requests

resp = requests.post(
    "http://localhost:8000/gemini/classify-batch-sync",
    json={"limit": 3}
)
print("Status:", resp.status_code)
import json
print("Response:", json.dumps(resp.json(), indent=2))
