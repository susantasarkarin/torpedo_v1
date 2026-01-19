"""
AUTHENTICATION UTILITIES
Secure password hashing and verification using bcrypt.

Usage:
    from auth import hash_password, verify_password
    
    hashed = hash_password("mysecretpassword")
    is_valid = verify_password("mysecretpassword", hashed)
"""

import os
import hashlib
import secrets
from typing import Tuple
from datetime import datetime, timedelta

# Note: Using passlib with bcrypt for production-grade password hashing
# If bcrypt is not available, falls back to PBKDF2-SHA256 which is still secure

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    print("⚠️ bcrypt not installed - using PBKDF2 fallback for password hashing")


# ============== PASSWORD HASHING ==============

def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt (or PBKDF2 fallback).
    
    Args:
        password: Plain text password to hash
        
    Returns:
        Hashed password string
    """
    if BCRYPT_AVAILABLE:
        # Use bcrypt with a work factor of 10 (secure and faster for login)
        salt = bcrypt.gensalt(rounds=10)
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    else:
        # Fallback to PBKDF2-SHA256 with 100,000 iterations (faster but still secure)
        salt = secrets.token_hex(16)
        hash_obj = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            260000
        )
        return f"pbkdf2:sha256:260000${salt}${hash_obj.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against its hash.
    
    Args:
        password: Plain text password to verify
        hashed: Hashed password to check against
        
    Returns:
        True if password matches, False otherwise
    """
    # Handle legacy plaintext passwords (for migration)
    if not hashed.startswith('$2') and not hashed.startswith('pbkdf2:'):
        # This is a plaintext password - direct comparison (INSECURE - for migration only)
        return password == hashed
    
    # Handle bcrypt hashes (start with $2a$, $2b$, $2y$)
    if hashed.startswith('$2'):
        if not BCRYPT_AVAILABLE:
            print("⚠️ Cannot verify bcrypt hash - bcrypt not installed on this system!")
            print("   Install bcrypt with: pip install bcrypt")
            return False
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception as e:
            print(f"⚠️ Bcrypt verification error: {e}")
            return False
    
    # Handle PBKDF2 hashes
    if hashed.startswith('pbkdf2:'):
        try:
            parts = hashed.split('$')
            if len(parts) != 3:
                return False
            _, salt, stored_hash = parts
            hash_obj = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt.encode('utf-8'),
                260000
            )
            return secrets.compare_digest(hash_obj.hex(), stored_hash)
        except Exception as e:
            print(f"⚠️ PBKDF2 verification error: {e}")
            return False
    
    # Unknown hash format
    print(f"⚠️ Unknown password hash format: {hashed[:20]}...")
    return False


def needs_rehash(hashed: str) -> bool:
    """
    Check if a password hash needs to be upgraded.
    This returns True for plaintext passwords or weak hashes.
    
    Args:
        hashed: Current password hash
        
    Returns:
        True if password should be rehashed
    """
    # Plaintext passwords need rehashing
    if not hashed.startswith('$2') and not hashed.startswith('pbkdf2:'):
        return True
    
    # If bcrypt is available but using PBKDF2, rehash to bcrypt
    if BCRYPT_AVAILABLE and hashed.startswith('pbkdf2:'):
        return True
    
    return False


# ============== PASSWORD MIGRATION ==============

def migrate_user_password(users_collection, username: str, password: str) -> bool:
    """
    Migrate a user's plaintext password to hashed.
    Call this after successful login with plaintext password.
    
    Args:
        users_collection: MongoDB users collection
        username: Username to migrate
        password: Current plaintext password
        
    Returns:
        True if migration successful
    """
    try:
        hashed = hash_password(password)
        result = users_collection.update_one(
            {"username": username},
            {
                "$set": {
                    "password": hashed,
                    "password_updated_at": datetime.utcnow()
                }
            }
        )
        if result.modified_count > 0:
            print(f"✅ Password migrated to hash for user: {username}")
            return True
    except Exception as e:
        print(f"❌ Password migration failed for {username}: {e}")
    return False


# ============== PASSWORD VALIDATION ==============

def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Validate password meets security requirements.
    
    Requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    
    Args:
        password: Password to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    
    return True, ""


# ============== TOKEN UTILITIES ==============

def generate_secure_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token.
    
    Args:
        length: Length of token in bytes (output is hex, so 2x characters)
        
    Returns:
        Secure random hex string
    """
    return secrets.token_hex(length)


def generate_reset_token() -> Tuple[str, datetime]:
    """
    Generate a password reset token with expiration.
    
    Returns:
        Tuple of (token, expiration_datetime)
    """
    token = generate_secure_token(32)
    expires = datetime.utcnow() + timedelta(hours=24)
    return token, expires


# ============== CURRENT USER DEPENDENCY ==============

def get_current_user() -> dict:
    """
    FastAPI dependency to get the current authenticated user.
    
    This is a placeholder implementation - integrate with your actual
    authentication system (JWT, session, OAuth, etc.).
    
    Returns:
        Dictionary with user information:
        - _id: User ID
        - user_id: User ID (alias)
        - id: User ID (alias)
        - name: User display name
        - email: User email
        - roles: List of user roles
    
    Raises:
        HTTPException: If user is not authenticated
    
    Usage:
        from auth import get_current_user
        from fastapi import Depends
        
        @router.get("/protected")
        def protected_route(current_user: dict = Depends(get_current_user)):
            return {"user": current_user}
    """
    # TODO: Implement actual authentication logic
    # This could be:
    # - JWT token validation from Authorization header
    # - Session validation from cookie
    # - OAuth token validation
    
    # Placeholder: Return a system user
    # In production, this should:
    # 1. Extract token from request headers
    # 2. Validate token
    # 3. Query user from database
    # 4. Return user dict or raise HTTPException(401)
    
    return {
        "_id": "system",
        "id": "system",
        "user_id": "system",
        "name": "System User",
        "email": "system@localhost",
        "roles": ["admin"],
    }
