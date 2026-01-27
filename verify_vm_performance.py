#!/usr/bin/env python3
"""
VM Performance Verification Script
===================================

This script connects to the actual VM database and tests Gemini API performance
with real credentials and data.

Run this on the VM to verify:
1. Gemini keys are properly stored in database
2. AI summary is working with real emails
3. AI classification is working with real data
4. Actual quota usage and performance metrics
"""

import sys
import os
from datetime import datetime, timedelta
from pymongo import MongoClient
import json

def main():
    print("\n" + "="*80)
    print("VM PERFORMANCE VERIFICATION - GEMINI API & AI PROCESSING")
    print("="*80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    try:
        # Connect to MongoDB
        mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        print(f"Connecting to MongoDB: {mongo_uri}")
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        
        # Test connection
        client.admin.command('ping')
        print("✓ MongoDB connection successful\n")
        
        results = {}
        
        # 1. Check Gemini Keys in Database
        print("="*80)
        print("1. CHECKING GEMINI API KEYS IN DATABASE")
        print("="*80)
        
        settings_db = client["torpedo_settings"]
        settings = settings_db["app_settings"].find_one()
        
        if not settings:
            print("❌ No app_settings found in torpedo_settings database")
            results['keys'] = False
        else:
            keys_found = []
            for i in range(1, 8):
                key_name = f"gemini_api_key_{i}"
                if key_name in settings and settings[key_name] and settings[key_name].strip():
                    key_value = settings[key_name]
                    masked = key_value[:10] + "..." + key_value[-5:] if len(key_value) > 15 else "***"
                    keys_found.append(i)
                    print(f"  ✓ gemini_api_key_{i}: {masked}")
                else:
                    print(f"  ✗ gemini_api_key_{i}: NOT FOUND or EMPTY")
            
            print(f"\n✓ Found {len(keys_found)}/7 Gemini API keys")
            results['keys'] = len(keys_found) == 7
            results['keys_count'] = len(keys_found)
        
        # 2. Check Recent Gemini API Activity
        print("\n" + "="*80)
        print("2. CHECKING RECENT GEMINI API ACTIVITY")
        print("="*80)
        
        email_db = client["email_automation"]
        gemini_requests = email_db["gemini_requests"]
        
        total_requests = gemini_requests.count_documents({})
        print(f"Total Gemini requests in database: {total_requests}")
        
        if total_requests > 0:
            # Get recent requests
            recent = list(gemini_requests.find().sort("timestamp", -1).limit(20))
            
            print(f"\n📊 Recent Gemini API Activity (last 20 requests):")
            for req in recent:
                timestamp = req.get('timestamp', 'Unknown')
                task_type = req.get('task_type', 'Unknown')
                key_index = req.get('key_index', '?')
                success = req.get('success', False)
                tokens = req.get('tokens_used', 0)
                status = "✓" if success else "✗"
                print(f"  {status} {timestamp} | Key #{key_index} | {task_type:12s} | {tokens:4d} tokens")
            
            # Get task type breakdown
            pipeline = [
                {"$group": {
                    "_id": "$task_type",
                    "count": {"$sum": 1},
                    "total_tokens": {"$sum": "$tokens_used"},
                    "success_count": {"$sum": {"$cond": ["$success", 1, 0]}}
                }},
                {"$sort": {"count": -1}}
            ]
            
            task_stats = list(gemini_requests.aggregate(pipeline))
            
            if task_stats:
                print(f"\n📈 Task Type Breakdown (All Time):")
                for stat in task_stats:
                    task_type = stat['_id']
                    count = stat['count']
                    tokens = stat['total_tokens']
                    success = stat['success_count']
                    success_rate = (success / count * 100) if count > 0 else 0
                    print(f"  {task_type:12s}: {count:5d} requests | {tokens:8d} tokens | {success_rate:5.1f}% success")
            
            results['activity'] = True
            results['total_requests'] = total_requests
        else:
            print("⚠️  No Gemini API requests found in database")
            results['activity'] = False
            results['total_requests'] = 0
        
        # 3. Check Today's Quota Usage
        print("\n" + "="*80)
        print("3. CHECKING TODAY'S QUOTA USAGE")
        print("="*80)
        
        gemini_quota = email_db["gemini_quota"]
        today = datetime.now().strftime("%Y-%m-%d")
        
        today_quotas = list(gemini_quota.find({"date": today}))
        
        if today_quotas:
            total_today = 0
            total_tokens_today = 0
            
            print(f"📊 Quota Usage for {today}:")
            for quota in sorted(today_quotas, key=lambda x: x.get('key_index', 0)):
                key_idx = quota.get('key_index', '?')
                requests = quota.get('requests_count', 0)
                tokens = quota.get('tokens_used', 0)
                percentage = (requests / 1000 * 100) if requests > 0 else 0
                total_today += requests
                total_tokens_today += tokens
                
                status = "✓" if requests < 900 else "⚠️" if requests < 1000 else "✗"
                print(f"  {status} Key #{key_idx}: {requests:4d}/1000 requests ({percentage:5.1f}%) | {tokens:6d} tokens")
            
            print(f"\n✓ Total today: {total_today}/7000 requests ({total_today/7000*100:.1f}%)")
            print(f"✓ Total tokens: {total_tokens_today:,}")
            print(f"✓ Remaining capacity: {7000-total_today} requests")
            
            results['quota'] = True
            results['today_requests'] = total_today
            results['today_tokens'] = total_tokens_today
        else:
            print(f"ℹ️  No quota data for today ({today})")
            results['quota'] = False
        
        # 4. Check Classified Emails
        print("\n" + "="*80)
        print("4. CHECKING CLASSIFIED EMAILS")
        print("="*80)
        
        classified_gmail = email_db["classified_gmail"]
        
        total_classified = classified_gmail.count_documents({})
        print(f"Total classified emails: {total_classified}")
        
        if total_classified > 0:
            # Get segment breakdown
            pipeline = [
                {"$group": {
                    "_id": "$segment",
                    "count": {"$sum": 1},
                    "high_priority": {"$sum": {"$cond": [{"$eq": ["$priority", "HIGH"]}, 1, 0]}}
                }},
                {"$sort": {"count": -1}}
            ]
            
            segment_stats = list(classified_gmail.aggregate(pipeline))
            
            print(f"\n📧 Email Classification Breakdown:")
            for stat in segment_stats:
                segment = stat['_id']
                count = stat['count']
                high_pri = stat['high_priority']
                percentage = (count / total_classified * 100) if total_classified > 0 else 0
                print(f"  {segment:12s}: {count:5d} emails ({percentage:5.1f}%) | {high_pri:4d} high priority")
            
            # Check recent classifications
            recent_classified = list(classified_gmail.find().sort("processed_at", -1).limit(5))
            
            if recent_classified:
                print(f"\n📬 Recent Classifications (last 5):")
                for email in recent_classified:
                    processed = email.get('processed_at', 'Unknown')
                    segment = email.get('segment', 'Unknown')
                    priority = email.get('priority', 'Unknown')
                    confidence = email.get('confidence', 0)
                    summary = email.get('summary', 'No summary')[:60]
                    print(f"  {processed} | {segment:10s} | {priority:6s} | {confidence:.2f} | {summary}...")
            
            results['classified'] = True
            results['total_classified'] = total_classified
        else:
            print("⚠️  No classified emails found")
            results['classified'] = False
            results['total_classified'] = 0
        
        # 5. Check Leads Generated
        print("\n" + "="*80)
        print("5. CHECKING LEADS GENERATED FROM AI CLASSIFICATION")
        print("="*80)
        
        leads_raw = email_db["leads_raw"]
        
        total_leads = leads_raw.count_documents({})
        gemini_leads = leads_raw.count_documents({"gemini_classification": {"$exists": True}})
        
        print(f"Total leads: {total_leads}")
        print(f"Leads with Gemini classification: {gemini_leads}")
        
        if gemini_leads > 0:
            # Get category breakdown
            pipeline = [
                {"$match": {"gemini_classification": {"$exists": True}}},
                {"$group": {
                    "_id": "$gemini_classification.category",
                    "count": {"$sum": 1},
                    "avg_buying_intent": {"$avg": "$gemini_classification.buying_intent"}
                }},
                {"$sort": {"count": -1}}
            ]
            
            category_stats = list(leads_raw.aggregate(pipeline))
            
            print(f"\n🎯 Lead Category Breakdown:")
            for stat in category_stats:
                category = stat['_id']
                count = stat['count']
                avg_intent = stat.get('avg_buying_intent', 0)
                percentage = (count / gemini_leads * 100) if gemini_leads > 0 else 0
                print(f"  {category:12s}: {count:5d} leads ({percentage:5.1f}%) | Avg Buying Intent: {avg_intent:.2f}")
            
            results['leads'] = True
            results['total_leads'] = gemini_leads
        else:
            print("⚠️  No leads with Gemini classification found")
            results['leads'] = False
            results['total_leads'] = 0
        
        # 6. Performance Metrics
        print("\n" + "="*80)
        print("6. PERFORMANCE METRICS (LAST 24 HOURS)")
        print("="*80)
        
        last_24h = datetime.now() - timedelta(hours=24)
        
        recent_requests = gemini_requests.count_documents({
            "timestamp": {"$gte": last_24h}
        })
        
        recent_classified = classified_gmail.count_documents({
            "processed_at": {"$gte": last_24h}
        })
        
        print(f"Gemini API requests (24h): {recent_requests}")
        print(f"Emails classified (24h): {recent_classified}")
        
        if recent_requests > 0:
            # Calculate average response time (estimate based on request count and time)
            avg_per_email = recent_requests / max(recent_classified, 1)
            print(f"Avg API calls per email: {avg_per_email:.1f}")
            
            # Success rate
            successful = gemini_requests.count_documents({
                "timestamp": {"$gte": last_24h},
                "success": True
            })
            success_rate = (successful / recent_requests * 100) if recent_requests > 0 else 0
            print(f"Success rate (24h): {success_rate:.1f}%")
        
        results['performance'] = recent_requests > 0
        
        # Final Summary
        print("\n" + "="*80)
        print("VERIFICATION SUMMARY")
        print("="*80)
        
        checks = [
            ("Gemini API Keys", results.get('keys', False)),
            ("API Activity", results.get('activity', False)),
            ("Quota Tracking", results.get('quota', False)),
            ("Email Classification", results.get('classified', False)),
            ("Lead Generation", results.get('leads', False)),
            ("Performance Metrics", results.get('performance', False))
        ]
        
        for check_name, passed in checks:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status}: {check_name}")
        
        all_passed = all(passed for _, passed in checks)
        
        print("\n" + "="*80)
        if all_passed:
            print("✅ ALL CHECKS PASSED!")
            print("\nYour Gemini API integration is working properly:")
            print(f"  • {results.get('keys_count', 0)}/7 API keys configured")
            print(f"  • {results.get('total_requests', 0):,} total API requests processed")
            print(f"  • {results.get('total_classified', 0):,} emails classified")
            print(f"  • {results.get('total_leads', 0):,} leads generated with AI enrichment")
            if results.get('today_requests', 0) > 0:
                print(f"  • {results.get('today_requests', 0)}/7000 quota used today ({results.get('today_requests', 0)/7000*100:.1f}%)")
        else:
            failed = [name for name, passed in checks if not passed]
            print("⚠️  SOME CHECKS FAILED!")
            print(f"\nFailed checks: {', '.join(failed)}")
            print("\nPossible issues:")
            if not results.get('keys', False):
                print("  • Gemini API keys not configured in database")
            if not results.get('activity', False):
                print("  • No API activity recorded (system may not be processing emails)")
            if not results.get('classified', False):
                print("  • No classified emails (email processor may not be running)")
        
        print("="*80)
        print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        return 0 if all_passed else 1
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
