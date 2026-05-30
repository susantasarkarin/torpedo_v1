    """
GOOGLE CSE RATE LIMITER
=======================
Proactive rate limiting for Google Custom Search API to stay within free tier.

Free Tier: 100 queries/day
Rate Limits:
    - Daily: 100 queries (default, configurable)
    - Hourly: 50 queries (prevent burst usage)

MongoDB Collection: google_cse_usage
"""

import os
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_db = _client['email_automation']

# Collection for tracking usage
usage_collection = _db['google_cse_usage']

# Settings collection
_settings_db = _client['torpedo_settings']
_app_settings = _settings_db['app_settings']

# Create indexes
try:
    usage_collection.create_index("date", unique=True)
    usage_collection.create_index("created_at")
except Exception as e:
    print(f"Warning: Could not create google_cse_usage indexes: {e}")


def get_rate_limit_settings() -> Dict[str, Any]:
    """Get rate limit settings from database with defaults"""
    try:
        cfg = _app_settings.find_one({"_id": "app_config"})
        if cfg:
            return {
                "daily_limit": cfg.get("google_cse_daily_limit", 100),
                "hourly_limit": cfg.get("google_cse_hourly_limit", 50),
                "rate_limit_enabled": cfg.get("google_cse_rate_limit_enabled", True),
            }
    except Exception:
        pass
    
    # Defaults from env or hardcoded
    return {
        "daily_limit": int(os.getenv("GOOGLE_CSE_DAILY_LIMIT", "100")),
        "hourly_limit": int(os.getenv("GOOGLE_CSE_HOURLY_LIMIT", "50")),
        "rate_limit_enabled": os.getenv("GOOGLE_CSE_RATE_LIMIT_ENABLED", "true").lower() == "true",
    }


def get_today_key() -> str:
    """Get the date key for today (UTC)"""
    return datetime.utcnow().strftime("%Y-%m-%d")


def get_current_hour() -> int:
    """Get the current hour (0-23) in UTC"""
    return datetime.utcnow().hour


def get_usage_stats() -> Dict[str, Any]:
    """
    Get current usage statistics.
    
    Returns:
        Dict with today_queries, daily_limit, remaining, hourly_queries, hourly_limit
    """
    settings = get_rate_limit_settings()
    today = get_today_key()
    current_hour = get_current_hour()
    
    # Get or create today's record
    record = usage_collection.find_one({"date": today})
    
    if not record:
        record = {
            "date": today,
            "total_queries": 0,
            "hourly_queries": {str(h): 0 for h in range(24)},
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
    
    today_queries = record.get("total_queries", 0)
    hourly_queries = record.get("hourly_queries", {}).get(str(current_hour), 0)
    
    return {
        "today_queries": today_queries,
        "daily_limit": settings["daily_limit"],
        "daily_remaining": max(0, settings["daily_limit"] - today_queries),
        "hourly_queries": hourly_queries,
        "hourly_limit": settings["hourly_limit"],
        "hourly_remaining": max(0, settings["hourly_limit"] - hourly_queries),
        "rate_limit_enabled": settings["rate_limit_enabled"],
        "current_hour": current_hour,
        "date": today
    }


def can_make_query() -> Tuple[bool, str]:
    """
    Check if we can make a Google CSE query within rate limits.
    
    Returns:
        Tuple of (allowed: bool, message: str)
    """
    settings = get_rate_limit_settings()
    
    # Rate limiting disabled
    if not settings["rate_limit_enabled"]:
        return True, "Rate limiting disabled"
    
    stats = get_usage_stats()
    
    # Check daily limit
    if stats["today_queries"] >= settings["daily_limit"]:
        return False, f"Daily quota exceeded ({stats['today_queries']}/{settings['daily_limit']}). Resets at midnight UTC."
    
    # Check hourly limit
    if stats["hourly_queries"] >= settings["hourly_limit"]:
        return False, f"Hourly quota exceeded ({stats['hourly_queries']}/{settings['hourly_limit']}). Resets in {60 - datetime.utcnow().minute} minutes."
    
    return True, "OK"


def record_query(queries: int = 1) -> Dict[str, Any]:
    """
    Record that we made Google CSE query/queries.
    
    Args:
        queries: Number of queries to record (default 1)
    
    Returns:
        Updated usage stats
    """
    today = get_today_key()
    current_hour = str(get_current_hour())
    
    # Upsert today's record
    result = usage_collection.find_one_and_update(
        {"date": today},
        {
            "$inc": {
                "total_queries": queries,
                f"hourly_queries.{current_hour}": queries
            },
            "$set": {"updated_at": datetime.utcnow()},
            "$setOnInsert": {
                "created_at": datetime.utcnow(),
                "date": today
            }
        },
        upsert=True,
        return_document=True
    )
    
    # Ensure hourly_queries structure exists
    if result and "hourly_queries" not in result:
        usage_collection.update_one(
            {"date": today},
            {"$set": {"hourly_queries": {str(h): 0 for h in range(24)}}}
        )
    
    return get_usage_stats()


def reset_daily_counter() -> Dict[str, Any]:
    """
    Manually reset today's counter (for testing/admin purposes).
    
    Returns:
        Reset stats
    """
    today = get_today_key()
    
    usage_collection.update_one(
        {"date": today},
        {
            "$set": {
                "total_queries": 0,
                "hourly_queries": {str(h): 0 for h in range(24)},
                "updated_at": datetime.utcnow(),
                "reset_at": datetime.utcnow()
            }
        },
        upsert=True
    )
    
    return get_usage_stats()


def get_historical_usage(days: int = 7) -> list:
    """
    Get usage history for the past N days.
    
    Args:
        days: Number of days to look back
    
    Returns:
        List of daily usage records
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    records = list(usage_collection.find(
        {"created_at": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("date", -1))
    
    return records


def estimate_monthly_cost() -> Dict[str, Any]:
    """
    Estimate monthly Google CSE cost based on recent usage.
    
    Google CSE pricing:
    - First 100 queries/day: FREE
    - Beyond free tier: $5 per 1000 queries
    
    Returns:
        Dict with estimated costs and projections
    """
    # Get last 7 days of usage
    history = get_historical_usage(7)
    
    if not history:
        return {
            "avg_daily_queries": 0,
            "projected_monthly_queries": 0,
            "free_queries_monthly": 3000,  # 100/day * 30 days
            "billable_queries": 0,
            "estimated_cost_usd": 0.0
        }
    
    # Calculate average
    total_queries = sum(r.get("total_queries", 0) for r in history)
    avg_daily = total_queries / len(history)
    
    # Project monthly
    projected_monthly = avg_daily * 30
    free_monthly = 100 * 30  # 100 free queries per day
    billable = max(0, projected_monthly - free_monthly)
    
    # Cost: $5 per 1000 queries beyond free tier
    cost = (billable / 1000) * 5
    
    return {
        "avg_daily_queries": round(avg_daily, 1),
        "projected_monthly_queries": round(projected_monthly),
        "free_queries_monthly": free_monthly,
        "billable_queries": round(billable),
        "estimated_cost_usd": round(cost, 2)
    }
