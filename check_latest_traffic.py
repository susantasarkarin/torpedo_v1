
import os
import sys
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

def check_all_recent():
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("❌ MONGO_URI not found in environment")
        return

    client = MongoClient(mongo_uri)
    db = client["traffic_flow_db"]
    collection = db["url_parameters"]

    print("--- Database Context ---")
    print(f"Database: traffic_flow_db")
    print(f"Collection: url_parameters")
    
    total_docs = collection.count_documents({})
    print(f"Total documents in collection: {total_docs}")

    if total_docs == 0:
        print("ℹ️ Collection is empty.")
        return

    print("\n📄 Most Recent 10 Records (Overall):")
    # Sort by _id descending to get absolute latest
    recent_records = list(collection.find({}).sort("_id", -1).limit(10))
    
    for r in recent_records:
        rid = r.get("respondentId", "N/A")
        status = r.get("status", "N/A")
        # Try different possible timestamp fields
        created = r.get("createdAt") or r.get("timestamp") or r.get("updatedAt") or "Unknown"
        provider = r.get("surveySource", "N/A")
        try:
            object_time = r["_id"].generation_time
        except:
            object_time = "N/A"
            
        print(f"  - [GenTime: {object_time}] [FieldTime: {created}] RID: {rid} | Status: {status} | Provider: {provider}")

if __name__ == "__main__":
    check_all_recent()
