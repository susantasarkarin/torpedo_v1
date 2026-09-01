"""
GMAIL API SERVICE
==================

Gmail API service for email synchronization with metadata-only storage.
Uses History API for efficient incremental sync.

Key Features:
1. OAuth 2.0 authentication with token refresh
2. History API for incremental sync (only new changes)
3. Metadata-only storage (fetch full content on-demand)
4. AI classification integration
5. Rate limiting and retry logic

Gmail API Quotas:
- messages.list: 5 quota units/call (100 results/page)
- messages.get: 5 quota units/call
- history.list: 2 quota units/call
- Per-user quota: 250 units/second
"""

import os
import base64
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Generator, Tuple
from email.utils import parsedate_to_datetime
from dataclasses import dataclass, field

from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from pymongo import MongoClient
from bson import ObjectId

logger = logging.getLogger(__name__)


# Gmail label constants
GMAIL_INBOX = "INBOX"
GMAIL_SENT = "SENT"
GMAIL_TRASH = "TRASH"
GMAIL_SPAM = "SPAM"


@dataclass
class EmailMetadata:
    """Lightweight email metadata for storage"""
    gmail_message_id: str
    gmail_thread_id: str
    mailbox_id: str
    from_email: str
    from_name: Optional[str]
    to_emails: List[str]
    cc_emails: List[str]
    subject: str
    snippet: str  # Gmail's preview text
    timestamp: datetime
    labels: List[str]
    direction: str  # inbound/outbound
    has_attachments: bool
    attachment_count: int
    is_read: bool
    is_starred: bool
    # AI classification fields
    ai_category: Optional[str] = None
    ai_confidence: Optional[float] = None
    ai_priority: Optional[str] = None
    ai_department: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_entities: Optional[Dict[str, Any]] = None
    ai_processed_at: Optional[datetime] = None
    # Sync metadata
    history_id: Optional[str] = None
    synced_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class GmailMailbox:
    """Gmail mailbox configuration"""
    id: str
    email: str
    display_name: str
    access_token: str
    refresh_token: str
    token_expiry: Optional[datetime]
    is_active: bool = True
    last_history_id: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    sync_error: Optional[str] = None


