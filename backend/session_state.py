"""
Session State
=============
THE session infrastructure: the serializer, the in-memory cache, the session
store singleton, and the `verify_session` FastAPI dependency. `main.py` and
every router import from here — there is deliberately only one of each.

(Until 2026-09-01 `main.py` defined a second, parallel copy of all of it.
Login wrote to *this* module's cache while request verification read *that*
one, so the cache never hit and — worse — `logout` purging one cache left the
other untouched. See TOR-19 in the architecture review.)

REVOCATION MODEL (TOR-02)
-------------------------
The token is a signed username: valid signature alone used to be sufficient,
which meant logout could not revoke anything and a leaked token stayed live
for its full TTL. Now the signature is only the cheap first filter and the
session store is authoritative:

    signature valid?  -> no: 401 (rejects garbage without touching Redis)
    store reachable?  -> yes: session must EXIST in the store, or 401
                      -> no:  degrade to signature-only, log a WARNING

The degradation matters. `get_session_store()` falls back to an empty
in-memory store when Redis is down; treating "not in the store" as "revoked"
there would log out every user in the building the moment Redis blinked. So a
Redis outage fails *open* on revocation and is announced loudly instead —
availability is preserved, and revocation resumes automatically.

Token epoch: the signed payload carries the user's `session_epoch`. Bumping
that field on the user document (password change, forced logout, offboarding)
invalidates every token that user holds, everywhere, without needing to
enumerate them. Legacy tokens whose payload is a bare username string are
still accepted — they simply carry no epoch and are checked against epoch 0.
"""

import logging
import os
from collections import OrderedDict
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

try:
    from .session_store import get_session_store, SESSION_TTL_SECONDS as REDIS_SESSION_TTL
except ImportError:
    from session_store import get_session_store, SESSION_TTL_SECONDS as REDIS_SESSION_TTL

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
# No insecure default: an unset SESSION_SECRET used to silently fall back to
# the literal "supersecretkey" here, while config.py refused to start without
# a real one — so whichever module loaded first decided whether the app was
# secure. config.py's rule wins now.
SECRET_KEY = os.getenv("SESSION_SECRET")
if not SECRET_KEY or SECRET_KEY in ("supersecretkey", "supersecretkey_change_this_in_production"):
    raise RuntimeError(
        "SESSION_SECRET must be set to a strong secret. Refusing to start with "
        "a missing or well-known session signing key."
    )

SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", 60 * 60 * 24))  # default 24h
serializer = URLSafeTimedSerializer(SECRET_KEY)

# How long a positive verification may be served from the local cache before
# re-checking the store. Bounded so a revocation issued by another process
# (a celery worker, a second uvicorn worker) takes effect quickly even though
# that process cannot reach into this one's memory.
CACHE_TTL_SECONDS = int(os.getenv("SESSION_CACHE_TTL_SECONDS", "30"))


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


def _store_is_authoritative(store) -> bool:
    """
    True when the store is durable and shared (Redis), so "absent" genuinely
    means "revoked". False for the in-memory fallback, which starts empty on
    every process start and would otherwise mass-revoke live sessions.
    """
    return type(store).__name__ != "InMemorySessionStore"


# -------------------------------------------------------------------
# Token payload
# -------------------------------------------------------------------
def issue_token(username: str, epoch: int = 0) -> str:
    """Sign a session token carrying the user's current session epoch."""
    return serializer.dumps({"u": username, "e": int(epoch or 0)})


def _unpack(payload):
    """Accept both the new dict payload and legacy bare-username tokens."""
    if isinstance(payload, dict):
        return payload.get("u"), int(payload.get("e") or 0)
    return payload, 0


def current_epoch(username: str) -> int:
    """Read the user's session epoch. Missing user or field -> 0."""
    try:
        try:
            from .database import get_database
        except ImportError:
            from database import get_database
        doc = get_database("email_automation")["users"].find_one(
            {"username": username}, {"session_epoch": 1}
        )
        return int((doc or {}).get("session_epoch") or 0)
    except Exception:
        # Reading the epoch is a hardening check, not the primary gate. If the
        # database is unreachable the request has bigger problems than a stale
        # token; don't turn a Mongo blip into a site-wide logout.
        logger.warning("session epoch lookup failed for %s; allowing", username)
        return -1  # sentinel: "unknown", compares equal to anything below


def bump_epoch(username: str) -> int:
    """
    Invalidate every existing token for this user. Called on password change
    and on user deletion/deactivation.
    """
    try:
        from .database import get_database
    except ImportError:
        from database import get_database
    doc = get_database("email_automation")["users"].find_one_and_update(
        {"username": username},
        {"$inc": {"session_epoch": 1}},
        projection={"session_epoch": 1},
        return_document=True,
    )
    # Local cache holds decoded tokens for this user; drop them so the change
    # is immediate in this process too.
    for key in [k for k, v in sessions.items() if v.get("username") == username]:
        sessions.pop(key, None)
    return int((doc or {}).get("session_epoch") or 0)


# -------------------------------------------------------------------
# FastAPI dependency — verify session token
# -------------------------------------------------------------------
async def verify_session(request: Request):
    """
    Verify the session token from the Authorization header.

    Signature is the cheap filter; the session store is the authority (see the
    module docstring for the Redis-outage degradation).
    """
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing session token")

    session_id = session_id.strip()

    # Fast path: a recent positive verification for this exact token.
    cached = sessions.get(session_id)
    if cached and cached.get("expires_at") and cached["expires_at"] > datetime.utcnow():
        return cached["username"]

    try:
        username, token_epoch = _unpack(
            serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)
        )
    except SignatureExpired:
        raise HTTPException(status_code=401, detail="Session expired - please login again")
    except BadSignature:
        raise HTTPException(status_code=401, detail="Invalid session token - please login again")

    if not username:
        raise HTTPException(status_code=401, detail="Invalid session token - please login again")

    # --- authority check -------------------------------------------------
    try:
        store = await get_session_store_instance()
        session_data = await store.get(session_id)
        if session_data:
            await store.extend(session_id, SESSION_TTL_SECONDS)
        elif _store_is_authoritative(store):
            # Absent from a durable store == logged out, revoked, or expired.
            raise HTTPException(
                status_code=401, detail="Session revoked - please login again"
            )
        else:
            logger.warning(
                "session store unavailable (in-memory fallback); accepting %s on "
                "signature alone — revocation is NOT enforced until Redis returns",
                username,
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Store unreachable entirely: same reasoning as the fallback branch —
        # fail open on revocation, loudly, rather than locking everyone out.
        logger.warning(
            "session store check failed (%s); accepting %s on signature alone",
            type(exc).__name__, username,
        )

    # --- token epoch -----------------------------------------------------
    live_epoch = current_epoch(username)
    if live_epoch >= 0 and token_epoch < live_epoch:
        raise HTTPException(
            status_code=401, detail="Session invalidated - please login again"
        )

    sessions[session_id] = {
        "username": username,
        "expires_at": datetime.utcnow() + timedelta(seconds=CACHE_TTL_SECONDS),
    }
    return username


async def revoke_session(session_id: str) -> None:
    """Delete a session everywhere it is known. Used by logout."""
    if not session_id:
        return
    sessions.pop(session_id, None)
    try:
        store = await get_session_store_instance()
        await store.delete(session_id)
    except Exception:
        logger.warning("session store delete failed during logout", exc_info=True)
