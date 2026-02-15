#!/usr/bin/env python3
"""
Analyze why CPX terminated users are not getting CINT fallback
"""
import pymongo
from datetime import datetime, timedelta

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["traffic_flow_db"]
url_parameters = db["url_parameters"]

# Calculate time range (last 2 hours)
two_hours_ago = datetime.utcnow() - timedelta(hours=2)

print(f"🔍 Analyzing CPX terminations and CINT fallback (last 2 hours)\n")

# Get all TERMINATED records
terminated = list(url_parameters.find({
    "createdAt": {"$gte": two_hours_ago},
    "status": "TERMINATED"
}))

# Get records with CINT fallback status
fallback_status = list(url_parameters.find({
    "createdAt": {"$gte": two_hours_ago},
    "status": "CPX_TERMINATED_CINT_FALLBACK"
}))

# Check for cint_fallback_attempted flag
terminated_with_flag = [r for r in terminated if r.get("cint_fallback_attempted")]

print(f"📊 Status Breakdown:")
print(f"  TERMINATED (should trigger CINT): {len(terminated)}")
print(f"  CPX_TERMINATED_CINT_FALLBACK:     {len(fallback_status)}")
print(f"  Missing fallback:                 {len(terminated) - len(fallback_status)}")
print(f"  TERMINATED with fallback flag:    {len(terminated_with_flag)}\n")

# Analyze the TERMINATED records without CINT fallback
missing_fallback = []
for rec in terminated:
    # Check if it has CPX survey assigned
    survey_id = rec.get("assignedSurveyId")
    if survey_id and int(survey_id) < 70000000:  # CPX survey
        # Check if fallback was attempted
        if not rec.get("cint_fallback_attempted"):
            missing_fallback.append(rec)

print(f"🔴 CPX terminations WITHOUT fallback attempt: {len(missing_fallback)}")

if missing_fallback:
    print(f"\n📋 Sample records (first 5):")
    for idx, rec in enumerate(missing_fallback[:5], 1):
        record_id = str(rec.get("_id"))
        vendor_id = rec.get("vendorId", "N/A")
        country = rec.get("countryCode", "N/A")
        survey_id = rec.get("assignedSurveyId", "NONE")
        created = rec.get("createdAt", "N/A")
        print(f"\n  {idx}. ID: {record_id}")
        print(f"     Vendor: {vendor_id}, Country: {country}")
        print(f"     CPX Survey: {survey_id}")
        print(f"     Created: {created}")
        print(f"     Has cint_fallback_attempted: {rec.get('cint_fallback_attempted', False)}")

# Now check CINT survey availability for India
print(f"\n{'='*70}")
print(f"\n🔍 Checking CINT survey availability for India:\n")

cint_db = client["cint_research"]
cint_surveys = cint_db["cint_surveys"]

# Count total CINT surveys for India
total_in_surveys = cint_surveys.count_documents({"country_code": "IN"})
live_in_surveys = cint_surveys.count_documents({"country_code": "IN", "is_live": True})
active_in_surveys = cint_surveys.count_documents({"country_code": "IN", "is_active": True})
active_live_in_surveys = cint_surveys.count_documents({
    "country_code": "IN", 
    "is_active": True, 
    "is_live": True
})
active_pool_in_surveys = cint_surveys.count_documents({
    "country_code": "IN", 
    "is_active_in_pool": True
})

print(f"📊 CINT Surveys for India (IN):")
print(f"  Total surveys:            {total_in_surveys}")
print(f"  Live surveys:             {live_in_surveys}")
print(f"  Active surveys:           {active_in_surveys}")
print(f"  Active AND Live:          {active_live_in_surveys}")
print(f"  Active in pool:           {active_pool_in_surveys}")

# Check if surveys were recently marked inactive
recently_deactivated = list(cint_surveys.find({
    "country_code": "IN",
    "is_active": False,
    "updated_at": {"$gte": two_hours_ago}
}).limit(10))

print(f"\n⚠️  Recently deactivated surveys: {len(recently_deactivated)}")
if recently_deactivated:
    print(f"\n📋 Sample deactivated surveys (first 5):")
    for idx, survey in enumerate(recently_deactivated[:5], 1):
        survey_id = survey.get("survey_id")
        title = survey.get("survey_title", "N/A")[:50]
        updated = survey.get("updated_at", "N/A")
        print(f"  {idx}. Survey {survey_id}: {title}")
        print(f"     Deactivated at: {updated}")

client.close()

print(f"\n{'='*70}")
print(f"\n💡 Analysis:")
print(f"   1. Check logs for 'CINT fallback' messages around these terminated records")
print(f"   2. If 'No active surveys for country IN' appears, surveys were marked inactive")
print(f"   3. Need to prevent surveys from being marked inactive on 409 errors")
print(f"   4. Recent deployment should have fixed this - check if it's deployed")
