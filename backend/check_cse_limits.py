"""
Check and update Google CSE rate limits and cache settings

Cost Optimization Settings:
    - Cache settings reduce API calls by 70%+
    - Deduplication prevents duplicate leads
"""
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client['torpedo_settings']
settings_collection = db['app_settings']

def get_current_settings():
    """Get current rate limit and cache settings"""
    settings = settings_collection.find_one({'_id': 'app_config'})
    if settings:
        print("\n=== Current Google CSE Settings ===")
        print(f"  Daily Limit:       {settings.get('google_cse_daily_limit', 400)}")
        print(f"  Hourly Limit:      {settings.get('google_cse_hourly_limit', 50)}")
        print(f"  Query Delay (sec): {settings.get('google_cse_query_delay', 3)}")
        print(f"  Monthly Budget ($):{settings.get('google_cse_monthly_budget', 50.0)}")
        print(f"  Rate Limit Enabled:{settings.get('google_cse_rate_limit_enabled', True)}")
        
        print("\n=== Cache Settings (Cost Optimization) ===")
        print(f"  Cache Enabled:     {settings.get('cache_enabled', True)}")
        print(f"  Cache TTL (hours): {settings.get('cache_ttl_hours', 48)}")
        print(f"  Target Hit Rate:   {settings.get('cache_hit_target', 0.70)}")
        print(f"  Normalize Queries: {settings.get('normalize_queries', True)}")
        
        print("\n=== Deduplication Settings ===")
        print(f"  Dedup Enabled:     {settings.get('dedup_enabled', True)}")
        print(f"  Check Email:       {settings.get('dedup_check_email', True)}")
        print(f"  Check Name+Company:{settings.get('dedup_check_name_company', True)}")
        
        return settings
    else:
        print("No settings found - using defaults")
        return None

def update_limits(daily=None, hourly=None, delay=None, budget=None, enabled=None):
    """Update rate limit settings"""
    updates = {}
    if daily is not None:
        updates['google_cse_daily_limit'] = daily
    if hourly is not None:
        updates['google_cse_hourly_limit'] = hourly
    if delay is not None:
        updates['google_cse_query_delay'] = delay
    if budget is not None:
        updates['google_cse_monthly_budget'] = budget
    if enabled is not None:
        updates['google_cse_rate_limit_enabled'] = enabled
    
    if updates:
        result = settings_collection.update_one(
            {'_id': 'app_config'},
            {'$set': updates},
            upsert=True
        )
        print(f"\n✓ Updated settings: {updates}")
        return True
    return False


def update_cache_settings(cache_enabled=None, ttl_hours=None, hit_target=None, normalize=None):
    """Update cache settings for cost optimization"""
    updates = {}
    if cache_enabled is not None:
        updates['cache_enabled'] = cache_enabled
    if ttl_hours is not None:
        updates['cache_ttl_hours'] = ttl_hours
    if hit_target is not None:
        updates['cache_hit_target'] = hit_target
    if normalize is not None:
        updates['normalize_queries'] = normalize
    
    if updates:
        result = settings_collection.update_one(
            {'_id': 'app_config'},
            {'$set': updates},
            upsert=True
        )
        print(f"\n✓ Updated cache settings: {updates}")
        return True
    return False


def update_dedup_settings(dedup_enabled=None, check_email=None, check_name_company=None):
    """Update deduplication settings"""
    updates = {}
    if dedup_enabled is not None:
        updates['dedup_enabled'] = dedup_enabled
    if check_email is not None:
        updates['dedup_check_email'] = check_email
    if check_name_company is not None:
        updates['dedup_check_name_company'] = check_name_company
    
    if updates:
        result = settings_collection.update_one(
            {'_id': 'app_config'},
            {'$set': updates},
            upsert=True
        )
        print(f"\n✓ Updated dedup settings: {updates}")
        return True
    return False


def show_cache_stats():
    """Show cache performance statistics"""
    try:
        from leads.search_cache import get_cache_stats, get_cache_size
        
        stats = get_cache_stats()
        size = get_cache_size()
        
        print("\n=== Cache Performance (Last 7 Days) ===")
        print(f"  Total Requests:    {stats['total_requests']}")
        print(f"  Cache Hits:        {stats['cache_hits']}")
        print(f"  Cache Misses:      {stats['cache_misses']}")
        print(f"  Hit Rate:          {stats['hit_rate']:.2%}")
        print(f"  Est. API Savings:  {stats['estimated_savings_percent']:.1f}%")
        print(f"\n  Cache Entries:     {size['entry_count']}")
        print(f"  Cache Size:        {size['size_mb']:.2f} MB")
        
        # Cost estimate
        if stats['cache_hits'] > 0:
            # $5 per 1000 queries
            saved_cost = (stats['cache_hits'] / 1000) * 5
            print(f"\n  Est. Cost Saved:   ${saved_cost:.2f}")
            
    except ImportError:
        print("Cache module not available")


