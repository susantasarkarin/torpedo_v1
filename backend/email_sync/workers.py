"""
ASYNC WORKERS
=============

Worker queue system for email sync operations.

Workers:
1. BackfillWorker - Handles historical email backfill
2. IncrementalSyncWorker - Handles live sync (~60 second intervals)
3. CategorizationWorker - Processes emails for categorization
4. CRMLinkWorker - Links emails to CRM entities

Design Principles:
- Workers are idempotent and crash-safe
- State is persisted in MongoDB
- Rate limits are respected
- Backfill never blocks live sync
"""

import os
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from pymongo import MongoClient
from bson import ObjectId

from .models import (
    ProviderType,
    SyncType,
    SyncStatus,
    EmailCategory,
    CategorizationStatus,
    WorkerTaskType,
    MailboxDocument,
)
from .state_machine import SyncStateMachine
from .rate_limiter import RateLimiter, GlobalRateLimiter
from .storage import EmailStorage
from .alias_resolver import AliasResolver
from .gmail_sync import GmailSyncer, create_credentials_from_tokens
from .imap_sync import ImapSyncer

logger = logging.getLogger(__name__)


class BaseWorker:
    """Base class for async workers"""
    
    def __init__(
        self,
        db: MongoClient,
        worker_name: str,
        poll_interval: int = 10
    ):
        """
        Initialize worker.
        
        Args:
            db: MongoDB database instance
            worker_name: Unique worker name
            poll_interval: Seconds between poll cycles
        """
        self.db = db
        self.worker_name = worker_name
        self.poll_interval = poll_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def start(self):
        """Start worker thread"""
        if self._running:
            logger.warning(f"{self.worker_name} already running")
            return
        
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=self.worker_name,
            daemon=True
        )
        self._thread.start()
        logger.info(f"{self.worker_name} started")
    
    def stop(self):
        """Stop worker thread"""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=30)
        logger.info(f"{self.worker_name} stopped")
    
    def _run_loop(self):
        """Main worker loop"""
        while self._running and not self._stop_event.is_set():
            try:
                self.process()
            except Exception as e:
                logger.error(f"{self.worker_name} error: {e}", exc_info=True)
            
            self._stop_event.wait(self.poll_interval)
    
    def process(self):
        """Process one cycle - to be implemented by subclasses"""
        raise NotImplementedError


