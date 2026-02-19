"""
Sender Manager Service.

Manages email sender accounts, warmup status, and allocation.
"""

import json
import logging
from typing import Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================

class WarmupStage(str, Enum):
    NEW = "new"           # 0-2 weeks, max 10/day
    WARMING = "warming"   # 2-6 weeks, max 30/day
    WARM = "warm"         # 6-12 weeks, max 50/day
    ESTABLISHED = "established"  # 12+ weeks, max 100/day


WARMUP_LIMITS = {
    WarmupStage.NEW: 10,
    WarmupStage.WARMING: 30,
    WarmupStage.WARM: 50,
    WarmupStage.ESTABLISHED: 100
}


# =============================================================================
# Data Models
# =============================================================================

class SenderAccount(BaseModel):
    """Email sender account."""
    id: str
    email: str
    name: str
    warmup_stage: WarmupStage
    warmup_start_date: datetime
    health_score: float = Field(..., ge=0.0, le=100.0)
    daily_sent_count: int = 0
    hourly_sent_count: int = 0
    bounce_rate: float = 0.0
    complaint_rate: float = 0.0
    timezone: str = "UTC"
    is_active: bool = True
    last_send_time: Optional[datetime] = None
    
    # SMTP configuration
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    use_tls: bool = True
    
    @property
    def daily_limit(self) -> int:
        """Get daily sending limit based on warmup stage."""
        return WARMUP_LIMITS.get(self.warmup_stage, 10)
    
    @property
    def remaining_daily_quota(self) -> int:
        """Get remaining daily quota."""
        return max(0, self.daily_limit - self.daily_sent_count)
    
    @property
    def is_healthy(self) -> bool:
        """Check if sender is healthy for sending."""
        return (
            self.health_score >= 70 and
            self.bounce_rate < 0.05 and
            self.complaint_rate < 0.001 and
            self.is_active
        )


class SenderAllocation(BaseModel):
    """Result of sender allocation."""
    selected_sender_id: Optional[str]
    reasoning: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    warnings: Optional[list[str]] = None


class SendingWindow(BaseModel):
    """Optimal sending window."""
    day_of_week: int  # 0=Monday, 6=Sunday
    start_hour: int  # 24-hour format
    end_hour: int
    timezone: str


# =============================================================================
# Service Implementation
# =============================================================================

