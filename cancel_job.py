from pymongo import MongoClient
from datetime import datetime

client = MongoClient('mongodb://139.59.32.72:27017/')
db = client['email_automation']

result = db.web_search_jobs.update_one(
    {'job_id': 'e65a7b78'}, 
    {'$set': {'status': 'CANCELLED', 'completed_at': datetime.utcnow()}}
)
print(f'Modified: {result.modified_count}')

job = db.web_search_jobs.find_one({'job_id': 'e65a7b78'}, {'job_id': 1, 'status': 1})
print(f'Job status: {job}')
