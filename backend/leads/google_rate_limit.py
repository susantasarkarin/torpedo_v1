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


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
_client = _get_pooled_client()
_db = _client['email_automation']

# Collection for tracking usage
usage_collection = _db['google_cse_usage']

# Collection for tracking month-to-date BILLABLE query usage (queries beyond
# the free daily_limit), so real spend can be capped independent of any
# single day's traffic -- 2026-09-27 ask: max $10/month, i.e. the free
# 100/day plus up to 2000 additional paid queries/month.
monthly_usage_collection = _db['google_cse_monthly_usage']

# Settings collection
_settings_db = _client['torpedo_settings']
_app_settings = _settings_db['app_settings']

# Create indexes
try:
    usage_collection.create_index("date", unique=True)
    usage_collection.create_index("created_at")
except Exception as e:
    print(f"Warning: Could not create google_cse_usage indexes: {e}")

try:
    monthly_usage_collection.create_index("month", unique=True)
except Exception as e:
    print(f"Warning: Could not create google_cse_monthly_usage indexes: {e}")


def _derive_monthly_paid_query_limit(monthly_budget_usd: float, cost_per_1000_queries: float) -> int:
    """How many billable queries fit in the monthly budget, e.g. $10 / $5 per
    1000 = 2000. Zero cost-per-1000 means cost tracking is misconfigured, so
    treat it as no paid headroom rather than dividing by zero."""
    if cost_per_1000_queries <= 0:
        return 0
    return int((monthly_budget_usd / cost_per_1000_queries) * 1000)


def get_rate_limit_settings() -> Dict[str, Any]:
    """Get rate limit settings from database with defaults"""
    try:
        cfg = _app_settings.find_one({"_id": "app_config"})
        if cfg:
            # Free tier only by default (owner, 2026-09-28): 0 paid queries.
            monthly_budget_usd = cfg.get("google_cse_monthly_budget_usd", 0.0)
            cost_per_1000_queries = cfg.get("google_cse_cost_per_1000_queries", 5.0)
            return {
                "daily_limit": cfg.get("google_cse_daily_limit", 100),
                "hourly_limit": cfg.get("google_cse_hourly_limit", 50),
                "rate_limit_enabled": cfg.get("google_cse_rate_limit_enabled", True),
                "monthly_budget_usd": monthly_budget_usd,
                "cost_per_1000_queries": cost_per_1000_queries,
                "monthly_paid_query_limit": _derive_monthly_paid_query_limit(
                    monthly_budget_usd, cost_per_1000_queries),
            }
    except Exception:
        pass

    # Defaults from env or hardcoded
    monthly_budget_usd = float(os.getenv("GOOGLE_CSE_MONTHLY_BUDGET_USD", "0"))
    cost_per_1000_queries = float(os.getenv("GOOGLE_CSE_COST_PER_1000_QUERIES", "5.0"))
    return {
        "daily_limit": int(os.getenv("GOOGLE_CSE_DAILY_LIMIT", "100")),
        "hourly_limit": int(os.getenv("GOOGLE_CSE_HOURLY_LIMIT", "50")),
        "rate_limit_enabled": os.getenv("GOOGLE_CSE_RATE_LIMIT_ENABLED", "true").lower() == "true",
        "monthly_budget_usd": monthly_budget_usd,
        "cost_per_1000_queries": cost_per_1000_queries,
        "monthly_paid_query_limit": _derive_monthly_paid_query_limit(
            monthly_budget_usd, cost_per_1000_queries),
    }