class SenderManagerService:
    """
    Service for managing sender accounts and allocation.
    
    This service:
    1. Tracks sender health and warmup status
    2. Allocates optimal sender for each email
    3. Manages sending windows and rate limits
    """
    
    # Health thresholds
    MIN_HEALTH_SCORE = 70
    MAX_BOUNCE_RATE = 0.05
    MAX_COMPLAINT_RATE = 0.001
    
    # Hourly limit (conservative)
    MAX_HOURLY_SENDS = 10
    
    def __init__(self, ai_client: Any = None, db: Any = None):
        """
        Initialize the sender manager.
        
        Args:
            ai_client: Optional AI client for smart allocation
            db: MongoDB database instance
        """
        self.ai_client = ai_client
        self.db = db
        self._senders: dict[str, SenderAccount] = {}
        
        # Load senders from DB if available
        if db:
            self._load_senders_from_db()
    
    def _load_senders_from_db(self):
        """Load sender accounts from database."""
        try:
            if self.db:
                senders_collection = self.db["outreach_senders"]
                for doc in senders_collection.find({"is_active": True}):
                    doc["id"] = str(doc.pop("_id"))
                    sender = SenderAccount(**doc)
                    self._senders[sender.id] = sender
                logger.info(f"Loaded {len(self._senders)} senders from database")
        except Exception as e:
            logger.error(f"Failed to load senders from DB: {e}")
    
    def register_sender(self, sender: SenderAccount) -> str:
        """
        Register a sender account.
        
        Args:
            sender: SenderAccount to register
            
        Returns:
            Sender ID
        """
        self._senders[sender.id] = sender
        
        # Persist to DB if available
        if self.db:
            try:
                senders_collection = self.db["outreach_senders"]
                sender_dict = sender.model_dump()
                sender_dict["_id"] = sender.id
                senders_collection.update_one(
                    {"_id": sender.id},
                    {"$set": sender_dict},
                    upsert=True
                )
            except Exception as e:
                logger.error(f"Failed to persist sender to DB: {e}")
        
        logger.info(f"Registered sender: {sender.email}")
        return sender.id
    
    def get_sender(self, sender_id: str) -> Optional[SenderAccount]:
        """Get a sender by ID."""
        return self._senders.get(sender_id)
    
    def get_all_senders(self) -> list[SenderAccount]:
        """Get all registered senders."""
        return list(self._senders.values())
    
    def get_available_senders(self) -> list[SenderAccount]:
        """Get all available senders that can send emails."""
        return [
            sender for sender in self._senders.values()
            if sender.is_healthy and sender.remaining_daily_quota > 0
        ]
    
    async def allocate_sender(
        self,
        recipient_timezone: str = "UTC",
        priority: str = "B",
        required_warmup_stage: Optional[WarmupStage] = None
    ) -> SenderAllocation:
        """
        Allocate the optimal sender for an email.
        
        Args:
            recipient_timezone: Recipient's timezone
            priority: Lead priority (A/B/C)
            required_warmup_stage: Minimum warmup stage required
            
        Returns:
            SenderAllocation with selected sender or None
        """
        available = self.get_available_senders()
        
        if not available:
            return SenderAllocation(
                selected_sender_id=None,
                reasoning="No healthy senders available with remaining quota",
                confidence=0,
                warnings=["All senders exhausted or unhealthy"]
            )
        
        # Filter by warmup stage if required
        if required_warmup_stage:
            stage_order = list(WarmupStage)
            min_index = stage_order.index(required_warmup_stage)
            available = [
                s for s in available
                if stage_order.index(s.warmup_stage) >= min_index
            ]
        
        if not available:
            return SenderAllocation(
                selected_sender_id=None,
                reasoning=f"No senders at warmup stage {required_warmup_stage} or higher",
                confidence=0,
                warnings=["Need to wait for sender warmup"]
            )
        
        # Use AI allocation if available, otherwise use rule-based
        if self.ai_client:
            return await self._ai_allocate(available, recipient_timezone, priority)
        else:
            return self._rule_based_allocate(available, recipient_timezone, priority)
    
    def _rule_based_allocate(
        self,
        available: list[SenderAccount],
        recipient_timezone: str,
        priority: str
    ) -> SenderAllocation:
        """Simple rule-based sender allocation."""
        # Score each sender
        scored = []
        for sender in available:
            score = 0
            
            # Health score weight (40%)
            score += (sender.health_score / 100) * 40
            
            # Quota usage weight (30%) - prefer less used
            usage_ratio = sender.daily_sent_count / sender.daily_limit
            score += (1 - usage_ratio) * 30
            
            # Timezone match weight (20%)
            if sender.timezone == recipient_timezone:
                score += 20
            
            # Warmup stage weight (10%) - prefer established
            stage_scores = {
                WarmupStage.ESTABLISHED: 10,
                WarmupStage.WARM: 7,
                WarmupStage.WARMING: 4,
                WarmupStage.NEW: 1
            }
            score += stage_scores.get(sender.warmup_stage, 0)
            
            scored.append((sender, score))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        best_sender, best_score = scored[0]
        
        warnings = []
        if best_sender.health_score < 80:
            warnings.append(f"Sender health below optimal: {best_sender.health_score}")
        if best_sender.bounce_rate > 0.03:
            warnings.append(f"Bounce rate elevated: {best_sender.bounce_rate:.2%}")
        
        return SenderAllocation(
            selected_sender_id=best_sender.id,
            reasoning=f"Selected {best_sender.email} with score {best_score:.1f}/100",
            confidence=best_score / 100,
            warnings=warnings if warnings else None
        )
    
    async def _ai_allocate(
        self,
        available: list[SenderAccount],
        recipient_timezone: str,
        priority: str
    ) -> SenderAllocation:
        """AI-powered sender allocation."""
        from .master_prompts import SENDER_ALLOCATION_PROMPT
        
        senders_data = [
            {
                "id": s.id,
                "email": s.email,
                "warmup_stage": s.warmup_stage.value,
                "health_score": s.health_score,
                "daily_sent": s.daily_sent_count,
                "daily_limit": s.daily_limit,
                "bounce_rate": s.bounce_rate,
                "timezone": s.timezone
            }
            for s in available
        ]
        
        context = f"""
AVAILABLE SENDERS:
{json.dumps(senders_data, indent=2)}

RECIPIENT TIMEZONE: {recipient_timezone}
LEAD PRIORITY: {priority}
"""
        
        try:
            response = await self.ai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "user", "content": f"{SENDER_ALLOCATION_PROMPT}\n\n---\n\n{context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=300
            )
            
            result = json.loads(response.choices[0].message.content)
            return SenderAllocation(**result)
            
        except Exception as e:
            logger.error(f"AI allocation failed, falling back to rules: {e}")
            return self._rule_based_allocate(available, recipient_timezone, priority)
    
    def record_send(self, sender_id: str) -> None:
        """Record that an email was sent from a sender."""
        sender = self._senders.get(sender_id)
        if sender:
            sender.daily_sent_count += 1
            sender.hourly_sent_count += 1
            sender.last_send_time = datetime.utcnow()
            self._persist_sender(sender)
    
    def record_bounce(self, sender_id: str) -> None:
        """Record a bounce for a sender."""
        sender = self._senders.get(sender_id)
        if sender:
            # Simple rolling average update
            total_sent = sender.daily_sent_count or 1
            sender.bounce_rate = (
                (sender.bounce_rate * (total_sent - 1) + 1) / total_sent
            )
            self._update_health_score(sender)
            self._persist_sender(sender)
    
    def record_complaint(self, sender_id: str) -> None:
        """Record a spam complaint for a sender."""
        sender = self._senders.get(sender_id)
        if sender:
            total_sent = sender.daily_sent_count or 1
            sender.complaint_rate = (
                (sender.complaint_rate * (total_sent - 1) + 1) / total_sent
            )
            self._update_health_score(sender)
            
            # Immediately deactivate if complaint rate too high
            if sender.complaint_rate >= self.MAX_COMPLAINT_RATE:
                sender.is_active = False
                logger.critical(
                    f"SENDER DEACTIVATED due to complaints: {sender.email}"
                )
            
            self._persist_sender(sender)
    
    def _update_health_score(self, sender: SenderAccount) -> None:
        """Update sender health score based on metrics."""
        score = 100
        
        # Penalize for bounce rate
        if sender.bounce_rate > 0.03:
            score -= (sender.bounce_rate - 0.03) * 500
        
        # Heavy penalty for complaints
        if sender.complaint_rate > 0:
            score -= sender.complaint_rate * 10000
        
        sender.health_score = max(0, min(100, score))
    
    def _persist_sender(self, sender: SenderAccount) -> None:
        """Persist sender updates to database."""
        if self.db:
            try:
                senders_collection = self.db["outreach_senders"]
                sender_dict = sender.model_dump()
                senders_collection.update_one(
                    {"_id": sender.id},
                    {"$set": sender_dict}
                )
            except Exception as e:
                logger.error(f"Failed to persist sender update: {e}")
    
    def reset_daily_counts(self) -> None:
        """Reset daily counts for all senders (call at midnight)."""
        for sender in self._senders.values():
            sender.daily_sent_count = 0
            self._persist_sender(sender)
        logger.info("Reset daily counts for all senders")
    
    def reset_hourly_counts(self) -> None:
        """Reset hourly counts for all senders (call each hour)."""
        for sender in self._senders.values():
            sender.hourly_sent_count = 0
    
    def update_warmup_stages(self) -> None:
        """Update warmup stages based on age (call daily)."""
        now = datetime.utcnow()
        
        for sender in self._senders.values():
            days_active = (now - sender.warmup_start_date).days
            
            if days_active >= 84:  # 12 weeks
                new_stage = WarmupStage.ESTABLISHED
            elif days_active >= 42:  # 6 weeks
                new_stage = WarmupStage.WARM
            elif days_active >= 14:  # 2 weeks
                new_stage = WarmupStage.WARMING
            else:
                new_stage = WarmupStage.NEW
            
            if sender.warmup_stage != new_stage:
                logger.info(
                    f"Sender {sender.email} warmup stage: "
                    f"{sender.warmup_stage} -> {new_stage}"
                )
                sender.warmup_stage = new_stage
                self._persist_sender(sender)
