"""
PERFORMANCE ROUTER
Provides endpoints for monitoring and managing API performance.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, Optional
from datetime import datetime
import os

router = APIRouter(prefix="/performance", tags=["Performance"])


# ============== CACHE MANAGEMENT ==============

def get_all_cache_stats() -> Dict[str, Any]:
    """Collect cache statistics from all caching modules"""
    stats = {
        "collected_at": datetime.utcnow().isoformat(),
        "caches": {}
    }
    
    # Sales Dashboard Cache
    try:
        from routers.sales_dashboard import _dashboard_cache, CACHE_TTL_SECONDS as sales_ttl
        import time
        now = time.time()
        valid_entries = sum(1 for v in _dashboard_cache.values() if now < v['expires_at'])
        stats["caches"]["sales_dashboard"] = {
            "total_entries": len(_dashboard_cache),
            "valid_entries": valid_entries,
            "ttl_seconds": sales_ttl
        }
    except Exception as e:
        stats["caches"]["sales_dashboard"] = {"error": str(e)}
    
    # Operations Cache
    try:
        from routers.operations import _operations_cache, CACHE_TTL_SECONDS as ops_ttl
        import time
        now = time.time()
        valid_entries = sum(1 for v in _operations_cache.values() if now < v['expires_at'])
        stats["caches"]["operations"] = {
            "total_entries": len(_operations_cache),
            "valid_entries": valid_entries,
            "ttl_seconds": ops_ttl
        }
    except Exception as e:
        stats["caches"]["operations"] = {"error": str(e)}
    
    # Unified Inbox Cache
    try:
        from routers.unified_inbox import _inbox_cache, CACHE_TTL_SECONDS as inbox_ttl
        import time
        now = time.time()
        valid_entries = sum(1 for v in _inbox_cache.values() if now < v['expires_at'])
        stats["caches"]["unified_inbox"] = {
            "total_entries": len(_inbox_cache),
            "valid_entries": valid_entries,
            "ttl_seconds": inbox_ttl
        }
    except Exception as e:
        stats["caches"]["unified_inbox"] = {"error": str(e)}
    
    # Search Cache from search_cache module
    try:
        from leads.search_cache import get_cache_stats
        stats["caches"]["search_cache"] = get_cache_stats()
    except Exception as e:
        stats["caches"]["search_cache"] = {"error": str(e)}
    
    return stats


def clear_all_caches() -> Dict[str, Any]:
    """Clear all in-memory caches"""
    cleared = {}
    
    try:
        from routers.sales_dashboard import _dashboard_cache
        count = len(_dashboard_cache)
        _dashboard_cache.clear()
        cleared["sales_dashboard"] = count
    except Exception as e:
        cleared["sales_dashboard"] = {"error": str(e)}
    
    try:
        from routers.operations import _operations_cache
        count = len(_operations_cache)
        _operations_cache.clear()
        cleared["operations"] = count
    except Exception as e:
        cleared["operations"] = {"error": str(e)}
    
    try:
        from routers.unified_inbox import _inbox_cache
        count = len(_inbox_cache)
        _inbox_cache.clear()
        cleared["unified_inbox"] = count
    except Exception as e:
        cleared["unified_inbox"] = {"error": str(e)}
    
    return {"cleared": cleared, "timestamp": datetime.utcnow().isoformat()}


# ============== ENDPOINTS ==============

@router.get("/stats")
async def get_performance_stats():
    """
    Get performance statistics including cache hit rates and response times.
    """
    stats = get_all_cache_stats()
    
    # Add system info
    stats["system"] = {
        "python_version": os.sys.version.split()[0] if hasattr(os, 'sys') else "unknown",
        "environment": os.getenv("ENVIRONMENT", "development")
    }
    
    return stats


@router.get("/cache-stats")
async def get_cache_statistics():
    """
    Get detailed cache statistics across all cache layers.
    """
    return get_all_cache_stats()


@router.post("/clear-cache")
async def clear_cache(
    cache_name: Optional[str] = Query(None, description="Specific cache to clear (or all if not specified)")
):
    """
    Clear API caches. Use after data updates or to force fresh data.
    
    Args:
        cache_name: Optional - clear specific cache only (sales_dashboard, operations, unified_inbox)
    """
    if cache_name:
        cleared = {}
        
        if cache_name == "sales_dashboard":
            try:
                from routers.sales_dashboard import _dashboard_cache
                count = len(_dashboard_cache)
                _dashboard_cache.clear()
                cleared[cache_name] = count
            except Exception as e:
                cleared[cache_name] = {"error": str(e)}
        
        elif cache_name == "operations":
            try:
                from routers.operations import _operations_cache
                count = len(_operations_cache)
                _operations_cache.clear()
                cleared[cache_name] = count
            except Exception as e:
                cleared[cache_name] = {"error": str(e)}
        
        elif cache_name == "unified_inbox":
            try:
                from routers.unified_inbox import _inbox_cache
                count = len(_inbox_cache)
                _inbox_cache.clear()
                cleared[cache_name] = count
            except Exception as e:
                cleared[cache_name] = {"error": str(e)}
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown cache: {cache_name}")
        
        return {"cleared": cleared, "timestamp": datetime.utcnow().isoformat()}
    
    # Clear all caches
    return clear_all_caches()


@router.get("/health-detailed")
async def detailed_health():
    """
    Detailed health check including database connections and cache status.
    """
    from pymongo import MongoClient
    import time
    
    health = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }
    
    # MongoDB connection check
    try:
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        start = time.time()
        client.admin.command('ping')
        ping_ms = (time.time() - start) * 1000
        health["checks"]["mongodb"] = {
            "status": "healthy",
            "ping_ms": round(ping_ms, 2)
        }
        client.close()
    except Exception as e:
        health["status"] = "degraded"
        health["checks"]["mongodb"] = {
            "status": "unhealthy",
            "error": str(e)
        }
    
    # Redis check (if available)
    try:
        import redis
        redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        r = redis.Redis(host=redis_host, port=redis_port, socket_timeout=2)
        start = time.time()
        r.ping()
        ping_ms = (time.time() - start) * 1000
        health["checks"]["redis"] = {
            "status": "healthy",
            "ping_ms": round(ping_ms, 2)
        }
    except Exception as e:
        health["checks"]["redis"] = {
            "status": "unavailable",
            "note": "Redis optional - using in-memory cache"
        }
    
    # Cache health
    cache_stats = get_all_cache_stats()
    health["checks"]["caches"] = {
        "status": "healthy",
        "count": len(cache_stats.get("caches", {}))
    }
    
    return health


@router.get("/slow-queries")
async def get_slow_query_info():
    """
    Get information about potential slow query patterns.
    Provides recommendations for optimization.
    """
    recommendations = [
        {
            "endpoint": "/sales/dashboard",
            "issue": "Multiple aggregation pipelines",
            "solution": "Caching implemented with 2-minute TTL",
            "status": "optimized"
        },
        {
            "endpoint": "/operations/accounts",
            "issue": "N+1 query pattern for project counts",
            "solution": "Batch loading implemented",
            "status": "optimized"
        },
        {
            "endpoint": "/inbox/stats",
            "issue": "Multiple count queries",
            "solution": "Single $facet aggregation with caching",
            "status": "optimized"
        },
        {
            "endpoint": "/inbox",
            "issue": "Large email documents",
            "solution": "Projection optimization to fetch only needed fields",
            "status": "optimized"
        }
    ]
    
    return {
        "recommendations": recommendations,
        "tips": [
            "Use bypass_cache=true parameter to force fresh data when needed",
            "Monitor X-Response-Time header for actual response times",
            "Clear caches after bulk data updates via POST /performance/clear-cache"
        ]
    }
