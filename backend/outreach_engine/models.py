"""
ENTERPRISE OUTBOUND ENGINE - DATA MODELS
========================================

Core data models for the enterprise outbound email system.

Lead Model:
- Core identification and contact info
- Workflow state tracking
- Mailbox assignment (sticky)
- Thread continuity fields
- AI context block storage
- Engagement tracking

Mailbox Model:
- Health status and rate limiting
- Daily/hourly send counts
- Warmup status
- Dynamic signature

Campaign Model:
- Workflow definition
- Sequence steps
- Sending rules
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
from bson import ObjectId


# ============== ENUMS ==============

class WorkflowStatus(str, Enum):
    """Lead workflow status"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED_REPLY = "stopped_reply"
    STOPPED_BOUNCE = "stopped_bounce"
    STOPPED_UNSUBSCRIBE = "stopped_unsubscribe"
    STOPPED_MANUAL = "stopped_manual"


class PersonalizationLevel(str, Enum):
    """Personalization intensity level"""
    LIGHT = "light"            # Token replacement only
    MEDIUM = "medium"          # Token + AI context block
    HEAVY = "heavy"            # Token + AI context block + AI hook sentence


class MailboxHealth(str, Enum):
    """Mailbox health status"""
    HEALTHY = "healthy"
    WARMING = "warming"
    THROTTLED = "throttled"
    SUSPENDED = "suspended"
    PAUSED = "paused"


class SendStatus(str, Enum):
    """Individual email send status"""
    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    FAILED = "failed"


class BounceType(str, Enum):
    """Bounce classification"""
    HARD = "hard"
    SOFT = "soft"
    UNKNOWN = "unknown"


# ============== LEAD MODEL ==============

class Lead(BaseModel):
    """
    Lead model with all required fields for enterprise outbound.
    
    Collection: outreach_leads_v2
    
    Indexes:
        - lead_id (unique)
        - email (unique)
        - workflow_id + workflow_status
        - assigned_mailbox_id
        - next_send_at
    """
    # Core Identification
    lead_id: str = Field(default_factory=lambda: str(ObjectId()))
    email: str = Field(..., description="Primary contact email (unique)")
    first_name: str
    last_name: str
    company: str
    industry: Optional[str] = None
    title: Optional[str] = None
    
    # Workflow State
    workflow_id: Optional[str] = None
    campaign_id: Optional[str] = None
    current_step: int = 0
    workflow_status: WorkflowStatus = WorkflowStatus.NOT_STARTED
    
    # Mailbox Assignment (STICKY - never changes after first send)
    assigned_mailbox_id: Optional[str] = None
    
    # Thread Continuity
    thread_id: Optional[str] = None
    message_id_last_sent: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: List[str] = Field(default_factory=list)
    
    # AI Context (generated ONCE per lead per campaign, reused for follow-ups)
    ai_context_block: Optional[str] = None
    ai_context_generated_at: Optional[datetime] = None
    ai_tokens_used: int = 0
    
    # Personalization
    personalization_level: PersonalizationLevel = PersonalizationLevel.LIGHT
    custom_fields: Dict[str, Any] = Field(default_factory=dict)
    
    # Engagement Tracking
    last_sent_at: Optional[datetime] = None
    next_send_at: Optional[datetime] = None
    reply_status: Optional[str] = None  # 'positive', 'negative', 'neutral', None
    reply_detected_at: Optional[datetime] = None
    reply_email_id: Optional[str] = None
    bounce_status: Optional[BounceType] = None
    bounce_detected_at: Optional[datetime] = None
    unsubscribe_detected_at: Optional[datetime] = None
    
    # Email Metrics
    emails_sent: int = 0
    emails_opened: int = 0
    emails_clicked: int = 0
    last_opened_at: Optional[datetime] = None
    last_clicked_at: Optional[datetime] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    workflow_started_at: Optional[datetime] = None
    workflow_completed_at: Optional[datetime] = None
    
    # Tags
    tags: List[str] = Field(default_factory=list)
    source: str = "manual"


# ============== MAILBOX MODEL ==============

class Mailbox(BaseModel):
    """
    Mailbox configuration and health tracking.
    
    Collection: outreach_mailboxes
    
    Indexes:
        - mailbox_id (unique)
        - health_status
    """
    mailbox_id: str = Field(default_factory=lambda: str(ObjectId()))
    
    # Email Configuration
    email_address: str
    display_name: str
    reply_to: Optional[str] = None
    
    # Provider Configuration
    provider: str = "gmail"  # gmail, outlook, smtp
    credentials_id: Optional[str] = None  # Reference to secure credentials store
    
    # Signature (pulled dynamically from profile)
    signature_html: str = ""
    signature_plain: str = ""
    
    # Rate Limiting (reset daily/hourly)
    daily_send_count: int = 0
    hourly_send_count: int = 0
    daily_send_limit: int = 400
    hourly_send_limit: int = 60
    last_send_at: Optional[datetime] = None
    daily_reset_at: Optional[datetime] = None
    hourly_reset_at: Optional[datetime] = None
    
    # Health Tracking
    health_status: MailboxHealth = MailboxHealth.HEALTHY
    warmup_status: str = "complete"  # warmup, complete
    warmup_day: int = 0
    bounce_rate_24h: float = 0.0
    complaint_rate_24h: float = 0.0
    
    # Pause Controls
    paused_until: Optional[datetime] = None
    pause_reason: Optional[str] = None
    
    # Metadata
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== CAMPAIGN MODEL ==============

class WorkflowStep(BaseModel):
    """Single step in campaign workflow"""
    step_number: int
    template_id: str
    delay_days: int = 0
    delay_hours: int = 0
    subject_line: str
    stop_on_reply: bool = True
    stop_on_bounce: bool = True


