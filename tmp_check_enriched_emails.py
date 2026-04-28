import pymongo
db = pymongo.MongoClient()["email_automation"]
count = db["leads_enriched"].count_documents({"email": {"$exists": True, "$nin": [None, ""]}})
print(f"Leads with email in leads_enriched: {count}")
samples = list(db["leads_enriched"].find({"email": {"$exists": True, "$nin": [None, ""]}}, {"email": 1}).limit(5))
for s in samples:
    print(" ", s.get("email"))
