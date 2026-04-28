import sys
sys.path.insert(0, '/var/www/campaign_platform/backend')

import pymongo

client = pymongo.MongoClient("mongodb://localhost:27017/")
col = client["email_automation"]["leads_raw"]

# Get a failed lead with attempts=1
doc = col.find_one({"classification_status": "Failed", "classification_attempts": 1})
if not doc:
    doc = col.find_one({"classification_status": "Pending"})

print(f"Lead id: {doc.get('_id')}")
print(f"email: {doc.get('email','(none)')}")
print(f"linkedin_url: {doc.get('linkedin_url','(none)')}")
print(f"icp_segment: {doc.get('icp_segment','(none)')}")
print(f"company_industry: {doc.get('company_industry','(none)')}")

# Try sync_to_enriched
try:
    from leads.canonical_ingestion import sync_to_enriched
    result = sync_to_enriched(doc, str(doc['_id']))
    print(f"\nsync_to_enriched result: {result}")
except Exception as e:
    import traceback
    print(f"\nERROR: {e}")
    traceback.print_exc()
