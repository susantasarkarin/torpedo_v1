from pymongo import MongoClient
from bson import ObjectId

client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
db = client['email_automation']
leads = list(db['leads_enriched'].find({'email': {'$ne': None}}, {'_id': 1, 'email': 1, 'name': 1}).limit(10))

print("Leads with emails:")
for l in leads:
    print(f"  {str(l['_id'])}: {l.get('email')} - {l.get('name')}")

# Check count
count_with_email = db['leads_enriched'].count_documents({'email': {'$ne': None}})
print(f"\nTotal leads with email: {count_with_email}")

# Check if any are already transferred
transferred = db['leads_enriched'].count_documents({'transferred_to_vendor_leads': True})
print(f"Total leads already transferred: {transferred}")

# Get leads NOT transferred
not_transferred = list(db['leads_enriched'].find(
    {'transferred_to_vendor_leads': {'$ne': True}, 'email': {'$ne': None}},
    {'_id': 1, 'email': 1, 'name': 1}
).limit(10))

print("\nLeads NOT transferred (with email):")
for l in not_transferred:
    print(f"  {str(l['_id'])}: {l.get('email')} - {l.get('name')}")
