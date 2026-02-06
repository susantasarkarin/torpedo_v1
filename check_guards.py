from pymongo import MongoClient
from bson import ObjectId
import json
from datetime import datetime

client = MongoClient("mongodb://localhost:27017/")
db = client["traffic_flow_db"]

class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, ObjectId)):
            return str(obj)
        return super().default(obj)

# Check entry guards
print("=" * 60)
print("CPX ENTRY GUARDS FOR RESPONDENT 1: 698585c106f61e8d32dd34ab")
guard1 = db.cpx_entry_guards.find_one({"ext_user_id": "698585c106f61e8d32dd34ab"})
print(json.dumps(guard1, indent=2, cls=DateEncoder) if guard1 else "No guard found")

print("=" * 60)
print("CPX ENTRY GUARDS FOR RESPONDENT 2: 698585b206f61e8d32dd34a7")
guard2 = db.cpx_entry_guards.find_one({"ext_user_id": "698585b206f61e8d32dd34a7"})
print(json.dumps(guard2, indent=2, cls=DateEncoder) if guard2 else "No guard found")

# Also check the cpx_surveys collection for the survey IDs
print("=" * 60)
print("SURVEY 60430947 (used by respondent 1)")
survey1 = db.cpx_surveys.find_one({"survey_id": 60430947})
if survey1:
    print(f"href: {survey1.get('href', 'N/A')[:100]}...")
    print(f"href_new: {survey1.get('href_new', 'N/A')[:100]}...")
else:
    print("Survey not found")

print("=" * 60)
print("SURVEY 59937461 (used by respondent 2)")
survey2 = db.cpx_surveys.find_one({"survey_id": 59937461})
if survey2:
    print(f"href: {survey2.get('href', 'N/A')[:100]}...")
    print(f"href_new: {survey2.get('href_new', 'N/A')[:100]}...")
else:
    print("Survey not found")
