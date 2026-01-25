"""Fetch all API keys and settings from VM MongoDB"""
from pymongo import MongoClient
import json

print("="*60)
print("FETCHING ALL SETTINGS FROM VM MONGODB")
print("="*60)

client = MongoClient()
db = client['torpedo_settings']

# Get all settings
config = db.app_settings.find_one({'_id': 'app_config'})

if config:
    # Print all keys (masked)
    print("\nAPI Keys found in VM:")
    for key, value in config.items():
        if key == '_id':
            continue
        if 'key' in key.lower() or 'secret' in key.lower() or 'token' in key.lower():
            if value and len(str(value)) > 10:
                print(f"  {key}: {str(value)[:15]}...{str(value)[-4:]}")
            else:
                print(f"  {key}: {value}")
        else:
            print(f"  {key}: {value}")
    
    # Save to JSON for transfer
    # Remove _id for transfer
    config_export = {k: v for k, v in config.items() if k != '_id'}
    with open('/tmp/vm_settings.json', 'w') as f:
        json.dump(config_export, f, indent=2, default=str)
    print("\n✅ Settings exported to /tmp/vm_settings.json")
else:
    print("❌ No config found in VM")
