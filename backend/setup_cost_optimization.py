"""
COST OPTIMIZATION SETUP SCRIPT
Run this once to set up caching and deduplication indexes.

Usage:
    python setup_cost_optimization.py          # Full setup
    python setup_cost_optimization.py indexes  # Create indexes only
    python setup_cost_optimization.py dedup    # Rebuild dedup index only
    python setup_cost_optimization.py status   # Check current status
"""

import os
import sys
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()


def setup_collections():
    """Ensure all cost optimization collections exist with proper indexes"""
    print("\n" + "="*60)
    print("COST OPTIMIZATION SETUP")
    print("="*60)
    
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    
    # Test connection
    try:
        client.admin.command('ping')
        print("✅ MongoDB connection successful")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False
    
    db = client['email_automation']
    
    # Create collections if they don't exist
    collections = [
        'search_cache',
        'search_cache_metrics', 
        'dedup_index',
        'dedup_logs'
    ]
    
    existing = db.list_collection_names()
    for coll in collections:
        if coll not in existing:
            db.create_collection(coll)
            print(f"✅ Created collection: {coll}")
        else:
            print(f"  Collection exists: {coll}")
    
    return True


def setup_indexes():
    """Create all required indexes"""
    print("\n--- Setting up indexes ---")
    
    try:
        from leads.search_cache import ensure_cache_indexes
        from leads.deduplication import ensure_dedup_indexes
        
        ensure_cache_indexes()
        ensure_dedup_indexes()
        print("✅ All indexes created")
        return True
    except Exception as e:
        print(f"❌ Error creating indexes: {e}")
        
        # Fallback: create indexes directly
        print("Attempting fallback index creation...")
        
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        db = client['email_automation']
        
        # Search cache indexes
        search_cache = db['search_cache']
        search_cache.create_index("query_hash", unique=True)
        search_cache.create_index("created_at")
        search_cache.create_index("expires_at", expireAfterSeconds=0)
        search_cache.create_index("provider")
        print("✅ Search cache indexes created")
        
        # Dedup indexes
        dedup_index = db['dedup_index']
        dedup_index.create_index("linkedin_url_hash", unique=True, sparse=True)
        dedup_index.create_index("email_hash", sparse=True)
        dedup_index.create_index("name_company_hash", sparse=True)
        dedup_index.create_index("lead_id")
        print("✅ Dedup indexes created")
        
        return True


def rebuild_dedup_index():
    """Rebuild deduplication index from existing leads"""
    print("\n--- Rebuilding deduplication index ---")
    
    try:
        from leads.deduplication import rebuild_dedup_index as rebuild
        result = rebuild()
        print(f"✅ Rebuilt index: {result}")
        return True
    except Exception as e:
        print(f"❌ Error rebuilding dedup index: {e}")
        return False


def setup_default_settings():
    """Set up default cache and dedup settings"""
    print("\n--- Setting up default settings ---")
    
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    settings_db = client['torpedo_settings']
    app_settings = settings_db['app_settings']
    
    # Default settings
    defaults = {
        # Cache settings
        'cache_enabled': True,
        'cache_ttl_hours': 48,
        'cache_hit_target': 0.70,
        'normalize_queries': True,
        
        # Dedup settings
        'dedup_enabled': True,
        'dedup_check_email': True,
        'dedup_check_name_company': True,
    }
    
    # Only set if not already set
    existing = app_settings.find_one({'_id': 'app_config'}) or {}
    
    updates = {}
    for key, value in defaults.items():
        if key not in existing:
            updates[key] = value
    
    if updates:
        app_settings.update_one(
            {'_id': 'app_config'},
            {'$set': updates},
            upsert=True
        )
        print(f"✅ Set default settings: {list(updates.keys())}")
    else:
        print("  All settings already configured")
    
    return True


