import pymongo
import re
from collections import Counter

db = pymongo.MongoClient()["email_automation"]
leads = db["leads_enriched"]

# Check enrichment fields
samples = list(leads.find({"email": None}).limit(20))

# What fields do they have with values?
print("=== Fields present in no-email leads ===")
s = samples[0]
for k, v in s.items():
    if k != "_id" and v not in [None, "", [], {}]:
        print(f"  {k}: {repr(v)[:80]}")

print("\n=== Can we extract name + company from title? ===")
for s in samples[:8]:
    name = s.get("name", "")
    title = s.get("title", "")
    linkedin = s.get("linkedin_url", "")
    # Try to split name
    clean_name = re.sub(r',.*', '', name).strip()  # remove suffix like ", PhD"
    parts = clean_name.split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""
    print(f"  name='{name}' -> first='{first}' last='{last}'")
    print(f"    title='{title[:60]}'")
    print(f"    linkedin={linkedin}")
    print()

# Check if company_name or company_website is present
has_company_name = leads.count_documents({"email": None, "company_name": {"$nin": [None, ""]}})
has_company_website = leads.count_documents({"email": None, "company_website": {"$nin": [None, ""]}})
print(f"No-email leads with company_name: {has_company_name}")
print(f"No-email leads with company_website: {has_company_website}")

# Check enrichment_source / enriched_at
has_enriched = leads.count_documents({"email": None, "enriched_at": {"$exists": True}})
print(f"No-email leads that were enriched: {has_enriched}")
print(f"No-email leads never enriched: {3442 - has_enriched}")
