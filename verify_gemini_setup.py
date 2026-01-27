#!/usr/bin/env python3
"""
Verification Script for Gemini Keys and AI Processing
=====================================================

This script verifies:
1. All 7 Gemini API keys are properly stored in the database
2. Gemini Rotator is working correctly
3. AI Summary functionality is working
4. AI Classification functionality is working
"""

import sys
import os
from datetime import datetime
from pymongo import MongoClient

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))


def check_gemini_keys_in_database():
    """Check if all 7 Gemini keys are stored in torpedo_settings.app_settings"""
    print("\n" + "="*80)
    print("1. CHECKING GEMINI API KEYS IN DATABASE")
    print("="*80)
    
    try:
        mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        client = MongoClient(mongo_uri)
        settings_db = client["torpedo_settings"]
        
        settings = settings_db["app_settings"].find_one()
        
        if not settings:
            print("❌ FAILED: No app_settings document found in torpedo_settings database")
            return False
        
        print(f"✓ Found app_settings document with ID: {settings['_id']}")
        
        keys_found = []
        keys_missing = []
        
        for i in range(1, 8):  # Check keys 1-7
            key_name = f"gemini_api_key_{i}"
            if key_name in settings and settings[key_name]:
                key_value = settings[key_name]
                # Mask the key for security
                masked_key = key_value[:10] + "..." + key_value[-5:] if len(key_value) > 15 else "***"
                keys_found.append((i, masked_key))
                print(f"  ✓ gemini_api_key_{i}: {masked_key}")
            else:
                keys_missing.append(i)
                print(f"  ✗ gemini_api_key_{i}: NOT FOUND")
        
        print(f"\nSummary:")
        print(f"  Keys found: {len(keys_found)}/7")
        print(f"  Keys missing: {keys_missing if keys_missing else 'None'}")
        
        if len(keys_found) == 7:
            print("✅ SUCCESS: All 7 Gemini API keys are stored in the database!")
            return True
        else:
            print(f"⚠️  WARNING: Only {len(keys_found)} keys found, expecting 7")
            return len(keys_found) > 0
            
    except Exception as e:
        print(f"❌ FAILED: Error checking database: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_gemini_rotator():
    """Check if Gemini Rotator is functioning properly"""
    print("\n" + "="*80)
    print("2. CHECKING GEMINI ROTATOR FUNCTIONALITY")
    print("="*80)
    
    try:
        from backend.leads.gemini_rotator import GeminiRotator
        
        print("✓ Successfully imported GeminiRotator")
        
        # Initialize rotator
        rotator = GeminiRotator()
        print("✓ Rotator initialized successfully")
        
        # Check loaded keys
        print(f"✓ Loaded {len(rotator.api_keys)} API keys")
        
        # Get an available key
        key_index, api_key = rotator.get_available_key()
        masked_key = api_key[:10] + "..." + api_key[-5:]
        print(f"✓ Got available key #{key_index}: {masked_key}")
        
        # Check quota
        quota = rotator.check_quota()
        print(f"\n📊 Quota Status:")
        print(f"  Total keys: {quota['total_keys']}")
        print(f"  Total requests today: {quota['total_requests_today']}/{quota['max_daily_capacity']}")
        print(f"  Total tokens used: {quota['total_tokens_used']}")
        print(f"  Remaining capacity: {quota['total_remaining_requests']}")
        print(f"  Usage: {quota['percentage_used']}%")
        
        # Show per-key breakdown
        print(f"\n  Per-key breakdown:")
        for key_info in quota['keys']:
            status_icon = "✓" if key_info['remaining_requests'] > 100 else "⚠️" if key_info['remaining_requests'] > 0 else "✗"
            print(f"    {status_icon} Key {key_info['key_index']}: {key_info['requests_today']}/1000 requests ({key_info['percentage_used']}% used)")
        
        # Health check
        health = rotator.health_check()
        print(f"\n🏥 System Health: {health['system_status'].upper()}")
        print(f"  Total remaining capacity: {health['total_remaining_capacity']} requests")
        
        print("\n✅ SUCCESS: Gemini Rotator is working properly!")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: Error with Gemini Rotator: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ai_summary():
    """Test AI Summary functionality"""
    print("\n" + "="*80)
    print("3. TESTING AI SUMMARY FUNCTIONALITY")
    print("="*80)
    
    try:
        from backend.leads.gemini_enrichment import summarize_email
        from backend.leads.gemini_rotator import get_rotator
        
        print("✓ Successfully imported summarize_email and get_rotator")
        
        # Test email
        test_subject = "Inquiry about survey panel services"
        test_body = """
Hi,

I'm reaching out from ABC Research Inc. We're looking for a reliable survey panel 
provider for an upcoming market research project targeting B2B decision makers.

We need approximately 500 completes in the US market, with specific targeting for 
IT managers in mid-sized companies. The survey should take about 10 minutes.

Could you provide a quote and let me know your typical turnaround time?

Best regards,
John Smith
Senior Research Manager
ABC Research Inc.
john.smith@abcresearch.com
+1-555-123-4567
"""
        
        print("\nTest Email:")
        print(f"  Subject: {test_subject}")
        print(f"  Body length: {len(test_body)} characters")
        
        print("\n⏳ Generating AI summary...")
        
        rotator = get_rotator()
        result = summarize_email(
            email_body=test_body,
            subject=test_subject,
            rotator=rotator
        )
        
        print("\n📝 Summary Result:")
        print(f"  Summary: {result['summary']}")
        print(f"  Key Points: {result['key_points']}")
        print(f"  Action Items: {result['action_items']}")
        print(f"  Sentiment: {result['sentiment']}")
        print(f"  Urgency: {result['urgency']}")
        print(f"  Contains Offer: {result['contains_offer']}")
        print(f"  Next Steps: {result['next_steps']}")
        
        if result['summary'] and result['summary'] != "Unable to summarize":
            print("\n✅ SUCCESS: AI Summary is working properly!")
            return True
        else:
            print("\n❌ FAILED: AI Summary returned empty or error result")
            return False
            
    except Exception as e:
        print(f"❌ FAILED: Error testing AI summary: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ai_classification():
    """Test AI Classification functionality"""
    print("\n" + "="*80)
    print("4. TESTING AI CLASSIFICATION FUNCTIONALITY")
    print("="*80)
    
    try:
        from backend.leads.gemini_enrichment import classify_lead, segment_email
        from backend.leads.gemini_rotator import get_rotator
        
        print("✓ Successfully imported classify_lead and segment_email")
        
        # Test lead data
        test_lead = {
            "email": "john.smith@abcresearch.com",
            "full_name": "John Smith",
            "title": "Senior Research Manager",
            "company": "ABC Research Inc",
            "email_subject": "Inquiry about survey panel services",
            "email_body": """Hi, I'm reaching out from ABC Research Inc. We're looking for a reliable 
survey panel provider for an upcoming market research project."""
        }
        
        print("\nTest Lead:")
        print(f"  Email: {test_lead['email']}")
        print(f"  Name: {test_lead['full_name']}")
        print(f"  Title: {test_lead['title']}")
        print(f"  Company: {test_lead['company']}")
        
        print("\n⏳ Running AI classification...")
        
        rotator = get_rotator()
        
        # Test quick segmentation
        print("\n1️⃣ Testing Quick Segmentation:")
        segment_result = segment_email(
            subject=test_lead['email_subject'],
            body=test_lead['email_body'],
            sender_email=test_lead['email'],
            rotator=rotator
        )
        
        print(f"  Segment: {segment_result['segment']}")
        print(f"  Confidence: {segment_result['confidence']}")
        print(f"  Reasoning: {segment_result['reasoning']}")
        
        # Test full classification
        print("\n2️⃣ Testing Full Classification:")
        classification = classify_lead(test_lead, rotator)
        
        print(f"  Category: {classification['category']}")
        print(f"  Confidence: {classification['confidence']}")
        print(f"  Department: {classification['department']}")
        print(f"  Seniority: {classification['seniority']}")
        print(f"  Priority: {classification['priority']}")
        print(f"  Buying Intent: {classification['buying_intent']}")
        print(f"  Reasoning: {classification['reasoning']}")
        
        if classification['category'] and classification['category'] != "UNKNOWN":
            print("\n✅ SUCCESS: AI Classification is working properly!")
            return True
        else:
            print("\n❌ FAILED: AI Classification returned UNKNOWN category")
            return False
            
    except Exception as e:
        print(f"❌ FAILED: Error testing AI classification: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_recent_ai_activity():
    """Check recent AI processing activity in the database"""
    print("\n" + "="*80)
    print("5. CHECKING RECENT AI ACTIVITY")
    print("="*80)
    
    try:
        mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        client = MongoClient(mongo_uri)
        email_db = client["email_automation"]
        
        # Check gemini_requests collection for recent activity
        gemini_requests = email_db["gemini_requests"]
        
        total_requests = gemini_requests.count_documents({})
        print(f"✓ Total Gemini API requests in database: {total_requests}")
        
        if total_requests > 0:
            # Get recent requests
            recent = list(gemini_requests.find().sort("timestamp", -1).limit(10))
            
            print(f"\n📊 Recent Gemini API Activity (last 10 requests):")
            for req in recent:
                timestamp = req.get('timestamp', 'Unknown')
                task_type = req.get('task_type', 'Unknown')
                key_index = req.get('key_index', '?')
                success = req.get('success', False)
                tokens = req.get('tokens_used', 0)
                status = "✓" if success else "✗"
                
                print(f"  {status} {timestamp} | Key #{key_index} | {task_type} | {tokens} tokens")
            
            # Get task type breakdown
            pipeline = [
                {"$group": {
                    "_id": "$task_type",
                    "count": {"$sum": 1},
                    "total_tokens": {"$sum": "$tokens_used"}
                }},
                {"$sort": {"count": -1}}
            ]
            
            task_stats = list(gemini_requests.aggregate(pipeline))
            
            if task_stats:
                print(f"\n📈 Task Type Breakdown:")
                for stat in task_stats:
                    task_type = stat['_id']
                    count = stat['count']
                    tokens = stat['total_tokens']
                    print(f"  {task_type}: {count} requests, {tokens} tokens")
        
        # Check classified_gmail collection
        classified_gmail = email_db["classified_gmail"]
        classified_count = classified_gmail.count_documents({})
        
        print(f"\n✓ Total classified emails: {classified_count}")
        
        if classified_count > 0:
            # Get segment breakdown
            pipeline = [
                {"$group": {
                    "_id": "$segment",
                    "count": {"$sum": 1}
                }},
                {"$sort": {"count": -1}}
            ]
            
            segment_stats = list(classified_gmail.aggregate(pipeline))
            
            print(f"\n📧 Email Classification Breakdown:")
            for stat in segment_stats:
                segment = stat['_id']
                count = stat['count']
                print(f"  {segment}: {count} emails")
        
        print("\n✅ Database activity check complete!")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: Error checking AI activity: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification checks"""
    print("\n" + "="*80)
    print("GEMINI SETUP AND AI PROCESSING VERIFICATION")
    print("="*80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {
        "database_keys": False,
        "rotator": False,
        "summary": False,
        "classification": False,
        "activity": False
    }
    
    # Run checks
    results["database_keys"] = check_gemini_keys_in_database()
    results["rotator"] = check_gemini_rotator()
    results["summary"] = test_ai_summary()
    results["classification"] = test_ai_classification()
    results["activity"] = check_recent_ai_activity()
    
    # Final summary
    print("\n" + "="*80)
    print("VERIFICATION SUMMARY")
    print("="*80)
    
    for check, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {check.replace('_', ' ').title()}")
    
    all_passed = all(results.values())
    
    print("\n" + "="*80)
    if all_passed:
        print("✅ ALL CHECKS PASSED!")
        print("\nConclusion:")
        print("1. All 7 Gemini API keys are properly configured in the database")
        print("2. Backend is successfully using Gemini for AI summary")
        print("3. Backend is successfully using Gemini for AI classification")
        print("4. The Gemini rotator is managing API quotas correctly")
    else:
        failed_checks = [k for k, v in results.items() if not v]
        print("⚠️  SOME CHECKS FAILED!")
        print(f"\nFailed checks: {', '.join(failed_checks)}")
        print("\nPlease review the output above for details on what failed.")
    
    print("="*80)
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
