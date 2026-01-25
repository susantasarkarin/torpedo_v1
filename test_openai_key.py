"""
Test OpenAI API Key validity
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
api_key = config.get('openai_api_key') if config else None

if not api_key:
    print("ERROR: No OpenAI API key found in database!")
    exit(1)

print(f"Testing OpenAI API key: {api_key[:10]}...{api_key[-4:]}")

try:
    from openai import OpenAI
    
    openai_client = OpenAI(api_key=api_key)
    
    # Test with a minimal API call
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=5
    )
    
    print("\n✅ OpenAI API key is VALID!")
    print(f"   Response: {response.choices[0].message.content}")
    print(f"   Model: {response.model}")
    
except Exception as e:
    print(f"\n❌ OpenAI API key FAILED!")
    print(f"   Error: {e}")
    print("\n   Please update your OpenAI API key in Settings.")
