from pymongo import MongoClient

client = MongoClient()
db = client['email_automation']

print("=== Distinct source values in leads_enriched ===")
sources = db.leads_enriched.distinct("source")
for s in sorted(sources) if sources else []:
    count = db.leads_enriched.count_documents({"source": s})
    print(f"  {s}: {count}")

print("\n=== Distinct source values in leads_raw ===")
sources_raw = db.leads_raw.distinct("source")
for s in sorted(sources_raw) if sources_raw else []:
    count = db.leads_raw.count_documents({"source": s})
    print(f"  {s}: {count}")

print("\n=== Sample lead_enriched document (first one) ===")
sample = db.leads_enriched.find_one()
if sample:
    print(f"  source: {sample.get('source')}")
    print(f"  keys: {list(sample.keys())[:15]}")
