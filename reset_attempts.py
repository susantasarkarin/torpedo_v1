"""
Reset classification_attempts for all stuck pending/failed leads.
Run once to unblock leads that hit the OpenAI 429 wall.
"""
import sys
sys.path.insert(0, '/var/www/campaign_platform/backend')

from pymongo import MongoClient
from datetime import datetime

db = MongoClient('mongodb://localhost:27017/')['email_automation']

result = db.leads_raw.update_many(
    {
        'classification_status': {'$in': ['pending', 'Pending', 'failed', 'Failed', 'Processing', 'processing']},
    },
    {
        '$set': {
            'classification_status': 'pending',
            'classification_attempts': 0,
        }
    }
)
print(f"Reset {result.modified_count} leads → attempts=0, status=pending")
print(f"Total pending now:", db.leads_raw.count_documents({'classification_status': 'pending'}))