def _trigger_mail_ai(new_count: int, mailbox_email: Optional[str] = None) -> None:
    """
    Queue an AI analysis pass immediately after new mail lands.

    The scheduled beat already picks up only unanalyzed senders, so this does
    not add work — it removes latency. Without it a mail arriving just after a
    beat waits the full 10 minutes before its RFQ appears on the Sales page.

    Sizing: the AI batches by SENDER, and a sync usually brings in mail from
    far fewer senders than emails, so ceil(new_count / 4) capped at 50 is a
    generous upper bound on senders touched. The task itself re-queries for
    unanalyzed senders, so an over- or under-estimate only affects how much of
    the backlog this particular pass clears.

    Fully best-effort: a missing broker or a down worker must never fail a mail
    sync, because the beat will still catch the mail on its next run.
    """
    try:
        from tasks.mail_pool_ai_tasks import process_mail_pool_sender_batch
    except ImportError:  # pragma: no cover
        try:
            from tasks.mail_pool_ai_tasks import process_mail_pool_sender_batch
        except ImportError:
            logger.debug("[mail-ai] task module unavailable; leaving mail to the beat")
            return

    limit = max(1, min(50, -(-new_count // 4)))
    try:
        process_mail_pool_sender_batch.delay(limit=limit)
        logger.info(
            "[mail-ai] %d new emails from %s — queued AI pass for up to %d senders",
            new_count, mailbox_email or "mailbox", limit,
        )
    except Exception as e:
        # Broker down, or Celery not configured in this process.
        logger.warning(f"[mail-ai] could not queue AI pass (beat will cover it): {e}")


class GmailService:
    """
    Gmail API service for email operations.
    
    Usage:
        service = GmailService(mongo_uri, db_name)
        
        # Add mailbox with OAuth tokens
        mailbox_id = service.add_mailbox(email, tokens)
        
        # Sync emails (incremental after first sync)
        new_emails = service.sync_mailbox(mailbox_id)
        
        # Get email content on-demand
        full_email = service.get_email_content(mailbox_id, message_id)
    """
    
    # Batch sizes
    LIST_PAGE_SIZE = 100
    GET_BATCH_SIZE = 50
    HISTORY_PAGE_SIZE = 100
    
    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    
    def __init__(self, mongo_uri: str, db_name: str = "torpedo_gmail"):
        """Initialize Gmail service with MongoDB connection"""
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        
        # Collections
        self.mailboxes = self.db["mailboxes"]
        self.emails = self.db["email_metadata"]
        self.sync_state = self.db["sync_state"]
        
        # Create indexes
        self._create_indexes()
    
    def _create_indexes(self):
        """Create MongoDB indexes for efficient queries"""
        # Mailboxes
        self.mailboxes.create_index("email", unique=True)
        
        # Email metadata
        self.emails.create_index([("mailbox_id", 1), ("gmail_message_id", 1)], unique=True)
        self.emails.create_index([("mailbox_id", 1), ("timestamp", -1)])
        self.emails.create_index([("mailbox_id", 1), ("ai_category", 1)])
        self.emails.create_index([("mailbox_id", 1), ("direction", 1)])
        self.emails.create_index([("mailbox_id", 1), ("ai_department", 1)])
        self.emails.create_index("gmail_thread_id")
        self.emails.create_index("ai_processed_at")
        # mail_pool_ai.py's derive_segment() writes this flat-schema field;
        # the /mail-pool/stats segment-breakdown aggregation groups by it and
        # was timing out (8s cap) on a full unindexed scan of 447K+ docs,
        # silently falling back to an empty result.
        self.emails.create_index("segment")
    
    def _get_credentials(self, mailbox: Dict) -> Credentials:
        """Get OAuth credentials from mailbox, refreshing if needed"""
        creds = Credentials(
            token=mailbox.get("access_token"),
            refresh_token=mailbox.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        )
        
        # Refresh if expired
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
            # Update tokens in database
            self.mailboxes.update_one(
                {"_id": mailbox["_id"]},
                {
                    "$set": {
                        "access_token": creds.token,
                        "token_expiry": creds.expiry,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        
        return creds
    
    def _get_service(self, mailbox: Dict) -> Resource:
        """Get Gmail API service for mailbox"""
        creds = self._get_credentials(mailbox)
        return build("gmail", "v1", credentials=creds)
    
    # =========================================================================
    # MAILBOX MANAGEMENT
    # =========================================================================
    
    def add_mailbox(
        self,
        email: str,
        access_token: str,
        refresh_token: str,
        display_name: Optional[str] = None,
        token_expiry: Optional[datetime] = None
    ) -> str:
        """
        Add a new Gmail mailbox with OAuth tokens.
        
        Returns:
            Mailbox ID string
        """
        doc = {
            "email": email,
            "display_name": display_name or email.split("@")[0],
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expiry": token_expiry,
            "is_active": True,
            "last_history_id": None,
            "last_sync_at": None,
            "sync_error": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = self.mailboxes.insert_one(doc)
        return str(result.inserted_id)
    
    def get_mailbox(self, mailbox_id: str) -> Optional[Dict]:
        """Get mailbox by ID"""
        return self.mailboxes.find_one({"_id": ObjectId(mailbox_id)})
    
    def get_mailbox_by_email(self, email: str) -> Optional[Dict]:
        """Get mailbox by email address"""
        return self.mailboxes.find_one({"email": email})
    
    def list_mailboxes(self, active_only: bool = True) -> List[Dict]:
        """List all mailboxes"""
        query = {"is_active": True} if active_only else {}
        return list(self.mailboxes.find(query))
    
    def update_mailbox_tokens(
        self,
        mailbox_id: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        token_expiry: Optional[datetime] = None
    ):
        """Update OAuth tokens for mailbox"""
        update = {
            "access_token": access_token,
            "updated_at": datetime.utcnow()
        }
        if refresh_token:
            update["refresh_token"] = refresh_token
        if token_expiry:
            update["token_expiry"] = token_expiry
        
        self.mailboxes.update_one(
            {"_id": ObjectId(mailbox_id)},
            {"$set": update}
        )
    
    def deactivate_mailbox(self, mailbox_id: str):
        """Deactivate a mailbox"""
        self.mailboxes.update_one(
            {"_id": ObjectId(mailbox_id)},
            {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
        )
    
    # =========================================================================
    # EMAIL SYNC
    # =========================================================================

    def sync_mailbox(
        self,
        mailbox_id: str,
        max_results: int = 500,
        days_back: int = 30
    ) -> Tuple[int, int]:
        """
        Sync emails for a mailbox.
        Uses History API for incremental sync after first sync.
        
        Args:
            mailbox_id: Mailbox ID
            max_results: Max emails to sync (for initial backfill)
            days_back: Days of history for initial backfill
            
        Returns:
            Tuple of (new_emails_count, updated_emails_count)
        """
        mailbox = self.get_mailbox(mailbox_id)
        if not mailbox:
            raise ValueError(f"Mailbox not found: {mailbox_id}")
        
        if not mailbox.get("is_active"):
            raise ValueError(f"Mailbox is not active: {mailbox_id}")
        
        try:
            service = self._get_service(mailbox)
            
            if mailbox.get("last_history_id"):
                # Incremental sync using History API
                new_count, updated_count = self._incremental_sync(
                    service, mailbox, mailbox["last_history_id"]
                )
            else:
                # Initial backfill
                new_count = self._initial_backfill(
                    service, mailbox, max_results, days_back
                )
                updated_count = 0
            
            # Update sync timestamp
            self.mailboxes.update_one(
                {"_id": mailbox["_id"]},
                {
                    "$set": {
                        "last_sync_at": datetime.utcnow(),
                        "sync_error": None,
                        "updated_at": datetime.utcnow()
                    }
                }
            )

            # New mail landed — kick the AI analysis now instead of waiting for
            # the next 10-minute beat.
            if new_count:
                _trigger_mail_ai(new_count, mailbox.get("email"))

            return new_count, updated_count
            
        except Exception as e:
            logger.error(f"Sync error for {mailbox['email']}: {e}")
            self.mailboxes.update_one(
                {"_id": mailbox["_id"]},
                {
                    "$set": {
                        "sync_error": str(e),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            raise
    
    def _initial_backfill(
        self,
        service: Resource,
        mailbox: Dict,
        max_results: int,
        days_back: int
    ) -> int:
        """
        Initial email backfill using messages.list
        
        Returns:
            Number of emails synced
        """
        mailbox_id = str(mailbox["_id"])
        mailbox_email = mailbox["email"]
        
        # Build query for date range
        after_date = datetime.utcnow() - timedelta(days=days_back)
        query = f"after:{after_date.strftime('%Y/%m/%d')}"
        
        new_count = 0
        page_token = None
        latest_history_id = None
        
        while True:
            # List message IDs
            result = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=min(self.LIST_PAGE_SIZE, max_results - new_count),
                pageToken=page_token
            ).execute()
            
            messages = result.get("messages", [])
            if not messages:
                break
            
            # Fetch full message details in batches
            for i in range(0, len(messages), self.GET_BATCH_SIZE):
                batch = messages[i:i + self.GET_BATCH_SIZE]
                
                for msg_info in batch:
                    try:
                        # Fetch message metadata
                        msg = service.users().messages().get(
                            userId="me",
                            id=msg_info["id"],
                            format="metadata",
                            metadataHeaders=["From", "To", "Cc", "Subject", "Date"]
                        ).execute()
                        
                        # Parse and store
                        metadata = self._parse_message_metadata(msg, mailbox_id, mailbox_email)
                        if metadata:
                            self._upsert_email(metadata)
                            new_count += 1
                            
                            # Track latest history ID
                            if not latest_history_id or msg.get("historyId", "") > latest_history_id:
                                latest_history_id = msg.get("historyId")
                    
                    except HttpError as e:
                        if e.resp.status == 404:
                            # Message was deleted
                            continue
                        raise
            
            # Check if we've reached max_results
            if new_count >= max_results:
                break
            
            # Next page
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        
        # Store latest history ID for incremental sync
        if latest_history_id:
            self.mailboxes.update_one(
                {"_id": mailbox["_id"]},
                {"$set": {"last_history_id": latest_history_id}}
            )
        
        logger.info(f"Backfill complete for {mailbox_email}: {new_count} emails")
        return new_count
    
    def _incremental_sync(
        self,
        service: Resource,
        mailbox: Dict,
        start_history_id: str
    ) -> Tuple[int, int]:
        """
        Incremental sync using History API.
        
        Returns:
            Tuple of (new_emails, updated_emails)
        """
        mailbox_id = str(mailbox["_id"])
        mailbox_email = mailbox["email"]
        
        new_count = 0
        updated_count = 0
        page_token = None
        latest_history_id = start_history_id
        
        try:
            while True:
                result = service.users().history().list(
                    userId="me",
                    startHistoryId=start_history_id,
                    historyTypes=["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"],
                    maxResults=self.HISTORY_PAGE_SIZE,
                    pageToken=page_token
                ).execute()
                
                # Update history ID
                if result.get("historyId"):
                    latest_history_id = result["historyId"]
                
                history = result.get("history", [])
                
                for record in history:
                    # Handle new messages
                    for msg_added in record.get("messagesAdded", []):
                        msg = msg_added.get("message", {})
                        if msg.get("id"):
                            try:
                                full_msg = service.users().messages().get(
                                    userId="me",
                                    id=msg["id"],
                                    format="metadata",
                                    metadataHeaders=["From", "To", "Cc", "Subject", "Date"]
                                ).execute()
                                
                                metadata = self._parse_message_metadata(full_msg, mailbox_id, mailbox_email)
                                if metadata:
                                    if self._upsert_email(metadata):
                                        new_count += 1
                                    else:
                                        updated_count += 1
                            except HttpError as e:
                                if e.resp.status != 404:
                                    raise
                    
                    # Handle deleted messages
                    for msg_deleted in record.get("messagesDeleted", []):
                        msg = msg_deleted.get("message", {})
                        if msg.get("id"):
                            self.emails.delete_one({
                                "mailbox_id": mailbox_id,
                                "gmail_message_id": msg["id"]
                            })
                    
                    # Handle label changes (update read/starred status)
                    for label_change in record.get("labelsAdded", []) + record.get("labelsRemoved", []):
                        msg = label_change.get("message", {})
                        if msg.get("id") and msg.get("labelIds"):
                            self.emails.update_one(
                                {
                                    "mailbox_id": mailbox_id,
                                    "gmail_message_id": msg["id"]
                                },
                                {
                                    "$set": {
                                        "labels": msg["labelIds"],
                                        "is_read": "UNREAD" not in msg["labelIds"],
                                        "is_starred": "STARRED" in msg["labelIds"],
                                        "synced_at": datetime.utcnow()
                                    }
                                }
                            )
                
                # Next page
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
            
            # Update history ID
            self.mailboxes.update_one(
                {"_id": mailbox["_id"]},
                {"$set": {"last_history_id": latest_history_id}}
            )
            
            logger.info(f"Incremental sync for {mailbox_email}: {new_count} new, {updated_count} updated")
            return new_count, updated_count
            
        except HttpError as e:
            if e.resp.status == 404:
                # History ID expired, need to do a fresh sync
                logger.warning(f"History ID expired for {mailbox_email}, doing partial resync")
                self.mailboxes.update_one(
                    {"_id": mailbox["_id"]},
                    {"$set": {"last_history_id": None}}
                )
                # Resync last 7 days
                return self._initial_backfill(service, mailbox, 1000, 7), 0
            raise
    
    def _parse_message_metadata(
        self,
        msg: Dict,
        mailbox_id: str,
        mailbox_email: str
    ) -> Optional[EmailMetadata]:
        """Parse Gmail message into EmailMetadata"""
        try:
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            
            # Parse addresses
            from_header = headers.get("from", "")
            from_email, from_name = self._parse_email_address(from_header)
            
            to_emails = self._parse_email_list(headers.get("to", ""))
            cc_emails = self._parse_email_list(headers.get("cc", ""))
            
            # Determine direction
            direction = "outbound" if mailbox_email.lower() == from_email.lower() else "inbound"
            
            # Parse timestamp
            internal_date = msg.get("internalDate")
            if internal_date:
                timestamp = datetime.fromtimestamp(int(internal_date) / 1000)
            else:
                timestamp = datetime.utcnow()
            
            # Check for attachments
            payload = msg.get("payload", {})
            has_attachments = False
            attachment_count = 0
            
            def count_attachments(parts):
                nonlocal has_attachments, attachment_count
                for part in parts:
                    if part.get("filename"):
                        has_attachments = True
                        attachment_count += 1
                    if part.get("parts"):
                        count_attachments(part["parts"])
            
            if payload.get("parts"):
                count_attachments(payload["parts"])
            
            labels = msg.get("labelIds", [])
            
            return EmailMetadata(
                gmail_message_id=msg["id"],
                gmail_thread_id=msg.get("threadId", msg["id"]),
                mailbox_id=mailbox_id,
                from_email=from_email,
                from_name=from_name,
                to_emails=to_emails,
                cc_emails=cc_emails,
                subject=headers.get("subject", "(No Subject)"),
                snippet=msg.get("snippet", ""),
                timestamp=timestamp,
                labels=labels,
                direction=direction,
                has_attachments=has_attachments,
                attachment_count=attachment_count,
                is_read="UNREAD" not in labels,
                is_starred="STARRED" in labels,
                history_id=msg.get("historyId")
            )
        except Exception as e:
            logger.error(f"Error parsing message {msg.get('id')}: {e}")
            return None
    
    def _parse_email_address(self, header: str) -> Tuple[str, Optional[str]]:
        """Parse email address from header like 'Name <email@domain.com>'"""
        import re
        match = re.match(r'^(?:"?([^"<]*)"?\s*)?<?([^>]+@[^>]+)>?$', header.strip())
        if match:
            name = match.group(1).strip() if match.group(1) else None
            email = match.group(2).strip()
            return email, name
        return header.strip(), None
    
    def _parse_email_list(self, header: str) -> List[str]:
        """Parse comma-separated email addresses"""
        if not header:
            return []
        emails = []
        for addr in header.split(","):
            email, _ = self._parse_email_address(addr)
            if email:
                emails.append(email)
        return emails
    
    def _upsert_email(self, metadata: EmailMetadata) -> bool:
        """
        Upsert email metadata.
        
        Returns:
            True if new email, False if updated
        """
        doc = {
            "gmail_message_id": metadata.gmail_message_id,
            "gmail_thread_id": metadata.gmail_thread_id,
            "mailbox_id": metadata.mailbox_id,
            "from_email": metadata.from_email,
            "from_name": metadata.from_name,
            "to_emails": metadata.to_emails,
            "cc_emails": metadata.cc_emails,
            "subject": metadata.subject,
            "snippet": metadata.snippet,
            "timestamp": metadata.timestamp,
            "labels": metadata.labels,
            "direction": metadata.direction,
            "has_attachments": metadata.has_attachments,
            "attachment_count": metadata.attachment_count,
            "is_read": metadata.is_read,
            "is_starred": metadata.is_starred,
            "history_id": metadata.history_id,
            "synced_at": metadata.synced_at
        }
        
        result = self.emails.update_one(
            {
                "mailbox_id": metadata.mailbox_id,
                "gmail_message_id": metadata.gmail_message_id
            },
            {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True
        )
        
        return result.upserted_id is not None
    
    # =========================================================================
    # EMAIL RETRIEVAL
    # =========================================================================
    
    def get_emails(
        self,
        mailbox_id: Optional[str] = None,
        direction: Optional[str] = None,
        category: Optional[str] = None,
        department: Optional[str] = None,
        search: Optional[str] = None,
        is_read: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[Dict], int]:
        """
        Get email metadata with filters.
        
        Returns:
            Tuple of (emails, total_count)
        """
        query = {}
        
        if mailbox_id:
            query["mailbox_id"] = mailbox_id
        if direction:
            query["direction"] = direction
        if category:
            query["ai_category"] = category
        if department:
            query["ai_department"] = department
        if is_read is not None:
            query["is_read"] = is_read
        if start_date:
            query["timestamp"] = {"$gte": start_date}
        if end_date:
            query.setdefault("timestamp", {})["$lte"] = end_date
        
        if search:
            query["$or"] = [
                {"subject": {"$regex": search, "$options": "i"}},
                {"from_email": {"$regex": search, "$options": "i"}},
                {"from_name": {"$regex": search, "$options": "i"}},
                {"snippet": {"$regex": search, "$options": "i"}}
            ]
        
        total = self.emails.count_documents(query)
        emails = list(
            self.emails.find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(limit)
        )
        
        # Convert ObjectId to string
        for email in emails:
            email["_id"] = str(email["_id"])
        
        return emails, total
    
    def get_email_by_id(self, email_id: str) -> Optional[Dict]:
        """Get email metadata by ID"""
        email = self.emails.find_one({"_id": ObjectId(email_id)})
        if email:
            email["_id"] = str(email["_id"])
        return email
    
    def get_email_content(self, mailbox_id: str, gmail_message_id: str) -> Optional[Dict]:
        """
        Fetch full email content from Gmail API on-demand.
        
        Returns:
            Full email with body content
        """
        mailbox = self.get_mailbox(mailbox_id)
        if not mailbox:
            return None
        
        try:
            service = self._get_service(mailbox)
            
            msg = service.users().messages().get(
                userId="me",
                id=gmail_message_id,
                format="full"
            ).execute()
            
            # Parse body
            body_plain, body_html = self._extract_body(msg.get("payload", {}))
            
            # Parse attachments
            attachments = self._extract_attachment_info(msg.get("payload", {}))
            
            return {
                "gmail_message_id": msg["id"],
                "gmail_thread_id": msg.get("threadId"),
                "body_plain": body_plain,
                "body_html": body_html,
                "attachments": attachments
            }
            
        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise
    
    def _extract_body(self, payload: Dict) -> Tuple[str, str]:
        """Extract plain text and HTML body from message payload"""
        body_plain = ""
        body_html = ""
        
        def extract_from_parts(parts):
            nonlocal body_plain, body_html
            for part in parts:
                mime_type = part.get("mimeType", "")
                body_data = part.get("body", {}).get("data")
                
                if body_data:
                    decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
                    if mime_type == "text/plain" and not body_plain:
                        body_plain = decoded
                    elif mime_type == "text/html" and not body_html:
                        body_html = decoded
                
                if part.get("parts"):
                    extract_from_parts(part["parts"])
        
        # Check if body is directly in payload
        if payload.get("body", {}).get("data"):
            decoded = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
            if payload.get("mimeType") == "text/html":
                body_html = decoded
            else:
                body_plain = decoded
        
        # Check parts
        if payload.get("parts"):
            extract_from_parts(payload["parts"])
        
        return body_plain, body_html
    
    def _extract_attachment_info(self, payload: Dict) -> List[Dict]:
        """Extract attachment information from message payload"""
        attachments = []
        
        def extract_from_parts(parts):
            for part in parts:
                if part.get("filename"):
                    attachments.append({
                        "filename": part["filename"],
                        "mime_type": part.get("mimeType", "application/octet-stream"),
                        "size": part.get("body", {}).get("size", 0),
                        "attachment_id": part.get("body", {}).get("attachmentId")
                    })
                if part.get("parts"):
                    extract_from_parts(part["parts"])
        
        if payload.get("parts"):
            extract_from_parts(payload["parts"])
        
        return attachments
    
    def download_attachment(
        self,
        mailbox_id: str,
        gmail_message_id: str,
        attachment_id: str
    ) -> Optional[bytes]:
        """Download attachment content"""
        mailbox = self.get_mailbox(mailbox_id)
        if not mailbox:
            return None
        
        try:
            service = self._get_service(mailbox)
            
            attachment = service.users().messages().attachments().get(
                userId="me",
                messageId=gmail_message_id,
                id=attachment_id
            ).execute()
            
            data = attachment.get("data")
            if data:
                return base64.urlsafe_b64decode(data)
            return None
            
        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise
    
    # =========================================================================
    # SEND EMAIL
    # =========================================================================
    
    def send_email(
        self,
        mailbox_id: str,
        to: List[str],
        subject: str,
        body_html: str,
        body_plain: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        reply_to_message_id: Optional[str] = None,
        thread_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Send email via Gmail API.
        
        Returns:
            Sent message ID or None on failure
        """
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        mailbox = self.get_mailbox(mailbox_id)
        if not mailbox:
            return None
        
        try:
            service = self._get_service(mailbox)
            
            # Create message
            msg = MIMEMultipart("alternative")
            msg["To"] = ", ".join(to)
            msg["From"] = mailbox["email"]
            msg["Subject"] = subject
            
            if cc:
                msg["Cc"] = ", ".join(cc)
            
            # Add reply headers if this is a reply
            if reply_to_message_id:
                msg["In-Reply-To"] = reply_to_message_id
                msg["References"] = reply_to_message_id
            
            # Add body parts
            if body_plain:
                msg.attach(MIMEText(body_plain, "plain"))
            msg.attach(MIMEText(body_html, "html"))
            
            # Encode
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            
            # Send
            body = {"raw": raw}
            if thread_id:
                body["threadId"] = thread_id
            
            result = service.users().messages().send(
                userId="me",
                body=body
            ).execute()
            
            return result.get("id")
            
        except HttpError as e:
            logger.error(f"Error sending email: {e}")
            return None
    
    # =========================================================================
    # THREAD OPERATIONS
    # =========================================================================
    
    def get_thread(self, mailbox_id: str, thread_id: str) -> List[Dict]:
        """Get all emails in a thread"""
        emails, _ = self.get_emails(mailbox_id=mailbox_id)
        return [e for e in emails if e.get("gmail_thread_id") == thread_id]
    
    def get_thread_content(self, mailbox_id: str, thread_id: str) -> List[Dict]:
        """Get full content for all emails in a thread"""
        mailbox = self.get_mailbox(mailbox_id)
        if not mailbox:
            return []
        
        try:
            service = self._get_service(mailbox)
            
            thread = service.users().threads().get(
                userId="me",
                id=thread_id,
                format="full"
            ).execute()
            
            messages = []
            for msg in thread.get("messages", []):
                headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
                body_plain, body_html = self._extract_body(msg.get("payload", {}))
                
                messages.append({
                    "gmail_message_id": msg["id"],
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "subject": headers.get("subject", ""),
                    "timestamp": datetime.fromtimestamp(int(msg["internalDate"]) / 1000),
                    "body_plain": body_plain,
                    "body_html": body_html,
                    "snippet": msg.get("snippet", "")
                })
            
            return messages
            
        except HttpError:
            return []
    
    # =========================================================================
    # STATISTICS
    # =========================================================================
    
    def get_stats(self, mailbox_id: Optional[str] = None) -> Dict:
        """Get email statistics"""
        query = {"mailbox_id": mailbox_id} if mailbox_id else {}
        
        total = self.emails.count_documents(query)
        
        # Count by category
        pipeline = [
            {"$match": query},
            {"$group": {"_id": "$ai_category", "count": {"$sum": 1}}}
        ]
        categories = {r["_id"]: r["count"] for r in self.emails.aggregate(pipeline) if r["_id"]}
        
        # Count by department
        pipeline = [
            {"$match": query},
            {"$group": {"_id": "$ai_department", "count": {"$sum": 1}}}
        ]
        departments = {r["_id"]: r["count"] for r in self.emails.aggregate(pipeline) if r["_id"]}
        
        # Unread count
        unread = self.emails.count_documents({**query, "is_read": False})
        
        # Pending classification
        unclassified = self.emails.count_documents({**query, "ai_category": None})
        
        # Today's emails
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = self.emails.count_documents({**query, "timestamp": {"$gte": today_start}})
        
        return {
            "total": total,
            "unread": unread,
            "unclassified": unclassified,
            "today": today_count,
            "by_category": categories,
            "by_department": departments
        }
    
    # =========================================================================
    # AI CLASSIFICATION UPDATE
    # =========================================================================
    
    def update_email_classification(
        self,
        email_id: str,
        category: str,
        confidence: float,
        summary: Optional[str] = None,
        ai_status: str = "success",
    ):
        """Update email with AI classification results"""
        self.emails.update_one(
            {"_id": ObjectId(email_id)},
            {
                "$set": {
                    "ai_category": category,
                    "ai_confidence": confidence,
                    "ai_summary": summary,
                    "ai_status": ai_status,
                }
            }
        )
    
    def get_unclassified_emails(self, limit: int = 100) -> List[Dict]:
        """Get emails pending AI classification"""
        emails = list(
            self.emails.find({"ai_category": None})
            .sort("timestamp", -1)
            .limit(limit)
        )
        
        for email in emails:
            email["_id"] = str(email["_id"])
        
        return emails
