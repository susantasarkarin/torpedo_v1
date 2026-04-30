"""
ORCHESTRATOR
============

Main orchestrator for the email sync system.

Coordinates:
- Worker lifecycle
- Mailbox registration
- Manual sync triggers
- Health monitoring
- Configuration management
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError
from bson import ObjectId

try:
    from ..database import get_client
except ImportError:
    from database import get_client

from .models import (
    MailboxDocument,
    AliasDocument,
    SyncStateDocument,
    SyncStatus,
    SyncType,
    ProviderType,
    GmailSyncCursor,
    ImapSyncCursor,
)
from .workers import WorkerManager
from .state_machine import SyncStateMachine
from .rate_limiter import RateLimiter, GlobalRateLimiter
from .storage import EmailStorage

logger = logging.getLogger(__name__)


class EmailSyncOrchestrator:
    """
    Main orchestrator for the email sync system.
    
    Responsibilities:
    - Manage mailbox registration
    - Trigger and monitor syncs
    - Coordinate workers
    - Report health and metrics
    
    Usage:
        orchestrator = EmailSyncOrchestrator(mongo_uri)
        orchestrator.start()
        
        # Register mailbox
        orchestrator.register_mailbox(...)
        
        # Stop
        orchestrator.stop()
    """
    
    def __init__(
        self,
        mongo_uri: str = None,
        db: MongoClient = None,
        db_name: str = "campaign_platform"
    ):
        """
        Initialize orchestrator.
        
        Args:
            mongo_uri: MongoDB connection URI
            db: Existing database instance (optional)
            db_name: Database name
        """
        if db:
            self.db = db
        elif mongo_uri:
            self.db = get_client()[db_name]
        else:
            raise ValueError("Either mongo_uri or db must be provided")
        
        # Collections
        self.mailboxes = self.db["mailboxes"]
        self.aliases = self.db["aliases"]
        self.emails = self.db["emails"]
        self.sync_states = self.db["sync_states"]
        
        # Services
        self.storage = EmailStorage(self.db)
        self.state_machine = SyncStateMachine(self.db)
        self.rate_limiter = RateLimiter(self.db)
        self.global_limiter = GlobalRateLimiter(self.db)
        self.worker_manager = WorkerManager(self.db)
        
        # Ensure indexes
        self._ensure_indexes()
        
        self._started = False
    
    def _ensure_indexes(self):
        """Create required indexes - handles existing indexes gracefully"""
        from pymongo.errors import OperationFailure
        
        def safe_create_index(collection, keys, **kwargs):
            """Create index, ignoring conflicts with existing indexes"""
            try:
                collection.create_index(keys, **kwargs)
            except OperationFailure as e:
                if e.code in [85, 86]:  # IndexOptionsConflict, IndexKeySpecsConflict
                    logger.debug(f"Index already exists on {collection.name}: {e}")
                else:
                    raise
        
        # Mailboxes
        safe_create_index(self.mailboxes, "email", unique=True)
        safe_create_index(self.mailboxes, "is_active")
        
        # Aliases
        safe_create_index(self.aliases, [("mailbox_id", ASCENDING), ("alias_email", ASCENDING)], unique=True)
        safe_create_index(self.aliases, "alias_email")
        
        # Emails - critical deduplication index
        safe_create_index(
            self.emails,
            [("mailbox_id", ASCENDING), ("provider_message_id", ASCENDING)],
            unique=True
        )
        safe_create_index(self.emails, "alias_id")
        safe_create_index(self.emails, "received_at")
        safe_create_index(self.emails, [("is_processed", ASCENDING), ("categorization_status", ASCENDING)])
        
        # Sync states
        safe_create_index(self.sync_states, "mailbox_id", unique=True)
        
        logger.info("Database indexes ensured")
    
    def start(self):
        """Start the orchestrator and all workers"""
        if self._started:
            logger.warning("Orchestrator already started")
            return
        
        logger.info("Starting email sync orchestrator")
        self.worker_manager.start_all()
        self._started = True
    
    def stop(self):
        """Stop the orchestrator and all workers"""
        if not self._started:
            return
        
        logger.info("Stopping email sync orchestrator")
        self.worker_manager.stop_all()
        self._started = False
    
    # =========================================================================
    # MAILBOX MANAGEMENT
    # =========================================================================
    
    def register_mailbox(
        self,
        email: str,
        provider: ProviderType,
        display_name: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        auto_start_backfill: bool = True
    ) -> Dict[str, Any]:
        """
        Register a new mailbox for sync.
        
        Args:
            email: Primary email address
            provider: Provider type (gmail, imap)
            display_name: Human-readable name
            credentials: Auth credentials
            auto_start_backfill: Whether to trigger backfill immediately
            
        Returns:
            Dict with mailbox_id and status
        """
        # Create mailbox document
        mailbox = MailboxDocument(
            email=email,
            provider=provider,
            display_name=display_name or email,
            credentials=credentials or {},
            sync_enabled=True,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        try:
            result = self.mailboxes.insert_one(mailbox.dict(by_alias=True, exclude={"id"}))
            mailbox_id = str(result.inserted_id)
        except DuplicateKeyError:
            # Return existing mailbox
            existing = self.mailboxes.find_one({"email": email})
            return {
                "mailbox_id": str(existing["_id"]),
                "status": "existing",
                "message": "Mailbox already registered"
            }
        
        # Initialize sync state
        self.state_machine.initialize_state(mailbox_id, provider)
        
        # Auto-register primary email as alias
        self.register_alias(mailbox_id, email, is_primary=True)
        
        # Trigger backfill if requested
        if auto_start_backfill:
            self.state_machine.transition(mailbox_id, SyncStatus.BACKFILL_PENDING)
        
        logger.info(f"Registered mailbox: {email} ({mailbox_id})")
        
        return {
            "mailbox_id": mailbox_id,
            "status": "created",
            "message": "Mailbox registered successfully"
        }
    
    def register_alias(
        self,
        mailbox_id: str,
        alias_email: str,
        is_primary: bool = False,
        display_name: Optional[str] = None,
        signature: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Register an alias for a mailbox.
        
        Aliases are metadata-only - they don't have separate auth.
        
        Args:
            mailbox_id: Parent mailbox ID
            alias_email: Alias email address
            is_primary: Whether this is the primary alias
            display_name: Human-readable name
            signature: HTML email signature for this alias
            
        Returns:
            Dict with alias_id and status
        """
        alias = AliasDocument(
            mailbox_id=mailbox_id,
            alias_email=alias_email.lower(),
            display_name=display_name or alias_email,
            signature=signature or "",
            is_primary=is_primary,
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        try:
            result = self.aliases.insert_one(alias.dict(by_alias=True, exclude={"id"}))
            alias_id = str(result.inserted_id)
        except DuplicateKeyError:
            existing = self.aliases.find_one({
                "mailbox_id": mailbox_id,
                "alias_email": alias_email.lower()
            })
            return {
                "alias_id": str(existing["_id"]),
                "status": "existing",
                "message": "Alias already registered"
            }
        
        logger.info(f"Registered alias: {alias_email} for mailbox {mailbox_id}")
        
        return {
            "alias_id": alias_id,
            "status": "created",
            "message": "Alias registered successfully"
        }
    
    def update_mailbox(
        self,
        mailbox_id: str,
        **updates
    ) -> bool:
        """
        Update mailbox settings.
        
        Args:
            mailbox_id: Mailbox ID
            **updates: Fields to update
            
        Returns:
            True if updated
        """
        allowed_fields = [
            "display_name", "sync_enabled", "is_active",
            "credentials", "sync_interval_seconds"
        ]
        
        update_dict = {
            k: v for k, v in updates.items()
            if k in allowed_fields and v is not None
        }
        
        if not update_dict:
            return False
        
        update_dict["updated_at"] = datetime.utcnow()
        
        result = self.mailboxes.update_one(
            {"_id": ObjectId(mailbox_id)},
            {"$set": update_dict}
        )
        
        return result.modified_count > 0
    
    def delete_mailbox(self, mailbox_id: str, delete_emails: bool = False) -> bool:
        """
        Delete a mailbox.
        
        Args:
            mailbox_id: Mailbox ID
            delete_emails: Whether to also delete synced emails
            
        Returns:
            True if deleted
        """
        # Delete aliases
        self.aliases.delete_many({"mailbox_id": mailbox_id})
        
        # Delete sync state
        self.sync_states.delete_one({"mailbox_id": mailbox_id})
        
        # Optionally delete emails
        if delete_emails:
            self.emails.delete_many({"mailbox_id": mailbox_id})
        
        # Delete mailbox
        result = self.mailboxes.delete_one({"_id": ObjectId(mailbox_id)})
        
        logger.info(f"Deleted mailbox: {mailbox_id}")
        
        return result.deleted_count > 0
    
    # =========================================================================
    # SYNC CONTROLS
    # =========================================================================
    
    def trigger_backfill(self, mailbox_id: str) -> Dict[str, Any]:
        """
        Manually trigger backfill for a mailbox.
        
        Args:
            mailbox_id: Mailbox ID
            
        Returns:
            Status dict
        """
        state = self.state_machine.get_state(mailbox_id)
        
        if not state:
            return {"success": False, "message": "Mailbox not found"}
        
        if state.status == SyncStatus.BACKFILL_RUNNING:
            return {"success": False, "message": "Backfill already running"}
        
        # Reset cursors for full backfill
        self.sync_states.update_one(
            {"mailbox_id": mailbox_id},
            {
                "$set": {
                    "gmail_cursor": None,
                    "imap_cursor": None,
                    "backfill_started_at": None,
                    "backfill_completed_at": None,
                }
            }
        )
        
        success, _ = self.state_machine.transition(mailbox_id, SyncStatus.BACKFILL_PENDING)
        
        return {
            "success": success,
            "message": "Backfill triggered" if success else "Failed to trigger backfill"
        }
    
    def trigger_incremental_sync(self, mailbox_id: str) -> Dict[str, Any]:
        """
        Manually trigger incremental sync for a mailbox.
        
        Args:
            mailbox_id: Mailbox ID
            
        Returns:
            Status dict
        """
        state = self.state_machine.get_state(mailbox_id)
        
        if not state:
            return {"success": False, "message": "Mailbox not found"}
        
        if not state.backfill_completed_at:
            return {"success": False, "message": "Backfill must complete first"}
        
        # Update last_sync_at to force sync
        self.mailboxes.update_one(
            {"_id": ObjectId(mailbox_id)},
            {"$set": {"last_sync_at": datetime(2000, 1, 1)}}
        )
        
        return {"success": True, "message": "Incremental sync triggered"}
    
    def pause_sync(self, mailbox_id: str) -> bool:
        """Pause sync for a mailbox"""
        success, _ = self.state_machine.transition(mailbox_id, SyncStatus.PAUSED)
        return success
    
    def resume_sync(self, mailbox_id: str) -> bool:
        """Resume sync for a mailbox"""
        success, _ = self.state_machine.transition(mailbox_id, SyncStatus.IDLE)
        return success
    
    # =========================================================================
    # STATUS AND METRICS
    # =========================================================================
    
    def get_mailbox_status(self, mailbox_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed status for a mailbox.
        
        Args:
            mailbox_id: Mailbox ID
            
        Returns:
            Status dict or None
        """
        mailbox = self.mailboxes.find_one({"_id": ObjectId(mailbox_id)})
        if not mailbox:
            return None
        
        state = self.state_machine.get_state(mailbox_id)
        
        # Get email count
        email_count = self.emails.count_documents({"mailbox_id": mailbox_id})
        
        # Get aliases (convert ObjectId to string)
        raw_aliases = list(self.aliases.find(
            {"mailbox_id": mailbox_id},
            {"alias_email": 1, "is_primary": 1}
        ))
        aliases = [
            {"alias_email": a.get("alias_email"), "is_primary": a.get("is_primary", False)}
            for a in raw_aliases
        ]
        
        # Get rate limit status (returns tuple: (allowed, wait_seconds))
        rate_allowed, rate_wait = self.rate_limiter.check_rate_limit(mailbox_id)
        
        return {
            "mailbox_id": mailbox_id,
            "email": mailbox.get("email"),
            "display_name": mailbox.get("display_name"),
            "provider": mailbox.get("provider"),
            "sync_enabled": mailbox.get("sync_enabled"),
            "is_active": mailbox.get("is_active"),
            "last_sync_at": mailbox.get("last_sync_at"),
            "sync_status": state.status.value if state else "unknown",
            "backfill_progress": {
                "started_at": state.backfill_started_at if state else None,
                "completed_at": state.backfill_completed_at if state else None,
                "messages_synced": state.backfill_messages_synced if state else 0,
                "total_messages": state.backfill_messages_total if state else 0,
                "progress_percent": state.backfill_progress_percent if state else 0.0,
            },
            "email_count": email_count,
            "aliases": aliases,
            "rate_limit": {
                "allowed": rate_allowed,
                "wait_seconds": rate_wait
            },
            "error": state.last_error if state else None
        }
    
    def list_mailboxes(
        self,
        skip: int = 0,
        limit: int = 50,
        active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        List all mailboxes.
        
        Args:
            skip: Pagination offset
            limit: Page size
            active_only: Only return active mailboxes
            
        Returns:
            List of mailbox summaries
        """
        query = {}
        if active_only:
            query["is_active"] = True
        
        mailboxes = list(self.mailboxes.find(
            query,
            {
                "email": 1,
                "display_name": 1,
                "provider": 1,
                "sync_enabled": 1,
                "is_active": 1,
                "last_sync_at": 1
            }
        ).skip(skip).limit(limit))
        
        result = []
        for m in mailboxes:
            mailbox_id = str(m["_id"])
            state = self.state_machine.get_state(mailbox_id)
            
            result.append({
                "mailbox_id": mailbox_id,
                "email": m.get("email"),
                "display_name": m.get("display_name"),
                "provider": m.get("provider"),
                "sync_enabled": m.get("sync_enabled"),
                "is_active": m.get("is_active"),
                "last_sync_at": m.get("last_sync_at"),
                "sync_status": state.status.value if state else "unknown"
            })
        
        return result
    
    def get_system_health(self) -> Dict[str, Any]:
        """
        Get overall system health.
        
        Returns:
            Health status dict
        """
        # Worker status
        worker_status = self.worker_manager.get_status()
        
        # Mailbox stats
        total_mailboxes = self.mailboxes.count_documents({})
        active_mailboxes = self.mailboxes.count_documents({"is_active": True})
        
        # Sync state distribution
        state_counts = {}
        for status in SyncStatus:
            count = self.sync_states.count_documents({"status": status.value})
            if count > 0:
                state_counts[status.value] = count
        
        # Email stats
        total_emails = self.emails.count_documents({})
        pending_categorization = self.db["categorization_queue"].count_documents({
            "status": "pending"
        })
        
        # Global rate limits
        global_status = self.global_limiter.get_status()
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "workers": worker_status,
            "mailboxes": {
                "total": total_mailboxes,
                "active": active_mailboxes
            },
            "sync_states": state_counts,
            "emails": {
                "total": total_emails,
                "pending_categorization": pending_categorization
            },
            "global_limits": global_status,
            "healthy": all(w.get("running") for w in worker_status.values())
        }
    
    def get_sync_errors(
        self,
        mailbox_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get recent sync errors.
        
        Args:
            mailbox_id: Optional mailbox filter
            limit: Max errors to return
            
        Returns:
            List of error details
        """
        query = {"status": SyncStatus.ERROR.value}
        if mailbox_id:
            query["mailbox_id"] = mailbox_id
        
        errors = list(self.sync_states.find(
            query,
            {
                "mailbox_id": 1,
                "last_error": 1,
                "error_count": 1,
                "last_error_at": 1
            }
        ).sort("last_error_at", DESCENDING).limit(limit))
        
        return errors

    # =========================================================================
    # IMAP ACCOUNTS SYNC (Bridge with existing system)
    # =========================================================================
    
    def sync_from_imap_accounts(self) -> Dict[str, Any]:
        """
        Sync mailboxes from the existing imap_accounts collection in torpedo_gmail DB.
        
        This bridges the existing email accounts with the new Email Sync system.
        
        Returns:
            Dict with sync results
        """
        # Get the torpedo_gmail database (same client)
        client = self.db.client
        torpedo_db = client["torpedo_gmail"]
        imap_accounts = torpedo_db["imap_accounts"]
        
        # Get all active IMAP accounts
        accounts = list(imap_accounts.find({"is_active": True}))
        
        results = {
            "synced": 0,
            "existing": 0,
            "errors": 0,
            "details": []
        }
        
        for account in accounts:
            email = account.get("email")
            if not email:
                continue
            
            try:
                # Always use IMAP provider for App Password accounts
                # ProviderType.GMAIL is only for OAuth2-based Gmail API access
                provider = ProviderType.IMAP
                
                # Prepare credentials
                credentials = {
                    "imap_server": account.get("imap_server"),
                    "imap_port": account.get("imap_port", 993),
                    "smtp_server": account.get("smtp_server"),
                    "smtp_port": account.get("smtp_port", 587),
                    "imap_password": account.get("password"),  # App password
                    "use_ssl": account.get("use_ssl", True)
                }
                
                # Register mailbox (will skip if exists)
                result = self.register_mailbox(
                    email=email,
                    provider=provider,
                    display_name=account.get("display_name", email),
                    credentials=credentials,
                    auto_start_backfill=False  # Don't auto-start, let user trigger
                )
                
                if result["status"] == "created":
                    results["synced"] += 1
                else:
                    results["existing"] += 1
                
                results["details"].append({
                    "email": email,
                    "status": result["status"],
                    "mailbox_id": result["mailbox_id"]
                })
                
            except Exception as e:
                results["errors"] += 1
                results["details"].append({
                    "email": email,
                    "status": "error",
                    "error": str(e)
                })
                logger.error(f"Error syncing account {email}: {e}")
        
        logger.info(f"IMAP accounts sync complete: {results['synced']} synced, {results['existing']} existing, {results['errors']} errors")
        
        return results
