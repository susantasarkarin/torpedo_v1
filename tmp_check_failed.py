import pymongo
from collections import Counter

client = pymongo.MongoClient('mongodb://localhost:27017')
db = client['email_automation']
col = db['leads_raw']

# Sample failed leads
print("=== SAMPLE FAILED LEADS ===")
sample = list(col.find({'classification_status': 'failed'}, {
    'name': 1, 'first_name': 1, 'last_name': 1,
    'email': 1, 'source': 1, 'classification_error': 1,
    'title': 1, 'company': 1
}).limit(5))
for d in sample:
    d.pop('_id', None)
    print(d)
    print()

# Count unique error messages
print("\n=== ERROR BREAKDOWN ===")
errors = Counter()
for doc in col.find({'classification_status': 'failed'}, {'classification_error': 1}):
    err = str(doc.get('classification_error', 'NONE'))[:120]
    errors[err] += 1
for k, v in errors.most_common(10):
    print(f"  {v:5d} | {k}")

# Check what fields exist on failed leads
print("\n=== FIELD PRESENCE ON FAILED LEADS (sample 100) ===")
fields = Counter()
for doc in col.find({'classification_status': 'failed'}).limit(100):
    for f in ['name', 'first_name', 'email', 'title', 'company', 'company_domain', 'linkedin_url']:
        if doc.get(f):
            fields[f] += 1
for k, v in sorted(fields.items()):
    print(f"  {k}: {v}/100")
