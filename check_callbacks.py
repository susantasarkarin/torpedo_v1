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

# Check CPX callback logs for the two SFWIDs
print("=" * 60)
print("CPX CALLBACK LOGS FOR SFWID: 698585c106f61e8d32dd34ab")
callbacks1 = list(db.cpx_callback_logs.find({"sfwid": "698585c106f61e8d32dd34ab"}))
for cb in callbacks1:
    print(json.dumps(cb, indent=2, cls=DateEncoder))
if not callbacks1:
    print("No callbacks found")

print("=" * 60)
print("CPX CALLBACK LOGS FOR SFWID: 698585b206f61e8d32dd34a7")
callbacks2 = list(db.cpx_callback_logs.find({"sfwid": "698585b206f61e8d32dd34a7"}))
for cb in callbacks2:
    print(json.dumps(cb, indent=2, cls=DateEncoder))
if not callbacks2:
    print("No callbacks found")

# Check CPX postback logs
print("=" * 60)
print("CPX POSTBACK LOGS (recent)")
postbacks = list(db.cpx_postback_logs.find().sort("timestamp", -1).limit(10))
for pb in postbacks:
    print(json.dumps(pb, indent=2, cls=DateEncoder))
if not postbacks:
    print("No postbacks found")

# Check PM2 logs for these IDs
print("=" * 60)
print("Checking collections available...")
print(db.list_collection_names())
