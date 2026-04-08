from pymongo import MongoClient

db = MongoClient('mongodb://localhost:27017/')['email_automation']

print("=== leads_raw classification_status breakdown ===")
for doc in db.leads_raw.aggregate([{"$group": {"_id": "$classification_status", "c": {"$sum": 1}}}]):
    print(f"  {doc['_id']!r:30s} -> {doc['c']}")

print()
print("=== leads_enriched total ===")
print("  total:", db.leads_enriched.count_documents({}))

print()
print("=== ai_usage_logs last 3 entries ===")
for doc in db.ai_usage_logs.find({}, {"timestamp":1,"provider":1,"model":1,"success":1,"error_message":1}).sort("timestamp",-1).limit(3):
    print(f"  {doc.get('timestamp')} | {doc.get('provider')} | {doc.get('model')} | success={doc.get('success')} | err={str(doc.get('error_message',''))[:60]}")
