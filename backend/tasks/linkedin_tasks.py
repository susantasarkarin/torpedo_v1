"""
LinkedIn Automation Celery Tasks
Scheduled and background tasks for LinkedIn account automation.
"""

import logging
from datetime import datetime
from typing import Optional

from celery_app import celery_app
from linkedin_automation.service import LinkedInService
from linkedin_automation.job import LinkedInBotFactory
from linkedin_automation.models import (
    TaskType,
    JobStatus,
    LinkedInBotConfig
)

logger = logging.getLogger(__name__)
service = LinkedInService()


@celery_app.task(bind=True, queue='linkedin_automation', max_retries=3)
def run_linkedin_account_automation(
    self,
    account_id: str,
    task_type: str = "all",
    bot_config: Optional[dict] = None
):
    """
    Execute LinkedIn automation for a single account
    
    This task:
    1. Retrieves account credentials from database
    2. Initializes Selenium bot
    3. Executes automation tasks
    4. Records job results in database
    5. Handles errors and retries
    
    Args:
        account_id: MongoDB account ID
        task_type: Type of task to execute (all, send_connections, etc.)
        bot_config: Optional bot configuration override
    """
    job_id = None
    
    try:
        # Validate task type
        task_type_enum = TaskType[task_type.upper()] if isinstance(task_type, str) else task_type
        
        # Get account with decrypted password
        service.set_account_status(account_id, "running")
        account = service.get_account_with_password(account_id)
        
        logger.info(f"Starting LinkedIn automation for account {account.get('email')}")
        
        # Create bot configuration
        if bot_config:
            config = LinkedInBotConfig(**bot_config)
        else:
            config = LinkedInBotConfig()
        
        # Execute automation
        results = LinkedInBotFactory.execute_automation(
            email=account['email'],
            password=account['password'],
            config=config
        )
        
        logger.info(f"Automation completed. Results: {results.model_dump()}")
        
        # Record results in database
        job = service.create_job(account_id, task_type_enum)
        job_id = str(job["_id"])
        
        # Determine job status based on results
        job_status = JobStatus.COMPLETED if not results.errors else JobStatus.COMPLETED
        
        service.update_job_status(
            job_id=job_id,
            status=job_status,
            results=results,
            error_message="; ".join(results.errors) if results.errors else None
        )
        
        # Update account last run time
        service.update_account_last_run(account_id)
        service.set_account_status(account_id, "idle")
        
        logger.info(f"Job {job_id} completed successfully")
        return {
            "status": "success",
            "job_id": job_id,
            "results": results.model_dump()
        }
    
    except Exception as e:
        logger.error(f"Error in LinkedIn automation: {str(e)}", exc_info=True)
        
        # Mark job as failed
        if job_id:
            service.update_job_status(
                job_id=job_id,
                status=JobStatus.FAILED,
                error_message=str(e)
            )
        
        # Update account status
        service.set_account_status(account_id, "error")
        
        # Retry logic
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying task. Attempt {self.request.retries + 1}/{self.max_retries}")
            raise self.retry(exc=e, countdown=300)  # Retry after 5 minutes
        
        return {
            "status": "failed",
            "job_id": job_id,
            "error": str(e)
        }


@celery_app.task(queue='linkedin_automation')
def run_daily_linkedin_automation():
    """
    Daily scheduled task to run automation for all enabled accounts
    
    This task:
    1. Fetches all active accounts with enabled schedules
    2. Checks if current time matches their schedule
    3. Queues automation tasks for matching accounts
    4. Returns summary of queued jobs
    """
    try:
        logger.info("Starting daily LinkedIn automation scheduler")
        
        # Get all accounts to run
        accounts = service.get_accounts_to_run()
        
        if not accounts:
            logger.info("No accounts scheduled to run")
            return {
                "status": "success",
                "accounts_scheduled": 0,
                "tasks_queued": 0
            }
        
        # Queue tasks for each account
        queued_count = 0
        for account in accounts:
            try:
                account_id = str(account["_id"])
                task_type = account.get("schedule", {}).get("default_task_type", "all")
                
                # Queue the task
                task = run_linkedin_account_automation.apply_async(
                    args=[account_id, task_type],
                    queue='linkedin_automation'
                )
                
                logger.info(f"Queued automation for account {account.get('email')}, task ID: {task.id}")
                queued_count += 1
            
            except Exception as e:
                logger.error(f"Error queueing account {account.get('email')}: {str(e)}")
                continue
        
        logger.info(f"Daily automation scheduler completed. {queued_count} accounts queued")
        return {
            "status": "success",
            "accounts_checked": len(accounts),
            "tasks_queued": queued_count
        }
    
    except Exception as e:
        logger.error(f"Error in daily automation scheduler: {str(e)}", exc_info=True)
        return {
            "status": "failed",
            "error": str(e)
        }


@celery_app.task(queue='linkedin_automation')
def cleanup_old_jobs(days=30):
    """
    Cleanup old job records (older than specified days)
    
    Args:
        days: Delete jobs older than this many days (default: 30)
    """
    try:
        from datetime import datetime, timedelta
        from database import DatabaseManager
        from bson import ObjectId
        
        db_manager = DatabaseManager()
        collection = db_manager.get_collection("linkedin_db", "automation_jobs")
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        result = collection.delete_many({"started_at": {"$lt": cutoff_date}})
        
        logger.info(f"Cleaned up {result.deleted_count} old job records")
        return {
            "status": "success",
            "deleted_count": result.deleted_count
        }
    
    except Exception as e:
        logger.error(f"Error cleaning up old jobs: {str(e)}")
        return {
            "status": "failed",
            "error": str(e)
        }
