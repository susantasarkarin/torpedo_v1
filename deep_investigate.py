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

# Check ALL details including CPX API call timing
print("=" * 70)
print("DETAILED COMPARISON")
print("=" * 70)

# Working one
print("\nWORKING: 698585c106f61e8d32dd34ab")
doc1 = db.url_parameters.find_one({"_id": ObjectId("698585c106f61e8d32dd34ab")})
if doc1:
    print(f"  Created: {doc1.get('createdAt')}")
    print(f"  Assigned: {doc1.get('assignedAt')}")
    print(f"  Survey: {doc1.get('assignedSurveyId')}")
    print(f"  Status: {doc1.get('status')}")
    print(f"  Has guard: ", end="")
    guard = db.cpx_entry_guards.find_one({"ext_user_id": "698585c106f61e8d32dd34ab"})
    print("YES" if guard else "NO")

# Latest broken
print("\nBROKEN: 6985eb3f9848c6ddb9b20695")
doc2 = db.url_parameters.find_one({"_id": ObjectId("6985eb3f9848c6ddb9b20695")})
if doc2:
    print(f"  Created: {doc2.get('createdAt')}")
    print(f"  Assigned: {doc2.get('assignedAt')}")
    print(f"  Survey: {doc2.get('assignedSurveyId')}")
    print(f"  Status: {doc2.get('status')}")
    print(f"  Has guard: ", end="")
    guard = db.cpx_entry_guards.find_one({"ext_user_id": "6985eb3f9848c6ddb9b20695"})
    print("YES" if guard else "NO")

# Check survey 60430947 in the database
print("\n" + "=" * 70)
print("SURVEY 60430947 IN DATABASE")
survey = db.cpx_surveys.find_one({"survey_id": 60430947})
if survey:
    print(f"  Found: YES")
    print(f"  Category: {survey.get('category')}")
    print(f"  LOI: {survey.get('loi')}")
    print(f"  Has href: {'YES' if survey.get('href') else 'NO'}")
    print(f"  Has href_new: {'YES' if survey.get('href_new') else 'NO'}")
    print(f"  Click count: {survey.get('click_count')}")
    print(f"  Last clicked: {survey.get('last_clicked_at')}")
else:
    print("  NOT FOUND")

# Check cpx_research database too
print("\n" + "=" * 70)
print("CPX_RESEARCH DATABASE - SURVEY 60430947")
db2 = client["cpx_research"]
survey2 = db2.cpx_surveys.find_one({"survey_id": 60430947})
if survey2:
    print(f"  Found: YES")
    print(f"  Click count: {survey2.get('click_count')}")
else:
    print("  NOT FOUND")
