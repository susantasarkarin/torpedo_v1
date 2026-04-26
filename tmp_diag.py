"""Diagnostic script for the three sales module issues."""
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(uri, serverSelectionTimeoutMS=5000)

torpedo_db = client['torpedo']
torpedo_gmail_db = client['torpedo_gmail']
email_auto_db = client['email_automation']
settings_db = client['torpedo_settings']

print('=' * 60)
print('=== ISSUE 1: MAIL SENDING DIAGNOSTICS ===')
print('=' * 60)

# Check workspace_mailboxes (torpedo_gmail DB)
ws_mailboxes = list(torpedo_gmail_db['workspace_mailboxes'].find(
    {},
    {'email': 1, 'display_name': 1, 'is_active': 1, 'health_status': 1, '_id': 0}
))
print(f'\nworkspace_mailboxes count: {len(ws_mailboxes)}')
for m in ws_mailboxes:
    print(f'  {m}')

# Check outreach_mailboxes (torpedo DB)
outreach_mailboxes = list(torpedo_db['outreach_mailboxes'].find(
    {},
    {'email_address': 1, 'business': 1, 'is_active': 1, 'provider': 1, '_id': 0}
))
print(f'\noutreach_mailboxes count: {len(outreach_mailboxes)}')
for m in outreach_mailboxes:
    print(f'  {m}')

# Check active campaigns
campaigns = list(torpedo_db['outreach_campaigns_v2'].find(
    {},
    {'campaign_id': 1, 'business': 1, 'is_active': 1, 'basket': 1, 'name': 1, '_id': 0}
))
print(f'\ncampaigns: {len(campaigns)}')
for c in campaigns:
    print(f'  {c}')

# Check leads workflow status breakdown
pipeline = [{'$group': {'_id': '$workflow_status', 'count': {'$sum': 1}}}]
wf_stats = list(torpedo_db['outreach_leads_v2'].aggregate(pipeline))
print(f'\noutreach_leads_v2 by workflow_status:')
total_leads = 0
for s in sorted(wf_stats, key=lambda x: -(x['count'])):
    print(f'  {s["_id"]}: {s["count"]}')
    total_leads += s['count']
print(f'  TOTAL: {total_leads}')

# Check leads with next_send_at due NOW per campaign
from datetime import datetime
now = datetime.utcnow()
print(f'\nLeads due NOW (next_send_at <= {now.strftime("%Y-%m-%d %H:%M")}):')
for c in campaigns:
    cid = c.get('campaign_id')
    due_count = torpedo_db['outreach_leads_v2'].count_documents({
        'campaign_id': cid,
        'workflow_status': {'$in': ['not_started', 'pending_scheduled', 'in_sequence']},
        'next_send_at': {'$lte': now}
    })
    print(f'  Campaign {c.get("business")} ({cid[:8]}...): {due_count} due')

# Check recent send errors
recent_errors = list(torpedo_db['outreach_leads_v2'].find(
    {'workflow_status': 'error'},
    {'email': 1, 'last_send_error': 1, 'campaign_id': 1, '_id': 0}
).limit(5))
print(f'\nRecent errors (sample):')
for e in recent_errors:
    print(f'  {e}')

print('\n' + '=' * 60)
print('=== ISSUE 2: LEADS vs COLD OUTREACH DISCREPANCY ===')
print('=' * 60)

# Basket distribution in leads_enriched
leads_enriched = email_auto_db['leads_enriched']
total_enriched = leads_enriched.count_documents({})
with_email = leads_enriched.count_documents({'email': {'$exists': True, '$ne': ''}})
print(f'\nleads_enriched total: {total_enriched}')
print(f'  with email: {with_email}')

pipeline = [
    {'$match': {'email': {'$exists': True, '$ne': ''}}},
    {'$group': {'_id': '$classification_basket', 'count': {'$sum': 1}}}
]
basket_counts = list(leads_enriched.aggregate(pipeline))
print(f'\nBasket distribution (email only):')
for b in sorted(basket_counts, key=lambda x: (x['_id'] or 'Z')):
    print(f'  Basket {b["_id"]}: {b["count"]}')

no_basket = leads_enriched.count_documents({
    'email': {'$exists': True, '$ne': ''},
    '$or': [
        {'classification_basket': {'$exists': False}},
        {'classification_basket': None},
        {'classification_basket': ''},
    ]
})
print(f'  No basket: {no_basket}')

# Check outreach_leads_v2 enrollment by campaign
print(f'\noutreach_leads_v2 enrollment by campaign:')
for c in campaigns:
    cid = c.get('campaign_id')
    enrolled = torpedo_db['outreach_leads_v2'].count_documents({'campaign_id': cid})
    print(f'  {c.get("business")} ({c.get("basket")}): {enrolled} enrolled')

print('\n' + '=' * 60)
print('=== ISSUE 3: NO NEW LEADS IN AI DATABASE ===')
print('=' * 60)

# Check web search jobs
jobs = list(client['email_automation']['web_search_jobs'].find(
    {},
    {'job_id': 1, 'status': 1, 'created_at': 1, 'total_imported': 1, 'total_found': 1, 'errors': 1, '_id': 0}
).sort('created_at', -1).limit(5))
print(f'\nRecent web search jobs:')
for j in jobs:
    err_count = len(j.get('errors', []))
    print(f'  {j.get("job_id", "")[:12]}... status={j.get("status")} imported={j.get("total_imported")} found={j.get("total_found")} errors={err_count}')

# Check global search control
try:
    control = settings_db['app_settings'].find_one({'_id': 'search_control'})
    print(f'\nGlobal search control: {control}')
except Exception as e:
    print(f'Error checking search control: {e}')

# Check Google API credentials
try:
    app_config = settings_db['app_settings'].find_one({'_id': 'app_config'})
    if app_config:
        has_google_key = bool(app_config.get('google_api_key'))
        has_cse_id = bool(app_config.get('google_cse_id'))
        has_openai_key = bool(app_config.get('openai_api_key'))
        print(f'\nAPI keys configured:')
        print(f'  Google API Key: {has_google_key}')
        print(f'  Google CSE ID: {has_cse_id}')
        print(f'  OpenAI API Key: {has_openai_key}')
    else:
        print(f'\nNo app_config found in torpedo_settings')
        has_google_key = bool(os.getenv('GOOGLE_API_KEY'))
        has_cse_id = bool(os.getenv('GOOGLE_CSE_ID'))
        print(f'  From ENV - Google API Key: {has_google_key}, CSE ID: {has_cse_id}')
except Exception as e:
    print(f'Error checking API keys: {e}')

# Check recent leads_raw additions
from datetime import timedelta
recent_raw = client['email_automation']['leads_raw'].count_documents({
    'created_at': {'$gte': datetime.utcnow() - timedelta(days=7)}
})
recent_enriched = leads_enriched.count_documents({
    'created_at': {'$gte': datetime.utcnow() - timedelta(days=7)}
})
print(f'\nLeads added in last 7 days:')
print(f'  leads_raw: {recent_raw}')
print(f'  leads_enriched: {recent_enriched}')

print('\n' + '=' * 60)
print('DIAGNOSTICS COMPLETE')
print('=' * 60)
