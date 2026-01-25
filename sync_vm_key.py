"""Update local MongoDB with VM's OpenAI API key"""
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['torpedo_settings']

key = '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'

result = db.app_settings.update_one(
    {'_id': 'app_config'},
    {'$set': {
        'openai_api_key': key,
        'openai_key_updated_at': datetime.now().isoformat()
    }},
    upsert=True
)

print(f"✅ OpenAI API key updated in local MongoDB!")
print(f"   Key: {key[:20]}...{key[-4:]}")
print(f"   Modified: {result.modified_count}, Upserted: {result.upserted_id is not None}")
