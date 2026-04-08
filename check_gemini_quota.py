"""Check Gemini quota state across all governance + rotator collections."""
import sys
sys.path.insert(0, '/var/www/campaign_platform/backend')

from pymongo import MongoClient
from datetime import datetime

today = datetime.now().strftime("%Y-%m-%d")

# email_automation DB (GeminiRotator quota)
db_email = MongoClient('mongodb://localhost:27017/')['email_automation']
print("=== GeminiRotator quota (email_automation.gemini_quota) ===")
docs = list(db_email['gemini_quota'].find({'date': today}))
if docs:
    for doc in docs:
        print(f"  key {doc['key_index']}: {doc.get('requests_count',0)} requests, {doc.get('tokens_used',0)} tokens")
else:
    print("  (empty)")

print()
print("=== gemini_requests collection ===")
print("  total:", db_email['gemini_requests'].count_documents({'date': today}))

# ai_governance DB (gemini_gateway quota)
print()
print("=== AI Governance DB (torpedo_db.gemini_daily_usage) ===")
for dbname in ['torpedo_db', 'email_automation', 'torpedo_settings']:
    try:
        db2 = MongoClient('mongodb://localhost:27017/')[dbname]
        for coll in ['gemini_daily_usage', 'gemini_usage', 'classified_emails']:
            try:
                c = db2[coll].count_documents({})
                if c > 0:
                    print(f"  {dbname}.{coll}: {c} documents")
                    # Show today's count
                    today_c = db2[coll].count_documents({'date': today})
                    if today_c > 0:
                        print(f"    today({today}): {today_c}")
            except:
                pass
    except:
        pass

print()
print("=== Check what databases use gemini keys ===")
# Find how many emails were classified today
db_email2 = MongoClient()['email_automation']
try:
    classified_today = db_email2['classified_emails'].count_documents({'classified_at': {'$gte': datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)}})
    print(f"  classified_emails classified today: {classified_today}")
except Exception as e:
    print(f"  classified_emails: error - {e}")
