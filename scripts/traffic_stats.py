#!/usr/bin/env python3
"""Traffic stats for analysis"""
from pymongo import MongoClient
from datetime import datetime, timedelta
from collections import Counter
import os
from dotenv import load_dotenv

# Load from specific path
load_dotenv('/var/www/campaign_platform/backend/.env')

client = MongoClient(os.getenv('MONGODB_URI'))
db = client['traffic_flow_db']
col = db['url_parameters']

now = datetime.utcnow()
one_hour_ago = now - timedelta(hours=1)

# Last 1 hour
recent = list(col.find({'createdAt': {'$gte': one_hour_ago}}).sort('_id', -1))
print(f'=== LAST 1 HOUR ===')
print(f'Total: {len(recent)}')

statuses = Counter([r.get('status', 'UNKNOWN') for r in recent])
for s, c in statuses.most_common():
    pct = c/len(recent)*100 if recent else 0
    print(f'  {s}: {c} ({pct:.1f}%)')

# Country breakdown
print(f'\n=== TRAFFIC BY COUNTRY (Last 1 hour) ===')
countries = Counter([r.get('countryCode', 'UNKNOWN') for r in recent])
for cc, cnt in countries.most_common():
    print(f'  {cc}: {cnt}')

# Source breakdown for TERMINATED
terms = [r for r in recent if r.get('status') == 'TERMINATED']
print(f'\n=== TERMINATED reasons ===')
alloc_errors = Counter([str(r.get('allocationFailureReason', 'NO_REASON'))[:60] for r in terms])
for e, c in alloc_errors.most_common(5):
    print(f'  {e}: {c}')

# Check CINT waterfall failures
terms_with_cint = [r for r in terms if r.get('cintCandidateIds')]
print(f'\n=== CINT WATERFALL STATS (TERMINATED with CINT candidates) ===')
print(f'  Records with CINT candidates: {len(terms_with_cint)}')
if terms_with_cint:
    avg_candidates = sum(len(r.get('cintCandidateIds', [])) for r in terms_with_cint) / len(terms_with_cint)
    avg_tried = sum(len(r.get('cintTriedSurveyIds', [])) for r in terms_with_cint) / len(terms_with_cint)
    print(f'  Avg candidates available: {avg_candidates:.1f}')
    print(f'  Avg candidates tried: {avg_tried:.1f}')

# Last 24 hours total
yesterday = now - timedelta(hours=24)
daily = col.count_documents({'createdAt': {'$gte': yesterday}})
print(f'\n=== LAST 24 HOURS ===')
print(f'Total: {daily}')

# Check for COMPLETE records
completes = col.count_documents({'createdAt': {'$gte': yesterday}, 'status': 'COMPLETE'})
print(f'COMPLETE: {completes}')

# INCOMPLETE breakdown (people who are still in a survey)
incompletes = list(col.find({'status': 'INCOMPLETE'}).sort('_id', -1).limit(100))
print(f'\n=== CURRENT INCOMPLETE STATUS ===')
print(f'Total INCOMPLETE in DB: {col.count_documents({"status": "INCOMPLETE"})}')
if incompletes:
    sources = Counter([r.get('surveySource', 'NONE') for r in incompletes[:100]])
    for s, c in sources.items():
        print(f'  {s}: {c}')
