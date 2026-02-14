#!/usr/bin/env python3
"""Quick CINT status check"""
from pymongo import MongoClient

c = MongoClient()
db = c['cint_research']

print('=== CINT DB Status ===')
print('Collections:', db.list_collection_names())
survey_count = db.cint_surveys.count_documents({})
print('Total surveys:', survey_count)
print('Active surveys:', db.cint_surveys.count_documents({'is_active': True}))
print('Live surveys:', db.cint_surveys.count_documents({'is_live': True}))

entry_link_count = db.cint_entry_links.count_documents({})
print('Entry links:', entry_link_count)

if entry_link_count > 0:
    print('\nRecent entry links:')
    for el in db.cint_entry_links.find().sort('created_at', -1).limit(3):
        sid = el.get('survey_id')
        ll = el.get('live_link', 'N/A')
        if ll and len(ll) > 50:
            ll = ll[:50] + '...'
        print(f'  survey_id={sid} live_link={ll}')

if survey_count > 0:
    recent = list(db.cint_surveys.find().sort('updated_at', -1).limit(3))
    print('\nRecent surveys:')
    for s in recent:
        sid = s.get('survey_id')
        live = s.get('is_live')
        upd = s.get('updated_at')
        print(f'  {sid} | live={live} | {upd}')
else:
    print('\n>>> No surveys in database <<<')
    # Check settings/subscription
    settings = db.cint_settings.find_one()
    if settings:
        print('\nCINT Settings found:')
        print(f'  webhook_url: {settings.get("webhook_url")}')
    sub = db.cint_subscriptions.find_one()
    if sub:
        print('\nCINT Subscription found:')
        print(f'  callback: {sub.get("callback")}')
        print(f'  countries: {sub.get("countries")}')

c.close()
