"""
MongoDB Setup Script
Creates collections and indexes for the hybrid Gemini + OpenAI system
"""

import os
from pymongo import MongoClient, ASCENDING, DESCENDING
from datetime import datetime


def setup_mongodb(mongo_uri: str = None):
    """
    Set up all collections and indexes for the system
    
    Args:
        mongo_uri: MongoDB connection string (default from env)
    """
    if mongo_uri is None:
        mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    
    client = MongoClient(mongo_uri)
    
    print("=== MongoDB Setup for Hybrid Lead Generation System ===\n")
    
    # ========================================
    # 1. CLASSIFIED_GMAIL Collection
    # ========================================
    print("1. Setting up classified_gmail collection...")
    db = client["email_automation"]
    classified_gmail = db["classified_gmail"]
    
    # Drop existing indexes (optional - comment out if you want to preserve)
    # classified_gmail.drop_indexes()
    
    # Create indexes
    classified_gmail.create_index([("email_id", ASCENDING)], unique=True, name="idx_email_id")
    classified_gmail.create_index([("segment", ASCENDING)], name="idx_segment")
    classified_gmail.create_index([("processed_at", DESCENDING)], name="idx_processed_at")
    classified_gmail.create_index([("moved_to_leads", ASCENDING)], name="idx_moved_to_leads")
    classified_gmail.create_index([("priority", ASCENDING)], name="idx_priority")
    classified_gmail.create_index([("confidence", DESCENDING)], name="idx_confidence")
    classified_gmail.create_index([("urgency", ASCENDING)], name="idx_urgency")
    
    print(f"   ✓ Created {len(list(classified_gmail.list_indexes()))} indexes")
    print(f"   ✓ Current documents: {classified_gmail.count_documents({})}\n")
    
    # ========================================
    # 2. COMPANY_CACHE Collection
    # ========================================
    print("2. Setting up company_cache collection...")
    company_cache = db["company_cache"]
    
    company_cache.create_index([("company_domain", ASCENDING)], unique=True, name="idx_company_domain")
    company_cache.create_index([("company_name_normalized", ASCENDING)], name="idx_company_name")
    company_cache.create_index([("expires_at", ASCENDING)], name="idx_expires_at")
    company_cache.create_index([("last_accessed", DESCENDING)], name="idx_last_accessed")
    company_cache.create_index([("hit_count", DESCENDING)], name="idx_hit_count")
    company_cache.create_index([("industry", ASCENDING)], name="idx_industry")
    
    print(f"   ✓ Created {len(list(company_cache.list_indexes()))} indexes")
    print(f"   ✓ Current documents: {company_cache.count_documents({})}\n")
    
    # ========================================
    # 3. EMAIL_PATTERNS Collection
    # ========================================
    print("3. Setting up email_patterns collection...")
    email_patterns = db["email_patterns"]
    
    email_patterns.create_index([("domain", ASCENDING)], unique=True, name="idx_domain")
    email_patterns.create_index([("confidence", DESCENDING)], name="idx_confidence")
    email_patterns.create_index([("last_verified", DESCENDING)], name="idx_last_verified")
    email_patterns.create_index([("source", ASCENDING)], name="idx_source")
    email_patterns.create_index([("hit_count", DESCENDING)], name="idx_hit_count")
    
    print(f"   ✓ Created {len(list(email_patterns.list_indexes()))} indexes")
    print(f"   ✓ Current documents: {email_patterns.count_documents({})}\n")
    
    # ========================================
    # 4. GEMINI_QUOTA Collection
    # ========================================
    print("4. Setting up gemini_quota collection...")
    gemini_quota = db["gemini_quota"]
    
    gemini_quota.create_index([("key_index", ASCENDING), ("date", ASCENDING)], unique=True, name="idx_key_date")
    gemini_quota.create_index([("date", ASCENDING)], name="idx_date")
    gemini_quota.create_index([("requests_count", DESCENDING)], name="idx_requests_count")
    
    # Initialize quota tracking for today
    today = datetime.now().strftime("%Y-%m-%d")
    for key_index in range(1, 8):  # 7 keys
        gemini_quota.update_one(
            {"key_index": key_index, "date": today},
            {
                "$setOnInsert": {
                    "requests_count": 0,
                    "tokens_used": 0,
                    "last_request_time": None,
                    "minute_requests": [],
                    "created_at": datetime.now()
                }
            },
            upsert=True
        )
    
    print(f"   ✓ Created {len(list(gemini_quota.list_indexes()))} indexes")
    print(f"   ✓ Initialized quota tracking for {today}")
    print(f"   ✓ Current documents: {gemini_quota.count_documents({})}\n")
    
    # ========================================
    # 5. GEMINI_REQUESTS Collection
    # ========================================
    print("5. Setting up gemini_requests collection...")
    gemini_requests = db["gemini_requests"]
    
    gemini_requests.create_index([("key_index", ASCENDING), ("timestamp", DESCENDING)], name="idx_key_timestamp")
    gemini_requests.create_index([("task_type", ASCENDING)], name="idx_task_type")
    gemini_requests.create_index([("timestamp", DESCENDING)], name="idx_timestamp")
    gemini_requests.create_index([("success", ASCENDING)], name="idx_success")
    gemini_requests.create_index([("date", ASCENDING)], name="idx_date")
    
    print(f"   ✓ Created {len(list(gemini_requests.list_indexes()))} indexes")
    print(f"   ✓ Current documents: {gemini_requests.count_documents({})}\n")
    
    # ========================================
    # 6. ENRICHMENT_LOGS Collection (optional - for tracking)
    # ========================================
    print("6. Setting up enrichment_logs collection...")
    enrichment_logs = db["enrichment_logs"]
    
    enrichment_logs.create_index([("lead_id", ASCENDING)], name="idx_lead_id")
    enrichment_logs.create_index([("timestamp", DESCENDING)], name="idx_timestamp")
    enrichment_logs.create_index([("enrichment_type", ASCENDING)], name="idx_enrichment_type")
    enrichment_logs.create_index([("source", ASCENDING)], name="idx_source")
    
    print(f"   ✓ Created {len(list(enrichment_logs.list_indexes()))} indexes")
    print(f"   ✓ Current documents: {enrichment_logs.count_documents({})}\n")
    
    # ========================================
    # 7. Update existing collections (if needed)
    # ========================================
    print("7. Updating existing collections...")
    
    # leads_raw - add new indexes for Gemini integration
    leads_raw = db["leads_raw"]
    try:
        leads_raw.create_index([("source", ASCENDING)], name="idx_source")
        leads_raw.create_index([("category", ASCENDING)], name="idx_category")
        leads_raw.create_index([("created_at", DESCENDING)], name="idx_created_at")
        leads_raw.create_index([("email", ASCENDING)], name="idx_email")
        print(f"   ✓ Updated leads_raw indexes")
    except Exception as e:
        print(f"   ⚠ leads_raw indexes may already exist: {e}")
    
    # mail_pool - add index for sender email
    mail_pool = db["mail_pool"]
    try:
        mail_pool.create_index([("sender.email", ASCENDING)], name="idx_sender_email")
        mail_pool.create_index([("date", DESCENDING)], name="idx_date")
        print(f"   ✓ Updated mail_pool indexes")
    except Exception as e:
        print(f"   ⚠ mail_pool indexes may already exist: {e}")
    
    print()
    
    # ========================================
    # Summary
    # ========================================
    print("=== Setup Complete ===\n")
    print("Collections created/updated:")
    print("  1. classified_gmail - Gemini-classified emails ready for manual review")
    print("  2. company_cache - 90-day cache for company details")
    print("  3. email_patterns - Discovered email patterns with tiered fallback")
    print("  4. gemini_quota - 7-key rotation quota tracking")
    print("  5. gemini_requests - Detailed request logging")
    print("  6. enrichment_logs - Enrichment activity tracking")
    print("  7. leads_raw - Updated indexes for Gemini integration")
    print("  8. mail_pool - Updated indexes for pattern analysis\n")
    
    print("Next steps:")
    print("  1. Add $10-20 to OpenAI account at https://platform.openai.com/account/billing")
    print("  2. Ensure 7 Gemini API keys are in torpedo_settings.app_settings (gemini_api_key_1 to 7)")
    print("  3. Add Hunter.io API key to app_settings (hunter_api_key) - optional but recommended")
    print("  4. Run: python -m backend.leads.email_pattern_system to analyze mail_pool patterns")
    print("  5. Test Gemini rotation: python -m backend.leads.gemini_rotator")
    print("  6. Process emails: python -m backend.leads.email_processor\n")
    
    client.close()


if __name__ == "__main__":
    print("Starting MongoDB setup...\n")
    
    try:
        setup_mongodb()
        print("✅ MongoDB setup completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during setup: {e}")
        import traceback
        traceback.print_exc()
