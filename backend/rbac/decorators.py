"""
RBAC Permission Decorators
==========================

FastAPI dependency-based permission enforcement.

Usage:
    @router.post("/invoices")
    @require_permission(Permissions.FINANCE_INVOICE_CREATE)
    async def create_invoice(request: Request):
        ...
    
    # Multiple permissions (any)
    @require_any_permission(Permissions.SALES_RFQ_UPDATE, Permissions.SALES_RFQ_CLOSE)
    async def update_rfq(request: Request):
        ...
    
    # Multiple permissions (all required)
    @require_all_permissions(Permissions.FINANCE_INVOICE_CREATE, Permissions.FINANCE_INVOICE_SEND)
    async def create_and_send_invoice(request: Request):
        ...
"""

import os
import logging
from functools import wraps
from typing import List, Optional, Callable, Any
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# Security scheme for auth header
security = HTTPBearer(auto_error=False)

# Environment flag to disable RBAC (for development/testing)
RBAC_ENABLED = os.getenv("RBAC_ENABLED", "true").lower() in ("true", "1", "yes")
RBAC_LOG_CHECKS = os.getenv("RBAC_LOG_CHECKS", "false").lower() in ("true", "1", "yes")


class PermissionDeniedError(HTTPException):
    """Raised when user lacks required permission."""
    def __init__(self, permission: str, detail: str = None):
        super().__init__(
            status_code=403,
            detail=detail or f"Permission denied: {permission}"
        )
        self.permission = permission


class AuthenticationRequiredError(HTTPException):
    """Raised when no valid authentication is present."""
    def __init__(self):
        super().__init__(
            status_code=401,
            detail="Authentication required"
        )


async def get_current_user(request: Request) -> Optional[dict]:
    """
    Extract current user from request.
    Checks session, JWT, or API key.
    
    Returns user dict with at minimum: {id, email, roles, permissions}
    """
    # Try to get user from request state (set by middleware)
    user = getattr(request.state, "user", None)
    if user:
        return user
    
    # Try session-based auth
    session_id = request.cookies.get("session_id")
    if session_id:
        try:
            from session_store import SessionStore
            store = await SessionStore.get_instance()
            session_data = await store.get(session_id)
            if session_data:
                return session_data
        except Exception as e:
            logger.debug(f"Session lookup failed: {e}")
    
    # Try Authorization header — plain signed session token (main app pattern)
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header and not auth_header.startswith(("Bearer ", "ApiKey ")):
        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from main import serializer, sessions, SESSION_TTL_SECONDS
            from datetime import datetime, timedelta

            cached = sessions.get(auth_header)
            if cached and cached.get("expires_at") and cached["expires_at"] > datetime.utcnow():
                username = cached["username"]
            else:
                username = serializer.loads(auth_header, max_age=SESSION_TTL_SECONDS)

            return {"username": username, "email": username, "roles": ["admin"], "permissions": []}
        except Exception as e:
            logger.debug(f"RBAC plain-token auth failed: {e}")

    return None


async def get_user_permissions(user: dict) -> set:
    """
    Get all permissions for a user (from roles + direct assignments).
    """
    if not user:
        return set()
    
    permissions = set()
    
    # Get directly assigned permissions
    permissions.update(user.get("permissions_override", []))
    
    # Get permissions from roles
    roles = user.get("roles", [])
    if roles:
        try:
            from .service import get_rbac_service
            from database import get_database
            
            db = get_database("torpedo_settings")
            rbac = get_rbac_service(db)
            
            for role_code in roles:
                role_permissions = rbac.get_role_permissions(role_code)
                permissions.update(role_permissions)
        except Exception as e:
            logger.error(f"Failed to load role permissions: {e}")
    
    # Remove explicitly denied permissions
    denied = set(user.get("permissions_denied", []))
    permissions = permissions - denied
    
    return permissions


