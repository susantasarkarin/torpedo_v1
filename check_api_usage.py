"""Check all AI usage logs to understand API consumption"""
from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv('MONGO_URI'))
db = client['email_automation']

print("=" * 70)
print("INVESTIGATING OPENAI API USAGE")
print("=" * 70)

# Check ai_usage_logs
print("\n📊 AI USAGE LOGS (ai_usage_logs collection):")
logs = db['ai_usage_logs']
print(f"   Total logs: {logs.count_documents({})}")

# Group by endpoint
pipeline = [{'$group': {'_id': '$endpoint', 'count': {'$sum': 1}}}, {'$sort': {'count': -1}}]
print("   By endpoint:")
for r in logs.aggregate(pipeline):
    print(f"      {r['_id']}: {r['count']}")

# Check openai_usage_logs
print("\n📊 OPENAI USAGE LOGS (openai_usage_logs collection):")
openai_logs = db['openai_usage_logs']
total_openai = openai_logs.count_documents({})
print(f"   Total: {total_openai}")

if total_openai > 0:
    print("   Recent entries:")
    recent = list(openai_logs.find({}).sort('timestamp', -1).limit(5))
    for r in recent:
        ts = r.get('timestamp', r.get('created_at', 'N/A'))
        if hasattr(ts, 'strftime'): 
            ts = ts.strftime('%Y-%m-%d %H:%M')
        tokens = r.get('total_tokens', r.get('tokens', '?'))
        print(f"      {ts} | {r.get('model', 'N/A')} | tokens: {tokens}")

# Check gemini logs
print("\n📊 GEMINI LOGS:")
gemini = db['gemini_requests']
print(f"   Total: {gemini.count_documents({})}")

# Check classified_gmail for recent activity
print("\n📊 CLASSIFIED GMAIL (email classifications):")
classified = db['classified_gmail']
total_classified = classified.count_documents({})
two_days = datetime.utcnow() - timedelta(days=2)
recent_classified = classified.count_documents({'classified_at': {'$gte': two_days}})
print(f"   Total classified emails: {total_classified}")
print(f"   Classified in last 2 days: {recent_classified}")

# Check for AI classification activity
print("\n📊 LEAD AI CLASSIFICATION LOGS:")
ai_class_logs = db['lead_ai_classification_logs']
total_class = ai_class_logs.count_documents({})
recent_class = ai_class_logs.count_documents({'created_at': {'$gte': two_days}})
print(f"   Total: {total_class}")
print(f"   Last 2 days: {recent_class}")

# Check emails collection for recent processing
print("\n📊 EMAILS COLLECTION:")
emails = db['emails']
total_emails = emails.count_documents({})
recent_emails = emails.count_documents({'received_at': {'$gte': two_days}})
ai_processed_emails = emails.count_documents({'ai_classified': True})
print(f"   Total emails: {total_emails}")
print(f"   AI classified: {ai_processed_emails}")
print(f"   Received in last 2 days: {recent_emails}")

# Check ai_review_queue
print("\n📊 AI REVIEW QUEUE:")
review = db['ai_review_queue']
print(f"   Total: {review.count_documents({})}")
print(f"   Pending: {review.count_documents({'status': 'pending'})}")

# Check for any collections with recent updates
print("\n📊 COLLECTIONS WITH RECENT ACTIVITY (last 2 days):")
for coll_name in db.list_collection_names():
    try:
        coll = db[coll_name]
        # Try different date fields
        for date_field in ['created_at', 'timestamp', 'updated_at', 'classified_at']:
            count = coll.count_documents({date_field: {'$gte': two_days}})
            if count > 0:
                print(f"   {coll_name} ({date_field}): {count}")
                break
    except:
        pass

print("\n" + "=" * 70)
