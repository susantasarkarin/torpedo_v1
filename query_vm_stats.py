"""Query VM/Production API for lead stats"""
import requests
import json

BASE_URL = "https://torpedo.cogentixresearch.com"

print("=" * 70)
print("QUERYING PRODUCTION VM FOR LEAD STATS")
print("=" * 70)

# Try health check first
try:
    print("\n1. Testing API connectivity...")
    r = requests.get(f"{BASE_URL}/api/health", timeout=10)
    print(f"   Health: {r.status_code} - {r.text[:100] if r.text else 'OK'}")
except Exception as e:
    print(f"   Error: {e}")

# Try lead discovery stats
endpoints = [
    "/api/leads/discovery/stats",
    "/api/leads/stats",
    "/api/vendor-leads/stats",
    "/api/dashboard/stats",
    "/api/sales/dashboard/stats",
]

print("\n2. Checking lead endpoints...")
for endpoint in endpoints:
    try:
        r = requests.get(f"{BASE_URL}{endpoint}", timeout=10)
        print(f"   {endpoint}: {r.status_code}")
        if r.status_code == 200:
            try:
                data = r.json()
                print(f"      Data: {json.dumps(data, indent=6)[:500]}")
            except:
                print(f"      Response: {r.text[:200]}")
    except Exception as e:
        print(f"   {endpoint}: Error - {str(e)[:50]}")

# Try to get AI usage stats
print("\n3. Checking AI/OpenAI endpoints...")
ai_endpoints = [
    "/api/ai/usage",
    "/api/settings/ai-status",
    "/api/leads/ai-stats",
]

for endpoint in ai_endpoints:
    try:
        r = requests.get(f"{BASE_URL}{endpoint}", timeout=10)
        print(f"   {endpoint}: {r.status_code}")
        if r.status_code == 200:
            try:
                data = r.json()
                print(f"      {json.dumps(data, indent=6)[:300]}")
            except:
                print(f"      {r.text[:200]}")
    except Exception as e:
        print(f"   {endpoint}: Error - {str(e)[:50]}")

print("\n" + "=" * 70)
