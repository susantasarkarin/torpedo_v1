#!/usr/bin/env python3
"""
Analyze traffic records from the last 2 hours to identify reasons for high INCOMPLETE rates
"""
import pymongo
from datetime import datetime, timedelta
from collections import Counter
import sys

# MongoDB connection
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["traffic_flow_db"]
url_parameters = db["url_parameters"]

# Calculate time range (last 2 hours)
two_hours_ago = datetime.utcnow() - timedelta(hours=2)

print(f"🔍 Analyzing traffic from last 2 hours (since {two_hours_ago.strftime('%Y-%m-%d %H:%M:%S')} UTC)\n")

# Get all traffic from last 2 hours
traffic_query = {"createdAt": {"$gte": two_hours_ago}}
traffic_records = list(url_parameters.find(traffic_query))

print(f"📊 Total traffic records in last 2 hours: {len(traffic_records)}\n")

if not traffic_records:
    print("⚠️  No traffic found in the last 2 hours")
    sys.exit(0)

# Group by status
status_counts = Counter([r.get("status", "UNKNOWN") for r in traffic_records])
print("📋 Status Breakdown:")
for status, count in status_counts.most_common():
    percentage = (count / len(traffic_records)) * 100
    print(f"  {status:25} {count:5} ({percentage:5.1f}%)")

print(f"\n{'='*70}")

# Analyze INCOMPLETE records specifically
incomplete_records = [r for r in traffic_records if r.get("status") == "INCOMPLETE"]
print(f"\n🔴 INCOMPLETE Analysis ({len(incomplete_records)} records):\n")

if incomplete_records:
    # Check if surveys were assigned
    assigned_count = sum(1 for r in incomplete_records if r.get("assignedSurveyId"))
    unassigned_count = len(incomplete_records) - assigned_count
    
    print(f"📌 Survey Assignment:")
    print(f"  Assigned survey:     {assigned_count:5} ({(assigned_count/len(incomplete_records)*100):5.1f}%)")
    print(f"  No survey assigned:  {unassigned_count:5} ({(unassigned_count/len(incomplete_records)*100):5.1f}%)")
    
    # Check for CPX vs CINT
    cpx_incomplete = sum(1 for r in incomplete_records if r.get("assignedSurveyId") and int(r.get("assignedSurveyId", 0)) < 70000000)
    cint_incomplete = sum(1 for r in incomplete_records if r.get("assignedSurveyId") and int(r.get("assignedSurveyId", 0)) >= 70000000)
    
    print(f"\n📌 Provider Breakdown (of assigned):")
    print(f"  CPX surveys:         {cpx_incomplete:5}")
    print(f"  CINT surveys:        {cint_incomplete:5}")
    
    # Check vendor distribution
    vendor_counts = Counter([r.get("vendorId", "UNKNOWN") for r in incomplete_records])
    print(f"\n📌 Vendor Breakdown:")
    for vendor_id, count in vendor_counts.most_common(5):
        percentage = (count / len(incomplete_records)) * 100
        print(f"  Vendor {vendor_id:10} {count:5} ({percentage:5.1f}%)")
    
    # Check country distribution
    country_counts = Counter([r.get("countryCode", "UNKNOWN") for r in incomplete_records])
    print(f"\n📌 Country Breakdown:")
    for country, count in country_counts.most_common(5):
        percentage = (count / len(incomplete_records)) * 100
        print(f"  {country:10} {count:5} ({percentage:5.1f}%)")
    
    # Check time distribution
    print(f"\n📌 Time Distribution (by hour):")
    hour_counts = Counter([r.get("createdAt").hour for r in incomplete_records if r.get("createdAt")])
    for hour in sorted(hour_counts.keys()):
        count = hour_counts[hour]
        print(f"  Hour {hour:02d}:00       {count:5}")
    
    # Analyze allocation failures
    allocation_failures = {}
    for rec in incomplete_records:
        failure_reason = rec.get("allocationFailureReason", "Unknown")
        allocation_failures[failure_reason] = allocation_failures.get(failure_reason, 0) + 1
    
    if allocation_failures:
        print(f"\n📌 Allocation Failure Reasons:")
        for reason, count in sorted(allocation_failures.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(incomplete_records)) * 100
            print(f"  {reason:50} {count:5} ({percentage:5.1f}%)")
    
    # Sample recent INCOMPLETE records
    print(f"\n📌 Sample Recent INCOMPLETE Records (last 5):")
    recent_incompletes = sorted(incomplete_records, key=lambda x: x.get("createdAt", datetime.min), reverse=True)[:5]
    for idx, rec in enumerate(recent_incompletes, 1):
        record_id = str(rec.get("_id"))
        vendor_id = rec.get("vendorId", "N/A")
        country = rec.get("countryCode", "N/A")
        survey_id = rec.get("assignedSurveyId", "NONE")
        created = rec.get("createdAt", "N/A")
        failure_reason = rec.get("allocationFailureReason", "Not recorded")
        attempts = rec.get("allocationAttempts", [])
        print(f"\n  {idx}. ID: {record_id}")
        print(f"     Vendor: {vendor_id}, Country: {country}, Survey: {survey_id}")
        print(f"     Created: {created}")
        print(f"     Has redirect URL: {bool(rec.get('redirectUrl'))}")
        print(f"     Has out URL: {bool(rec.get('outUrl'))}")
        print(f"     Failure reason: {failure_reason}")
        if attempts:
            print(f"     Allocation attempts: {len(attempts)}")
            # Show last 3 attempts (or fewer if less than 3 exist) for brevity
            # Most recent attempts are usually most relevant for diagnosing current issues
            for attempt in attempts[-3:]:
                status = "✅" if attempt.get("success") else "❌"
                provider = attempt.get("provider", "?")
                reason = attempt.get("failure_reason", "success")
                print(f"       {status} {provider}: {reason}")

print(f"\n{'='*70}")
print("\n💡 Common reasons for INCOMPLETE status with no survey assignment:")
print("   1. CPX WebView Block - User using in-app browser (Facebook/Instagram/LinkedIn)")
print("   2. CPX Entry Guard Block - Duplicate attempt or fraud prevention")
print("   3. No Surveys Available - Neither CPX nor CINT have matching surveys")
print("   4. Invalid IP Address - Local/private IP cannot be used for survey APIs")
print("   5. Country Mismatch - No surveys available for user's country")
print("   6. API Errors - CPX or CINT service temporarily unavailable")
print("   7. Configuration Issues - Missing API credentials or database connection")
print("\n📊 To reduce INCOMPLETE rates:")
print("   • Ensure adequate survey inventory for all supported countries")
print("   • Monitor CPX/CINT API availability and error rates")
print("   • Review entry guard thresholds if blocking legitimate users")
print("   • Add fallback survey pools for common failure scenarios")
print("   • Implement retry mechanism for temporary failures")

client.close()
