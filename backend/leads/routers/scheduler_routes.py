"""
leads/routers/scheduler_routes.py
===================================
Route group: Lead ingestion scheduler (start/stop/status/logs/config).
Registered via register_scheduler_routes(router) in leads/router.py.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from ..scheduler import (
    start_scheduler, stop_scheduler, get_scheduler_status,
    get_scheduler_logs, update_scheduler_config
)


def register_scheduler_routes(router: APIRouter):

    # ============== LEAD SCHEDULER ENDPOINTS ==============

    class SchedulerConfigRequest(BaseModel):
        """Request model for scheduler configuration"""
        designations: Optional[List[str]] = None
        countries: Optional[List[str]] = None
        seniorities: Optional[List[str]] = None
        custom_query: Optional[str] = None

    @router.post("/scheduler/start")
    async def start_scheduler_endpoint(config: Optional[SchedulerConfigRequest] = None):
        """
        POST /leads/scheduler/start
        Start the lead ingestion scheduler.

        Optional body:
        {
            "designations": ["CEO", "CTO"],
            "countries": ["United States", "Canada"],
            "seniorities": ["CXO", "VP"],
            "custom_query": "technology startup"
        }
        """
        try:
            config_dict = config.model_dump() if config else None
            result = start_scheduler(config_dict)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/scheduler/stop")
    async def stop_scheduler_endpoint():
        """POST /leads/scheduler/stop — Stop the lead ingestion scheduler."""
        try:
            result = stop_scheduler()
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/scheduler/status")
    async def get_scheduler_status_endpoint():
        """
        GET /leads/scheduler/status
        Get current scheduler status including running state, leads today/this hour,
        progress percentages, and error count.
        """
        try:
            status = get_scheduler_status()
            return status
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/scheduler/logs")
    async def get_scheduler_logs_endpoint(limit: int = Query(100, ge=1, le=500)):
        """GET /leads/scheduler/logs — Get recent scheduler activity logs."""
        try:
            logs = get_scheduler_logs(limit)
            return {"logs": logs, "count": len(logs)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.put("/scheduler/config")
    async def update_scheduler_config_endpoint(config: SchedulerConfigRequest):
        """PUT /leads/scheduler/config — Update scheduler search configuration."""
        try:
            result = update_scheduler_config(config.model_dump())
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
