#!/usr/bin/env python3
"""Check CINT cache status"""
from pymongo import MongoClient
from datetime import datetime
import os

client = MongoClient("mongodb://localhost:27017/")
db = client['cint_research']

print("=== CINT CACHE STATUS ===\n")

for country in ['GB', 'IN', 'US']:
    doc = db.cint_surveys.find_one({'country_code': country})
    if doc:
        surveys = doc.get('surveys', [])
        last_updated = doc.get('last_updated', 'Unknown')
        if isinstance(last_updated, datetime):
            age = datetime.utcnow() - last_updated
            age_str = f"{age.total_seconds()/60:.1f} min ago"
        else:
            age_str = str(last_updated)
        
        print(f"{country}: {len(surveys)} surveys (updated: {age_str})")
        if surveys:
            ids = [s.get('SurveyId') for s in surveys[:5]]
            print(f"  Sample IDs: {ids}")
    else:
        print(f"{country}: NOT IN CACHE")
    print()

# Check all countries in cache
print("=== ALL COUNTRIES IN CACHE ===")
all_countries = list(db.cint_surveys.find({}, {'country_code': 1, 'surveys': 1}))
for doc in sorted(all_countries, key=lambda x: len(x.get('surveys', [])), reverse=True)[:10]:
    cc = doc.get('country_code')
    count = len(doc.get('surveys', []))
    print(f"  {cc}: {count} surveys")