def show_dedup_stats():
    """Show deduplication statistics"""
    try:
        from leads.deduplication import get_duplicate_stats
        
        stats = get_duplicate_stats()
        
        print(f"\n=== Deduplication Stats (Last {stats['period_days']} Days) ===")
        print(f"  Total Rejected:    {stats['total_rejected']}")
        for reason, count in stats.get('by_reason', {}).items():
            print(f"    - {reason}: {count}")
            
    except ImportError:
        print("Deduplication module not available")


# ============== ADDITIONAL OPTIMIZER SETTINGS ==============

def update_optimizer_settings(args):
    """Update all optimizer settings"""
    updates = {}
    
    for arg in args:
        if '=' in arg:
            key, value = arg.split('=', 1)
            bool_val = value.lower() == 'true'
            
            if key == 'smart_queries':
                updates['smart_queries_enabled'] = bool_val
            elif key == 'batch':
                updates['batch_enrichment_enabled'] = bool_val
            elif key == 'batch_min':
                updates['batch_enrichment_min_size'] = int(value)
            elif key == 'url_validation':
                updates['url_validation_enabled'] = bool_val
            elif key == 'perplexity':
                updates['perplexity_enabled'] = bool_val
            elif key == 'perplexity_key':
                updates['perplexity_api_key'] = value
    
    if updates:
        settings_collection.update_one(
            {'_id': 'app_config'},
            {'$set': updates},
            upsert=True
        )
        print(f"\n✓ Updated optimizer settings: {list(updates.keys())}")


def show_optimizer_stats():
    """Show all optimizer module statistics"""
    print("\n=== Optimizer Module Stats ===")
    
    # Query Generator stats
    try:
        from leads.query_generator import get_query_generation_stats
        stats = get_query_generation_stats()
        print(f"\n[Query Generator]")
        print(f"  Plans Generated:   {stats['total_plans']}")
        print(f"  Cache Hit Rate:    {stats['cache_hit_rate']:.1%}")
        print(f"  Fallbacks Used:    {stats['fallbacks_used']}")
    except Exception as e:
        print(f"\n[Query Generator] Not available: {e}")
    
    # URL Validator stats
    try:
        from leads.url_validator import get_validation_stats
        stats = get_validation_stats()
        print(f"\n[URL Validator]")
        print(f"  Total Validated:   {stats['total_validated']}")
        print(f"  Valid:             {stats['valid_count']} ({stats['valid_rate']:.1%})")
        print(f"  Invalid:           {stats['invalid_count']}")
        print(f"  Wasted Enrichment Prevented: {stats['invalid_count']}")
    except Exception as e:
        print(f"\n[URL Validator] Not available: {e}")
    
    # Batch Enrichment stats
    try:
        from leads.batch_enrichment import get_batch_stats
        stats = get_batch_stats()
        print(f"\n[Batch Enrichment]")
        print(f"  Total Enriched:    {stats['total_enriched_via_batch']}")
        print(f"  Pending Jobs:      {stats['pending_jobs']}")
        print(f"  Est. Savings:      ${stats['estimated_savings_usd']:.2f}")
    except Exception as e:
        print(f"\n[Batch Enrichment] Not available: {e}")
    
    # Perplexity stats
    try:
        from leads.perplexity_client import get_perplexity_usage_stats
        stats = get_perplexity_usage_stats()
        print(f"\n[Perplexity Discovery]")
        print(f"  Total Queries:     {stats['total_queries']}")
        print(f"  Companies Found:   {stats.get('companies_discovered', 'N/A')}")
        print(f"  Cost (est):        ${stats.get('estimated_cost_usd', 0):.2f}")
    except Exception as e:
        print(f"\n[Perplexity Discovery] Not available: {e}")


