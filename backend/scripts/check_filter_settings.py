"""Quick script to check and optionally fix filter settings"""
import os
import sys
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv('MONGO_URI'))
db = client['torpedo_settings']

# Check current settings
result = db.app_settings.find_one({'_id': 'survey_filters'})
print("Current filter settings:")
print(result)

# Reset to good defaults
db.app_settings.update_one(
    {'_id': 'survey_filters'},
    {'$set': {'max_loi': 20, 'min_cpi': 1.0, 'deletion_period_days': 3}},
    upsert=True
)
print("\n✅ Settings updated to: max_loi=20, min_cpi=1.0, deletion_period_days=3")

# Verify
result = db.app_settings.find_one({'_id': 'survey_filters'})
print("New filter settings:")
print(result)
