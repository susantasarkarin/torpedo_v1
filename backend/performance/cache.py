"""
API RESPONSE CACHE MODULE
Multi-tier caching for API responses to reduce database load.

Features:
- In-memory LRU cache for hot data (immediate response)
- Redis cache for warm data (shared across workers)
- Automatic TTL management
- Cache invalidation on data mutations
- Cache statistics for monitoring
"""

import os
import hashlib
import json
import time
import asyncio
from typing import Any, Callable, Optional, Dict, List, TypeVar, Union
from functools import wraps
from collections import OrderedDict
from datetime import datetime, timedelta
import threading
import logging

logger = logging.getLogger(__name__)

# Try to import Redis
try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available - using in-memory cache only")


# ============== CONFIGURATION ==============

class CacheConfig:
    """Cache configuration with defaults"""
    
    # In-memory cache settings
    MEMORY_CACHE_MAX_SIZE = int(os.getenv("CACHE_MEMORY_MAX_SIZE", "1000"))
    MEMORY_CACHE_TTL = int(os.getenv("CACHE_MEMORY_TTL", "300"))  # 5 minutes
    
    # Redis cache settings
    REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
    REDIS_DB = int(os.getenv("REDIS_CACHE_DB", "1"))  # Use DB 1 for cache, 0 for sessions
    REDIS_CACHE_TTL = int(os.getenv("CACHE_REDIS_TTL", "900"))  # 15 minutes
    
    # Endpoint-specific TTLs (in seconds)
    ENDPOINT_TTLS = {
        # Heavy dashboard endpoints - cache longer
        "sales/dashboard": 120,
        "sales/funnel": 120,
        "operations/accounts": 60,
        "operations/kpis": 120,
        "unified-inbox/stats": 60,
        "unified-inbox/conversations": 30,
        "leads/statistics": 60,
        "leads/segment-stats": 60,
        "finance/dashboard": 120,
        "finance/receivables": 60,
        "finance/payables": 60,
        
        # Frequently accessed but static data
        "users/me": 300,
        "settings": 600,
        "roles": 600,
        
        # Default
        "default": 60
    }
    
    # Cache key prefixes for invalidation groups
    CACHE_GROUPS = {
        "sales": ["sales/", "leads/", "rfq/"],
        "finance": ["finance/", "invoices/", "bills/"],
        "operations": ["operations/", "projects/", "clients/"],
        "email": ["unified-inbox/", "gmail/", "email/"],
        "users": ["users/", "roles/", "permissions/"]
    }


# ============== IN-MEMORY LRU CACHE ==============

