# backend/mcp/models.py
# Pydantic models for MCP Action Router

from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from enum import Enum
from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Types of actions the MCP can execute"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    REJECT = "reject"
    ASSIGN = "assign"
    CONVERT = "convert"
    SEND = "send"
    ARCHIVE = "archive"
    RESTORE = "restore"


class ActionStatus(str, Enum):
    """Status of an MCP action"""
    PENDING = "pending"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class ActionPriority(str, Enum):
    """Priority levels for actions"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class EntityType(str, Enum):
    """Entity types that can be acted upon"""
    INVOICE = "invoice"
    BILL = "bill"
    PAYMENT = "payment"
    EXPENSE = "expense"
    LEAD = "lead"
    CONTACT = "contact"
    DEAL = "deal"
    RFQ = "rfq"
    PROJECT = "project"
    TASK = "task"
    TICKET = "ticket"
    USER = "user"
    VENDOR = "vendor"
    CUSTOMER = "customer"


class ValidationResult(BaseModel):
    """Result of action validation"""
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    transformed_payload: Optional[Dict[str, Any]] = None


class ActionPayload(BaseModel):
    """Payload for an MCP action"""
    entity_type: EntityType
    action_type: ActionType
    entity_id: Optional[str] = None  # None for create operations
    data: Dict[str, Any] = Field(default_factory=dict)
    
    # Optional metadata
    reason: Optional[str] = None
    related_entities: List[Dict[str, str]] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class ActionResult(BaseModel):
    """Result of an executed action"""
    success: bool
    action_id: str
    entity_id: Optional[str] = None
    entity_type: EntityType
    action_type: ActionType
    
    # Result data
    result_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    
    # For rollback
    rollback_data: Optional[Dict[str, Any]] = None
    can_rollback: bool = False


class RollbackInfo(BaseModel):
    """Information needed to rollback an action"""
    action_id: str
    entity_type: EntityType
    entity_id: str
    action_type: ActionType
    
    # State before action
    previous_state: Optional[Dict[str, Any]] = None
    
    # For create actions - just need the ID to delete
    created_entity_id: Optional[str] = None
    
    # Rollback status
    is_rolled_back: bool = False
    rolled_back_at: Optional[datetime] = None
    rolled_back_by: Optional[str] = None


class MCPAction(BaseModel):
    """Complete MCP Action record"""
    id: Optional[str] = None
    
    # Action details
    payload: ActionPayload
    status: ActionStatus = ActionStatus.PENDING
    priority: ActionPriority = ActionPriority.NORMAL
    
    # Validation
    validation_result: Optional[ValidationResult] = None
    
    # Execution
    result: Optional[ActionResult] = None
    rollback_info: Optional[RollbackInfo] = None
    
    # Approval (if required)
    requires_approval: bool = False
    approval_request_id: Optional[str] = None
    
    # Dry run
    is_dry_run: bool = False
    dry_run_result: Optional[Dict[str, Any]] = None
    
    # User context
    initiated_by: str
    initiated_by_name: Optional[str] = None
    executed_by: Optional[str] = None  # May differ if approved by different user
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    validated_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Audit
    audit_log: List[Dict[str, Any]] = Field(default_factory=list)


class MCPActionCreate(BaseModel):
    """Request model for creating an MCP action"""
    entity_type: EntityType
    action_type: ActionType
    entity_id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None
    priority: ActionPriority = ActionPriority.NORMAL
    is_dry_run: bool = False
    skip_approval: bool = False  # Admin override


class MCPActionBatch(BaseModel):
    """Batch of actions to execute together"""
    actions: List[MCPActionCreate]
    atomic: bool = True  # If true, rollback all if any fails
    reason: Optional[str] = None


class DryRunResult(BaseModel):
    """Result of a dry run execution"""
    action_id: str
    would_succeed: bool
    predicted_result: Optional[Dict[str, Any]] = None
    validation_result: ValidationResult
    requires_approval: bool
    approval_rule: Optional[str] = None
    affected_entities: List[Dict[str, str]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
