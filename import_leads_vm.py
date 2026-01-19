#!/usr/bin/env python3
"""Import leads data from JSON exports"""
import json
from bson import json_util
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['email_automation']

import_dir = '/tmp/mongo_import'

for coll_name in ['leads', 'leads_enriched', 'leads_raw']:
    filepath = f'{import_dir}/{coll_name}.json'
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            docs = json.load(f, object_hook=json_util.object_hook)
        
        if docs:
            # Clear existing (optional - keeps VM's existing data)
            # db[coll_name].delete_many({})
            
            # Insert with upsert to avoid duplicates
            inserted = 0
            updated = 0
            for doc in docs:
                doc_id = doc.pop('_id', None)
                if doc_id:
                    result = db[coll_name].update_one(
                        {'_id': doc_id},
                        {'$set': doc},
                        upsert=True
                    )
                    if result.upserted_id:
                        inserted += 1
                    elif result.modified_count > 0:
                        updated += 1
                else:
                    db[coll_name].insert_one(doc)
                    inserted += 1
            
            print(f'{coll_name}: {inserted} inserted, {updated} updated')
        else:
            print(f'{coll_name}: No documents found in export')
            
    except FileNotFoundError:
        print(f'{coll_name}: File not found at {filepath}')
    except Exception as e:
        print(f'{coll_name}: Error - {e}')

# Verify counts
print('\n=== Final Counts ===')
for coll_name in ['leads', 'leads_enriched', 'leads_raw']:
    count = db[coll_name].count_documents({})
    print(f'{coll_name}: {count} documents')