class LRUCache:
    """Thread-safe LRU cache with TTL support"""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """Get item from cache, return None if expired or missing"""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            item = self._cache[key]
            if time.time() > item['expires_at']:
                # Expired
                del self._cache[key]
                self._misses += 1
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return item['value']
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set item in cache with TTL"""
        with self._lock:
            ttl = ttl or self._default_ttl
            expires_at = time.time() + ttl
            
            # If key exists, update it
            if key in self._cache:
                self._cache[key] = {'value': value, 'expires_at': expires_at}
                self._cache.move_to_end(key)
            else:
                # Check capacity
                while len(self._cache) >= self._max_size:
                    # Remove oldest (first) item
                    self._cache.popitem(last=False)
                
                self._cache[key] = {'value': value, 'expires_at': expires_at}
    
    def delete(self, key: str) -> bool:
        """Delete item from cache"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern (prefix match)"""
        with self._lock:
            keys_to_delete = [k for k in self._cache.keys() if k.startswith(pattern)]
            for key in keys_to_delete:
                del self._cache[key]
            return len(keys_to_delete)
    
    def clear(self):
        """Clear all cache entries"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': round(hit_rate, 2)
            }


# ============== REDIS CACHE (ASYNC) ==============

class RedisCache:
    """Async Redis cache for distributed caching"""
    
    _instance: Optional['RedisCache'] = None
    _client: Optional[Any] = None
    _available: bool = False
    
    def __init__(self):
        self._hits = 0
        self._misses = 0
    
    @classmethod
    async def get_instance(cls) -> 'RedisCache':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance._initialize()
        return cls._instance
    
    async def _initialize(self):
        """Initialize Redis connection"""
        if not REDIS_AVAILABLE:
            logger.warning("Redis library not available")
            return
        
        try:
            self._client = aioredis.Redis(
                host=CacheConfig.REDIS_HOST,
                port=CacheConfig.REDIS_PORT,
                password=CacheConfig.REDIS_PASSWORD,
                db=CacheConfig.REDIS_DB,
                decode_responses=True,
                socket_timeout=2.0,  # 2 second timeout to prevent hanging
                socket_connect_timeout=2.0,  # 2 second connect timeout
                retry_on_timeout=False  # Don't retry on timeout
            )
            await asyncio.wait_for(self._client.ping(), timeout=2.0)
            self._available = True
            logger.info(f"Redis cache connected: {CacheConfig.REDIS_HOST}:{CacheConfig.REDIS_PORT} DB:{CacheConfig.REDIS_DB}")
        except asyncio.TimeoutError:
            logger.warning("Redis cache connection timed out - using in-memory cache only")
            self._available = False
        except Exception as e:
            logger.warning(f"Redis cache connection failed: {e}")
            self._available = False
    
    @property
    def available(self) -> bool:
        return self._available
    
    async def get(self, key: str) -> Optional[Any]:
        """Get item from Redis cache"""
        if not self._available:
            return None
        
        try:
            data = await self._client.get(f"cache:{key}")
            if data:
                self._hits += 1
                return json.loads(data)
            self._misses += 1
            return None
        except Exception as e:
            logger.debug(f"Redis get error: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = None):
        """Set item in Redis cache"""
        if not self._available:
            return
        
        try:
            ttl = ttl or CacheConfig.REDIS_CACHE_TTL
            await self._client.setex(
                f"cache:{key}",
                ttl,
                json.dumps(value, default=str)
            )
        except Exception as e:
            logger.debug(f"Redis set error: {e}")
    
    async def delete(self, key: str) -> bool:
        """Delete item from Redis cache"""
        if not self._available:
            return False
        
        try:
            result = await self._client.delete(f"cache:{key}")
            return result > 0
        except Exception as e:
            logger.debug(f"Redis delete error: {e}")
            return False
    
    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        if not self._available:
            return 0
        
        try:
            keys = []
            async for key in self._client.scan_iter(match=f"cache:{pattern}*"):
                keys.append(key)
            
            if keys:
                await self._client.delete(*keys)
            return len(keys)
        except Exception as e:
            logger.debug(f"Redis delete_pattern error: {e}")
            return 0
    
    async def clear(self):
        """Clear all cache entries"""
        if not self._available:
            return
        
        try:
            async for key in self._client.scan_iter(match="cache:*"):
                await self._client.delete(key)
            self._hits = 0
            self._misses = 0
        except Exception as e:
            logger.debug(f"Redis clear error: {e}")
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        return {
            'available': self._available,
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': round(hit_rate, 2)
        }


# ============== UNIFIED API CACHE ==============

class APICache:
    """
    Unified cache manager with two-tier caching:
    - L1: In-memory LRU (fast, local)
    - L2: Redis (slower, distributed)
    """
    
    def __init__(self):
        self._memory_cache = LRUCache(
            max_size=CacheConfig.MEMORY_CACHE_MAX_SIZE,
            default_ttl=CacheConfig.MEMORY_CACHE_TTL
        )
        self._redis_cache: Optional[RedisCache] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize async components"""
        if not self._initialized:
            self._redis_cache = await RedisCache.get_instance()
            self._initialized = True
    
    def _generate_key(self, endpoint: str, params: Dict[str, Any] = None, user_id: str = None) -> str:
        """Generate cache key from endpoint and parameters"""
        key_parts = [endpoint]
        
        if params:
            # Sort params for consistent keys
            sorted_params = sorted(params.items())
            param_str = "&".join(f"{k}={v}" for k, v in sorted_params if v is not None)
            if param_str:
                key_parts.append(param_str)
        
        if user_id:
            key_parts.append(f"user:{user_id}")
        
        key = ":".join(key_parts)
        
        # Hash if too long
        if len(key) > 200:
            key = f"{endpoint}:{hashlib.md5(key.encode()).hexdigest()}"
        
        return key
    
    def _get_ttl(self, endpoint: str) -> int:
        """Get TTL for endpoint"""
        for pattern, ttl in CacheConfig.ENDPOINT_TTLS.items():
            if pattern in endpoint:
                return ttl
        return CacheConfig.ENDPOINT_TTLS.get("default", 60)
    
    async def get(self, endpoint: str, params: Dict[str, Any] = None, user_id: str = None) -> Optional[Any]:
        """Get from cache (L1 then L2)"""
        key = self._generate_key(endpoint, params, user_id)
        
        # Try L1 (memory)
        result = self._memory_cache.get(key)
        if result is not None:
            return result
        
        # Try L2 (Redis)
        if self._redis_cache and self._redis_cache.available:
            result = await self._redis_cache.get(key)
            if result is not None:
                # Promote to L1
                ttl = self._get_ttl(endpoint)
                self._memory_cache.set(key, result, ttl)
                return result
        
        return None
    
    async def set(self, endpoint: str, value: Any, params: Dict[str, Any] = None, user_id: str = None, ttl: int = None):
        """Set in cache (both L1 and L2)"""
        key = self._generate_key(endpoint, params, user_id)
        ttl = ttl or self._get_ttl(endpoint)
        
        # Set in L1
        self._memory_cache.set(key, value, ttl)
        
        # Set in L2
        if self._redis_cache and self._redis_cache.available:
            await self._redis_cache.set(key, value, ttl)
    
    async def invalidate(self, patterns: Union[str, List[str]]):
        """Invalidate cache entries matching patterns"""
        if isinstance(patterns, str):
            patterns = [patterns]
        
        total_deleted = 0
        for pattern in patterns:
            # Invalidate L1
            total_deleted += self._memory_cache.delete_pattern(pattern)
            
            # Invalidate L2
            if self._redis_cache and self._redis_cache.available:
                total_deleted += await self._redis_cache.delete_pattern(pattern)
        
        logger.debug(f"Cache invalidated: {patterns} ({total_deleted} keys)")
        return total_deleted
    
    async def invalidate_group(self, group: str):
        """Invalidate all patterns in a cache group"""
        patterns = CacheConfig.CACHE_GROUPS.get(group, [])
        if patterns:
            return await self.invalidate(patterns)
        return 0
    
    def stats(self) -> Dict[str, Any]:
        """Get combined cache statistics"""
        memory_stats = self._memory_cache.stats()
        redis_stats = self._redis_cache.stats() if self._redis_cache else {'available': False}
        
        return {
            'memory_cache': memory_stats,
            'redis_cache': redis_stats,
            'config': {
                'memory_max_size': CacheConfig.MEMORY_CACHE_MAX_SIZE,
                'memory_ttl': CacheConfig.MEMORY_CACHE_TTL,
                'redis_ttl': CacheConfig.REDIS_CACHE_TTL
            }
        }


