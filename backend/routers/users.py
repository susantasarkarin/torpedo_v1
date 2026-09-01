"""
Users Router - User Management API
===================================

Endpoints for user CRUD operations.
Requires admin permissions for most operations.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Request, Depends
from pydantic import BaseModel, Field, EmailStr
from pymongo import MongoClient
from bson import ObjectId
import os

from rbac import (
    Permissions, require_permission, get_rbac_service,
    RBACService
)
from rbac.models import (
    User, UserCreate, UserUpdate, UserStatus,
    AssignRoleRequest
)

def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
client = _get_pooled_client()
settings_db = client["torpedo_settings"]


def get_rbac() -> RBACService:
    """Get RBAC service instance."""
    return get_rbac_service(settings_db)


# ========================================
# Response Models
# ========================================

class UserResponse(BaseModel):
    """User response model (without sensitive data)."""
    id: str
    email: str
    name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: str
    roles: List[str]
    department: Optional[str] = None
    created_at: datetime
    last_login: Optional[datetime] = None


class UserListResponse(BaseModel):
    """Paginated user list response."""
    users: List[UserResponse]
    total: int
    page: int
    page_size: int


# ========================================
# Endpoints
# ========================================

@router.get("/", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_USER_READ)
async def list_users(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status"),
    role: Optional[str] = Query(None, description="Filter by role"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100)
):
    """
    List all users with optional filters.
    Requires: admin.user.read permission.
    """
    rbac = get_rbac()
    
    # Build query
    query = {}
    if status:
        query["status"] = status
    if role:
        query["roles"] = role
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}}
        ]
    
    # Get total count
    total = rbac.users.count_documents(query)
    
    # Get paginated results
    skip = (page - 1) * page_size
    docs = list(
        rbac.users.find(query)
        .sort("name", 1)
        .skip(skip)
        .limit(page_size)
    )
    
    users = []
    for doc in docs:
        users.append({
            "id": str(doc["_id"]),
            "email": doc.get("email"),
            "name": doc.get("name"),
            "first_name": doc.get("first_name"),
            "last_name": doc.get("last_name"),
            "status": doc.get("status"),
            "roles": doc.get("roles", []),
            "department": doc.get("department"),
            "created_at": doc.get("created_at"),
            "last_login": doc.get("last_login")
        })
    
    return {
        "users": users,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.get("/me", response_model=Dict[str, Any])
async def get_current_user_profile(request: Request):
    """
    Get current authenticated user's profile.
    No special permission required - users can view their own profile.
    """
    from rbac.decorators import get_current_user, get_user_permissions
    
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    permissions = await get_user_permissions(user)
    
    return {
        "id": user.get("id") or str(user.get("_id", "")),
        "email": user.get("email"),
        "name": user.get("name"),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "status": user.get("status"),
        "roles": user.get("roles", []),
        "permissions": list(permissions),
        "department": user.get("department"),
        "last_login": user.get("last_login")
    }


@router.get("/{user_id}", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_USER_READ)
async def get_user(request: Request, user_id: str):
    """
    Get a specific user by ID.
    Requires: admin.user.read permission.
    """
    rbac = get_rbac()
    user = rbac.get_user(user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "status": user.status.value if isinstance(user.status, UserStatus) else user.status,
        "roles": user.roles,
        "permissions_override": user.permissions_override,
        "permissions_denied": user.permissions_denied,
        "department": user.department,
        "manager_id": user.manager_id,
        "territory": user.territory,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "last_login": user.last_login
    }


@router.post("/", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_USER_CREATE)
async def create_user(request: Request, data: UserCreate):
    """
    Create a new user.
    Requires: admin.user.create permission.
    """
    from rbac.decorators import get_user_email
    
    rbac = get_rbac()
    created_by = await get_user_email(request)
    
    try:
        user = rbac.create_user(data, created_by=created_by)
        
        return {
            "success": True,
            "message": "User created successfully",
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "roles": user.roles
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")


@router.put("/{user_id}", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_USER_UPDATE)
async def update_user(request: Request, user_id: str, data: UserUpdate):
    """
    Update an existing user.
    Requires: admin.user.update permission.
    """
    from rbac.decorators import get_user_email
    
    rbac = get_rbac()
    updated_by = await get_user_email(request)
    
    user = rbac.update_user(user_id, data, updated_by=updated_by)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "success": True,
        "message": "User updated successfully",
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "status": user.status.value if isinstance(user.status, UserStatus) else user.status,
            "roles": user.roles
        }
    }


@router.delete("/{user_id}", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_USER_DELETE)
async def delete_user(request: Request, user_id: str):
    """
    Deactivate a user (soft delete).
    Requires: admin.user.delete permission.
    """
    rbac = get_rbac()
    
    # Get user first
    user = rbac.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Prevent deleting yourself
    from rbac.decorators import get_user_id
    current_user_id = await get_user_id(request)
    if current_user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    success = rbac.deactivate_user(user_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to deactivate user")
    
    return {
        "success": True,
        "message": "User deactivated successfully"
    }


@router.post("/{user_id}/roles", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_ASSIGN)
async def assign_role_to_user(request: Request, user_id: str, data: AssignRoleRequest):
    """
    Assign a role to a user.
    Requires: admin.role.assign permission.
    """
    from rbac.decorators import get_user_email
    
    rbac = get_rbac()
    assigned_by = await get_user_email(request)
    
    try:
        success = rbac.assign_role(user_id, data.role_code, assigned_by=assigned_by)
        
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "success": True,
            "message": f"Role '{data.role_code}' assigned to user"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{user_id}/roles/{role_code}", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_ASSIGN)
async def revoke_role_from_user(request: Request, user_id: str, role_code: str):
    """
    Revoke a role from a user.
    Requires: admin.role.assign permission.
    """
    rbac = get_rbac()
    
    success = rbac.revoke_role(user_id, role_code)
    
    if not success:
        raise HTTPException(status_code=404, detail="User or role assignment not found")
    
    return {
        "success": True,
        "message": f"Role '{role_code}' revoked from user"
    }


@router.get("/{user_id}/permissions", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_USER_READ)
async def get_user_permissions_endpoint(request: Request, user_id: str):
    """
    Get all effective permissions for a user.
    Combines role permissions with direct assignments.
    """
    rbac = get_rbac()
    
    user = rbac.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    permissions = rbac.get_user_permissions(user_id)
    
    # Group by category
    by_category = {}
    for perm in permissions:
        parts = perm.split(".")
        category = parts[0] if parts else "other"
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(perm)
    
    return {
        "user_id": user_id,
        "email": user.email,
        "roles": user.roles,
        "permissions": list(permissions),
        "by_category": by_category,
        "total_count": len(permissions)
    }


@router.post("/{user_id}/permissions", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_ASSIGN)
async def add_direct_permission(
    request: Request,
    user_id: str,
    permission: str = Query(..., description="Permission code to add")
):
    """
    Add a direct permission to a user (bypassing roles).
    """
    rbac = get_rbac()
    
    result = rbac.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$addToSet": {"permissions_override": permission},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "success": True,
        "message": f"Permission '{permission}' added to user"
    }


@router.delete("/{user_id}/permissions/{permission}", response_model=Dict[str, Any])
@require_permission(Permissions.ADMIN_ROLE_ASSIGN)
async def remove_direct_permission(request: Request, user_id: str, permission: str):
    """
    Remove a direct permission from a user.
    """
    rbac = get_rbac()
    
    result = rbac.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$pull": {"permissions_override": permission},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "success": True,
        "message": f"Permission '{permission}' removed from user"
    }
