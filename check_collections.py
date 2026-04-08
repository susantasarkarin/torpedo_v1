from pymongo import MongoClient
c = MongoClient()

# Check all DBs for anything project/campaign related
for db_name in ['email_automation', 'torpedo', 'campaign_platform']:
    db = c[db_name]
    cols = db.list_collection_names()
    print(f"\n=== {db_name} collections ===")
    for col in cols:
        count = db[col].count_documents({})
        print(f"  {col}: {count}")

# Check campaign collection if it exists
db = c['email_automation']
if 'campaigns' in db.list_collection_names():
    sample = db.campaigns.find_one()
    if sample:
        print('\nCampaign sample fields:', list(sample.keys()))
        print('Campaign name:', sample.get('name',''))