def get_today_key() -> str:
    """The quota day as Google counts it: midnight to midnight US Pacific.

    It used to be the UTC date, which rolls over 7-8 hours before Google's
    reset -- every UTC morning we believed 100 fresh queries were available
    while Google still counted the previous day, and the searches 429'd."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone
        return datetime.now(timezone.utc).astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d")


def get_current_hour() -> int:
    """Get the current hour (0-23) in UTC"""
    return datetime.utcnow().hour


def get_month_key() -> str:
    """Get the month key for the current UTC month, e.g. '2026-09'."""
    return datetime.utcnow().strftime("%Y-%m")


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

    month = get_month_key()
    monthly_record = monthly_usage_collection.find_one({"month": month}) or {}
    monthly_billable_queries = monthly_record.get("billable_queries", 0)

    return {
        "today_queries": today_queries,
        "daily_limit": settings["daily_limit"],
        "daily_remaining": max(0, settings["daily_limit"] - today_queries),
        "hourly_queries": hourly_queries,
        "hourly_limit": settings["hourly_limit"],
        "hourly_remaining": max(0, settings["hourly_limit"] - hourly_queries),
        "rate_limit_enabled": settings["rate_limit_enabled"],
        "current_hour": current_hour,
        "date": today,
        "month": month,
        "monthly_billable_queries": monthly_billable_queries,
        "monthly_paid_query_limit": settings["monthly_paid_query_limit"],
        "monthly_budget_usd": settings["monthly_budget_usd"],
        "monthly_remaining_paid_queries": max(
            0, settings["monthly_paid_query_limit"] - monthly_billable_queries),
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


def reserve_query_slot() -> Tuple[bool, str]:
    """
    Atomically reserve one Google CSE query slot for the current day+hour, or
    refuse if the daily or hourly cap is already reached.

    can_make_query()-then-record_query() (above) is check-then-act: two
    concurrent callers can both read a count below the limit and both proceed,
    overshooting it -- exactly the bug already found and fixed for outreach
    sends (routers/cold_outreach_router.py's _reserve_daily_send_slot: "the
    previous implementation counted sends and then sent... concurrent workers
    each saw a count below the limit and all sent, overshooting the cap").
    Found live 2026-09-26: multiple concurrent lead-search workers (leads/
    router.py's WebSearch jobs, each tracking its OWN per-job leads_today
    counter rather than this shared one) fired 5 queries within 1.6 seconds
    against the real 100/day cap. A single atomic $inc, refunded if it turns
    out to have gone over, is race-free the same way.

    Callers must reserve a slot before EVERY actual HTTP request, not once per
    logical search (a paginated search issues one request per page/quota unit).

    Beyond daily_limit (the free tier), a query is billable. Billable queries
    draw from a separate month-to-date counter capped at
    monthly_paid_query_limit (monthly_budget_usd / cost_per_1000_queries),
    so total spend can never exceed the configured monthly budget no matter
    how usage is spread across days -- the 2026-09-27 ask was "$10/month
    max, so 100 free + up to 2000 paid". daily_limit itself is no longer a
    hard stop; hourly_limit still is, as pure burst protection.
    """
    settings = get_rate_limit_settings()
    if not settings["rate_limit_enabled"]:
        return True, "Rate limiting disabled"

    today = get_today_key()
    current_hour = str(get_current_hour())

    doc = usage_collection.find_one_and_update(
        {"date": today},
        {
            "$inc": {"total_queries": 1, f"hourly_queries.{current_hour}": 1},
            "$set": {"updated_at": datetime.utcnow()},
            "$setOnInsert": {"created_at": datetime.utcnow(), "date": today},
        },
        upsert=True,
        return_document=True,
    )

    total = doc.get("total_queries", 0)
    hourly = (doc.get("hourly_queries") or {}).get(current_hour, 0)
    over_hourly = hourly > settings["hourly_limit"]
    is_billable = total > settings["daily_limit"]

    def _refund_daily():
        usage_collection.update_one(
            {"date": today},
            {"$inc": {"total_queries": -1, f"hourly_queries.{current_hour}": -1}},
        )

    if over_hourly:
        _refund_daily()
        return False, f"Hourly quota exceeded ({settings['hourly_limit']}/hour). Resets within the hour."

    if not is_billable:
        return True, "OK"

    if settings.get("monthly_paid_query_limit", 0) <= 0:
        # Free tier only (owner, 2026-09-28): no paid queries at all. The
        # wording must not say "monthly" -- the caller pauses until the limit
        # named in the reason resets, and this one resets at Google's daily
        # reset, not next month.
        _refund_daily()
        return False, (f"Daily free quota reached ({settings['daily_limit']}/day). "
                       "Resets at midnight US Pacific.")

    # Past the free daily tier -- this query only proceeds if the monthly
    # paid budget has room for it.
    month = get_month_key()
    monthly_doc = monthly_usage_collection.find_one_and_update(
        {"month": month},
        {
            "$inc": {"billable_queries": 1},
            "$set": {"updated_at": datetime.utcnow()},
            "$setOnInsert": {"created_at": datetime.utcnow(), "month": month},
        },
        upsert=True,
        return_document=True,
    )
    billable = monthly_doc.get("billable_queries", 0)
    monthly_limit = settings.get("monthly_paid_query_limit", 0)

    if billable > monthly_limit:
        # Over the monthly budget -- refund both reservations so a refused
        # query never counts against either the day or the month.
        monthly_usage_collection.update_one(
            {"month": month}, {"$inc": {"billable_queries": -1}}
        )
        _refund_daily()
        return False, (
            f"Monthly CSE budget exceeded (${settings['monthly_budget_usd']:.2f} "
            f"/ {monthly_limit} paid queries used this month). Resets next month."
        )

    return True, "OK"


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
