#!/bin/bash
python3 -c "
from pymongo import MongoClient
import json
db = MongoClient()['torpedo_gmail']
m = db['workspace_mailboxes'].find_one({'email': 'indira@surveyfieldwork.com'})
for k, v in m.items():
    if k != '_id':
        print(f'{k}: {repr(v)[:200]}')
"
