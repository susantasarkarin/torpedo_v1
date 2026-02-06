from pymongo import MongoClient
from bson import ObjectId
import json

client = MongoClient('mongodb://localhost:27017')
db = client['traffic_flow_db']

# Working respondent
print("=== WORKING DOC KEYS ===")
working = db.url_parameters.find_one({'_id': ObjectId('698585c106f61e8d32dd34ab')})
if working:
    print(list(working.keys()))
    # Print full doc but serialize ObjectIds
    for k, v in working.items():
        if k == '_id':
            print(f"  {k}: {str(v)}")
        elif isinstance(v, dict):
            print(f"  {k}: <dict with keys: {list(v.keys())[:5]}>")
        else:
            val_str = str(v)[:100] if v else 'None'
            print(f"  {k}: {val_str}")
else:
    print("NOT FOUND")

print()
print("=== BROKEN DOC KEYS ===")
broken = db.url_parameters.find_one({'_id': ObjectId('6985eb3f9848c6ddb9b20695')})
if broken:
    print(list(broken.keys()))
    for k, v in broken.items():
        if k == '_id':
            print(f"  {k}: {str(v)}")
        elif isinstance(v, dict):
            print(f"  {k}: <dict with keys: {list(v.keys())[:5]}>")
        else:
            val_str = str(v)[:100] if v else 'None'
            print(f"  {k}: {val_str}")
else:
    print("NOT FOUND")
