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
            daily_budget_usd = float(cfg.get("google_cse_daily_budget_usd",
                                             os.getenv("GOOGLE_CSE_DAILY_BUDGET_USD", "0")))
            return {
                "daily_budget_usd": daily_budget_usd,
                "daily_paid_query_limit": _derive_monthly_paid_query_limit(
                    daily_budget_usd, cost_per_1000_queries),
                "company_hourly_limit": int(cfg.get("google_cse_company_hourly_limit", 200)),
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
    daily_budget_usd = float(os.getenv("GOOGLE_CSE_DAILY_BUDGET_USD", "0"))
    return {
        "daily_budget_usd": daily_budget_usd,
        "daily_paid_query_limit": _derive_monthly_paid_query_limit(daily_budget_usd, cost_per_1000_queries),
        "company_hourly_limit": int(os.getenv("GOOGLE_CSE_COMPANY_HOURLY_LIMIT", "200")),
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


def reserve_query_slot(purpose: str = "") -> Tuple[bool, str]:
    """
    Atomically reserve one Google CSE query slot for the current day+hour, or
    refuse if a cap is already reached. A single atomic $inc, refunded if it
    turns out to have gone over, is race-free (check-then-act let concurrent
    lead-search workers fire 5 queries in 1.6 s against the cap, 2026-09-26).
    Callers reserve before EVERY HTTP request.

    Caps:
      hourly    burst protection. Lead-gen's pacing (hourly_limit, 12 -- what
                extraction can process) does not apply to company lookups
                (purpose="company"), which have their own hourly counter
                (company_hourly_limit) so neither starves the other.
      free      the first daily_limit (100) queries of the Google day.
      paid      beyond that, each query is billable ($5 / 1000). Owner
                2026-10-21: "cap google budget at $5 per day" -> at most
                daily_paid_query_limit (daily_budget_usd / cost * 1000 = 1000)
                billable queries per day; a monthly budget, when set, caps
                the month as well. Neither set = free tier only.
    """
    settings = get_rate_limit_settings()
    if not settings["rate_limit_enabled"]:
        return True, "Rate limiting disabled"

    today = get_today_key()
    current_hour = str(get_current_hour())
    company = purpose == "company"
    hour_field = f"company_hourly_queries.{current_hour}" if company else f"hourly_queries.{current_hour}"

    doc = usage_collection.find_one_and_update(
        {"date": today},
        {
            "$inc": {"total_queries": 1, hour_field: 1},
            "$set": {"updated_at": datetime.utcnow()},
            "$setOnInsert": {"created_at": datetime.utcnow(), "date": today},
        },
        upsert=True,
        return_document=True,
    )

    total = doc.get("total_queries", 0)
    hourly_map = doc.get("company_hourly_queries" if company else "hourly_queries") or {}
    hourly = hourly_map.get(current_hour, 0)
    hourly_limit = settings.get("company_hourly_limit", 200) if company else settings["hourly_limit"]
    is_billable = total > settings["daily_limit"]

    def _refund_daily():
        usage_collection.update_one({"date": today}, {"$inc": {"total_queries": -1, hour_field: -1}})

    if hourly > hourly_limit:
        _refund_daily()
        return False, f"Hourly quota exceeded ({hourly_limit}/hour). Resets within the hour."

    if not is_billable:
        return True, "OK"

    daily_paid_limit = settings.get("daily_paid_query_limit", 0)
    monthly_limit = settings.get("monthly_paid_query_limit", 0)
    if daily_paid_limit <= 0 and monthly_limit <= 0:
        # Free tier only. The wording must not say "monthly": the caller
        # pauses until the named limit resets, which is Google's daily reset.
        _refund_daily()
        return False, (f"Daily free quota reached ({settings['daily_limit']}/day). "
                       "Resets at midnight US Pacific.")

    # Past the free tier -- a billable query, within the day's paid budget...
    paid_doc = usage_collection.find_one_and_update(
        {"date": today}, {"$inc": {"billable_queries": 1}}, return_document=True)
    billable_today = (paid_doc or {}).get("billable_queries", 0)

    def _refund_paid_day():
        usage_collection.update_one({"date": today}, {"$inc": {"billable_queries": -1}})

    if daily_paid_limit > 0 and billable_today > daily_paid_limit:
        _refund_paid_day()
        _refund_daily()
        return False, (f"Daily CSE budget reached (${settings.get('daily_budget_usd', 0):.2f} = "
                       f"{daily_paid_limit} paid queries). Resets at midnight US Pacific.")

    # ...and the month's, when one is set.
    if monthly_limit > 0:
        month = get_month_key()
        monthly_doc = monthly_usage_collection.find_one_and_update(
            {"month": month},
            {"$inc": {"billable_queries": 1}, "$set": {"updated_at": datetime.utcnow()},
             "$setOnInsert": {"created_at": datetime.utcnow(), "month": month}},
            upsert=True, return_document=True)
        if monthly_doc.get("billable_queries", 0) > monthly_limit:
            monthly_usage_collection.update_one({"month": month}, {"$inc": {"billable_queries": -1}})
            _refund_paid_day()
            _refund_daily()
            return False, (
                f"Monthly CSE budget exceeded (${settings['monthly_budget_usd']:.2f} "
                f"/ {monthly_limit} paid queries used this month). Resets next month.")
    else:
        # no monthly cap; the month's spend is still counted for reporting
        monthly_usage_collection.find_one_and_update(
            {"month": get_month_key()},
            {"$inc": {"billable_queries": 1}, "$set": {"updated_at": datetime.utcnow()},
             "$setOnInsert": {"created_at": datetime.utcnow()}}, upsert=True)

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


def queries_left_today(purpose: str = "") -> int:
    """How many more queries today's free tier + daily paid budget allow
    (ignores the hourly caps; reserve_query_slot still enforces everything)."""
    settings = get_rate_limit_settings()
    if not settings["rate_limit_enabled"]:
        return 10_000
    doc = usage_collection.find_one({"date": get_today_key()}) or {}
    free_left = max(0, settings["daily_limit"] - doc.get("total_queries", 0) + doc.get("billable_queries", 0))
    paid_left = max(0, settings.get("daily_paid_query_limit", 0) - doc.get("billable_queries", 0))
    return free_left + paid_left
