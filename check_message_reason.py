#!/usr/bin/env python3
"""Check survey message_reason and is_active status"""
from pymongo import MongoClient

c = MongoClient()
db = c['cint_research']

# Check a sample of surveys
print('Sample surveys (10):')
for s in db.cint_surveys.find().limit(10):
    sid = s.get('survey_id')
    live = s.get('is_live')
    active = s.get('is_active')
    reason = s.get('message_reason')
    print(f'  survey_id={sid} is_live={live} is_active={active} msg_reason={reason}')

# Simple distinct values check
print()
print('Distinct message_reason values:')
reasons = db.cint_surveys.distinct('message_reason')
print(f'  {reasons[:20]}')  # First 20

c.close()
