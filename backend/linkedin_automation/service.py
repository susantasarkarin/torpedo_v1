"""
LinkedIn Automation Service
Handles account management, credential encryption, and job orchestration.
"""

import logging
from typing import Optional, List
from datetime import datetime
from bson import ObjectId
from cryptography.fernet import Fernet
import os

from backend.database import DatabaseManager
from backend.linkedin_automation.models import (
    LinkedInAccountCreate,
    LinkedInAccountUpdate,
    LinkedInAccountResponse,
    LinkedInAutomationJob,
    LinkedInJobResult,
    JobStatus,
    TaskType
)

logger = logging.getLogger(__name__)


class LinkedInService:
    """Service layer for LinkedIn automation"""
    
    DB_NAME = "linkedin_db"
    ACCOUNTS_COLLECTION = "accounts"
    JOBS_COLLECTION = "automation_jobs"
    JOB_LOGS_COLLECTION = "job_logs"
    
    def __init__(self):
        """Initialize service with encryption key"""
        self.db_manager = DatabaseManager()
        # Get or generate encryption key
        self.cipher_suite = self._get_cipher_suite()
    
    @staticmethod
    def _get_cipher_suite() -> Fernet:
        """Get or initialize encryption cipher suite"""
        encryption_key = os.getenv("LINKEDIN_ENCRYPTION_KEY")
        
        if not encryption_key:
            # Generate a new key if not provided
            encryption_key = Fernet.generate_key().decode()
            logger.warning(
                "LINKEDIN_ENCRYPTION_KEY not set in environment. "
                "Generated new key. Please set it in your .env file for production."
            )
        
        return Fernet(encryption_key.encode())
    
    def _encrypt_password(self, password: str) -> str:
        """Encrypt a password"""
        return self.cipher_suite.encrypt(password.encode()).decode()
    
    def _decrypt_password(self, encrypted_password: str) -> str:
        """Decrypt a password"""
        return self.cipher_suite.decrypt(encrypted_password.encode()).decode()
    
    def create_account(self, account_data: LinkedInAccountCreate) -> LinkedInAccountResponse:
        """Create a new LinkedIn account with encrypted credentials"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.ACCOUNTS_COLLECTION)
            
            # Check if account already exists
            existing = collection.find_one({"email": account_data.email})
            if existing:
                raise ValueError(f"Account with email {account_data.email} already exists")
            
            # Encrypt password before storing
            encrypted_password = self._encrypt_password(account_data.password)
            
            account_doc = {
                "email": account_data.email,
                "password": encrypted_password,
                "account_name": account_data.account_name,
                "active": account_data.active,
                "schedule": account_data.schedule.model_dump(),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "last_run": None,
                "status": "idle"
            }
            
            result = collection.insert_one(account_doc)
            account_doc["_id"] = result.inserted_id
            
            logger.info(f"Created LinkedIn account: {account_data.email}")
            return self._doc_to_response(account_doc)
        
        except Exception as e:
            logger.error(f"Error creating LinkedIn account: {str(e)}")
            raise
    
    def get_account(self, account_id: str) -> LinkedInAccountResponse:
        """Retrieve a LinkedIn account by ID"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.ACCOUNTS_COLLECTION)
            account = collection.find_one({"_id": ObjectId(account_id)})
            
            if not account:
                raise ValueError(f"Account with ID {account_id} not found")
            
            return self._doc_to_response(account)
        
        except Exception as e:
            logger.error(f"Error retrieving LinkedIn account: {str(e)}")
            raise
    
    def get_account_with_password(self, account_id: str) -> dict:
        """Retrieve a LinkedIn account with decrypted password (for bot execution)"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.ACCOUNTS_COLLECTION)
            account = collection.find_one({"_id": ObjectId(account_id)})
            
            if not account:
                raise ValueError(f"Account with ID {account_id} not found")
            
            # Decrypt password
            account["password"] = self._decrypt_password(account["password"])
            return account
        
        except Exception as e:
            logger.error(f"Error retrieving account with password: {str(e)}")
            raise
    
    def list_accounts(self, active_only: bool = True) -> List[LinkedInAccountResponse]:
        """List all LinkedIn accounts"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.ACCOUNTS_COLLECTION)
            
            query = {"active": True} if active_only else {}
            accounts = collection.find(query).sort("created_at", -1)
            
            return [self._doc_to_response(acc) for acc in accounts]
        
        except Exception as e:
            logger.error(f"Error listing LinkedIn accounts: {str(e)}")
            raise
    
    def update_account(self, account_id: str, update_data: LinkedInAccountUpdate) -> LinkedInAccountResponse:
        """Update a LinkedIn account"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.ACCOUNTS_COLLECTION)
            
            update_doc = {}
            if update_data.account_name is not None:
                update_doc["account_name"] = update_data.account_name
            if update_data.active is not None:
                update_doc["active"] = update_data.active
            if update_data.schedule is not None:
                update_doc["schedule"] = update_data.schedule.model_dump()
            
            update_doc["updated_at"] = datetime.utcnow()
            
            result = collection.find_one_and_update(
                {"_id": ObjectId(account_id)},
                {"$set": update_doc},
                return_document=True
            )
            
            if not result:
                raise ValueError(f"Account with ID {account_id} not found")
            
            logger.info(f"Updated LinkedIn account: {account_id}")
            return self._doc_to_response(result)
        
        except Exception as e:
            logger.error(f"Error updating LinkedIn account: {str(e)}")
            raise
    
    def delete_account(self, account_id: str) -> bool:
        """Delete a LinkedIn account (soft delete - set inactive)"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.ACCOUNTS_COLLECTION)
            
            result = collection.find_one_and_update(
                {"_id": ObjectId(account_id)},
                {
                    "$set": {
                        "active": False,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            if not result:
                raise ValueError(f"Account with ID {account_id} not found")
            
            logger.info(f"Deleted LinkedIn account: {account_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error deleting LinkedIn account: {str(e)}")
            raise
    
    def create_job(self, account_id: str, task_type: TaskType) -> LinkedInAutomationJob:
        """Create a new automation job record"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.JOBS_COLLECTION)
            
            job_doc = {
                "account_id": ObjectId(account_id) if isinstance(account_id, str) else account_id,
                "task_type": task_type,
                "status": JobStatus.PENDING,
                "started_at": datetime.utcnow(),
                "ended_at": None,
                "results": {
                    "connections_sent": 0,
                    "messages_sent": 0,
                    "posts_liked": 0,
                    "posts_reposted": 0,
                    "posts_commented": 0,
                    "errors": [],
                    "duration_seconds": 0.0
                },
                "error_message": None
            }
            
            result = collection.insert_one(job_doc)
            job_doc["_id"] = result.inserted_id
            
            logger.info(f"Created automation job: {result.inserted_id}")
            return job_doc
        
        except Exception as e:
            logger.error(f"Error creating automation job: {str(e)}")
            raise
    
    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        results: Optional[LinkedInJobResult] = None,
        error_message: Optional[str] = None
    ) -> None:
        """Update job status and results"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.JOBS_COLLECTION)
            
            update_doc = {
                "status": status,
                "ended_at": datetime.utcnow() if status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.STOPPED] else None
            }
            
            if results:
                update_doc["results"] = results.model_dump() if hasattr(results, 'model_dump') else results
            
            if error_message:
                update_doc["error_message"] = error_message
            
            collection.find_one_and_update(
                {"_id": ObjectId(job_id)},
                {"$set": update_doc}
            )
            
            logger.info(f"Updated job {job_id} status to {status}")
        
        except Exception as e:
            logger.error(f"Error updating job status: {str(e)}")
            raise
    
    def get_job(self, job_id: str) -> dict:
        """Retrieve a job by ID"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.JOBS_COLLECTION)
            job = collection.find_one({"_id": ObjectId(job_id)})
            
            if not job:
                raise ValueError(f"Job with ID {job_id} not found")
            
            return job
        
        except Exception as e:
            logger.error(f"Error retrieving job: {str(e)}")
            raise
    
    def get_account_jobs(self, account_id: str, limit: int = 50) -> List[dict]:
        """Get recent jobs for an account"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.JOBS_COLLECTION)
            
            jobs = list(collection.find(
                {"account_id": ObjectId(account_id) if isinstance(account_id, str) else account_id}
            ).sort("started_at", -1).limit(limit))
            
            return jobs
        
        except Exception as e:
            logger.error(f"Error retrieving account jobs: {str(e)}")
            raise
    
    def get_accounts_to_run(self) -> List[dict]:
        """Get all active accounts that should run now based on schedule"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.ACCOUNTS_COLLECTION)
            
            # Get all active accounts with enabled schedules
            accounts = list(collection.find({
                "active": True,
                "schedule.enabled": True
            }))
            
            # TODO: Filter by schedule (time-based filtering)
            # For now, return all active accounts
            return accounts
        
        except Exception as e:
            logger.error(f"Error getting accounts to run: {str(e)}")
            raise
    
    def update_account_last_run(self, account_id: str) -> None:
        """Update the last_run timestamp for an account"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.ACCOUNTS_COLLECTION)
            
            collection.find_one_and_update(
                {"_id": ObjectId(account_id)},
                {
                    "$set": {
                        "last_run": datetime.utcnow(),
                        "status": "idle"
                    }
                }
            )
        
        except Exception as e:
            logger.error(f"Error updating account last_run: {str(e)}")
            raise
    
    def set_account_status(self, account_id: str, status: str) -> None:
        """Set account status (idle, running, error)"""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.ACCOUNTS_COLLECTION)
            
            collection.find_one_and_update(
                {"_id": ObjectId(account_id)},
                {"$set": {"status": status}}
            )
        
        except Exception as e:
            logger.error(f"Error setting account status: {str(e)}")
            raise
    
    @staticmethod
    def _doc_to_response(doc: dict) -> LinkedInAccountResponse:
        """Convert a MongoDB document to a response model"""
        doc["_id"] = str(doc["_id"])
        return LinkedInAccountResponse(**doc)
