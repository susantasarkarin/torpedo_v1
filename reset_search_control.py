#!/usr/bin/env python3
"""Check and reset search control state"""

from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
settings_db = client['torpedo_settings']

# Check search control state
control = settings_db['app_settings'].find_one({'_id': 'search_control'})
print('Current Search Control State:')
print(control)

# Reset the search control if it has circuit breaker open or is paused
if control and (control.get('circuit_breaker_open') or control.get('paused')):
    print("\nResetting search control...")
    result = settings_db['app_settings'].update_one(
        {'_id': 'search_control'},
        {'$set': {
            'paused': False,
            'paused_at': None,
            'paused_reason': '',
            'consecutive_errors': 0,
            'circuit_breaker_open': False,
            'last_error': None
        }}
    )
    print(f"Updated: {result.modified_count}")
    
    # Verify
    control = settings_db['app_settings'].find_one({'_id': 'search_control'})
    print("\nNew Search Control State:")
    print(control)
else:
    print("\nSearch control is already in a healthy state.")
