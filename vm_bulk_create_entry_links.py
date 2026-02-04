#!/usr/bin/env python3
import os
import asyncio
import sys
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('.env')
sys.path.insert(0, '/var/www/campaign_platform/backend')

from app.services.cint_service import CintService
from app.models.cint import SupplierLinkCreate

mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
api_key = os.getenv('CINT_API_KEY')
supplier_code = os.getenv('CINT_SUPPLIER_CODE')
api_base = os.getenv('API_BASE', 'https://torpedo.cogentixresearch.com')
frontend_url = os.getenv('FRONTEND_URL', 'https://surveyfieldwork.com')

# Get collections
client = MongoClient(mongo_uri)
db = client['cint_research']
surveys_coll = db['cint_surveys']
entry_links_coll = db['cint_entry_links']
settings_coll = db['cint_settings']

# Create service
service = CintService(
    api_key=api_key,
    supplier_code=supplier_code,
    environment='production',
    cint_surveys_collection=surveys_coll,
    cint_entry_links_collection=entry_links_coll,
    cint_settings_collection=settings_coll
)

async def bulk_create_entry_links():
    # Get first 10 active surveys
    active_surveys = list(surveys_coll.find({'is_active_in_pool': True}).limit(10))
    print(f'Found {len(active_surveys)} active surveys, attempting to create entry links...')
    
    created = 0
    failed = 0
    
    for survey in active_surveys:
        survey_id = survey.get('survey_id')
        print(f'\nSurvey {survey_id}:')
        
        # Build link config with proper URLs
        success_url = api_base + '/cint-response?status=complete&mid=[%MID%]&revenue=[%REVENUE%]'
        failure_url = api_base + '/cint-response?status=terminate&mid=[%MID%]'
        over_quota_url = api_base + '/cint-response?status=quota_full&mid=[%MID%]'
        quality_term_url = api_base + '/cint-response?status=quality_terminate&mid=[%MID%]'
        default_url = frontend_url + '/survey'
        
        link_config = SupplierLinkCreate(
            supplier_link_type_code="OWS",
            tracking_type_code="NONE",
            default_link=default_url,
            success_link=success_url,
            failure_link=failure_url,
            over_quota_link=over_quota_url,
            quality_termination_link=quality_term_url,
        )
        
        try:
            result = await service.create_entry_link(survey_id, link_config)
            if result.get('success'):
                print(f'  ✓ Entry link created')
                created += 1
            else:
                print(f'  ✗ Failed: {result.get("error", "Unknown error")}')
                failed += 1
        except Exception as e:
            print(f'  ✗ Exception: {str(e)}')
            failed += 1
    
    print(f'\n\nSummary: {created} created, {failed} failed')
    await service.close()

# Run async function
asyncio.run(bulk_create_entry_links())
