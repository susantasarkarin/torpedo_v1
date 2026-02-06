from pymongo import MongoClient
from bson import ObjectId

client = MongoClient('mongodb://localhost:27017')
db = client['traffic_flow_db']

# Working respondent
working = db.url_parameters.find_one({'_id': ObjectId('698585c106f61e8d32dd34ab')})

# Broken respondent  
broken = db.url_parameters.find_one({'_id': ObjectId('6985eb3f9848c6ddb9b20695')})

print('=== WORKING (698585c1) ===')
if working:
    print(f"overall_status: {working.get('overall_status')}")
    cpx = working.get('allocated_cpx_survey') or {}
    print(f"survey_id: {cpx.get('cpx_survey_id')}")
    link = cpx.get('entry_link', '') or ''
    is_href = 'click.cpx' in link
    print(f"link_type: {'href (click)' if is_href else 'href_new (offers)'}")
    print(f"link: {link[:80]}..." if len(link) > 80 else f"link: {link}")
    print(f"ip: {working.get('ip')}")
else:
    print('NOT FOUND')

print()
print('=== BROKEN (6985eb3f) ===')
if broken:
    print(f"overall_status: {broken.get('overall_status')}")
    cpx = broken.get('allocated_cpx_survey') or {}
    print(f"survey_id: {cpx.get('cpx_survey_id')}")
    link = cpx.get('entry_link', '') or ''
    is_href = 'click.cpx' in link
    print(f"link_type: {'href (click)' if is_href else 'href_new (offers)'}")
    print(f"link: {link[:80]}..." if len(link) > 80 else f"link: {link}")
    print(f"ip: {broken.get('ip')}")
else:
    print('NOT FOUND')

# Check entry guards
print()
print('=== CPX ENTRY GUARDS ===')
guard_w = db.cpx_entry_guards.find_one({'ext_user_id': '698585c106f61e8d32dd34ab'})
guard_b = db.cpx_entry_guards.find_one({'ext_user_id': '6985eb3f9848c6ddb9b20695'})
print(f"Working has guard: {'YES - ' + str(guard_w.get('status')) if guard_w else 'NO'}")
print(f"Broken has guard: {'YES - ' + str(guard_b.get('status')) if guard_b else 'NO'}")

# Recent callbacks
print()
print('=== RECENT CALLBACKS ===')
for cb in db.cpx_callback_logs.find().sort([('_id', -1)]).limit(5):
    sfwid = cb.get('sfwid') or cb.get('resolved_sfwid') or 'N/A'
    print(f"sfwid={str(sfwid)[:10]}... status={cb.get('status')} resolved={cb.get('resolved_status')}")
