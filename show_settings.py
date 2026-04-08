from pymongo import MongoClient
doc = MongoClient()["torpedo_settings"]["app_settings"].find_one()
if doc:
    for k, v in sorted(doc.items()):
        if k != "_id":
            print(f"{k}: {repr(v)[:80]}")
