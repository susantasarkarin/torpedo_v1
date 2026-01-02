"""
SYNC STATE MACHINE
==================

Manages sync state transitions for email synchronization.
Ensures crash recovery, idempotency, and proper state management.

State Transitions:
    IDLE -> BACKFILL_PENDING (when backfill requested)
    BACKFILL_PENDING -> BACKFILL_RUNNING (when worker picks up)
    BACKFILL_RUNNING -> BACKFILL_COMPLETED (when backfill finishes)
    BACKFILL_RUNNING -> ERROR (on failure)
    BACKFILL_RUNNING -> PAUSED (when rate limit hit)
    PAUSED -> BACKFILL_RUNNING (when rate limit clears)
    BACKFILL_COMPLETED -> INCREMENTAL_RUNNING (automatic transition)
    INCREMENTAL_RUNNING -> IDLE (after sync completes)
    ERROR -> BACKFILL_PENDING (on retry)
    ERROR -> IDLE (on manual reset)

Key Features:
    - Atomic state transitions
    - Cursor persistence for restart safety
    - Error tracking with exponential backoff
    - Rate limit awareness
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from bson import ObjectId

from .models import (
    SyncStatus,
    SyncStateDocument,
    GmailSyncCursor,
    ImapSyncCursor,
    ProviderType,
)

logger = logging.getLogger(__name__)


class SyncStateMachine:
    """
    Manages sync state for a mailbox with atomic transitions.
    
    Design Principles:
    1. All state changes are atomic
    2. Cursors are persisted after each batch
    3. Restarts resume from last cursor
    4. Errors trigger backoff
    """
    
    # Valid state transitions
    VALID_TRANSITIONS = {
        SyncStatus.IDLE: [SyncStatus.BACKFILL_PENDING, SyncStatus.INCREMENTAL_RUNNING],
        SyncStatus.BACKFILL_PENDING: [SyncStatus.BACKFILL_RUNNING, SyncStatus.IDLE],
        SyncStatus.BACKFILL_RUNNING: [
            SyncStatus.BACKFILL_COMPLETED,
            SyncStatus.ERROR,
            SyncStatus.PAUSED,
        ],
        SyncStatus.BACKFILL_COMPLETED: [SyncStatus.INCREMENTAL_RUNNING, SyncStatus.IDLE],
        SyncStatus.INCREMENTAL_RUNNING: [
            SyncStatus.IDLE,
            SyncStatus.ERROR,
            SyncStatus.PAUSED,
        ],
        SyncStatus.ERROR: [
            SyncStatus.BACKFILL_PENDING,
            SyncStatus.INCREMENTAL_RUNNING,
            SyncStatus.IDLE,
        ],
        SyncStatus.PAUSED: [
            SyncStatus.BACKFILL_RUNNING,
            SyncStatus.INCREMENTAL_RUNNING,
            SyncStatus.IDLE,
        ],
    }
    
    # Backoff configuration
    MAX_CONSECUTIVE_ERRORS = 10
    BASE_BACKOFF_SECONDS = 60
    MAX_BACKOFF_SECONDS = 3600  # 1 hour
    
    def __init__(self, db: MongoClient, collection_name: str = "sync_state"):
        """
        Initialize state machine with MongoDB connection.
        
        Args:
            db: MongoDB database instance
            collection_name: Name of the sync state collection
        """
        self.collection = db[collection_name]
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create required indexes"""
        try:
            self.collection.create_index("mailbox_id", unique=True)
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    def get_state(self, mailbox_id: str) -> Optional[SyncStateDocument]:
        """
        Get current sync state for a mailbox.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            SyncStateDocument or None if not found
        """
        doc = self.collection.find_one({"mailbox_id": mailbox_id})
        if doc:
            doc["_id"] = str(doc["_id"])
            return SyncStateDocument(**doc)
        return None
    
    def initialize_state(
        self,
        mailbox_id: str,
        provider: ProviderType
    ) -> SyncStateDocument:
        """
        Initialize sync state for a new mailbox.
        Idempotent - returns existing state if already initialized.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            provider: Provider type (gmail/imap)
            
        Returns:
            SyncStateDocument
        """
        now = datetime.utcnow()
        
        # Initialize provider-specific cursor
        gmail_cursor = GmailSyncCursor() if provider == ProviderType.GMAIL else None
        imap_cursor = ImapSyncCursor() if provider == ProviderType.IMAP else None
        
        doc = {
            "mailbox_id": mailbox_id,
            "status": SyncStatus.IDLE.value,
            "gmail_cursor": gmail_cursor.dict() if gmail_cursor else None,
            "imap_cursor": imap_cursor.dict() if imap_cursor else None,
            "created_at": now,
            "updated_at": now,
        }
        
        try:
            result = self.collection.insert_one(doc)
            doc["_id"] = str(result.inserted_id)
            logger.info(f"Initialized sync state for mailbox {mailbox_id}")
            return SyncStateDocument(**doc)
        except DuplicateKeyError:
            # Already exists, return existing
            return self.get_state(mailbox_id)
    
    def transition(
        self,
        mailbox_id: str,
        to_status: SyncStatus,
        cursor_update: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> Tuple[bool, Optional[SyncStateDocument]]:
        """
        Atomically transition to a new state.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            to_status: Target status
            cursor_update: Optional cursor fields to update
            error: Optional error message (for ERROR state)
            
        Returns:
            Tuple of (success, updated_state)
        """
        current = self.get_state(mailbox_id)
        if not current:
            logger.error(f"No sync state found for mailbox {mailbox_id}")
            return False, None
        
        # Validate transition
        if to_status not in self.VALID_TRANSITIONS.get(current.status, []):
            logger.warning(
                f"Invalid transition {current.status} -> {to_status} for mailbox {mailbox_id}"
            )
            return False, current
        
        now = datetime.utcnow()
        
        # Build update document
        update = {
            "$set": {
                "status": to_status.value,
                "updated_at": now,
            }
        }
        
        # Handle specific transitions
        if to_status == SyncStatus.BACKFILL_RUNNING and current.status == SyncStatus.BACKFILL_PENDING:
            update["$set"]["backfill_started_at"] = now
            
        elif to_status == SyncStatus.BACKFILL_COMPLETED:
            update["$set"]["backfill_completed_at"] = now
            update["$set"]["backfill_progress_percent"] = 100.0
            
        elif to_status == SyncStatus.INCREMENTAL_RUNNING:
            pass  # Normal transition
            
        elif to_status == SyncStatus.IDLE and current.status == SyncStatus.INCREMENTAL_RUNNING:
            update["$set"]["last_incremental_at"] = now
            update["$set"]["consecutive_errors"] = 0
            
        elif to_status == SyncStatus.ERROR:
            update["$set"]["last_error"] = error
            update["$set"]["last_error_at"] = now
            update["$inc"] = {"consecutive_errors": 1}
            
        elif to_status == SyncStatus.PAUSED:
            pass  # Paused for rate limit
        
        # Apply cursor update if provided
        if cursor_update:
            for key, value in cursor_update.items():
                update["$set"][key] = value
        
        # Atomic update with version check
        result = self.collection.find_one_and_update(
            {
                "mailbox_id": mailbox_id,
                "status": current.status.value,  # Optimistic lock
            },
            update,
            return_document=ReturnDocument.AFTER
        )
        
        if result:
            result["_id"] = str(result["_id"])
            logger.info(f"Transitioned mailbox {mailbox_id}: {current.status} -> {to_status}")
            return True, SyncStateDocument(**result)
        else:
            logger.warning(f"Transition failed for mailbox {mailbox_id} (concurrent modification?)")
            return False, None
    
    def start_backfill(self, mailbox_id: str) -> Tuple[bool, Optional[SyncStateDocument]]:
        """
        Request backfill for a mailbox.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            Tuple of (success, state)
        """
        current = self.get_state(mailbox_id)
        if not current:
            logger.error(f"No sync state found for mailbox {mailbox_id}")
            return False, None
        
        # Can start backfill from IDLE or after ERROR
        if current.status not in [SyncStatus.IDLE, SyncStatus.ERROR]:
            logger.warning(f"Cannot start backfill from status {current.status}")
            return False, current
        
        return self.transition(mailbox_id, SyncStatus.BACKFILL_PENDING)
    
    def claim_backfill_task(self, mailbox_id: str) -> Tuple[bool, Optional[SyncStateDocument]]:
        """
        Atomically claim a backfill task for processing.
        Only succeeds if status is BACKFILL_PENDING.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            Tuple of (claimed, state)
        """
        result = self.collection.find_one_and_update(
            {
                "mailbox_id": mailbox_id,
                "status": SyncStatus.BACKFILL_PENDING.value,
            },
            {
                "$set": {
                    "status": SyncStatus.BACKFILL_RUNNING.value,
                    "backfill_started_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }
            },
            return_document=ReturnDocument.AFTER
        )
        
        if result:
            result["_id"] = str(result["_id"])
            logger.info(f"Claimed backfill task for mailbox {mailbox_id}")
            return True, SyncStateDocument(**result)
        
        return False, None
    
    def update_backfill_progress(
        self,
        mailbox_id: str,
        messages_synced: int,
        total_messages: int,
        cursor: Dict[str, Any]
    ) -> bool:
        """
        Update backfill progress and cursor.
        Called after each batch to enable restart safety.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            messages_synced: Total messages synced so far
            total_messages: Estimated total messages
            cursor: Provider-specific cursor dict
            
        Returns:
            True if update succeeded
        """
        progress = (messages_synced / total_messages * 100) if total_messages > 0 else 0
        
        result = self.collection.update_one(
            {
                "mailbox_id": mailbox_id,
                "status": SyncStatus.BACKFILL_RUNNING.value,
            },
            {
                "$set": {
                    "backfill_messages_synced": messages_synced,
                    "backfill_messages_total": total_messages,
                    "backfill_progress_percent": min(progress, 99.9),  # Reserve 100 for completion
                    "updated_at": datetime.utcnow(),
                    **cursor,
                }
            }
        )
        
        return result.modified_count > 0
    
    def update_incremental_cursor(
        self,
        mailbox_id: str,
        cursor: Dict[str, Any]
    ) -> bool:
        """
        Update incremental sync cursor.
        Called after each batch during incremental sync.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            cursor: Provider-specific cursor dict
            
        Returns:
            True if update succeeded
        """
        result = self.collection.update_one(
            {
                "mailbox_id": mailbox_id,
                "status": SyncStatus.INCREMENTAL_RUNNING.value,
            },
            {
                "$set": {
                    "last_incremental_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    **cursor,
                }
            }
        )
        
        return result.modified_count > 0
    
    def complete_backfill(self, mailbox_id: str) -> Tuple[bool, Optional[SyncStateDocument]]:
        """
        Mark backfill as complete and transition to incremental sync.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            Tuple of (success, state)
        """
        return self.transition(mailbox_id, SyncStatus.BACKFILL_COMPLETED)
    
    def record_error(
        self,
        mailbox_id: str,
        error: str
    ) -> Tuple[bool, Optional[SyncStateDocument]]:
        """
        Record an error and transition to ERROR state.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            error: Error message
            
        Returns:
            Tuple of (success, state)
        """
        return self.transition(mailbox_id, SyncStatus.ERROR, error=error)
    
    def should_retry(self, mailbox_id: str) -> Tuple[bool, int]:
        """
        Check if mailbox should retry after error.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            Tuple of (should_retry, backoff_seconds)
        """
        state = self.get_state(mailbox_id)
        if not state:
            return False, 0
        
        if state.status != SyncStatus.ERROR:
            return False, 0
        
        if state.consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
            logger.warning(f"Mailbox {mailbox_id} exceeded max consecutive errors")
            return False, 0
        
        # Exponential backoff
        backoff = min(
            self.BASE_BACKOFF_SECONDS * (2 ** state.consecutive_errors),
            self.MAX_BACKOFF_SECONDS
        )
        
        if state.last_error_at:
            elapsed = (datetime.utcnow() - state.last_error_at).total_seconds()
            if elapsed < backoff:
                return False, int(backoff - elapsed)
        
        return True, 0
    
    def pause_for_rate_limit(
        self,
        mailbox_id: str,
        resume_after_seconds: int = 60
    ) -> Tuple[bool, Optional[SyncStateDocument]]:
        """
        Pause sync due to rate limiting.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            resume_after_seconds: Seconds until resume
            
        Returns:
            Tuple of (success, state)
        """
        result = self.collection.find_one_and_update(
            {
                "mailbox_id": mailbox_id,
                "status": {"$in": [
                    SyncStatus.BACKFILL_RUNNING.value,
                    SyncStatus.INCREMENTAL_RUNNING.value,
                ]},
            },
            {
                "$set": {
                    "status": SyncStatus.PAUSED.value,
                    "updated_at": datetime.utcnow(),
                }
            },
            return_document=ReturnDocument.AFTER
        )
        
        if result:
            result["_id"] = str(result["_id"])
            logger.info(f"Paused mailbox {mailbox_id} for rate limit")
            return True, SyncStateDocument(**result)
        
        return False, None
    
    def get_mailboxes_needing_sync(self, limit: int = 10) -> list:
        """
        Get mailboxes that need incremental sync.
        
        Args:
            limit: Maximum number of mailboxes to return
            
        Returns:
            List of mailbox_ids
        """
        # Find mailboxes with completed backfill that are idle
        cursor = self.collection.find(
            {
                "status": {"$in": [
                    SyncStatus.IDLE.value,
                    SyncStatus.BACKFILL_COMPLETED.value,
                ]},
                "backfill_completed_at": {"$ne": None},
            },
            {"mailbox_id": 1}
        ).limit(limit)
        
        return [doc["mailbox_id"] for doc in cursor]
    
    def get_pending_backfills(self, limit: int = 10) -> list:
        """
        Get mailboxes with pending backfills.
        
        Args:
            limit: Maximum number to return
            
        Returns:
            List of mailbox_ids
        """
        cursor = self.collection.find(
            {"status": SyncStatus.BACKFILL_PENDING.value},
            {"mailbox_id": 1}
        ).limit(limit)
        
        return [doc["mailbox_id"] for doc in cursor]
    
    def reset_to_idle(self, mailbox_id: str) -> bool:
        """
        Force reset a mailbox to IDLE state.
        Use with caution - mainly for manual intervention.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            True if reset succeeded
        """
        result = self.collection.update_one(
            {"mailbox_id": mailbox_id},
            {
                "$set": {
                    "status": SyncStatus.IDLE.value,
                    "consecutive_errors": 0,
                    "last_error": None,
                    "updated_at": datetime.utcnow(),
                }
            }
        )
        
        if result.modified_count > 0:
            logger.info(f"Reset mailbox {mailbox_id} to IDLE")
            return True
        return False
