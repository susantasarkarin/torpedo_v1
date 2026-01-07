"""
Redis-backed session store for production use.
Falls back gracefully if Redis unavailable.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Redis configuration from environment
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "86400"))  # 24 hours

class SessionStore:
    """Redis-backed session storage with connection pooling."""
    
    _instance: Optional["SessionStore"] = None
    _pool: Optional[redis.ConnectionPool] = None
    _client: Optional[redis.Redis] = None
    _available: bool = False
    
    def __init__(self):
        pass
    
    @classmethod
    async def get_instance(cls) -> "SessionStore":
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance._initialize()
        return cls._instance
    
    async def _initialize(self):
        """Initialize Redis connection pool."""
        try:
            self._pool = redis.ConnectionPool(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                db=REDIS_DB,
                decode_responses=True,
                max_connections=10,
                socket_timeout=2.0,  # 2 second timeout to prevent hanging
                socket_connect_timeout=2.0  # 2 second connect timeout
            )
            self._client = redis.Redis(connection_pool=self._pool)
            # Test connection with timeout
            import asyncio
            await asyncio.wait_for(self._client.ping(), timeout=2.0)
            self._available = True
            logger.info(f"Redis session store connected: {REDIS_HOST}:{REDIS_PORT}")
        except asyncio.TimeoutError:
            logger.warning("Redis session store connection timed out. Sessions will not persist.")
            self._available = False
        except Exception as e:
            logger.error(f"Redis connection failed: {e}. Sessions will not persist across restarts.")
            self._available = False
    
    def _session_key(self, session_id: str) -> str:
        """Generate Redis key for session."""
        return f"session:{session_id}"
    
    async def create(self, session_id: str, user_data: Dict[str, Any], ttl_seconds: int = None) -> bool:
        """Create a new session."""
        if not self._available:
            logger.warning("Redis unavailable - session not persisted")
            return False
        
        ttl = ttl_seconds or SESSION_TTL_SECONDS
        key = self._session_key(session_id)
        
        try:
            data = {
                **user_data,
                "created_at": datetime.utcnow().isoformat(),
                "session_id": session_id
            }
            await self._client.setex(key, ttl, json.dumps(data))
            logger.debug(f"Session created: {session_id[:8]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            return False
    
    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data."""
        if not self._available:
            return None
        
        key = self._session_key(session_id)
        
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get session: {e}")
            return None
    
    async def delete(self, session_id: str) -> bool:
        """Delete a session."""
        if not self._available:
            return False
        
        key = self._session_key(session_id)
        
        try:
            await self._client.delete(key)
            logger.debug(f"Session deleted: {session_id[:8]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False
    
    async def extend(self, session_id: str, ttl_seconds: int = None) -> bool:
        """Extend session TTL."""
        if not self._available:
            return False
        
        ttl = ttl_seconds or SESSION_TTL_SECONDS
        key = self._session_key(session_id)
        
        try:
            await self._client.expire(key, ttl)
            return True
        except Exception as e:
            logger.error(f"Failed to extend session: {e}")
            return False
    
    async def exists(self, session_id: str) -> bool:
        """Check if session exists."""
        if not self._available:
            return False
        
        key = self._session_key(session_id)
        
        try:
            return await self._client.exists(key) > 0
        except Exception as e:
            logger.error(f"Failed to check session: {e}")
            return False
    
    @property
    def is_available(self) -> bool:
        """Check if Redis is available."""
        return self._available
    
    async def health_check(self) -> Dict[str, Any]:
        """Return health status of Redis connection."""
        if not self._available:
            return {
                "status": "unavailable",
                "host": REDIS_HOST,
                "port": REDIS_PORT,
                "message": "Redis connection not established"
            }
        
        try:
            await self._client.ping()
            info = await self._client.info("server")
            return {
                "status": "healthy",
                "host": REDIS_HOST,
                "port": REDIS_PORT,
                "redis_version": info.get("redis_version", "unknown"),
                "uptime_seconds": info.get("uptime_in_seconds", 0)
            }
        except Exception as e:
            return {
                "status": "error",
                "host": REDIS_HOST,
                "port": REDIS_PORT,
                "message": str(e)
            }


# Fallback in-memory store for development/testing
class InMemorySessionStore:
    """In-memory session store for development. NOT for production."""
    
    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._expiry: Dict[str, datetime] = {}
        logger.warning("Using in-memory session store - sessions will not persist!")
    
    async def create(self, session_id: str, user_data: Dict[str, Any], ttl_seconds: int = SESSION_TTL_SECONDS) -> bool:
        self._sessions[session_id] = {**user_data, "session_id": session_id}
        self._expiry[session_id] = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        return True
    
    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        if session_id in self._expiry:
            if datetime.utcnow() > self._expiry[session_id]:
                await self.delete(session_id)
                return None
        return self._sessions.get(session_id)
    
    async def delete(self, session_id: str) -> bool:
        self._sessions.pop(session_id, None)
        self._expiry.pop(session_id, None)
        return True
    
    async def extend(self, session_id: str, ttl_seconds: int = SESSION_TTL_SECONDS) -> bool:
        if session_id in self._sessions:
            self._expiry[session_id] = datetime.utcnow() + timedelta(seconds=ttl_seconds)
            return True
        return False
    
    async def exists(self, session_id: str) -> bool:
        return session_id in self._sessions
    
    @property
    def is_available(self) -> bool:
        return True
    
    async def health_check(self) -> Dict[str, Any]:
        return {
            "status": "in-memory",
            "warning": "Not suitable for production",
            "session_count": len(self._sessions)
        }


async def get_session_store() -> SessionStore:
    """Factory function to get appropriate session store."""
    store = await SessionStore.get_instance()
    if store.is_available:
        return store
    # Fallback to in-memory for development
    logger.warning("Falling back to in-memory session store")
    return InMemorySessionStore()
