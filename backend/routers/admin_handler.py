"""
Admin Handler
=============
User management endpoints (admin-only).
Extracted from main.py to keep the app entry-point lean.
"""

import logging
from datetime import datetime
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Body, Request, Depends

from auth import hash_password

from session_state import serializer, SESSION_TTL_SECONDS, verify_session

from database import get_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

# ---------------------------------------------------------------------------
# Lazy collection accessor
# ---------------------------------------------------------------------------
_users_collection = None


def _get_users_collection():
    global _users_collection
    if _users_collection is None:
        db = get_database("email_automation")
        _users_collection = db["users"]
    return _users_collection


# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------
AVAILABLE_ROLES = {
    "admin": {
        "name": "Administrator",
        "description": "Full system access",
        "permissions": ["*"],
    },
    "manager": {
        "name": "Manager",
        "description": "Can manage campaigns, leads, and view reports",
        "permissions": ["campaigns.*", "leads.*", "reports.view", "analytics.view"],
    },
    "user": {
        "name": "Standard User",
        "description": "Can view and edit campaigns and leads",
        "permissions": ["campaigns.view", "campaigns.edit", "leads.view", "leads.edit"],
    },
    "viewer": {
        "name": "Viewer",
        "description": "Read-only access to campaigns and leads",
        "permissions": ["campaigns.view", "leads.view", "reports.view"],
    },
}


