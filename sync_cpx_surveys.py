#!/usr/bin/env python3
"""
Sync CPX surveys from cpx_research.cpx_surveys to survey_allocation.surveys
This ensures allocation surveys have the href field with k= parameter
"""

from pymongo import MongoClient
from datetime import datetime

def sync_cpx_surveys():
    client = MongoClient('mongodb://localhost:27017')
    cpx_db = client['cpx_research']
    alloc_db = client['survey_allocation']
    
    print('🔄 Syncing CPX surveys...')
    
    # Get all CPX surveys with href
    cpx_surveys = list(cpx_db.cpx_surveys.find({'href': {'$exists': True, '$ne': ''}}))
    print(f'Found {len(cpx_surveys)} CPX surveys with href')
    
    synced = 0
    updated = 0
    
    for cpx_survey in cpx_surveys:
        survey_id = str(cpx_survey.get('_id') or cpx_survey.get('survey_id'))
        
        # Check if survey exists in allocation
        existing = alloc_db.surveys.find_one({'provider': 'CPX', 'external_id': survey_id})
        
        if existing:
            # Update existing survey with href
            alloc_db.surveys.update_one(
                {'_id': existing['_id']},
                {'$set': {
                    'href': cpx_survey['href'],
                    'href_new': cpx_survey.get('href_new', ''),
                    'last_synced': datetime.utcnow()
                }}
            )
            updated += 1
        else:
            # Insert new survey
            alloc_db.surveys.insert_one({
                'external_id': survey_id,
                'provider': 'CPX',
                'status': 'active',
                'name': f'CPX Survey {survey_id}',
                'loi': cpx_survey.get('loi', 0),
                'cpi': cpx_survey.get('payout', 0),
                'conversion_rate': cpx_survey.get('conversion_rate', 0),
                'country': cpx_survey.get('country', 'ALL'),
                'href': cpx_survey['href'],
                'href_new': cpx_survey.get('href_new', ''),
                'created_at': datetime.utcnow(),
                'last_synced': datetime.utcnow()
            })
            synced += 1
    
    print(f'✅ Sync complete: {synced} new, {updated} updated')
    print(f'📊 Total in cpx_research.cpx_surveys: {cpx_db.cpx_surveys.count_documents({})}')
    print(f'📊 Total CPX in survey_allocation.surveys: {alloc_db.surveys.count_documents({"provider": "CPX"})}')

if __name__ == '__main__':
    sync_cpx_surveys()