def show_cost_savings_report():
    """Generate comprehensive cost savings report"""
    print("\n" + "="*60)
    print("         COST OPTIMIZATION SAVINGS REPORT")
    print("="*60)
    
    total_savings_inr = 0
    
    # 1. Cache savings
    try:
        from leads.search_cache import get_cache_stats
        stats = get_cache_stats()
        cache_savings = (stats['cache_hits'] / 1000) * 5 * 84  # $5 per 1000, INR 84/$
        total_savings_inr += cache_savings
        print(f"\n1. SEARCH CACHING")
        print(f"   Cache Hits:        {stats['cache_hits']}")
        print(f"   API Calls Saved:   {stats['cache_hits']}")
        print(f"   Savings:           ₹{cache_savings:.2f}")
    except:
        print(f"\n1. SEARCH CACHING: Not available")
    
    # 2. Deduplication savings
    try:
        from leads.deduplication import get_duplicate_stats
        stats = get_duplicate_stats()
        # Each duplicate blocked saves ~$0.0007 enrichment + possible future emails
        dedup_savings = stats['total_rejected'] * 0.0007 * 84
        total_savings_inr += dedup_savings
        print(f"\n2. DEDUPLICATION")
        print(f"   Duplicates Blocked: {stats['total_rejected']}")
        print(f"   Savings:            ₹{dedup_savings:.2f}")
    except:
        print(f"\n2. DEDUPLICATION: Not available")
    
    # 3. Batch API savings
    try:
        from leads.batch_enrichment import get_batch_stats
        stats = get_batch_stats()
        batch_savings = stats['estimated_savings_usd'] * 84
        total_savings_inr += batch_savings
        print(f"\n3. BATCH ENRICHMENT (50% off OpenAI)")
        print(f"   Leads Enriched:     {stats['total_enriched_via_batch']}")
        print(f"   Savings:            ₹{batch_savings:.2f}")
    except:
        print(f"\n3. BATCH ENRICHMENT: Not available")
    
    # 4. URL Validation savings
    try:
        from leads.url_validator import get_validation_stats
        stats = get_validation_stats()
        # Each invalid URL caught saves $0.0007 enrichment cost
        url_savings = stats['invalid_count'] * 0.0007 * 84
        total_savings_inr += url_savings
        print(f"\n4. URL VALIDATION")
        print(f"   Invalid URLs Caught: {stats['invalid_count']}")
        print(f"   Wasted Enrichment Prevented: {stats['invalid_count']}")
        print(f"   Savings:             ₹{url_savings:.2f}")
    except:
        print(f"\n4. URL VALIDATION: Not available")
    
    print("\n" + "-"*60)
    print(f"   TOTAL ESTIMATED SAVINGS: ₹{total_savings_inr:.2f}")
    print("-"*60)
    
    # Monthly projection
    monthly_projection = total_savings_inr * 4  # Rough monthly estimate
    print(f"   Monthly Projection:      ₹{monthly_projection:.2f}")
    
    # Compare to baseline
    print(f"\n   Baseline (before optimization): ₹24,070/month")
    print(f"   Target (after optimization):    ₹8,200/month")
    print(f"   Target Savings:                 ₹15,870/month (66%)")
    print("="*60)


# ============== MAIN ==============

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) == 1:
        get_current_settings()
        show_cache_stats()
        show_dedup_stats()
    elif sys.argv[1] == 'set':
        # Parse args: set daily=100 hourly=10 delay=5 budget=20
        for arg in sys.argv[2:]:
            if '=' in arg:
                key, value = arg.split('=', 1)
                if key == 'daily':
                    update_limits(daily=int(value))
                elif key == 'hourly':
                    update_limits(hourly=int(value))
                elif key == 'delay':
                    update_limits(delay=int(value))
                elif key == 'budget':
                    update_limits(budget=float(value))
                elif key == 'enabled':
                    update_limits(enabled=value.lower() == 'true')
        get_current_settings()
    elif sys.argv[1] == 'cache':
        # Cache settings: cache ttl=24 enabled=true target=0.80
        for arg in sys.argv[2:]:
            if '=' in arg:
                key, value = arg.split('=', 1)
                if key == 'enabled':
                    update_cache_settings(cache_enabled=value.lower() == 'true')
                elif key == 'ttl':
                    update_cache_settings(ttl_hours=int(value))
                elif key == 'target':
                    update_cache_settings(hit_target=float(value))
                elif key == 'normalize':
                    update_cache_settings(normalize=value.lower() == 'true')
        get_current_settings()
    elif sys.argv[1] == 'dedup':
        # Dedup settings: dedup enabled=true email=true name_company=true
        for arg in sys.argv[2:]:
            if '=' in arg:
                key, value = arg.split('=', 1)
                if key == 'enabled':
                    update_dedup_settings(dedup_enabled=value.lower() == 'true')
                elif key == 'email':
                    update_dedup_settings(check_email=value.lower() == 'true')
                elif key == 'name_company':
                    update_dedup_settings(check_name_company=value.lower() == 'true')
        get_current_settings()
    elif sys.argv[1] == 'optimizer':
        update_optimizer_settings(sys.argv[2:])
        get_current_settings()
    elif sys.argv[1] == 'stats':
        show_cache_stats()
        show_dedup_stats()
        show_optimizer_stats()
    elif sys.argv[1] == 'cost':
        show_cost_savings_report()
    else:
        print("Usage:")
        print("  python check_cse_limits.py                    # View all settings + stats")
        print("  python check_cse_limits.py set daily=100 hourly=10 delay=5 budget=20")
        print("  python check_cse_limits.py cache ttl=48 enabled=true target=0.70")
        print("  python check_cse_limits.py dedup enabled=true email=true name_company=true")
        print("  python check_cse_limits.py optimizer smart_queries=true batch=true url_validation=true perplexity=true")
        print("  python check_cse_limits.py stats              # View cache, dedup & optimizer stats")
        print("  python check_cse_limits.py cost               # Cost savings report")

