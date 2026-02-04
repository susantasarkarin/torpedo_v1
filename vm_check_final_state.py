from pymongo import MongoClient
import os

mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
client = MongoClient(mongo_uri)

surveys = client["cint_research"]["cint_surveys"]
links = client["cint_research"]["cint_entry_links"]

print("CINT STATE AFTER FIXES:")
print(f"  Total surveys: {surveys.count_documents({})}")
print(f"  Active surveys: {surveys.count_documents({'is_active_in_pool': True})}")
print(f"  Entry links: {links.count_documents({})}")

sample = surveys.find_one({"is_active_in_pool": True})
if sample:
    link = links.find_one({"survey_id": sample.get("survey_id")})
    print(f"\nSample - Survey {sample.get('survey_id')}:")
    print(f"  Has entry link: {bool(link)}")
    if link:
        print(f"  Live link: {link.get('live_link')[:100]}...")
