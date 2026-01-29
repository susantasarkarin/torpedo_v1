#!/usr/bin/env python3
"""
Daily OpenAI Cost Report
========================
Shows today's OpenAI/AI spending breakdown by source, model, and provider.
Run daily to monitor costs and prevent budget overruns.

Usage:
    python daily_cost_report.py              # Show today's costs
    python daily_cost_report.py --yesterday  # Show yesterday's costs
    python daily_cost_report.py --week       # Show last 7 days
"""
import os
import sys
from pymongo import MongoClient
from datetime import datetime, timedelta, time
from dotenv import load_dotenv

load_dotenv()


def get_cost_report(hours: int = None, start_date: datetime = None):
    """
    Get cost report for specified time period.
    
    Args:
        hours: Number of hours to look back (if specified)
        start_date: Start date for report (if specified, overrides hours)
    """
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    
    try:
        client.admin.command('ping')
    except Exception as e:
        print(f"❌ Cannot connect to MongoDB: {e}")
        print(f"   URI: {mongo_uri}")
        return
    
    logs = client['email_automation']['ai_usage_logs']
    
    # Determine time range
    if start_date:
        since = start_date
        period_name = start_date.strftime('%Y-%m-%d')
    elif hours:
        since = datetime.utcnow() - timedelta(hours=hours)
        period_name = f"Last {hours} hours"
    else:
        # Default: Today
        since = datetime.combine(datetime.today(), time.min)
        period_name = f"Today ({datetime.today().strftime('%Y-%m-%d')})"
    
    # Aggregate costs by source, model, provider
    pipeline = [
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {
            "_id": {
                "source": "$source",
                "model": "$model",
                "provider": "$provider"
            },
            "calls": {"$sum": 1},
            "cost": {"$sum": "$cost_usd"},
            "input_tokens": {"$sum": "$input_tokens"},
            "output_tokens": {"$sum": "$output_tokens"},
            "total_tokens": {"$sum": "$total_tokens"},
            "avg_latency": {"$avg": "$latency_ms"},
            "failures": {
                "$sum": {
                    "$cond": [{"$eq": ["$success", False]}, 1, 0]
                }
            }
        }},
        {"$sort": {"cost": -1}}
    ]
    
    results = list(logs.aggregate(pipeline))
    
    if not results:
        print(f"\n📊 No API usage found for {period_name}")
        return
    
    # Print report header
    print("\n" + "="*80)
    print(f"OpenAI/AI COST REPORT - {period_name}".center(80))
    print("="*80)
    
    total_cost = 0
    total_calls = 0
    total_tokens = 0
    total_failures = 0
    
    # Print breakdown
    for r in results:
        source = r["_id"].get("source", "unknown")
        model = r["_id"].get("model", "unknown")
        provider = r["_id"].get("provider", "unknown")
        calls = r["calls"]
        cost = r["cost"]
        tokens = r["total_tokens"]
        input_tok = r["input_tokens"]
        output_tok = r["output_tokens"]
        failures = r["failures"]
        latency = r["avg_latency"]
        
        total_cost += cost
        total_calls += calls
        total_tokens += tokens
        total_failures += failures
        
        success_rate = ((calls - failures) / calls * 100) if calls > 0 else 0
        
        print(f"\n📌 {source.upper()} / {provider} / {model}")
        print(f"   Calls:        {calls:,} ({failures} failed, {success_rate:.1f}% success)")
        print(f"   Cost:         ${cost:.4f}")
        print(f"   Tokens:       {tokens:,} ({input_tok:,} in, {output_tok:,} out)")
        print(f"   Avg Latency:  {latency:.0f}ms")
        print(f"   Cost/Call:    ${cost/calls:.6f}")
    
    # Print totals
    print("\n" + "-"*80)
    print(f"TOTAL CALLS:     {total_calls:,}")
    print(f"TOTAL COST:      ${total_cost:.4f}")
    print(f"TOTAL TOKENS:    {total_tokens:,}")
    print(f"TOTAL FAILURES:  {total_failures}")
    
    # Extrapolate to monthly
    if hours and hours <= 24:
        monthly_est = total_cost * (30 * 24 / hours)
        print(f"MONTHLY EST.:    ${monthly_est:.2f}")
    elif not hours:  # Today
        current_hour = datetime.now().hour + 1
        if current_hour > 0:
            daily_est = total_cost * (24 / current_hour)
            monthly_est = daily_est * 30
            print(f"DAILY EST.:      ${daily_est:.2f}")
            print(f"MONTHLY EST.:    ${monthly_est:.2f}")
    
    # Budget check
    budget = float(os.getenv("DAILY_AI_BUDGET_USD", "10.0"))
    
    print("\n" + "-"*80)
    print(f"DAILY BUDGET:    ${budget:.2f}")
    
    if not hours or hours == 24:
        # Only show budget comparison for daily reports
        remaining = budget - total_cost
        percent = (total_cost / budget * 100) if budget > 0 else 0
        
        print(f"USED TODAY:      ${total_cost:.2f} ({percent:.0f}%)")
        
        if remaining > 0:
            print(f"REMAINING:       ${remaining:.2f} ✅")
        else:
            print(f"OVER BUDGET:     ${-remaining:.2f} 🚨")
    
    print("="*80 + "\n")
    
    # Alerts
    if not hours or hours == 24:
        if total_cost > budget:
            print("🚨 WARNING: Daily budget exceeded!")
            print("🚨 Consider setting DISABLE_AI_CALLS=true in .env")
            print("🚨 Or switch to DeepSeek: AI_DEFAULT_PROVIDER=deepseek")
        elif total_cost > budget * 0.8:
            print("⚠️  WARNING: 80% of daily budget used")
            print("⚠️  Monitor closely to avoid overrun")
    
    # Provider breakdown
    print("\n📊 Cost by Provider:")
    provider_costs = {}
    for r in results:
        provider = r["_id"].get("provider", "unknown")
        provider_costs[provider] = provider_costs.get(provider, 0) + r["cost"]
    
    for provider, cost in sorted(provider_costs.items(), key=lambda x: x[1], reverse=True):
        percent = (cost / total_cost * 100) if total_cost > 0 else 0
        print(f"   {provider:12s}: ${cost:8.4f} ({percent:5.1f}%)")
    
    # Model breakdown
    print("\n📊 Cost by Model:")
    model_costs = {}
    for r in results:
        model = r["_id"].get("model", "unknown")
        model_costs[model] = model_costs.get(model, 0) + r["cost"]
    
    for model, cost in sorted(model_costs.items(), key=lambda x: x[1], reverse=True):
        percent = (cost / total_cost * 100) if total_cost > 0 else 0
        print(f"   {model:20s}: ${cost:8.4f} ({percent:5.1f}%)")
    
    print()


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        
        if arg in ['--yesterday', '-y']:
            # Yesterday's costs
            yesterday = datetime.combine(
                datetime.today() - timedelta(days=1),
                time.min
            )
            get_cost_report(start_date=yesterday)
        
        elif arg in ['--week', '-w']:
            # Last 7 days
            get_cost_report(hours=24*7)
        
        elif arg in ['--month', '-m']:
            # Last 30 days
            get_cost_report(hours=24*30)
        
        elif arg in ['--hour', '-h']:
            # Last hour
            get_cost_report(hours=1)
        
        elif arg in ['--help', '-?']:
            print(__doc__)
        
        else:
            print(f"Unknown option: {arg}")
            print("Use --help for usage")
    else:
        # Default: Today
        get_cost_report()


if __name__ == "__main__":
    main()
