"""
GMAIL SYNC IMPLEMENTATION
=========================

Gmail API sync implementation using:
- messages.list for historical backfill (paginated)
- History API for incremental sync

Key Design Decisions:
1. Backfill uses messages.list with pagination
2. After backfill, persist historyId
3. Incremental sync uses history.list with startHistoryId
4. If historyId invalid, fall back to partial resync (last 7-14 days)
5. All operations are idempotent via (mailbox_id, provider_message_id) unique constraint

Gmail API Quotas:
- messages.list: 5 quota units/call (100 results/page)
- messages.get: 5 quota units/call
- history.list: 2 quota units/call
- Per-user quota: 250 units/second

Backfill Strategy:
1. List all message IDs first (minimal quota)
2. Fetch message details in batches
3. Store historyId from most recent message
"""

import os
import time
import base64
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Generator, Tuple
from email.utils import parsedate_to_datetime
from dataclasses import dataclass

from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from .models import (
    EmailDocument,
    EmailAddress,
    EmailDirection,
    SyncType,
    GmailSyncCursor,
    ProviderType,
)
from .alias_resolver import extract_email_addresses, determine_direction
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


# Gmail label constants
GMAIL_INBOX = "INBOX"
GMAIL_SENT = "SENT"


@dataclass
class GmailMessage:
    """Parsed Gmail message"""
    id: str
    thread_id: str
    history_id: str
    internal_date: int
    labels: List[str]
    from_address: EmailAddress
    to_addresses: List[EmailAddress]
    cc_addresses: List[EmailAddress]
    subject: str
    body_plain: str
    body_html: str
    snippet: str
    delivered_to: Optional[str]
    reply_to: Optional[str]
    raw_headers: Dict[str, str]
    has_attachments: bool
    attachment_count: int
    attachments: List[Dict[str, Any]]


