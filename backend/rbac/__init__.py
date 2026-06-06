"""
RBAC (Role-Based Access Control) Module
========================================

Provides:
- Permission definitions per module (finance, sales, ops, admin)
- Role management with hierarchical permissions
- Decorator-based permission enforcement
- User-role assignment

Usage:
    from rbac import require_permission, Permissions
    
    @require_permission(Permissions.FINANCE_INVOICE_CREATE)
    async def create_invoice(...):
        ...
"""

from .permissions import Permissions, PermissionCategory
from .models import Role, Permission, UserRole, ApprovalAuthority
from .decorators import require_permission, require_any_permission, require_all_permissions
from .service import RBACService, get_rbac_service
from .simple import can, has_role, SIMPLE_ROLES

__all__ = [
    # Permissions
    "Permissions",
    "PermissionCategory",
    # Models
    "Role",
    "Permission",
    "UserRole",
    "ApprovalAuthority",
    # Decorators
    "require_permission",
    "require_any_permission",
    "require_all_permissions",
    # Service
    "RBACService",
    "get_rbac_service",
    # Simple coarse-grained helpers (folded in from the old root rbac.py stub)
    "can",
    "has_role",
    "SIMPLE_ROLES",
]
