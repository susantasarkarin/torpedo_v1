"""Quick check of url_parameters collection stats."""
from pymongo import MongoClient
from datetime import datetime, timedelta

c = MongoClient()
db = c.campaign_platform
total = db.url_parameters.count_documents({})
seven_ago = datetime.utcnow() - timedelta(days=7)

# Check if createdAt is stored as datetime or string
sample = db.url_parameters.find_one({}, {"createdAt": 1, "status": 1})
if sample:
    sa = sample.get("createdAt")
    print(f"Sample createdAt: {sa!r} type: {type(sa).__name__}")

recent_dt = db.url_parameters.count_documents({"createdAt": {"$gte": seven_ago}})
# Also try string comparison in case createdAt is stored as ISO string
recent_str = db.url_parameters.count_documents({"createdAt": {"$gte": seven_ago.isoformat()}})

print(f"Total: {total}")
print(f"Last 7d (datetime gte): {recent_dt}")
print(f"Last 7d (string gte): {recent_str}")
