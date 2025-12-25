from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['email_automation']

# Rename vendorNo to vid in all vendor documents
result = db.vendors.update_many({}, {'$rename': {'vendorNo': 'vid'}})
print(f'Updated {result.modified_count} vendor records: renamed vendorNo to vid')

# Verify the change
vendors = list(db.vendors.find({}, {'vid': 1, 'vendorName': 1}))
print(f'\nVerifying vendors:')
for v in vendors:
    print(f"  - {v.get('vendorName')}: vid = {v.get('vid')}")
