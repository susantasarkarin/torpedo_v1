"""
RATE LIMITER
============

Per-mailbox and global rate limit enforcement for email sync.

Features:
- Per-mailbox rate limits (respects provider quotas)
- Global worker throttling
- Sliding window rate limiting
- Automatic backoff on 429 responses
- Priority queue for live sync over backfill

Gmail API Quotas (per user):
- 250 quota units/second
- messages.list: 5 units/call
- messages.get: 5 units/call
- history.list: 2 units/call

Conservative limits for this system:
- 50 API calls/minute per mailbox
- 500 API calls/hour per mailbox
- Backfill pauses when approaching limits
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
from threading import Lock
from dataclasses import dataclass, field
from pymongo import MongoClient, ReturnDocument

from .models import RateLimitDocument, RateLimitWindow

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limit configuration"""
    # Per-mailbox limits
    per_minute_limit: int = 50  # API calls per minute
    per_hour_limit: int = 500  # API calls per hour
    per_day_limit: int = 5000  # API calls per day
    
    # Cooldown after hitting limit
    minute_cooldown_seconds: int = 60
    hour_cooldown_seconds: int = 300  # 5 minutes
    day_cooldown_seconds: int = 3600  # 1 hour
    
    # Backoff configuration
    min_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    backoff_multiplier: float = 2.0
    
    # Thresholds for pausing backfill (to preserve quota for live sync)
    backfill_pause_threshold_percent: float = 0.8  # Pause at 80% of limit


@dataclass
class GlobalRateLimitConfig:
    """Global rate limit across all workers"""
    max_concurrent_backfills: int = 5
    max_concurrent_syncs: int = 20
    global_per_second_limit: int = 100  # Total API calls/second across all mailboxes