class BackfillWorker(BaseWorker):
    """
    Handles historical email backfill.
    
    Design:
    - Picks up mailboxes with status=BACKFILL_PENDING
    - Claims task atomically
    - Syncs in batches, saving cursor after each
    - Pauses when rate limits approach threshold
    - Never blocks incremental sync
    """
    
    def __init__(
        self,
        db: MongoClient,
        mailboxes_collection: str = "mailboxes",
        **kwargs
    ):
        super().__init__(db, "BackfillWorker", poll_interval=30, **kwargs)
        
        self.mailboxes = db[mailboxes_collection]
        self.state_machine = SyncStateMachine(db)
        self.rate_limiter = RateLimiter(db)
        self.global_limiter = GlobalRateLimiter(db)
        self.storage = EmailStorage(db)
        self.alias_resolver = AliasResolver(db)
    
    def process(self):
        """Process pending backfills"""
        # Get pending backfill tasks
        pending = self.state_machine.get_pending_backfills(limit=1)
        
        if not pending:
            return
        
        for mailbox_id in pending:
            # Try to acquire global slot
            if not self.global_limiter.acquire_backfill_slot(mailbox_id):
                logger.debug(f"No backfill slots available for {mailbox_id}")
                continue
            
            try:
                self._process_backfill(mailbox_id)
            finally:
                self.global_limiter.release_backfill_slot(mailbox_id)
    
    def _process_backfill(self, mailbox_id: str):
        """
        Process backfill for a mailbox.
        
        Args:
            mailbox_id: Mailbox ObjectId string
        """
        # Claim the task atomically
        claimed, state = self.state_machine.claim_backfill_task(mailbox_id)
        if not claimed:
            logger.debug(f"Could not claim backfill for {mailbox_id}")
            return
        
        logger.info(f"Starting backfill for mailbox {mailbox_id}")
        
        # Get mailbox details
        mailbox_doc = self.mailboxes.find_one({"_id": ObjectId(mailbox_id)})
        if not mailbox_doc:
            logger.error(f"Mailbox {mailbox_id} not found")
            self.state_machine.record_error(mailbox_id, "Mailbox not found")
            return
        
        try:
            # Create syncer based on provider
            provider = mailbox_doc.get("provider", "imap")
            
            if provider == ProviderType.GMAIL.value:
                syncer = self._create_gmail_syncer(mailbox_id, mailbox_doc)
            else:
                syncer = self._create_imap_syncer(mailbox_id, mailbox_doc)
            
            if not syncer:
                self.state_machine.record_error(mailbox_id, "Failed to create syncer")
                return
            
            # Get resume cursor
            cursor = None
            if provider == ProviderType.GMAIL.value and state.gmail_cursor:
                cursor = state.gmail_cursor
            elif provider == ProviderType.IMAP.value and state.imap_cursor:
                cursor = state.imap_cursor
            
            # Run backfill
            total_synced = 0
            
            for documents, updated_cursor in syncer.backfill(cursor=cursor):
                if not self._running:
                    logger.info(f"Backfill interrupted for {mailbox_id}")
                    break
                
                if documents:
                    # Resolve aliases
                    aliases = self.alias_resolver.get_aliases_for_mailbox(mailbox_id)
                    alias_emails = [a.get("alias_email", "") for a in aliases]
                    
                    for doc in documents:
                        alias_id, _ = self.alias_resolver.resolve(
                            mailbox_id,
                            mailbox_doc.get("email", ""),
                            doc.to_addresses,
                            doc.cc_addresses,
                            doc.delivered_to,
                            doc.raw_headers
                        )
                        doc.alias_id = alias_id
                    
                    # Save emails
                    stats = self.storage.save_emails_batch(documents)
                    total_synced += stats.get("inserted", 0)
                
                # Update progress
                cursor_dict = {}
                if provider == ProviderType.GMAIL.value:
                    cursor_dict["gmail_cursor"] = updated_cursor.dict()
                else:
                    cursor_dict["imap_cursor"] = updated_cursor.dict()
                
                self.state_machine.update_backfill_progress(
                    mailbox_id,
                    messages_synced=updated_cursor.messages_synced,
                    total_messages=updated_cursor.messages_synced + 100,  # Estimate
                    cursor=cursor_dict
                )
                
                # Check rate limit threshold
                if self.rate_limiter.should_pause_backfill(mailbox_id):
                    logger.info(f"Pausing backfill for {mailbox_id} - rate limit")
                    self.state_machine.pause_for_rate_limit(mailbox_id)
                    return
            
            # Complete backfill
            self.state_machine.complete_backfill(mailbox_id)
            logger.info(f"Backfill complete for {mailbox_id}: {total_synced} emails")
            
            # Update mailbox
            self.mailboxes.update_one(
                {"_id": ObjectId(mailbox_id)},
                {"$set": {"last_sync_at": datetime.utcnow()}}
            )
            
        except Exception as e:
            logger.error(f"Backfill failed for {mailbox_id}: {e}", exc_info=True)
            self.state_machine.record_error(mailbox_id, str(e))
    
    def _create_gmail_syncer(
        self,
        mailbox_id: str,
        mailbox_doc: Dict
    ) -> Optional[GmailSyncer]:
        """Create Gmail syncer from mailbox document"""
        try:
            creds = mailbox_doc.get("credentials", {})
            credentials = create_credentials_from_tokens(
                access_token=creds.get("access_token", ""),
                refresh_token=creds.get("refresh_token", ""),
                token_expiry=creds.get("token_expiry")
            )
            
            return GmailSyncer(
                db=self.db,
                mailbox_id=mailbox_id,
                mailbox_email=mailbox_doc.get("email", ""),
                credentials=credentials,
                rate_limiter=self.rate_limiter
            )
        except Exception as e:
            logger.error(f"Failed to create Gmail syncer: {e}")
            return None
    
    def _create_imap_syncer(
        self,
        mailbox_id: str,
        mailbox_doc: Dict
    ) -> Optional[ImapSyncer]:
        """Create IMAP syncer from mailbox document"""
        try:
            creds = mailbox_doc.get("credentials", {})
            
            return ImapSyncer(
                db=self.db,
                mailbox_id=mailbox_id,
                mailbox_email=mailbox_doc.get("email", ""),
                password=creds.get("imap_password", ""),
                imap_server=creds.get("imap_server", "imap.gmail.com"),
                imap_port=creds.get("imap_port", 993),
                use_ssl=creds.get("use_ssl", True),
                rate_limiter=self.rate_limiter
            )
        except Exception as e:
            logger.error(f"Failed to create IMAP syncer: {e}")
            return None


