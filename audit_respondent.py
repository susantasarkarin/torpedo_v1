#!/usr/bin/env python3
"""Audit script for respondent 69809ce2dd20421911277e08"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))

sfwid = "69809ce2dd20421911277e08"
print("=" * 60)
print(f"BACKEND AUDIT FOR SFWID: {sfwid}")
print("=" * 60)

# 1. Check survey_respondents for this SFWID
respondents_db = client["survey_respondents"]
print("\n1. RESPONDENT RECORD (survey_respondents.respondents):")
respondent = respondents_db["respondents"].find_one({"_id": sfwid})
if not respondent:
    respondent = respondents_db["respondents"].find_one({"sfwid": sfwid})
if respondent:
    for k, v in respondent.items():
        if k not in ["raw_data", "responses"]:
            print(f"   {k}: {v}")
else:
    print("   NOT FOUND")

# 2. Check CPX callback logs
cpx_db = client["cpx_research"]
print("\n2. CPX CALLBACKS (cpx_research.cpx_callbacks):")
collections = cpx_db.list_collection_names()
print(f"   Available collections: {collections}")
for coll_name in ["cpx_callbacks", "callbacks", "cpx_responses"]:
    if coll_name in collections:
        callbacks = list(cpx_db[coll_name].find({"$or": [{"sfwid": sfwid}, {"subid_1": sfwid}]}).limit(5))
        if callbacks:
            print(f"   Found in {coll_name}:")
            for cb in callbacks:
                print(f"     Status: {cb.get('status')}, Created: {cb.get('created_at')}")
        else:
            print(f"   No records in {coll_name}")

# 3. Check torpedo_surveys allocations
torpedo_db = client["torpedo_surveys"]
print("\n3. TORPEDO SURVEYS ALLOCATIONS (torpedo_surveys.survey_allocations):")
if "survey_allocations" in torpedo_db.list_collection_names():
    allocs = list(torpedo_db["survey_allocations"].find({"respondent_id": sfwid}).limit(5))
    if allocs:
        for a in allocs:
            print(f"   ID: {a.get('_id')}")
            print(f"   Survey ID: {a.get('survey_id')}")
            print(f"   Status: {a.get('status')}")
            print(f"   Provider: {a.get('provider')}")
            print(f"   Created: {a.get('created_at')}")
            entry = a.get("entry_link", "")
            if entry:
                print(f"   Entry Link: {entry[:100]}...")
            print()
    else:
        print("   No allocations found")
else:
    print("   Collection does not exist")

# 4. Check if there's a cpx_survey record for this survey
print("\n4. CPX SURVEY RECORD:")
# Get survey_id from allocation
if allocs:
    survey_id = allocs[0].get("survey_id")
    if survey_id:
        survey = cpx_db["cpx_surveys"].find_one({"_id": survey_id})
        if survey:
            print(f"   Survey ID: {survey.get('_id')}")
            print(f"   Title: {survey.get('title')}")
            print(f"   LOI: {survey.get('loi')}")
            print(f"   Payout: {survey.get('payout')}")
            print(f"   Click Count: {survey.get('click_count')}")
            print(f"   Last Clicked: {survey.get('last_clicked_at')}")
        else:
            print(f"   Survey {survey_id} not found in cpx_surveys")

# 5. Check cpx-response endpoint logs in any logging collection
print("\n5. RESPONSE LOGS:")
settings_db = client["torpedo_settings"]
for coll_name in settings_db.list_collection_names():
    if "log" in coll_name.lower() or "callback" in coll_name.lower():
        print(f"   Found collection: {coll_name}")
        logs = list(settings_db[coll_name].find({"$or": [{"sfwid": sfwid}, {"respondent_id": sfwid}]}).limit(3))
        if logs:
            for log in logs:
                print(f"     {log}")

# 6. Check all databases for any reference to this SFWID
print("\n6. SCANNING ALL DATABASES FOR SFWID:")
for db_name in client.list_database_names():
    if db_name in ["admin", "local", "config"]:
        continue
    db = client[db_name]
    for coll_name in db.list_collection_names():
        try:
            count = db[coll_name].count_documents({"$or": [
                {"sfwid": sfwid},
                {"respondent_id": sfwid},
                {"subid_1": sfwid},
                {"_id": sfwid}
            ]})
            if count > 0:
                print(f"   {db_name}.{coll_name}: {count} record(s)")
        except Exception as e:
            pass

print("\n" + "=" * 60)
print("AUDIT COMPLETE")
print("=" * 60)
