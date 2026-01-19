#!/usr/bin/env python3
import requests

try:
    r = requests.post(
        'http://127.0.0.1:8000/login/', 
        json={'username': 'admin', 'password': 'password123'},
        timeout=10
    )
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
except Exception as e:
    print(f"Error: {e}")