class CampaignSettings(BaseModel):
    """Campaign sending settings"""
    # Rate limiting
    max_emails_per_day_per_inbox: int = 400
    max_emails_per_hour_per_inbox: int = 60
    min_send_interval_seconds: int = 60
    max_send_interval_seconds: int = 180
    
    # Timing
    send_days: List[int] = [0, 1, 2, 3, 4]  # Mon-Fri
    send_hours_start: int = 9   # 9 AM
    send_hours_end: int = 17    # 5:30 PM (17:30 = ~17)
    use_recipient_timezone: bool = True
    default_timezone: str = "America/New_York"
    
    # Safety
    bounce_rate_threshold: float = 0.05  # 5% - auto pause
    stop_on_reply: bool = True
    stop_on_unsubscribe: bool = True
    
    # Personalization
    default_personalization_level: PersonalizationLevel = PersonalizationLevel.LIGHT
    ai_token_limit_per_lead: int = 150


class Campaign(BaseModel):
    """
    Campaign definition with workflow steps.
    
    Collection: outreach_campaigns_v2
    """
    campaign_id: str = Field(default_factory=lambda: str(ObjectId()))
    name: str
    description: Optional[str] = None
    
    # Company/Brand
    company_brand: str = "surveyfieldwork"  # surveyfieldwork, cogentixresearch
    value_proposition: str = "Market research, consumer insights, ad testing, brand lift studies."
    
    # Workflow Steps
    workflow_steps: List[WorkflowStep] = Field(default_factory=list)
    
    # Mailbox Pool
    mailbox_ids: List[str] = Field(default_factory=list)
    
    # Settings
    settings: CampaignSettings = Field(default_factory=CampaignSettings)
    
    # Status
    status: str = "draft"  # draft, active, paused, completed, archived
    is_active: bool = False
    
    # Statistics
    total_leads: int = 0
    leads_in_progress: int = 0
    leads_completed: int = 0
    leads_replied: int = 0
    leads_bounced: int = 0
    total_emails_sent: int = 0
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Metadata
    created_by: str = ""
    tags: List[str] = Field(default_factory=list)


# ============== EMAIL SEND RECORD ==============

class EmailSend(BaseModel):
    """
    Individual email send record with full tracking.
    
    Collection: outreach_sends_v2
    
    Indexes:
        - campaign_id + lead_id
        - mailbox_id + sent_at
        - message_id (unique)
        - status
    """
    send_id: str = Field(default_factory=lambda: str(ObjectId()))
    
    # References
    campaign_id: str
    lead_id: str
    mailbox_id: str
    workflow_step: int
    template_id: str
    
    # Email Details (rendered)
    to_email: str
    from_email: str
    from_name: str
    subject: str
    body_html: str
    body_plain: str
    
    # Thread Continuity
    message_id: str  # Generated Message-ID for this email
    in_reply_to: Optional[str] = None  # Previous message_id for threading
    references: List[str] = Field(default_factory=list)  # All message_ids in thread
    thread_id: Optional[str] = None  # Provider-specific thread ID
    
    # Status
    status: SendStatus = SendStatus.SCHEDULED
    scheduled_at: datetime = Field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    
    # Tracking
    opened_at: Optional[datetime] = None
    open_count: int = 0
    clicked_at: Optional[datetime] = None
    click_count: int = 0
    clicked_links: List[str] = Field(default_factory=list)
    replied_at: Optional[datetime] = None
    
    # Errors
    bounced_at: Optional[datetime] = None
    bounce_type: Optional[BounceType] = None
    bounce_reason: Optional[str] = None
    failed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    
    # Personalization/AI Logging
    personalization_level: PersonalizationLevel = PersonalizationLevel.LIGHT
    ai_tokens_used: int = 0
    
    # Provider Response
    provider_message_id: Optional[str] = None
    provider_response: Optional[Dict[str, Any]] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============== SEND LOG ENTRY ==============

class SendLogEntry(BaseModel):
    """
    Detailed log entry per email send for observability.
    
    Collection: outreach_send_logs
    """
    log_id: str = Field(default_factory=lambda: str(ObjectId()))
    send_id: str
    campaign_id: str
    lead_id: str
    
    # Core Logging Fields
    personalization_level: PersonalizationLevel
    mailbox_used: str
    ai_tokens_used: int
    message_id: str
    thread_id: Optional[str]
    workflow_step: int
    
    # Result
    status: str  # sent, bounced, failed
    error_type: Optional[str] = None  # bounce, delivery_failure, api_error, mailbox_suspended
    error_message: Optional[str] = None
    
    # Performance
    render_time_ms: int = 0
    send_time_ms: int = 0
    
    # Timestamp
    logged_at: datetime = Field(default_factory=datetime.utcnow)


# ============== TEMPLATES ==============

class EmailTemplate(BaseModel):
    """
    Email template with token placeholders.
    
    Collection: outreach_templates_v2
    
    Tokens: {{first_name}}, {{company}}, {{industry}}, {{title}}, 
            {{ai_context_block}}, {{signature}}
    """
    template_id: str = Field(default_factory=lambda: str(ObjectId()))
    name: str
    description: Optional[str] = None
    
    # Content (with {{token}} placeholders)
    subject: str
    body_html: str
    body_plain: Optional[str] = None
    
    # Step Type
    step_type: str = "initial"  # initial, follow_up_1, follow_up_2, follow_up_3, breakup
    
    # Tokens used
    tokens: List[str] = Field(default_factory=list)
    
    # Metadata
    company_brand: str = "surveyfieldwork"
    category: str = "outreach"
    is_active: bool = True
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
