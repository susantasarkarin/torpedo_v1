import sys, os
sys.path.insert(0, '/var/www/campaign_platform/backend')
os.chdir('/var/www/campaign_platform/backend')
from pymongo import MongoClient
from datetime import datetime

c = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
print('=== AI Classification Counts ===\n')

keywords = ('classif', 'sentiment', 'ai_log', 'ai_usage', 'ai_daily', 'intent')
for db_name in c.list_database_names():
    if db_name in ('admin', 'config', 'local'):
        continue
    db = c[db_name]
    for coll in db.list_collection_names():
        if any(kw in coll for kw in keywords):
            cnt = db[coll].count_documents({})
            if cnt > 0:
                print(f'  {db_name}.{coll}: {cnt}')

print('\n--- AI daily usage (last 10 days) ---')
for db_name in c.list_database_names():
    if db_name in ('admin', 'config', 'local'): continue
    db = c[db_name]
    if 'ai_daily_usage' in db.list_collection_names():
        docs = list(db['ai_daily_usage'].find({}, {'date': 1, 'count': 1}).sort('date', -1).limit(10))
        for d in docs:
            print(f"  {d.get('date', '?')} : {d.get('count', 0)} AI calls")

print('\n--- Campaign recipients with reply sentiment ---')
for db_name in c.list_database_names():
    if db_name in ('admin', 'config', 'local'): continue
    db = c[db_name]
    if 'campaign_recipients' in db.list_collection_names():
        total = db['campaign_recipients'].count_documents({'reply_sentiment': {'$exists': True}})
        if total:
            print(f'  {db_name}.campaign_recipients: {total} with sentiment')
            for r in db['campaign_recipients'].aggregate([
                {'$match': {'reply_sentiment': {'$exists': True}}},
                {'$group': {'_id': '$reply_sentiment', 'count': {'$sum': 1}}},
                {'$sort': {'count': -1}}
            ]):
                print(f"    {r['_id']}: {r['count']}")

print('\n--- Leads with AI classification ---')
for db_name in c.list_database_names():
    if db_name in ('admin', 'config', 'local'): continue
    db = c[db_name]
    if 'leads' in db.list_collection_names():
        n = db['leads'].count_documents({'seniority_level': {'$exists': True}})
        if n: print(f'  {db_name}.leads with seniority_level: {n}')
        n2 = db['leads'].count_documents({'reply_sentiment': {'$exists': True}})
        if n2: print(f'  {db_name}.leads with reply_sentiment: {n2}')
