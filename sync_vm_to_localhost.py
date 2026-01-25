"""Sync VM settings to localhost MongoDB"""
from pymongo import MongoClient
from datetime import datetime
import json
import os
from dotenv import load_dotenv

load_dotenv()

print("="*60)
print("SYNCING VM SETTINGS TO LOCALHOST MONGODB")
print("="*60)

# Load VM settings
with open('vm_settings.json', 'r') as f:
    vm_settings = json.load(f)

# Connect to localhost MongoDB
client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['torpedo_settings']

# Get current localhost settings
current = db.app_settings.find_one({'_id': 'app_config'}) or {}

print("\nComparing settings...")
changes = []
for key, vm_value in vm_settings.items():
    current_value = current.get(key)
    if current_value != vm_value:
        if 'key' in key.lower() or 'secret' in key.lower():
            cv = f"...{str(current_value)[-4:]}" if current_value and len(str(current_value)) > 4 else str(current_value)
            vv = f"...{str(vm_value)[-4:]}" if vm_value and len(str(vm_value)) > 4 else str(vm_value)
            changes.append(f"  {key}: {cv} → {vv}")
        else:
            changes.append(f"  {key}: {current_value} → {vm_value}")

if changes:
    print("\nChanges to apply:")
    for c in changes:
        print(c)
else:
    print("\n✅ All settings already in sync!")

# Apply the update
vm_settings['last_synced_from_vm'] = datetime.now().isoformat()
vm_settings['sync_source'] = 'VM 139.59.32.72'

result = db.app_settings.update_one(
    {'_id': 'app_config'},
    {'$set': vm_settings},
    upsert=True
)

print(f"\n✅ Settings synced to localhost MongoDB!")
print(f"   Modified: {result.modified_count}")
print(f"   Synced at: {datetime.now().isoformat()}")
