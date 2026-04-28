import pymongo, datetime

client = pymongo.MongoClient("mongodb://localhost:27017/")
col = client["email_automation"]["leads_raw"]

# Check most recent failures
recent_failed = list(col.find(
    {"classification_status": "Failed", "last_attempt_at": {"$gte": datetime.datetime.utcnow() - datetime.timedelta(minutes=10)}},
    {"last_error": 1, "classification_attempts": 1, "last_attempt_at": 1}
).sort("last_attempt_at", -1).limit(5))

print("=== Recent failures (last 10 min) ===")
for f in recent_failed:
    print(f"  attempts={f.get('classification_attempts')} error={str(f.get('last_error',''))[:300]}")

if not recent_failed:
    # Fall back to any failed with attempts=1-3
    sample = list(col.find(
        {"classification_status": "Failed", "classification_attempts": {"$lte": 3}},
        {"last_error": 1, "classification_attempts": 1}
    ).limit(5))
    print("=== Any failed (low attempts) ===")
    for f in sample:
        print(f"  attempts={f.get('classification_attempts')} error={str(f.get('last_error',''))[:300]}")