class IncrementalSyncWorker(BaseWorker):
    """
    Handles incremental email sync (~60 second intervals).
    
    Design:
    - Polls mailboxes with completed backfill
    - Uses History API (Gmail) or UID comparison (IMAP)
    - Higher priority than backfill
    - Lightweight and fast
    """
    
    SYNC_INTERVAL_SECONDS = 60
    
    def __init__(
        self,
        db: MongoClient,
        mailboxes_collection: str = "mailboxes",
        **kwargs
    ):
        super().__init__(db, "IncrementalSyncWorker", poll_interval=30, **kwargs)
        
        self.mailboxes = db[mailboxes_collection]
        self.state_machine = SyncStateMachine(db)
        self.rate_limiter = RateLimiter(db)
        self.global_limiter = GlobalRateLimiter(db)
        self.storage = EmailStorage(db)
        self.alias_resolver = AliasResolver(db)
    
    def process(self):
        """Process incremental syncs"""
        # Get mailboxes needing sync
        mailbox_ids = self._get_mailboxes_needing_sync()
        
        for mailbox_id in mailbox_ids:
            if not self._running:
                break
            
            # Try to acquire sync slot
            if not self.global_limiter.acquire_sync_slot(mailbox_id):
                continue
            
            try:
                self._process_sync(mailbox_id)
            finally:
                self.global_limiter.release_sync_slot(mailbox_id)
    
    def _get_mailboxes_needing_sync(self, limit: int = 10) -> List[str]:
        """Get mailboxes that need incremental sync"""
        cutoff = datetime.utcnow() - timedelta(seconds=self.SYNC_INTERVAL_SECONDS)
        
        # Find mailboxes with completed backfill and stale sync
        mailboxes = self.mailboxes.find(
            {
                "sync_enabled": True,
                "is_active": True,
                "$or": [
                    {"last_sync_at": {"$lt": cutoff}},
                    {"last_sync_at": None}
                ]
            },
            {"_id": 1}
        ).limit(limit)
        
        mailbox_ids = []
        for m in mailboxes:
            mailbox_id = str(m["_id"])
            
            # Check state
            state = self.state_machine.get_state(mailbox_id)
            if state and state.backfill_completed_at:
                if state.status in [SyncStatus.IDLE, SyncStatus.BACKFILL_COMPLETED]:
                    mailbox_ids.append(mailbox_id)
        
        return mailbox_ids
    
    def _process_sync(self, mailbox_id: str):
        """Process incremental sync for a mailbox"""
        # Transition to running
        success, state = self.state_machine.transition(
            mailbox_id,
            SyncStatus.INCREMENTAL_RUNNING
        )
        
        if not success:
            return
        
        logger.info(f"Starting incremental sync for {mailbox_id}")
        
        # Get mailbox details
        mailbox_doc = self.mailboxes.find_one({"_id": ObjectId(mailbox_id)})
        if not mailbox_doc:
            logger.error(f"Mailbox {mailbox_id} not found")
            return
        
        try:
            provider = mailbox_doc.get("provider", "imap")
            
            # Create syncer
            if provider == ProviderType.GMAIL.value:
                syncer = BackfillWorker._create_gmail_syncer(
                    self, mailbox_id, mailbox_doc
                )
                cursor = state.gmail_cursor
            else:
                syncer = BackfillWorker._create_imap_syncer(
                    self, mailbox_id, mailbox_doc
                )
                cursor = state.imap_cursor
            
            if not syncer or not cursor:
                self.state_machine.transition(mailbox_id, SyncStatus.IDLE)
                return
            
            # Run incremental sync
            total_synced = 0
            
            for documents, updated_cursor in syncer.incremental_sync(cursor):
                if documents:
                    # Resolve aliases
                    for doc in documents:
                        alias_id, _ = self.alias_resolver.resolve(
                            mailbox_id,
                            mailbox_doc.get("email", ""),
                            doc.to_addresses,
                            doc.cc_addresses,
                            doc.delivered_to,
                            doc.raw_headers
                        )
                        doc.alias_id = alias_id
                    
                    # Save emails
                    stats = self.storage.save_emails_batch(documents)
                    total_synced += stats.get("inserted", 0)
                
                # Update cursor
                cursor_dict = {}
                if provider == ProviderType.GMAIL.value:
                    cursor_dict["gmail_cursor"] = updated_cursor.dict()
                else:
                    cursor_dict["imap_cursor"] = updated_cursor.dict()
                
                self.state_machine.update_incremental_cursor(mailbox_id, cursor_dict)
            
            # Complete sync
            self.state_machine.transition(mailbox_id, SyncStatus.IDLE)
            
            # Update mailbox
            self.mailboxes.update_one(
                {"_id": ObjectId(mailbox_id)},
                {"$set": {"last_sync_at": datetime.utcnow()}}
            )
            
            if total_synced > 0:
                logger.info(f"Incremental sync complete for {mailbox_id}: {total_synced} new emails")
            
        except Exception as e:
            logger.error(f"Incremental sync failed for {mailbox_id}: {e}", exc_info=True)
            self.state_machine.record_error(mailbox_id, str(e))


