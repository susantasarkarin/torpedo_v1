#!/bin/bash
echo "=== CAMPAIGN STATUS ==="
python3 << 'PYEOF'
from pymongo import MongoClient
from datetime import datetime
db = MongoClient()['torpedo']

camps = list(db['outreach_campaigns_v2'].find({'business': 'sfw'}, {'steps': 0}))
for c in camps:
    print(f"Campaign: {c.get('name')} | id={c['campaign_id']} | active={c.get('is_active')} | basket={c.get('basket')} | launched={c.get('launched_at')}")
    ctx = c.get('business_context', {})
    print(f"  business_context keys: {list(ctx.keys()) if ctx else 'EMPTY'}")

print()
print("=== ENROLLED LEADS ===")
for c in camps:
    cid = c['campaign_id']
    total = db['outreach_leads_v2'].count_documents({'campaign_id': cid})
    print(f"Campaign {c.get('name')}: {total} total enrolled")
    for st in ['not_started','pending_scheduled','in_sequence','completed','paused','suppressed']:
        n = db['outreach_leads_v2'].count_documents({'campaign_id': cid, 'workflow_status': st})
        if n: print(f"  {st}: {n}")
    # Sample a due lead
    now = datetime.utcnow()
    due = db['outreach_leads_v2'].find_one({'campaign_id': cid, 'workflow_status': {'$in': ['not_started','pending_scheduled','in_sequence']}, 'next_send_at': {'$lte': now}})
    if due:
        print(f"  DUE lead example: email={due.get('email','?')[:30]} status={due['workflow_status']} next_send={due.get('next_send_at')} step={due.get('current_step')}")
        if due.get('last_send_error'):
            print(f"  LAST ERROR: {due['last_send_error'][:300]}")
    else:
        not_due = db['outreach_leads_v2'].find_one({'campaign_id': cid, 'workflow_status': {'$in': ['not_started','pending_scheduled','in_sequence']}})
        if not_due:
            print(f"  NO DUE LEADS. Next send_at: {not_due.get('next_send_at')} (now={now})")
        else:
            print(f"  NO LEADS in sendable status")

print()
print("=== SENDS ===")
for c in camps:
    cid = c['campaign_id']
    sends = db['outreach_sends_v2'].count_documents({'campaign_id': cid})
    print(f"Campaign {c.get('name')}: {sends} sends")
    last = db['outreach_sends_v2'].find_one({'campaign_id': cid}, sort=[('sent_at', -1)])
    if last:
        print(f"  Last send: {last.get('sent_at')} to={last.get('email','?')[:30]} status={last.get('status')}")

print()
print("=== ERROR LEADS (last 5) ===")
errs = list(db['outreach_leads_v2'].find({'last_send_error': {'$exists': True}}).sort('last_send_error_at', -1).limit(5))
for e in errs:
    print(f"  {e.get('email','?')[:30]} | step={e.get('current_step')} | err={e.get('last_send_error','')[:200]} | at={e.get('last_send_error_at')}")
if not errs:
    print("  (none)")
PYEOF

echo ""
echo "=== BACKEND LOGS (outreach-related, last 50) ==="
grep -i 'outreach\|Outreach\|OutreachSend' /var/log/torpedo_backend.log | tail -50

echo ""
echo "=== SCHEDULER STARTUP ==="
grep -i 'outreach send processor\|outreach_send' /var/log/torpedo_backend.log | tail -5

echo ""
echo "=== RECENT ERRORS ==="
grep -i 'error\|Error\|ERROR' /var/log/torpedo_backend.log | tail -20
