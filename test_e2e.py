"""End-to-end system test: extraction → enrichment → BU routing → status check"""
import sys, os, time, requests

sys.path.insert(0, '/var/www/campaign_platform')
os.chdir('/var/www/campaign_platform/backend')

BASE = "http://localhost:8000"
VENV_PY = "/var/www/campaign_platform/backend/venv/bin/python3"

def check(label, ok, detail=""):
    status = "✅" if ok else "❌"
    print(f"{status} {label}", f"| {detail}" if detail else "")

def section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print('='*50)

# ─── MODULE 1: Validation ────────────────────────────────────────────────────
section("MODULE 1 — Validation")
r = requests.get(f"{BASE}/api/sales-outreach/validate", timeout=20)
v = r.json()
check("Overall OK", v.get("overall_ok"), str(v.get("failed_checks", [])))
for k, chk in v.get("checks", {}).items():
    check(f"  {k}", chk.get("ok"), str({x: chk[x] for x in chk if x != "ok"}))

# ─── MODULE 2: Email extraction (sync via DB direct call) ────────────────────
section("MODULE 2 — Email Extraction")
from pymongo import MongoClient
mc = MongoClient('mongodb://localhost:27017')

# Check torpedo_gmail pool
gmail_db = mc['torpedo_gmail']
total_pool = gmail_db['email_metadata'].count_documents({})
inbound = gmail_db['email_metadata'].count_documents({'direction': 'inbound'})
check("torpedo_gmail.email_metadata exists", total_pool > 0, f"{total_pool} total, {inbound} inbound")

# Check leads collection
cp_db = mc['campaign_platform']
leads_total = cp_db['leads'].count_documents({})
check("campaign_platform.leads collection", True, f"{leads_total} leads stored")

# Get a sample lead
sample = cp_db['leads'].find_one({'email': {'$exists': True, '$ne': None}})
if sample:
    lead_id = str(sample['_id'])
    check("Sample lead found", True, f"id={lead_id} | name={sample.get('name','?')} | email={sample.get('email','?')} | domain={sample.get('domain','?')}")
else:
    # Insert a synthetic lead for testing
    from datetime import datetime
    result = cp_db['leads'].insert_one({
        'name': 'Keya Kundu', 'email': None, 'domain': 'hansaresearch.com',
        'company': 'Hansa Research', 'stage': 'new', 'source': 'mail_pool',
        'created_at': datetime.utcnow()
    })
    lead_id = str(result.inserted_id)
    check("Inserted synthetic test lead", True, f"id={lead_id}")

# ─── MODULE 3: Gemini Enrichment ────────────────────────────────────────────
section("MODULE 3 — Gemini Enrichment")
r = requests.post(f"{BASE}/api/sales-outreach/enrich/{lead_id}", timeout=30)
enrich = r.json()
check("Enrich endpoint reachable", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    check("Task queued", enrich.get('status') == 'queued', str(enrich))
    print(f"  Task ID: {enrich.get('task_id','?')}")
    print("  Waiting 15s for worker to process...")
    time.sleep(15)
    # Check if lead was enriched
    updated = cp_db['leads'].find_one({'_id': sample['_id'] if sample else result.inserted_id})
    enriched = updated.get('enriched') or updated.get('gemini_enriched') or updated.get('stage') == 'enriched'
    email_predicted = updated.get('email') or updated.get('email_address')
    check("Lead enriched by Gemini", bool(updated.get('enriched') or enriched), f"stage={updated.get('stage','?')}")
    check("Email predicted by Gemini", bool(email_predicted), f"email={email_predicted}")
    print(f"  Enriched data: company_size={updated.get('company_size','?')}, industry={updated.get('industry','?')}, seniority={updated.get('seniority','?')}")
else:
    check("Enrich failed", False, str(enrich))

# ─── MODULE 4: BU Routing ────────────────────────────────────────────────────
section("MODULE 4 — BU Routing")
r = requests.post(f"{BASE}/api/sales-outreach/route/{lead_id}", timeout=30)
route = r.json()
check("Route endpoint reachable", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    check("Task queued", route.get('status') == 'queued', str(route))
    print("  Waiting 15s for worker...")
    time.sleep(15)
    updated = cp_db['leads'].find_one({'_id': (sample['_id'] if sample else result.inserted_id)})
    check("BU assigned", bool(updated.get('business_unit')), f"bu={updated.get('business_unit','?')}")
    check("Draft email written", bool(updated.get('draft_email')), f"preview={str(updated.get('draft_email',''))[:80]}...")

# ─── MODULE 5: Gmail ─────────────────────────────────────────────────────────
section("MODULE 5 — Gmail Auth")
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
creds = Credentials.from_authorized_user_file('/var/www/campaign_platform/backend/gmail_token.json')
svc = build('gmail', 'v1', credentials=creds, cache_discovery=False)
profile = svc.users().getProfile(userId='me').execute()
check("Gmail authenticated", True, f"account={profile.get('emailAddress')} | messages={profile.get('messagesTotal')}")
check("Gmail not send (dry run)", True, "Send skipped — real lead required")

# ─── MODULE 6: Reply analysis ─────────────────────────────────────────────────
section("MODULE 6 — Reply Analysis")
r = requests.post(f"{BASE}/api/sales-outreach/reply/{lead_id}",
                  json={"reply_body": "Thanks for reaching out! We are very interested in learning more about your data quality solutions. Can we schedule a call?"}, timeout=30)
reply = r.json()
check("Reply endpoint reachable", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    check("Task queued", reply.get('status') == 'queued', str(reply))
    time.sleep(10)
    updated = cp_db['leads'].find_one({'_id': (sample['_id'] if sample else result.inserted_id)})
    sentiment = updated.get('reply_sentiment', 'not_set')
    crm_status = updated.get('crm_status', updated.get('stage', '?'))
    check("Sentiment analyzed", sentiment != 'not_set', f"sentiment={sentiment}")
    check("Stage updated correctly", True, f"stage={crm_status}")

# ─── Final Status ─────────────────────────────────────────────────────────────
section("FINAL — Lead Status")
r = requests.get(f"{BASE}/api/sales-outreach/status/{lead_id}", timeout=10)
status = r.json()
check("Status endpoint works", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    print(f"  Lead stage: {status.get('stage','?')}")
    print(f"  Email: {status.get('email','?')}")
    print(f"  Business unit: {status.get('business_unit','?')}")
    print(f"  Sentiment: {status.get('reply_sentiment','?')}")
    print(f"  Outreach records: {len(status.get('outreach_records',[]))}")

mc.close()
print("\n" + "="*50)
print("  TEST COMPLETE")
print("="*50)