# ============== GLOBAL INSTANCE ==============

api_cache = APICache()


# ============== DECORATOR FOR ROUTE CACHING ==============

T = TypeVar('T')

def cache_response(
    ttl: int = None,
    key_params: List[str] = None,
    include_user: bool = False,
    cache_group: str = None
):
    """
    Decorator to cache FastAPI route responses.
    
    Args:
        ttl: Time-to-live in seconds (auto-detected from endpoint if not set)
        key_params: Query parameters to include in cache key
        include_user: Include user_id in cache key (for user-specific data)
        cache_group: Cache group for invalidation (e.g., 'sales', 'finance')
    
    Usage:
        @router.get("/dashboard")
        @cache_response(ttl=120, cache_group="sales")
        async def get_dashboard(date_from: str, date_to: str):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Ensure cache is initialized
            if not api_cache._initialized:
                await api_cache.initialize()
            
            # Build endpoint path from function name
            endpoint = func.__module__.split('.')[-1] + "/" + func.__name__
            
            # Extract params for cache key
            params = {}
            if key_params:
                for param in key_params:
                    if param in kwargs:
                        params[param] = kwargs[param]
            else:
                # Use all kwargs as params
                params = {k: v for k, v in kwargs.items() 
                         if not k.startswith('_') and k not in ('request', 'db', 'background_tasks')}
            
            # Check for user_id
            user_id = None
            if include_user:
                request = kwargs.get('request')
                if request and hasattr(request, 'state') and hasattr(request.state, 'user'):
                    user_id = request.state.user.get('user_id')
            
            # Try to get from cache
            cached = await api_cache.get(endpoint, params, user_id)
            if cached is not None:
                logger.debug(f"Cache HIT: {endpoint}")
                return cached
            
            # Execute function
            logger.debug(f"Cache MISS: {endpoint}")
            result = await func(*args, **kwargs)
            
            # Cache the result
            await api_cache.set(endpoint, result, params, user_id, ttl)
            
            return result
        
        return wrapper
    return decorator


async def invalidate_cache(patterns: Union[str, List[str]]):
    """Invalidate cache entries matching patterns"""
    if not api_cache._initialized:
        await api_cache.initialize()
    return await api_cache.invalidate(patterns)


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics"""
    return api_cache.stats()
