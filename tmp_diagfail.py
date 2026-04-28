import pymongo, datetime

client = pymongo.MongoClient("mongodb://localhost:27017/")
col = client["email_automation"]["leads_raw"]

# Check a recent failed lead's last_error
failed = list(col.find(
    {"classification_status": "Failed", "last_error": {"$exists": True, "$ne": None}},
    {"last_error": 1, "classification_attempts": 1, "last_attempt_at": 1}
).sort("last_attempt_at", -1).limit(3))

for f in failed:
    print(f"attempts={f.get('classification_attempts')} error={f.get('last_error','')[:200]}")
    print(f"  last_attempt: {f.get('last_attempt_at')}")
    print()

# Current server time
print("Server UTC now:", datetime.datetime.utcnow())

# Check if job has ever run by looking for any leads with classified_at recently
recent = col.count_documents({
    "classified_at": {"$gte": datetime.datetime.utcnow() - datetime.timedelta(hours=1)}
})
print(f"Classified in last hour: {recent}")