def setup_optimizer_settings():
    """Set up Phase 2-4 optimizer settings"""
    print("\n--- Setting up optimizer settings ---")
    
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    settings_db = client['torpedo_settings']
    app_settings = settings_db['app_settings']
    
    # Phase 2-4 settings
    optimizer_defaults = {
        # Phase 2: Smart Query Generation
        'smart_queries_enabled': True,
        
        # Phase 3: Perplexity Discovery
        'perplexity_enabled': False,  # Disabled until API key is set
        'perplexity_api_key': '',
        'perplexity_daily_limit': 100,
        
        # Phase 4: URL Validation
        'url_validation_enabled': True,
        'url_validation_cache_days': 7,
        
        # Phase 4: Batch Enrichment
        'batch_enrichment_enabled': True,
        'batch_enrichment_min_size': 10,
    }
    
    existing = app_settings.find_one({'_id': 'app_config'}) or {}
    
    updates = {}
    for key, value in optimizer_defaults.items():
        if key not in existing:
            updates[key] = value
    
    if updates:
        app_settings.update_one(
            {'_id': 'app_config'},
            {'$set': updates},
            upsert=True
        )
        print(f"✅ Set optimizer settings: {list(updates.keys())}")
    else:
        print("  All optimizer settings already configured")
    
    return True


def setup_optimizer_collections():
    """Create Phase 2-4 collections"""
    print("\n--- Setting up optimizer collections ---")
    
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = client['email_automation']
    
    collections = [
        'query_generation_cache',
        'query_generation_logs',
        'discovery_cache',
        'perplexity_usage_logs',
        'url_validation_cache',
        'url_validation_logs',
        'batch_enrichment_jobs',
        'batch_enrichment_results'
    ]
    
    existing = db.list_collection_names()
    for coll in collections:
        if coll not in existing:
            db.create_collection(coll)
            print(f"✅ Created collection: {coll}")
        else:
            print(f"  Collection exists: {coll}")
    
    return True


def setup_optimizer_indexes():
    """Create Phase 2-4 indexes"""
    print("\n--- Setting up optimizer indexes ---")
    
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = client['email_automation']
    
    def safe_create_index(collection, *args, **kwargs):
        """Create index, ignore if already exists with different options"""
        try:
            db[collection].create_index(*args, **kwargs)
        except Exception as e:
            if 'IndexOptionsConflict' not in str(e):
                raise
            # Index exists with different options - skip
    
    # Query generation cache
    safe_create_index('query_generation_cache', "plan_hash", unique=True)
    safe_create_index('query_generation_cache', "expires_at", expireAfterSeconds=0)
    print("✅ Query generation indexes created")
    
    # Discovery cache (Perplexity)
    safe_create_index('discovery_cache', "query_hash", unique=True)
    safe_create_index('discovery_cache', "query_type")
    safe_create_index('discovery_cache', "expires_at", expireAfterSeconds=0)
    print("✅ Discovery cache indexes created")
    
    # URL validation cache
    safe_create_index('url_validation_cache', "url_hash", unique=True)
    safe_create_index('url_validation_cache', "validated_at")
    safe_create_index('url_validation_cache', "expires_at", expireAfterSeconds=0)
    print("✅ URL validation indexes created")
    
    # Batch enrichment
    safe_create_index('batch_enrichment_jobs', "batch_id", unique=True, sparse=True)
    safe_create_index('batch_enrichment_jobs', "status")
    safe_create_index('batch_enrichment_jobs', "created_at")
    safe_create_index('batch_enrichment_results', "batch_job_id")
    safe_create_index('batch_enrichment_results', "lead_id")
    print("✅ Batch enrichment indexes created")
    
    return True
    
    return True


