from pymongo import MongoClient
from bson import ObjectId

client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
db = client['email_automation']

# Get leads that are NOT transferred yet
not_transferred = list(db['leads_enriched'].find(
    {'transferred_to_vendor_leads': {'$ne': True}, 'email': {'$ne': None}},
    {'_id': 1, 'email': 1, 'name': 1}
).skip(15).limit(15))

print("Fresh leads NOT transferred (skip first 15):")
for l in not_transferred:
    print(f"{str(l['_id'])}")
