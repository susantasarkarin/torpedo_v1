"""
IMAP SYNC IMPLEMENTATION
========================

IMAP UID-based sync implementation for email providers.

Key Design Decisions:
1. Uses UID for incremental sync (UIDs are unique and ascending)
2. Stores UIDVALIDITY to detect mailbox rebuild
3. Syncs both INBOX and Sent folders
4. Never fetches entire mailbox - only UID > last_synced

IMAP UID Behavior:
- UIDs are unique within a mailbox
- UIDs increase monotonically for new messages
- UIDVALIDITY changes when mailbox is rebuilt
- If UIDVALIDITY changes, must do full resync

Sync Strategy:
1. Check UIDVALIDITY - if changed, reset cursor
2. Search for UID > last_uid_synced
3. Fetch new messages in batches
4. Update cursor after each batch
"""

import email
import imaplib
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Generator, Tuple
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from dataclasses import dataclass

from .models import (
    EmailDocument,
    EmailAddress,
    EmailDirection,
    SyncType,
    ImapSyncCursor,
    ProviderType,
)
from .alias_resolver import extract_email_addresses
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


# Common sent folder names
SENT_FOLDER_NAMES = [
    "[Gmail]/Sent Mail",
    "Sent",
    "Sent Items",
    "Sent Mail",
    "INBOX.Sent",
    "Sent Messages",
]

# Common drafts folder names
DRAFTS_FOLDER_NAMES = [
    "[Gmail]/Drafts",
    "Drafts",
    "Draft",
    "INBOX.Drafts",
]


@dataclass
class ImapMessage:
    """Parsed IMAP message"""
    uid: int
    message_id: str
    thread_id: Optional[str]
    folder: str
    from_address: EmailAddress
    to_addresses: List[EmailAddress]
    cc_addresses: List[EmailAddress]
    subject: str
    body_plain: str
    body_html: str
    date: datetime
    delivered_to: Optional[str]
    reply_to: Optional[str]
    in_reply_to: Optional[str]
    references: Optional[str]
    raw_headers: Dict[str, str]
    has_attachments: bool
    attachment_count: int
    attachments: List[Dict[str, Any]]


