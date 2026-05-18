"""
Auth Handler
============
Login, logout, and user-profile endpoints.
Extracted from main.py to keep the app entry-point lean.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Body, Request, Depends

try:
    from .auth import hash_password, verify_password, needs_rehash, migrate_user_password
except ImportError:
    from auth import hash_password, verify_password, needs_rehash, migrate_user_password

try:
    from .session_state import (
        serializer, SESSION_TTL_SECONDS, sessions,
        get_session_store_instance, verify_session,
    )
except ImportError:
    from session_state import (
        serializer, SESSION_TTL_SECONDS, sessions,
        get_session_store_instance, verify_session,
    )

try:
    from .database import get_database
except ImportError:
    from database import get_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

# ---------------------------------------------------------------------------
# Lazy collection accessor — avoids module-level DB call at import time
# ---------------------------------------------------------------------------
_users_collection = None


def _get_users_collection():
    global _users_collection
    if _users_collection is None:
        db = get_database("email_automation")
        _users_collection = db["users"]
    return _users_collection


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@router.post("/login/")
@router.post("/api/login/", include_in_schema=False)
async def login(credentials: Dict[str, str] = Body(...)):
    users_col = _get_users_collection()
    try:
        username = credentials.get("username")
        password = credentials.get("password")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")

        user = users_col.find_one({"username": username})
        if not user:
            logger.warning("Login failed: user '%s' not found", username)
            raise HTTPException(status_code=401, detail="Invalid username or password")

        stored_password = user.get("password", "")
        if not verify_password(password, stored_password):
            logger.warning("Login failed: bad password for '%s'", username)
            raise HTTPException(status_code=401, detail="Invalid username or password")

        if needs_rehash(stored_password):
            migrate_user_password(users_col, username, password)

        role = user.get("role", "admin")
        session_id = serializer.dumps(username)

        store = await get_session_store_instance()
        await store.create(session_id, {"username": username, "role": role}, SESSION_TTL_SECONDS)

        sessions[session_id] = {
            "username": username,
            "expires_at": datetime.utcnow() + timedelta(seconds=SESSION_TTL_SECONDS),
        }

        return {
            "message": "Login successful",
            "username": username,
            "session_id": session_id,
            "role": role,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login error: {str(e)}")


@router.post("/logout/")
@router.post("/api/logout/", include_in_schema=False)
async def logout(request: Request):
    session_id = request.headers.get("Authorization")
    if session_id:
        store = await get_session_store_instance()
        await store.delete(session_id)
        sessions.pop(session_id, None)
    return {"message": "Logged out successfully"}


# ---------------------------------------------------------------------------
# Profile endpoints
# ---------------------------------------------------------------------------

@router.get("/profile/", dependencies=[Depends(verify_session)])
@router.get("/api/profile/", include_in_schema=False, dependencies=[Depends(verify_session)])
async def get_profile(request: Request):
    """Get current user's profile (audit-safe fields only)."""
    users_col = _get_users_collection()
    try:
        session_id = request.headers.get("Authorization")
        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)
        user = users_col.find_one({"username": username})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "username": user.get("username", ""),
            "email": user.get("email", ""),
            "displayName": user.get("displayName", user.get("username", "")),
            "role": user.get("role", "admin"),
            "createdAt": user.get("createdAt", "").isoformat() if user.get("createdAt") else "",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile fetch error: {str(e)}")


@router.put("/profile/update", dependencies=[Depends(verify_session)])
@router.put("/api/profile/update", include_in_schema=False, dependencies=[Depends(verify_session)])
async def update_profile(request: Request, profile_data: Dict[str, Any] = Body(...)):
    """Update user profile (audit-safe fields: email, displayName)."""
    users_col = _get_users_collection()
    try:
        session_id = request.headers.get("Authorization")
        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)

        update_data: Dict[str, Any] = {}
        if "display_name" in profile_data:
            update_data["displayName"] = profile_data["display_name"]
        elif "displayName" in profile_data:
            update_data["displayName"] = profile_data["displayName"]
        if "email" in profile_data:
            update_data["email"] = profile_data["email"]

        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        update_data["updatedAt"] = datetime.utcnow()
        result = users_col.update_one({"username": username}, {"$set": update_data})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")
        return {"message": "Profile updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile update error: {str(e)}")


@router.put("/profile/change-password", dependencies=[Depends(verify_session)])
@router.put("/api/profile/change-password", include_in_schema=False, dependencies=[Depends(verify_session)])
async def change_password(request: Request, password_data: Dict[str, str] = Body(...)):
    """Change password (requires current password verification)."""
    users_col = _get_users_collection()
    try:
        session_id = request.headers.get("Authorization")
        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)

        current_password = password_data.get("current_password")
        new_password = password_data.get("new_password")

        if not current_password or not new_password:
            raise HTTPException(status_code=400, detail="Current and new password are required")
        if len(new_password) < 8:
            raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

        user = users_col.find_one({"username": username})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not verify_password(current_password, user.get("password", "")):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

        hashed = hash_password(new_password)
        result = users_col.update_one(
            {"username": username},
            {"$set": {"password": hashed, "password_updated_at": datetime.utcnow(), "updatedAt": datetime.utcnow()}},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")
        return {"message": "Password changed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Password change error: {str(e)}")
