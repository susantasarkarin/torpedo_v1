"""
Monitor OpenAI API Usage
========================
Run this to see your current API usage and costs
"""

import os
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client['email_automation']
logs = db['ai_usage_logs']

def get_usage_last_24h():
    """Get API usage for last 24 hours"""
    since = datetime.utcnow() - timedelta(hours=24)
    
    pipeline = [
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {
            "_id": {
                "source": "$source",
                "provider": "$provider",
                "model": "$model"
            },
            "total_calls": {"$sum": 1},
            "total_tokens": {"$sum": "$total_tokens"},
            "total_cost": {"$sum": "$cost_usd"},
            "avg_latency": {"$avg": "$latency_ms"}
        }},
        {"$sort": {"total_calls": -1}}
    ]
    
    results = list(logs.aggregate(pipeline))
    
    print("\n" + "="*70)
    print("API USAGE - LAST 24 HOURS")
    print("="*70)
    
    total_calls = 0
    total_cost = 0
    
    for r in results:
        source = r["_id"]["source"]
        provider = r["_id"]["provider"]
        model = r["_id"]["model"]
        calls = r["total_calls"]
        tokens = r["total_tokens"]
        cost = r["total_cost"]
        latency = r["avg_latency"]
        
        total_calls += calls
        total_cost += cost
        
        print(f"\n{source} ({provider}/{model}):")
        print(f"  Calls:    {calls:,}")
        print(f"  Tokens:   {tokens:,}")
        print(f"  Cost:     ${cost:.4f}")
        print(f"  Latency:  {latency:.0f}ms")
    
    print("\n" + "-"*70)
    print(f"TOTAL CALLS:  {total_calls:,}")
    print(f"TOTAL COST:   ${total_cost:.4f}")
    print(f"EST. MONTHLY: ${total_cost * 30:.2f}")
    print("="*70 + "\n")
    
    # Check for rate limit issues
    print("\nRATE LIMIT CHECK:")
    
    # Get calls per minute in last hour
    last_hour = datetime.utcnow() - timedelta(hours=1)
    hourly_logs = list(logs.find({"timestamp": {"$gte": last_hour}}).sort("timestamp", 1))
    
    if hourly_logs:
        # Count max calls in any 1-minute window
        max_rpm = 0
        for i in range(len(hourly_logs)):
            minute_start = hourly_logs[i]["timestamp"]
            minute_end = minute_start + timedelta(minutes=1)
            calls_in_minute = sum(1 for log in hourly_logs if minute_start <= log["timestamp"] < minute_end)
            max_rpm = max(max_rpm, calls_in_minute)
        
        print(f"  Max RPM in last hour: {max_rpm}")
        if max_rpm > 50:
            print(f"  ⚠️  WARNING: High burst detected! OpenAI limit is ~500 RPM")
        else:
            print(f"  ✅ Rate limit safe (recommended: <30 RPM)")
    
    print()

if __name__ == "__main__":
    get_usage_last_24h()
