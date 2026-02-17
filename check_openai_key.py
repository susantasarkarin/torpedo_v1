#!/usr/bin/env python3
from pymongo import MongoClient
import os

c = MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017/"))
s = c.torpedo_settings.app_settings.find_one({"_id": "app_config"})

if s and s.get("openai_api_key"):
    key = s.get("openai_api_key")
    print(f"Key exists: True")
    print(f"Key prefix: {key[:20]}...")
    print(f"Key length: {len(key)}")
else:
    print("Key exists: False")
    print("Checking email_automation.app_settings...")
    s2 = c.email_automation.app_settings.find_one()
    if s2:
        print(f"email_automation.app_settings keys: {list(s2.keys())}")
