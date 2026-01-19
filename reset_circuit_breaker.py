#!/usr/bin/env python3
"""Reset circuit breaker state for web search"""

from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')

# Check and reset circuit breaker state
db = client['torpedo_settings']

# Check all circuit breakers
print("All circuit breakers:")
for breaker in db['circuit_breakers'].find():
    print(f"  - {breaker}")

# Reset web_search circuit breaker
breaker = db['circuit_breakers'].find_one({'name': 'web_search'})
print(f'\nWeb search circuit breaker: {breaker}')

if breaker:
    result = db['circuit_breakers'].delete_one({'name': 'web_search'})
    print(f'Deleted circuit breaker: {result.deleted_count}')

# Reset google_cse circuit breaker
breaker2 = db['circuit_breakers'].find_one({'name': 'google_cse'})
print(f'Google CSE circuit breaker: {breaker2}')

if breaker2:
    result = db['circuit_breakers'].delete_one({'name': 'google_cse'})
    print(f'Deleted Google CSE breaker: {result.deleted_count}')

# Reset openai_web circuit breaker
breaker3 = db['circuit_breakers'].find_one({'name': 'openai_web'})
print(f'OpenAI web circuit breaker: {breaker3}')

if breaker3:
    result = db['circuit_breakers'].delete_one({'name': 'openai_web'})
    print(f'Deleted OpenAI web breaker: {result.deleted_count}')

# Also check email_automation database
db2 = client['email_automation']
print(f"\nChecking email_automation.circuit_breakers:")
for breaker in db2['circuit_breakers'].find():
    print(f"  - {breaker}")
    
# Delete all circuit breakers in email_automation
result = db2['circuit_breakers'].delete_many({})
print(f"Deleted {result.deleted_count} circuit breakers from email_automation")

print("\nCircuit breakers reset complete!")
