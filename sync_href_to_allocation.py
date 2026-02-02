from pymongo import MongoClient
from datetime import datetime

c = MongoClient('mongodb://localhost:27017')

# Get all CPX surveys from cpx_research.cpx_surveys with href
cpx_surveys = {
    str(s['_id']): s.get('href', '')
    for s in c.cpx_research.cpx_surveys.find({'href': {'$exists': True, '$ne': ''}}, {'_id': 1, 'href': 1})
}

print(f"📋 Found {len(cpx_surveys)} CPX surveys with href in cpx_research.cpx_surveys")

# Update survey_allocation.surveys with href field
updated = 0
skipped = 0

for survey_id, href in cpx_surveys.items():
    # Update survey in allocation DB if it exists
    result = c.survey_allocation.surveys.update_one(
        {'external_id': survey_id, 'provider': 'CPX'},
        {'$set': {'href': href, 'updated_at': datetime.utcnow()}}
    )
    if result.modified_count > 0:
        updated += 1
    else:
        skipped += 1

print(f"✅ Updated {updated} surveys in survey_allocation.surveys with href field")
print(f"⏭️  Skipped {skipped} surveys (not found in allocation DB or already updated)")

# Verify
with_href = c.survey_allocation.surveys.count_documents({'provider': 'CPX', 'href': {'$exists': True, '$ne': ''}})
print(f"📊 Total CPX surveys with href: {with_href}")

# Show sample
sample = c.survey_allocation.surveys.find_one({'provider': 'CPX', 'href': {'$exists': True, '$ne': ''}})
if sample:
    print(f"\n📋 Sample survey with href:")
    print(f"  external_id: {sample.get('external_id')}")
    print(f"  href: {sample['href'][:150]}...")