class GmailSyncer:
    """
    Gmail sync implementation.
    
    Usage:
        syncer = GmailSyncer(db, mailbox_id, credentials)
        
        # Historical backfill
        for batch in syncer.backfill():
            # Process batch
            save_emails(batch)
        
        # Incremental sync
        for batch in syncer.incremental_sync(cursor):
            # Process batch
            save_emails(batch)
    """
    
    # Batch sizes for API calls
    LIST_PAGE_SIZE = 100  # Max 100 per page
    GET_BATCH_SIZE = 50   # Messages to get per batch
    HISTORY_PAGE_SIZE = 100
    
    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    
    def __init__(
        self,
        db,
        mailbox_id: str,
        mailbox_email: str,
        credentials: Credentials,
        rate_limiter: Optional[RateLimiter] = None,
        user_id: str = "me"
    ):
        """
        Initialize Gmail syncer.
        
        Args:
            db: MongoDB database instance
            mailbox_id: Mailbox ObjectId string
            mailbox_email: Mailbox email address
            credentials: Google OAuth credentials
            rate_limiter: Optional rate limiter
            user_id: Gmail user ID (default "me")
        """
        self.db = db
        self.mailbox_id = mailbox_id
        self.mailbox_email = mailbox_email
        self.credentials = credentials
        self.rate_limiter = rate_limiter
        self.user_id = user_id
        self._service: Optional[Resource] = None
    
    @property
    def service(self) -> Resource:
        """Get or create Gmail API service"""
        if not self._service:
            # Refresh credentials if needed
            if self.credentials.expired and self.credentials.refresh_token:
                self.credentials.refresh(Request())
            
            self._service = build("gmail", "v1", credentials=self.credentials)
        
        return self._service
    
    def _check_rate_limit(self) -> bool:
        """
        Check if we can make a request.
        Returns True if allowed, raises if should pause.
        """
        if not self.rate_limiter:
            return True
        
        can_proceed, wait_seconds = self.rate_limiter.check_rate_limit(self.mailbox_id)
        
        if not can_proceed:
            if wait_seconds and wait_seconds > 0:
                logger.info(f"Rate limit: waiting {wait_seconds}s for mailbox {self.mailbox_id}")
                time.sleep(min(wait_seconds, 60))  # Cap at 60s
            return False
        
        return True
    
    def _record_request(self):
        """Record that a request was made"""
        if self.rate_limiter:
            self.rate_limiter.record_request(self.mailbox_id)
    
    def _handle_rate_limit_error(self, error: HttpError):
        """Handle 429 rate limit error"""
        if self.rate_limiter:
            backoff = self.rate_limiter.record_rate_limit_hit(self.mailbox_id)
            time.sleep(backoff)
    
    def _api_call_with_retry(self, request, description: str = "API call"):
        """
        Execute API call with retry logic.
        
        Args:
            request: API request to execute
            description: Description for logging
            
        Returns:
            API response
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                # Check rate limit
                if not self._check_rate_limit():
                    continue
                
                # Execute request
                response = request.execute()
                self._record_request()
                
                # Clear backoff on success
                if self.rate_limiter:
                    self.rate_limiter.clear_backoff(self.mailbox_id)
                
                return response
                
            except HttpError as e:
                if e.resp.status == 429:
                    logger.warning(f"Rate limit hit on {description}")
                    self._handle_rate_limit_error(e)
                elif e.resp.status == 401:
                    logger.error(f"Authentication error on {description}")
                    raise
                elif e.resp.status >= 500:
                    logger.warning(f"Server error on {description}: {e}")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"API error on {description}: {e}")
                    raise
                    
            except Exception as e:
                logger.error(f"Unexpected error on {description}: {e}")
                if attempt == self.MAX_RETRIES - 1:
                    raise
                time.sleep(self.RETRY_DELAY)
        
        raise Exception(f"Max retries exceeded for {description}")
    
    def _parse_message(self, msg_data: Dict[str, Any]) -> GmailMessage:
        """
        Parse Gmail API message response.
        
        Args:
            msg_data: Raw message data from API
            
        Returns:
            Parsed GmailMessage
        """
        headers = {}
        payload = msg_data.get("payload", {})
        
        # Parse headers
        for header in payload.get("headers", []):
            name = header.get("name", "").lower()
            value = header.get("value", "")
            headers[name] = value
        
        # Extract addresses
        from_header = headers.get("from", "")
        to_header = headers.get("to", "")
        cc_header = headers.get("cc", "")
        
        from_addresses = extract_email_addresses(from_header)
        from_address = from_addresses[0] if from_addresses else EmailAddress(email="unknown@unknown.com")
        
        # Parse body
        body_plain = ""
        body_html = ""
        attachments = []
        
        def extract_parts(part):
            nonlocal body_plain, body_html, attachments
            
            mime_type = part.get("mimeType", "")
            body = part.get("body", {})
            
            if mime_type == "text/plain" and not body_plain:
                data = body.get("data", "")
                if data:
                    body_plain = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            
            elif mime_type == "text/html" and not body_html:
                data = body.get("data", "")
                if data:
                    body_html = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            
            elif body.get("attachmentId"):
                attachments.append({
                    "filename": part.get("filename", "attachment"),
                    "mime_type": mime_type,
                    "size": body.get("size", 0),
                    "attachment_id": body.get("attachmentId"),
                })
            
            # Recursively process parts
            for subpart in part.get("parts", []):
                extract_parts(subpart)
        
        extract_parts(payload)
        
        return GmailMessage(
            id=msg_data["id"],
            thread_id=msg_data.get("threadId", msg_data["id"]),
            history_id=msg_data.get("historyId", ""),
            internal_date=int(msg_data.get("internalDate", 0)),
            labels=msg_data.get("labelIds", []),
            from_address=from_address,
            to_addresses=extract_email_addresses(to_header),
            cc_addresses=extract_email_addresses(cc_header),
            subject=headers.get("subject", ""),
            body_plain=body_plain,
            body_html=body_html,
            snippet=msg_data.get("snippet", ""),
            delivered_to=headers.get("delivered-to"),
            reply_to=headers.get("reply-to"),
            raw_headers={k: v for k, v in headers.items()},
            has_attachments=len(attachments) > 0,
            attachment_count=len(attachments),
            attachments=attachments,
        )
    
    def _message_to_document(
        self,
        msg: GmailMessage,
        sync_type: SyncType,
        alias_id: Optional[str] = None
    ) -> EmailDocument:
        """
        Convert parsed message to EmailDocument.
        
        Args:
            msg: Parsed GmailMessage
            sync_type: Type of sync (backfill/incremental)
            alias_id: Resolved alias ID
            
        Returns:
            EmailDocument ready for storage
        """
        # Determine direction
        direction = EmailDirection.INBOUND
        
        # Check if sent from this mailbox
        from_email = msg.from_address.email.lower()
        if from_email == self.mailbox_email.lower():
            direction = EmailDirection.OUTBOUND
        elif GMAIL_SENT in msg.labels:
            direction = EmailDirection.OUTBOUND
        
        # Parse timestamp
        timestamp = datetime.utcnow()
        if msg.internal_date:
            timestamp = datetime.utcfromtimestamp(msg.internal_date / 1000)
        
        return EmailDocument(
            provider_message_id=msg.id,
            provider_thread_id=msg.thread_id,
            mailbox_id=self.mailbox_id,
            alias_id=alias_id,
            direction=direction,
            from_address=msg.from_address,
            to_addresses=msg.to_addresses,
            cc_addresses=msg.cc_addresses,
            reply_to=msg.reply_to,
            delivered_to=msg.delivered_to,
            subject=msg.subject,
            body_plain=msg.body_plain,
            body_html=msg.body_html,
            snippet=msg.snippet[:200] if msg.snippet else "",
            timestamp=timestamp,
            internal_date=msg.internal_date,
            labels=msg.labels,
            has_attachments=msg.has_attachments,
            attachment_count=msg.attachment_count,
            attachments=msg.attachments,
            raw_headers=msg.raw_headers,
            sync_source=sync_type,
            synced_at=datetime.utcnow(),
            processed=False,
        )
    
    def get_profile(self) -> Dict[str, Any]:
        """
        Get Gmail profile info including current historyId.
        
        Returns:
            Profile dict with historyId
        """
        request = self.service.users().getProfile(userId=self.user_id)
        return self._api_call_with_retry(request, "getProfile")
    
    def list_message_ids(
        self,
        label_ids: Optional[List[str]] = None,
        query: Optional[str] = None,
        page_token: Optional[str] = None,
        max_results: Optional[int] = None
    ) -> Tuple[List[str], Optional[str], int]:
        """
        List message IDs (minimal API usage).
        
        Args:
            label_ids: Filter by labels
            query: Gmail search query
            page_token: Pagination token
            max_results: Maximum results (uses all available if None)
            
        Returns:
            Tuple of (message_ids, next_page_token, result_size_estimate)
        """
        params = {
            "userId": self.user_id,
            "maxResults": self.LIST_PAGE_SIZE,
        }
        
        if label_ids:
            params["labelIds"] = label_ids
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        
        request = self.service.users().messages().list(**params)
        response = self._api_call_with_retry(request, "messages.list")
        
        messages = response.get("messages", [])
        message_ids = [m["id"] for m in messages]
        next_token = response.get("nextPageToken")
        estimate = response.get("resultSizeEstimate", len(messages))
        
        return message_ids, next_token, estimate
    
    def get_message(self, message_id: str, format: str = "full") -> Optional[GmailMessage]:
        """
        Get a single message.
        
        Args:
            message_id: Message ID
            format: Message format (full, metadata, minimal)
            
        Returns:
            Parsed message or None
        """
        try:
            request = self.service.users().messages().get(
                userId=self.user_id,
                id=message_id,
                format=format
            )
            response = self._api_call_with_retry(request, f"messages.get({message_id})")
            return self._parse_message(response)
        except Exception as e:
            logger.warning(f"Failed to get message {message_id}: {e}")
            return None
    
    def get_messages_batch(
        self, 
        message_ids: List[str],
        progress_callback: Optional[callable] = None
    ) -> List[GmailMessage]:
        """
        Get multiple messages efficiently using Gmail BatchHttpRequest.
        
        This fetches 10-20 emails in parallel per batch request, significantly
        faster than sequential fetching while respecting Gmail API limits.
        
        Args:
            message_ids: List of message IDs
            progress_callback: Optional callback(current_id, subject, index, total)
            
        Returns:
            List of parsed messages
        """
        from googleapiclient.http import BatchHttpRequest
        
        messages = []
        errors = []
        total = len(message_ids)
        
        # Process in chunks of 20 (Gmail batch limit is 100, but 20 is safer)
        BATCH_CHUNK_SIZE = 20
        
        for chunk_start in range(0, len(message_ids), BATCH_CHUNK_SIZE):
            chunk_ids = message_ids[chunk_start:chunk_start + BATCH_CHUNK_SIZE]
            chunk_messages = []
            chunk_index = chunk_start
            
            def create_callback(msg_id, idx):
                """Create a callback for this specific message"""
                def callback(request_id, response, exception):
                    nonlocal chunk_messages, errors, chunk_index
                    if exception:
                        logger.warning(f"Batch request failed for {msg_id}: {exception}")
                        errors.append({"id": msg_id, "error": str(exception)})
                    else:
                        try:
                            parsed = self._parse_message(response)
                            chunk_messages.append(parsed)
                            
                            # Call progress callback if provided
                            if progress_callback:
                                try:
                                    progress_callback(
                                        msg_id, 
                                        parsed.subject[:50] if parsed.subject else "",
                                        chunk_index + idx,
                                        total
                                    )
                                except Exception as cb_err:
                                    logger.debug(f"Progress callback error: {cb_err}")
                                    
                        except Exception as parse_err:
                            logger.warning(f"Failed to parse message {msg_id}: {parse_err}")
                            errors.append({"id": msg_id, "error": str(parse_err)})
                return callback
            
            # Check rate limit before batch
            if not self._check_rate_limit():
                time.sleep(1)
                continue
            
            # Create batch request
            batch = self.service.new_batch_http_request()
            
            for idx, msg_id in enumerate(chunk_ids):
                request = self.service.users().messages().get(
                    userId=self.user_id,
                    id=msg_id,
                    format="full"
                )
                batch.add(request, callback=create_callback(msg_id, idx))
            
            # Execute batch with retry
            for attempt in range(self.MAX_RETRIES):
                try:
                    batch.execute()
                    self._record_request()
                    break
                except HttpError as e:
                    if e.resp.status == 429:
                        logger.warning("Rate limit hit on batch request")
                        self._handle_rate_limit_error(e)
                    elif attempt == self.MAX_RETRIES - 1:
                        logger.error(f"Batch request failed after {self.MAX_RETRIES} attempts: {e}")
                        raise
                    else:
                        time.sleep(self.RETRY_DELAY * (attempt + 1))
                except Exception as e:
                    if attempt == self.MAX_RETRIES - 1:
                        logger.error(f"Batch request failed: {e}")
                        raise
                    time.sleep(self.RETRY_DELAY)
            
            messages.extend(chunk_messages)
            
            # Small delay between batches to avoid overwhelming the API
            if chunk_start + BATCH_CHUNK_SIZE < len(message_ids):
                time.sleep(0.1)
        
        if errors:
            logger.info(f"Batch fetch completed: {len(messages)} success, {len(errors)} errors")
        
        return messages
    
    def backfill(
        self,
        cursor: Optional[GmailSyncCursor] = None,
        max_messages: Optional[int] = None,
        days_limit: Optional[int] = None
    ) -> Generator[Tuple[List[EmailDocument], GmailSyncCursor], None, None]:
        """
        Historical backfill using messages.list.
        
        Yields batches of EmailDocuments with updated cursor.
        Caller should save cursor after each batch for restart safety.
        
        Args:
            cursor: Resume cursor (None for fresh start)
            max_messages: Optional limit on total messages
            days_limit: Optional limit to last N days
            
        Yields:
            Tuple of (documents, updated_cursor)
        """
        cursor = cursor or GmailSyncCursor()
        page_token = cursor.page_token
        total_synced = cursor.messages_synced
        latest_history_id = None
        
        # Build query
        query_parts = []
        if days_limit:
            after_date = (datetime.utcnow() - timedelta(days=days_limit)).strftime("%Y/%m/%d")
            query_parts.append(f"after:{after_date}")
        
        query = " ".join(query_parts) if query_parts else None
        
        logger.info(f"Starting Gmail backfill for mailbox {self.mailbox_id}")
        
        while True:
            # Check if we should pause for rate limits
            if self.rate_limiter and self.rate_limiter.should_pause_backfill(self.mailbox_id):
                logger.info(f"Pausing backfill for mailbox {self.mailbox_id} - rate limit threshold")
                # Yield current progress
                yield [], cursor
                time.sleep(60)  # Wait before checking again
                continue
            
            # List message IDs
            message_ids, next_token, estimate = self.list_message_ids(
                label_ids=[GMAIL_INBOX, GMAIL_SENT],
                query=query,
                page_token=page_token
            )
            
            if not message_ids:
                break
            
            # Fetch message details in batches
            for i in range(0, len(message_ids), self.GET_BATCH_SIZE):
                batch_ids = message_ids[i:i + self.GET_BATCH_SIZE]
                messages = self.get_messages_batch(batch_ids)
                
                if not messages:
                    continue
                
                # Track latest history ID
                for msg in messages:
                    if msg.history_id:
                        if not latest_history_id or msg.history_id > latest_history_id:
                            latest_history_id = msg.history_id
                
                # Convert to documents
                documents = [
                    self._message_to_document(msg, SyncType.BACKFILL)
                    for msg in messages
                ]
                
                total_synced += len(documents)
                
                # Update cursor
                cursor = GmailSyncCursor(
                    history_id=latest_history_id,
                    page_token=next_token,
                    last_message_id=message_ids[-1],
                    messages_synced=total_synced
                )
                
                yield documents, cursor
                
                # Check max messages
                if max_messages and total_synced >= max_messages:
                    logger.info(f"Reached max messages limit ({max_messages})")
                    return
            
            # Move to next page
            if next_token:
                page_token = next_token
            else:
                break
        
        logger.info(f"Backfill complete: {total_synced} messages synced")
    
    def incremental_sync(
        self,
        cursor: GmailSyncCursor
    ) -> Generator[Tuple[List[EmailDocument], GmailSyncCursor], None, None]:
        """
        Incremental sync using History API.
        
        Args:
            cursor: Cursor with historyId from last sync
            
        Yields:
            Tuple of (documents, updated_cursor)
        """
        if not cursor.history_id:
            logger.warning("No historyId in cursor, falling back to partial resync")
            yield from self._partial_resync()
            return
        
        start_history_id = cursor.history_id
        logger.info(f"Starting incremental sync from historyId {start_history_id}")
        
        try:
            # Get current historyId
            profile = self.get_profile()
            current_history_id = profile.get("historyId")
            
            if start_history_id == current_history_id:
                logger.info("No new changes since last sync")
                return
            
            # Fetch history
            page_token = None
            added_message_ids = set()
            
            while True:
                params = {
                    "userId": self.user_id,
                    "startHistoryId": start_history_id,
                    "historyTypes": ["messageAdded"],
                    "maxResults": self.HISTORY_PAGE_SIZE,
                }
                
                if page_token:
                    params["pageToken"] = page_token
                
                request = self.service.users().history().list(**params)
                response = self._api_call_with_retry(request, "history.list")
                
                # Extract added message IDs
                for history_item in response.get("history", []):
                    for msg_added in history_item.get("messagesAdded", []):
                        msg = msg_added.get("message", {})
                        if msg.get("id"):
                            added_message_ids.add(msg["id"])
                
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            
            logger.info(f"Found {len(added_message_ids)} new messages")
            
            # Fetch new messages
            if added_message_ids:
                message_ids = list(added_message_ids)
                
                for i in range(0, len(message_ids), self.GET_BATCH_SIZE):
                    batch_ids = message_ids[i:i + self.GET_BATCH_SIZE]
                    messages = self.get_messages_batch(batch_ids)
                    
                    documents = [
                        self._message_to_document(msg, SyncType.INCREMENTAL)
                        for msg in messages
                    ]
                    
                    # Update cursor
                    updated_cursor = GmailSyncCursor(
                        history_id=current_history_id,
                        messages_synced=cursor.messages_synced + len(documents)
                    )
                    
                    yield documents, updated_cursor
            
            logger.info("Incremental sync complete")
            
        except HttpError as e:
            if e.resp.status == 404 or "historyId" in str(e).lower():
                logger.warning(f"HistoryId {start_history_id} invalid, falling back to partial resync")
                yield from self._partial_resync()
            else:
                raise
    
    def _partial_resync(
        self,
        days: int = 14
    ) -> Generator[Tuple[List[EmailDocument], GmailSyncCursor], None, None]:
        """
        Partial resync when historyId is invalid.
        Fetches last N days of emails.
        
        Args:
            days: Number of days to resync
            
        Yields:
            Tuple of (documents, cursor)
        """
        logger.info(f"Performing partial resync for last {days} days")
        
        # Use backfill with days limit
        yield from self.backfill(days_limit=days)


def create_credentials_from_tokens(
    access_token: str,
    refresh_token: str,
    token_expiry: Optional[datetime] = None
) -> Credentials:
    """
    Create Google credentials from stored tokens.
    
    Args:
        access_token: OAuth access token
        refresh_token: OAuth refresh token
        token_expiry: Token expiration time
        
    Returns:
        Google Credentials object
    """
    from google.oauth2.credentials import Credentials
    
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        expiry=token_expiry
    )
    
    return creds
