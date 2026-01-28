"""
THROTTLE MANAGER
================

Global send rate limiting and campaign-level throttling with automatic
slowdown on delivery issues.

Features:
- Global rate limits across all email accounts
- Per-campaign throttling
- Per-mailbox throttling
- Automatic slowdown on bounce rates
- Sliding window rate limiting
- Delivery health monitoring
- Warm-up mode support

Usage:
    from campaigns.throttle_manager import ThrottleManager
    
    throttle = ThrottleManager()
    
    # Check before sending
    if throttle.check_global_rate_limit():
        # OK to send
        throttle.record_send(campaign_id="...", mailbox_id="...")
    else:
        # Wait or reschedule
        wait_time = throttle.get_wait_time()
        
    # Monitor and auto-throttle
    if bounce_rate > 5:
        throttle.apply_throttle(
            campaign_id="...",
            reason="High bounce rate detected"
        )
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Literal
from redis import Redis
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Throttle reasons
ThrottleReason = Literal[
    "high_bounce_rate",
    "spam_complaints",
    "delivery_issues",
    "manual",
    "warmup"
]

# Redis keys
KEY_GLOBAL_SENDS = "throttle:global:sends"
KEY_CAMPAIGN_SENDS = "throttle:campaign:{campaign_id}:sends"
KEY_MAILBOX_SENDS = "throttle:mailbox:{mailbox_id}:sends"
KEY_THROTTLE_STATUS = "throttle:status:{resource_type}:{resource_id}"
KEY_DELIVERY_HEALTH = "throttle:health:{mailbox_id}"

# Default limits
DEFAULT_GLOBAL_HOURLY = 5000
DEFAULT_GLOBAL_DAILY = 50000
DEFAULT_CAMPAIGN_HOURLY = 500
DEFAULT_MAILBOX_HOURLY = 100
DEFAULT_MAILBOX_DAILY = 500


class ThrottleStatus(BaseModel):
    """Throttle status for a resource"""
    resource_type: str  # global, campaign, mailbox
    resource_id: str
    is_throttled: bool = False
    reason: Optional[ThrottleReason] = None
    throttled_at: Optional[datetime] = None
    throttled_until: Optional[datetime] = None
    rate_limit_override: Optional[int] = None  # Custom rate limit
    notes: Optional[str] = None


class DeliveryHealth(BaseModel):
    """Delivery health metrics for a mailbox"""
    mailbox_id: str
    
    # Counts (last 24 hours)
    total_sent: int = 0
    bounces: int = 0
    spam_complaints: int = 0
    successful_deliveries: int = 0
    
    # Rates
    bounce_rate: float = 0.0
    spam_rate: float = 0.0
    
    # Status
    health_status: str = "good"  # good, warning, critical
    last_updated: datetime
    
    # Auto-throttle thresholds
    bounce_threshold: float = 5.0  # 5% bounce rate triggers throttle
    spam_threshold: float = 0.1  # 0.1% spam rate triggers throttle


class ThrottleManager:
    """
    Manages global and resource-level throttling for email sending
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        global_hourly_limit: int = DEFAULT_GLOBAL_HOURLY,
        global_daily_limit: int = DEFAULT_GLOBAL_DAILY
    ):
        """
        Initialize throttle manager
        
        Args:
            redis_url: Redis connection URL
            global_hourly_limit: Maximum sends per hour globally
            global_daily_limit: Maximum sends per day globally
        """
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.global_hourly_limit = global_hourly_limit
        self.global_daily_limit = global_daily_limit
    
    def check_global_rate_limit(self) -> bool:
        """
        Check if global rate limit allows sending
        
        Returns:
            True if within rate limits, False otherwise
        """
        current_time = time.time()
        
        # Check hourly limit
        hour_ago = current_time - 3600
        hourly_count = self._count_sends_in_window(KEY_GLOBAL_SENDS, hour_ago, current_time)
        
        if hourly_count >= self.global_hourly_limit:
            logger.warning(f"Global hourly limit reached: {hourly_count}/{self.global_hourly_limit}")
            return False
        
        # Check daily limit
        day_ago = current_time - 86400
        daily_count = self._count_sends_in_window(KEY_GLOBAL_SENDS, day_ago, current_time)
        
        if daily_count >= self.global_daily_limit:
            logger.warning(f"Global daily limit reached: {daily_count}/{self.global_daily_limit}")
            return False
        
        return True
    
    def check_campaign_rate_limit(
        self,
        campaign_id: str,
        hourly_limit: Optional[int] = None
    ) -> bool:
        """
        Check if campaign-specific rate limit allows sending
        
        Args:
            campaign_id: Campaign identifier
            hourly_limit: Override default hourly limit
            
        Returns:
            True if within rate limits
        """
        # Check if campaign is throttled
        status = self.get_throttle_status("campaign", campaign_id)
        if status.is_throttled:
            if status.throttled_until and datetime.utcnow() < status.throttled_until:
                logger.warning(
                    f"Campaign {campaign_id} is throttled until {status.throttled_until}. "
                    f"Reason: {status.reason}"
                )
                return False
            else:
                # Throttle period expired, clear it
                self.clear_throttle("campaign", campaign_id)
        
        # Check rate limit
        limit = hourly_limit or status.rate_limit_override or DEFAULT_CAMPAIGN_HOURLY
        
        current_time = time.time()
        hour_ago = current_time - 3600
        key = KEY_CAMPAIGN_SENDS.format(campaign_id=campaign_id)
        
        count = self._count_sends_in_window(key, hour_ago, current_time)
        
        if count >= limit:
            logger.warning(f"Campaign {campaign_id} hourly limit reached: {count}/{limit}")
            return False
        
        return True
    
    def check_mailbox_rate_limit(
        self,
        mailbox_id: str,
        hourly_limit: Optional[int] = None,
        daily_limit: Optional[int] = None
    ) -> bool:
        """
        Check if mailbox-specific rate limit allows sending
        
        Args:
            mailbox_id: Mailbox identifier
            hourly_limit: Override default hourly limit
            daily_limit: Override default daily limit
            
        Returns:
            True if within rate limits
        """
        # Check if mailbox is throttled
        status = self.get_throttle_status("mailbox", mailbox_id)
        if status.is_throttled:
            if status.throttled_until and datetime.utcnow() < status.throttled_until:
                logger.warning(
                    f"Mailbox {mailbox_id} is throttled until {status.throttled_until}. "
                    f"Reason: {status.reason}"
                )
                return False
            else:
                self.clear_throttle("mailbox", mailbox_id)
        
        current_time = time.time()
        key = KEY_MAILBOX_SENDS.format(mailbox_id=mailbox_id)
        
        # Check hourly limit
        h_limit = hourly_limit or status.rate_limit_override or DEFAULT_MAILBOX_HOURLY
        hour_ago = current_time - 3600
        hourly_count = self._count_sends_in_window(key, hour_ago, current_time)
        
        if hourly_count >= h_limit:
            logger.warning(f"Mailbox {mailbox_id} hourly limit reached: {hourly_count}/{h_limit}")
            return False
        
        # Check daily limit
        d_limit = daily_limit or DEFAULT_MAILBOX_DAILY
        day_ago = current_time - 86400
        daily_count = self._count_sends_in_window(key, day_ago, current_time)
        
        if daily_count >= d_limit:
            logger.warning(f"Mailbox {mailbox_id} daily limit reached: {daily_count}/{d_limit}")
            return False
        
        return True
    
    def record_send(
        self,
        campaign_id: Optional[str] = None,
        mailbox_id: Optional[str] = None
    ) -> None:
        """
        Record a send for rate limiting
        
        Args:
            campaign_id: Campaign identifier
            mailbox_id: Mailbox identifier
        """
        current_time = time.time()
        
        # Record global send
        self.redis.zadd(KEY_GLOBAL_SENDS, {str(current_time): current_time})
        self._cleanup_old_records(KEY_GLOBAL_SENDS, current_time - 86400)
        
        # Record campaign send
        if campaign_id:
            key = KEY_CAMPAIGN_SENDS.format(campaign_id=campaign_id)
            self.redis.zadd(key, {str(current_time): current_time})
            self._cleanup_old_records(key, current_time - 3600)
        
        # Record mailbox send
        if mailbox_id:
            key = KEY_MAILBOX_SENDS.format(mailbox_id=mailbox_id)
            self.redis.zadd(key, {str(current_time): current_time})
            self._cleanup_old_records(key, current_time - 86400)
    
    def apply_throttle(
        self,
        campaign_id: Optional[str] = None,
        mailbox_id: Optional[str] = None,
        reason: ThrottleReason = "manual",
        duration_hours: Optional[int] = None,
        notes: Optional[str] = None
    ) -> None:
        """
        Apply throttle to a campaign or mailbox
        
        Args:
            campaign_id: Campaign to throttle
            mailbox_id: Mailbox to throttle
            reason: Throttle reason
            duration_hours: Throttle duration (None = indefinite)
            notes: Additional notes
        """
        if campaign_id:
            resource_type = "campaign"
            resource_id = campaign_id
        elif mailbox_id:
            resource_type = "mailbox"
            resource_id = mailbox_id
        else:
            raise ValueError("Must specify campaign_id or mailbox_id")
        
        throttled_until = None
        if duration_hours:
            throttled_until = datetime.utcnow() + timedelta(hours=duration_hours)
        
        status = ThrottleStatus(
            resource_type=resource_type,
            resource_id=resource_id,
            is_throttled=True,
            reason=reason,
            throttled_at=datetime.utcnow(),
            throttled_until=throttled_until,
            notes=notes
        )
        
        key = KEY_THROTTLE_STATUS.format(
            resource_type=resource_type,
            resource_id=resource_id
        )
        
        # Store for 30 days or until throttled_until
        ttl = 86400 * 30
        if throttled_until:
            ttl = int((throttled_until - datetime.utcnow()).total_seconds())
        
        self.redis.setex(key, ttl, status.json())
        
        logger.warning(
            f"Throttle applied to {resource_type} {resource_id}. "
            f"Reason: {reason}, Duration: {duration_hours}h, Notes: {notes}"
        )
    
    def clear_throttle(
        self,
        resource_type: str,
        resource_id: str
    ) -> None:
        """
        Clear throttle status
        
        Args:
            resource_type: campaign or mailbox
            resource_id: Resource identifier
        """
        key = KEY_THROTTLE_STATUS.format(
            resource_type=resource_type,
            resource_id=resource_id
        )
        self.redis.delete(key)
        logger.info(f"Throttle cleared for {resource_type} {resource_id}")
    
    def get_throttle_status(
        self,
        resource_type: str,
        resource_id: str
    ) -> ThrottleStatus:
        """
        Get throttle status for a resource
        
        Args:
            resource_type: campaign or mailbox
            resource_id: Resource identifier
            
        Returns:
            ThrottleStatus object
        """
        key = KEY_THROTTLE_STATUS.format(
            resource_type=resource_type,
            resource_id=resource_id
        )
        
        data = self.redis.get(key)
        if data:
            return ThrottleStatus.parse_raw(data)
        else:
            return ThrottleStatus(
                resource_type=resource_type,
                resource_id=resource_id,
                is_throttled=False
            )
    
    def update_delivery_health(
        self,
        mailbox_id: str,
        bounced: bool = False,
        spam_complaint: bool = False,
        delivered: bool = False
    ) -> DeliveryHealth:
        """
        Update delivery health metrics and auto-throttle if needed
        
        Args:
            mailbox_id: Mailbox identifier
            bounced: Whether this send bounced
            spam_complaint: Whether this triggered spam complaint
            delivered: Whether successfully delivered
            
        Returns:
            Updated DeliveryHealth object
        """
        key = KEY_DELIVERY_HEALTH.format(mailbox_id=mailbox_id)
        
        # Get existing health data
        data = self.redis.get(key)
        if data:
            health = DeliveryHealth.parse_raw(data)
        else:
            health = DeliveryHealth(
                mailbox_id=mailbox_id,
                last_updated=datetime.utcnow()
            )
        
        # Update counts
        health.total_sent += 1
        if bounced:
            health.bounces += 1
        if spam_complaint:
            health.spam_complaints += 1
        if delivered:
            health.successful_deliveries += 1
        
        # Calculate rates
        if health.total_sent > 0:
            health.bounce_rate = (health.bounces / health.total_sent) * 100
            health.spam_rate = (health.spam_complaints / health.total_sent) * 100
        
        # Update health status
        if health.bounce_rate > health.bounce_threshold:
            health.health_status = "critical"
        elif health.spam_rate > health.spam_threshold:
            health.health_status = "critical"
        elif health.bounce_rate > health.bounce_threshold * 0.7:
            health.health_status = "warning"
        else:
            health.health_status = "good"
        
        health.last_updated = datetime.utcnow()
        
        # Save to Redis (24 hour TTL)
        self.redis.setex(key, 86400, health.json())
        
        # Auto-throttle if critical
        if health.health_status == "critical":
            reason = "high_bounce_rate" if health.bounce_rate > health.bounce_threshold else "spam_complaints"
            
            # Check if already throttled
            status = self.get_throttle_status("mailbox", mailbox_id)
            if not status.is_throttled:
                self.apply_throttle(
                    mailbox_id=mailbox_id,
                    reason=reason,
                    duration_hours=4,  # 4 hour automatic throttle
                    notes=f"Auto-throttled: bounce_rate={health.bounce_rate:.2f}%, spam_rate={health.spam_rate:.2f}%"
                )
        
        return health
    
    def get_delivery_health(self, mailbox_id: str) -> Optional[DeliveryHealth]:
        """
        Get delivery health for a mailbox
        
        Args:
            mailbox_id: Mailbox identifier
            
        Returns:
            DeliveryHealth object or None
        """
        key = KEY_DELIVERY_HEALTH.format(mailbox_id=mailbox_id)
        data = self.redis.get(key)
        
        if data:
            return DeliveryHealth.parse_raw(data)
        return None
    
    def get_wait_time(
        self,
        resource_type: str = "global",
        resource_id: Optional[str] = None
    ) -> int:
        """
        Get wait time in seconds before next send allowed
        
        Args:
            resource_type: global, campaign, or mailbox
            resource_id: Resource identifier (if not global)
            
        Returns:
            Wait time in seconds
        """
        current_time = time.time()
        
        if resource_type == "global":
            hour_ago = current_time - 3600
            count = self._count_sends_in_window(KEY_GLOBAL_SENDS, hour_ago, current_time)
            
            if count >= self.global_hourly_limit:
                # Find oldest send in the window
                oldest = self.redis.zrange(KEY_GLOBAL_SENDS, 0, 0, withscores=True)
                if oldest:
                    oldest_time = oldest[0][1]
                    wait_time = int(oldest_time + 3600 - current_time)
                    return max(0, wait_time)
        
        return 0
    
    def get_rate_stats(self) -> Dict:
        """
        Get current rate statistics
        
        Returns:
            Dictionary with current send rates
        """
        current_time = time.time()
        hour_ago = current_time - 3600
        day_ago = current_time - 86400
        
        return {
            "global": {
                "last_hour": self._count_sends_in_window(KEY_GLOBAL_SENDS, hour_ago, current_time),
                "last_day": self._count_sends_in_window(KEY_GLOBAL_SENDS, day_ago, current_time),
                "hourly_limit": self.global_hourly_limit,
                "daily_limit": self.global_daily_limit
            }
        }
    
    def _count_sends_in_window(self, key: str, start: float, end: float) -> int:
        """Count sends in time window"""
        return self.redis.zcount(key, start, end)
    
    def _cleanup_old_records(self, key: str, before: float) -> None:
        """Remove old records from sorted set"""
        self.redis.zremrangebyscore(key, 0, before)
