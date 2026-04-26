#!/bin/bash
# Remove the email_metadata doc with null gmail_message_id that causes duplicate key errors
# And reset failed leads so they get retried
python3 << 'PYEOF'
from pymongo import MongoClient
from datetime import datetime

client = MongoClient()

# 1. Remove email_metadata docs with null gmail_message_id
gmail_db = client["torpedo_gmail"]
result = gmail_db["email_metadata"].delete_many({"gmail_message_id": None})
print(f"Deleted {result.deleted_count} email_metadata docs with null gmail_message_id")

# 2. Reset outreach leads that had send errors (so they retry)
db = client["torpedo"]
result = db["outreach_leads_v2"].update_many(
    {
        "last_send_error": {"$exists": True, "$ne": None},
        "workflow_status": {"$in": ["not_started", "pending_scheduled", "in_sequence"]},
    },
    {
        "$set": {"updated_at": datetime.utcnow()},
        "$unset": {"last_send_error": "", "last_send_error_at": ""},
    },
)
print(f"Reset {result.modified_count} leads with send errors for retry")
PYEOF
