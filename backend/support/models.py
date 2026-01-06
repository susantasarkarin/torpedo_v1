# backend/support/models.py
# Pydantic models for Support/Tickets Module

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    """Ticket status values"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_ON_CUSTOMER = "waiting_on_customer"
    WAITING_ON_THIRD_PARTY = "waiting_on_third_party"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"


class TicketPriority(str, Enum):
    """Ticket priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class TicketCategory(str, Enum):
    """Ticket category types"""
    QUESTION = "question"
    INCIDENT = "incident"
    PROBLEM = "problem"
    FEATURE_REQUEST = "feature_request"
    CHANGE_REQUEST = "change_request"
    BILLING = "billing"
    TECHNICAL = "technical"
    GENERAL = "general"


class TicketSource(str, Enum):
    """Ticket source channels"""
    EMAIL = "email"
    PHONE = "phone"
    WEB = "web"
    CHAT = "chat"
    API = "api"
    INTERNAL = "internal"


class EscalationLevel(str, Enum):
    """Escalation levels"""
    LEVEL_1 = "level_1"  # Front-line support
    LEVEL_2 = "level_2"  # Technical support
    LEVEL_3 = "level_3"  # Engineering
    LEVEL_4 = "level_4"  # Management


class SLAPolicy(BaseModel):
    """SLA Policy definition"""
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    
    # Response times by priority (in hours)
    response_time: Dict[str, float] = Field(default_factory=lambda: {
        "low": 24,
        "medium": 8,
        "high": 4,
        "urgent": 1,
        "critical": 0.25  # 15 minutes
    })
    
    # Resolution times by priority (in hours)
    resolution_time: Dict[str, float] = Field(default_factory=lambda: {
        "low": 168,  # 7 days
        "medium": 72,  # 3 days
        "high": 24,
        "urgent": 8,
        "critical": 4
    })
    
    # Business hours
    business_hours_only: bool = True
    business_hours_start: int = 9  # 9 AM
    business_hours_end: int = 17  # 5 PM
    business_days: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri
    
    # Is active
    is_active: bool = True
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class SLAStatus(BaseModel):
    """SLA status for a ticket"""
    response_due: Optional[datetime] = None
    resolution_due: Optional[datetime] = None
    first_response_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    
    response_breached: bool = False
    resolution_breached: bool = False
    
    response_time_remaining: Optional[float] = None  # hours
    resolution_time_remaining: Optional[float] = None  # hours


class TicketComment(BaseModel):
    """Ticket comment/reply"""
    id: Optional[str] = None
    ticket_id: str
    
    # Author
    author_id: str
    author_name: Optional[str] = None
    author_type: str = "agent"  # agent, customer, system
    
    # Content
    content: str
    is_internal: bool = False  # Internal notes not visible to customer
    
    # Attachments
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    
    # If this comment was via email
    email_message_id: Optional[str] = None


class TicketActivity(BaseModel):
    """Ticket activity log entry"""
    id: Optional[str] = None
    ticket_id: str
    
    # Activity
    action: str  # status_change, assignment, comment, escalation, sla_breach, etc.
    description: str
    
    # Actor
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    actor_type: str = "agent"  # agent, customer, system
    
    # Details
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Timestamp
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Ticket(BaseModel):
    """Ticket entity"""
    id: Optional[str] = None
    
    # Ticket number (human-readable)
    ticket_number: Optional[str] = None
    
    # Basic info
    subject: str
    description: str
    
    # Classification
    status: TicketStatus = TicketStatus.OPEN
    priority: TicketPriority = TicketPriority.MEDIUM
    category: TicketCategory = TicketCategory.GENERAL
    source: TicketSource = TicketSource.WEB
    
    # Assignment
    assigned_to: Optional[str] = None
    assigned_to_name: Optional[str] = None
    assigned_at: Optional[datetime] = None
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    
    # Escalation
    escalation_level: EscalationLevel = EscalationLevel.LEVEL_1
    escalated_at: Optional[datetime] = None
    escalated_by: Optional[str] = None
    
    # Customer/Contact
    contact_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    
    # Organization/Account
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    
    # Related entities
    related_tickets: List[str] = Field(default_factory=list)
    project_id: Optional[str] = None
    deal_id: Optional[str] = None
    
    # SLA
    sla_policy_id: Optional[str] = None
    sla_status: Optional[SLAStatus] = None
    
    # Tags
    tags: List[str] = Field(default_factory=list)
    
    # Resolution
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    
    # Satisfaction
    satisfaction_rating: Optional[int] = None  # 1-5
    satisfaction_comment: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    first_response_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    # Created by
    created_by: Optional[str] = None
    
    # Soft delete
    is_deleted: bool = False


class TicketCreate(BaseModel):
    """Request model for creating a ticket"""
    subject: str
    description: str
    priority: TicketPriority = TicketPriority.MEDIUM
    category: TicketCategory = TicketCategory.GENERAL
    source: TicketSource = TicketSource.WEB
    
    contact_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    
    account_id: Optional[str] = None
    assigned_to: Optional[str] = None
    team_id: Optional[str] = None
    
    project_id: Optional[str] = None
    deal_id: Optional[str] = None
    
    sla_policy_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class TicketUpdate(BaseModel):
    """Request model for updating a ticket"""
    subject: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    category: Optional[TicketCategory] = None
    assigned_to: Optional[str] = None
    team_id: Optional[str] = None
    tags: Optional[List[str]] = None


class TicketResolve(BaseModel):
    """Request model for resolving a ticket"""
    resolution: str
    close_ticket: bool = False


class TicketEscalate(BaseModel):
    """Request model for escalating a ticket"""
    level: EscalationLevel
    reason: str
    assign_to: Optional[str] = None


class TicketStats(BaseModel):
    """Ticket statistics"""
    total_tickets: int = 0
    open_tickets: int = 0
    in_progress_tickets: int = 0
    resolved_tickets: int = 0
    closed_tickets: int = 0
    
    overdue_tickets: int = 0
    sla_breached_count: int = 0
    
    avg_response_time_hours: float = 0
    avg_resolution_time_hours: float = 0
    
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_priority: Dict[str, int] = Field(default_factory=dict)
    by_category: Dict[str, int] = Field(default_factory=dict)
    
    satisfaction_avg: float = 0


class TeamQueue(BaseModel):
    """Support team queue configuration"""
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    
    # Team members
    member_ids: List[str] = Field(default_factory=list)
    manager_ids: List[str] = Field(default_factory=list)
    
    # Default SLA policy
    default_sla_policy_id: Optional[str] = None
    
    # Routing rules
    categories: List[str] = Field(default_factory=list)  # Categories handled by this team
    
    # Is active
    is_active: bool = True
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
