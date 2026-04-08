from pymongo import MongoClient
c = MongoClient()
for dbname in ['torpedo_settings', 'email_automation', 'torpedo', 'campaign_platform']:
    db = c[dbname]
    colls = db.list_collection_names()
    print(f"\nDB: {dbname} — collections: {colls}")
    for coll in colls:
        if 'setting' in coll.lower() or 'config' in coll.lower() or 'key' in coll.lower() or 'gemini' in coll.lower():
            docs = list(db[coll].find({'key': {'$regex': 'gemini'}}, {'key': 1, 'value': 1}))
            if docs:
                print(f"  Found in {coll}:")
                for d in docs:
                    print(f"    {d['key']}: {str(d.get('value',''))[:25]}")