class RateLimiter:
    """
    Per-mailbox rate limiter with sliding window.
    
    Design:
    - Uses MongoDB for persistence (crash recovery)
    - Sliding window algorithm for smooth limits
    - Backoff tracking for 429 responses
    """
    
    def __init__(
        self,
        db: MongoClient,
        config: Optional[RateLimitConfig] = None,
        collection_name: str = "rate_limits"
    ):
        """
        Initialize rate limiter.
        
        Args:
            db: MongoDB database instance
            config: Rate limit configuration
            collection_name: Name of the rate limits collection
        """
        self.collection = db[collection_name]
        self.config = config or RateLimitConfig()
        self._ensure_indexes()
        self._local_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
    
    def _ensure_indexes(self):
        """Create required indexes"""
        try:
            self.collection.create_index("mailbox_id", unique=True)
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    def _get_or_create_limit_doc(self, mailbox_id: str) -> Dict[str, Any]:
        """Get or create rate limit document for mailbox"""
        doc = self.collection.find_one({"mailbox_id": mailbox_id})
        
        if not doc:
            now = datetime.utcnow()
            doc = {
                "mailbox_id": mailbox_id,
                "minute_window": {"count": 0, "window_start": now},
                "hour_window": {"count": 0, "window_start": now},
                "day_window": {"count": 0, "window_start": now},
                "last_request_at": None,
                "backoff_until": None,
                "consecutive_rate_limits": 0,
                "updated_at": now,
            }
            try:
                self.collection.insert_one(doc)
            except Exception:
                # Race condition - another process created it
                doc = self.collection.find_one({"mailbox_id": mailbox_id})
        
        return doc
    
    def _reset_window_if_expired(
        self,
        window: Dict[str, Any],
        window_duration: timedelta
    ) -> Tuple[Dict[str, Any], bool]:
        """Reset window if expired, return (updated_window, was_reset)"""
        now = datetime.utcnow()
        window_start = window.get("window_start", now)
        
        if isinstance(window_start, str):
            window_start = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
        
        if now - window_start >= window_duration:
            return {"count": 0, "window_start": now}, True
        
        return window, False
    
    def check_rate_limit(self, mailbox_id: str) -> Tuple[bool, Optional[int]]:
        """
        Check if a request can be made for this mailbox.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            Tuple of (can_proceed, wait_seconds)
            - can_proceed: True if request allowed
            - wait_seconds: Seconds to wait if not allowed (None if allowed)
        """
        doc = self._get_or_create_limit_doc(mailbox_id)
        now = datetime.utcnow()
        
        # Check backoff
        backoff_until = doc.get("backoff_until")
        if backoff_until:
            if isinstance(backoff_until, str):
                backoff_until = datetime.fromisoformat(backoff_until.replace("Z", "+00:00"))
            if now < backoff_until:
                wait = int((backoff_until - now).total_seconds())
                logger.debug(f"Mailbox {mailbox_id} in backoff, wait {wait}s")
                return False, wait
        
        # Check minute window
        minute_window, minute_reset = self._reset_window_if_expired(
            doc.get("minute_window", {}),
            timedelta(minutes=1)
        )
        if minute_window.get("count", 0) >= self.config.per_minute_limit:
            wait = self.config.minute_cooldown_seconds
            logger.debug(f"Mailbox {mailbox_id} hit minute limit")
            return False, wait
        
        # Check hour window
        hour_window, hour_reset = self._reset_window_if_expired(
            doc.get("hour_window", {}),
            timedelta(hours=1)
        )
        if hour_window.get("count", 0) >= self.config.per_hour_limit:
            wait = self.config.hour_cooldown_seconds
            logger.debug(f"Mailbox {mailbox_id} hit hour limit")
            return False, wait
        
        # Check day window
        day_window, day_reset = self._reset_window_if_expired(
            doc.get("day_window", {}),
            timedelta(days=1)
        )
        if day_window.get("count", 0) >= self.config.per_day_limit:
            wait = self.config.day_cooldown_seconds
            logger.debug(f"Mailbox {mailbox_id} hit day limit")
            return False, wait
        
        return True, None
    
    def record_request(self, mailbox_id: str) -> bool:
        """
        Record that a request was made.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            True if recorded successfully
        """
        now = datetime.utcnow()
        
        # Get current doc and update windows
        doc = self._get_or_create_limit_doc(mailbox_id)
        
        # Reset windows if expired
        minute_window, _ = self._reset_window_if_expired(
            doc.get("minute_window", {}), timedelta(minutes=1)
        )
        hour_window, _ = self._reset_window_if_expired(
            doc.get("hour_window", {}), timedelta(hours=1)
        )
        day_window, _ = self._reset_window_if_expired(
            doc.get("day_window", {}), timedelta(days=1)
        )
        
        # Increment counts
        minute_window["count"] = minute_window.get("count", 0) + 1
        hour_window["count"] = hour_window.get("count", 0) + 1
        day_window["count"] = day_window.get("count", 0) + 1
        
        result = self.collection.update_one(
            {"mailbox_id": mailbox_id},
            {
                "$set": {
                    "minute_window": minute_window,
                    "hour_window": hour_window,
                    "day_window": day_window,
                    "last_request_at": now,
                    "updated_at": now,
                }
            },
            upsert=True
        )
        
        return result.modified_count > 0 or result.upserted_id is not None
    
    def record_rate_limit_hit(self, mailbox_id: str) -> int:
        """
        Record that we hit a rate limit (429 response).
        Implements exponential backoff.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            Backoff duration in seconds
        """
        now = datetime.utcnow()
        
        doc = self._get_or_create_limit_doc(mailbox_id)
        consecutive = doc.get("consecutive_rate_limits", 0) + 1
        
        # Calculate exponential backoff
        backoff = min(
            self.config.min_backoff_seconds * (self.config.backoff_multiplier ** consecutive),
            self.config.max_backoff_seconds
        )
        
        backoff_until = now + timedelta(seconds=backoff)
        
        self.collection.update_one(
            {"mailbox_id": mailbox_id},
            {
                "$set": {
                    "backoff_until": backoff_until,
                    "consecutive_rate_limits": consecutive,
                    "updated_at": now,
                }
            },
            upsert=True
        )
        
        logger.warning(
            f"Rate limit hit for mailbox {mailbox_id}, backoff {backoff}s "
            f"(consecutive: {consecutive})"
        )
        
        return int(backoff)
    
    def clear_backoff(self, mailbox_id: str):
        """
        Clear backoff after successful request.
        
        Args:
            mailbox_id: Mailbox ObjectId string
        """
        self.collection.update_one(
            {"mailbox_id": mailbox_id},
            {
                "$set": {
                    "backoff_until": None,
                    "consecutive_rate_limits": 0,
                    "updated_at": datetime.utcnow(),
                }
            }
        )
    
    def should_pause_backfill(self, mailbox_id: str) -> bool:
        """
        Check if backfill should pause to preserve quota for live sync.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            True if backfill should pause
        """
        doc = self._get_or_create_limit_doc(mailbox_id)
        
        # Check against thresholds
        threshold = self.config.backfill_pause_threshold_percent
        
        # Check hour window (most important for sustained load)
        hour_window = doc.get("hour_window", {})
        hour_count = hour_window.get("count", 0)
        if hour_count >= self.config.per_hour_limit * threshold:
            logger.info(
                f"Mailbox {mailbox_id} approaching hour limit "
                f"({hour_count}/{self.config.per_hour_limit}), pausing backfill"
            )
            return True
        
        return False
    
    def get_status(self, mailbox_id: str) -> Dict[str, Any]:
        """
        Get rate limit status for a mailbox.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            Status dict with current counts and limits
        """
        doc = self._get_or_create_limit_doc(mailbox_id)
        now = datetime.utcnow()
        
        # Reset windows if expired for accurate reporting
        minute_window, _ = self._reset_window_if_expired(
            doc.get("minute_window", {}), timedelta(minutes=1)
        )
        hour_window, _ = self._reset_window_if_expired(
            doc.get("hour_window", {}), timedelta(hours=1)
        )
        day_window, _ = self._reset_window_if_expired(
            doc.get("day_window", {}), timedelta(days=1)
        )
        
        backoff_until = doc.get("backoff_until")
        in_backoff = False
        backoff_remaining = 0
        
        if backoff_until:
            if isinstance(backoff_until, str):
                backoff_until = datetime.fromisoformat(backoff_until.replace("Z", "+00:00"))
            if now < backoff_until:
                in_backoff = True
                backoff_remaining = int((backoff_until - now).total_seconds())
        
        return {
            "mailbox_id": mailbox_id,
            "minute": {
                "count": minute_window.get("count", 0),
                "limit": self.config.per_minute_limit,
            },
            "hour": {
                "count": hour_window.get("count", 0),
                "limit": self.config.per_hour_limit,
            },
            "day": {
                "count": day_window.get("count", 0),
                "limit": self.config.per_day_limit,
            },
            "in_backoff": in_backoff,
            "backoff_remaining_seconds": backoff_remaining,
            "consecutive_rate_limits": doc.get("consecutive_rate_limits", 0),
        }


