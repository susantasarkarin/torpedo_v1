"""
AI COLD OUTREACH & RE-ENGAGEMENT MODULE - DATA MODELS
=====================================================

Comprehensive data models for AI-driven cold outreach, behavior tracking,
and intelligent re-engagement campaigns.

Collections:
- outreach_leads: Lead intelligence with engagement tracking
- outreach_sequences: Email sequence definitions
- outreach_emails: Individual email sends with tracking
- outreach_events: Email behavior events (opens, clicks, etc.)
- reengagement_pool: Leads for drip and re-engagement campaigns
- automation_rules: Deterministic automation rules
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from pydantic import BaseModel, Field
from bson import ObjectId


# ============== ENUMS ==============

class SeniorityLevel(str, Enum):
    """Seniority levels for B2B leads"""
    C_LEVEL = "C-Level"
    VP = "VP"
    DIRECTOR = "Director"
    MANAGER = "Manager"
    IC = "IC"
    UNKNOWN = "Unknown"


class Department(str, Enum):
    """Department/function"""
    SALES = "Sales"
    MARKETING = "Marketing"
    ENGINEERING = "Engineering"
    OPERATIONS = "Operations"
    FINANCE = "Finance"
    HR = "HR"
    PRODUCT = "Product"
    IT = "IT"
    PROCUREMENT = "Procurement"
    RESEARCH = "Research"
    OTHER = "Other"


class EmailStatus(str, Enum):
    """Email verification status"""
    VALID = "Valid"
    INVALID = "Invalid"
    CATCH_ALL = "Catch-All"
    RISKY = "Risky"
    UNKNOWN = "Unknown"


class SequenceStage(str, Enum):
    """Current stage in outreach sequence"""
    NOT_STARTED = "Not Started"
    EMAIL_1_SCHEDULED = "Email 1 - Scheduled"
    EMAIL_1_SENT = "Email 1 - Sent"
    EMAIL_2_SCHEDULED = "Email 2 - Scheduled"
    EMAIL_2_SENT = "Email 2 - Sent"
    EMAIL_3_SCHEDULED = "Email 3 - Scheduled"
    EMAIL_3_SENT = "Email 3 - Sent"
    EMAIL_4_SCHEDULED = "Email 4 - Scheduled"
    EMAIL_4_SENT = "Email 4 - Sent"
    SEQUENCE_COMPLETED = "Sequence Completed"
    SEQUENCE_STOPPED = "Sequence Stopped"


class EngagementStatus(str, Enum):
    """Lead engagement status"""
    NEVER_OPENED = "Never Opened"
    OPENED_NO_REPLY = "Opened - No Reply"
    ENGAGED = "Engaged"
    REPLIED_POSITIVE = "Replied - Positive"
    REPLIED_NEUTRAL = "Replied - Neutral"
    REPLIED_NEGATIVE = "Replied - Negative"
    UNSUBSCRIBED = "Unsubscribed"
    BOUNCED = "Bounced"
    WARM_LEAD = "Warm Lead"


class EmailEventType(str, Enum):
    """Email tracking event types"""
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    UNSUBSCRIBED = "unsubscribed"


class PersonalizationLevel(str, Enum):
    """Personalization intensity level"""
    LIGHT = "Light"  # Name, company, industry
    ROLE_BASED = "Role-Based"  # + Title, seniority, department, pain points
    DEEP = "Deep"  # + Company-specific context, triggers, insights


class ReengagementStage(str, Enum):
    """Re-engagement campaign stage"""
    NOT_IN_POOL = "Not in Pool"
    SOFT_DRIP_WEEK_3_4 = "Soft Drip (Week 3-4)"
    TRIGGER_BASED_MONTH_2 = "Trigger-Based (Month 2)"
    RESET_OUTREACH_MONTH_3_4 = "Reset Outreach (Month 3-4)"


class AutomationRuleType(str, Enum):
    """Types of automation rules"""
    EMAIL_BOUNCED = "email_bounced"
    REPLY_RECEIVED = "reply_received"
    WARM_LEAD_DETECTION = "warm_lead_detection"
    CADENCE_DOWNGRADE = "cadence_downgrade"


# ============== LEAD INTELLIGENCE MODEL ==============

class OutreachLead(BaseModel):
    """
    Lead intelligence for cold outreach campaigns.
    Collection: outreach_leads
    
    Indexes:
        - email (unique)
        - company
        - sequence_stage
        - engagement_status
        - last_contacted_at
    """
    # Identification
    id: Optional[str] = Field(default_factory=lambda: str(ObjectId()))
    
    # Personal Information
    first_name: str
    last_name: str
    email: str = Field(..., description="Primary contact email")
    title: Optional[str] = None
    
    # Company Information
    company: str
    seniority: Optional[SeniorityLevel] = None
    department: Optional[Department] = None
    industry: Optional[str] = None
    
    # Source & Metadata
    source: str = "manual"  # manual, csv, api, linkedin, etc.
    email_status: EmailStatus = EmailStatus.UNKNOWN
    
    # Personalization Intelligence
    pain_point: Optional[str] = None  # Key pain point to address
    use_case: Optional[str] = None  # Relevant use case
    value_proposition: Optional[str] = None  # Tailored value prop
    
    # Sequence Tracking
    last_contacted_at: Optional[datetime] = None
    sequence_stage: SequenceStage = SequenceStage.NOT_STARTED
    engagement_status: EngagementStatus = EngagementStatus.NEVER_OPENED
    
    # Sequence Assignment
    assigned_sequence_id: Optional[str] = None
    personalization_level: PersonalizationLevel = PersonalizationLevel.ROLE_BASED
    
    # Engagement Metrics
    emails_sent: int = 0
    emails_opened: int = 0
    emails_clicked: int = 0
    emails_replied: int = 0
    last_opened_at: Optional[datetime] = None
    last_clicked_at: Optional[datetime] = None
    last_replied_at: Optional[datetime] = None
    
    # Re-engagement Tracking
    reengagement_eligible: bool = False
    reengagement_stage: ReengagementStage = ReengagementStage.NOT_IN_POOL
    reengagement_enrolled_at: Optional[datetime] = None
    
    # Custom Fields
    custom_fields: Dict[str, Any] = Field(default_factory=dict)
    
    # Tags and Segmentation
    tags: List[str] = Field(default_factory=list)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== SEQUENCE DEFINITION MODEL ==============

class SequenceStep(BaseModel):
    """Individual step in an outreach sequence"""
    step_number: int  # 1, 2, 3, 4
    day_offset: int  # Days from sequence start (0, 4, 7, 12)
    name: str  # "Introduction", "Value Follow-Up", etc.
    description: str
    
    # Template
    template_id: str
    template_variant: Optional[str] = None  # For A/B testing
    
    # Conditions
    send_if_not_opened: bool = False
    send_if_not_clicked: bool = False
    send_if_not_replied: bool = True  # Default: only send if no reply
    
    # Behavior-based adjustments
    subject_variants: List[str] = Field(default_factory=list)
    cta_variants: List[str] = Field(default_factory=list)


class OutreachSequence(BaseModel):
    """
    Email sequence definition for cold outreach.
    Collection: outreach_sequences
    """
    # Identification
    id: Optional[str] = Field(default_factory=lambda: str(ObjectId()))
    name: str
    description: Optional[str] = None
    
    # Configuration
    duration_days: int = 14  # Default 14-18 days
    steps: List[SequenceStep] = Field(default_factory=list)
    
    # Targeting
    target_seniority: List[SeniorityLevel] = Field(default_factory=list)
    target_department: List[Department] = Field(default_factory=list)
    target_industries: List[str] = Field(default_factory=list)
    
    # Settings
    personalization_level: PersonalizationLevel = PersonalizationLevel.ROLE_BASED
    stop_on_reply: bool = True
    stop_on_bounce: bool = True
    stop_on_unsubscribe: bool = True
    
    # Deliverability
    daily_send_limit: int = 50
    cooldown_hours: int = 24  # Min hours between emails to same lead
    
    # Status
    is_active: bool = True
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== EMAIL SEND MODEL ==============

class OutreachEmail(BaseModel):
    """
    Individual email send record with tracking.
    Collection: outreach_emails
    
    Indexes:
        - lead_id
        - sequence_id
        - status
        - scheduled_send_at
        - sent_at
    """
    # Identification
    id: Optional[str] = Field(default_factory=lambda: str(ObjectId()))
    
    # Relationships
    lead_id: str
    sequence_id: str
    step_number: int
    
    # Email Details
    to_email: str
    subject: str  # Rendered with personalization
    body_html: str  # Rendered content
    body_plain: Optional[str] = None
    
    # Status
    status: str = "scheduled"  # scheduled, sent, delivered, failed
    
    # Scheduling
    scheduled_send_at: datetime
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    
    # Error Handling
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    
    # Provider Details
    provider: str = "smtp"  # smtp, sendgrid, mailgun, etc.
    provider_message_id: Optional[str] = None
    
    # Personalization Used
    personalization_data: Dict[str, str] = Field(default_factory=dict)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== EMAIL EVENT TRACKING MODEL ==============

class EmailEvent(BaseModel):
    """
    Email behavior tracking events.
    Collection: outreach_events
    
    Indexes:
        - email_id
        - lead_id
        - event_type
        - timestamp
    """
    # Identification
    id: Optional[str] = Field(default_factory=lambda: str(ObjectId()))
    
    # Relationships
    email_id: str
    lead_id: str
    sequence_id: str
    
    # Event Details
    event_type: EmailEventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Event Metadata
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    clicked_url: Optional[str] = None  # For click events
    bounce_reason: Optional[str] = None  # For bounce events
    reply_message_id: Optional[str] = None  # For reply events
    
    # Provider Data
    provider_event_id: Optional[str] = None
    raw_provider_data: Optional[Dict[str, Any]] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============== RE-ENGAGEMENT POOL MODEL ==============

class ReengagementLead(BaseModel):
    """
    Lead in re-engagement pool for drip campaigns.
    Collection: reengagement_pool
    
    Indexes:
        - lead_id (unique)
        - stage
        - enrolled_at
        - next_action_at
    """
    # Identification
    id: Optional[str] = Field(default_factory=lambda: str(ObjectId()))
    lead_id: str
    
    # Original Sequence Info
    original_sequence_id: str
    completed_sequence_at: datetime
    
    # Re-engagement Stage
    stage: ReengagementStage = ReengagementStage.SOFT_DRIP_WEEK_3_4
    enrolled_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Engagement During Original Sequence
    original_opens: int = 0
    original_clicks: int = 0
    last_activity_at: Optional[datetime] = None
    
    # Re-engagement Actions
    drip_emails_sent: int = 0
    last_drip_sent_at: Optional[datetime] = None
    next_action_at: Optional[datetime] = None
    
    # Trigger Detection
    detected_triggers: List[str] = Field(default_factory=list)  # job_change, company_growth, etc.
    trigger_detected_at: Optional[datetime] = None
    
    # Status
    is_active: bool = True
    converted_to_active: bool = False
    removed_reason: Optional[str] = None  # replied, unsubscribed, etc.
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== AUTOMATION RULES MODEL ==============

class AutomationRule(BaseModel):
    """
    Deterministic automation rule definition.
    Collection: automation_rules
    """
    # Identification
    id: Optional[str] = Field(default_factory=lambda: str(ObjectId()))
    name: str
    description: str
    rule_type: AutomationRuleType
    
    # Conditions (JSON-based rule engine)
    conditions: Dict[str, Any] = Field(default_factory=dict)
    # Example: {"email_bounced": True}
    # Example: {"opened_count": {"$gte": 2}, "replied": False}
    
    # Actions
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    # Example: [{"action": "mark_invalid", "field": "email_status", "value": "Invalid"}]
    # Example: [{"action": "stop_sequence"}, {"action": "update_status", "value": "Engaged"}]
    
    # Priority & Status
    priority: int = 10  # Lower = higher priority
    is_active: bool = True
    
    # Execution Tracking
    execution_count: int = 0
    last_executed_at: Optional[datetime] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== EMAIL TEMPLATE MODEL ==============

class EmailTemplate(BaseModel):
    """
    Email template with personalization tokens.
    Collection: outreach_templates
    """
    # Identification
    id: Optional[str] = Field(default_factory=lambda: str(ObjectId()))
    name: str
    description: Optional[str] = None
    
    # Template Content
    subject: str  # Supports {{tokens}}
    body_html: str  # Supports {{tokens}}
    body_plain: Optional[str] = None
    
    # Categorization
    category: str = "cold_outreach"  # cold_outreach, follow_up, reengagement, etc.
    step_type: Optional[str] = None  # introduction, value_followup, direct, final_touch
    
    # Personalization
    required_tokens: List[str] = Field(default_factory=list)
    # ["first_name", "company", "title", "pain_point", etc.]
    
    personalization_level: PersonalizationLevel = PersonalizationLevel.ROLE_BASED
    
    # Variants for A/B Testing
    variants: List[Dict[str, str]] = Field(default_factory=list)
    # [{"variant": "A", "subject": "...", "key_change": "shorter CTA"}]
    
    # Status
    is_active: bool = True
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== REQUEST/RESPONSE MODELS ==============

class LeadEnrollmentRequest(BaseModel):
    """Request to enroll leads in outreach sequence"""
    leads: List[OutreachLead]
    sequence_id: str
    personalization_level: Optional[PersonalizationLevel] = None
    start_immediately: bool = True


class LeadEnrollmentResponse(BaseModel):
    """Response from lead enrollment"""
    enrolled: int
    duplicates: int
    errors: int
    lead_ids: List[str]


class SequenceAnalyticsResponse(BaseModel):
    """Analytics for an outreach sequence"""
    sequence_id: str
    sequence_name: str
    
    # Counts
    total_leads: int
    emails_sent: int
    emails_delivered: int
    emails_opened: int
    emails_clicked: int
    emails_replied: int
    emails_bounced: int
    
    # Rates
    open_rate: float
    click_rate: float
    reply_rate: float
    positive_reply_rate: float
    bounce_rate: float
    
    # Re-engagement
    reengagement_eligible: int
    reengagement_converted: int
    reengagement_conversion_rate: float


class LeadStatusUpdate(BaseModel):
    """Update lead status manually"""
    lead_id: str
    engagement_status: Optional[EngagementStatus] = None
    sequence_stage: Optional[SequenceStage] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None


# ============== SUCCESS METRICS MODEL ==============

class SequenceMetrics(BaseModel):
    """Success metrics for tracking"""
    sequence_id: str
    date: datetime = Field(default_factory=datetime.utcnow)
    
    # Core Metrics
    open_rate: float = 0.0
    reply_rate: float = 0.0
    positive_reply_rate: float = 0.0
    bounce_rate: float = 0.0
    reengagement_conversion_rate: float = 0.0
    
    # Volume
    emails_sent: int = 0
    unique_opens: int = 0
    unique_clicks: int = 0
    replies: int = 0
    positive_replies: int = 0
    bounces: int = 0
    
    # Re-engagement
    entered_reengagement: int = 0
    converted_from_reengagement: int = 0
