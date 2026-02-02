from pymongo import MongoClient
from datetime import datetime

c = MongoClient('mongodb://localhost:27017')

# Activate CPX surveys that have href field
result = c.campaign_platform.surveys.update_many(
    {'provider': 'CPX', 'href': {'$exists': True, '$ne': ''}},
    {'$set': {'status': 'active', 'updated_at': datetime.utcnow()}}
)

print(f"✅ Activated {result.modified_count} CPX surveys with href field")

# Check active surveys now
active_count = c.campaign_platform.surveys.count_documents({'provider': 'CPX', 'status': 'active'})
print(f"📊 Total active CPX surveys: {active_count}")

# Show a sample
sample = c.campaign_platform.surveys.find_one({'provider': 'CPX', 'status': 'active'})
if sample:
    print(f"\n📋 Sample survey:")
    print(f"  external_id: {sample.get('external_id')}")
    print(f"  has href: {'href' in sample}")
    if 'href' in sample:
        print(f"  href: {sample['href'][:150]}...")
