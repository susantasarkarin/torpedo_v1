"""Query VM API for OpenAI lead generation stats - trying all possible endpoints"""
import requests
import json

BASE_URL = "https://torpedo.cogentixresearch.com"

print("=" * 70)
print("QUERYING PRODUCTION VM - COMPREHENSIVE ENDPOINT CHECK")
print("=" * 70)

# Check direct routes (without /api prefix based on nginx config)
endpoints = [
    # Direct routes
    "/leads/stats",
    "/leads/discovery/stats",
    "/leads/search-jobs",
    "/leads/web-search/stats",
    
    # API prefixed routes
    "/api/leads/search-jobs",
    "/api/web-search-jobs",
    
    # Sales dashboard
    "/sales/dashboard",
    "/sales/leads/stats",
    
    # Vendor leads
    "/vendor-leads/stats",
    
    # Gmail/Email based leads
    "/gmail/leads/stats",
    "/classification/stats",
    
    # Agent routes
    "/agents/status",
    "/agents/jobs",
    
    # Settings that might have stats
    "/settings/ai-usage",
    "/settings/openai",
]

print("\nChecking all lead-related endpoints...")
for endpoint in endpoints:
    try:
        r = requests.get(f"{BASE_URL}{endpoint}", timeout=10, allow_redirects=True)
        status = r.status_code
        if status == 200:
            print(f"✅ {endpoint}: {status}")
            try:
                data = r.json()
                print(f"   {json.dumps(data, indent=3)[:400]}")
            except:
                if len(r.text) < 500:
                    print(f"   Response: {r.text[:300]}")
        elif status == 401:
            print(f"🔐 {endpoint}: {status} (Auth required)")
        elif status == 403:
            print(f"🚫 {endpoint}: {status} (Forbidden)")
        elif status != 404:
            print(f"⚠️  {endpoint}: {status}")
    except requests.exceptions.Timeout:
        print(f"⏱️  {endpoint}: Timeout")
    except Exception as e:
        print(f"❌ {endpoint}: {str(e)[:40]}")

# Check if we can access MongoDB directly from .env file
print("\n" + "=" * 70)
print("NOTE: To get accurate VM stats, you need to either:")
print("1. SSH into the VM and run a script there")
print("2. Connect to the VM's MongoDB directly")
print("3. Add a stats API endpoint to the production server")
print("=" * 70)
