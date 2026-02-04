#!/usr/bin/env python3
"""
Cint Integration Diagnostics

Diagnoses the current state of Cint survey allocation:
1. Check if surveys exist in cint_surveys collection
2. Check if entry links exist in cint_entry_links collection
3. Check if surveys are marked as is_active_in_pool
4. Check filter settings in tornado_settings.app_settings
5. Compare to CPX implementation (which works)
"""
import os
import sys
from datetime import datetime
from pymongo import MongoClient
from typing import Dict, Any, List

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

def connect_mongo():
    """Connect to MongoDB"""
    try:
        client = MongoClient(MONGO_URI)
        # Test connection
        client.admin.command('ping')
        print("✅ MongoDB connection successful")
        return client
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        sys.exit(1)

def diagnose_cint_surveys(client: MongoClient) -> Dict[str, Any]:
    """Check Cint surveys collection state"""
    print("\n" + "="*80)
    print("DIAGNOSIS 1: CINT SURVEYS COLLECTION")
    print("="*80)
    
    db = client["cint"]
    surveys = db["surveys"]
    
    # Get counts
    total_count = surveys.count_documents({})
    active_count = surveys.count_documents({"is_active_in_pool": True})
    inactive_count = surveys.count_documents({"is_active_in_pool": False})
    no_status_count = surveys.count_documents({"is_active_in_pool": {"$exists": False}})
    
    print(f"\n📊 Survey Counts:")
    print(f"   Total surveys: {total_count}")
    print(f"   Active (is_active_in_pool=true): {active_count}")
    print(f"   Inactive (is_active_in_pool=false): {inactive_count}")
    print(f"   No status field: {no_status_count}")
    
    if total_count == 0:
        print(f"\n❌ PROBLEM: No surveys found in cint.surveys!")
        print(f"   This means webhook opportunities are not being received or stored.")
        print(f"   Expected: Cint should be pushing opportunities via webhook to cint_service")
        return {"has_surveys": False, "total": 0}
    
    print(f"\n✅ {total_count} surveys found")
    
    # Sample a survey to check structure
    sample = surveys.find_one({})
    if sample:
        print(f"\n📋 Sample Survey Structure:")
        print(f"   survey_id: {sample.get('survey_id')}")
        print(f"   survey_name: {sample.get('survey_name')}")
        print(f"   is_live: {sample.get('is_live')}")
        print(f"   is_active_in_pool: {sample.get('is_active_in_pool')}")
        print(f"   is_active: {sample.get('is_active')}")
        print(f"   length_of_interview: {sample.get('length_of_interview')}")
        print(f"   payout: {sample.get('payout')}")
        print(f"   bid_incidence: {sample.get('bid_incidence')}")
        print(f"   created_at: {sample.get('created_at')}")
        
    # Sample inactive surveys to understand why
    inactive_sample = surveys.find_one({"is_active_in_pool": False})
    if inactive_sample:
        print(f"\n📋 Sample Inactive Survey (WHY NOT ACTIVE?):")
        print(f"   survey_id: {inactive_sample.get('survey_id')}")
        print(f"   survey_name: {inactive_sample.get('survey_name')}")
        print(f"   is_live: {inactive_sample.get('is_live')}")
        print(f"   message_reason: {inactive_sample.get('message_reason')}")
        loi = inactive_sample.get('length_of_interview') or inactive_sample.get('bid_length_of_interview')
        payout = inactive_sample.get('payout')
        incidence = inactive_sample.get('bid_incidence')
        print(f"   length_of_interview: {loi}")
        print(f"   payout: {payout}")
        print(f"   bid_incidence: {incidence}")
    
    return {
        "has_surveys": total_count > 0,
        "total": total_count,
        "active": active_count,
        "inactive": inactive_count,
        "no_status": no_status_count
    }

def diagnose_entry_links(client: MongoClient) -> Dict[str, Any]:
    """Check Cint entry links collection state"""
    print("\n" + "="*80)
    print("DIAGNOSIS 2: CINT ENTRY LINKS COLLECTION")
    print("="*80)
    
    db = client["cint"]
    try:
        entry_links = db["entry_links"]
        total_count = entry_links.count_documents({})
        
        print(f"\n📊 Entry Links Count: {total_count}")
        
        if total_count == 0:
            print(f"\n❌ PROBLEM: No entry links found in cint.entry_links!")
            print(f"   This means _auto_create_entry_link() is not being called or not succeeding.")
            print(f"   Expected: One entry link per survey with live_link field")
            return {"has_links": False, "total": 0}
        
        print(f"\n✅ {total_count} entry links found")
        
        # Sample
        sample = entry_links.find_one({})
        if sample:
            print(f"\n📋 Sample Entry Link Structure:")
            print(f"   survey_id: {sample.get('survey_id')}")
            print(f"   live_link: {sample.get('live_link')[:100]}..." if sample.get('live_link') else "   live_link: MISSING!")
            print(f"   test_link: {sample.get('test_link')[:100]}..." if sample.get('test_link') else "   test_link: MISSING!")
            print(f"   created_at: {sample.get('created_at')}")
        
        # Check for missing live_link
        missing_live_link = entry_links.count_documents({"live_link": {"$exists": False}})
        if missing_live_link > 0:
            print(f"\n⚠️  {missing_live_link} entry links missing live_link field")
        
        return {"has_links": total_count > 0, "total": total_count}
    except Exception as e:
        print(f"\n⚠️  Could not check entry_links: {e}")
        return {"has_links": False, "total": 0, "error": str(e)}

