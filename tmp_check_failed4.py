import pymongo
from collections import Counter

client = pymongo.MongoClient('mongodb://localhost:27017')
col = client['email_automation']['leads_raw']

# Check last_error on Failed leads
print("=== LAST ERRORS ON FAILED LEADS (sample 5) ===")
for d in col.find({'classification_status': 'Failed'}, {'name': 1, 'last_error': 1, 'source': 1, 'classification_attempts': 1}).limit(5):
    print(f"  name={d.get('name')} | source={d.get('source')} | error={d.get('last_error', 'NONE')}")

# Count unique last_error messages
print("\n=== UNIQUE LAST_ERROR VALUES ===")
errors = Counter()
for d in col.find({'classification_status': 'Failed'}, {'last_error': 1}):
    errors[str(d.get('last_error', 'NONE'))[:120]] += 1
for k, v in errors.most_common(10):
    print(f"  {v:6d} | {k}")

# For csv_import failed leads - do they have email?
print("\n=== CSV_IMPORT FAILED - FIELD CHECK ===")
total_csv_failed = col.count_documents({'classification_status': 'Failed', 'source': 'csv_import'})
csv_with_email = col.count_documents({'classification_status': 'Failed', 'source': 'csv_import', 'email': {'$exists': True, '$ne': None, '$ne': ''}})
csv_with_name = col.count_documents({'classification_status': 'Failed', 'source': 'csv_import', 'name': {'$exists': True, '$ne': None, '$ne': ''}})
print(f"  Total csv_import failed: {total_csv_failed}")
print(f"  Has email: {csv_with_email}")
print(f"  Has name: {csv_with_name}")

# Sample csv_import failed leads
print("\n=== SAMPLE CSV_IMPORT FAILED LEADS ===")
for d in col.find({'classification_status': 'Failed', 'source': 'csv_import'}).limit(3):
    print({k: d.get(k) for k in ['name', 'first_name', 'email', 'title', 'company', 'last_error']})
