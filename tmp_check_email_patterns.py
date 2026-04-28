import pymongo
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["email_automation"]
coll = db["email_patterns"]

total = coll.count_documents({})
print(f"Total patterns: {total}")

if total > 0:
    sample = list(coll.find({}, {"domain":1,"pattern":1,"confidence":1,"sample_count":1}).limit(5))
    for s in sample:
        s.pop("_id", None)
        print(s)
    
    # Check how many have non-null pattern
    with_pattern = coll.count_documents({"pattern": {"$exists": True, "$ne": None, "$ne": ""}})
    print(f"\nPatterns with non-null 'pattern' field: {with_pattern}")
    
    # Check confidence distribution
    high = coll.count_documents({"confidence": {"$gte": 0.8}})
    med = coll.count_documents({"confidence": {"$gte": 0.5, "$lt": 0.8}})
    low = coll.count_documents({"confidence": {"$lt": 0.5}})
    print(f"High conf (>=0.8): {high}, Med (0.5-0.8): {med}, Low (<0.5): {low}")
else:
    print("Collection is EMPTY - no patterns discovered yet!")
    print("User needs to click 'Run Analysis' or 'Scan AI Database'")
