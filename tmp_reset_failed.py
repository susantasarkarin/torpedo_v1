import pymongo, datetime

client = pymongo.MongoClient("mongodb://localhost:27017/")
col = client["email_automation"]["leads_raw"]

# Check why leads are failing - sample last_error
sample = list(col.find(
    {"classification_status": "Failed"},
    {"last_error": 1, "classification_attempts": 1}
).sort("classification_attempts", 1).limit(5))

print("=== Sample failed leads (lowest attempt count) ===")
for s in sample:
    print(f"  attempts={s.get('classification_attempts',0)}  error={str(s.get('last_error',''))[:150]}")

# Reset ALL failed leads: clear attempts + set back to Pending
result = col.update_many(
    {"classification_status": {"$in": ["Failed", "failed"]}},
    {"$set": {
        "classification_status": "Pending",
        "classification_attempts": 0,
        "last_error": None,
        "last_attempt_at": None,
    }}
)
print(f"\nReset {result.modified_count} failed leads back to Pending")

# Confirm
pending = col.count_documents({"classification_status": {"$in": ["Pending", "pending"]}})
failed = col.count_documents({"classification_status": {"$in": ["Failed", "failed"]}})
print(f"Pending: {pending}  Failed: {failed}")
