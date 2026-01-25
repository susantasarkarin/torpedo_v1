"""
Check and test OpenAI API key from database
"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
settings_db = client['torpedo_settings']
app_settings = settings_db['app_settings']

config = app_settings.find_one({'_id': 'app_config'})
key = config.get('openai_api_key', '') if config else ''

print(f"Key length: {len(key)}")
print(f"Key prefix: {key[:15] if len(key) > 15 else key}")
print(f"Key suffix: {key[-8:] if len(key) > 8 else key}")
print(f"Last updated: {config.get('last_updated') if config else 'N/A'}")

if key:
    try:
        from openai import OpenAI
        client_ai = OpenAI(api_key=key)
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=5
        )
        print(f"\n✅ Key is VALID! Response: {response.choices[0].message.content}")
    except Exception as e:
        print(f"\n❌ Key is INVALID: {e}")
else:
    print("\n❌ No key found in database!")
