from pymongo import MongoClient
from datetime import datetime, timedelta
c = MongoClient()
db = c.traffic_flow_db

# Check how createdAt is stored
samples = list(db.url_parameters.find({}, {"createdAt": 1, "timestamp": 1}).limit(5))
for s in samples:
    cr = s.get("createdAt")
    ts = s.get("timestamp")
    print(f"  createdAt={cr!r} ({type(cr).__name__}), timestamp={ts!r} ({type(ts).__name__})")

# Count records with different createdAt types
has_dt = db.url_parameters.count_documents({"createdAt": {"$type": "date"}})
has_str = db.url_parameters.count_documents({"createdAt": {"$type": "string"}})
has_null = db.url_parameters.count_documents({"createdAt": None})
has_ts = db.url_parameters.count_documents({"timestamp": {"$exists": True}})
print(f"\ncreatedAt as date: {has_dt}")
print(f"createdAt as string: {has_str}")
print(f"createdAt is null/missing: {has_null}")
print(f"has timestamp field: {has_ts}")

# Check what old records use for dating
old_sample = db.url_parameters.find_one({"createdAt": None}, {"timestamp": 1, "createdAt": 1, "updatedAt": 1})
if old_sample:
    print(f"\nOld record (no createdAt): timestamp={old_sample.get('timestamp')!r}, updatedAt={old_sample.get('updatedAt')!r}")
