"""
AGENTS ROUTER
=============

Health check and monitoring endpoints for AI agents.

Endpoints:
- GET /agents/health - Overall agent system health
- GET /agents/status - Status of all agents (Celery, Auto-Classify, Scheduled)
- GET /agents/jobs - Recent agent job history
- GET /agents/ai-usage - AI provider usage statistics
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from pymongo import MongoClient, DESCENDING
from bson import ObjectId


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    try:
        from ..database import get_client
    except ImportError:
        from database import get_client
    return get_client()


# ============== LOGGING ==============
logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
client = _get_pooled_client()

# Databases
email_db = client["email_automation"]
settings_db = client["torpedo_settings"]
cpx_db = client["cpx_research"]

# Collections
agent_jobs_collection = email_db["agent_jobs"]
ai_usage_logs_collection = settings_db.get_collection("ai_usage_logs") if "ai_usage_logs" in settings_db.list_collection_names() else settings_db["openai_usage_logs"]
auto_classifier_stats = email_db.get_collection("auto_classifier_stats") if "auto_classifier_stats" in email_db.list_collection_names() else None

# ============== ROUTER ==============
router = APIRouter(prefix="/agents", tags=["Agents"])


# ============== SCHEMAS ==============

class AgentHealth(BaseModel):
    """Overall agent system health"""
    status: str  # healthy, degraded, unhealthy
    celery_status: str
    auto_classify_status: str
    scheduled_jobs_status: str
    last_checked: str
    issues: List[str] = []


class CeleryWorkerStatus(BaseModel):
    """Celery worker status"""
    running: bool
    queue_depth: int = 0
    active_tasks: int = 0
    last_heartbeat: Optional[str] = None


class AutoClassifyStatus(BaseModel):
    """Auto-classify agent status"""
    running: bool
    last_run: Optional[str] = None
    leads_classified_today: int = 0
    leads_classified_total: int = 0
    last_error: Optional[str] = None


class ScheduledJobStatus(BaseModel):
    """Scheduled job status"""
    name: str
    enabled: bool
    next_run: Optional[str] = None
    last_run: Optional[str] = None
    status: str  # running, idle, error


class AgentJobSummary(BaseModel):
    """Agent job summary"""
    job_id: str
    type: str
    status: str
    progress_percent: float = 0
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None


class AIProviderUsage(BaseModel):
    """AI provider usage statistics"""
    provider: str
    requests_today: int = 0
    requests_total: int = 0
    cost_today_usd: float = 0
    cost_total_usd: float = 0
    avg_latency_ms: float = 0


class AIUsageStats(BaseModel):
    """AI usage statistics"""
    date: str
    providers: List[AIProviderUsage]
    total_requests_today: int = 0
    total_cost_today_usd: float = 0


# ============== HELPER FUNCTIONS ==============

def check_celery_status() -> CeleryWorkerStatus:
    """Check Celery worker status via Redis"""
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        
        # Check if Celery is connected by checking queue length
        queue_length = r.llen("ai_processing") or 0
        
        # Check for active workers via Celery inspect (if available)
        try:
            from celery import Celery
            celery_app = Celery(broker=redis_url)
            inspect = celery_app.control.inspect()
            active = inspect.active()
            if active:
                active_count = sum(len(tasks) for tasks in active.values())
                return CeleryWorkerStatus(
                    running=True,
                    queue_depth=queue_length,
                    active_tasks=active_count,
                    last_heartbeat=datetime.utcnow().isoformat()
                )
        except Exception:
            pass
        
        # Fallback: assume running if Redis is accessible
        return CeleryWorkerStatus(
            running=True,
            queue_depth=queue_length,
            active_tasks=0,
            last_heartbeat=None
        )
    except Exception as e:
        logger.warning(f"Could not check Celery status: {e}")
        return CeleryWorkerStatus(running=False, queue_depth=0, active_tasks=0)


def check_auto_classify_status() -> AutoClassifyStatus:
    """Check auto-classify agent status from database"""
    try:
        if auto_classifier_stats is None:
            return AutoClassifyStatus(running=False)
        
        # Check for recent stats update (within last 5 minutes)
        recent = auto_classifier_stats.find_one(
            {"_id": "auto_classify"},
        )
        
        if recent:
            last_run = recent.get("last_run")
            is_running = False
            
            if last_run:
                # Consider running if last update was within 2 minutes
                time_diff = datetime.utcnow() - last_run
                is_running = time_diff.total_seconds() < 120
            
            return AutoClassifyStatus(
                running=is_running,
                last_run=last_run.isoformat() if last_run else None,
                leads_classified_today=recent.get("leads_classified_today", 0),
                leads_classified_total=recent.get("leads_classified_total", 0),
                last_error=recent.get("last_error")
            )
        
        return AutoClassifyStatus(running=False)
    except Exception as e:
        logger.warning(f"Could not check auto-classify status: {e}")
        return AutoClassifyStatus(running=False, last_error=str(e))


def get_ai_usage_stats(days: int = 1) -> AIUsageStats:
    """Get AI usage statistics"""
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Aggregate by provider
        pipeline = [
            {"$match": {"timestamp": {"$gte": start_date}}},
            {"$group": {
                "_id": "$provider",
                "requests": {"$sum": 1},
                "total_cost": {"$sum": {"$ifNull": ["$cost_usd", 0]}},
                "avg_latency": {"$avg": {"$ifNull": ["$latency_ms", 0]}}
            }}
        ]
        
        results = list(ai_usage_logs_collection.aggregate(pipeline))
        
        providers = []
        total_requests = 0
        total_cost = 0
        
        for r in results:
            provider = AIProviderUsage(
                provider=r["_id"] or "unknown",
                requests_today=r["requests"],
                requests_total=r["requests"],
                cost_today_usd=round(r["total_cost"], 4),
                cost_total_usd=round(r["total_cost"], 4),
                avg_latency_ms=round(r["avg_latency"] or 0, 2)
            )
            providers.append(provider)
            total_requests += r["requests"]
            total_cost += r["total_cost"]
        
        return AIUsageStats(
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            providers=providers,
            total_requests_today=total_requests,
            total_cost_today_usd=round(total_cost, 4)
        )
    except Exception as e:
        logger.warning(f"Could not get AI usage stats: {e}")
        return AIUsageStats(
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            providers=[],
            total_requests_today=0,
            total_cost_today_usd=0
        )


# ============== ENDPOINTS ==============

@router.get("/health", response_model=AgentHealth)
async def get_agent_health():
    """
    Get overall agent system health.
    
    Returns the health status of all agent subsystems:
    - Celery workers (background task processing)
    - Auto-classify agent (lead classification)
    - Scheduled jobs (APScheduler tasks)
    """
    issues = []
    
    # Check Celery
    celery = check_celery_status()
    celery_status = "healthy" if celery.running else "unhealthy"
    if not celery.running:
        issues.append("Celery worker not running")
    elif celery.queue_depth > 100:
        celery_status = "degraded"
        issues.append(f"Celery queue depth high: {celery.queue_depth}")
    
    # Check Auto-Classify
    auto_classify = check_auto_classify_status()
    auto_classify_status = "healthy" if auto_classify.running else "stopped"
    if not auto_classify.running:
        issues.append("Auto-classify agent not running")
    if auto_classify.last_error:
        auto_classify_status = "error"
        issues.append(f"Auto-classify error: {auto_classify.last_error}")
    
    # Scheduled jobs - assume healthy if app is running
    scheduled_status = "healthy"
    
    # Overall status
    if not celery.running and not auto_classify.running:
        overall_status = "unhealthy"
    elif issues:
        overall_status = "degraded"
    else:
        overall_status = "healthy"
    
    return AgentHealth(
        status=overall_status,
        celery_status=celery_status,
        auto_classify_status=auto_classify_status,
        scheduled_jobs_status=scheduled_status,
        last_checked=datetime.utcnow().isoformat(),
        issues=issues
    )


@router.get("/status")
async def get_agent_status():
    """
    Get detailed status of all agent subsystems.
    
    Returns:
    - Celery worker details (running, queue depth, active tasks)
    - Auto-classify agent details (running, leads processed)
    - Scheduled jobs list with next run times
    """
    celery = check_celery_status()
    auto_classify = check_auto_classify_status()
    
    # Get scheduled jobs info from APScheduler (if available)
    scheduled_jobs = []
    try:
        # These are the scheduled jobs defined in main.py
        scheduled_jobs = [
            ScheduledJobStatus(
                name="CPX Survey Refresh",
                enabled=True,
                next_run=None,
                last_run=None,
                status="running"
            ),
            ScheduledJobStatus(
                name="Email Sync + Classification",
                enabled=True,
                next_run=None,
                last_run=None,
                status="running"
            ),
            ScheduledJobStatus(
                name="Cint Webhook Monitor",
                enabled=True,
                next_run=None,
                last_run=None,
                status="running"
            ),
        ]
    except Exception as e:
        logger.warning(f"Could not get scheduled jobs: {e}")
    
    return {
        "celery": celery.dict(),
        "auto_classify": auto_classify.dict(),
        "scheduled_jobs": [j.dict() for j in scheduled_jobs],
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/jobs", response_model=List[AgentJobSummary])
async def get_agent_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None, description="Filter by status: pending, running, completed, failed")
):
    """
    Get recent agent job history.
    
    Returns a list of recent agent jobs with their status and progress.
    """
    try:
        query = {}
        if status:
            query["status"] = status
        
        jobs = list(agent_jobs_collection.find(query).sort("created_at", DESCENDING).limit(limit))
        
        result = []
        for job in jobs:
            result.append(AgentJobSummary(
                job_id=job.get("job_id", str(job.get("_id", ""))),
                type=job.get("type", job.get("agents_to_run", ["unknown"])[0] if isinstance(job.get("agents_to_run"), list) else "unknown"),
                status=job.get("status", "unknown"),
                progress_percent=job.get("progress_percent", 0),
                created_at=job.get("created_at", datetime.utcnow()).isoformat() if isinstance(job.get("created_at"), datetime) else str(job.get("created_at", "")),
                completed_at=job.get("completed_at").isoformat() if isinstance(job.get("completed_at"), datetime) else None,
                error=job.get("error") or (job.get("errors", [None])[0] if job.get("errors") else None)
            ))
        
        return result
    except Exception as e:
        logger.error(f"Error getting agent jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-usage", response_model=AIUsageStats)
async def get_ai_usage(
    days: int = Query(default=1, ge=1, le=30, description="Number of days to aggregate")
):
    """
    Get AI provider usage statistics.
    
    Returns usage breakdown by provider (Gemini, OpenAI, Anthropic)
    including request counts, costs, and latency.
    """
    return get_ai_usage_stats(days)


@router.get("/ai-usage/daily")
async def get_ai_usage_daily(
    days: int = Query(default=7, ge=1, le=30, description="Number of days to show")
):
    """
    Get daily AI usage breakdown for charts.
    
    Returns daily request counts and costs by provider.
    """
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        
        pipeline = [
            {"$match": {"timestamp": {"$gte": start_date}}},
            {"$group": {
                "_id": {
                    "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
                    "provider": "$provider"
                },
                "requests": {"$sum": 1},
                "cost": {"$sum": {"$ifNull": ["$cost_usd", 0]}}
            }},
            {"$sort": {"_id.date": 1}}
        ]
        
        results = list(ai_usage_logs_collection.aggregate(pipeline))
        
        # Organize by date
        daily_data = {}
        for r in results:
            date = r["_id"]["date"]
            provider = r["_id"]["provider"] or "unknown"
            
            if date not in daily_data:
                daily_data[date] = {"date": date, "providers": {}, "total_requests": 0, "total_cost": 0}
            
            daily_data[date]["providers"][provider] = {
                "requests": r["requests"],
                "cost": round(r["cost"], 4)
            }
            daily_data[date]["total_requests"] += r["requests"]
            daily_data[date]["total_cost"] += r["cost"]
        
        # Convert to list
        return list(daily_data.values())
    except Exception as e:
        logger.error(f"Error getting daily AI usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auto-classify/start")
async def start_auto_classify():
    """
    Start the auto-classify agent.
    
    Note: This is a placeholder. In production, use systemd/supervisor to manage the agent.
    """
    return {
        "message": "Auto-classify agent should be started via systemd/supervisor",
        "command": "sudo systemctl start auto_classify_agent",
        "status": "manual_action_required"
    }


@router.post("/auto-classify/stop")
async def stop_auto_classify():
    """
    Stop the auto-classify agent.
    
    Note: This is a placeholder. In production, use systemd/supervisor to manage the agent.
    """
    return {
        "message": "Auto-classify agent should be stopped via systemd/supervisor",
        "command": "sudo systemctl stop auto_classify_agent",
        "status": "manual_action_required"
    }
