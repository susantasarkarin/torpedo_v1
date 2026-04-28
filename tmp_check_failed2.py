import pymongo
from collections import Counter

client = pymongo.MongoClient('mongodb://localhost:27017')
col = client['email_automation']['leads_raw']

# Check classification_status distribution
print("=== classification_status distribution ===")
s = Counter(str(d.get('classification_status', 'NONE')) for d in col.find({}))
for k, v in s.most_common(15):
    print(f"  {v:6d}  {k}")

# Check the statistics service counts - what query does it use?
print("\n=== docs with no company AND no email (sample 3) ===")
for d in col.find({'$or': [{'email': {'$exists': False}}, {'email': None}, {'email': ''}]}).limit(3):
    print({k: d.get(k) for k in ['name','first_name','email','title','company','classification_status','source']})