class CategorizationWorker(BaseWorker):
    """
    Processes emails for AI categorization.
    
    Design:
    - Runs independently from sync
    - Processes from categorization queue
    - Idempotent - can reprocess on failure
    - Updates email with category and confidence
    """
    
    BATCH_SIZE = 10
    
    def __init__(
        self,
        db: MongoClient,
        categorize_fn: Optional[Callable] = None,
        **kwargs
    ):
        """
        Initialize categorization worker.
        
        Args:
            db: MongoDB database instance
            categorize_fn: Function to categorize email (subject, body) -> (category, confidence)
        """
        super().__init__(db, "CategorizationWorker", poll_interval=5, **kwargs)
        
        self.storage = EmailStorage(db)
        self.queue = db["categorization_queue"]
        self.categorize_fn = categorize_fn or self._default_categorize
        self.model_version = "keyword-v1"
    
    def process(self):
        """Process categorization queue"""
        # Get pending items
        items = list(self.queue.find(
            {
                "status": CategorizationStatus.PENDING.value,
                "attempts": {"$lt": 3}
            }
        ).limit(self.BATCH_SIZE))
        
        for item in items:
            if not self._running:
                break
            
            self._process_item(item)
    
    def _process_item(self, item: Dict[str, Any]):
        """Process a single categorization item"""
        item_id = item["_id"]
        email_id = item["email_id"]
        
        # Mark as processing
        self.queue.update_one(
            {"_id": item_id},
            {
                "$set": {"status": CategorizationStatus.PROCESSING.value, "started_at": datetime.utcnow()},
                "$inc": {"attempts": 1}
            }
        )
        
        try:
            # Categorize
            category, confidence = self.categorize_fn(
                item.get("subject", ""),
                item.get("body_preview", ""),
                item.get("from_email", "")
            )
            
            # Update email
            self.storage.update_categorization(
                email_id,
                category=category,
                confidence=confidence,
                model_version=self.model_version
            )
            
            # Mark as complete
            self.queue.update_one(
                {"_id": item_id},
                {
                    "$set": {
                        "status": CategorizationStatus.COMPLETED.value,
                        "completed_at": datetime.utcnow(),
                        "result": {"category": category, "confidence": confidence}
                    }
                }
            )
            
        except Exception as e:
            logger.warning(f"Categorization failed for email {email_id}: {e}")
            
            self.queue.update_one(
                {"_id": item_id},
                {
                    "$set": {
                        "status": CategorizationStatus.PENDING.value if item.get("attempts", 0) < 2 else CategorizationStatus.FAILED.value,
                        "error": str(e)
                    }
                }
            )
    
    def _default_categorize(
        self,
        subject: str,
        body: str,
        from_email: str
    ) -> tuple:
        """
        Default keyword-based categorization.
        
        Args:
            subject: Email subject
            body: Email body preview
            from_email: Sender email
            
        Returns:
            Tuple of (category, confidence)
        """
        content = f"{subject} {body}".lower()
        
        # Keyword patterns
        patterns = {
            EmailCategory.INVOICE.value: [
                "invoice", "payment", "due", "billing", "receipt", "outstanding"
            ],
            EmailCategory.RFQ_PRICING.value: [
                "rfq", "request for quote", "quotation", "pricing", "quote",
                "cost", "estimate", "budget", "price list"
            ],
            EmailCategory.NEGOTIATION.value: [
                "negotiate", "terms", "contract", "agreement", "counter offer",
                "final offer", "best price", "deal", "closing"
            ],
            EmailCategory.BANKING.value: [
                "bank", "account", "transfer", "wire", "routing", "swift"
            ],
            EmailCategory.DISCOVERY.value: [
                "demo", "learn more", "exploring", "considering", "evaluate",
                "discovery call", "capabilities"
            ],
            EmailCategory.OUTREACH.value: [
                "reaching out", "connect", "introduce", "partnership",
                "collaboration", "opportunity"
            ],
            EmailCategory.PROMOTIONAL.value: [
                "newsletter", "unsubscribe", "marketing", "promotion",
                "discount", "offer", "sale"
            ],
        }
        
        # Score each category
        scores = {}
        for category, keywords in patterns.items():
            score = sum(1 for kw in keywords if kw in content)
            if score > 0:
                scores[category] = score
        
        if scores:
            best = max(scores, key=scores.get)
            confidence = min(scores[best] / 5, 1.0)  # Normalize to 0-1
            return best, confidence
        
        return EmailCategory.OTHERS.value, 0.5


class WorkerManager:
    """
    Manages all email sync workers.
    
    Usage:
        manager = WorkerManager(db)
        manager.start_all()
        # ... application runs ...
        manager.stop_all()
    """
    
    def __init__(self, db: MongoClient):
        """
        Initialize worker manager.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.workers = {
            "backfill": BackfillWorker(db),
            "incremental": IncrementalSyncWorker(db),
            "categorization": CategorizationWorker(db),
        }
    
    def start_all(self):
        """Start all workers"""
        logger.info("Starting all email sync workers")
        for name, worker in self.workers.items():
            worker.start()
    
    def stop_all(self):
        """Stop all workers"""
        logger.info("Stopping all email sync workers")
        for name, worker in self.workers.items():
            worker.stop()
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all workers"""
        status = {}
        for name, worker in self.workers.items():
            status[name] = {
                "running": worker._running,
                "poll_interval": worker.poll_interval,
            }
        return status
    
    def start_worker(self, name: str):
        """Start a specific worker"""
        if name in self.workers:
            self.workers[name].start()
    
    def stop_worker(self, name: str):
        """Stop a specific worker"""
        if name in self.workers:
            self.workers[name].stop()
