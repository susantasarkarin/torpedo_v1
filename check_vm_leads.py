#!/usr/bin/env python3
"""Check leads on VM - run via SSH"""
from pymongo import MongoClient
from datetime import datetime, timedelta

client = MongoClient()
db = client["email_automation"]
cutoff = datetime.utcnow() - timedelta(hours=24)
total = db.leads_raw.count_documents({"source": "google_search"})
recent = db.leads_raw.count_documents({"source": "google_search", "created_at": {"$gte": cutoff}})
print(f"Total google_search leads: {total}")
print(f"Last 24 hours: {recent}")
