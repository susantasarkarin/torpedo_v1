#!/usr/bin/env python3
from pymongo import MongoClient
client = MongoClient('mongodb://localhost:27017/')
db = client['email_automation']
print('=== AI LEADS DATA ON VM ===')
for coll in ['leads', 'leads_enriched', 'leads_raw']:
    count = db[coll].count_documents({})
    print(coll + ': ' + str(count) + ' documents')
