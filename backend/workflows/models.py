# backend/workflows/models.py
# Pydantic models for the Approval Workflow Engine

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class ApprovalStatus(str, Enum):
    """Status of an approval request"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalActionType(str, Enum):
    """Types of actions that can be taken on an approval"""
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    COMMENT = "comment"
    DELEGATE = "delegate"
    REQUEST_INFO = "request_info"


class EscalationConfig(BaseModel):
    """Configuration for automatic escalation"""
    enabled: bool = False
    hours_until_escalation: int = Field(default=24, ge=1)
    escalation_role: Optional[str] = None  # Role to escalate to
    escalation_user_id: Optional[str] = None  # Specific user to escalate to
    max_escalations: int = Field(default=3, ge=1)
    notify_on_escalation: bool = True


class ApprovalRule(BaseModel):
    """Rule that defines when approval is required"""
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    
    # Trigger conditions
    entity_type: str  # e.g., "invoice", "purchase_order", "lead_conversion"
    action: str  # e.g., "create", "approve", "delete", "update"
    
    # Condition expression (MongoDB-style query on entity)
    # e.g., {"amount": {"$gte": 10000}} for invoices over $10k
    conditions: Dict[str, Any] = Field(default_factory=dict)
    
    # Who can approve
    approver_roles: List[str] = Field(default_factory=list)  # Roles that can approve
    approver_user_ids: List[str] = Field(default_factory=list)  # Specific users
    require_all_approvers: bool = False  # If true, all listed approvers must approve
    min_approvals: int = Field(default=1, ge=1)  # Minimum number of approvals needed
    
    # Escalation
    escalation: Optional[EscalationConfig] = None
    
    # Metadata
    priority: int = Field(default=0)  # Higher priority rules checked first
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None


class ApprovalRuleCreate(BaseModel):
    """Request model for creating an approval rule"""
    name: str
    description: Optional[str] = None
    entity_type: str
    action: str
    conditions: Dict[str, Any] = Field(default_factory=dict)
    approver_roles: List[str] = Field(default_factory=list)
    approver_user_ids: List[str] = Field(default_factory=list)
    require_all_approvers: bool = False
    min_approvals: int = Field(default=1, ge=1)
    escalation: Optional[EscalationConfig] = None
    priority: int = Field(default=0)


class ApprovalAction(BaseModel):
    """Record of an action taken on an approval request"""
    action_type: ApprovalActionType
    user_id: str
    user_name: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    comment: Optional[str] = None
    
    # For delegation
    delegated_to_user_id: Optional[str] = None
    delegated_to_role: Optional[str] = None
    
    # For escalation tracking
    escalation_level: int = 0


class ApprovalRequest(BaseModel):
    """An approval request for a specific action on an entity"""
    id: Optional[str] = None
    
    # Rule that triggered this request
    rule_id: str
    rule_name: Optional[str] = None
    
    # Entity being approved
    entity_type: str  # e.g., "invoice", "purchase_order"
    entity_id: str  # ID of the entity in its collection
    entity_summary: Optional[str] = None  # Human-readable summary
    entity_snapshot: Optional[Dict[str, Any]] = None  # Copy of entity at request time
    
    # The action being requested
    requested_action: str  # e.g., "approve", "create", "delete"
    
    # Status
    status: ApprovalStatus = ApprovalStatus.PENDING
    
    # Approvers
    required_approvers: List[str] = Field(default_factory=list)  # User IDs
    approved_by: List[str] = Field(default_factory=list)  # User IDs who approved
    rejected_by: Optional[str] = None  # User ID who rejected
    min_approvals_required: int = 1
    
    # Action history
    actions: List[ApprovalAction] = Field(default_factory=list)
    
    # Escalation tracking
    current_escalation_level: int = 0
    escalated_at: Optional[datetime] = None
    
    # Requester info
    requested_by: str  # User ID
    requested_by_name: Optional[str] = None
    request_reason: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    
    # Callbacks - what to do after approval
    on_approve_callback: Optional[str] = None  # Function path to call
    on_reject_callback: Optional[str] = None
    callback_data: Optional[Dict[str, Any]] = None


class ApprovalRequestCreate(BaseModel):
    """Request model for creating an approval request"""
    entity_type: str
    entity_id: str
    entity_summary: Optional[str] = None
    requested_action: str
    request_reason: Optional[str] = None
    # Optional - if not provided, engine will find matching rule
    rule_id: Optional[str] = None


class ApprovalRequestUpdate(BaseModel):
    """Request model for updating an approval request"""
    status: Optional[ApprovalStatus] = None
    entity_summary: Optional[str] = None
    expires_at: Optional[datetime] = None


class ApprovalDecision(BaseModel):
    """Request model for making an approval decision"""
    action: ApprovalActionType
    comment: Optional[str] = None
    delegated_to_user_id: Optional[str] = None


class ApprovalStats(BaseModel):
    """Statistics about approvals"""
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    escalated_count: int = 0
    expired_count: int = 0
    average_resolution_hours: float = 0.0
    by_entity_type: Dict[str, int] = Field(default_factory=dict)
    by_approver: Dict[str, int] = Field(default_factory=dict)
