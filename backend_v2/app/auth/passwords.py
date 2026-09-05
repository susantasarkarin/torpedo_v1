"""
Argon2id password hashing (spec §48). v1's password-strength validation existed in
exactly one place across the whole codebase (`routers/panel.py`'s signup form) and was
absent everywhere else that accepted a password — including the RBAC `UserCreate`
model itself. This module is the only place v2 hashes or verifies a password; nothing
else may call a hashing primitive directly.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plaintext: str) -> str:
    if len(plaintext) < 8:
        raise ValueError("password must be at least 8 characters")
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, stored_hash: str) -> bool:
    try:
        return _hasher.verify(stored_hash, plaintext)
    except VerifyMismatchError:
        return False
