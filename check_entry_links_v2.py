#!/usr/bin/env python3
"""Check entry link data in cint_research database"""
from pymongo import MongoClient
import json
from bson.regex import Regex

c = MongoClient()
db = c['cint_research']

print("=== SAMPLE ENTRY LINKS ===")
samples = list(db.cint_entry_links.find({}, {'_id': 0}).limit(3))
for i, sample in enumerate(samples, 1):
    print(f"\n--- Entry Link {i} ---")
    print(json.dumps(sample, indent=2, default=str))

print("\n=== ENTRY LINK URL PATTERNS ===")
total = db.cint_entry_links.count_documents({})
count_samplicio = db.cint_entry_links.count_documents({'live_link': Regex('samplicio', 'i')})
count_torpedo = db.cint_entry_links.count_documents({'live_link': Regex('torpedo', 'i')})
count_none = db.cint_entry_links.count_documents({'live_link': None})
count_empty = db.cint_entry_links.count_documents({'live_link': ''})
count_missing = db.cint_entry_links.count_documents({'live_link': {'$exists': False}})

print(f"Total entry links: {total}")
print(f"With samplicio.us URLs: {count_samplicio}")
print(f"With torpedo URLs: {count_torpedo}")
print(f"With null live_link: {count_none}")
print(f"With empty live_link: {count_empty}")
print(f"Missing live_link field: {count_missing}")

print("\n=== SAMPLE SURVEYS (checking if they have entry links) ===")
surveys = list(db.cint_surveys.find({'is_live': True}, {'survey_id': 1, 'survey_name': 1, '_id': 0}).limit(5))
for s in surveys:
    survey_id = s['survey_id']
    entry_link = db.cint_entry_links.find_one({'survey_id': survey_id}, {'live_link': 1, '_id': 0})
    has_link = 'YES' if entry_link and entry_link.get('live_link') else 'NO'
    print(f"Survey {survey_id}: Entry Link = {has_link}")
    if entry_link:
        print(f"  -> {entry_link.get('live_link', 'N/A')[:80]}")
