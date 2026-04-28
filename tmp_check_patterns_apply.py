import pymongo
from datetime import datetime

db = pymongo.MongoClient()["email_automation"]

# Check email_patterns collection
coll = db["email_patterns"]
total = coll.count_documents({})
print(f"Total patterns discovered: {total}")

if total > 0:
    high = coll.count_documents({"confidence": {"$gte": 0.8}})
    med = coll.count_documents({"confidence": {"$gte": 0.5, "$lt": 0.8}})
    low = coll.count_documents({"confidence": {"$lt": 0.5}})
    print(f"High (>=80%): {high}  Medium (50-80%): {med}  Low (<50%): {low}")
    
    print("\nSample patterns:")
    samples = list(coll.find({}, {"domain":1,"pattern":1,"confidence":1,"sample_count":1}).sort("confidence",-1).limit(10))
    for s in samples:
        s.pop("_id", None)
        print(f"  {s}")

# Check apply-to-bounced-and-missing logic
print("\n--- Apply Patterns candidates ---")
leads = db["leads_enriched"]

# Bounced leads
bounced = leads.count_documents({"email_status": "bounced"})
print(f"Bounced leads: {bounced}")

# Missing email leads
missing = leads.count_documents({"email": {"$in": [None, ""]}, "company_domain": {"$exists": True, "$nin": [None, ""]}})
missing2 = leads.count_documents({"email": {"$exists": False}, "company_domain": {"$exists": True, "$nin": [None, ""]}})
print(f"Missing email (empty): {missing}")
print(f"Missing email (not exists): {missing2}")

# Check what fields exist
sample_lead = leads.find_one({"email": {"$nin": [None, ""]}})
if sample_lead:
    print(f"\nSample lead fields: {list(sample_lead.keys())}")
    print(f"  email: {sample_lead.get('email')}")
    print(f"  email_status: {sample_lead.get('email_status')}")
    print(f"  company_domain: {sample_lead.get('company_domain')}")
    print(f"  domain: {sample_lead.get('domain')}")
