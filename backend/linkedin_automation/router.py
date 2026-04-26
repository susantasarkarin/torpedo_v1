"""
LinkedIn Automation Router
FastAPI endpoints for managing LinkedIn accounts and executing automation.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from datetime import datetime

from backend.linkedin_automation.service import LinkedInService
from backend.linkedin_automation.models import (
    LinkedInAccountCreate,
    LinkedInAccountUpdate,
    LinkedInAccountResponse,
    LinkedInOpportunityIngestRequest,
    LinkedInOpportunityResponse,
    LinkedInOpportunityUpdate,
    OpportunityStatus,
    TaskType,
    LinkedInBotConfig
)
from backend.linkedin_automation.jobs_queue import queue_linkedin_automation

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/marketing/linkedin",
    tags=["Marketing - LinkedIn Automation"]
)

service = LinkedInService()


@router.post("/accounts", response_model=LinkedInAccountResponse)
async def create_account(account_data: LinkedInAccountCreate):
    """
    Create a new LinkedIn account
    
    Stores email and password securely with encryption.
    Schedule can be configured for daily or custom execution.
    """
    try:
        account = service.create_account(account_data)
        return account
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating account: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create account")


@router.get("/accounts", response_model=List[LinkedInAccountResponse])
async def list_accounts(active_only: bool = Query(True)):
    """
    List all LinkedIn accounts
    
    ?active_only=true - Only show active accounts (default)
    ?active_only=false - Show all accounts including inactive
    """
    try:
        accounts = service.list_accounts(active_only=active_only)
        return accounts
    except Exception as e:
        logger.error(f"Error listing accounts: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list accounts")


@router.get("/accounts/{account_id}", response_model=LinkedInAccountResponse)
async def get_account(account_id: str):
    """
    Get a specific LinkedIn account by ID
    
    Note: Password is not returned. Use /accounts/{id}/credentials endpoint if needed.
    """
    try:
        account = service.get_account(account_id)
        return account
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting account: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get account")


@router.put("/accounts/{account_id}", response_model=LinkedInAccountResponse)
async def update_account(account_id: str, update_data: LinkedInAccountUpdate):
    """
    Update a LinkedIn account
    
    Can update: account_name, active status, schedule configuration
    """
    try:
        account = service.update_account(account_id, update_data)
        return account
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating account: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update account")


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: str):
    """
    Delete (deactivate) a LinkedIn account
    
    Performs a soft delete by setting active=false
    """
    try:
        service.delete_account(account_id)
        return {"message": "Account deleted successfully", "account_id": account_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting account: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete account")


@router.post("/accounts/{account_id}/run")
async def run_automation_now(
    account_id: str,
    background_tasks: BackgroundTasks,
    task_type: TaskType = TaskType.ALL
):
    """
    Manually trigger LinkedIn automation for an account
    
    task_type options: all|send_connections|send_messages|like_posts|repost_posts|comment_posts
    
    Returns immediately with job ID. Execution happens in background.
    """
    try:
        # Verify account exists
        account = service.get_account(account_id)
        
        # Queue the automation task
        job_id = queue_linkedin_automation(
            account_id=account_id,
            task_type=task_type
        )
        
        # Also add to background tasks for immediate processing
        background_tasks.add_task(
            _execute_automation_task,
            account_id=account_id,
            task_type=task_type
        )
        
        return {
            "message": "Automation queued successfully",
            "account_id": account_id,
            "job_id": job_id,
            "task_type": task_type.value
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error queuing automation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to queue automation")


@router.get("/accounts/{account_id}/jobs")
async def get_account_jobs(account_id: str, limit: int = Query(50, ge=1, le=100)):
    """
    Get recent automation jobs for an account
    
    ?limit=50 - Number of recent jobs to retrieve (default: 50, max: 100)
    """
    try:
        # Verify account exists
        service.get_account(account_id)
        
        # Get jobs
        jobs = service.get_account_jobs(account_id, limit=limit)
        
        return {
            "account_id": account_id,
            "total": len(jobs),
            "jobs": jobs
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting jobs: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get jobs")


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """
    Get details of a specific automation job
    """
    try:
        job = service.get_job(job_id)
        return job
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting job: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get job")


@router.get("/dashboard")
async def get_dashboard():
    """
    Get LinkedIn automation dashboard summary
    
    Shows: total accounts, pending jobs, recent activity, error summary
    """
    try:
        accounts = service.list_accounts(active_only=False)
        active_count = len([a for a in accounts if a.active])
        inactive_count = len([a for a in accounts if not a.active])
        
        return {
            "timestamp": datetime.utcnow(),
            "accounts": {
                "total": len(accounts),
                "active": active_count,
                "inactive": inactive_count
            },
            "recent_runs": []  # TODO: Query recent jobs
        }
    except Exception as e:
        logger.error(f"Error getting dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get dashboard")


@router.post("/update-schedule/{account_id}")
async def update_schedule(account_id: str, schedule: dict):
    """
    Update the automation schedule for an account
    
    Example body:
    {
        "frequency": "daily",
        "run_time": "02:00",
        "days_of_week": null,
        "enabled": true
    }
    """
    try:
        from backend.linkedin_automation.models import LinkedInScheduleConfig
        
        schedule_config = LinkedInScheduleConfig(**schedule)
        update_data = LinkedInAccountUpdate(schedule=schedule_config)
        
        account = service.update_account(account_id, update_data)
        return {
            "message": "Schedule updated successfully",
            "account": account
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating schedule: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update schedule")


@router.post("/opportunities/ingest", response_model=LinkedInOpportunityResponse)
async def ingest_opportunity(payload: LinkedInOpportunityIngestRequest):
    """Record an inbound LinkedIn message/comment as an opportunity candidate."""
    try:
        return service.ingest_opportunity(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error ingesting LinkedIn opportunity: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to ingest opportunity")


@router.get("/opportunities", response_model=List[LinkedInOpportunityResponse])
async def list_opportunities(
    status: Optional[OpportunityStatus] = Query(None),
    division_owner: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
):
    """List recent LinkedIn opportunities with filters for status and owner."""
    try:
        status_value = status.value if status is not None else None
        return service.list_opportunities(
            status=status_value,
            division_owner=division_owner,
            days=days,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"Error listing LinkedIn opportunities: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list opportunities")


@router.get("/opportunities/dashboard")
async def get_opportunities_dashboard(days: int = Query(30, ge=1, le=365)):
    """Return a funnel-style dashboard summary for LinkedIn-sourced opportunities."""
    try:
        return service.get_opportunity_dashboard(days=days)
    except Exception as e:
        logger.error(f"Error getting LinkedIn opportunities dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get opportunities dashboard")


@router.get("/opportunities/{opportunity_id}", response_model=LinkedInOpportunityResponse)
async def get_opportunity(opportunity_id: str):
    """Get a specific LinkedIn opportunity."""
    try:
        return service.get_opportunity(opportunity_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting LinkedIn opportunity: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get opportunity")


@router.patch("/opportunities/{opportunity_id}", response_model=LinkedInOpportunityResponse)
async def update_opportunity(opportunity_id: str, update_data: LinkedInOpportunityUpdate):
    """Update status, owner, notes, and draft for a LinkedIn opportunity."""
    try:
        return service.update_opportunity(opportunity_id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating LinkedIn opportunity: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update opportunity")


async def _execute_automation_task(account_id: str, task_type: TaskType):
    """Background task for executing automation"""
    try:
        from backend.tasks.linkedin_tasks import run_linkedin_account_automation
        
        logger.info(f"Executing LinkedIn automation for account {account_id}")
        # This will call the Celery task which handles execution
        result = run_linkedin_account_automation.apply_async(
            args=[account_id, task_type.value],
            queue='linkedin_automation'
        )
        logger.info(f"Task submitted with ID: {result.id}")
    except Exception as e:
        logger.error(f"Error executing automation task: {str(e)}")
