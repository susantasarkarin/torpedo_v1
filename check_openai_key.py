#!/usr/bin/env python3
from pymongo import MongoClient
client = MongoClient('mongodb://localhost:27017/')
settings = client['torpedo_settings']['app_settings'].find_one({'_id': 'app_config'})
if settings:
    has_openai = bool(settings.get('openai_api_key'))
    print('OpenAI key configured:', has_openai)
    if has_openai:
        key = settings.get('openai_api_key', '')
        print('Key prefix:', key[:10] + '...' if len(key) > 10 else 'N/A')
else:
    print('No settings found')
