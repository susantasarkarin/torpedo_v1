"""
EMAIL SYNC DATA MODELS
======================

MongoDB Schema Design for Production-Grade Email Sync System

Collections:
- mailboxes: Authenticated email accounts (Gmail OAuth / IMAP credentials)
- aliases: Email aliases associated with mailboxes (metadata only)
- emails: Synced email messages with deduplication
- sync_state: Sync cursors and state per mailbox
- categorization_queue: Queue for async email categorization
- rate_limits: Per-mailbox rate limit tracking

Key Design Decisions:
1. Unique constraint: (mailbox_id, provider_message_id) prevents duplicates
2. Mailbox vs Alias: Mailboxes have credentials, aliases are metadata only
3. Sync state is separate to enable restart safety
4. Categorization is decoupled from ingestion
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from pydantic import BaseModel, Field


# ============== ENUMS ==============

class ProviderType(str, Enum):
    """Email provider types"""
    GMAIL = "gmail"
    IMAP = "imap"


class SyncType(str, Enum):
    """Type of sync operation"""
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"


class SyncStatus(str, Enum):
    """Sync state status"""
    IDLE = "idle"
    BACKFILL_PENDING = "backfill_pending"
    BACKFILL_RUNNING = "backfill_running"
    BACKFILL_COMPLETED = "backfill_completed"
    INCREMENTAL_RUNNING = "incremental_running"
    ERROR = "error"
    PAUSED = "paused"


class EmailDirection(str, Enum):
    """Email direction"""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class EmailCategory(str, Enum):
    """Email categories for CRM"""
    OUTREACH = "outreach"
    DISCOVERY = "discovery"
    RFQ_PRICING = "rfq_pricing"
    NEGOTIATION = "negotiation"
    INVOICE = "invoice"
    BANKING = "banking"
    INTERNAL = "internal"
    PROMOTIONAL = "promotional"
    OTHERS = "others"
    UNCATEGORIZED = "uncategorized"


class CategorizationStatus(str, Enum):
    """Categorization processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ============== MAILBOX MODEL ==============

class MailboxCredentials(BaseModel):
    """Credentials for mailbox authentication"""
    # Gmail OAuth
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expiry: Optional[datetime] = None
    
    # IMAP credentials
    imap_password: Optional[str] = None  # App password
    imap_server: Optional[str] = None
    imap_port: int = 993
    smtp_server: Optional[str] = None
    smtp_port: int = 587
    use_ssl: bool = True


class MailboxDocument(BaseModel):
    """
    Mailbox represents an authenticated email account.
    
    Collection: mailboxes
    Indexes:
        - email (unique)
        - provider
        - is_active
    """
    # Identity
    id: Optional[str] = Field(None, alias="_id", description="MongoDB ObjectId")
    email: str = Field(..., description="Primary email address")
    display_name: str = ""
    
    # Provider config
    provider: ProviderType = ProviderType.IMAP
    credentials: MailboxCredentials = Field(default_factory=MailboxCredentials)
    
    # Status
    is_active: bool = True
    is_default: bool = False
    
    # Sync config
    sync_enabled: bool = True
    sync_inbox: bool = True
    sync_sent: bool = True
    historical_days: int = Field(365, description="Days of history to backfill (0 = all)")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    
    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}


# ============== ALIAS MODEL ==============

class AliasDocument(BaseModel):
    """
    Alias is metadata only - no OAuth, no inbox, no rate limits.
    Used to map incoming emails to the correct mailbox.
    
    Collection: aliases
    Indexes:
        - alias_email (unique)
        - mailbox_id
    """
    id: Optional[str] = Field(None, alias="_id")
    mailbox_id: str = Field(..., description="Reference to parent mailbox")
    alias_email: str = Field(..., description="Alias email address")
    display_name: str = ""
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True


# ============== EMAIL MODEL ==============

class EmailAddress(BaseModel):
    """Parsed email address with name"""
    email: str
    name: str = ""


class EmailDocument(BaseModel):
    """
    Email message stored in CRM.
    
    Collection: emails
    Indexes:
        - (mailbox_id, provider_message_id) UNIQUE - prevents duplicates
        - provider_thread_id
        - alias_id
        - direction
        - timestamp
        - processed (for categorization queue)
        - category
    """
    id: Optional[str] = Field(None, alias="_id")
    
    # Provider identifiers
    provider_message_id: str = Field(..., description="Gmail messageId or IMAP Message-ID header")
    provider_thread_id: Optional[str] = Field(None, description="Gmail threadId or References/In-Reply-To")
    
    # Attribution
    mailbox_id: str = Field(..., description="Reference to mailbox")
    alias_id: Optional[str] = Field(None, description="Reference to alias if matched")
    
    # Direction
    direction: EmailDirection = EmailDirection.INBOUND
    
    # Headers
    from_address: EmailAddress
    to_addresses: List[EmailAddress] = []
    cc_addresses: List[EmailAddress] = []
    bcc_addresses: List[EmailAddress] = []
    reply_to: Optional[str] = None
    delivered_to: Optional[str] = None
    
    # Content
    subject: str = ""
    body_plain: str = ""
    body_html: str = ""
    snippet: str = Field("", description="Preview text (first 200 chars)")
    
    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    internal_date: Optional[int] = Field(None, description="Gmail internalDate (epoch ms)")
    labels: List[str] = Field([], description="Gmail labels or IMAP folder")
    
    # Attachments
    has_attachments: bool = False
    attachment_count: int = 0
    attachments: List[Dict[str, Any]] = []
    
    # Raw data (for debugging/reprocessing)
    raw_headers: Dict[str, str] = {}
    
    # Sync metadata
    sync_source: SyncType = SyncType.BACKFILL
    synced_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Categorization (set by async worker)
    processed: bool = Field(False, description="Whether categorization has run")
    category: EmailCategory = EmailCategory.UNCATEGORIZED
    category_confidence: float = Field(0.0, description="AI confidence score 0-1")
    category_model_version: str = ""
    categorized_at: Optional[datetime] = None
    
    # CRM linking (set by CRM worker)
    crm_contact_id: Optional[str] = None
    crm_lead_id: Optional[str] = None
    crm_rfq_id: Optional[str] = None
    crm_linked_at: Optional[datetime] = None
    
    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}


