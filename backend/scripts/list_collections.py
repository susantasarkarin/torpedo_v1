"""List all collections with data"""
import sys
import os
sys.path.insert(0, "/var/www/campaign_platform/backend")
os.chdir("/var/www/campaign_platform/backend")

from database import get_database
db = get_database("email_automation")

print("Collections with documents:")
for c in sorted(db.list_collection_names()):
    count = db[c].count_documents({})
    if count > 0:
        print(f"  {c}: {count} docs")
        # Show first doc for relevant collections
        if "gmail" in c.lower() or "mail" in c.lower() or "config" in c.lower() or "setting" in c.lower():
            doc = db[c].find_one()
            if doc:
                # Print keys only for readability
                print(f"    Keys: {list(doc.keys())}")
