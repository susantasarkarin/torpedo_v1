#!/usr/bin/env python3
"""Check lead counts for debugging"""

from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['email_automation']

# Raw leads counts
raw_total = db['leads_raw'].count_documents({})
pending = db['leads_raw'].count_documents({'classification_status': 'pending'})
processing = db['leads_raw'].count_documents({'classification_status': 'processing'})
classified = db['leads_raw'].count_documents({'classification_status': 'classified'})
failed = db['leads_raw'].count_documents({'classification_status': 'failed'})

# Source counts in raw
csv_sources = ['csv', 'csv_import', 'google_sheets', 'json_import']
websearch_sources = ['web_search', 'google_search', 'linkedin']
gmail_sources = ['gmail', 'email', 'imap']

raw_csv_count = db['leads_raw'].count_documents({'source': {'$in': csv_sources}})
raw_websearch_count = db['leads_raw'].count_documents({'source': {'$in': websearch_sources}})
raw_gmail_count = db['leads_raw'].count_documents({'source': {'$in': gmail_sources}})

# Classified by source in raw
raw_csv_classified = db['leads_raw'].count_documents({'source': {'$in': csv_sources}, 'classification_status': 'classified'})
raw_websearch_classified = db['leads_raw'].count_documents({'source': {'$in': websearch_sources}, 'classification_status': 'classified'})
raw_csv_pending = db['leads_raw'].count_documents({'source': {'$in': csv_sources}, 'classification_status': 'pending'})

# Enriched counts  
enriched_total = db['leads_enriched'].count_documents({})
enriched_csv = db['leads_enriched'].count_documents({'source': {'$in': csv_sources}})
enriched_websearch = db['leads_enriched'].count_documents({'source': {'$in': websearch_sources}})
enriched_gmail = db['leads_enriched'].count_documents({'source': {'$in': gmail_sources}})

# CSV with email (auto-classified logic)
raw_csv_with_email = db['leads_raw'].count_documents({
    'source': {'$in': csv_sources},
    'email': {'$exists': True, '$ne': '', '$ne': None}
})

print('=== RAW LEADS ===')
print(f'Total: {raw_total}')
print(f'Pending: {pending}')
print(f'Processing: {processing}')
print(f'Classified: {classified}')
print(f'Failed: {failed}')
print()
print('=== RAW BY SOURCE ===')
print(f'CSV Sources: {raw_csv_count}')
print(f'  - Classified: {raw_csv_classified}')
print(f'  - Pending: {raw_csv_pending}')
print(f'  - With Email: {raw_csv_with_email}')
print(f'WebSearch Sources: {raw_websearch_count}')
print(f'Gmail Sources: {raw_gmail_count}')
print()
print('=== ENRICHED LEADS ===')
print(f'Total: {enriched_total}')
print(f'CSV Source: {enriched_csv}')
print(f'WebSearch Source: {enriched_websearch}')
print(f'Gmail Source: {enriched_gmail}')
print()

# Get unique sources
print('=== UNIQUE SOURCES IN RAW ===')
sources = db['leads_raw'].distinct('source')
for s in sources:
    count = db['leads_raw'].count_documents({'source': s})
    print(f'  {s}: {count}')

print()
print('=== UNIQUE SOURCES IN ENRICHED ===')
sources = db['leads_enriched'].distinct('source')
for s in sources:
    count = db['leads_enriched'].count_documents({'source': s})
    print(f'  {s}: {count}')
