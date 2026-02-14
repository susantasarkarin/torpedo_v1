#!/usr/bin/env python3
"""Analyze CINT surveys state"""
from pymongo import MongoClient

c = MongoClient()
surveys = c.cint_research.cint_surveys
entry_links = c.cint_research.cint_entry_links

# Count by is_active
total = surveys.count_documents({})
active = surveys.count_documents({'is_active': True})
inactive = surveys.count_documents({'is_active': False})

print(f'Total surveys: {total}')
print(f'Active (is_active=True): {active}')
print(f'Inactive (is_active=False): {inactive}')

# Check sample active survey
sample = surveys.find_one({'is_active': True})
if sample:
    print(f'\nSample active survey:')
    print(f'  survey_id: {sample.get("survey_id")}')
    print(f'  supplier_code: {sample.get("supplier_code")}')
    print(f'  message_reason: {sample.get("message_reason")}')
    print(f'  is_live: {sample.get("is_live")}')
    print(f'  country_language: {sample.get("country_language")}')

# Check entry links
el_count = entry_links.count_documents({})
print(f'\nCached entry links: {el_count}')