# ============== SYNC STATE MODEL ==============

class GmailSyncCursor(BaseModel):
    """Gmail-specific sync cursor"""
    history_id: Optional[str] = Field(None, description="Last processed historyId")
    page_token: Optional[str] = Field(None, description="Pagination token for backfill")
    last_message_id: Optional[str] = None
    messages_synced: int = 0


class ImapSyncCursor(BaseModel):
    """IMAP-specific sync cursor"""
    inbox_last_uid: int = Field(0, description="Last UID synced from INBOX")
    sent_last_uid: int = Field(0, description="Last UID synced from Sent")
    inbox_uidvalidity: Optional[int] = None
    sent_uidvalidity: Optional[int] = None
    messages_synced: int = 0


class SyncStateDocument(BaseModel):
    """
    Sync state per mailbox - enables restart safety.
    
    Collection: sync_state
    Indexes:
        - mailbox_id (unique)
    """
    id: Optional[str] = Field(None, alias="_id")
    mailbox_id: str = Field(..., description="Reference to mailbox")
    
    # Current status
    status: SyncStatus = SyncStatus.IDLE
    
    # Backfill state
    backfill_started_at: Optional[datetime] = None
    backfill_completed_at: Optional[datetime] = None
    backfill_progress_percent: float = 0.0
    backfill_messages_total: int = 0
    backfill_messages_synced: int = 0
    
    # Incremental sync state
    last_incremental_at: Optional[datetime] = None
    incremental_errors_count: int = 0
    
    # Provider-specific cursors
    gmail_cursor: Optional[GmailSyncCursor] = None
    imap_cursor: Optional[ImapSyncCursor] = None
    
    # Error tracking
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    consecutive_errors: int = 0
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True


# ============== CATEGORIZATION QUEUE ==============

class CategorizationQueueItem(BaseModel):
    """
    Item in the categorization queue.
    
    Collection: categorization_queue
    Indexes:
        - email_id (unique)
        - status
        - created_at
    """
    id: Optional[str] = Field(None, alias="_id")
    email_id: str = Field(..., description="Reference to email document")
    mailbox_id: str
    
    # Processing state
    status: CategorizationStatus = CategorizationStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    
    # Input data (denormalized for worker efficiency)
    subject: str = ""
    body_preview: str = ""
    from_email: str = ""
    
    # Result
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    class Config:
        populate_by_name = True


class CategorizationResult(BaseModel):
    """Result of email categorization"""
    category: EmailCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    model_version: str = ""
    reasoning: str = ""
    subcategories: List[str] = []


# ============== RATE LIMIT MODEL ==============

class RateLimitWindow(BaseModel):
    """Rate limit tracking for a time window"""
    count: int = 0
    window_start: datetime = Field(default_factory=datetime.utcnow)
    

class RateLimitDocument(BaseModel):
    """
    Rate limit tracking per mailbox.
    
    Collection: rate_limits
    Indexes:
        - mailbox_id (unique)
    """
    id: Optional[str] = Field(None, alias="_id")
    mailbox_id: str
    
    # Per-minute tracking
    minute_window: RateLimitWindow = Field(default_factory=RateLimitWindow)
    
    # Per-hour tracking  
    hour_window: RateLimitWindow = Field(default_factory=RateLimitWindow)
    
    # Per-day tracking
    day_window: RateLimitWindow = Field(default_factory=RateLimitWindow)
    
    # Last request time
    last_request_at: Optional[datetime] = None
    
    # Backoff state
    backoff_until: Optional[datetime] = None
    consecutive_rate_limits: int = 0
    
    # Timestamps
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True


# ============== WORKER MODELS ==============

class WorkerTaskType(str, Enum):
    """Types of async worker tasks"""
    BACKFILL_GMAIL = "backfill_gmail"
    BACKFILL_IMAP = "backfill_imap"
    INCREMENTAL_GMAIL = "incremental_gmail"
    INCREMENTAL_IMAP = "incremental_imap"
    CATEGORIZE = "categorize"
    CRM_LINK = "crm_link"


class WorkerTask(BaseModel):
    """
    Async worker task definition.
    
    Collection: worker_tasks
    Indexes:
        - task_type
        - status
        - scheduled_at
        - mailbox_id
    """
    id: Optional[str] = Field(None, alias="_id")
    task_type: WorkerTaskType
    mailbox_id: Optional[str] = None
    
    # Task payload
    payload: Dict[str, Any] = {}
    
    # Scheduling
    scheduled_at: datetime = Field(default_factory=datetime.utcnow)
    priority: int = Field(0, description="Higher = more urgent")
    
    # Execution state
    status: str = "pending"  # pending, running, completed, failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Result
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempts: int = 0
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
