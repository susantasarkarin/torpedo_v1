#!/usr/bin/env python3
"""
Validate CINT surveys against API and mark closed ones as inactive.
This script checks all active surveys in our DB against the CINT API.
"""
import os
import sys
import time
import httpx
from datetime import datetime
from pymongo import MongoClient

# Configuration
CINT_API_KEY = os.environ.get('CINT_API_KEY', 'C61C48A6-8154-4F9F-B616-8DFB66F452A7')
CINT_SUPPLIER_CODE = os.environ.get('CINT_SUPPLIER_CODE', '6777')
BATCH_SIZE = 50  # Number of surveys to check per batch
DELAY_BETWEEN_CALLS = 0.2  # Seconds between API calls to avoid rate limiting

def validate_surveys():
    """Check active surveys against CINT API and mark closed ones as inactive."""
    client = MongoClient()
    db = client['cint_research']
    surveys_col = db['cint_surveys']
    entry_links_col = db['cint_entry_links']
    
    # Get all active surveys
    active_surveys = list(surveys_col.find(
        {'is_active': True},
        {'survey_id': 1, 'survey_name': 1, 'country_language': 1}
    ))
    
    print(f"[{datetime.now().isoformat()}] Found {len(active_surveys)} active surveys to validate")
    
    headers = {
        'Authorization': CINT_API_KEY,
        'Content-Type': 'application/json'
    }
    
    closed_count = 0
    error_count = 0
    valid_count = 0
    
    for i, survey in enumerate(active_surveys):
        survey_id = survey['survey_id']
        
        try:
            # Check survey status via API
            url = f"https://api.samplicio.us/Supply/v1/Surveys/BySurveyNumber/{survey_id}/{CINT_SUPPLIER_CODE}"
            resp = httpx.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 404:
                # Survey is closed/not found - mark as inactive
                surveys_col.update_one(
                    {'survey_id': survey_id},
                    {'$set': {
                        'is_active': False,
                        'survey_status_code': 'Closed',
                        'closed_at': datetime.utcnow().isoformat(),
                        'closed_reason': 'API returned 404'
                    }}
                )
                # Remove cached entry link
                entry_links_col.delete_one({'survey_id': survey_id})
                closed_count += 1
                print(f"  [{i+1}/{len(active_surveys)}] Survey {survey_id} CLOSED - marked inactive")
                
            elif resp.status_code == 200:
                data = resp.json()
                survey_data = data.get('Survey', {})
                status_code = survey_data.get('SurveyStatusCode', '')
                
                if status_code not in ['Live', 'Fielding']:
                    # Survey is paused/closed
                    surveys_col.update_one(
                        {'survey_id': survey_id},
                        {'$set': {
                            'is_active': False,
                            'survey_status_code': status_code,
                            'closed_at': datetime.utcnow().isoformat()
                        }}
                    )
                    entry_links_col.delete_one({'survey_id': survey_id})
                    closed_count += 1
                    print(f"  [{i+1}/{len(active_surveys)}] Survey {survey_id} status={status_code} - marked inactive")
                else:
                    valid_count += 1
                    
            else:
                error_count += 1
                print(f"  [{i+1}/{len(active_surveys)}] Survey {survey_id} API error: {resp.status_code}")
                
        except Exception as e:
            error_count += 1
            print(f"  [{i+1}/{len(active_surveys)}] Survey {survey_id} exception: {e}")
        
        # Rate limiting
        if i > 0 and i % BATCH_SIZE == 0:
            print(f"  Processed {i}/{len(active_surveys)} surveys...")
            time.sleep(1)  # Extra pause between batches
        else:
            time.sleep(DELAY_BETWEEN_CALLS)
    
    print(f"\n[{datetime.now().isoformat()}] Validation complete:")
    print(f"  Valid (still active): {valid_count}")
    print(f"  Closed (marked inactive): {closed_count}")
    print(f"  Errors: {error_count}")
    
    return closed_count

if __name__ == '__main__':
    validate_surveys()
