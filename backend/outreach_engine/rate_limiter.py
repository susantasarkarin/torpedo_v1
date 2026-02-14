"""
RATE LIMITER
============

Per-mailbox rate limiting with safety controls.

Enterprise Sending Rules:
- Max 300-400 emails/day per inbox
- Max 40-60 emails/hour per inbox
- Randomized send interval (60-180 seconds)
- Sending window: 9am-5:30pm recipient timezone
- Auto pause if:
    - Bounce rate > 5%
    - Reply detected (stop that lead)
    - Unsubscribe detected
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
from pymongo.database import Database
from collections import defaultdict
import threading

from .models import MailboxHealth

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter for email sending with per-mailbox controls.
    
    Features:
    - Per-mailbox daily/hourly limits
    - Sending window enforcement
    - Bounce rate monitoring
    - Thread-safe counter updates
    """
    
    # Default limits
    DEFAULT_DAILY_LIMIT = 400
    DEFAULT_HOURLY_LIMIT = 60
    BOUNCE_RATE_THRESHOLD = 0.05  # 5%
    
    # Sending window (server timezone by default)
    SEND_WINDOW_START_HOUR = 9  # 9 AM
    SEND_WINDOW_END_HOUR = 17   # 5 PM (17:30 represented as 17)
    VALID_SEND_DAYS = [0, 1, 2, 3, 4]  # Monday-Friday
    
    def __init__(self, db: Database):
        """
        Initialize rate limiter.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.mailboxes_collection = db["outreach_mailboxes"]
        self.sends_collection = db["outreach_sends_v2"]
        
        # In-memory counters for fast checks (synced from DB periodically)
        self._lock = threading.Lock()
        self._daily_counts: Dict[str, int] = defaultdict(int)
        self._hourly_counts: Dict[str, int] = defaultdict(int)
        self._last_sync = datetime.utcnow()
    
    def can_send(
        self,
        mailbox_id: str,
        settings: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        Check if an email can be sent from this mailbox.
        
        Args:
            mailbox_id: Mailbox to check
            settings: Optional campaign settings override
            
        Returns:
            Tuple of (can_send, reason)
        """
        # Get mailbox
        mailbox = self.mailboxes_collection.find_one({"mailbox_id": mailbox_id})
        if not mailbox:
            return False, "Mailbox not found"
        
        # Check mailbox is active
        if not mailbox.get("is_active", False):
            return False, "Mailbox is inactive"
        
        # Check health status
        health = mailbox.get("health_status")
        if health == MailboxHealth.SUSPENDED.value:
            return False, "Mailbox is suspended"
        if health == MailboxHealth.PAUSED.value:
            paused_until = mailbox.get("paused_until")
            if paused_until and paused_until > datetime.utcnow():
                return False, f"Mailbox paused until {paused_until}"
        
        # Check sending window
        in_window, window_reason = self._check_sending_window(settings)
        if not in_window:
            return False, window_reason
        
        # Get limits
        daily_limit = settings.get("max_emails_per_day_per_inbox", 
                                   mailbox.get("daily_send_limit", self.DEFAULT_DAILY_LIMIT))
        hourly_limit = settings.get("max_emails_per_hour_per_inbox",
                                    mailbox.get("hourly_send_limit", self.DEFAULT_HOURLY_LIMIT))
        
        # Check daily limit
        daily_count = self._get_daily_count(mailbox)
        if daily_count >= daily_limit:
            return False, f"Daily limit reached ({daily_count}/{daily_limit})"
        
        # Check hourly limit
        hourly_count = self._get_hourly_count(mailbox)
        if hourly_count >= hourly_limit:
            return False, f"Hourly limit reached ({hourly_count}/{hourly_limit})"
        
        # Check bounce rate
        bounce_rate = mailbox.get("bounce_rate_24h", 0)
        if bounce_rate > self.BOUNCE_RATE_THRESHOLD:
            return False, f"Bounce rate too high ({bounce_rate:.1%})"
        
        return True, "OK"
    
    def _check_sending_window(
        self,
        settings: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        Check if current time is within sending window.
        """
        now = datetime.utcnow()
        
        # Get settings
        if settings:
            start_hour = settings.get("send_hours_start", self.SEND_WINDOW_START_HOUR)
            end_hour = settings.get("send_hours_end", self.SEND_WINDOW_END_HOUR)
            valid_days = settings.get("send_days", self.VALID_SEND_DAYS)
        else:
            start_hour = self.SEND_WINDOW_START_HOUR
            end_hour = self.SEND_WINDOW_END_HOUR
            valid_days = self.VALID_SEND_DAYS
        
        # Check day of week
        if now.weekday() not in valid_days:
            return False, f"Not a valid send day (today: {now.strftime('%A')})"
        
        # Check hour
        if now.hour < start_hour:
            return False, f"Before sending window start ({start_hour}:00)"
        
        if now.hour >= end_hour:
            return False, f"After sending window end ({end_hour}:00)"
        
        return True, "Within sending window"
    
    def _get_daily_count(self, mailbox: Dict[str, Any]) -> int:
        """
        Get daily send count for mailbox.
        """
        daily_reset_at = mailbox.get("daily_reset_at")
        now = datetime.utcnow()
        
        # If reset time has passed, count is effectively 0
        if daily_reset_at and daily_reset_at < now:
            return 0
        
        return mailbox.get("daily_send_count", 0)
    
    def _get_hourly_count(self, mailbox: Dict[str, Any]) -> int:
        """
        Get hourly send count for mailbox.
        """
        hourly_reset_at = mailbox.get("hourly_reset_at")
        now = datetime.utcnow()
        
        # If reset time has passed, count is effectively 0
        if hourly_reset_at and hourly_reset_at < now:
            return 0
        
        return mailbox.get("hourly_send_count", 0)
    
    def get_available_capacity(self, mailbox_id: str) -> Dict[str, Any]:
        """
        Get available sending capacity for mailbox.
        
        Returns:
            Dictionary with capacity info
        """
        mailbox = self.mailboxes_collection.find_one({"mailbox_id": mailbox_id})
        if not mailbox:
            return {"error": "Mailbox not found"}
        
        daily_limit = mailbox.get("daily_send_limit", self.DEFAULT_DAILY_LIMIT)
        hourly_limit = mailbox.get("hourly_send_limit", self.DEFAULT_HOURLY_LIMIT)
        
        daily_count = self._get_daily_count(mailbox)
        hourly_count = self._get_hourly_count(mailbox)
        
        return {
            "mailbox_id": mailbox_id,
            "daily": {
                "used": daily_count,
                "limit": daily_limit,
                "remaining": max(0, daily_limit - daily_count),
                "reset_at": mailbox.get("daily_reset_at")
            },
            "hourly": {
                "used": hourly_count,
                "limit": hourly_limit,
                "remaining": max(0, hourly_limit - hourly_count),
                "reset_at": mailbox.get("hourly_reset_at")
            },
            "can_send": daily_count < daily_limit and hourly_count < hourly_limit,
            "health_status": mailbox.get("health_status")
        }
    
    def get_pool_capacity(self, mailbox_ids: List[str]) -> Dict[str, Any]:
        """
        Get total available capacity across mailbox pool.
        
        Args:
            mailbox_ids: List of mailbox IDs in pool
            
        Returns:
            Pool capacity summary
        """
        total_daily_remaining = 0
        total_hourly_remaining = 0
        available_mailboxes = 0
        
        for mailbox_id in mailbox_ids:
            capacity = self.get_available_capacity(mailbox_id)
            if capacity.get("can_send"):
                available_mailboxes += 1
                total_daily_remaining += capacity["daily"]["remaining"]
                total_hourly_remaining += capacity["hourly"]["remaining"]
        
        return {
            "total_mailboxes": len(mailbox_ids),
            "available_mailboxes": available_mailboxes,
            "total_daily_remaining": total_daily_remaining,
            "total_hourly_remaining": total_hourly_remaining,
            "effective_hourly_capacity": min(total_hourly_remaining, total_daily_remaining)
        }
    
    def calculate_send_schedule(
        self,
        total_emails: int,
        mailbox_ids: List[str],
        settings: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculate optimal send schedule for batch.
        
        Args:
            total_emails: Total emails to send
            mailbox_ids: Available mailbox pool
            settings: Campaign settings
            
        Returns:
            Schedule recommendation
        """
        pool_capacity = self.get_pool_capacity(mailbox_ids)
        
        if pool_capacity["available_mailboxes"] == 0:
            return {
                "feasible": False,
                "reason": "No available mailboxes"
            }
        
        hourly_capacity = pool_capacity["effective_hourly_capacity"]
        daily_capacity = pool_capacity["total_daily_remaining"]
        
        if daily_capacity < total_emails:
            # Need multiple days
            days_needed = (total_emails + daily_capacity - 1) // daily_capacity
            return {
                "feasible": True,
                "warning": f"Will require {days_needed} days to complete",
                "daily_capacity": daily_capacity,
                "hourly_capacity": hourly_capacity,
                "estimated_days": days_needed,
                "recommended_batch_size": min(hourly_capacity, 50)
            }
        
        # Can complete today
        hours_needed = (total_emails + hourly_capacity - 1) // hourly_capacity
        
        return {
            "feasible": True,
            "daily_capacity": daily_capacity,
            "hourly_capacity": hourly_capacity,
            "estimated_hours": hours_needed,
            "recommended_batch_size": min(hourly_capacity, 50)
        }
    
    def record_send(self, mailbox_id: str) -> bool:
        """
        Record a send against mailbox quota.
        This is typically called by MailboxManager.increment_send_count()
        but can be used directly for quick updates.
        
        Args:
            mailbox_id: Mailbox that sent
            
        Returns:
            True if recorded
        """
        now = datetime.utcnow()
        
        # Atomic update with reset logic
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        
        # Try to increment, or reset if past reset time
        result = self.mailboxes_collection.update_one(
            {
                "mailbox_id": mailbox_id,
                "$or": [
                    {"daily_reset_at": {"$gt": now}},
                    {"daily_reset_at": {"$exists": False}},
                    {"daily_reset_at": None}
                ]
            },
            {
                "$inc": {
                    "daily_send_count": 1,
                    "hourly_send_count": 1
                },
                "$set": {
                    "last_send_at": now
                }
            }
        )
        
        if result.modified_count == 0:
            # Need to reset counters
            self.mailboxes_collection.update_one(
                {"mailbox_id": mailbox_id},
                {
                    "$set": {
                        "daily_send_count": 1,
                        "hourly_send_count": 1,
                        "daily_reset_at": tomorrow,
                        "hourly_reset_at": next_hour,
                        "last_send_at": now
                    }
                }
            )
        
        return True
    
    def check_bounce_rate(self, mailbox_id: str) -> Tuple[float, bool]:
        """
        Check current bounce rate for mailbox.
        
        Args:
            mailbox_id: Mailbox to check
            
        Returns:
            Tuple of (bounce_rate, should_pause)
        """
        yesterday = datetime.utcnow() - timedelta(hours=24)
        
        # Count sends and bounces
        total = self.sends_collection.count_documents({
            "mailbox_id": mailbox_id,
            "sent_at": {"$gte": yesterday}
        })
        
        bounced = self.sends_collection.count_documents({
            "mailbox_id": mailbox_id,
            "sent_at": {"$gte": yesterday},
            "status": "bounced"
        })
        
        if total == 0:
            return 0.0, False
        
        rate = bounced / total
        should_pause = rate > self.BOUNCE_RATE_THRESHOLD
        
        return rate, should_pause
    
    def pause_if_needed(self, mailbox_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check bounce rate and pause mailbox if threshold exceeded.
        
        Returns:
            Tuple of (was_paused, reason)
        """
        rate, should_pause = self.check_bounce_rate(mailbox_id)
        
        if should_pause:
            reason = f"Bounce rate {rate:.1%} exceeds threshold {self.BOUNCE_RATE_THRESHOLD:.1%}"
            
            self.mailboxes_collection.update_one(
                {"mailbox_id": mailbox_id},
                {"$set": {
                    "health_status": MailboxHealth.THROTTLED.value,
                    "paused_until": datetime.utcnow() + timedelta(hours=4),
                    "pause_reason": reason,
                    "bounce_rate_24h": rate,
                    "updated_at": datetime.utcnow()
                }}
            )
            
            logger.warning(f"Paused mailbox {mailbox_id}: {reason}")
            return True, reason
        
        return False, None
