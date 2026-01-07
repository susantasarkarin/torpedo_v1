"""
PERFORMANCE OPTIMIZATION MODULE
Provides caching, query optimization, and performance monitoring.
"""

from .cache import (
    api_cache, 
    cache_response, 
    invalidate_cache, 
    get_cache_stats,
    CacheConfig
)
from .query_optimizer import QueryOptimizer, optimize_query
from .middleware import PerformanceMiddleware
from .monitoring import PerformanceMonitor, get_performance_stats

__all__ = [
    'api_cache',
    'cache_response', 
    'invalidate_cache',
    'get_cache_stats',
    'CacheConfig',
    'QueryOptimizer',
    'optimize_query',
    'PerformanceMiddleware',
    'PerformanceMonitor',
    'get_performance_stats'
]
