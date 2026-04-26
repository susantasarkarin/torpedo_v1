from pymongo import MongoClient
c = MongoClient()
db = c.traffic_flow_db
for idx in db.url_parameters.list_indexes():
    print(f"  {idx['name']}: {idx['key']}")
