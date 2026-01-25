"""
Update OpenAI API Key in database
Run: python update_openai_key.py YOUR_API_KEY
"""
import sys
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

if len(sys.argv) < 2:
    print("Usage: python update_openai_key.py YOUR_OPENAI_API_KEY")
    print("\nGet your key from: https://platform.openai.com/api-keys")
    sys.exit(1)

new_key = sys.argv[1]

if not new_key.startswith("sk-"):
    print("❌ Invalid key format. OpenAI keys start with 'sk-'")
    sys.exit(1)

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
settings_db = client['torpedo_settings']
app_settings = settings_db['app_settings']

# Update the key
result = app_settings.update_one(
    {'_id': 'app_config'},
    {'$set': {
        'openai_api_key': new_key,
        'last_updated': datetime.utcnow()
    }},
    upsert=True
)

print(f"✅ Key updated! Modified: {result.modified_count}, Upserted: {result.upserted_id is not None}")

# Test the new key
print("\nTesting new key...")
try:
    from openai import OpenAI
    client_ai = OpenAI(api_key=new_key)
    response = client_ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Say OK"}],
        max_tokens=5
    )
    print(f"✅ Key is VALID! Response: {response.choices[0].message.content}")
except Exception as e:
    print(f"❌ Key test failed: {e}")
