import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# Use MONGO_URI from environment, fallback to localhost
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
print(f"Connecting to: {MONGO_URI[:30]}...")  # Only show first 30 chars for security

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']

# Copy vendorNo to vid for all vendors that have vendorNo but no vid
vendors = db.vendors.find({})
updated_count = 0

for vendor in vendors:
    vendor_no = vendor.get('vendorNo')
    vid = vendor.get('vid')
    
    # If vendorNo exists but vid doesn't, copy vendorNo to vid
    if vendor_no and not vid:
        db.vendors.update_one(
            {'_id': vendor['_id']},
            {'$set': {'vid': vendor_no}}
        )
        updated_count += 1
    # If vid exists but vendorNo doesn't, copy vid to vendorNo
    elif vid and not vendor_no:
        db.vendors.update_one(
            {'_id': vendor['_id']},
            {'$set': {'vendorNo': vid}}
        )
        updated_count += 1

print(f'Updated {updated_count} vendor records: synced vendorNo and vid')

# Verify the change
vendors = list(db.vendors.find({}, {'vid': 1, 'vendorName': 1}))
print(f'\nVerifying vendors:')
for v in vendors:
    print(f"  - {v.get('vendorName')}: vid = {v.get('vid')}")
