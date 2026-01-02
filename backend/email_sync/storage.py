"""
EMAIL STORAGE SERVICE
=====================

Handles email persistence with strong deduplication guarantees.

Key Features:
- Unique constraint: (mailbox_id, provider_message_id)
- Upsert logic for idempotent writes
- Batch insert with duplicate handling
- Index creation and maintenance
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from pymongo import MongoClient, ASCENDING, DESCENDING, UpdateOne
from pymongo.errors import DuplicateKeyError, BulkWriteError
from bson import ObjectId

from .models import EmailDocument, CategorizationQueueItem, CategorizationStatus

logger = logging.getLogger(__name__)


class EmailStorage:
    """
    Email storage with deduplication and idempotency.
    
    Design:
    - All writes use upsert to handle duplicates
    - Unique index on (mailbox_id, provider_message_id)
    - Categorization queue is populated on insert
    """
    
    def __init__(self, db: MongoClient, emails_collection: str = "emails"):
        """
        Initialize storage.
        
        Args:
            db: MongoDB database instance
            emails_collection: Name of emails collection
        """
        self.db = db
        self.emails = db[emails_collection]
        self.categorization_queue = db["categorization_queue"]
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create required indexes"""
        try:
            # Unique constraint for deduplication
            self.emails.create_index(
                [("mailbox_id", ASCENDING), ("provider_message_id", ASCENDING)],
                unique=True,
                name="unique_mailbox_message"
            )
            
            # Query indexes
            self.emails.create_index("provider_thread_id")
            self.emails.create_index("alias_id")
            self.emails.create_index("direction")
            self.emails.create_index("timestamp", expireAfterSeconds=None)
            self.emails.create_index([("timestamp", DESCENDING)])
            self.emails.create_index("processed")
            self.emails.create_index("category")
            self.emails.create_index("synced_at")
            
            # Categorization queue indexes
            self.categorization_queue.create_index("email_id", unique=True)
            self.categorization_queue.create_index("status")
            self.categorization_queue.create_index([("created_at", ASCENDING)])
            
            logger.info("Email storage indexes created")
            
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    def save_email(self, email: EmailDocument) -> Tuple[bool, str]:
        """
        Save a single email with upsert logic.
        
        Args:
            email: EmailDocument to save
            
        Returns:
            Tuple of (is_new, email_id)
        """
        email_dict = email.dict(exclude={"id"})
        
        # Use upsert to handle duplicates
        result = self.emails.update_one(
            {
                "mailbox_id": email.mailbox_id,
                "provider_message_id": email.provider_message_id,
            },
            {
                "$setOnInsert": {
                    "synced_at": datetime.utcnow(),
                    "processed": False,
                },
                "$set": {k: v for k, v in email_dict.items() if k not in ["synced_at", "processed"]}
            },
            upsert=True
        )
        
        is_new = result.upserted_id is not None
        email_id = str(result.upserted_id) if is_new else None
        
        # If new, get the ID
        if not email_id:
            existing = self.emails.find_one({
                "mailbox_id": email.mailbox_id,
                "provider_message_id": email.provider_message_id,
            })
            email_id = str(existing["_id"]) if existing else None
        
        # Add to categorization queue if new
        if is_new and email_id:
            self._enqueue_for_categorization(email_id, email)
        
        return is_new, email_id
    
    def save_emails_batch(
        self,
        emails: List[EmailDocument]
    ) -> Dict[str, Any]:
        """
        Save multiple emails with batch upsert.
        
        Args:
            emails: List of EmailDocument objects
            
        Returns:
            Stats dict with inserted, updated, duplicates counts
        """
        if not emails:
            return {"inserted": 0, "updated": 0, "duplicates": 0}
        
        operations = []
        for email in emails:
            email_dict = email.dict(exclude={"id"})
            
            operations.append(UpdateOne(
                {
                    "mailbox_id": email.mailbox_id,
                    "provider_message_id": email.provider_message_id,
                },
                {
                    "$setOnInsert": {
                        "synced_at": datetime.utcnow(),
                        "processed": False,
                    },
                    "$set": {k: v for k, v in email_dict.items() if k not in ["synced_at", "processed"]}
                },
                upsert=True
            ))
        
        try:
            result = self.emails.bulk_write(operations, ordered=False)
            
            inserted = result.upserted_count
            updated = result.modified_count
            
            # Enqueue new emails for categorization
            if result.upserted_ids:
                for idx, email_id in result.upserted_ids.items():
                    self._enqueue_for_categorization(str(email_id), emails[idx])
            
            logger.info(f"Batch save: {inserted} inserted, {updated} updated")
            
            return {
                "inserted": inserted,
                "updated": updated,
                "duplicates": len(emails) - inserted - updated,
            }
            
        except BulkWriteError as e:
            # Handle partial success
            write_errors = e.details.get("writeErrors", [])
            duplicates = sum(1 for err in write_errors if err.get("code") == 11000)
            
            logger.warning(f"Bulk write partial failure: {len(write_errors)} errors, {duplicates} duplicates")
            
            return {
                "inserted": e.details.get("nUpserted", 0),
                "updated": e.details.get("nModified", 0),
                "duplicates": duplicates,
                "errors": len(write_errors) - duplicates,
            }
    
    def _enqueue_for_categorization(self, email_id: str, email: EmailDocument):
        """
        Add email to categorization queue.
        
        Args:
            email_id: Email ObjectId string
            email: EmailDocument
        """
        try:
            queue_item = {
                "email_id": email_id,
                "mailbox_id": email.mailbox_id,
                "status": CategorizationStatus.PENDING.value,
                "attempts": 0,
                "max_attempts": 3,
                "subject": email.subject[:500] if email.subject else "",
                "body_preview": email.body_plain[:1000] if email.body_plain else "",
                "from_email": email.from_address.email if email.from_address else "",
                "created_at": datetime.utcnow(),
            }
            
            self.categorization_queue.insert_one(queue_item)
            
        except DuplicateKeyError:
            # Already in queue
            pass
        except Exception as e:
            logger.warning(f"Error enqueueing email {email_id}: {e}")
    
    def get_email(self, email_id: str) -> Optional[Dict[str, Any]]:
        """
        Get email by ID.
        
        Args:
            email_id: Email ObjectId string
            
        Returns:
            Email document or None
        """
        try:
            email = self.emails.find_one({"_id": ObjectId(email_id)})
            if email:
                email["_id"] = str(email["_id"])
            return email
        except Exception:
            return None
    
    def get_emails_for_mailbox(
        self,
        mailbox_id: str,
        limit: int = 50,
        skip: int = 0,
        direction: Optional[str] = None,
        processed: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """
        Get emails for a mailbox with filtering.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            limit: Maximum results
            skip: Skip count
            direction: Filter by direction
            processed: Filter by processed status
            
        Returns:
            List of email documents
        """
        query = {"mailbox_id": mailbox_id}
        
        if direction:
            query["direction"] = direction
        if processed is not None:
            query["processed"] = processed
        
        cursor = self.emails.find(query).sort(
            "timestamp", DESCENDING
        ).skip(skip).limit(limit)
        
        emails = []
        for email in cursor:
            email["_id"] = str(email["_id"])
            emails.append(email)
        
        return emails
    
    def get_thread(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        Get all emails in a thread.
        
        Args:
            thread_id: Provider thread ID
            
        Returns:
            List of email documents sorted by timestamp
        """
        cursor = self.emails.find(
            {"provider_thread_id": thread_id}
        ).sort("timestamp", ASCENDING)
        
        emails = []
        for email in cursor:
            email["_id"] = str(email["_id"])
            emails.append(email)
        
        return emails
    
    def update_categorization(
        self,
        email_id: str,
        category: str,
        confidence: float,
        model_version: str
    ) -> bool:
        """
        Update email with categorization result.
        
        Args:
            email_id: Email ObjectId string
            category: Category value
            confidence: Confidence score
            model_version: Model version string
            
        Returns:
            True if updated
        """
        result = self.emails.update_one(
            {"_id": ObjectId(email_id)},
            {
                "$set": {
                    "processed": True,
                    "category": category,
                    "category_confidence": confidence,
                    "category_model_version": model_version,
                    "categorized_at": datetime.utcnow(),
                }
            }
        )
        
        return result.modified_count > 0
    
    def update_crm_links(
        self,
        email_id: str,
        contact_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        rfq_id: Optional[str] = None
    ) -> bool:
        """
        Update email with CRM entity links.
        
        Args:
            email_id: Email ObjectId string
            contact_id: CRM contact ID
            lead_id: CRM lead ID
            rfq_id: CRM RFQ ID
            
        Returns:
            True if updated
        """
        update = {"crm_linked_at": datetime.utcnow()}
        
        if contact_id:
            update["crm_contact_id"] = contact_id
        if lead_id:
            update["crm_lead_id"] = lead_id
        if rfq_id:
            update["crm_rfq_id"] = rfq_id
        
        result = self.emails.update_one(
            {"_id": ObjectId(email_id)},
            {"$set": update}
        )
        
        return result.modified_count > 0
    
    def get_unprocessed_count(self, mailbox_id: Optional[str] = None) -> int:
        """
        Get count of unprocessed emails.
        
        Args:
            mailbox_id: Optional filter by mailbox
            
        Returns:
            Count of unprocessed emails
        """
        query = {"processed": False}
        if mailbox_id:
            query["mailbox_id"] = mailbox_id
        
        return self.emails.count_documents(query)
    
    def get_stats(self, mailbox_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get email statistics.
        
        Args:
            mailbox_id: Optional filter by mailbox
            
        Returns:
            Stats dict
        """
        match = {}
        if mailbox_id:
            match["mailbox_id"] = mailbox_id
        
        pipeline = [
            {"$match": match},
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    "inbound": {
                        "$sum": {"$cond": [{"$eq": ["$direction", "inbound"]}, 1, 0]}
                    },
                    "outbound": {
                        "$sum": {"$cond": [{"$eq": ["$direction", "outbound"]}, 1, 0]}
                    },
                    "processed": {
                        "$sum": {"$cond": ["$processed", 1, 0]}
                    },
                    "unprocessed": {
                        "$sum": {"$cond": ["$processed", 0, 1]}
                    },
                }
            }
        ]
        
        result = list(self.emails.aggregate(pipeline))
        
        if result:
            stats = result[0]
            del stats["_id"]
            return stats
        
        return {
            "total": 0,
            "inbound": 0,
            "outbound": 0,
            "processed": 0,
            "unprocessed": 0,
        }
