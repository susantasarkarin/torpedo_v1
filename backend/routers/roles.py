"""
Roles Router - Role & Permission Management API
================================================

Endpoints for managing roles and permissions.
Requires admin permissions.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from pymongo import MongoClient
import os

from rbac import (
    Permissions, require_permission, get_rbac_service,
    RBACService
)
from rbac.models import RoleCreate, RoleUpdate, RoleStatus
from rbac.permissions import ROLE_TEMPLATES, PermissionCategory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/roles", tags=["Roles & Permissions"])

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
settings_db = client["torpedo_settings"]


def get_rbac() -> RBACService:
    """Get RBAC service instance."""
    return get_rbac_service(settings_db)


# ========================================
# Role Endpoints
# ========================================

@router.get("/", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_READ)
async def list_roles(
    request: Request,
    include_inactive: bool = Query(False, description="Include inactive roles")
):
    """
    List all roles.
    Requires: admin.role.read permission.
    """
    rbac = get_rbac()
    roles = rbac.list_roles(include_inactive=include_inactive)
    
    return {
        "roles": [
            {
                "code": r.code,
                "name": r.name,
                "description": r.description,
                "permissions_count": len(r.permissions),
                "is_system_role": r.is_system_role,
                "status": r.status.value if isinstance(r.status, RoleStatus) else r.status
            }
            for r in roles
        ],
        "total": len(roles)
    }


@router.get("/templates", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_READ)
async def get_role_templates(request: Request):
    """
    Get predefined role templates for reference.
    Useful for creating new roles based on templates.
    """
    return {
        "templates": {
            code: {
                "name": template["name"],
                "description": template.get("description"),
                "permissions_count": len(template["permissions"])
            }
            for code, template in ROLE_TEMPLATES.items()
        }
    }


@router.get("/{role_code}", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_READ)
async def get_role(request: Request, role_code: str):
    """
    Get a specific role with all permissions.
    Requires: admin.role.read permission.
    """
    rbac = get_rbac()
    role = rbac.get_role(role_code)
    
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    # Group permissions by category
    permissions_by_category = {}
    for perm in role.permissions:
        parts = perm.split(".")
        category = parts[0] if parts else "other"
        if category not in permissions_by_category:
            permissions_by_category[category] = []
        permissions_by_category[category].append(perm)
    
    return {
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "permissions": role.permissions,
        "permissions_by_category": permissions_by_category,
        "is_system_role": role.is_system_role,
        "status": role.status.value if isinstance(role.status, RoleStatus) else role.status,
        "created_at": role.created_at,
        "updated_at": role.updated_at
    }


@router.post("/", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_CREATE)
async def create_role(request: Request, data: RoleCreate):
    """
    Create a new custom role.
    Requires: admin.role.create permission.
    """
    from rbac.decorators import get_user_email
    
    rbac = get_rbac()
    created_by = await get_user_email(request)
    
    try:
        role = rbac.create_role(data, created_by=created_by)
        
        return {
            "success": True,
            "message": "Role created successfully",
            "role": {
                "code": role.code,
                "name": role.name,
                "permissions_count": len(role.permissions)
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{role_code}", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_UPDATE)
async def update_role(request: Request, role_code: str, data: RoleUpdate):
    """
    Update an existing role.
    System roles can have limited modifications.
    Requires: admin.role.update permission.
    """
    rbac = get_rbac()
    
    role = rbac.update_role(role_code, data)
    
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    return {
        "success": True,
        "message": "Role updated successfully",
        "role": {
            "code": role.code,
            "name": role.name,
            "permissions_count": len(role.permissions),
            "status": role.status.value if isinstance(role.status, RoleStatus) else role.status
        }
    }


@router.delete("/{role_code}", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_DELETE)
async def delete_role(request: Request, role_code: str):
    """
    Delete a role.
    System roles are soft-deleted (deactivated).
    Custom roles are permanently deleted.
    Requires: admin.role.delete permission.
    """
    rbac = get_rbac()
    
    role = rbac.get_role(role_code)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    success = rbac.delete_role(role_code)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete role")
    
    action = "deactivated" if role.is_system_role else "deleted"
    return {
        "success": True,
        "message": f"Role {action} successfully"
    }


# ========================================
# Permission Endpoints
# ========================================

@router.get("/permissions/all", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_READ)
async def list_all_permissions(request: Request):
    """
    List all available permissions in the system.
    Grouped by category/module.
    """
    all_permissions = Permissions.all_permissions()
    
    # Group by category
    by_category = {}
    for perm in all_permissions:
        parts = perm.split(".")
        category = parts[0] if parts else "other"
        if category not in by_category:
            by_category[category] = []
        by_category[category].append({
            "code": perm,
            "entity": parts[1] if len(parts) > 1 else None,
            "action": parts[2] if len(parts) > 2 else None
        })
    
    return {
        "permissions": by_category,
        "categories": list(by_category.keys()),
        "total": len(all_permissions)
    }


@router.get("/permissions/by-category/{category}", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_READ)
async def get_permissions_by_category(request: Request, category: str):
    """
    Get all permissions for a specific category/module.
    Categories: finance, sales, ops, admin, system
    """
    try:
        perm_category = PermissionCategory(category.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Valid categories: {[c.value for c in PermissionCategory]}"
        )
    
    permissions = Permissions.by_category(perm_category)
    
    # Group by entity
    by_entity = {}
    for perm in permissions:
        parts = perm.split(".")
        entity = parts[1] if len(parts) > 1 else "general"
        if entity not in by_entity:
            by_entity[entity] = []
        by_entity[entity].append({
            "code": perm,
            "action": parts[2] if len(parts) > 2 else None
        })
    
    return {
        "category": category,
        "permissions": by_entity,
        "total": len(permissions)
    }


@router.get("/permissions/approval", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_READ)
async def get_approval_permissions(request: Request):
    """
    Get all approval-related permissions.
    Useful for configuring approval workflows.
    """
    approval_perms = Permissions.approval_permissions()
    
    return {
        "permissions": approval_perms,
        "description": "These permissions control who can approve various entities",
        "total": len(approval_perms)
    }


# ========================================
# Role Comparison
# ========================================

@router.get("/compare", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_READ)
async def compare_roles(
    request: Request,
    role1: str = Query(..., description="First role code"),
    role2: str = Query(..., description="Second role code")
):
    """
    Compare permissions between two roles.
    Shows shared, unique to each, and differences.
    """
    rbac = get_rbac()
    
    r1 = rbac.get_role(role1)
    r2 = rbac.get_role(role2)
    
    if not r1:
        raise HTTPException(status_code=404, detail=f"Role '{role1}' not found")
    if not r2:
        raise HTTPException(status_code=404, detail=f"Role '{role2}' not found")
    
    perms1 = set(r1.permissions)
    perms2 = set(r2.permissions)
    
    return {
        "role1": {
            "code": r1.code,
            "name": r1.name,
            "total_permissions": len(perms1)
        },
        "role2": {
            "code": r2.code,
            "name": r2.name,
            "total_permissions": len(perms2)
        },
        "comparison": {
            "shared": list(perms1 & perms2),
            "only_in_role1": list(perms1 - perms2),
            "only_in_role2": list(perms2 - perms1),
            "shared_count": len(perms1 & perms2),
            "difference_count": len(perms1 ^ perms2)
        }
    }


# ========================================
# System Initialization
# ========================================

@router.post("/initialize-system-roles", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_CREATE)
async def initialize_system_roles(request: Request):
    """
    Initialize or refresh system roles from templates.
    Safe to call multiple times (idempotent).
    """
    rbac = get_rbac()
    
    created = rbac.initialize_system_roles()
    
    return {
        "success": True,
        "message": f"System roles initialized. {created} new roles created.",
        "roles_created": created
    }
