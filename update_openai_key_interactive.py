"""
Update OpenAI API Key in the database.
Usage: python update_openai_key_interactive.py
"""
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

print("="*60)
print("OPENAI API KEY UPDATE UTILITY")
print("="*60)

# Connect to MongoDB
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
settings_db = client['torpedo_settings']
app_settings = settings_db['app_settings']

# Show current key
config = app_settings.find_one({'_id': 'app_config'})
current_key = config.get('openai_api_key', '') if config else ''
print(f"\nCurrent key in DB: {current_key[:15]}...{current_key[-4:] if current_key else 'NONE'}")

# Get new key
print("\nPlease paste your new OpenAI API key:")
new_key = input().strip()

if not new_key:
    print("❌ No key provided. Exiting.")
    exit(1)

if not new_key.startswith('sk-'):
    print("⚠️ Warning: Key doesn't start with 'sk-'. Are you sure this is correct? (y/n)")
    if input().strip().lower() != 'y':
        exit(1)

# Test the key first
print("\n🔄 Testing the new key...")
try:
    from openai import OpenAI
    test_client = OpenAI(api_key=new_key)
    response = test_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Say OK"}],
        max_tokens=5
    )
    print(f"✅ Key is valid! Test response: {response.choices[0].message.content}")
except Exception as e:
    print(f"❌ Key test failed: {e}")
    print("Do you still want to save this key? (y/n)")
    if input().strip().lower() != 'y':
        exit(1)

# Update the database
result = app_settings.update_one(
    {'_id': 'app_config'},
    {'$set': {
        'openai_api_key': new_key,
        'openai_key_updated_at': datetime.now().isoformat()
    }},
    upsert=True
)

print(f"\n✅ OpenAI API key updated in database!")
print(f"   New key: {new_key[:15]}...{new_key[-4:]}")
print(f"   Updated at: {datetime.now().isoformat()}")
print("\n✅ You can now run: python test_openai_web_search.py")
