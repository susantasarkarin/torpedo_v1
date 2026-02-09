from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017/")

# List all databases
print("Databases:")
for db_name in client.list_database_names():
    print(f"  {db_name}")
    db = client[db_name]
    for coll_name in db.list_collection_names():
        count = db[coll_name].estimated_document_count()
        if count > 0 and "cint" in coll_name.lower():
            print(f"    - {coll_name}: {count} documents")
        elif count > 0 and "survey" in coll_name.lower():
            print(f"    - {coll_name}: {count} documents")

# Also check campaign_platform collections
print("\nAll collections in campaign_platform:")
db = client["campaign_platform"]
for coll_name in db.list_collection_names():
    count = db[coll_name].estimated_document_count()
    print(f"  {coll_name}: {count}")
