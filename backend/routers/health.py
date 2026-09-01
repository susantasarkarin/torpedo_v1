"""
Health Check Router - System health monitoring endpoints
"""
from fastapi import APIRouter
from typing import Dict, Any
from datetime import datetime
import os

router = APIRouter(
    prefix="/health",
    tags=["health"]
)


@router.get("/")
async def health_check() -> Dict[str, Any]:
    """
    Basic health check endpoint.
    Returns system status and timestamp.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": os.getenv("APP_VERSION", "1.0.0")
    }


@router.get("/redis")
async def redis_health() -> Dict[str, Any]:
    """
    Check Redis session store health.
    Returns detailed Redis connection status.
    """
    from session_store import SessionStore
    
    store = await SessionStore.get_instance()
    return await store.health_check()


@router.get("/detailed")
async def detailed_health() -> Dict[str, Any]:
    """
    Comprehensive health check including all dependencies.
    """
    from pymongo import MongoClient
    
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {}
    }
    
    # Check MongoDB
    try:
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        health_status["components"]["mongodb"] = {
            "status": "healthy",
            "host": mongo_uri.split("@")[-1].split("/")[0] if "@" in mongo_uri else mongo_uri.split("//")[-1].split("/")[0]
        }
    except Exception as e:
        health_status["components"]["mongodb"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Check Redis
    try:
        from session_store import SessionStore
        
        store = await SessionStore.get_instance()
        redis_health = await store.health_check()
        health_status["components"]["redis"] = redis_health
        if redis_health.get("status") != "healthy":
            # Redis being unavailable is acceptable (fallback to in-memory)
            if health_status["status"] == "healthy":
                health_status["status"] = "healthy"  # Keep healthy, Redis is optional
            health_status["components"]["redis"]["note"] = "Optional - using in-memory fallback if unavailable"
    except Exception as e:
        health_status["components"]["redis"] = {
            "status": "error",
            "error": str(e),
            "note": "Optional - using in-memory fallback"
        }
    
    return health_status
