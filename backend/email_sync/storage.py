"""
EMAIL STORAGE SERVICE
=====================

Handles email persistence with strong deduplication guarantees.

Key Features:
- GLOBAL content-based deduplication via dedupe_hash (unique index)
- Mailbox-scoped deduplication via (mailbox_id, provider_message_id)
- System email detection BEFORE queueing for LLM classification
- Upsert logic for idempotent writes
- Batch insert with duplicate handling
- Index creation and maintenance

Design Decisions:
- dedupe_hash is the PRIMARY deduplication mechanism (global)
- (mailbox_id, provider_message_id) is SECONDARY (per-mailbox provider key)
- System emails (bounce, OOO, auto-reply) are NEVER queued for LLM
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from pymongo import MongoClient, ASCENDING, DESCENDING, UpdateOne
from pymongo.errors import DuplicateKeyError, BulkWriteError
from bson import ObjectId

from .models import EmailDocument, CategorizationQueueItem, CategorizationStatus, EmailType

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
            # PRIMARY: Global content-based deduplication (unique across ALL mailboxes)
            # This prevents the same logical email from triggering multiple LLM calls
            self.emails.create_index(
                [("dedupe_hash", ASCENDING)],
                unique=True,
                sparse=True,  # Allow null values during migration
                name="unique_global_dedupe_hash"
            )
            
            # SECONDARY: Per-mailbox provider message ID (backward compatibility)
            self.emails.create_index(
                [("mailbox_id", ASCENDING), ("provider_message_id", ASCENDING)],
                unique=True,
                name="unique_mailbox_message"
            )
            
            # Email type index for filtering system vs normal
            self.emails.create_index("email_type", name="idx_email_type")
            
            # Query indexes
            self.emails.create_index("provider_thread_id")
            self.emails.create_index("alias_id")
            self.emails.create_index("direction")
            self.emails.create_index("timestamp")
            self.emails.create_index([("timestamp", DESCENDING)])
            self.emails.create_index("processed")
            self.emails.create_index("category")
            self.emails.create_index("synced_at")
            
            # Categorization queue indexes
            self.categorization_queue.create_index("email_id", unique=True)
            self.categorization_queue.create_index("status")
            self.categorization_queue.create_index([("created_at", ASCENDING)])
            
            logger.info("Email storage indexes created (including global dedupe_hash)")
            
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    def save_email(self, email: EmailDocument) -> Tuple[bool, str, bool]:
        """
        Save a single email with global deduplication and system email detection.
        
        Args:
            email: EmailDocument to save
            
        Returns:
            Tuple of (is_new, email_id, is_global_duplicate)
            - is_new: True if this is a new email in this mailbox
            - email_id: The email's ObjectId string
            - is_global_duplicate: True if dedupe_hash matched an existing email
        """
        from .system_email_detector import (
            compute_dedupe_hash, 
            detect_system_email,
            generate_system_email_summary
        )
        from .preview_resolver import resolve_and_update_preview, build_sender_metadata
        
        # Compute global dedupe hash if not already set
        email_dict = email.dict(exclude={"id"})
        if not email_dict.get("dedupe_hash"):
            email_dict["dedupe_hash"] = compute_dedupe_hash(email_dict)
        
        # Check for global duplicate FIRST (before any processing)
        existing_by_hash = self.emails.find_one({"dedupe_hash": email_dict["dedupe_hash"]})
        if existing_by_hash:
            # Global duplicate - same logical email already exists
            logger.debug(
                f"Global duplicate detected: hash={email_dict['dedupe_hash'][:16]}... "
                f"existing_id={existing_by_hash['_id']}, mailbox={email.mailbox_id}"
            )
            return False, str(existing_by_hash["_id"]), True
        
        # Detect system email type BEFORE save
        if email_dict.get("email_type") != EmailType.SYSTEM.value:
            detection = detect_system_email(email_dict)
            if detection.is_system:
                email_dict["email_type"] = detection.email_type.value
                email_dict["system_subtype"] = detection.system_subtype.value if detection.system_subtype else None
                # Generate deterministic summary for system emails
                email_dict["gmail_summary"] = generate_system_email_summary(
                    email_dict, detection.system_subtype
                )
                # System emails are immediately marked as processed (no LLM needed)
                email_dict["processed"] = True
                email_dict["ai_needs_classification"] = False
                logger.info(
                    f"System email detected: type={detection.system_subtype}, "
                    f"reason={detection.detection_reason[:80]}"
                )
        
        # Phase 2: Resolve preview (gmail_summary → ai_summary → snippet)
        resolve_and_update_preview(email_dict)
        
        # Phase 2: Build sender metadata with confidence
        if not email_dict.get("sender_metadata"):
            from_address = email_dict.get("from_address", {})
            sender = build_sender_metadata(from_address)
            email_dict["sender_metadata"] = sender.model_dump()
        
        # Use upsert with dedupe_hash as primary key
        try:
            result = self.emails.update_one(
                {"dedupe_hash": email_dict["dedupe_hash"]},
                {
                    "$setOnInsert": {
                        "synced_at": datetime.utcnow(),
                        "mailbox_id": email.mailbox_id,
                        "provider_message_id": email.provider_message_id,
                    },
                    "$set": {k: v for k, v in email_dict.items() 
                             if k not in ["synced_at", "mailbox_id", "provider_message_id"]}
                },
                upsert=True
            )
        except DuplicateKeyError:
            # Race condition: another process inserted with same hash
            existing = self.emails.find_one({"dedupe_hash": email_dict["dedupe_hash"]})
            return False, str(existing["_id"]) if existing else None, True
        
        is_new = result.upserted_id is not None
        email_id = str(result.upserted_id) if is_new else None
        
        # If new, get the ID
        if not email_id:
            existing = self.emails.find_one({"dedupe_hash": email_dict["dedupe_hash"]})
            email_id = str(existing["_id"]) if existing else None
        
        # Add to categorization queue ONLY if:
        # 1. This is a new email (not duplicate)
        # 2. It's NOT a system email (system emails skip LLM entirely)
        if is_new and email_id:
            is_system = email_dict.get("email_type") == EmailType.SYSTEM.value
            if not is_system:
                self._enqueue_for_categorization(email_id, email)
            else:
                logger.debug(f"Skipping LLM queue for system email: {email_id}")
        
        return is_new, email_id, False  # Not a global duplicate
    
    def save_emails_batch(
        self,
        emails: List[EmailDocument]
    ) -> Dict[str, Any]:
        """
        Save multiple emails with global deduplication and system email detection.
        
        Args:
            emails: List of EmailDocument objects
            
        Returns:
            Stats dict with inserted, updated, duplicates, system_emails counts
        """
        from .system_email_detector import (
            compute_dedupe_hash, 
            detect_system_email,
            generate_system_email_summary
        )
        from .preview_resolver import resolve_and_update_preview, build_sender_metadata
        
        if not emails:
            return {"inserted": 0, "updated": 0, "duplicates": 0, "system_emails": 0, "global_duplicates": 0}
        
        # Pre-process: compute hashes, detect system emails, check for global duplicates
        processed_emails = []
        global_duplicate_count = 0
        system_email_count = 0
        
        # Collect all hashes to check for existing emails in one query
        email_dicts = []
        for email in emails:
            email_dict = email.dict(exclude={"id"})
            if not email_dict.get("dedupe_hash"):
                email_dict["dedupe_hash"] = compute_dedupe_hash(email_dict)
            email_dicts.append(email_dict)
        
        # Batch check for existing dedupe_hashes
        all_hashes = [e["dedupe_hash"] for e in email_dicts]
        existing_hashes = set()
        for doc in self.emails.find(
            {"dedupe_hash": {"$in": all_hashes}},
            {"dedupe_hash": 1}
        ):
            existing_hashes.add(doc["dedupe_hash"])
        
        # Filter out global duplicates and process system emails
        operations = []
        emails_to_queue = []  # (email_id will be filled after bulk_write, email_dict)
        
        for i, email_dict in enumerate(email_dicts):
            dedupe_hash = email_dict["dedupe_hash"]
            
            # Skip global duplicates
            if dedupe_hash in existing_hashes:
                global_duplicate_count += 1
                continue
            
            # Detect system email
            if email_dict.get("email_type") != EmailType.SYSTEM.value:
                detection = detect_system_email(email_dict)
                if detection.is_system:
                    email_dict["email_type"] = detection.email_type.value
                    email_dict["system_subtype"] = detection.system_subtype.value if detection.system_subtype else None
                    email_dict["gmail_summary"] = generate_system_email_summary(
                        email_dict, detection.system_subtype
                    )
                    email_dict["processed"] = True
                    email_dict["ai_needs_classification"] = False
                    system_email_count += 1
            
            # Phase 2: Resolve preview and build sender metadata
            resolve_and_update_preview(email_dict)
            if not email_dict.get("sender_metadata"):
                from_address = email_dict.get("from_address", {})
                sender = build_sender_metadata(from_address)
                email_dict["sender_metadata"] = sender.model_dump()
            
            is_system = email_dict.get("email_type") == EmailType.SYSTEM.value
            
            operations.append(UpdateOne(
                {"dedupe_hash": dedupe_hash},
                {
                    "$setOnInsert": {
                        "synced_at": datetime.utcnow(),
                        "processed": email_dict.get("processed", False),
                    },
                    "$set": {k: v for k, v in email_dict.items() 
                             if k not in ["synced_at", "processed"]}
                },
                upsert=True
            ))
            
            # Track which emails need queueing (only non-system)
            if not is_system:
                emails_to_queue.append((i, emails[i]))
        
        if not operations:
            return {
                "inserted": 0, 
                "updated": 0, 
                "duplicates": 0,
                "global_duplicates": global_duplicate_count,
                "system_emails": system_email_count
            }
        
        try:
            result = self.emails.bulk_write(operations, ordered=False)
            
            inserted = result.upserted_count
            updated = result.modified_count
            
            # Enqueue ONLY non-system emails for categorization
            if result.upserted_ids:
                for op_idx, email_id in result.upserted_ids.items():
                    # Find the corresponding email in emails_to_queue
                    for orig_idx, email_obj in emails_to_queue:
                        if orig_idx == op_idx:
                            self._enqueue_for_categorization(str(email_id), email_obj)
                            break
            
            logger.info(
                f"Batch save: {inserted} inserted, {updated} updated, "
                f"{global_duplicate_count} global duplicates, {system_email_count} system emails skipped"
            )
            
            return {
                "inserted": inserted,
                "updated": updated,
                "duplicates": len(emails) - inserted - updated - global_duplicate_count,
                "global_duplicates": global_duplicate_count,
                "system_emails": system_email_count,
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
                "global_duplicates": global_duplicate_count,
                "system_emails": system_email_count,
                "errors": len(write_errors) - duplicates,
            }
    
    def _enqueue_for_categorization(self, email_id: str, email: EmailDocument):
        """
        Add email to categorization queue and mark for AI classification.
        
        Args:
            email_id: Email ObjectId string
            email: EmailDocument
        """
        try:
            # Mark email as needing AI classification
            self.emails.update_one(
                {"_id": ObjectId(email_id)},
                {"$set": {"ai_needs_classification": True}}
            )
            
            # Also add to legacy categorization queue for backward compatibility
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
