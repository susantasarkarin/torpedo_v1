#!/usr/bin/env python3
"""Quick test: send a test email via the cold outreach API."""
import urllib.request, json, sys

data = json.dumps({"recipient_email": "susantasarkar7447@gmail.com"}).encode()
url = "http://localhost:8000/api/cold-outreach/campaigns/a981bdcd-fbd5-497a-8522-e886e9c2f57c/steps/1/test"

req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
try:
    resp = urllib.request.urlopen(req, timeout=30)
    print(resp.read().decode())
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}")
    sys.exit(1)
