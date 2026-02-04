#!/usr/bin/env python3
import os
from pymongo import MongoClient

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client["cint"]
settings = db["settings"]
sub = settings.find_one({"_id": "opportunities_subscription"})

if sub:
    print("Subscription found:")
    print(f"  callback_url: {sub.get('callback_url')}")
    print(f"  subscription_id: {sub.get('subscription_id')}")
    print(f"  status: {sub.get('status')}")
    print(f"  created_at: {sub.get('created_at')}")
    print(f"  error_count: {sub.get('error_count', 0)}")
    if sub.get('last_error'):
        print(f"  last_error: {sub.get('last_error')}")
else:
    print("No subscription found - webhook not configured!")
    print("This means Cint cannot push opportunities to the platform")
