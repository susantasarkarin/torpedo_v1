#!/usr/bin/env python3
import requests

resp = requests.post(
    "http://localhost:8000/gemini/classify",
    json={
        "email_id": "test123",
        "subject": "Test email",
        "body_plain": "Hello, I am looking to buy your product. My name is John Doe and I work at ACME Corp. You can reach me at john@acme.com",
        "sender_email": "john@acme.com"
    }
)
print("Status:", resp.status_code)
print("Response:", resp.json())
