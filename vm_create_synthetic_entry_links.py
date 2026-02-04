#!/usr/bin/env python3
"""
Create synthetic entry links for Cint surveys that aren't allocated via API.

Since Cint supplier allocation must be done manually via Cint interface,
we create synthetic entry links that can be used for allocation.
These use Cint's standard entry link format with placeholder URLs.
"""
import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timezone

load_dotenv('.env')
sys.path.insert(0, '/var/www/campaign_platform/backend')

mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
api_base = os.getenv('API_BASE', 'https://torpedo.cogentixresearch.com')

client = MongoClient(mongo_uri)
db = client['cint_research']
surveys_coll = db['cint_surveys']
entry_links_coll = db['cint_entry_links']

# Get active surveys
active_surveys = list(surveys_coll.find({'is_active_in_pool': True}).limit(50))
print(f'Creating synthetic entry links for {len(active_surveys)} active surveys...\n')

created = 0
existing = 0

for survey in active_surveys:
    survey_id = survey.get('survey_id')
    
    # Check if link already exists
    existing_link = entry_links_coll.find_one({'survey_id': survey_id})
    if existing_link:
        existing += 1
        continue
    
    # Create synthetic entry link using Cint standard format with [%MID%] placeholder
    # This allows Cint to replace the placeholder with actual respondent ID when clicked
    live_link = f'{api_base}/cint-response?mid=[%MID%]&sid={survey_id}&status=start'
    test_link = f'{api_base}/cint-response?mid=[TEST_MID]&sid={survey_id}&status=test'
    
    entry_link_doc = {
        'survey_id': survey_id,
        'survey_number': survey_id,
        'supplier_link_type_code': 'OWS',
        'tracking_type_code': 'NONE',
        'live_link': live_link,
        'test_link': test_link,
        'default_link': f'{api_base}/survey',
        'success_link': f'{api_base}/cint-response?mid=[%MID%]&sid={survey_id}&status=complete&revenue=[%REVENUE%]',
        'failure_link': f'{api_base}/cint-response?mid=[%MID%]&sid={survey_id}&status=terminate',
        'over_quota_link': f'{api_base}/cint-response?mid=[%MID%]&sid={survey_id}&status=quota_full',
        'quality_termination_link': f'{api_base}/cint-response?mid=[%MID%]&sid={survey_id}&status=quality_terminate',
        'created_at': datetime.now(timezone.utc),
        'updated_at': datetime.now(timezone.utc),
        'synthetic': True,  # Mark as synthetic (not from Cint API)
        '_type': 'synthetic_entry_link'
    }
    
    entry_links_coll.insert_one(entry_link_doc)
    created += 1
    
    if created % 10 == 0:
        print(f'  Created {created} entry links...')

print(f'\n✅ Complete:')
print(f'  Created: {created}')
print(f'  Already existing: {existing}')
print(f'  Total in collection: {entry_links_coll.count_documents({})}')
