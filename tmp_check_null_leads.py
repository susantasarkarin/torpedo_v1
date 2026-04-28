import pymongo
from collections import Counter

db = pymongo.MongoClient()["email_automation"]
leads = db["leads_enriched"]
leads_raw = db["leads_raw"]

# Sample no-email leads
samples = list(leads.find({"email": None}).limit(10))
print("=== Sample leads with email=null ===")
for s in samples[:3]:
    keys_with_values = {k: v for k, v in s.items() if v not in [None, "", [], {}, "_id"]}
    keys_with_values.pop("_id", None)
    print(f"  {keys_with_values}")
    print()

# What fields DO they have?
sample = samples[0] if samples else None
if sample:
    print(f"All fields present: {list(sample.keys())}")

# Check if they have a raw_lead_id link to leads_raw
with_raw_id = sum(1 for s in samples if s.get("raw_lead_id"))
print(f"\nOf 10 sampled no-email leads, {with_raw_id} have raw_lead_id")

# Check leads_raw for any of these
if with_raw_id > 0:
    from bson import ObjectId
    raw_id = samples[0].get("raw_lead_id")
    if raw_id:
        raw = leads_raw.find_one({"_id": ObjectId(str(raw_id)) if not hasattr(raw_id, 'id') else raw_id})
        if raw:
            print(f"Matching raw lead: name={raw.get('name')}, email={raw.get('email')}, company={raw.get('company')}")

# Classification status distribution
status_dist = Counter(s.get("classification_status") for s in leads.find({"email": None}, {"classification_status":1}).limit(500))
print(f"\nClassification status of no-email leads: {dict(status_dist)}")

# Source distribution
source_dist = Counter(s.get("source") for s in leads.find({"email": None}, {"source":1}).limit(500))
print(f"Source distribution: {dict(source_dist)}")