def check_admin_role(request: Request) -> str:
    """Verify user has admin role. Returns username if authorized."""
    users_col = _get_users_collection()
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)
        user = users_col.find_one({"username": username})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if user.get("role", "user") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        return username
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid session")


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@router.get("/admin/users/", dependencies=[Depends(verify_session)])
async def list_all_users(request: Request):
    users_col = _get_users_collection()
    check_admin_role(request)
    try:
        all_users = list(users_col.find({}, {"password": 0}))
        users_list = []
        for user in all_users:
            users_list.append({
                "id": str(user.get("_id", "")),
                "username": user.get("username", ""),
                "email": user.get("email", ""),
                "name": user.get("displayName", user.get("username", "")),
                "role": user.get("role", "user"),
                "roles": [user.get("role", "user")],
                "status": user.get("status", "active"),
                "createdAt": user.get("createdAt", "").isoformat() if user.get("createdAt") else "",
                "lastLogin": user.get("lastLogin", "").isoformat() if user.get("lastLogin") else "",
            })
        return {"users": users_list, "total": len(users_list)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch users: {str(e)}")


@router.get("/admin/users/{user_id}", dependencies=[Depends(verify_session)])
async def get_user_by_id(request: Request, user_id: str):
    users_col = _get_users_collection()
    check_admin_role(request)
    try:
        user = users_col.find_one({"_id": ObjectId(user_id)}, {"password": 0})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "id": str(user.get("_id", "")),
            "username": user.get("username", ""),
            "email": user.get("email", ""),
            "name": user.get("displayName", user.get("username", "")),
            "role": user.get("role", "user"),
            "roles": [user.get("role", "user")],
            "status": user.get("status", "active"),
            "createdAt": user.get("createdAt", "").isoformat() if user.get("createdAt") else "",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch user: {str(e)}")


@router.post("/admin/users/", dependencies=[Depends(verify_session)])
async def create_new_user(request: Request, user_data: Dict[str, Any] = Body(...)):
    users_col = _get_users_collection()
    admin_username = check_admin_role(request)
    try:
        username = user_data.get("username") or user_data.get("email")
        email = user_data.get("email", "")
        password = user_data.get("password")
        name = user_data.get("name", username)
        role = user_data.get("role", "user")

        if not username:
            raise HTTPException(status_code=400, detail="Username or email is required")
        if not password:
            raise HTTPException(status_code=400, detail="Password is required")
        if len(password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        if role not in AVAILABLE_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid role. Available roles: {list(AVAILABLE_ROLES.keys())}")

        if users_col.find_one({"username": username}):
            raise HTTPException(status_code=400, detail="Username already exists")

        new_user = {
            "username": username,
            "email": email,
            "displayName": name,
            "password": hash_password(password),
            "role": role,
            "status": "active",
            "createdAt": datetime.utcnow(),
            "createdBy": admin_username,
        }
        result = users_col.insert_one(new_user)
        logger.info("User '%s' created by admin '%s' with role '%s'", username, admin_username, role)
        return {
            "success": True,
            "message": f"User '{username}' created successfully",
            "user": {
                "id": str(result.inserted_id),
                "username": username,
                "email": email,
                "name": name,
                "role": role,
                "roles": [role],
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")


@router.put("/admin/users/{user_id}", dependencies=[Depends(verify_session)])
async def update_user_by_id(request: Request, user_id: str, user_data: Dict[str, Any] = Body(...)):
    users_col = _get_users_collection()
    admin_username = check_admin_role(request)
    try:
        user = users_col.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        update_doc: Dict[str, Any] = {"updatedAt": datetime.utcnow(), "updatedBy": admin_username}
        if "name" in user_data:
            update_doc["displayName"] = user_data["name"]
        if "email" in user_data:
            update_doc["email"] = user_data["email"]
        if "role" in user_data:
            role = user_data["role"]
            if role not in AVAILABLE_ROLES:
                raise HTTPException(status_code=400, detail=f"Invalid role. Available roles: {list(AVAILABLE_ROLES.keys())}")
            update_doc["role"] = role
        if "roles" in user_data and isinstance(user_data["roles"], list) and len(user_data["roles"]) > 0:
            role = user_data["roles"][0]
            if role in AVAILABLE_ROLES:
                update_doc["role"] = role
        if "status" in user_data:
            if user_data["status"] not in ["active", "inactive", "pending", "locked"]:
                raise HTTPException(status_code=400, detail="Invalid status")
            update_doc["status"] = user_data["status"]
        if "password" in user_data and user_data["password"]:
            if len(user_data["password"]) < 6:
                raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
            update_doc["password"] = hash_password(user_data["password"])

        result = users_col.update_one({"_id": ObjectId(user_id)}, {"$set": update_doc})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")

        logger.info("User '%s' updated by admin '%s'", user.get("username"), admin_username)
        return {
            "success": True,
            "message": "User updated successfully",
            "user": {
                "id": user_id,
                "username": user.get("username"),
                "role": update_doc.get("role", user.get("role")),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update user: {str(e)}")


@router.delete("/admin/users/{user_id}", dependencies=[Depends(verify_session)])
async def delete_user_by_id(request: Request, user_id: str):
    users_col = _get_users_collection()
    admin_username = check_admin_role(request)
    try:
        user = users_col.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.get("username") == admin_username:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")

        users_col.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"status": "inactive", "deletedAt": datetime.utcnow(), "deletedBy": admin_username}},
        )
        logger.info("User '%s' deactivated by admin '%s'", user.get("username"), admin_username)
        return {"success": True, "message": "User deactivated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete user: {str(e)}")


@router.get("/admin/roles/", dependencies=[Depends(verify_session)])
async def list_available_roles(request: Request):
    check_admin_role(request)
    roles_list = [
        {"code": code, "name": info["name"], "description": info["description"], "permissions": info["permissions"]}
        for code, info in AVAILABLE_ROLES.items()
    ]
    return {"roles": roles_list}


@router.put("/admin/users/{user_id}/role", dependencies=[Depends(verify_session)])
async def change_user_role(request: Request, user_id: str, role_data: Dict[str, str] = Body(...)):
    users_col = _get_users_collection()
    admin_username = check_admin_role(request)
    try:
        role = role_data.get("role")
        if not role or role not in AVAILABLE_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid role. Available roles: {list(AVAILABLE_ROLES.keys())}")

        user = users_col.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        users_col.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"role": role, "updatedAt": datetime.utcnow(), "roleChangedBy": admin_username}},
        )
        logger.info("User '%s' role changed to '%s' by admin '%s'", user.get("username"), role, admin_username)
        return {"success": True, "message": f"User role changed to '{role}'", "role": role}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to change role: {str(e)}")


@router.put("/admin/users/{user_id}/reset-password", dependencies=[Depends(verify_session)])
async def admin_reset_password(request: Request, user_id: str, password_data: Dict[str, str] = Body(...)):
    users_col = _get_users_collection()
    admin_username = check_admin_role(request)
    try:
        new_password = password_data.get("new_password")
        if not new_password:
            raise HTTPException(status_code=400, detail="New password is required")
        if len(new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

        user = users_col.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        users_col.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "password": hash_password(new_password),
                "password_updated_at": datetime.utcnow(),
                "passwordResetBy": admin_username,
            }},
        )
        logger.info("Password reset for user '%s' by admin '%s'", user.get("username"), admin_username)
        return {"success": True, "message": "Password reset successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset password: {str(e)}")
