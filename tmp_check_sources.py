import pymongo
db = pymongo.MongoClient()["email_automation"]

# Check source values for leads with emails
pipeline = [
    {"$match": {"email": {"$exists": True, "$nin": [None, ""]}}},
    {"$group": {"_id": "$source", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 15}
]
results = list(db["leads_enriched"].aggregate(pipeline))
print("Source distribution for leads with emails:")
for r in results:
    print(f"  {r['_id']}: {r['count']}")

# Check what scan-ai-database would find
ai_sources = {"ai_agent", "web_search", "google_search", "websearch", "ai_database"}
ai_count = db["leads_enriched"].count_documents({
    "source": {"$in": list(ai_sources)},
    "email": {"$exists": True, "$nin": [None, ""]}
})
print(f"\nLeads matching ai_sources filter: {ai_count}")
print(f"(if 0, the Scan AI Database button won't find anything)")
