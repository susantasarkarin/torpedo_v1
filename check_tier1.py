from pymongo import MongoClient
c = MongoClient()
db = c.torpedo_gmail

# Check unclassified count using the same query as the worker
unclassified = db.email_metadata.count_documents({
    "$or": [
        {"ai_tier1_category": {"$exists": False}},
        {"ai_needs_classification": True}
    ]
})
classified = db.email_metadata.count_documents({"ai_tier1_category": {"$exists": True}})
print(f"Unclassified (tier1): {unclassified}")
print(f"Classified (tier1): {classified}")

# Also check total emails
total = db.email_metadata.count_documents({})
print(f"Total emails: {total}")

# Check if worker is running by looking at recent classifications
from datetime import datetime, timedelta, timezone
five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
recent = db.email_metadata.count_documents({
    "ai_tier1_category": {"$exists": True},
    "ai_classified_at": {"$gte": five_min_ago}
})
print(f"Classified in last 5 min: {recent}")
