"""
Session State
=============
Shared session infrastructure used by main.py and auth_handler.py.
Centralises the serializer, in-memory session cache, session store singleton,
and the verify_session FastAPI dependency so they are not defined in main.py
but remain importable by any router that needs them.
"""

import os
from collections import OrderedDict
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

try:
    from .session_store import get_session_store, SESSION_TTL_SECONDS as REDIS_SESSION_TTL
except ImportError:
    from session_store import get_session_store, SESSION_TTL_SECONDS as REDIS_SESSION_TTL

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
SECRET_KEY = os.getenv("SESSION_SECRET", "supersecretkey")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", 60 * 60 * 24))  # default 24h
serializer = URLSafeTimedSerializer(SECRET_KEY)


# -------------------------------------------------------------------
# In-memory session cache (LRU, max 500 entries)
# -------------------------------------------------------------------
class BoundedSessionCache(OrderedDict):
    """LRU-style session cache with max size limit."""
    MAX_SIZE = 500

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.MAX_SIZE:
            self.popitem(last=False)


sessions = BoundedSessionCache()


# -------------------------------------------------------------------
# Redis session store singleton
# -------------------------------------------------------------------
_session_store = None


async def get_session_store_instance():
    """Get or initialize the session store singleton."""
    global _session_store
    if _session_store is None:
        _session_store = await get_session_store()
    return _session_store


# -------------------------------------------------------------------
# FastAPI dependency — verify session token
# -------------------------------------------------------------------
async def verify_session(request: Request):
    """
    Verify session token from Authorization header.
    Uses Redis store for session persistence, with fallback to in-memory.
    """
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing session token")

    session_id = session_id.strip()

    try:
        # Fast path: in-memory cache
        cached = sessions.get(session_id)
        if cached and cached.get("expires_at") and cached["expires_at"] > datetime.utcnow():
            return cached["username"]

        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)

        sessions[session_id] = {
            "username": username,
            "expires_at": datetime.utcnow() + timedelta(seconds=SESSION_TTL_SECONDS),
        }

        # Extend Redis session in background (non-blocking)
        try:
            store = await get_session_store_instance()
            session_data = await store.get(session_id)
            if session_data:
                await store.extend(session_id, SESSION_TTL_SECONDS)
            else:
                await store.create(
                    session_id, {"username": username}, SESSION_TTL_SECONDS
                )
        except Exception:
            pass

        return username
    except SignatureExpired:
        print(f"Token expired: {session_id[:20]}...")
        raise HTTPException(status_code=401, detail="Session expired - please login again")
    except BadSignature:
        print(f"Invalid token signature: {session_id[:20]}...")
        raise HTTPException(status_code=401, detail="Invalid session token - please login again")
    except Exception as e:
        print(f"Session verification error: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Session verification failed: {str(e)}")
