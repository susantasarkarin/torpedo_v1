from pymongo import MongoClient
from datetime import datetime

c = MongoClient('mongodb://localhost:27017')

# Deactivate CPX surveys that don't have href field (they're outdated)
result = c.survey_allocation.surveys.update_many(
    {'provider': 'CPX', '$or': [{'href': {'$exists': False}}, {'href': ''}]},
    {'$set': {'status': 'paused', 'updated_at': datetime.utcnow()}}
)

print(f"✅ Paused {result.modified_count} outdated CPX surveys (missing href)")

# Count active surveys now
active_with_href = c.survey_allocation.surveys.count_documents({
    'provider': 'CPX',
    'status': 'active',
    'href': {'$exists': True, '$ne': ''}
})

print(f"📊 Active CPX surveys with href: {active_with_href}")

# Show a sample
sample = c.survey_allocation.surveys.find_one({
    'provider': 'CPX',
    'status': 'active',
    'href': {'$exists': True, '$ne': ''}
})

if sample:
    print(f"\n📋 Sample active survey:")
    print(f"  external_id: {sample.get('external_id')}")
    print(f"  href preview: {sample['href'][:150]}...")
else:
    print("\n❌ No active CPX surveys with href found!")
