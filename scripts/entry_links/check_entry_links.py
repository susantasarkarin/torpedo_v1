#!/usr/bin/env python3
"""Quick script to check entry link data in MongoDB"""
from pymongo import MongoClient
import json
from bson.regex import Regex

client = MongoClient('mongodb://localhost:27017/')
db = client['traffic_flow_db']

# Get sample entry links
print("=== SAMPLE ENTRY LINKS ===")
samples = list(db.cint_entry_links.find({}, {'_id': 0}).limit(3))
for i, sample in enumerate(samples, 1):
    print(f"\n--- Entry Link {i} ---")
    print(json.dumps(sample, indent=2, default=str))

# Stats
print("\n=== STATISTICS ===")
total = db.cint_entry_links.count_documents({})
count_samplicio = db.cint_entry_links.count_documents({'live_link': Regex('samplicio', 'i')})
count_torpedo = db.cint_entry_links.count_documents({'live_link': Regex('torpedo', 'i')})
print(f"Total entry links: {total}")
print(f"With samplicio.us URLs: {count_samplicio}")
print(f"With torpedo URLs: {count_torpedo}")

# Check distinct live_link patterns
print("\n=== SAMPLE LIVE LINK URLS ===")
pipeline = [
    {'$project': {'live_link': 1}},
    {'$limit': 5}
]
results = list(db.cint_entry_links.aggregate(pipeline))
for r in results:
    ll = r.get('live_link', 'N/A')
    print(f"- {ll[:120]}...")
