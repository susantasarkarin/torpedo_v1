"""
LinkedIn Automation Jobs Queue
Manages queuing of LinkedIn automation tasks
"""

import logging
from typing import Optional
from datetime import datetime
from linkedin_automation.service import LinkedInService
from linkedin_automation.models import TaskType

logger = logging.getLogger(__name__)
service = LinkedInService()


def queue_linkedin_automation(
    account_id: str,
    task_type: TaskType = TaskType.ALL
) -> str:
    """
    Queue a LinkedIn automation job for execution
    Returns the job ID
    """
    try:
        job = service.create_job(account_id, task_type)
        job_id = str(job["_id"])
        logger.info(f"Queued job {job_id} for account {account_id} with task type {task_type}")
        return job_id
    except Exception as e:
        logger.error(f"Error queuing automation: {str(e)}")
        raise
