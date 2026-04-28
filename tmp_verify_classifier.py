"""Verify rule-based classifier is working: check pending/classified counts and test one lead."""
import pymongo, datetime, time

col = pymongo.MongoClient()['email_automation']['leads_raw']
enriched = pymongo.MongoClient()['email_automation']['leads_enriched']

# Status distribution
from collections import Counter
status_counts = Counter(str(d.get('classification_status', 'NONE')) for d in col.find({}, {'classification_status': 1}))
print("=== leads_raw status distribution ===")
for status, count in status_counts.most_common():
    print(f"  {count:>6}  {status}")

print(f"\n=== leads_enriched total ===")
print(f"  {enriched.count_documents({})} leads in leads_enriched")

# Check if Pending leads exist (the ones we reset)
pending = col.count_documents({'classification_status': {'$in': ['Pending', 'pending']}})
print(f"\n=== Pending leads (awaiting classification) ===")
print(f"  {pending} pending")

# Sample a Pending lead and run rule-based classification manually
sample = col.find_one({'classification_status': {'$in': ['Pending', 'pending']}})
if sample:
    print(f"\n=== Sample pending lead ===")
    print(f"  name={sample.get('name')} | title={sample.get('title','')[:50]} | industry={sample.get('company_industry','')}")

    # Test compute_icp_basket directly
    import sys
    sys.path.insert(0, '/var/www/campaign_platform/backend')
    from leads.canonical_ingestion import compute_icp_basket, sync_to_enriched

    basket = compute_icp_basket(sample)
    print(f"\n=== Rule-based basket result ===")
    print(f"  basket_code={basket.get('classification_basket')} | basket_name={basket.get('classification_basket_name')}")
    print(f"  fit_tier={basket.get('fit_tier')} ({basket.get('fit_tier_label')}) | persona={basket.get('persona_label')}")
    print(f"  icp_tags={basket.get('icp_tags')}")

    # Test full sync_to_enriched
    lead_id = str(sample['_id'])
    result = sync_to_enriched(sample, lead_id)
    print(f"\n=== sync_to_enriched result ===")
    print(f"  enriched_id={result}")

    # Verify in enriched collection
    if result:
        doc = enriched.find_one({'_id': pymongo.collection.Collection._objectid_class(result) if hasattr(pymongo.collection.Collection, '_objectid_class') else __import__('bson').ObjectId(result)})
        if doc:
            print(f"  classification_basket={doc.get('classification_basket')} | icp_tags={doc.get('icp_tags')}")
else:
    print("  No pending leads found!")

# Check recent classifications (last 5 mins)
recent = col.count_documents({
    'classification_status': {'$in': ['Classified', 'classified']},
    'classified_at': {'$gte': datetime.datetime.utcnow() - datetime.timedelta(minutes=60)}
})
print(f"\n=== Leads classified in last 60 minutes ===")
print(f"  {recent} leads classified recently")
