"""
Guardrails Service.

Enforces safety constraints and risk management across the outreach system.
"""

import logging
from typing import Optional, Tuple
from pydantic import BaseModel, Field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration Models
# =============================================================================

class OutreachLimits(BaseModel):
    """Configurable limits for outreach operations."""
    
    # Sender limits
    max_daily_emails_per_sender: int = 50
    max_hourly_emails_per_sender: int = 10
    
    # Lead limits
    min_lead_score: int = 60
    max_emails_per_lead: int = 4  # Initial + 3 follow-ups
    min_days_between_emails: int = 3
    max_leads_per_company: int = 3
    
    # Health thresholds
    max_bounce_rate: float = 0.05
    max_complaint_rate: float = 0.001
    min_sender_health: float = 70.0
    
    # Campaign limits
    max_daily_total_sends: int = 500
    max_concurrent_campaigns: int = 10
    
    # Reply handling
    auto_response_confidence_threshold: float = 0.7
    
    # Time restrictions
    send_start_hour: int = 8  # 8 AM
    send_end_hour: int = 18   # 6 PM
    blocked_days: list[int] = Field(default_factory=lambda: [5, 6])  # Sat, Sun


class RiskLevel(BaseModel):
    """Risk assessment result."""
    level: str = Field(..., pattern="^(low|medium|high|critical)$")
    score: int = Field(..., ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    should_proceed: bool = True


# =============================================================================
# Service Implementation
# =============================================================================

class GuardrailsService:
    """
    Service for enforcing safety constraints and risk management.
    
    CRITICAL: AI handles intelligence, System handles constraints.
    This service is the constraint layer.
    
    Never allows:
    - AI to decide send volume
    - AI to override risk thresholds
    - AI to exceed sender limits
    - AI to send without lead_score check
    - AI to ignore bounce/complaint signals
    """
    
    def __init__(self, limits: Optional[OutreachLimits] = None):
        """
        Initialize with configurable limits.
        
        Args:
            limits: Custom limits or defaults
        """
        self.limits = limits or OutreachLimits()
        self._daily_send_count = 0
        self._hourly_send_counts: dict[str, int] = {}  # sender_id -> count
    
    # =========================================================================
    # Sender Checks
    # =========================================================================
    
    def can_sender_send(
        self,
        sender_id: str,
        sender_daily_count: int,
        sender_hourly_count: int,
        sender_bounce_rate: float,
        sender_complaint_rate: float,
        sender_health_score: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a sender can send an email.
        
        Returns:
            Tuple of (can_send, reason_if_not)
        """
        # Daily limit
        if sender_daily_count >= self.limits.max_daily_emails_per_sender:
            return False, f"Daily limit reached ({self.limits.max_daily_emails_per_sender})"
        
        # Hourly limit
        if sender_hourly_count >= self.limits.max_hourly_emails_per_sender:
            return False, f"Hourly limit reached ({self.limits.max_hourly_emails_per_sender})"
        
        # Bounce rate
        if sender_bounce_rate >= self.limits.max_bounce_rate:
            logger.warning(f"Sender {sender_id} blocked: bounce rate {sender_bounce_rate:.2%}")
            return False, f"Bounce rate too high ({sender_bounce_rate:.2%})"
        
        # Complaint rate - CRITICAL
        if sender_complaint_rate >= self.limits.max_complaint_rate:
            logger.critical(f"Sender {sender_id} BLOCKED: complaint rate {sender_complaint_rate:.4%}")
            return False, f"CRITICAL: Complaint rate exceeded ({sender_complaint_rate:.4%})"
        
        # Health score
        if sender_health_score < self.limits.min_sender_health:
            return False, f"Sender health too low ({sender_health_score:.0f})"
        
        return True, None
    
    # =========================================================================
    # Lead Checks
    # =========================================================================
    
    def can_outreach_lead(
        self,
        lead_score: int,
        previous_emails_sent: int,
        last_email_date: Optional[datetime],
        has_replied: bool = False,
        has_unsubscribed: bool = False,
        has_complained: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if outreach to a lead is allowed.
        
        Returns:
            Tuple of (can_outreach, reason_if_not)
        """
        # Hard stops
        if has_complained:
            return False, "Lead has filed a complaint - PERMANENTLY BLOCKED"
        
        if has_unsubscribed:
            return False, "Lead has unsubscribed"
        
        if has_replied:
            return False, "Lead has replied - sequence should stop"
        
        # Lead score
        if lead_score < self.limits.min_lead_score:
            return False, f"Lead score {lead_score} below threshold {self.limits.min_lead_score}"
        
        # Email count
        if previous_emails_sent >= self.limits.max_emails_per_lead:
            return False, f"Maximum emails ({self.limits.max_emails_per_lead}) already sent"
        
        # Time between emails
        if last_email_date:
            days_since = (datetime.utcnow() - last_email_date).days
            if days_since < self.limits.min_days_between_emails:
                return False, f"Only {days_since} days since last email (min: {self.limits.min_days_between_emails})"
        
        return True, None
    
    # =========================================================================
    # Time Checks
    # =========================================================================
    
    def is_valid_send_time(
        self,
        send_time: Optional[datetime] = None,
        recipient_timezone: str = "UTC"
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if current time is valid for sending.
        
        Returns:
            Tuple of (is_valid, reason_if_not)
        """
        check_time = send_time or datetime.utcnow()
        
        # Check day of week
        if check_time.weekday() in self.limits.blocked_days:
            return False, f"Sending blocked on day {check_time.weekday()}"
        
        # Check hour (simplified, should use recipient timezone)
        if not (self.limits.send_start_hour <= check_time.hour < self.limits.send_end_hour):
            return False, f"Outside sending hours ({self.limits.send_start_hour}-{self.limits.send_end_hour})"
        
        return True, None
    
    # =========================================================================
    # Campaign Checks
    # =========================================================================
    
    def can_start_campaign(
        self,
        active_campaign_count: int,
        daily_sends_today: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a new campaign can be started.
        
        Returns:
            Tuple of (can_start, reason_if_not)
        """
        if active_campaign_count >= self.limits.max_concurrent_campaigns:
            return False, f"Maximum concurrent campaigns ({self.limits.max_concurrent_campaigns}) reached"
        
        if daily_sends_today >= self.limits.max_daily_total_sends:
            return False, f"Daily send limit ({self.limits.max_daily_total_sends}) reached"
        
        return True, None
    
    # =========================================================================
    # Reply Risk Checks
    # =========================================================================
    
    def check_reply_risk(
        self,
        classification: str,
        confidence: float
    ) -> Tuple[bool, str, str]:
        """
        Check if a reply indicates risk requiring action.
        
        Returns:
            Tuple of (is_risk, risk_level, action_required)
        """
        # Critical risks - immediate halt
        critical_classifications = ["Legal Warning", "Spam Complaint Risk"]
        if classification in critical_classifications:
            return True, "critical", "HALT ALL AUTOMATION - MANUAL REVIEW REQUIRED"
        
        # High risk - remove from sequence
        high_risk_classifications = ["Not Interested"]
        if classification in high_risk_classifications and confidence > 0.8:
            return True, "high", "Remove from sequence, no further contact"
        
        # Medium risk - flag for review
        if confidence < 0.6:
            return True, "medium", "Low confidence classification - human review recommended"
        
        return False, "low", "No risk detected"
    
    # =========================================================================
    # Comprehensive Risk Assessment
    # =========================================================================
    
    def assess_send_risk(
        self,
        sender_id: str,
        sender_bounce_rate: float,
        sender_complaint_rate: float,
        sender_health_score: float,
        lead_score: int,
        email_spam_score: int,
        is_first_email: bool
    ) -> RiskLevel:
        """
        Comprehensive risk assessment for sending an email.
        
        Returns:
            RiskLevel with score and recommendations
        """
        risk_score = 0
        reasons = []
        recommendations = []
        
        # Sender risks
        if sender_bounce_rate > 0.03:
            risk_score += 20
            reasons.append(f"Elevated bounce rate: {sender_bounce_rate:.2%}")
            recommendations.append("Monitor sender closely")
        
        if sender_complaint_rate > 0:
            risk_score += 40
            reasons.append(f"Has complaints: {sender_complaint_rate:.4%}")
            recommendations.append("Consider sender rotation")
        
        if sender_health_score < 80:
            risk_score += 15
            reasons.append(f"Below optimal health: {sender_health_score:.0f}")
        
        # Lead risks
        if lead_score < 70:
            risk_score += 15
            reasons.append(f"Low lead score: {lead_score}")
            recommendations.append("Consider skipping low-quality leads")
        
        # Email risks
        if email_spam_score > 20:
            risk_score += email_spam_score // 2
            reasons.append(f"Spam score concerns: {email_spam_score}")
            recommendations.append("Review and revise email content")
        
        # Determine risk level
        if risk_score >= 60:
            level = "critical"
            should_proceed = False
        elif risk_score >= 40:
            level = "high"
            should_proceed = False
        elif risk_score >= 20:
            level = "medium"
            should_proceed = True
        else:
            level = "low"
            should_proceed = True
        
        return RiskLevel(
            level=level,
            score=risk_score,
            reasons=reasons,
            recommendations=recommendations,
            should_proceed=should_proceed
        )
    
    # =========================================================================
    # Auto-Response Guards
    # =========================================================================
    
    def can_auto_respond(
        self,
        classification: str,
        confidence: float,
        has_been_reviewed: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if auto-response should be sent.
        
        Returns:
            Tuple of (can_respond, reason_if_not)
        """
        # Never auto-respond to these
        blocked = ["Legal Warning", "Spam Complaint Risk", "Not Interested", "Unclear"]
        if classification in blocked:
            return False, f"Auto-response blocked for classification: {classification}"
        
        # Confidence check
        if confidence < self.limits.auto_response_confidence_threshold:
            if not has_been_reviewed:
                return False, f"Confidence {confidence:.2f} below threshold, needs review"
        
        return True, None
    
    # =========================================================================
    # Daily Tracking
    # =========================================================================
    
    def record_send(self) -> None:
        """Record a sent email for daily tracking."""
        self._daily_send_count += 1
    
    def check_daily_limit(self) -> Tuple[bool, int]:
        """
        Check if daily limit is reached.
        
        Returns:
            Tuple of (limit_reached, remaining_count)
        """
        remaining = self.limits.max_daily_total_sends - self._daily_send_count
        return remaining <= 0, max(0, remaining)
    
    def reset_daily_counts(self) -> None:
        """Reset daily counters (call at midnight)."""
        self._daily_send_count = 0
        self._hourly_send_counts.clear()
        logger.info("Daily guardrail counters reset")
