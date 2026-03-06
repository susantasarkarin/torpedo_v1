"""
LinkedIn Automation Module
Integrates LinkedIn account management and automation into Torpedo.

This module provides:
- Account credential management with encryption
- Selenium-based LinkedIn bot for automation
- Scheduled and manual automation execution
- Job tracking and result recording
- RESTful API for integration with the Marketing Module

Database: linkedin_db
Collections:
  - accounts: LinkedIn account credentials and configuration
  - automation_jobs: Job execution history and results
  - job_logs: Detailed execution logs
"""

from .service import LinkedInService
from .models import (
    LinkedInAccountCreate,
    LinkedInAccountUpdate,
    LinkedInAccountResponse,
    LinkedInAutomationJob,
    LinkedInJobResult,
    TaskType,
    JobStatus,
    FrequencyType,
    LinkedInBotConfig
)
from . import router

__all__ = [
    'LinkedInService',
    'LinkedInAccountCreate',
    'LinkedInAccountUpdate',
    'LinkedInAccountResponse',
    'LinkedInAutomationJob',
    'LinkedInJobResult',
    'TaskType',
    'JobStatus',
    'FrequencyType',
    'LinkedInBotConfig',
    'router',
]
