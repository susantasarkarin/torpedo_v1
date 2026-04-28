import pymongo
from collections import Counter

client = pymongo.MongoClient('mongodb://localhost:27017')
col = client['email_automation']['leads_raw']

# Check Failed leads - what data do they have?
print("=== SAMPLE FAILED LEADS ===")
for d in col.find({'classification_status': 'Failed'}).limit(5):
    print({k: d.get(k) for k in ['name', 'first_name', 'email', 'title', 'company', 'source', 'classification_attempts', 'classification_error']})
    print()

# What sources are the Failed leads from?
print("=== FAILED LEADS BY SOURCE ===")
src = Counter(str(d.get('source', 'NONE')) for d in col.find({'classification_status': 'Failed'}))
for k, v in src.most_common(10):
    print(f"  {v:6d}  {k}")

# Check classification_attempts distribution for Failed
print("\n=== FAILED - ATTEMPTS DISTRIBUTION ===")
attempts = Counter(d.get('classification_attempts', 0) for d in col.find({'classification_status': 'Failed'}))
for k, v in sorted(attempts.items()):
    print(f"  {k} attempts: {v}")

# Check what error message they have
print("\n=== FAILED ERROR MESSAGES (sample) ===")
errors = Counter()
for d in col.find({'classification_status': 'Failed'}, {'classification_error': 1}):
    err = str(d.get('classification_error', 'NONE'))[:120]
    errors[err] += 1
for k, v in errors.most_common(8):
    print(f"  {v:5d} | {k}")
