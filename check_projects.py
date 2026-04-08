from pymongo import MongoClient
db = MongoClient()['email_automation']

print("=== projects ===")
for p in db.projects.find():
    print(p)

print("\n=== icp_configs ===")
for c in db.icp_configs.find():
    print({k:v for k,v in c.items() if k != '_id'})

print("\n=== icp_segments ===")
for s in db.icp_segments.find():
    print({k:v for k,v in s.items() if k != '_id'})
