"""
Download Entry Links for Traffic Sent Today
Exports all traffic records from today with their entry links to a CSV file.
If no traffic today, exports all available records.
"""
import os
import csv
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def download_entry_links_today():
    """
    Download all entry links for traffic sent today.
    If no traffic today, exports all available records.
    Exports to CSV file with timestamp.
    """
    # Connect to MongoDB
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    print(f"📡 Connecting to MongoDB...")
    
    client = MongoClient(mongo_uri)
    traffic_db = client["traffic_flow_db"]
    url_parameters = traffic_db["url_parameters"]
    
    # Get today's date range (UTC)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    print(f"📅 Fetching traffic records from {today_start.strftime('%Y-%m-%d %H:%M:%S')} to {today_end.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    # Query for traffic records created today
    query = {
        "$or": [
            {"createdAt": {"$gte": today_start.replace(tzinfo=None), "$lt": today_end.replace(tzinfo=None)}},
            {"timestamp": {"$gte": today_start.isoformat(), "$lt": today_end.isoformat()}}
        ]
    }
    
    # Check count first
    today_count = url_parameters.count_documents(query)
    
    if today_count == 0:
        print(f"⚠️ No traffic records found for today. Fetching ALL available records instead...")
        query = {}  # Get all records
    
    # Fetch records
    records = list(url_parameters.find(query).sort("createdAt", -1))
    
    print(f"✅ Found {len(records)} traffic records for today")
    
    if not records:
        print("⚠️ No traffic records found for today.")
        return
    
    # Generate output filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"entry_links_today_{timestamp}.csv"
    
    # Export to CSV
    fieldnames = [
        "sfwid",
        "entry_link",
        "vendor_id",
        "country_code",
        "respondent_id",
        "status",
        "survey_id",
        "created_at"
    ]
    
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        entry_link_count = 0
        
        for record in records:
            # Get entry link (can be in redirectUrl or entry_link field)
            entry_link = record.get("redirectUrl") or record.get("entry_link") or ""
            
            if entry_link:
                entry_link_count += 1
            
            row = {
                "sfwid": str(record.get("_id", "")),
                "entry_link": entry_link,
                "vendor_id": record.get("vendorId") or record.get("params", {}).get("vid", ""),
                "country_code": record.get("countryCode") or record.get("params", {}).get("cc", ""),
                "respondent_id": record.get("respondentId") or record.get("params", {}).get("rid", ""),
                "status": record.get("status", ""),
                "survey_id": record.get("assignedSurveyId", ""),
                "created_at": record.get("createdAt", record.get("timestamp", ""))
            }
            writer.writerow(row)
    
    print(f"\n📊 Summary:")
    print(f"   • Total records: {len(records)}")
    print(f"   • Records with entry links: {entry_link_count}")
    print(f"   • Records without entry links: {len(records) - entry_link_count}")
    print(f"\n📁 Exported to: {output_file}")
    
    # Also print just the entry links for quick copy
    print(f"\n📋 Entry Links ({entry_link_count} total):")
    print("-" * 80)
    
    for record in records:
        entry_link = record.get("redirectUrl") or record.get("entry_link")
        if entry_link:
            sfwid = str(record.get("_id", ""))[:8]
            status = record.get("status", "?")
            print(f"[{sfwid}] ({status}) {entry_link}")
    
    return output_file


if __name__ == "__main__":
    download_entry_links_today()