def show_status():
    """Show current status of cost optimization features"""
    print("\n" + "="*60)
    print("COST OPTIMIZATION STATUS")
    print("="*60)
    
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    
    # Check settings
    settings_db = client['torpedo_settings']
    settings = settings_db['app_settings'].find_one({'_id': 'app_config'}) or {}
    
    print("\n--- Phase 1: Cache & Dedup ---")
    print(f"  Cache Enabled:      {settings.get('cache_enabled', True)}")
    print(f"  Cache TTL (hours):  {settings.get('cache_ttl_hours', 48)}")
    print(f"  Cache Target Rate:  {settings.get('cache_hit_target', 0.70):.0%}")
    print(f"  Dedup Enabled:      {settings.get('dedup_enabled', True)}")
    
    print("\n--- Phase 2-4: Optimizers ---")
    print(f"  Smart Queries:      {settings.get('smart_queries_enabled', False)}")
    print(f"  Perplexity:         {settings.get('perplexity_enabled', False)}")
    print(f"  URL Validation:     {settings.get('url_validation_enabled', False)}")
    print(f"  Batch Enrichment:   {settings.get('batch_enrichment_enabled', False)}")
    
    # Check collections
    db = client['email_automation']
    
    print("\n--- Collections ---")
    print(f"  search_cache:        {db['search_cache'].count_documents({})} entries")
    print(f"  dedup_index:         {db['dedup_index'].count_documents({})} entries")
    print(f"  url_validation_cache:{db['url_validation_cache'].count_documents({})} entries")
    print(f"  batch_enrichment_jobs:{db['batch_enrichment_jobs'].count_documents({})} jobs")
    
    # Check leads
    print(f"\n  leads_raw:           {db['leads_raw'].count_documents({})} leads")
    print(f"  leads_enriched:      {db['leads_enriched'].count_documents({})} leads")
    
    # Cache stats
    try:
        from leads.search_cache import get_cache_stats
        stats = get_cache_stats()
        
        print(f"\n--- Cache Performance (Last 7 Days) ---")
        print(f"  Total Requests:     {stats['total_requests']}")
        print(f"  Cache Hits:         {stats['cache_hits']}")
        print(f"  Hit Rate:           {stats['hit_rate']:.2%}")
        
        if stats['cache_hits'] > 0:
            saved_cost = (stats['cache_hits'] / 1000) * 5  # $5 per 1000 queries
            print(f"  Est. Cost Saved:    ${saved_cost:.2f}")
    except Exception as e:
        print(f"\n  (Cache stats unavailable: {e})")
    
    # Dedup stats
    try:
        from leads.deduplication import get_duplicate_stats
        stats = get_duplicate_stats()
        
        print(f"\n--- Deduplication Stats (Last 7 Days) ---")
        print(f"  Duplicates Blocked: {stats['total_rejected']}")
    except Exception as e:
        print(f"\n  (Dedup stats unavailable: {e})")
    
    # Batch enrichment stats
    try:
        from leads.batch_enrichment import get_batch_stats
        stats = get_batch_stats()
        
        print(f"\n--- Batch Enrichment Stats ---")
        print(f"  Total Enriched:     {stats['total_enriched_via_batch']}")
        print(f"  Pending Jobs:       {stats['pending_jobs']}")
        print(f"  Est. Savings:       ${stats['estimated_savings_usd']:.2f}")
    except Exception as e:
        print(f"\n  (Batch stats unavailable: {e})")
    
    print("\n" + "="*60)


def main():
    """Main entry point"""
    if len(sys.argv) == 1:
        # Full setup
        if setup_collections():
            setup_indexes()
            setup_default_settings()
            setup_optimizer_collections()
            setup_optimizer_indexes()
            setup_optimizer_settings()
            rebuild_dedup_index()
            show_status()
            print("\n✅ FULL COST OPTIMIZATION SETUP COMPLETE!")
            print("\n" + "="*60)
            print("Expected Monthly Savings:")
            print("="*60)
            print("  Google CSE:    ₹15,472 → ₹4,500  (70% reduction)")
            print("  OpenAI:        ₹600    → ₹200    (50% batch savings)")
            print("  Infrastructure:₹7,600  → ₹3,200  (spot VMs - manual)")
            print("  ─────────────────────────────────────")
            print("  TOTAL:         ₹24,070 → ₹8,200  (~66% savings)")
            print("="*60)
            print("\nNext steps:")
            print("  1. Run the optimized scheduler:")
            print("     from leads import start_optimized_scheduler")
            print("     start_optimized_scheduler()")
            print("\n  2. Monitor savings with:")
            print("     python check_cse_limits.py cost")
            
    elif sys.argv[1] == 'indexes':
        setup_collections()
        setup_indexes()
        setup_optimizer_collections()
        setup_optimizer_indexes()
        
    elif sys.argv[1] == 'dedup':
        rebuild_dedup_index()
        
    elif sys.argv[1] == 'status':
        show_status()
        
    elif sys.argv[1] == 'settings':
        setup_default_settings()
        setup_optimizer_settings()
        
    elif sys.argv[1] == 'phase2':
        setup_optimizer_collections()
        setup_optimizer_indexes()
        setup_optimizer_settings()
        print("✅ Phase 2-4 setup complete")
        
    else:
        print(__doc__)
        print("\nAdditional commands:")
        print("  python setup_cost_optimization.py phase2   # Setup Phase 2-4 only")


if __name__ == '__main__':
    main()
