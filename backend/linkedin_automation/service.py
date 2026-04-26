"""
LinkedIn Automation Service
Handles account management, credential encryption, job orchestration,
and LinkedIn-sourced opportunity tracking.
"""

import logging
import re
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
    LinkedInOpportunityIngestRequest,
    LinkedInOpportunityResponse,
    LinkedInOpportunityUpdate,
    JobStatus,
    OpportunityStatus,
    TaskType,
)

logger = logging.getLogger(__name__)


class LinkedInService:
    """Service layer for LinkedIn automation"""
    
    DB_NAME = "linkedin_db"
    ACCOUNTS_COLLECTION = "accounts"
    JOBS_COLLECTION = "automation_jobs"
    JOB_LOGS_COLLECTION = "job_logs"
    OPPORTUNITIES_COLLECTION = "opportunities"
    _indexes_ensured = False
    
    def __init__(self):
        """Initialize service with encryption key"""
        self.db_manager = DatabaseManager()
        # Get or generate encryption key
        self.cipher_suite = self._get_cipher_suite()
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Ensure opportunity indexes exist without blocking app startup on failure."""
        if LinkedInService._indexes_ensured:
            return

        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.OPPORTUNITIES_COLLECTION)
            collection.create_index("message_id", unique=True, sparse=True)
            collection.create_index([("status", 1), ("created_at", -1)])
            collection.create_index([("division_owner", 1), ("created_at", -1)])
            collection.create_index("account_id")
            collection.create_index("created_at")
            LinkedInService._indexes_ensured = True
        except Exception as e:
            logger.warning(f"Could not ensure LinkedIn opportunity indexes: {e}")
    
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

    def ingest_opportunity(self, payload: LinkedInOpportunityIngestRequest) -> LinkedInOpportunityResponse:
        """Persist a LinkedIn message as an opportunity candidate with heuristic scoring."""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.OPPORTUNITIES_COLLECTION)

            if payload.message_id:
                existing = collection.find_one({"message_id": payload.message_id})
                if existing:
                    return self._doc_to_opportunity_response(existing)

            analysis = self._analyze_opportunity_text(payload.message_text)
            now = datetime.utcnow()
            division_owner = self._resolve_division_owner(payload.division_hint, payload.message_text)

            opportunity_doc = {
                "account_id": payload.account_id,
                "message_id": payload.message_id,
                "channel": payload.channel.value if hasattr(payload.channel, "value") else str(payload.channel),
                "sender_name": payload.sender_name,
                "sender_profile_url": payload.sender_profile_url,
                "sender_company": payload.sender_company,
                "sender_title": payload.sender_title,
                "message_text": payload.message_text.strip(),
                "message_excerpt": payload.message_text.strip()[:280],
                "detected_need": analysis["detected_need"],
                "detected_keywords": analysis["detected_keywords"],
                "intent_score": analysis["intent_score"],
                "confidence": analysis["confidence"],
                "status": OpportunityStatus.DISCOVERED.value,
                "division_owner": division_owner,
                "response_draft": self._build_response_draft(payload.sender_name, analysis["detected_need"], division_owner),
                "notes": payload.notes,
                "converted_value": None,
                "created_at": now,
                "updated_at": now,
                "contacted_at": None,
                "replied_at": None,
                "converted_at": None,
            }

            result = collection.insert_one(opportunity_doc)
            opportunity_doc["_id"] = result.inserted_id
            return self._doc_to_opportunity_response(opportunity_doc)
        except Exception as e:
            logger.error(f"Error ingesting LinkedIn opportunity: {str(e)}")
            raise

    def list_opportunities(
        self,
        status: Optional[str] = None,
        division_owner: Optional[str] = None,
        days: int = 30,
        limit: int = 50,
    ) -> List[LinkedInOpportunityResponse]:
        """List recent LinkedIn opportunities with optional filters."""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.OPPORTUNITIES_COLLECTION)
            query = {"created_at": {"$gte": datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)}}
            if days > 1:
                query["created_at"]["$gte"] = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                query["created_at"]["$gte"] = query["created_at"]["$gte"]
            if days:
                from datetime import timedelta
                query["created_at"] = {"$gte": datetime.utcnow() - timedelta(days=days)}
            if status:
                query["status"] = status
            if division_owner:
                query["division_owner"] = division_owner

            docs = list(collection.find(query).sort("created_at", -1).limit(limit))
            return [self._doc_to_opportunity_response(doc) for doc in docs]
        except Exception as e:
            logger.error(f"Error listing LinkedIn opportunities: {str(e)}")
            raise

    def get_opportunity(self, opportunity_id: str) -> LinkedInOpportunityResponse:
        """Retrieve a LinkedIn opportunity by ID."""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.OPPORTUNITIES_COLLECTION)
            doc = collection.find_one({"_id": ObjectId(opportunity_id)})
            if not doc:
                raise ValueError(f"Opportunity with ID {opportunity_id} not found")
            return self._doc_to_opportunity_response(doc)
        except Exception as e:
            logger.error(f"Error retrieving LinkedIn opportunity: {str(e)}")
            raise

    def update_opportunity(self, opportunity_id: str, update_data: LinkedInOpportunityUpdate) -> LinkedInOpportunityResponse:
        """Update a LinkedIn opportunity as it moves through the pipeline."""
        try:
            collection = self.db_manager.get_collection(self.DB_NAME, self.OPPORTUNITIES_COLLECTION)
            update_doc = {"updated_at": datetime.utcnow()}
            now = datetime.utcnow()

            if update_data.status is not None:
                status_value = update_data.status.value if hasattr(update_data.status, "value") else str(update_data.status)
                update_doc["status"] = status_value
                if status_value == OpportunityStatus.CONTACTED.value:
                    update_doc["contacted_at"] = now
                elif status_value == OpportunityStatus.REPLIED.value:
                    update_doc["replied_at"] = now
                elif status_value == OpportunityStatus.CONVERTED.value:
                    update_doc["converted_at"] = now

            if update_data.division_owner is not None:
                update_doc["division_owner"] = update_data.division_owner
            if update_data.notes is not None:
                update_doc["notes"] = update_data.notes
            if update_data.response_draft is not None:
                update_doc["response_draft"] = update_data.response_draft
            if update_data.converted_value is not None:
                update_doc["converted_value"] = update_data.converted_value

            result = collection.find_one_and_update(
                {"_id": ObjectId(opportunity_id)},
                {"$set": update_doc},
                return_document=True,
            )

            if not result:
                raise ValueError(f"Opportunity with ID {opportunity_id} not found")

            return self._doc_to_opportunity_response(result)
        except Exception as e:
            logger.error(f"Error updating LinkedIn opportunity: {str(e)}")
            raise

    def get_opportunity_dashboard(self, days: int = 30) -> dict:
        """Return funnel and division summaries for recent LinkedIn opportunities."""
        try:
            opportunities = self.list_opportunities(days=days, limit=500)
            status_totals = {status.value: 0 for status in OpportunityStatus}
            division_totals = {}

            for opp in opportunities:
                status_totals[opp.status.value if hasattr(opp.status, "value") else str(opp.status)] += 1
                division_key = opp.division_owner or "unassigned"
                division_totals[division_key] = division_totals.get(division_key, 0) + 1

            return {
                "days": days,
                "total": len(opportunities),
                "status_totals": status_totals,
                "division_totals": division_totals,
                "avg_confidence": round(sum(opp.confidence for opp in opportunities) / max(len(opportunities), 1), 2),
                "recent": [opp.model_dump(by_alias=True) for opp in opportunities[:10]],
            }
        except Exception as e:
            logger.error(f"Error building LinkedIn opportunity dashboard: {str(e)}")
            raise

    @staticmethod
    def _analyze_opportunity_text(message_text: str) -> dict:
        """Use a light heuristic pass to score likely business opportunities."""
        normalized = re.sub(r"\s+", " ", message_text or "").strip().lower()
        opportunity_keywords = [
            "opportunity", "partnership", "collaborate", "project", "proposal",
            "quote", "rfq", "scope", "budget", "pricing", "demo", "meeting",
            "call", "vendor", "outsource", "support", "survey", "research",
            "bim", "construction", "sample", "respondents",
        ]
        urgency_keywords = ["this week", "asap", "urgent", "timeline", "next week", "immediately"]
        matched_keywords = [keyword for keyword in opportunity_keywords if keyword in normalized]
        urgency_matches = [keyword for keyword in urgency_keywords if keyword in normalized]

        score = min(100, len(matched_keywords) * 12 + len(urgency_matches) * 8)
        if "?" in normalized:
            score = min(100, score + 5)

        sentences = re.split(r"(?<=[.!?])\s+", message_text.strip()) if message_text else []
        detected_need = sentences[0][:220] if sentences else None

        return {
            "detected_keywords": matched_keywords,
            "intent_score": score,
            "confidence": round(min(0.98, max(0.15, score / 100)), 2),
            "detected_need": detected_need,
        }

    @staticmethod
    def _resolve_division_owner(division_hint: Optional[str], message_text: str) -> str:
        """Map an opportunity to the most likely business division."""
        hint = (division_hint or "").strip().lower()
        if hint in {"sfw", "cogentix", "bimwave"}:
            return hint

        text = (message_text or "").lower()
        if any(keyword in text for keyword in ["survey", "respondent", "fieldwork", "sample"]):
            return "sfw"
        if any(keyword in text for keyword in ["bim", "construction", "architecture", "engineering"]):
            return "bimwave"
        if any(keyword in text for keyword in ["research", "insight", "analytics", "market"]):
            return "cogentix"
        return "unassigned"

    @staticmethod
    def _build_response_draft(sender_name: str, detected_need: Optional[str], division_owner: Optional[str]) -> str:
        """Create a human-review draft based on the detected need."""
        intro_name = sender_name.strip().split()[0] if sender_name else "there"
        division_text = division_owner or "our team"
        need_text = detected_need or "your note"
        return (
            f"Hi {intro_name}, thanks for reaching out. I reviewed {need_text.lower()} and "
            f"I can route this to the {division_text} team for a quick follow-up. "
            "If you can share timeline, volume, and any budget context, we can respond with the right next steps."
        )
    
    @staticmethod
    def _doc_to_response(doc: dict) -> LinkedInAccountResponse:
        """Convert a MongoDB document to a response model"""
        doc["_id"] = str(doc["_id"])
        return LinkedInAccountResponse(**doc)

    @staticmethod
    def _doc_to_opportunity_response(doc: dict) -> LinkedInOpportunityResponse:
        """Convert a MongoDB document to an opportunity response model"""
        doc["_id"] = str(doc["_id"])
        return LinkedInOpportunityResponse(**doc)
