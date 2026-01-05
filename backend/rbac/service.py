"""
RBAC Service
============

Business logic for role and permission management.
Handles CRUD operations and permission resolution.
"""

import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Set
from pymongo.database import Database
from pymongo import ASCENDING
from bson import ObjectId

from .models import (
    Role, Permission, UserRole, ApprovalAuthority, User,
    RoleCreate, RoleUpdate, UserCreate, UserUpdate,
    RoleStatus, UserStatus
)
from .permissions import ROLE_TEMPLATES, Permissions

logger = logging.getLogger(__name__)


class RBACService:
    """
    Service for managing roles, permissions, and user assignments.
    """
    
    ROLES_COLLECTION = "roles"
    PERMISSIONS_COLLECTION = "permissions"
    USER_ROLES_COLLECTION = "user_roles"
    USERS_COLLECTION = "users"
    APPROVAL_AUTH_COLLECTION = "approval_authorities"
    
    def __init__(self, db: Database):
        self.db = db
        self.roles = db[self.ROLES_COLLECTION]
        self.permissions = db[self.PERMISSIONS_COLLECTION]
        self.user_roles = db[self.USER_ROLES_COLLECTION]
        self.users = db[self.USERS_COLLECTION]
        self.approval_auth = db[self.APPROVAL_AUTH_COLLECTION]
    
    def ensure_indexes(self):
        """Create required indexes."""
        self.roles.create_index("code", unique=True)
        self.permissions.create_index("code", unique=True)
        self.user_roles.create_index([("user_id", ASCENDING), ("role_code", ASCENDING)], unique=True)
        self.users.create_index("email", unique=True)
        self.approval_auth.create_index([("role_code", ASCENDING), ("entity_type", ASCENDING)])
        logger.info("RBAC indexes ensured")
    
    def initialize_system_roles(self) -> int:
        """
        Initialize system-defined roles from templates.
        Idempotent - safe to call multiple times.
        Returns number of roles created.
        """
        created = 0
        for code, template in ROLE_TEMPLATES.items():
            existing = self.roles.find_one({"code": code})
            if not existing:
                role_data = {
                    "code": code,
                    "name": template["name"],
                    "description": template.get("description"),
                    "permissions": template["permissions"],
                    "is_system_role": template.get("is_system_role", True),
                    "status": RoleStatus.ACTIVE.value,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "created_by": "system"
                }
                self.roles.insert_one(role_data)
                logger.info(f"Created system role: {code}")
                created += 1
            else:
                # Update permissions for system roles (keep in sync with templates)
                if existing.get("is_system_role"):
                    self.roles.update_one(
                        {"code": code},
                        {"$set": {
                            "permissions": template["permissions"],
                            "updated_at": datetime.utcnow()
                        }}
                    )
        return created
    
    # ========================================
    # Role Management
    # ========================================
    
    def create_role(self, data: RoleCreate, created_by: Optional[str] = None) -> Role:
        """Create a new role."""
        # Check for duplicate
        if self.roles.find_one({"code": data.code}):
            raise ValueError(f"Role with code '{data.code}' already exists")
        
        role_doc = {
            "code": data.code,
            "name": data.name,
            "description": data.description,
            "permissions": data.permissions,
            "is_system_role": False,
            "status": RoleStatus.ACTIVE.value,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": created_by
        }
        
        result = self.roles.insert_one(role_doc)
        role_doc["_id"] = str(result.inserted_id)
        return Role(**role_doc)
    
    def get_role(self, code: str) -> Optional[Role]:
        """Get role by code."""
        doc = self.roles.find_one({"code": code})
        if doc:
            doc["_id"] = str(doc["_id"])
            return Role(**doc)
        return None
    
    def list_roles(self, include_inactive: bool = False) -> List[Role]:
        """List all roles."""
        query = {} if include_inactive else {"status": RoleStatus.ACTIVE.value}
        docs = list(self.roles.find(query).sort("name", ASCENDING))
        roles = []
        for doc in docs:
            doc["_id"] = str(doc["_id"])
            roles.append(Role(**doc))
        return roles
    
    def update_role(self, code: str, data: RoleUpdate, updated_by: Optional[str] = None) -> Optional[Role]:
        """Update a role."""
        role = self.roles.find_one({"code": code})
        if not role:
            return None
        
        # Prevent modifying system roles' core properties
        if role.get("is_system_role") and data.permissions is not None:
            logger.warning(f"Attempt to modify system role permissions: {code}")
            # Allow it but log - admin might need to extend
        
        update_doc = {"updated_at": datetime.utcnow()}
        if data.name is not None:
            update_doc["name"] = data.name
        if data.description is not None:
            update_doc["description"] = data.description
        if data.permissions is not None:
            update_doc["permissions"] = data.permissions
        if data.status is not None:
            update_doc["status"] = data.status.value
        
        self.roles.update_one({"code": code}, {"$set": update_doc})
        return self.get_role(code)
    
    def delete_role(self, code: str) -> bool:
        """Delete a role (soft delete for system roles)."""
        role = self.roles.find_one({"code": code})
        if not role:
            return False
        
        if role.get("is_system_role"):
            # Soft delete system roles
            self.roles.update_one(
                {"code": code},
                {"$set": {"status": RoleStatus.INACTIVE.value, "updated_at": datetime.utcnow()}}
            )
        else:
            # Hard delete custom roles
            self.roles.delete_one({"code": code})
            # Remove role assignments
            self.user_roles.delete_many({"role_code": code})
        
        return True
    
    def get_role_permissions(self, role_code: str) -> List[str]:
        """Get all permissions for a role."""
        role = self.roles.find_one({"code": role_code, "status": RoleStatus.ACTIVE.value})
        if role:
            return role.get("permissions", [])
        return []
    
    # ========================================
    # User Management
    # ========================================
    
    def create_user(self, data: UserCreate, created_by: Optional[str] = None) -> User:
        """Create a new user."""
        from auth import hash_password
        
        # Check for duplicate
        if self.users.find_one({"email": data.email.lower()}):
            raise ValueError(f"User with email '{data.email}' already exists")
        
        user_doc = {
            "email": data.email.lower(),
            "name": data.name,
            "password_hash": hash_password(data.password),
            "first_name": data.first_name,
            "last_name": data.last_name,
            "status": UserStatus.ACTIVE.value,
            "roles": data.roles,
            "permissions_override": [],
            "permissions_denied": [],
            "department": data.department,
            "manager_id": data.manager_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": created_by
        }
        
        result = self.users.insert_one(user_doc)
        user_doc["_id"] = str(result.inserted_id)
        del user_doc["password_hash"]  # Don't return password
        return User(**user_doc)
    
    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        try:
            doc = self.users.find_one({"_id": ObjectId(user_id)})
        except:
            doc = self.users.find_one({"email": user_id.lower()})
        
        if doc:
            doc["_id"] = str(doc["_id"])
            doc.pop("password_hash", None)
            return User(**doc)
        return None
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        doc = self.users.find_one({"email": email.lower()})
        if doc:
            doc["_id"] = str(doc["_id"])
            doc.pop("password_hash", None)
            return User(**doc)
        return None
    
    def list_users(
        self,
        status: Optional[UserStatus] = None,
        role: Optional[str] = None,
        limit: int = 100,
        skip: int = 0
    ) -> List[User]:
        """List users with optional filters."""
        query = {}
        if status:
            query["status"] = status.value
        if role:
            query["roles"] = role
        
        docs = list(
            self.users.find(query)
            .sort("name", ASCENDING)
            .skip(skip)
            .limit(limit)
        )
        
        users = []
        for doc in docs:
            doc["_id"] = str(doc["_id"])
            doc.pop("password_hash", None)
            users.append(User(**doc))
        return users
    
    def update_user(self, user_id: str, data: UserUpdate, updated_by: Optional[str] = None) -> Optional[User]:
        """Update a user."""
        try:
            oid = ObjectId(user_id)
        except:
            return None
        
        update_doc = {"updated_at": datetime.utcnow()}
        if data.name is not None:
            update_doc["name"] = data.name
        if data.first_name is not None:
            update_doc["first_name"] = data.first_name
        if data.last_name is not None:
            update_doc["last_name"] = data.last_name
        if data.status is not None:
            update_doc["status"] = data.status.value
        if data.roles is not None:
            update_doc["roles"] = data.roles
        if data.department is not None:
            update_doc["department"] = data.department
        if data.manager_id is not None:
            update_doc["manager_id"] = data.manager_id
        
        result = self.users.update_one({"_id": oid}, {"$set": update_doc})
        if result.matched_count > 0:
            return self.get_user(user_id)
        return None
    
    def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user."""
        try:
            result = self.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"status": UserStatus.INACTIVE.value, "updated_at": datetime.utcnow()}}
            )
            return result.modified_count > 0
        except:
            return False
    
    def assign_role(self, user_id: str, role_code: str, assigned_by: Optional[str] = None) -> bool:
        """Assign a role to a user."""
        # Verify role exists
        if not self.roles.find_one({"code": role_code, "status": RoleStatus.ACTIVE.value}):
            raise ValueError(f"Role '{role_code}' not found or inactive")
        
        # Add to user's roles
        result = self.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$addToSet": {"roles": role_code},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        return result.modified_count > 0
    
    def revoke_role(self, user_id: str, role_code: str) -> bool:
        """Revoke a role from a user."""
        result = self.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$pull": {"roles": role_code},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        return result.modified_count > 0
    
    def get_user_permissions(self, user_id: str) -> Set[str]:
        """Get all effective permissions for a user."""
        user = self.get_user(user_id)
        if not user:
            return set()
        
        permissions = set()
        
        # Add permissions from roles
        for role_code in user.roles:
            role_perms = self.get_role_permissions(role_code)
            permissions.update(role_perms)
        
        # Add direct permissions
        permissions.update(user.permissions_override)
        
        # Remove denied permissions
        permissions -= set(user.permissions_denied)
        
        return permissions
    
    def user_has_permission(self, user_id: str, permission: str) -> bool:
        """Check if user has a specific permission."""
        permissions = self.get_user_permissions(user_id)
        
        if permission in permissions:
            return True
        
        # Check wildcards
        parts = permission.split(".")
        if len(parts) >= 2:
            wildcard = f"{parts[0]}.*"
            if wildcard in permissions:
                return True
        
        return False
    
    # ========================================
    # Approval Authority
    # ========================================
    
    def get_approval_authority(
        self,
        user_id: str,
        entity_type: str
    ) -> Optional[ApprovalAuthority]:
        """Get approval authority for a user on an entity type."""
        user = self.get_user(user_id)
        if not user:
            return None
        
        # Check user-specific authority
        auth = self.approval_auth.find_one({
            "user_id": user_id,
            "entity_type": entity_type
        })
        if auth:
            auth["_id"] = str(auth["_id"])
            return ApprovalAuthority(**auth)
        
        # Check role-based authority
        for role_code in user.roles:
            auth = self.approval_auth.find_one({
                "role_code": role_code,
                "entity_type": entity_type
            })
            if auth:
                auth["_id"] = str(auth["_id"])
                return ApprovalAuthority(**auth)
        
        return None
    
    def can_approve_amount(
        self,
        user_id: str,
        entity_type: str,
        amount: float,
        currency: str = "USD"
    ) -> bool:
        """Check if user can approve a specific amount."""
        authority = self.get_approval_authority(user_id, entity_type)
        if not authority:
            return False
        
        if not authority.can_approve:
            return False
        
        # Check currency match
        if authority.currency != currency:
            return False
        
        # Check amount limit
        if authority.max_amount is not None:
            return amount <= authority.max_amount
        
        return True  # Unlimited


# Singleton instance
_rbac_service: Optional[RBACService] = None


def get_rbac_service(db: Database) -> RBACService:
    """Get or create RBAC service instance."""
    global _rbac_service
    if _rbac_service is None:
        _rbac_service = RBACService(db)
        _rbac_service.ensure_indexes()
        _rbac_service.initialize_system_roles()
    return _rbac_service
