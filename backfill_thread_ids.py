"""
One-time backfill: populate gmail_thread_id on existing outreach_sends_v2
records by matching gmail_message_id against torpedo_gmail.email_metadata.
"""
import pymongo, sys

client = pymongo.MongoClient("mongodb://localhost:27017/")
sends_col = client["torpedo"]["outreach_sends_v2"]
meta_col  = client["torpedo_gmail"]["email_metadata"]

# Find sends that have a gmail_message_id but no gmail_thread_id
sends = list(sends_col.find(
    {"gmail_message_id": {"$exists": True, "$ne": None}, "gmail_thread_id": {"$exists": False}},
    {"_id": 1, "gmail_message_id": 1}
))

print(f"Found {len(sends)} send records missing gmail_thread_id")
if not sends:
    print("Nothing to backfill.")
    sys.exit(0)

updated = 0
not_found = 0

for s in sends:
    msg_id = s["gmail_message_id"]
    # Look up in email_metadata by gmail_message_id
    meta = meta_col.find_one({"gmail_message_id": msg_id}, {"gmail_thread_id": 1})
    if meta and meta.get("gmail_thread_id"):
        sends_col.update_one(
            {"_id": s["_id"]},
            {"$set": {"gmail_thread_id": meta["gmail_thread_id"]}}
        )
        updated += 1
    else:
        not_found += 1

print(f"Backfilled {updated} records, {not_found} could not find matching metadata")
client.close()
