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
            100000
        )
        return f"pbkdf2:sha256:100000${salt}${hash_obj.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against its hash.
    
    Args:
        password: Plain text password to verify
        hashed: Hashed password to check against
        
    Returns:
        True if password matches, False otherwise
        
    Raises:
        ValueError: If password hash is in plaintext format
    """
    # A MISSING hash is not a plaintext hash. 223,951 of 224,002 panelists have
    # no password_hash at all (registration happens on the SFW panel), so
    # panel.py's `panelist.get("password_hash", "")` passed "" here on every
    # such login attempt and this raised — turning "wrong email" into a 500,
    # ~200 times a day. Absent credentials simply fail to verify.
    if not hashed:
        return False

    # Reject plaintext passwords - this is a security violation
    if not hashed.startswith('$2') and not hashed.startswith('pbkdf2:'):
        raise ValueError(f"❌ SECURITY VIOLATION: Found plaintext password hash. All passwords must be hashed with bcrypt or PBKDF2. "
                        f"Use hash_password() or migrate_user_password() to fix user accounts.")
    
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

# fastapi is only needed for the request-bound dependency below. The pure
# password helpers above must stay importable in the minimal CI env (which
# installs requirements-ci.txt without fastapi), so fall back to lightweight
# stand-ins when it is absent. Production always has fastapi installed, so the
# real Request/Depends/HTTPException are used for dependency injection.
try:
    from fastapi import Request, Depends, HTTPException
except ModuleNotFoundError:  # minimal CI / test env
    Request = None

    def Depends(dependency):  # type: ignore
        return dependency

    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int = 500, detail: str = ""):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)


def get_current_user(request: Request = None) -> dict:
    """
    FastAPI dependency to get the current authenticated user via session token.
    Uses verify_session from main.py which raises HTTPException on failure.
    Returns a minimal user dict loaded from the users collection.
    """
    try:
        # Import here to avoid circular imports at module load time
        from main import verify_session, serializer, SESSION_TTL_SECONDS

        username = None
        # verify_session returns username (the serializer payload)
        if request is None:
            raise HTTPException(status_code=401, detail="Missing request for auth")
        username = None
        # Manually call verify_session dependency logic
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)

        # Fetch user from DB
        from database import get_database
        users_col = get_database("email_automation")["users"]
        user = users_col.find_one({"username": username})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Minimal user dict
        return {
            "_id": str(user.get("_id")),
            "username": user.get("username"),
            "email": user.get("email"),
            "displayName": user.get("displayName", user.get("username")),
            "roles": user.get("roles", [user.get("role")]) if user.get("roles") or user.get("role") else ["user"]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