def diagnose_filter_settings(client: MongoClient) -> Dict[str, Any]:
    """Check filter settings"""
    print("\n" + "="*80)
    print("DIAGNOSIS 3: FILTER SETTINGS")
    print("="*80)
    
    db = client["torpedo_settings"]
    settings = db["app_settings"]
    
    filter_doc = settings.find_one({"_id": "survey_filters"})
    
    if not filter_doc:
        print(f"\n⚠️  No filter settings found! Using hardcoded defaults:")
        defaults = {
            "max_loi": 20,
            "min_cpi": 1.0,
            "min_incidence": 60,
            "deletion_period_days": 7,
        }
        for k, v in defaults.items():
            print(f"   {k}: {v}")
        return defaults
    
    print(f"\n✅ Filter settings found:")
    print(f"   max_loi: {filter_doc.get('max_loi', 20)}")
    print(f"   min_cpi: {filter_doc.get('min_cpi', 1.0)}")
    print(f"   min_incidence: {filter_doc.get('min_incidence', 60)}")
    print(f"   deletion_period_days: {filter_doc.get('deletion_period_days', 7)}")
    
    return {
        "max_loi": filter_doc.get('max_loi', 20),
        "min_cpi": filter_doc.get('min_cpi', 1.0),
        "min_incidence": filter_doc.get('min_incidence', 60),
    }

def diagnose_sync_active_status(client: MongoClient, filters: Dict[str, Any]) -> None:
    """Check if sync_active_status_by_filters() would activate surveys"""
    print("\n" + "="*80)
    print("DIAGNOSIS 4: FILTER APPLICATION (Why surveys not active?)")
    print("="*80)
    
    db = client["cint"]
    surveys = db["surveys"]
    
    max_loi = filters.get("max_loi", 20)
    min_cpi = filters.get("min_cpi", 1.0)
    min_incidence = filters.get("min_incidence", 60)
    
    print(f"\n🔍 Testing filters: max_loi={max_loi}, min_cpi={min_cpi}, min_incidence={min_incidence}")
    
    # Find surveys that would PASS the filter
    pass_filter = surveys.find_one({
        "$and": [
            {"$or": [
                {"length_of_interview": {"$lte": max_loi}},
                {"bid_length_of_interview": {"$lte": max_loi}},
                {"loi": {"$lte": max_loi}},
            ]},
            {"$or": [
                {"payout": {"$gte": min_cpi}},
                {"revenue_per_interview": {"$gte": min_cpi}},
            ]}
        ]
    })
    
    if pass_filter:
        print(f"\n✅ Found survey that PASSES filters:")
        print(f"   survey_id: {pass_filter.get('survey_id')}")
        loi = pass_filter.get('length_of_interview') or pass_filter.get('bid_length_of_interview')
        print(f"   LOI: {loi} (max: {max_loi})")
        payout = pass_filter.get('payout')
        print(f"   Payout: {payout} (min: {min_cpi})")
    else:
        print(f"\n❌ NO surveys pass the filters!")
        print(f"\n   Checking survey LOI values:")
        loi_samples = surveys.aggregate([
            {"$project": {
                "survey_id": 1,
                "loi": {"$ifNull": ["$length_of_interview", "$bid_length_of_interview"]}
            }},
            {"$limit": 5}
        ])
        for doc in loi_samples:
            loi = doc.get("loi")
            status = "PASS" if (loi and loi <= max_loi) else "FAIL"
            print(f"      Survey {doc.get('survey_id')}: LOI={loi} [{status}]")
        
        print(f"\n   Checking survey PAYOUT values:")
        payout_samples = surveys.find({}, {"survey_id": 1, "payout": 1, "revenue_per_interview": 1}).limit(5)
        for doc in payout_samples:
            payout = doc.get("payout") or doc.get("revenue_per_interview")
            status = "PASS" if (payout and payout >= min_cpi) else "FAIL"
            print(f"      Survey {doc.get('survey_id')}: Payout={payout} [{status}]")
        
        print(f"\n❌ PROBLEM: All surveys filtered out by max_loi or min_cpi!")
        print(f"   Either:")
        print(f"   1. Filter settings are too restrictive")
        print(f"   2. Cint is only sending surveys that don't match CPX filter settings")
        print(f"   3. Survey data has missing LOI/payout fields")

