"""
CRM EMAIL SYNC SYSTEM
=====================

Production-grade email synchronization system for CRM with:
- Historical backfill support
- Incremental sync via Gmail History API and IMAP UID
- Strong deduplication guarantees
- Async categorization pipeline
- Rate limiting per mailbox and global

Modules:
- models: Database schemas and data models
- state_machine: Sync state management
- gmail_sync: Gmail API sync implementation
- imap_sync: IMAP UID-based sync implementation
- workers: Async task workers
- alias_resolver: Map emails to aliases
- rate_limiter: Rate limit enforcement
- storage: Email persistence with deduplication
- orchestrator: Main coordinator
- router: FastAPI endpoints

Usage:
    from email_sync import EmailSyncOrchestrator
    from email_sync.router import router
    
    # FastAPI integration
    app.include_router(router)
    
    # Or standalone
    orchestrator = EmailSyncOrchestrator(mongo_uri="mongodb://localhost:27017")
    orchestrator.start()
"""

# Models
from .models import (
    EmailDocument,
    MailboxDocument,
    AliasDocument,
    SyncStateDocument,
    CategorizationResult,
    ProviderType,
    SyncType,
    SyncStatus,
    EmailCategory,
    CategorizationStatus,
    GmailSyncCursor,
    ImapSyncCursor,
)

# Core services
from .storage import EmailStorage
from .state_machine import SyncStateMachine
from .rate_limiter import RateLimiter, GlobalRateLimiter
from .alias_resolver import AliasResolver

# Sync implementations
from .gmail_sync import GmailSyncer
from .imap_sync import ImapSyncer

# Workers
from .workers import (
    BackfillWorker,
    IncrementalSyncWorker,
    CategorizationWorker,
    WorkerManager,
)

# OpenAI Email Classifier (Two-tier with Gemini fallback)
from .openai_email_classifier import (
    OpenAIEmailClassifier,
    OpenAIClassificationWorker,
    classify_single_email,
    start_background_classification,
)

# Orchestrator
from .orchestrator import EmailSyncOrchestrator

# Router
from .router import router

__all__ = [
    # Models
    "EmailDocument",
    "MailboxDocument",
    "AliasDocument",
    "SyncStateDocument",
    "CategorizationResult",
    "ProviderType",
    "SyncType",
    "SyncStatus",
    "EmailCategory",
    "CategorizationStatus",
    "GmailSyncCursor",
    "ImapSyncCursor",
    # Services
    "EmailStorage",
    "SyncStateMachine",
    "RateLimiter",
    "GlobalRateLimiter",
    "AliasResolver",
    # Sync
    "GmailSyncer",
    "ImapSyncer",
    # Workers
    "BackfillWorker",
    "IncrementalSyncWorker",
    "CategorizationWorker",
    "WorkerManager",
    # OpenAI Email Classifier
    "OpenAIEmailClassifier",
    "OpenAIClassificationWorker",
    "classify_single_email",
    "start_background_classification",
    # Main
    "EmailSyncOrchestrator",
    "router",
]
