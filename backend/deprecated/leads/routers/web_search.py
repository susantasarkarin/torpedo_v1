"""Web-search route registrations extracted from leads/router.py (Phase 12)."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ..router_shared import (
    LEADS_PER_MINUTE,
    JobStatus,
    WebSearchRequest,
    create_job,
    get_global_search_control,
    get_job,
    get_rate_limit_settings,
    run_web_search_job,
    set_global_search_control,
    stop_all_jobs,
    update_job,
    web_search_jobs_collection,
)


def register_web_search_routes(router: APIRouter) -> None:
    @router.post("/import/web-search")
    async def import_from_web_search(
        request: WebSearchRequest,
        background_tasks: BackgroundTasks,
    ):
        """
        POST /leads/import/web-search
        Start background web search job that runs until target_count is reached.

        Features:
        - Runs in background, returns job_id immediately
        - Rate limits to ~7 leads/min (10,000/day max)
        - Auto-classifies leads with email prediction
        - Pauses on quota exceeded, auto-resumes at midnight UTC
        - Persists to MongoDB for resume on restart

        Use GET /leads/import/web-search/status/{job_id} to check progress.
        Use POST /leads/import/web-search/stop/{job_id} to stop.
        """
        try:
            # Starting a fresh job should clear stale global pause/circuit flags.
            control = get_global_search_control()
            if (
                control.get("paused")
                or control.get("circuit_breaker_open")
                or control.get("consecutive_errors", 0) > 0
            ):
                set_global_search_control(
                    {
                        "paused": False,
                        "paused_at": None,
                        "paused_reason": "",
                        "circuit_breaker_open": False,
                        "consecutive_errors": 0,
                    }
                )

            # Auto-heal zombie jobs: if a RUNNING/PENDING job hasn't updated recently,
            # mark it stopped so it doesn't block new search starts forever.
            stale_cutoff = datetime.utcnow() - timedelta(minutes=15)
            web_search_jobs_collection.update_many(
                {
                    "status": {"$in": [JobStatus.RUNNING, JobStatus.PENDING]},
                    "$or": [
                        {"last_update": {"$lt": stale_cutoff}},
                        {"last_update": None, "created_at": {"$lt": stale_cutoff}},
                    ],
                },
                {
                    "$set": {
                        "status": JobStatus.STOPPED,
                        "last_update": datetime.utcnow(),
                        "stopped_reason": "auto-stopped stale job on new start request",
                    }
                },
            )

            # Check for already running job
            running_jobs = list(
                web_search_jobs_collection.find(
                    {"status": {"$in": [JobStatus.RUNNING, JobStatus.PENDING]}}
                )
            )
            if running_jobs:
                return {
                    "success": False,
                    "message": "A search job is already running",
                    "job_id": running_jobs[0]["job_id"],
                    "status": running_jobs[0]["status"],
                }

            # Parse inputs
            countries = request.countries if request.countries else ([request.country] if request.country else [])
            seniorities = request.seniorities if request.seniorities else ([request.seniority] if request.seniority else [])
            designations = [d.strip() for d in request.designation.split(",")] if request.designation else []
            industries = request.industries if request.industries else ([request.industry] if request.industry else [])

            if not designations and not countries and not seniorities and not request.custom_query and not industries:
                raise ValueError(
                    "At least one search filter (designation, country, seniority, industry, or custom_query) is required"
                )

            # No target limit - job runs continuously until stopped (controlled by rate limits)
            target_count = 999999999  # Effectively unlimited

            # Create job config
            config = {
                "designations": designations,
                "countries": countries,
                "seniorities": seniorities,
                "industries": industries,
                "custom_query": request.custom_query,
                "icp_id": request.icp_id or None,
            }

            # Create job in MongoDB
            job_id = create_job(config, target_count)

            # Start background task
            background_tasks.add_task(run_web_search_job, job_id)

            return {
                "success": True,
                "job_id": job_id,
                "message": "Search job started in continuous mode. Stop manually when done.",
                "status_url": f"/leads/import/web-search/status/{job_id}",
                "stop_url": f"/leads/import/web-search/stop/{job_id}",
            }

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/import/web-search/status/{job_id}")
    async def get_web_search_status(job_id: str):
        """
        GET /leads/import/web-search/status/{job_id}
        Get real-time status of a web search job.
        """
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Calculate progress
        progress_percent = 0
        if job["target_count"] > 0:
            progress_percent = round((job["total_imported"] / job["target_count"]) * 100, 1)

        # Calculate ETA
        eta_minutes = None
        if job["status"] == JobStatus.RUNNING and job["total_imported"] > 0:
            remaining = job["target_count"] - job["total_imported"]
            eta_minutes = int(remaining / LEADS_PER_MINUTE)

        # Get dynamic rate limits for response
        rate_limits = get_rate_limit_settings()

        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "target_count": job["target_count"],
            "total_found": job["total_found"],
            "total_imported": job["total_imported"],
            "total_duplicates": job["total_duplicates"],
            "total_classified": job["total_classified"],
            "emails_found": job["emails_found"],
            "leads_today": job["leads_today"],
            "daily_limit": rate_limits["daily_limit"],
            "rate_limit_enabled": rate_limits["enabled"],
            "queries_used": job["queries_used"],
            "current_query": job.get("current_query", ""),
            "progress_percent": progress_percent,
            "eta_minutes": eta_minutes,
            "errors": job.get("errors", [])[-5:],
            "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
            "started_at": job["started_at"].isoformat() if job.get("started_at") else None,
            "last_update": job["last_update"].isoformat() if job.get("last_update") else None,
            "completed_at": job["completed_at"].isoformat() if job.get("completed_at") else None,
            "config": job.get("config", {}),
        }

    @router.post("/import/web-search/stop/{job_id}")
    async def stop_web_search(job_id: str):
        """
        POST /leads/import/web-search/stop/{job_id}
        Stop a running web search job.
        """
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job["status"] not in [
            JobStatus.RUNNING,
            JobStatus.PENDING,
            JobStatus.PAUSED,
            JobStatus.QUOTA_EXCEEDED,
            JobStatus.API_ERROR,
        ]:
            return {
                "success": False,
                "message": f"Job is not running (status: {job['status']})",
            }

        update_job(job_id, {"status": JobStatus.STOPPED})

        return {
            "success": True,
            "message": "Stop signal sent. Job will stop after current operation.",
            "job_id": job_id,
            "total_imported": job["total_imported"],
        }

    @router.post("/import/web-search/stop-all")
    async def stop_all_web_searches():
        """
        POST /leads/import/web-search/stop-all
        EMERGENCY STOP: Stop ALL running web search jobs immediately.
        Also pauses the global search system to prevent auto-resume.
        """
        stopped_count = stop_all_jobs("Emergency stop - all jobs stopped")

        return {
            "success": True,
            "message": f"Emergency stop executed. {stopped_count} jobs stopped.",
            "jobs_stopped": stopped_count,
            "global_search_paused": True,
            "note": "Use /leads/import/web-search/control to resume search capability",
        }

    @router.get("/import/web-search/control")
    async def get_search_control():
        """
        GET /leads/import/web-search/control
        Get global search control status (pause state, circuit breaker, errors).
        """
        control = get_global_search_control()

        # Get count of active jobs
        active_jobs = web_search_jobs_collection.count_documents(
            {
                "status": {
                    "$in": [
                        JobStatus.RUNNING,
                        JobStatus.PENDING,
                        JobStatus.PAUSED,
                        JobStatus.QUOTA_EXCEEDED,
                    ]
                }
            }
        )

        return {
            "global_paused": control.get("paused", False),
            "paused_at": control.get("paused_at"),
            "paused_reason": control.get("paused_reason", ""),
            "circuit_breaker_open": control.get("circuit_breaker_open", False),
            "consecutive_errors": control.get("consecutive_errors", 0),
            "last_error": control.get("last_error"),
            "auto_resume_disabled": control.get("auto_resume_disabled", False),
            "active_jobs_count": active_jobs,
        }

    @router.post("/import/web-search/control/resume")
    async def resume_search_control():
        """
        POST /leads/import/web-search/control/resume
        Resume global search capability (un-pause, reset circuit breaker).
        Does NOT auto-start any jobs - they must be resumed manually.
        """
        set_global_search_control(
            {
                "paused": False,
                "paused_at": None,
                "paused_reason": "",
                "circuit_breaker_open": False,
                "consecutive_errors": 0,
            }
        )

        return {
            "success": True,
            "message": "Global search resumed. Use /resume/{job_id} to restart individual jobs.",
            "global_paused": False,
            "circuit_breaker_open": False,
        }

    @router.post("/import/web-search/control/pause")
    async def pause_search_control(reason: str = "Manual pause"):
        """
        POST /leads/import/web-search/control/pause
        Pause global search capability. Running jobs will stop at next check.
        """
        set_global_search_control(
            {
                "paused": True,
                "paused_at": datetime.utcnow().isoformat(),
                "paused_reason": reason,
            }
        )

        return {
            "success": True,
            "message": f"Global search paused: {reason}",
            "global_paused": True,
        }

    @router.post("/import/web-search/control/disable-auto-resume")
    async def disable_auto_resume():
        """
        POST /leads/import/web-search/control/disable-auto-resume
        Disable auto-resume of jobs on server restart.
        """
        set_global_search_control(
            {
                "auto_resume_disabled": True,
            }
        )

        return {
            "success": True,
            "message": "Auto-resume on startup disabled. Jobs will not restart automatically.",
            "auto_resume_disabled": True,
        }

    @router.post("/import/web-search/control/enable-auto-resume")
    async def enable_auto_resume():
        """
        POST /leads/import/web-search/control/enable-auto-resume
        Enable auto-resume of jobs on server restart.
        """
        set_global_search_control(
            {
                "auto_resume_disabled": False,
            }
        )

        return {
            "success": True,
            "message": "Auto-resume on startup enabled.",
            "auto_resume_disabled": False,
        }

    @router.get("/import/web-search/jobs")
    async def list_web_search_jobs(
        status: Optional[str] = None,
        limit: int = Query(20, ge=1, le=100),
    ):
        """
        GET /leads/import/web-search/jobs
        List all web search jobs, optionally filtered by status.
        """
        try:
            query = {}
            if status:
                query["status"] = status

            jobs = list(web_search_jobs_collection.find(query).sort("created_at", -1).limit(limit))

            result = []
            for job in jobs:
                target_count = job.get("target_count", 0) or 0
                total_imported = job.get("total_imported", 0) or 0
                progress_percent = 0
                if target_count > 0:
                    progress_percent = round((total_imported / target_count) * 100, 1)

                result.append(
                    {
                        "job_id": job.get("job_id"),
                        "status": job.get("status", "unknown"),
                        "target_count": target_count,
                        "total_imported": total_imported,
                        "progress_percent": progress_percent,
                        "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
                        "config": job.get("config", {}),
                    }
                )

            return {"jobs": result, "count": len(result)}
        except Exception as e:
            print(f"❌ Error listing web search jobs: {type(e).__name__}: {str(e)}")
            import traceback

            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Failed to fetch jobs: {str(e)}")

    @router.post("/import/web-search/resume/{job_id}")
    async def resume_web_search(job_id: str, background_tasks: BackgroundTasks):
        """
        POST /leads/import/web-search/resume/{job_id}
        Resume a paused or stopped job.
        """
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job["status"] in [JobStatus.RUNNING, JobStatus.PENDING]:
            return {
                "success": False,
                "message": "Job is already running",
            }

        if job["status"] == JobStatus.COMPLETED:
            return {
                "success": False,
                "message": "Job is already completed",
            }

        # Reset status and start
        update_job(job_id, {"status": JobStatus.PENDING})
        background_tasks.add_task(run_web_search_job, job_id)

        return {
            "success": True,
            "message": "Job resumed",
            "job_id": job_id,
        }
