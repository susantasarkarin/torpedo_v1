import pymongo
import datetime
import re

client = pymongo.MongoClient('mongodb://localhost:27017')
col_raw = client['email_automation']['leads_raw']
col_enriched = client['email_automation']['leads_enriched']

# 1. Reset Failed -> Pending
result = col_raw.update_many(
    {'classification_status': 'Failed'},
    {'$set': {'classification_status': 'Pending', 'classification_attempts': 0, 'retried_at': datetime.datetime.utcnow()}}
)
print(f'Reset to Pending: {result.modified_count}')

# 2. Clean LinkedIn suffix from leads_raw
SUFFIX_RE = re.compile(r'\s*\|.*$')

def clean(val):
    if val and isinstance(val, str):
        return SUFFIX_RE.sub('', val).strip()
    return val

cleaned_raw = 0
for doc in col_raw.find({'name': {'$regex': r'\|'}}):
    updates = {}
    for field in ('name', 'title', 'first_name'):
        orig = doc.get(field)
        c = clean(orig)
        if c != orig:
            updates[field] = c
    if updates:
        col_raw.update_one({'_id': doc['_id']}, {'$set': updates})
        cleaned_raw += 1

print(f'Cleaned raw names: {cleaned_raw}')

# 3. Clean LinkedIn suffix from leads_enriched
cleaned_enriched = 0
for doc in col_enriched.find({'name': {'$regex': r'\|'}}):
    updates = {}
    for field in ('name', 'title', 'first_name'):
        orig = doc.get(field)
        c = clean(orig)
        if c != orig:
            updates[field] = c
    if updates:
        col_enriched.update_one({'_id': doc['_id']}, {'$set': updates})
        cleaned_enriched += 1

print(f'Cleaned enriched names: {cleaned_enriched}')
print('Done.')