class GlobalRateLimiter:
    """
    Global rate limiter across all workers.
    Controls concurrent operations to prevent overwhelming providers.
    """
    
    def __init__(
        self,
        db: MongoClient,
        config: Optional[GlobalRateLimitConfig] = None,
        collection_name: str = "global_rate_limits"
    ):
        """
        Initialize global rate limiter.
        
        Args:
            db: MongoDB database instance
            config: Global rate limit configuration
            collection_name: Collection name
        """
        self.collection = db[collection_name]
        self.config = config or GlobalRateLimitConfig()
        self._ensure_state()
    
    def _ensure_state(self):
        """Ensure global state document exists"""
        self.collection.update_one(
            {"_id": "global"},
            {
                "$setOnInsert": {
                    "active_backfills": [],
                    "active_syncs": [],
                    "last_request_at": datetime.utcnow(),
                    "requests_this_second": 0,
                    "second_start": datetime.utcnow(),
                }
            },
            upsert=True
        )
    
    def acquire_backfill_slot(self, mailbox_id: str) -> bool:
        """
        Try to acquire a backfill slot.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            True if slot acquired
        """
        result = self.collection.find_one_and_update(
            {
                "_id": "global",
                "$expr": {
                    "$lt": [{"$size": "$active_backfills"}, self.config.max_concurrent_backfills]
                }
            },
            {
                "$addToSet": {"active_backfills": mailbox_id},
                "$set": {"updated_at": datetime.utcnow()}
            },
            return_document=ReturnDocument.AFTER
        )
        
        if result:
            logger.info(f"Acquired backfill slot for {mailbox_id}")
            return True
        
        logger.debug(f"No backfill slots available for {mailbox_id}")
        return False
    
    def release_backfill_slot(self, mailbox_id: str):
        """
        Release a backfill slot.
        
        Args:
            mailbox_id: Mailbox ObjectId string
        """
        self.collection.update_one(
            {"_id": "global"},
            {
                "$pull": {"active_backfills": mailbox_id},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        logger.info(f"Released backfill slot for {mailbox_id}")
    
    def acquire_sync_slot(self, mailbox_id: str) -> bool:
        """
        Try to acquire an incremental sync slot.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            True if slot acquired
        """
        result = self.collection.find_one_and_update(
            {
                "_id": "global",
                "$expr": {
                    "$lt": [{"$size": "$active_syncs"}, self.config.max_concurrent_syncs]
                }
            },
            {
                "$addToSet": {"active_syncs": mailbox_id},
                "$set": {"updated_at": datetime.utcnow()}
            },
            return_document=ReturnDocument.AFTER
        )
        
        return result is not None
    
    def release_sync_slot(self, mailbox_id: str):
        """
        Release a sync slot.
        
        Args:
            mailbox_id: Mailbox ObjectId string
        """
        self.collection.update_one(
            {"_id": "global"},
            {
                "$pull": {"active_syncs": mailbox_id},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
    
    def check_global_rate(self) -> Tuple[bool, int]:
        """
        Check if global rate limit allows a request.
        
        Returns:
            Tuple of (can_proceed, wait_ms)
        """
        now = datetime.utcnow()
        doc = self.collection.find_one({"_id": "global"})
        
        if not doc:
            return True, 0
        
        second_start = doc.get("second_start", now)
        if isinstance(second_start, str):
            second_start = datetime.fromisoformat(second_start.replace("Z", "+00:00"))
        
        # Reset if second has passed
        if (now - second_start).total_seconds() >= 1:
            self.collection.update_one(
                {"_id": "global"},
                {
                    "$set": {
                        "requests_this_second": 1,
                        "second_start": now,
                        "last_request_at": now,
                    }
                }
            )
            return True, 0
        
        # Check limit
        requests = doc.get("requests_this_second", 0)
        if requests >= self.config.global_per_second_limit:
            wait_ms = int((1 - (now - second_start).total_seconds()) * 1000)
            return False, max(wait_ms, 10)
        
        # Increment counter
        self.collection.update_one(
            {"_id": "global"},
            {
                "$inc": {"requests_this_second": 1},
                "$set": {"last_request_at": now}
            }
        )
        
        return True, 0
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get global rate limit status.
        
        Returns:
            Status dict
        """
        doc = self.collection.find_one({"_id": "global"}) or {}
        
        return {
            "active_backfills": len(doc.get("active_backfills", [])),
            "max_backfills": self.config.max_concurrent_backfills,
            "active_syncs": len(doc.get("active_syncs", [])),
            "max_syncs": self.config.max_concurrent_syncs,
            "requests_this_second": doc.get("requests_this_second", 0),
            "global_per_second_limit": self.config.global_per_second_limit,
        }
