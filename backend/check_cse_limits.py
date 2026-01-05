"""
Check and update Google CSE rate limits
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
    """Get current rate limit settings"""
    settings = settings_collection.find_one({'_id': 'app_config'})
    if settings:
        print("\n=== Current Google CSE Settings ===")
        print(f"  Daily Limit:       {settings.get('google_cse_daily_limit', 400)}")
        print(f"  Hourly Limit:      {settings.get('google_cse_hourly_limit', 50)}")
        print(f"  Query Delay (sec): {settings.get('google_cse_query_delay', 3)}")
        print(f"  Monthly Budget ($):{settings.get('google_cse_monthly_budget', 50.0)}")
        print(f"  Rate Limit Enabled:{settings.get('google_cse_rate_limit_enabled', True)}")
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

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) == 1:
        get_current_settings()
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
    else:
        print("Usage:")
        print("  python check_cse_limits.py           # View current settings")
        print("  python check_cse_limits.py set daily=100 hourly=10 delay=5 budget=20")
