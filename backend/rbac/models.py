"""
RBAC Pydantic Models
====================

Data models for roles, permissions, and user assignments.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class RoleStatus(str, Enum):
    """Role status."""
    ACTIVE = "active"
    INACTIVE = "inactive"


class UserStatus(str, Enum):
    """User account status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    LOCKED = "locked"


class Permission(BaseModel):
    """
    Individual permission definition.
    Stored in permissions collection for custom permissions.
    """
    code: str = Field(..., description="Permission code e.g. 'finance.invoice.create'")
    name: str = Field(..., description="Human-readable name")
    description: Optional[str] = None
    category: str = Field(..., description="Module category: finance, sales, ops, admin")
    is_system: bool = Field(default=False, description="System-defined, cannot be deleted")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_schema_extra = {
            "example": {
                "code": "finance.invoice.approve",
                "name": "Approve Invoices",
                "description": "Can approve invoices for sending",
                "category": "finance",
                "is_system": True
            }
        }


class Role(BaseModel):
    """
    Role definition with assigned permissions.
    """
    id: Optional[str] = Field(None, alias="_id")
    code: str = Field(..., description="Unique role code e.g. 'sales_manager'")
    name: str = Field(..., description="Display name")
    description: Optional[str] = None
    permissions: List[str] = Field(default_factory=list, description="List of permission codes")
    is_system_role: bool = Field(default=False, description="System role, cannot be deleted")
    status: RoleStatus = Field(default=RoleStatus.ACTIVE)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    
    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "code": "sales_manager",
                "name": "Sales Manager",
                "description": "Full sales access with team management",
                "permissions": [
                    "sales.lead.read",
                    "sales.lead.create",
                    "sales.lead.update",
                    "sales.rfq.close"
                ],
                "is_system_role": True,
                "status": "active"
            }
        }


class UserRole(BaseModel):
    """
    Assignment of a role to a user.
    Stored in user_roles collection.
    """
    id: Optional[str] = Field(None, alias="_id")
    user_id: str = Field(..., description="User ID")
    user_email: str = Field(..., description="User email for easy lookup")
    role_code: str = Field(..., description="Role code")
    assigned_at: datetime = Field(default_factory=datetime.utcnow)
    assigned_by: Optional[str] = None
    expires_at: Optional[datetime] = Field(None, description="Optional role expiration")
    is_active: bool = Field(default=True)
    
    class Config:
        populate_by_name = True


class ApprovalAuthority(BaseModel):
    """
    Defines approval thresholds and authorities for a user/role.
    """
    id: Optional[str] = Field(None, alias="_id")
    user_id: Optional[str] = Field(None, description="Specific user, or None for role-based")
    role_code: Optional[str] = Field(None, description="Role code, or None for user-specific")
    entity_type: str = Field(..., description="Entity type: invoice, bill, expense, rfq")
    max_amount: Optional[float] = Field(None, description="Max amount can approve, None = unlimited")
    currency: str = Field(default="USD")
    can_approve: bool = Field(default=True)
    can_reject: bool = Field(default=True)
    requires_reason: bool = Field(default=False, description="Require reason for approval/rejection")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "role_code": "finance_manager",
                "entity_type": "invoice",
                "max_amount": 50000,
                "currency": "USD",
                "can_approve": True,
                "requires_reason": False
            }
        }


class User(BaseModel):
    """
    User model for RBAC.
    Extends basic auth with role information.
    """
    id: Optional[str] = Field(None, alias="_id")
    email: str = Field(..., description="User email (unique)")
    name: str = Field(..., description="Display name")
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: UserStatus = Field(default=UserStatus.ACTIVE)
    roles: List[str] = Field(default_factory=list, description="Assigned role codes")
    permissions_override: List[str] = Field(
        default_factory=list, 
        description="Direct permissions (in addition to roles)"
    )
    permissions_denied: List[str] = Field(
        default_factory=list,
        description="Explicitly denied permissions (overrides roles)"
    )
    department: Optional[str] = None
    manager_id: Optional[str] = None
    territory: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    
    class Config:
        populate_by_name = True


# ========================================
# Request/Response Models
# ========================================

class RoleCreate(BaseModel):
    """Request model for creating a role."""
    code: str
    name: str
    description: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    """Request model for updating a role."""
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None
    status: Optional[RoleStatus] = None


class UserCreate(BaseModel):
    """Request model for creating a user."""
    email: str
    name: str
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    department: Optional[str] = None
    manager_id: Optional[str] = None


class UserUpdate(BaseModel):
    """Request model for updating a user."""
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: Optional[UserStatus] = None
    roles: Optional[List[str]] = None
    department: Optional[str] = None
    manager_id: Optional[str] = None


class AssignRoleRequest(BaseModel):
    """Request to assign role to user."""
    user_id: str
    role_code: str
    expires_at: Optional[datetime] = None


class PermissionCheckResult(BaseModel):
    """Result of permission check."""
    allowed: bool
    permission: str
    user_id: str
    reason: Optional[str] = None
    checked_at: datetime = Field(default_factory=datetime.utcnow)
