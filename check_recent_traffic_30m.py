
import os
import sys
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

def check_traffic():
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("❌ MONGO_URI not found in environment")
        return

    client = MongoClient(mongo_uri)
    db = client["traffic_flow_db"]
    collection = db["url_parameters"]
    logs_col = db["cpx_callback_logs"]

    # IST is UTC + 5:30. 
    # Current local time is 11:40 IST = 06:10 UTC.
    # 30 mins ago is 05:40 UTC.
    
    # Let's just use current UTC and subtract 30 mins.
    now_utc = datetime.utcnow()
    thirty_mins_ago = now_utc - timedelta(minutes=30)

    print(f"--- Traffic Check (Last 30 Minutes: {thirty_mins_ago.isoformat()} to {now_utc.isoformat()} UTC) ---")

    # Query for records created or updated in the last 30 minutes
    query = {
        "$or": [
            {"createdAt": {"$gte": thirty_mins_ago}},
            {"updatedAt": {"$gte": thirty_mins_ago}},
            {"timestamp": {"$gte": thirty_mins_ago.isoformat()}} # Handle string timestamps too
        ]
    }

    recent_records = list(collection.find(query).sort("createdAt", -1))
    total_count = len(recent_records)

    print(f"📊 Total Recent Records: {total_count}")

    if total_count == 0:
        print("ℹ️ No traffic found in the last 30 minutes.")
        return

    # Breakdown by status
    status_counts = {}
    provider_counts = {}
    for r in recent_records:
        status = r.get("status", "UNKNOWN").upper()
        status_counts[status] = status_counts.get(status, 0) + 1
        
        provider = r.get("surveySource", "NONE")
        provider_counts[provider] = provider_counts.get(provider, 0) + 1

    print("\n📈 Status Breakdown:")
    for status, count in status_counts.items():
        print(f"  - {status}: {count}")

    print("\n🏢 Provider Breakdown:")
    for provider, count in provider_counts.items():
        print(f"  - {provider}: {count}")

    # Check for redirects
    redirected = [r for r in recent_records if r.get("redirectUrl")]
    print(f"\n🔗 Successfully Redirected: {len(redirected)} / {total_count}")

    # Check CPX Callback Logs
    recent_logs = list(logs_col.find({"timestamp": {"$gte": thirty_mins_ago}}))
    print(f"📝 Recent CPX Callback Logs: {len(recent_logs)}")

    if total_count > 0:
        print("\n📄 Most Recent 5 Records:")
        for r in recent_records[:5]:
            rid = r.get("respondentId", "N/A")
            status = r.get("status", "N/A")
            created = r.get("createdAt") or r.get("timestamp")
            provider = r.get("surveySource", "N/A")
            print(f"  - [{created}] RID: {rid} | Status: {status} | Provider: {provider}")

if __name__ == "__main__":
    check_traffic()
