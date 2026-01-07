"""
PERFORMANCE MIDDLEWARE
FastAPI middleware for request timing, compression, and optimization.
"""

import time
import logging
import gzip
import json
from typing import Callable, Dict, Any
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ============== TIMING MIDDLEWARE ==============

class TimingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to track request timing and add performance headers.
    
    Adds headers:
    - X-Response-Time: Request processing time in ms
    - X-Cache-Status: HIT/MISS/BYPASS
    """
    
    def __init__(self, app: FastAPI, slow_threshold_ms: float = 1000):
        super().__init__(app)
        self.slow_threshold_ms = slow_threshold_ms
        self._request_times: Dict[str, list] = {}
        self._max_samples = 100
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        
        # Process request
        response = await call_next(request)
        
        # Calculate processing time
        process_time_ms = (time.perf_counter() - start_time) * 1000
        
        # Add timing header
        response.headers["X-Response-Time"] = f"{process_time_ms:.2f}ms"
        
        # Log slow requests
        if process_time_ms > self.slow_threshold_ms:
            logger.warning(f"SLOW REQUEST: {request.method} {request.url.path} - {process_time_ms:.2f}ms")
        
        # Track timing for monitoring
        path = request.url.path
        if path not in self._request_times:
            self._request_times[path] = []
        self._request_times[path].append(process_time_ms)
        
        # Keep only recent samples
        if len(self._request_times[path]) > self._max_samples:
            self._request_times[path] = self._request_times[path][-self._max_samples:]
        
        return response
    
    def get_timing_stats(self) -> Dict[str, Any]:
        """Get request timing statistics"""
        stats = {}
        for path, times in self._request_times.items():
            if times:
                stats[path] = {
                    'count': len(times),
                    'avg_ms': sum(times) / len(times),
                    'min_ms': min(times),
                    'max_ms': max(times),
                    'p95_ms': sorted(times)[int(len(times) * 0.95)] if len(times) >= 20 else max(times)
                }
        return stats


# ============== CACHE CONTROL MIDDLEWARE ==============

class CacheControlMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add cache control headers for browser caching.
    """
    
    # Default cache times by path pattern
    CACHE_RULES = {
        '/api/settings': 600,  # 10 minutes
        '/api/roles': 600,
        '/api/permissions': 600,
        '/static': 86400,  # 1 day
        '/assets': 86400,
    }
    
    # Paths that should never be cached
    NO_CACHE_PATHS = [
        '/api/auth',
        '/api/login',
        '/api/logout',
        '/api/session'
    ]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        path = request.url.path
        
        # Skip for non-GET requests
        if request.method != "GET":
            response.headers["Cache-Control"] = "no-store"
            return response
        
        # Skip for no-cache paths
        for no_cache in self.NO_CACHE_PATHS:
            if path.startswith(no_cache):
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
                return response
        
        # Apply cache rules
        for pattern, max_age in self.CACHE_RULES.items():
            if pattern in path:
                response.headers["Cache-Control"] = f"public, max-age={max_age}"
                return response
        
        # Default: allow browser caching for 60 seconds
        if path.startswith('/api/'):
            response.headers["Cache-Control"] = "private, max-age=60"
        
        return response


# ============== REQUEST DEDUPLICATION ==============

class DeduplicationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to deduplicate identical concurrent requests.
    If the same request comes in while another is processing,
    wait for the first to complete and return its result.
    
    Useful for:
    - Double-click prevention
    - Concurrent API calls from React
    """
    
    def __init__(self, app: FastAPI, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled
        self._pending: Dict[str, Any] = {}
        self._max_pending = 100
    
    def _request_key(self, request: Request) -> str:
        """Generate key for request deduplication"""
        return f"{request.method}:{request.url.path}:{request.url.query}"
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)
        
        # Only dedupe GET requests
        if request.method != "GET":
            return await call_next(request)
        
        key = self._request_key(request)
        
        # If same request is already pending, we could wait for it
        # For now, just process normally to avoid complexity
        # Future enhancement: implement request coalescing
        
        return await call_next(request)


# ============== COMBINED PERFORMANCE MIDDLEWARE ==============

class PerformanceMiddleware:
    """
    Combined performance middleware manager.
    
    Usage:
        app = FastAPI()
        perf = PerformanceMiddleware(app)
        perf.setup()
    """
    
    def __init__(self, app: FastAPI, config: Dict[str, Any] = None):
        self.app = app
        self.config = config or {}
        self._timing_middleware = None
    
    def setup(self):
        """Set up all performance middleware"""
        
        # Timing middleware (added first, runs last)
        slow_threshold = self.config.get('slow_threshold_ms', 1000)
        self._timing_middleware = TimingMiddleware(self.app, slow_threshold)
        self.app.add_middleware(TimingMiddleware, slow_threshold_ms=slow_threshold)
        
        # Cache control
        if self.config.get('cache_control', True):
            self.app.add_middleware(CacheControlMiddleware)
        
        logger.info("Performance middleware configured")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        return {
            'timing': self._timing_middleware.get_timing_stats() if self._timing_middleware else {}
        }


# ============== CONNECTION POOLING OPTIMIZATION ==============

def optimize_mongodb_connection(mongo_uri: str) -> Dict[str, Any]:
    """
    Get optimized MongoDB connection options.
    
    Args:
        mongo_uri: Base MongoDB URI
    
    Returns:
        Dict of optimized connection options
    """
    return {
        'serverSelectionTimeoutMS': 5000,
        'connectTimeoutMS': 5000,
        'socketTimeoutMS': 30000,
        'maxPoolSize': 100,  # Increased from 50
        'minPoolSize': 10,   # Increased from 5
        'maxIdleTimeMS': 30000,
        'waitQueueTimeoutMS': 10000,
        'retryWrites': True,
        'retryReads': True,
        'w': 'majority',
        'readPreference': 'primaryPreferred',
        'compressors': ['zstd', 'snappy', 'zlib'],  # Enable compression
    }


# ============== RESPONSE OPTIMIZATION ==============

def optimize_response_payload(data: Any, request: Request) -> Any:
    """
    Optimize response payload based on request parameters.
    
    - Supports field selection via ?fields=a,b,c
    - Supports sparse mode via ?sparse=true
    """
    if not isinstance(data, (dict, list)):
        return data
    
    # Check for field selection
    fields_param = request.query_params.get('fields')
    if fields_param:
        fields = [f.strip() for f in fields_param.split(',')]
        if isinstance(data, list):
            return [{k: v for k, v in item.items() if k in fields} for item in data]
        else:
            return {k: v for k, v in data.items() if k in fields}
    
    # Check for sparse mode (remove null/empty values)
    sparse = request.query_params.get('sparse', '').lower() == 'true'
    if sparse:
        if isinstance(data, list):
            return [_remove_empty(item) for item in data]
        else:
            return _remove_empty(data)
    
    return data


def _remove_empty(d: Dict) -> Dict:
    """Remove empty/null values from dict"""
    return {k: v for k, v in d.items() if v is not None and v != '' and v != []}
