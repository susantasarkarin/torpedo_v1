from pymongo import MongoClient
from bson import ObjectId

client = MongoClient('mongodb://localhost:27017')
db = client['traffic_flow_db']

# Working respondent
working_id = '698585c106f61e8d32dd34ab'
working = db['url_parameters'].find_one({'_id': ObjectId(working_id)})

# Broken respondent  
broken_id = '6985eb3f9848c6ddb9b20695'
broken = db['url_parameters'].find_one({'_id': ObjectId(broken_id)})

print('=== WORKING RESPONDENT ===')
if working:
    print(f"Created: {working.get('created_at')}")
    print(f"Status: {working.get('overall_status')}")
    alloc = working.get('allocated_cpx_survey', {})
    print(f"Survey ID: {alloc.get('cpx_survey_id')}")
    link = alloc.get('entry_link', '')
    print(f"Entry URL: {'href (click.cpx)' if 'click.cpx-research.com' in link else 'href_new (offers.cpx)'}")
    print(f"IP: {working.get('ip')}")

print()
print('=== BROKEN RESPONDENT ===')
if broken:
    print(f"Created: {broken.get('created_at')}")
    print(f"Status: {broken.get('overall_status')}")
    alloc = broken.get('allocated_cpx_survey', {})
    print(f"Survey ID: {alloc.get('cpx_survey_id')}")
    link = alloc.get('entry_link', '')
    print(f"Entry URL: {'href (click.cpx)' if 'click.cpx-research.com' in link else 'href_new (offers.cpx)'}")
    print(f"IP: {broken.get('ip')}")

print()
print('=== RECENT CPX CALLBACKS ===')
for cb in db['cpx_callback_logs'].find().sort('created_at', -1).limit(10):
    print(f"{cb.get('created_at')} - sfwid={str(cb.get('sfwid'))[:8]}... status={cb.get('status')} resolved={cb.get('resolved_status')}")
