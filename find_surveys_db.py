from pymongo import MongoClient

c = MongoClient('mongodb://localhost:27017')

# List all databases
dbs = c.list_database_names()
print("📂 All databases:", dbs)

# Find survey/allocation related databases
survey_dbs = [db for db in dbs if any(k in db.lower() for k in ['survey', 'campaign', 'allocation', 'cpx', 'cint'])]
print(f"\n📋 Survey-related databases: {survey_dbs}")

# Check each for surveys collections
for db_name in survey_dbs:
    db = c[db_name]
    colls = db.list_collection_names()
    survey_colls = [c for c in colls if 'survey' in c.lower()]
    if survey_colls:
        print(f"\n  {db_name}:")
        for coll_name in survey_colls:
            count = db[coll_name].count_documents({})
            print(f"    - {coll_name}: {count} documents")
