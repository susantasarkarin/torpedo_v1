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

# Compare WORKING vs BROKEN respondents
print("=" * 70)
print("WORKING RESPONDENT 1: 698585c106f61e8d32dd34ab (4min 28sec)")
doc1 = db.url_parameters.find_one({"_id": ObjectId("698585c106f61e8d32dd34ab")})
if doc1:
    print(f"  IP: {doc1.get('clientIp')}")
    print(f"  IP Source: {doc1.get('ipSource')}")
    print(f"  Survey: {doc1.get('assignedSurveyId')}")
    print(f"  Created: {doc1.get('createdAt')}")
    print(f"  UA: {doc1.get('userAgent', '')[:80]}...")

print("=" * 70)
print("WORKING RESPONDENT 2: 698585b206f61e8d32dd34a7 (3min 22sec)")
doc2 = db.url_parameters.find_one({"_id": ObjectId("698585b206f61e8d32dd34a7")})
if doc2:
    print(f"  IP: {doc2.get('clientIp')}")
    print(f"  IP Source: {doc2.get('ipSource')}")
    print(f"  Survey: {doc2.get('assignedSurveyId')}")
    print(f"  Created: {doc2.get('createdAt')}")
    print(f"  UA: {doc2.get('userAgent', '')[:80]}...")

# Broken ones
broken_ids = [
    "6985e7ca5f4c596ea301d46f",  # Latest - 14:09
    "6985dea17fa5647045397779",  # 13:32
    "6985b3357fa564704539732b",  # 10:25
    "6985a3467fa5647045397195",  # 09:16
    "69858c8d660ed7d7ede5b8b1",  # 07:41
]

for bid in broken_ids:
    print("=" * 70)
    print(f"BROKEN: {bid}")
    try:
        doc = db.url_parameters.find_one({"_id": ObjectId(bid)})
        if doc:
            print(f"  IP: {doc.get('clientIp')}")
            print(f"  IP Source: {doc.get('ipSource')}")
            print(f"  Survey: {doc.get('assignedSurveyId')}")
            print(f"  Created: {doc.get('createdAt')}")
            print(f"  Status: {doc.get('status')}")
            print(f"  UA: {doc.get('userAgent', '')[:80]}...")
        else:
            print("  NOT FOUND in MongoDB")
    except Exception as e:
        print(f"  ERROR: {e}")

# Check CPX entry guards for all
print("\n" + "=" * 70)
print("CPX ENTRY GUARDS:")
for bid in ["698585c106f61e8d32dd34ab", "698585b206f61e8d32dd34a7"] + broken_ids:
    guard = db.cpx_entry_guards.find_one({"ext_user_id": bid})
    if guard:
        print(f"  {bid}: status={guard.get('status')}, created={guard.get('created_at')}")
    else:
        print(f"  {bid}: NO GUARD")
