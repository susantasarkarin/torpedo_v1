#!/usr/bin/env python3
"""Start new OpenAI web search job with user's criteria"""
import requests
import json

API_BASE = "https://torpedo.cogentixresearch.com"

# Search criteria from user's screenshot
search_params = {
    "designation": "Director Consumer Insights, VP Market Research, Head of Insights",
    "countries": [
        "United States", "United Kingdom", "Canada", "Australia", 
        "Germany", "France", "India", "Singapore"
    ],
    "seniorities": ["Manager"]
}

print("=== STARTING NEW OPENAI WEB SEARCH ===")
print(f"Designation: {search_params['designation']}")
print(f"Countries: {', '.join(search_params['countries'])}")
print(f"Seniorities: {', '.join(search_params['seniorities'])}")
print()

# Start the search job
try:
    response = requests.post(
        f"{API_BASE}/leads/import/web-search",
        json=search_params,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(f"Response: {json.dumps(data, indent=2)}")
    
    if data.get("success") and data.get("job_id"):
        print(f"\n✅ Search started! Job ID: {data['job_id']}")
        print("Monitor progress in the frontend or check logs.")
    else:
        print(f"\n⚠️ Search may not have started: {data}")
        
except Exception as e:
    print(f"❌ Error: {e}")