class ImapSyncer:
    """
    IMAP sync implementation using UID-based tracking.
    
    Usage:
        syncer = ImapSyncer(db, mailbox_id, email, password, server)
        
        # Historical backfill
        for batch in syncer.backfill():
            save_emails(batch)
        
        # Incremental sync
        for batch in syncer.incremental_sync(cursor):
            save_emails(batch)
    """
    
    # Batch sizes
    FETCH_BATCH_SIZE = 50
    
    # Connection timeout
    SOCKET_TIMEOUT = 30
    
    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    
    def __init__(
        self,
        db,
        mailbox_id: str,
        mailbox_email: str,
        password: str,
        imap_server: str,
        imap_port: int = 993,
        use_ssl: bool = True,
        rate_limiter: Optional[RateLimiter] = None
    ):
        """
        Initialize IMAP syncer.
        
        Args:
            db: MongoDB database instance
            mailbox_id: Mailbox ObjectId string
            mailbox_email: Mailbox email address
            password: IMAP password (app password for Gmail)
            imap_server: IMAP server hostname
            imap_port: IMAP server port
            use_ssl: Whether to use SSL
            rate_limiter: Optional rate limiter
        """
        self.db = db
        self.mailbox_id = mailbox_id
        self.mailbox_email = mailbox_email
        self.password = password
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.use_ssl = use_ssl
        self.rate_limiter = rate_limiter
        self._connection: Optional[imaplib.IMAP4] = None
    
    def _connect(self) -> imaplib.IMAP4:
        """
        Establish IMAP connection.
        
        Returns:
            IMAP connection
        """
        try:
            if self.use_ssl:
                conn = imaplib.IMAP4_SSL(
                    self.imap_server,
                    self.imap_port,
                    timeout=self.SOCKET_TIMEOUT
                )
            else:
                conn = imaplib.IMAP4(
                    self.imap_server,
                    self.imap_port,
                    timeout=self.SOCKET_TIMEOUT
                )
            
            conn.login(self.mailbox_email, self.password)
            logger.info(f"Connected to IMAP server {self.imap_server} for {self.mailbox_email}")
            return conn
            
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP authentication failed: {e}")
            raise
        except Exception as e:
            logger.error(f"IMAP connection failed: {e}")
            raise
    
    def _disconnect(self):
        """Close IMAP connection safely"""
        if self._connection:
            try:
                self._connection.close()
                self._connection.logout()
            except Exception:
                pass
            finally:
                self._connection = None
    
    @property
    def connection(self) -> imaplib.IMAP4:
        """Get or create IMAP connection"""
        if not self._connection:
            self._connection = self._connect()
        return self._connection
    
    def _check_rate_limit(self) -> bool:
        """Check rate limit before making request"""
        if not self.rate_limiter:
            return True
        
        can_proceed, wait_seconds = self.rate_limiter.check_rate_limit(self.mailbox_id)
        
        if not can_proceed:
            if wait_seconds and wait_seconds > 0:
                logger.info(f"Rate limit: waiting {wait_seconds}s")
                time.sleep(min(wait_seconds, 60))
            return False
        
        return True
    
    def _record_request(self):
        """Record API request"""
        if self.rate_limiter:
            self.rate_limiter.record_request(self.mailbox_id)
    
    def _get_available_folders(self) -> List[str]:
        """
        Get list of available IMAP folders.
        
        Returns:
            List of folder names
        """
        try:
            status, folder_list = self.connection.list()
            if status != "OK":
                return []
            
            available_folders = []
            for folder_data in folder_list:
                if isinstance(folder_data, bytes):
                    folder_str = folder_data.decode("utf-8", errors="ignore")
                    # Parse folder name (format: (flags) delimiter "name")
                    parts = folder_str.split('"')
                    if len(parts) >= 2:
                        available_folders.append(parts[-2])
            
            return available_folders
            
        except Exception as e:
            logger.warning(f"Error listing folders: {e}")
            return []
    
    def _find_sent_folder(self) -> Optional[str]:
        """
        Find the sent folder name for this mailbox.
        
        Returns:
            Sent folder name or None
        """
        try:
            available_folders = self._get_available_folders()
            
            # Find matching sent folder
            for sent_name in SENT_FOLDER_NAMES:
                for folder in available_folders:
                    if folder.lower() == sent_name.lower():
                        return folder
            
            return None
            
        except Exception as e:
            logger.warning(f"Error finding sent folder: {e}")
            return None
    
    def _find_drafts_folder(self) -> Optional[str]:
        """
        Find the drafts folder name for this mailbox.
        
        Returns:
            Drafts folder name or None
        """
        try:
            available_folders = self._get_available_folders()
            
            # Find matching drafts folder
            for draft_name in DRAFTS_FOLDER_NAMES:
                for folder in available_folders:
                    if folder.lower() == draft_name.lower():
                        return folder
            
            return None
            
        except Exception as e:
            logger.warning(f"Error finding drafts folder: {e}")
            return None
    
    def _get_uidvalidity(self, folder: str) -> Optional[int]:
        """
        Get UIDVALIDITY for a folder.
        
        Args:
            folder: Folder name
            
        Returns:
            UIDVALIDITY value or None
        """
        try:
            status, data = self.connection.select(folder, readonly=True)
            if status != "OK":
                return None
            
            # UIDVALIDITY is returned in the SELECT response
            status, data = self.connection.response("UIDVALIDITY")
            if status == "OK" and data[0]:
                return int(data[0])
            
            return None
            
        except Exception as e:
            logger.warning(f"Error getting UIDVALIDITY for {folder}: {e}")
            return None
    
    def _decode_header(self, header_value) -> str:
        """Decode email header to string"""
        if header_value is None:
            return ""
        
        decoded_parts = decode_header(header_value)
        result = ""
        for content, charset in decoded_parts:
            if isinstance(content, bytes):
                try:
                    result += content.decode(charset or "utf-8", errors="ignore")
                except Exception:
                    result += content.decode("utf-8", errors="ignore")
            else:
                result += str(content)
        return result
    
    def _get_email_body(self, msg) -> Tuple[str, str]:
        """
        Extract plain text and HTML body from email message.
        
        Args:
            msg: Email message object
            
        Returns:
            Tuple of (body_plain, body_html)
        """
        body_plain = ""
        body_html = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                
                if content_type == "text/plain" and not body_plain:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        body_plain = payload.decode(charset, errors="ignore")
                    except Exception:
                        pass
                        
                elif content_type == "text/html" and not body_html:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        body_html = payload.decode(charset, errors="ignore")
                    except Exception:
                        pass
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                content_type = msg.get_content_type()
                
                if content_type == "text/html":
                    body_html = payload.decode(charset, errors="ignore")
                else:
                    body_plain = payload.decode(charset, errors="ignore")
            except Exception:
                body_plain = str(msg.get_payload())
        
        return body_plain.strip(), body_html.strip()
    
    def _get_attachments(self, msg) -> List[Dict[str, Any]]:
        """
        Extract attachment metadata from message.
        
        Args:
            msg: Email message object
            
        Returns:
            List of attachment metadata dicts
        """
        attachments = []
        
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_disposition() == "attachment":
                    filename = part.get_filename()
                    if filename:
                        payload = part.get_payload(decode=True) or b""
                        # Store attachment data as base64 for download
                        import base64
                        attachments.append({
                            "filename": self._decode_header(filename),
                            "mime_type": part.get_content_type(),
                            "size": len(payload),
                            "data": base64.b64encode(payload).decode('utf-8') if len(payload) < 10 * 1024 * 1024 else None,  # Only store if < 10MB
                        })
        
        return attachments
    
    def _parse_message(
        self,
        uid: int,
        raw_email: bytes,
        folder: str
    ) -> Optional[ImapMessage]:
        """
        Parse raw email into ImapMessage.
        
        Args:
            uid: Message UID
            raw_email: Raw email bytes
            folder: Folder name
            
        Returns:
            Parsed ImapMessage or None
        """
        try:
            msg = email.message_from_bytes(raw_email)
            
            # Parse headers
            message_id = msg.get("Message-ID", f"{self.mailbox_email}_{folder}_{uid}")
            subject = self._decode_header(msg.get("Subject", ""))
            from_header = self._decode_header(msg.get("From", ""))
            to_header = self._decode_header(msg.get("To", ""))
            cc_header = self._decode_header(msg.get("Cc", ""))
            date_str = msg.get("Date", "")
            delivered_to = msg.get("Delivered-To")
            reply_to = msg.get("Reply-To")
            in_reply_to = msg.get("In-Reply-To")
            references = msg.get("References")
            
            # Parse addresses
            from_addresses = extract_email_addresses(from_header)
            from_address = from_addresses[0] if from_addresses else EmailAddress(
                email="unknown@unknown.com"
            )
            
            # Parse body
            body_plain, body_html = self._get_email_body(msg)
            
            # Parse date
            try:
                email_date = parsedate_to_datetime(date_str)
            except Exception:
                email_date = datetime.utcnow()
            
            # Get attachments
            attachments = self._get_attachments(msg)
            
            # Build thread ID from references or in-reply-to
            thread_id = None
            if references:
                thread_id = references.split()[0]
            elif in_reply_to:
                thread_id = in_reply_to
            
            # Extract raw headers
            raw_headers = {}
            for key in msg.keys():
                raw_headers[key.lower()] = self._decode_header(msg.get(key))
            
            return ImapMessage(
                uid=uid,
                message_id=message_id,
                thread_id=thread_id,
                folder=folder,
                from_address=from_address,
                to_addresses=extract_email_addresses(to_header),
                cc_addresses=extract_email_addresses(cc_header),
                subject=subject,
                body_plain=body_plain[:50000],  # Limit body size
                body_html=body_html[:100000],
                date=email_date,
                delivered_to=self._decode_header(delivered_to) if delivered_to else None,
                reply_to=self._decode_header(reply_to) if reply_to else None,
                in_reply_to=in_reply_to,
                references=references,
                raw_headers=raw_headers,
                has_attachments=len(attachments) > 0,
                attachment_count=len(attachments),
                attachments=attachments,
            )
            
        except Exception as e:
            logger.warning(f"Error parsing message UID {uid}: {e}")
            return None
    
    def _message_to_document(
        self,
        msg: ImapMessage,
        sync_type: SyncType,
        alias_id: Optional[str] = None
    ) -> EmailDocument:
        """
        Convert parsed message to EmailDocument.
        
        Args:
            msg: Parsed ImapMessage
            sync_type: Type of sync
            alias_id: Resolved alias ID
            
        Returns:
            EmailDocument
        """
        # Determine direction
        direction = EmailDirection.INBOUND
        is_draft = False
        
        from_email = msg.from_address.email.lower()
        folder_lower = msg.folder.lower()
        
        if "draft" in folder_lower:
            # Drafts are outbound (user is sender)
            direction = EmailDirection.OUTBOUND
            is_draft = True
        elif from_email == self.mailbox_email.lower():
            direction = EmailDirection.OUTBOUND
        elif "sent" in folder_lower:
            direction = EmailDirection.OUTBOUND
        
        # Build labels list
        labels = [msg.folder]
        if is_draft:
            labels.append("DRAFT")
        
        return EmailDocument(
            provider_message_id=msg.message_id,
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
            snippet=msg.body_plain[:200] if msg.body_plain else "",
            timestamp=msg.date,
            labels=labels,
            has_attachments=msg.has_attachments,
            attachment_count=msg.attachment_count,
            attachments=msg.attachments,
            raw_headers=msg.raw_headers,
            sync_source=sync_type,
            synced_at=datetime.utcnow(),
            processed=False,
        )
    
    def _fetch_uids(self, folder: str, since_uid: int = 0) -> List[int]:
        """
        Fetch UIDs greater than since_uid.
        
        Args:
            folder: Folder name
            since_uid: Minimum UID (exclusive)
            
        Returns:
            List of UIDs
        """
        try:
            status, _ = self.connection.select(folder, readonly=True)
            if status != "OK":
                logger.warning(f"Could not select folder {folder}")
                return []
            
            self._record_request()
            
            # Search for UIDs greater than since_uid
            if since_uid > 0:
                search_criteria = f"UID {since_uid + 1}:*"
                status, data = self.connection.uid("search", None, search_criteria)
            else:
                status, data = self.connection.uid("search", None, "ALL")
            
            if status != "OK":
                return []
            
            uid_str = data[0].decode() if data[0] else ""
            if not uid_str:
                return []
            
            uids = [int(u) for u in uid_str.split()]
            
            # Filter out UIDs <= since_uid (edge case)
            uids = [u for u in uids if u > since_uid]
            
            return sorted(uids)
            
        except Exception as e:
            logger.warning(f"Error fetching UIDs from {folder}: {e}")
            return []
    
    def _fetch_messages(
        self,
        folder: str,
        uids: List[int]
    ) -> List[ImapMessage]:
        """
        Fetch messages by UID.
        
        Args:
            folder: Folder name
            uids: List of UIDs to fetch
            
        Returns:
            List of parsed messages
        """
        messages = []
        
        try:
            status, _ = self.connection.select(folder, readonly=True)
            if status != "OK":
                return messages
            
            for uid in uids:
                if not self._check_rate_limit():
                    continue
                
                try:
                    self._record_request()
                    status, data = self.connection.uid("fetch", str(uid), "(RFC822)")
                    
                    if status != "OK" or not data or not data[0]:
                        continue
                    
                    raw_email = data[0][1]
                    if isinstance(raw_email, bytes):
                        msg = self._parse_message(uid, raw_email, folder)
                        if msg:
                            messages.append(msg)
                            
                except Exception as e:
                    logger.warning(f"Error fetching UID {uid}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error in fetch_messages: {e}")
        
        return messages
    
    def backfill(
        self,
        cursor: Optional[ImapSyncCursor] = None,
        max_messages: Optional[int] = None,
        days_limit: Optional[int] = None
    ) -> Generator[Tuple[List[EmailDocument], ImapSyncCursor], None, None]:
        """
        Historical backfill for IMAP.
        
        Args:
            cursor: Resume cursor
            max_messages: Maximum messages to sync
            days_limit: Limit to last N days
            
        Yields:
            Tuple of (documents, updated_cursor)
        """
        cursor = cursor or ImapSyncCursor()
        total_synced = cursor.messages_synced
        
        try:
            # Find sent and drafts folders
            sent_folder = self._find_sent_folder()
            drafts_folder = self._find_drafts_folder()
            
            # Build list of folders to sync
            folders = [("INBOX", "inbox")]
            if sent_folder:
                folders.append((sent_folder, "sent"))
            if drafts_folder:
                folders.append((drafts_folder, "drafts"))
            
            for folder, cursor_key in folders:
                if not folder:
                    continue
                
                logger.info(f"Starting IMAP backfill for {folder}")
                
                # Check UIDVALIDITY
                current_uidvalidity = self._get_uidvalidity(folder)
                stored_uidvalidity = getattr(cursor, f"{cursor_key}_uidvalidity", None)
                
                if stored_uidvalidity and current_uidvalidity != stored_uidvalidity:
                    logger.warning(f"UIDVALIDITY changed for {folder}, resetting cursor")
                    if cursor_key == "inbox":
                        cursor.inbox_last_uid = 0
                        cursor.inbox_uidvalidity = current_uidvalidity
                    elif cursor_key == "sent":
                        cursor.sent_last_uid = 0
                        cursor.sent_uidvalidity = current_uidvalidity
                    elif cursor_key == "drafts":
                        cursor.drafts_last_uid = 0
                        cursor.drafts_uidvalidity = current_uidvalidity
                
                # Get last synced UID
                last_uid = getattr(cursor, f"{cursor_key}_last_uid", 0)
                
                # Fetch all UIDs
                uids = self._fetch_uids(folder, since_uid=0)  # Full backfill
                
                if not uids:
                    continue
                
                logger.info(f"Found {len(uids)} messages in {folder}")
                
                # Fetch in batches
                for i in range(0, len(uids), self.FETCH_BATCH_SIZE):
                    batch_uids = uids[i:i + self.FETCH_BATCH_SIZE]
                    messages = self._fetch_messages(folder, batch_uids)
                    
                    if not messages:
                        continue
                    
                    # Convert to documents
                    documents = [
                        self._message_to_document(msg, SyncType.BACKFILL)
                        for msg in messages
                    ]
                    
                    total_synced += len(documents)
                    
                    # Update cursor
                    max_uid = max(m.uid for m in messages)
                    if cursor_key == "inbox":
                        cursor.inbox_last_uid = max_uid
                        cursor.inbox_uidvalidity = current_uidvalidity
                    elif cursor_key == "sent":
                        cursor.sent_last_uid = max_uid
                        cursor.sent_uidvalidity = current_uidvalidity
                    elif cursor_key == "drafts":
                        cursor.drafts_last_uid = max_uid
                        cursor.drafts_uidvalidity = current_uidvalidity
                    
                    cursor.messages_synced = total_synced
                    
                    yield documents, cursor
                    
                    # Check max messages
                    if max_messages and total_synced >= max_messages:
                        return
            
            logger.info(f"IMAP backfill complete: {total_synced} messages")
            
        finally:
            self._disconnect()
    
    def incremental_sync(
        self,
        cursor: ImapSyncCursor
    ) -> Generator[Tuple[List[EmailDocument], ImapSyncCursor], None, None]:
        """
        Incremental sync using UID comparison.
        
        Args:
            cursor: Cursor with last synced UIDs
            
        Yields:
            Tuple of (documents, updated_cursor)
        """
        total_synced = cursor.messages_synced
        
        try:
            # Find sent and drafts folders
            sent_folder = self._find_sent_folder()
            drafts_folder = self._find_drafts_folder()
            
            # Build list of folders to sync
            folders = [
                ("INBOX", "inbox", cursor.inbox_last_uid, cursor.inbox_uidvalidity),
            ]
            if sent_folder:
                folders.append(
                    (sent_folder, "sent", cursor.sent_last_uid, cursor.sent_uidvalidity)
                )
            if drafts_folder:
                folders.append(
                    (drafts_folder, "drafts", cursor.drafts_last_uid, cursor.drafts_uidvalidity)
                )
            
            for folder, cursor_key, last_uid, stored_uidvalidity in folders:
                if not folder:
                    continue
                
                logger.info(f"Incremental sync for {folder} (last UID: {last_uid})")
                
                # Check UIDVALIDITY
                current_uidvalidity = self._get_uidvalidity(folder)
                
                if stored_uidvalidity and current_uidvalidity != stored_uidvalidity:
                    logger.warning(f"UIDVALIDITY changed for {folder}, need full resync")
                    # Should trigger a partial resync
                    continue
                
                # Fetch UIDs greater than last
                uids = self._fetch_uids(folder, since_uid=last_uid)
                
                if not uids:
                    logger.info(f"No new messages in {folder}")
                    continue
                
                logger.info(f"Found {len(uids)} new messages in {folder}")
                
                # Fetch messages
                messages = self._fetch_messages(folder, uids)
                
                if not messages:
                    continue
                
                # Convert to documents
                documents = [
                    self._message_to_document(msg, SyncType.INCREMENTAL)
                    for msg in messages
                ]
                
                total_synced += len(documents)
                
                # Update cursor
                max_uid = max(m.uid for m in messages)
                if cursor_key == "inbox":
                    cursor.inbox_last_uid = max_uid
                    cursor.inbox_uidvalidity = current_uidvalidity
                elif cursor_key == "sent":
                    cursor.sent_last_uid = max_uid
                    cursor.sent_uidvalidity = current_uidvalidity
                elif cursor_key == "drafts":
                    cursor.drafts_last_uid = max_uid
                    cursor.drafts_uidvalidity = current_uidvalidity
                
                cursor.messages_synced = total_synced
                
                yield documents, cursor
            
            logger.info("IMAP incremental sync complete")
            
        finally:
            self._disconnect()
