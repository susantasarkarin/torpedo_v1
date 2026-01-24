from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

c = MongoClient()
db = c.torpedo_gmail

# Count pending vs classified
pending = db.email_metadata.count_documents({"ai_category": {"$exists": False}})
classified = db.email_metadata.count_documents({"ai_category": {"$exists": True}})

print(f"Pending classification: {pending}")
print(f"Already classified: {classified}")

# Check recently classified (last 10 minutes)
ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
recent = db.email_metadata.count_documents({
    "ai_category": {"$exists": True},
    "classified_at": {"$gte": ten_min_ago}
})
print(f"Classified in last 10 min: {recent}")

# Show a sample of recent classifications
sample = list(db.email_metadata.find(
    {"ai_category": {"$exists": True}},
    {"ai_category": 1, "subject": 1, "classified_at": 1}
).sort("classified_at", -1).limit(5))

print("\nRecent classifications:")
for s in sample:
    cat = s.get("ai_category", "N/A")
    subj = s.get("subject", "N/A")[:50]
    when = s.get("classified_at", "N/A")
    print(f"  {cat}: {subj}... ({when})")
