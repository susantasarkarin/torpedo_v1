from pymongo import MongoClient
from bson import ObjectId

client = MongoClient('mongodb://localhost:27017')
db = client['traffic_flow_db']

# Get the broken respondent's entry link
broken = db.url_parameters.find_one({'_id': ObjectId('6985eb3f9848c6ddb9b20695')})

if broken:
    print("=== BROKEN RESPONDENT FULL DATA ===")
    for k, v in broken.items():
        if k == '_id':
            continue
        if isinstance(v, dict):
            print(f"{k}:")
            for kk, vv in v.items():
                print(f"  {kk}: {str(vv)[:200]}{'...' if len(str(vv)) > 200 else ''}")
        else:
            print(f"{k}: {str(v)[:200]}{'...' if len(str(v)) > 200 else ''}")
else:
    print("NOT FOUND")

# Check CPX entry guard details
print()
print("=== CPX ENTRY GUARD ===")
guard = db.cpx_entry_guards.find_one({'ext_user_id': '6985eb3f9848c6ddb9b20695'})
if guard:
    for k, v in guard.items():
        print(f"{k}: {v}")
else:
    print("NO GUARD FOUND")
