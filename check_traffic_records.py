"""
Check traffic records in the database to understand what data exists.
"""
import os
from datetime import datetime, timedelta
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def check_traffic_records():
    """Check what traffic records exist in the database."""
    
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    print(f"📡 Connecting to MongoDB...")
    
    client = MongoClient(mongo_uri)
    traffic_db = client["traffic_flow_db"]
    url_parameters = traffic_db["url_parameters"]
    
    # Get total count
    total_count = url_parameters.count_documents({})
    print(f"\n📊 Total traffic records: {total_count}")
    
    if total_count == 0:
        print("⚠️ No traffic records in database")
        return
    
    # Get sample records to understand schema
    print("\n📋 Sample record schema:")
    sample = url_parameters.find_one({})
    if sample:
        for key, value in sample.items():
            value_type = type(value).__name__
            value_preview = str(value)[:80] if value else "None"
            print(f"   • {key}: ({value_type}) {value_preview}")
    
    # Get date range
    print("\n📅 Date range analysis:")
    
    # Check createdAt field
    oldest_by_created = url_parameters.find_one(
        {"createdAt": {"$exists": True}}, 
        sort=[("createdAt", 1)]
    )
    newest_by_created = url_parameters.find_one(
        {"createdAt": {"$exists": True}}, 
        sort=[("createdAt", -1)]
    )
    
    if oldest_by_created and oldest_by_created.get("createdAt"):
        print(f"   • Oldest record (createdAt): {oldest_by_created['createdAt']}")
    if newest_by_created and newest_by_created.get("createdAt"):
        print(f"   • Newest record (createdAt): {newest_by_created['createdAt']}")
    
    # Check timestamp field (legacy format)
    oldest_by_timestamp = url_parameters.find_one(
        {"timestamp": {"$exists": True}}, 
        sort=[("timestamp", 1)]
    )
    newest_by_timestamp = url_parameters.find_one(
        {"timestamp": {"$exists": True}}, 
        sort=[("timestamp", -1)]
    )
    
    if oldest_by_timestamp and oldest_by_timestamp.get("timestamp"):
        print(f"   • Oldest record (timestamp): {oldest_by_timestamp['timestamp']}")
    if newest_by_timestamp and newest_by_timestamp.get("timestamp"):
        print(f"   • Newest record (timestamp): {newest_by_timestamp['timestamp']}")
    
    # Count records with entry links
    with_redirect = url_parameters.count_documents({"redirectUrl": {"$exists": True, "$ne": None, "$ne": ""}})
    print(f"\n📎 Records with entry links (redirectUrl): {with_redirect}")
    
    # Count by status
    print("\n📊 Records by status:")
    statuses = url_parameters.distinct("status")
    for status in statuses:
        count = url_parameters.count_documents({"status": status})
        print(f"   • {status}: {count}")
    
    # Show recent records with entry links
    print("\n📋 Recent records with entry links (last 10):")
    recent_with_links = list(url_parameters.find(
        {"redirectUrl": {"$exists": True, "$ne": None, "$ne": ""}}
    ).sort("createdAt", -1).limit(10))
    
    for rec in recent_with_links:
        sfwid = str(rec.get("_id", ""))[:12]
        created = rec.get("createdAt", rec.get("timestamp", "?"))
        status = rec.get("status", "?")
        link = rec.get("redirectUrl", "")[:60]
        print(f"   [{sfwid}] ({created}) {status} -> {link}...")


if __name__ == "__main__":
    check_traffic_records()