def diagnose_cpx_vs_cint(client: MongoClient) -> None:
    """Compare CPX and Cint to understand the difference"""
    print("\n" + "="*80)
    print("DIAGNOSIS 5: CPX VS CINT COMPARISON")
    print("="*80)
    
    cpx_db = client["cpx_research"]
    cint_db = client["cint"]
    
    cpx_surveys = cpx_db["surveys"]
    cint_surveys = cint_db["surveys"]
    
    cpx_count = cpx_surveys.count_documents({})
    cpx_active = cpx_surveys.count_documents({"is_active_in_pool": True})
    
    cint_count = cint_surveys.count_documents({})
    cint_active = cint_surveys.count_documents({"is_active_in_pool": True})
    
    print(f"\n📊 Comparison:")
    print(f"   CPX Surveys: {cpx_count} total, {cpx_active} active")
    print(f"   Cint Surveys: {cint_count} total, {cint_active} active")
    
    # Check if CPX is working
    if cpx_active > 0:
        print(f"\n✅ CPX allocation working (has active surveys)")
        cpx_sample = cpx_surveys.find_one({"is_active_in_pool": True})
        if cpx_sample:
            print(f"   CPX Sample Active Survey:")
            print(f"      survey_id: {cpx_sample.get('_id')}")
            print(f"      loi: {cpx_sample.get('loi')}")
            print(f"      payout: {cpx_sample.get('payout')}")
            print(f"      is_active_in_pool: {cpx_sample.get('is_active_in_pool')}")
    else:
        print(f"\n⚠️  CPX has no active surveys either")
    
    # Check if Cint is working
    if cint_active > 0:
        print(f"\n✅ Cint has active surveys")
    else:
        print(f"\n❌ Cint has NO active surveys")
        if cint_count > 0:
            print(f"   But {cint_count} surveys exist - they're just not marked active")

def diagnose_sync_method_called(client: MongoClient) -> None:
    """Check if sync_active_status_by_filters() has ever been called"""
    print("\n" + "="*80)
    print("DIAGNOSIS 6: HAS SYNC_ACTIVE_STATUS_BY_FILTERS() BEEN CALLED?")
    print("="*80)
    
    db = client["cint"]
    surveys = db["surveys"]
    
    # Count surveys with is_active_in_pool field
    has_status_field = surveys.count_documents({"is_active_in_pool": {"$exists": True}})
    no_status_field = surveys.count_documents({"is_active_in_pool": {"$exists": False}})
    
    print(f"\n📊 Status Field Presence:")
    print(f"   Surveys with is_active_in_pool field: {has_status_field}")
    print(f"   Surveys WITHOUT is_active_in_pool field: {no_status_field}")
    
    if has_status_field > 0:
        print(f"\n✅ The sync method HAS been called (surveys have is_active_in_pool field)")
    else:
        print(f"\n❌ The sync method has NOT been called!")
        print(f"   All surveys still have the $setOnInsert default of is_active_in_pool=false")
        print(f"   ACTION: Call sync_active_status_by_filters() on cint_service")

def main():
    """Run all diagnostics"""
    print("\n" + "="*80)
    print("CINT INTEGRATION DIAGNOSTICS")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*80)
    
    # Connect
    client = connect_mongo()
    
    try:
        # Run all diagnostics
        surveys_status = diagnose_cint_surveys(client)
        entry_links_status = diagnose_entry_links(client)
        filters = diagnose_filter_settings(client)
        diagnose_sync_active_status(client, filters)
        diagnose_cpx_vs_cint(client)
        diagnose_sync_method_called(client)
        
        # Summary
        print("\n" + "="*80)
        print("DIAGNOSIS SUMMARY")
        print("="*80)
        
        if not surveys_status.get("has_surveys"):
            print(f"\n🔴 CRITICAL: No surveys in cint.surveys collection!")
            print(f"   Webhook opportunities not being received or stored")
        elif surveys_status.get("active") == 0:
            print(f"\n🟡 WARNING: {surveys_status.get('total')} surveys but NONE are active!")
            print(f"   sync_active_status_by_filters() needs to be called or filter settings are wrong")
        else:
            print(f"\n🟢 Surveys found and marked active: {surveys_status.get('active')}")
        
        if not entry_links_status.get("has_links"):
            print(f"\n🟡 WARNING: No entry links found!")
            print(f"   _auto_create_entry_link() not being called on new surveys")
        else:
            print(f"\n🟢 Entry links found: {entry_links_status.get('total')}")
        
    finally:
        client.close()
        print("\n✅ Diagnostics complete")

if __name__ == "__main__":
    main()
