"""
Unified Rate Limiter Service for Email Campaigns.
DB-backed rate limiting that persists across restarts.

Consolidates rate limiting logic from gmail.py for use across all email sending.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""
    daily_limit: int = 500
    hourly_limit: int = 50
    per_minute_limit: int = 10
    cooldown_seconds: int = 5


@dataclass
class RateLimitStatus:
    """Result of rate limit check."""
    allowed: bool
    reason: Optional[str] = None
    wait_seconds: int = 0
    current_usage: Dict[str, int] = None
    limits: Dict[str, int] = None


class RateLimitService:
    """
    DB-backed rate limiting service for email sending.
    Tracks sends per account and enforces limits.
    """
    
    COLLECTION_NAME = "rate_limits"
    CONFIG_COLLECTION = "rate_limit_settings"
    
    # Default limits
    DEFAULT_LIMITS = RateLimitConfig(
        daily_limit=int(os.getenv("EMAIL_DAILY_LIMIT", "500")),
        hourly_limit=int(os.getenv("EMAIL_HOURLY_LIMIT", "50")),
        per_minute_limit=int(os.getenv("EMAIL_MINUTE_LIMIT", "10")),
        cooldown_seconds=int(os.getenv("EMAIL_COOLDOWN_SECONDS", "5"))
    )
    
    def __init__(self, db):
        """
        Initialize with database connection.
        
        Args:
            db: MongoDB database (can be sync pymongo or async motor)
        """
        self.db = db
        self.collection = db[self.COLLECTION_NAME]
        self.config_collection = db[self.CONFIG_COLLECTION]
    
    def _get_time_windows(self) -> Dict[str, datetime]:
        """Get current time windows for rate limit checks."""
        now = datetime.utcnow()
        return {
            "minute": now.replace(second=0, microsecond=0),
            "hour": now.replace(minute=0, second=0, microsecond=0),
            "day": now.replace(hour=0, minute=0, second=0, microsecond=0)
        }
    
    def get_limits(self, account_id: str) -> RateLimitConfig:
        """
        Get rate limits for an account (sync version).
        Falls back to defaults if no custom config.
        """
        try:
            config = self.config_collection.find_one({"account_id": account_id})
            if config:
                return RateLimitConfig(
                    daily_limit=config.get("daily_limit", self.DEFAULT_LIMITS.daily_limit),
                    hourly_limit=config.get("hourly_limit", self.DEFAULT_LIMITS.hourly_limit),
                    per_minute_limit=config.get("per_minute_limit", self.DEFAULT_LIMITS.per_minute_limit),
                    cooldown_seconds=config.get("cooldown_seconds", self.DEFAULT_LIMITS.cooldown_seconds)
                )
        except Exception as e:
            logger.warning(f"Failed to get custom limits for {account_id}: {e}")
        
        return self.DEFAULT_LIMITS
    
    def get_usage(self, account_id: str) -> Dict[str, int]:
        """
        Get current usage for an account (sync version).
        """
        windows = self._get_time_windows()
        
        try:
            usage_doc = self.collection.find_one({"account_id": account_id})
            if not usage_doc:
                return {"minute": 0, "hour": 0, "day": 0, "last_send": None}
            
            # Check if usage is within current time windows
            result = {
                "minute": 0,
                "hour": 0,
                "day": 0,
                "last_send": usage_doc.get("last_send_at")
            }
            
            # Count sends in each window
            sends = usage_doc.get("sends", [])
            for send_time in sends:
                if isinstance(send_time, str):
                    send_time = datetime.fromisoformat(send_time)
                
                if send_time >= windows["minute"]:
                    result["minute"] += 1
                if send_time >= windows["hour"]:
                    result["hour"] += 1
                if send_time >= windows["day"]:
                    result["day"] += 1
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get usage for {account_id}: {e}")
            return {"minute": 0, "hour": 0, "day": 0, "last_send": None}
    
    def check_can_send(self, account_id: str) -> RateLimitStatus:
        """
        Check if sending is allowed for an account (sync version).
        """
        limits = self.get_limits(account_id)
        usage = self.get_usage(account_id)
        
        # Check cooldown
        if usage["last_send"]:
            last_send = usage["last_send"]
            if isinstance(last_send, str):
                last_send = datetime.fromisoformat(last_send)
            
            seconds_since_last = (datetime.utcnow() - last_send).total_seconds()
            if seconds_since_last < limits.cooldown_seconds:
                wait = int(limits.cooldown_seconds - seconds_since_last)
                return RateLimitStatus(
                    allowed=False,
                    reason=f"Cooldown active. Wait {wait} seconds.",
                    wait_seconds=wait,
                    current_usage=usage,
                    limits={
                        "daily": limits.daily_limit,
                        "hourly": limits.hourly_limit,
                        "per_minute": limits.per_minute_limit
                    }
                )
        
        # Check minute limit
        if usage["minute"] >= limits.per_minute_limit:
            return RateLimitStatus(
                allowed=False,
                reason=f"Per-minute limit reached ({limits.per_minute_limit})",
                wait_seconds=60,
                current_usage=usage,
                limits={
                    "daily": limits.daily_limit,
                    "hourly": limits.hourly_limit,
                    "per_minute": limits.per_minute_limit
                }
            )
        
        # Check hourly limit
        if usage["hour"] >= limits.hourly_limit:
            return RateLimitStatus(
                allowed=False,
                reason=f"Hourly limit reached ({limits.hourly_limit})",
                wait_seconds=3600,
                current_usage=usage,
                limits={
                    "daily": limits.daily_limit,
                    "hourly": limits.hourly_limit,
                    "per_minute": limits.per_minute_limit
                }
            )
        
        # Check daily limit
        if usage["day"] >= limits.daily_limit:
            return RateLimitStatus(
                allowed=False,
                reason=f"Daily limit reached ({limits.daily_limit})",
                wait_seconds=86400,
                current_usage=usage,
                limits={
                    "daily": limits.daily_limit,
                    "hourly": limits.hourly_limit,
                    "per_minute": limits.per_minute_limit
                }
            )
        
        # All checks passed
        return RateLimitStatus(
            allowed=True,
            current_usage=usage,
            limits={
                "daily": limits.daily_limit,
                "hourly": limits.hourly_limit,
                "per_minute": limits.per_minute_limit
            }
        )
    
    def record_send(self, account_id: str) -> bool:
        """
        Record a send for rate limiting (sync version).
        Cleans up old entries automatically.
        """
        now = datetime.utcnow()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        try:
            # Update or create usage document
            result = self.collection.update_one(
                {"account_id": account_id},
                {
                    "$push": {
                        "sends": {
                            "$each": [now],
                            "$slice": -1000  # Keep last 1000 entries max
                        }
                    },
                    "$set": {
                        "last_send_at": now,
                        "updated_at": now
                    },
                    "$setOnInsert": {
                        "account_id": account_id,
                        "created_at": now
                    }
                },
                upsert=True
            )
            
            # Periodically clean up old entries (entries older than 24 hours)
            if result.modified_count > 0 or result.upserted_id:
                self.collection.update_one(
                    {"account_id": account_id},
                    {
                        "$pull": {
                            "sends": {"$lt": day_start}
                        }
                    }
                )
            
            logger.debug(f"Recorded send for account {account_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to record send for {account_id}: {e}")
            return False
    
    def reset_limits(self, account_id: str) -> bool:
        """
        Reset rate limits for an account (admin function).
        """
        try:
            self.collection.update_one(
                {"account_id": account_id},
                {
                    "$set": {
                        "sends": [],
                        "last_send_at": None,
                        "reset_at": datetime.utcnow()
                    }
                }
            )
            logger.info(f"Rate limits reset for account {account_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to reset limits for {account_id}: {e}")
            return False
    
    def set_custom_limits(
        self,
        account_id: str,
        daily_limit: int = None,
        hourly_limit: int = None,
        per_minute_limit: int = None,
        cooldown_seconds: int = None
    ) -> bool:
        """
        Set custom rate limits for an account.
        """
        try:
            update = {"account_id": account_id, "updated_at": datetime.utcnow()}
            if daily_limit is not None:
                update["daily_limit"] = daily_limit
            if hourly_limit is not None:
                update["hourly_limit"] = hourly_limit
            if per_minute_limit is not None:
                update["per_minute_limit"] = per_minute_limit
            if cooldown_seconds is not None:
                update["cooldown_seconds"] = cooldown_seconds
            
            self.config_collection.update_one(
                {"account_id": account_id},
                {"$set": update},
                upsert=True
            )
            logger.info(f"Custom limits set for account {account_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to set custom limits for {account_id}: {e}")
            return False


    def get_available_accounts(self, required_capacity: int = 1) -> list:
        """
        Get available Gmail accounts with capacity for required sends.
        Returns accounts with sends_today + required_capacity <= 2000.
        Sorted by sends_today ASC (accounts with least usage first).
        
        Args:
            required_capacity: Number of emails to be sent (default: 1)
            
        Returns:
            List of available account dicts with fields:
            - account_id, account_email, sends_today, send_limit, etc.
        """
        try:
            # Query gmail_account_usage collection from deliverability module
            gmail_usage_collection = self.db.get_collection("gmail_account_usage")
            
            # Calculate max sends allowed
            max_sends_today = 2000 - required_capacity
            
            # Find active accounts with capacity
            available = list(gmail_usage_collection.find(
                {
                    "status": "active",
                    "sends_today": {"$lte": max_sends_today}
                }
            ).sort("sends_today", 1))  # Sort ASC: least used first
            
            logger.info(f"Found {len(available)} accounts with capacity for {required_capacity} sends")
            return available
            
        except Exception as e:
            logger.error(f"Failed to get available accounts: {e}")
            return []
    
    def select_best_account(self, accounts: list) -> Optional[Dict[str, Any]]:
        """
        Select best account from available list using round-robin within capacity tiers.
        Prefers accounts under 80% capacity (< 1600 sends) for round-robin distribution.
        Falls back to any available account if all are heavily used.
        
        Args:
            accounts: List of available account dicts
            
        Returns:
            Selected account dict or None if list is empty
        """
        if not accounts:
            return None
        
        # Define 80% threshold (1600 out of 2000)
        OPTIMAL_THRESHOLD = 1600
        
        # Filter accounts under 80% capacity
        optimal_accounts = [acc for acc in accounts if acc.get("sends_today", 0) < OPTIMAL_THRESHOLD]
        
        if optimal_accounts:
            # Round-robin: select account with lowest sends_today
            # Already sorted by sends_today ASC, so take first
            selected = optimal_accounts[0]
            logger.info(f"Selected optimal account {selected.get('account_email')} with {selected.get('sends_today', 0)} sends")
            return selected
        else:
            # All accounts heavily used, select least used
            selected = accounts[0]  # First in sorted list
            logger.warning(f"All accounts over 80% capacity. Selected {selected.get('account_email')} with {selected.get('sends_today', 0)} sends")
            return selected
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """
        Get aggregate statistics for the entire Gmail account pool.
        
        Returns:
            Dict with keys:
            - total_capacity: Total sending capacity across all accounts
            - used: Total emails sent today across all accounts
            - available: Remaining capacity
            - accounts: List of all accounts with usage stats
            - active_accounts: Number of active accounts
            - quota_exceeded: Number of accounts at quota
        """
        try:
            gmail_usage_collection = self.db.get_collection("gmail_account_usage")
            
            # Get all accounts
            all_accounts = list(gmail_usage_collection.find({}))
            
            # Calculate aggregates
            active_accounts = [acc for acc in all_accounts if acc.get("status") == "active"]
            total_capacity = len(active_accounts) * 2000
            used = sum(acc.get("sends_today", 0) for acc in active_accounts)
            available = total_capacity - used
            quota_exceeded = len([acc for acc in all_accounts if acc.get("status") == "quota_exceeded"])
            
            stats = {
                "total_capacity": total_capacity,
                "used": used,
                "available": available,
                "percentage_used": round((used / total_capacity * 100) if total_capacity > 0 else 0, 2),
                "active_accounts": len(active_accounts),
                "total_accounts": len(all_accounts),
                "quota_exceeded": quota_exceeded,
                "accounts": [
                    {
                        "account_id": acc.get("account_id"),
                        "account_email": acc.get("account_email"),
                        "sends_today": acc.get("sends_today", 0),
                        "send_limit": acc.get("send_limit", 2000),
                        "status": acc.get("status", "unknown"),
                        "percentage_used": round((acc.get("sends_today", 0) / acc.get("send_limit", 2000) * 100), 2)
                    }
                    for acc in all_accounts
                ]
            }
            
            logger.info(f"Pool stats: {used}/{total_capacity} used ({stats['percentage_used']}%)")
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get pool stats: {e}")
            return {
                "total_capacity": 0,
                "used": 0,
                "available": 0,
                "percentage_used": 0,
                "active_accounts": 0,
                "total_accounts": 0,
                "quota_exceeded": 0,
                "accounts": []
            }


# Singleton instance holder
_rate_limiter: Optional[RateLimitService] = None


def get_rate_limiter(db) -> RateLimitService:
    """Get or create the rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimitService(db)
    return _rate_limiter