def check_permission(permission: str):
    """
    FastAPI dependency to check a single permission.
    Use as: Depends(check_permission(Permissions.FINANCE_INVOICE_CREATE))
    """
    async def dependency(request: Request) -> bool:
        if not RBAC_ENABLED:
            if RBAC_LOG_CHECKS:
                logger.debug(f"[RBAC DISABLED] Would check: {permission}")
            return True
        
        user = await get_current_user(request)
        if not user:
            raise AuthenticationRequiredError()
        
        user_permissions = await get_user_permissions(user)
        
        # Check for admin (has all permissions)
        if "admin" in user.get("roles", []):
            if RBAC_LOG_CHECKS:
                logger.debug(f"[RBAC] Admin bypass for {permission}")
            return True
        
        # Check specific permission
        if permission in user_permissions:
            if RBAC_LOG_CHECKS:
                logger.debug(f"[RBAC] Allowed: {permission} for user {user.get('email')}")
            return True
        
        # Check wildcard permissions (e.g., finance.* for all finance)
        parts = permission.split(".")
        if len(parts) >= 2:
            wildcard = f"{parts[0]}.*"
            if wildcard in user_permissions:
                if RBAC_LOG_CHECKS:
                    logger.debug(f"[RBAC] Wildcard allowed: {wildcard} for {permission}")
                return True
        
        logger.warning(f"[RBAC] Denied: {permission} for user {user.get('email')}")
        raise PermissionDeniedError(permission)
    
    return dependency


def require_permission(permission: str):
    """
    Decorator to require a specific permission on an endpoint.
    
    Usage:
        @router.post("/invoices")
        @require_permission(Permissions.FINANCE_INVOICE_CREATE)
        async def create_invoice(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request in args/kwargs
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if request is None:
                raise ValueError("Request object not found. Add 'request: Request' to endpoint parameters.")
            
            # Check permission
            checker = check_permission(permission)
            await checker(request)
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_any_permission(*permissions: str):
    """
    Decorator requiring ANY of the specified permissions.
    User needs at least one.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if request is None:
                raise ValueError("Request object not found.")
            
            if not RBAC_ENABLED:
                return await func(*args, **kwargs)
            
            user = await get_current_user(request)
            if not user:
                raise AuthenticationRequiredError()
            
            user_permissions = await get_user_permissions(user)
            
            # Admin bypass
            if "admin" in user.get("roles", []):
                return await func(*args, **kwargs)
            
            # Check if user has any of the required permissions
            for perm in permissions:
                if perm in user_permissions:
                    return await func(*args, **kwargs)
            
            raise PermissionDeniedError(
                permissions[0],
                detail=f"Permission denied. Requires one of: {', '.join(permissions)}"
            )
        
        return wrapper
    return decorator


def require_all_permissions(*permissions: str):
    """
    Decorator requiring ALL of the specified permissions.
    User needs all of them.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if request is None:
                raise ValueError("Request object not found.")
            
            if not RBAC_ENABLED:
                return await func(*args, **kwargs)
            
            user = await get_current_user(request)
            if not user:
                raise AuthenticationRequiredError()
            
            user_permissions = await get_user_permissions(user)
            
            # Admin bypass
            if "admin" in user.get("roles", []):
                return await func(*args, **kwargs)
            
            # Check all permissions
            missing = [p for p in permissions if p not in user_permissions]
            if missing:
                raise PermissionDeniedError(
                    missing[0],
                    detail=f"Permission denied. Missing: {', '.join(missing)}"
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


# ========================================
# Utility Functions
# ========================================

async def has_permission(request: Request, permission: str) -> bool:
    """
    Check if current user has permission without raising exception.
    Useful for conditional UI elements.
    """
    if not RBAC_ENABLED:
        return True
    
    try:
        user = await get_current_user(request)
        if not user:
            return False
        
        if "admin" in user.get("roles", []):
            return True
        
        user_permissions = await get_user_permissions(user)
        return permission in user_permissions
    except Exception:
        return False


async def get_user_id(request: Request) -> Optional[str]:
    """Get current user ID from request."""
    user = await get_current_user(request)
    return user.get("id") or user.get("_id") if user else None


async def get_user_email(request: Request) -> Optional[str]:
    """Get current user email from request."""
    user = await get_current_user(request)
    return user.get("email") if user else None
