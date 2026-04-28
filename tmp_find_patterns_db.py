import pymongo
c = pymongo.MongoClient()
for db_name in c.list_database_names():
    db = c[db_name]
    if "email_patterns" in db.list_collection_names():
        count = db["email_patterns"].count_documents({})
        print(f"DB: {db_name}, email_patterns count: {count}")
