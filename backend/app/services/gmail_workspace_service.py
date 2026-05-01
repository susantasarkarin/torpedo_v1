"""
GMAIL WORKSPACE SERVICE
========================

Gmail API service using Google Workspace Domain-Wide Delegation.
Uses a single service account to access multiple mailboxes.

Setup Requirements:
1. Create Service Account in Google Cloud Console
2. Enable Gmail API
3. Enable Domain-Wide Delegation for the service account
4. In Google Workspace Admin Console:
   - Security → API Controls → Domain-wide Delegation
   - Add service account Client ID
   - Add scopes: https://www.googleapis.com/auth/gmail.readonly,
                 https://www.googleapis.com/auth/gmail.send,
                 https://www.googleapis.com/auth/gmail.modify

Usage:
    service = GmailWorkspaceService(mongo_uri, service_account_file)
    service.add_mailbox("user@yourdomain.com")
    emails = service.sync_mailbox(mailbox_id)
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from google.oauth2 import service_account
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError
from pymongo import MongoClient
from bson import ObjectId

logger = logging.getLogger(__name__)

# Gmail API scopes for domain-wide delegation
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]


@dataclass
class WorkspaceMailbox:
    """Gmail Workspace mailbox configuration"""
    id: str
    email: str
    display_name: str
    is_active: bool = True
    last_history_id: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    sync_error: Optional[str] = None
    email_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


def _serialize_doc(doc: Dict) -> Dict:
    """Convert MongoDB document to JSON-serializable dict"""
    if doc is None:
        return None
    result = {}
    for key, value in doc.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat() if value else None
        elif isinstance(value, ObjectId):
            result[key] = str(value)
        else:
            result[key] = value
    return result


class GmailWorkspaceService:
    """
    Gmail API service using Service Account with Domain-Wide Delegation.
    
    This allows a single service account to access multiple mailboxes
    in a Google Workspace domain without individual OAuth consent.
    """
    
    # Batch sizes
    LIST_PAGE_SIZE = 100
    GET_BATCH_SIZE = 50
    HISTORY_PAGE_SIZE = 100
    
    def __init__(
        self,
        mongo_uri: str,
        service_account_file: Optional[str] = None,
        service_account_info: Optional[Dict] = None,
        db_name: str = "torpedo_gmail"
    ):
        """
        Initialize Gmail Workspace service.
        
        Args:
            mongo_uri: MongoDB connection URI
            service_account_file: Path to service account JSON key file
            service_account_info: Service account credentials as dict (alternative to file)
            db_name: MongoDB database name
        """
        self.mongo_uri = mongo_uri
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        
        # Collections
        self.mailboxes = self.db["workspace_mailboxes"]
        self.emails = self.db["email_metadata"]
        self.config = self.db["gmail_config"]
        
        # Service account credentials
        self.service_account_file = service_account_file
        self.service_account_info = service_account_info
        
        # Load from file if provided
        if service_account_file and os.path.exists(service_account_file):
            with open(service_account_file) as f:
                self.service_account_info = json.load(f)
        
        # Create indexes
        self._create_indexes()
    
    def _create_indexes(self):
        """Create MongoDB indexes for efficient queries"""
        # Mailboxes
        self.mailboxes.create_index("email", unique=True)
        self.mailboxes.create_index("is_active")
        
        # Email metadata
        self.emails.create_index([("mailbox_id", 1), ("gmail_message_id", 1)], unique=True)
        self.emails.create_index([("mailbox_id", 1), ("timestamp", -1)])
        self.emails.create_index([("mailbox_id", 1), ("direction", 1)])
        self.emails.create_index("gmail_thread_id")
    
    def is_configured(self) -> bool:
        """Check if service account is configured"""
        return self.service_account_info is not None
    
    def save_service_account(self, credentials: Dict) -> bool:
        """
        Save service account credentials to database.
        
        Args:
            credentials: Service account JSON key contents
            
        Returns:
            True if saved successfully
        """
        try:
            # Validate required fields
            required = ["type", "project_id", "private_key", "client_email"]
            for field in required:
                if field not in credentials:
                    raise ValueError(f"Missing required field: {field}")
            
            if credentials["type"] != "service_account":
                raise ValueError("Credentials must be service account type")
            
            # Save to database (encrypted in production)
            self.config.update_one(
                {"_id": "service_account"},
                {
                    "$set": {
                        "credentials": credentials,
                        "updated_at": datetime.utcnow()
                    }
                },
                upsert=True
            )
            
            # Update in-memory
            self.service_account_info = credentials
            
            logger.info(f"Service account saved: {credentials.get('client_email')}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save service account: {e}")
            raise
    
    def load_service_account(self) -> Optional[Dict]:
        """Load service account credentials from database"""
        try:
            doc = self.config.find_one({"_id": "service_account"})
            if doc and "credentials" in doc:
                self.service_account_info = doc["credentials"]
                return self.service_account_info
        except Exception as e:
            logger.error(f"Failed to load service account: {e}")
        return None
    
    def get_service_account_info(self) -> Optional[Dict]:
        """Get service account info (without private key)"""
        if not self.service_account_info:
            self.load_service_account()
        
        if self.service_account_info:
            return {
                "client_email": self.service_account_info.get("client_email"),
                "project_id": self.service_account_info.get("project_id"),
                "client_id": self.service_account_info.get("client_id"),
            }
        return None
    
    def _get_credentials(self, user_email: str) -> service_account.Credentials:
        """
        Get delegated credentials for a specific user.
        
        Args:
            user_email: Email of the user to impersonate
            
        Returns:
            Delegated credentials
        """
        if not self.service_account_info:
            self.load_service_account()
        
        if not self.service_account_info:
            raise ValueError("Service account not configured")
        
        credentials = service_account.Credentials.from_service_account_info(
            self.service_account_info,
            scopes=GMAIL_SCOPES
        )
        
        # Delegate to the specific user
        delegated_credentials = credentials.with_subject(user_email)
        
        return delegated_credentials
    
    def _get_service(self, user_email: str) -> Resource:
        """Get Gmail API service for a specific user"""
        credentials = self._get_credentials(user_email)
        return build("gmail", "v1", credentials=credentials)

    def get_signature(self, email: str) -> Optional[str]:
        """
        Fetch the Gmail signature HTML for a mailbox via the sendAs settings API.

        Args:
            email: The mailbox email address whose signature to fetch.

        Returns:
            The signature HTML string, or None if not set / on error.
        """
        try:
            service = self._get_service(email)
            send_as = (
                service.users()
                .settings()
                .sendAs()
                .get(userId="me", sendAsEmail=email)
                .execute()
            )
            sig = send_as.get("signature") or None
            if sig:
                logger.info(f"Fetched Gmail signature for {email} ({len(sig)} chars)")
            else:
                logger.info(f"No Gmail signature configured for {email}")
            return sig
        except Exception as exc:
            logger.warning(f"Could not fetch Gmail signature for {email}: {exc}")
            return None

    def test_connection(self, email: str) -> Dict[str, Any]:
        """
        Test connection to a mailbox.
        
        Args:
            email: Email address to test
            
        Returns:
            Dict with connection status and profile info
        """
        try:
            service = self._get_service(email)
            profile = service.users().getProfile(userId="me").execute()
            
            return {
                "success": True,
                "email": profile.get("emailAddress"),
                "messages_total": profile.get("messagesTotal"),
                "threads_total": profile.get("threadsTotal"),
                "history_id": profile.get("historyId"),
            }
        except HttpError as e:
            error_msg = str(e)
            if "403" in error_msg:
                return {
                    "success": False,
                    "error": "Access denied. Please verify: 1) Domain-wide delegation is enabled for the service account. 2) The service account is added in Google Workspace Admin Console. 3) Required scopes are authorized.",
                    "details": error_msg
                }
            elif "404" in error_msg:
                return {
                    "success": False,
                    "error": "User not found. The email address may not exist in this domain.",
                    "details": error_msg
                }
            elif "400" in error_msg:
                return {
                    "success": False,
                    "error": "Invalid request. Please check the email address format.",
                    "details": error_msg
                }
            return {
                "success": False,
                "error": f"Gmail API error: {error_msg}",
                "details": error_msg
            }
        except Exception as e:
            error_str = str(e)
            # Handle common service account issues
            if "invalid_grant" in error_str.lower():
                return {
                    "success": False,
                    "error": "Service account authorization failed. Check domain-wide delegation settings in Google Workspace Admin Console."
                }
            if "unauthorized" in error_str.lower():
                return {
                    "success": False,
                    "error": "Unauthorized. The service account may not have permission to access this mailbox."
                }
            return {
                "success": False,
                "error": f"Connection failed: {error_str}"
            }
    
    # =========================================================================
    # MAILBOX MANAGEMENT
    # =========================================================================
    
    def add_mailbox(self, email: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Add a new mailbox to sync.
        
        Args:
            email: Email address to add
            display_name: Optional display name
            
        Returns:
            Mailbox document
        """
        # Check if already exists
        existing = self.mailboxes.find_one({"email": email.lower()})
        if existing:
            # Reactivate if inactive
            if not existing.get("is_active"):
                self.mailboxes.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"is_active": True, "updated_at": datetime.utcnow()}}
                )
                existing["is_active"] = True
            return {
                "id": str(existing["_id"]),
                **existing,
                "message": "Mailbox already exists"
            }
        
        # Test connection first
        test_result = self.test_connection(email)
        if not test_result["success"]:
            raise ValueError(f"Cannot access mailbox: {test_result.get('error')}")
        
        # Create mailbox
        doc = {
            "email": email.lower(),
            "display_name": display_name or email.split("@")[0],
            "is_active": True,
            "last_history_id": test_result.get("history_id"),
            "last_sync_at": None,
            "sync_error": None,
            "email_count": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            # Historic sync tracking fields
            "historic_sync_status": "not_started",  # not_started, pending, in_progress, completed
            "historic_sync_progress": 0,            # emails downloaded so far
            "historic_sync_total": test_result.get("messages_total", 0),  # total in Gmail
            "historic_sync_cursor": None,           # page_token for resume
            "historic_sync_started_at": None,
            "historic_sync_completed_at": None,
            "historic_sync_error": None,
        }
        
        result = self.mailboxes.insert_one(doc)
        doc["id"] = str(result.inserted_id)
        
        logger.info(f"Added workspace mailbox: {email}")
        return doc
    
    def remove_mailbox(self, mailbox_id: str, delete_emails: bool = False) -> bool:
        """
        Remove a mailbox.
        
        Args:
            mailbox_id: Mailbox ID to remove
            delete_emails: If True, also delete synced emails
            
        Returns:
            True if removed
        """
        try:
            oid = ObjectId(mailbox_id)
        except:
            return False
        
        mailbox = self.mailboxes.find_one({"_id": oid})
        if not mailbox:
            return False
        
        # Delete mailbox
        self.mailboxes.delete_one({"_id": oid})
        
        # Optionally delete emails
        if delete_emails:
            self.emails.delete_many({"mailbox_id": mailbox_id})
        
        logger.info(f"Removed mailbox: {mailbox.get('email')}")
        return True
    
    def get_mailbox(self, mailbox_id: str) -> Optional[Dict]:
        """Get mailbox by ID"""
        try:
            oid = ObjectId(mailbox_id)
        except:
            return None
        
        mailbox = self.mailboxes.find_one({"_id": oid})
        if mailbox:
            mailbox["id"] = str(mailbox.pop("_id"))
            return _serialize_doc(mailbox)
        return None
    
    def get_mailbox_by_email(self, email: str) -> Optional[Dict]:
        """Get mailbox by email address"""
        mailbox = self.mailboxes.find_one({"email": email.lower()})
        if mailbox:
            mailbox["id"] = str(mailbox.pop("_id"))
        return _serialize_doc(mailbox) if mailbox else None
    
    def list_mailboxes(self, active_only: bool = True) -> List[Dict]:
        """List all mailboxes"""
        query = {"is_active": True} if active_only else {}
        mailboxes = list(self.mailboxes.find(query).sort("email", 1))
        
        result = []
        for m in mailboxes:
            m["id"] = str(m.pop("_id"))
            result.append(_serialize_doc(m))
        
        return result
    
    def update_mailbox(self, mailbox_id: str, updates: Dict) -> bool:
        """Update mailbox settings"""
        try:
            oid = ObjectId(mailbox_id)
        except:
            return False
        
        # Only allow certain fields to be updated
        allowed = {"display_name", "is_active"}
        filtered = {k: v for k, v in updates.items() if k in allowed}
        filtered["updated_at"] = datetime.utcnow()
        
        result = self.mailboxes.update_one({"_id": oid}, {"$set": filtered})
        return result.modified_count > 0
    
    # =========================================================================
    # EMAIL SYNC
    # =========================================================================
    
    def sync_mailbox(
        self,
        mailbox_id: str,
        max_results: int = 500,
        full_sync: bool = False
    ) -> Dict[str, Any]:
        """
        Sync emails for a mailbox.
        
        Uses History API for incremental sync after initial full sync.
        
        Args:
            mailbox_id: Mailbox ID to sync
            max_results: Maximum emails to fetch
            full_sync: Force full sync instead of incremental
            
        Returns:
            Sync statistics
        """
        mailbox = self.get_mailbox(mailbox_id)
        if not mailbox:
            raise ValueError(f"Mailbox not found: {mailbox_id}")
        
        email = mailbox["email"]
        
        try:
            service = self._get_service(email)
            
            # Get current profile
            profile = service.users().getProfile(userId="me").execute()
            current_history_id = profile.get("historyId")
            
            stats = {
                "mailbox_id": mailbox_id,
                "email": email,
                "new_emails": 0,
                "updated_emails": 0,
                "errors": 0,
                "sync_type": "full" if full_sync or not mailbox.get("last_history_id") else "incremental"
            }
            
            if full_sync or not mailbox.get("last_history_id"):
                # Full sync - list all messages
                stats = self._full_sync(service, mailbox_id, email, max_results, stats)
            else:
                # Incremental sync using History API
                stats = self._incremental_sync(
                    service, mailbox_id, email,
                    mailbox["last_history_id"], stats
                )
            
            # Update mailbox state
            self.mailboxes.update_one(
                {"_id": ObjectId(mailbox_id)},
                {
                    "$set": {
                        "last_history_id": current_history_id,
                        "last_sync_at": datetime.utcnow(),
                        "sync_error": None,
                        "email_count": self.emails.count_documents({"mailbox_id": mailbox_id}),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            stats["success"] = True
            return stats
            
        except Exception as e:
            logger.error(f"Sync error for {email}: {e}")
            
            # Update error state
            self.mailboxes.update_one(
                {"_id": ObjectId(mailbox_id)},
                {
                    "$set": {
                        "sync_error": str(e),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            return {
                "success": False,
                "mailbox_id": mailbox_id,
                "email": email,
                "error": str(e)
            }
    
    def _full_sync(
        self,
        service: Resource,
        mailbox_id: str,
        email: str,
        max_results: int,
        stats: Dict
    ) -> Dict:
        """Perform full sync of mailbox"""
        logger.info(f"Starting full sync for {email}")
        
        page_token = None
        fetched = 0
        
        while fetched < max_results:
            # List messages
            results = service.users().messages().list(
                userId="me",
                maxResults=min(self.LIST_PAGE_SIZE, max_results - fetched),
                pageToken=page_token
            ).execute()
            
            messages = results.get("messages", [])
            if not messages:
                break
            
            # Fetch message details with FULL body for AI classification
            for msg in messages:
                try:
                    # Use 'full' format to download complete email body
                    msg_data = service.users().messages().get(
                        userId="me",
                        id=msg["id"],
                        format="full"  # Changed from 'metadata' to 'full' for AI classification
                    ).execute()
                    
                    self._save_email_metadata(mailbox_id, email, msg_data)
                    stats["new_emails"] += 1
                    
                except Exception as e:
                    logger.warning(f"Error fetching message {msg['id']}: {e}")
                    stats["errors"] += 1
            
            fetched += len(messages)
            page_token = results.get("nextPageToken")
            
            if not page_token:
                break
        
        return stats
    
    def _incremental_sync(
        self,
        service: Resource,
        mailbox_id: str,
        email: str,
        start_history_id: str,
        stats: Dict
    ) -> Dict:
        """Perform incremental sync using History API"""
        logger.info(f"Starting incremental sync for {email} from history {start_history_id}")
        
        try:
            page_token = None
            
            while True:
                results = service.users().history().list(
                    userId="me",
                    startHistoryId=start_history_id,
                    historyTypes=["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"],
                    maxResults=self.HISTORY_PAGE_SIZE,
                    pageToken=page_token
                ).execute()
                
                history = results.get("history", [])
                
                for record in history:
                    # Handle new messages - download full body for AI classification
                    for msg in record.get("messagesAdded", []):
                        try:
                            msg_data = service.users().messages().get(
                                userId="me",
                                id=msg["message"]["id"],
                                format="full"  # Changed from 'metadata' to 'full' for AI classification
                            ).execute()
                            
                            self._save_email_metadata(mailbox_id, email, msg_data)
                            stats["new_emails"] += 1
                            
                        except Exception as e:
                            stats["errors"] += 1
                    
                    # Handle deleted messages
                    for msg in record.get("messagesDeleted", []):
                        self.emails.delete_one({
                            "mailbox_id": mailbox_id,
                            "gmail_message_id": msg["message"]["id"]
                        })
                
                page_token = results.get("nextPageToken")
                if not page_token:
                    break
                    
        except HttpError as e:
            if "404" in str(e) or "historyId" in str(e).lower():
                # History expired, need full sync
                logger.warning(f"History expired for {email}, doing full sync")
                stats["sync_type"] = "full (history expired)"
                return self._full_sync(service, mailbox_id, email, 500, stats)
            raise
        
        return stats
    
    def _save_email_metadata(self, mailbox_id: str, mailbox_email: str, msg_data: Dict):
        """Save email metadata and body to database for AI classification"""
        headers = {h["name"].lower(): h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
        
        # Parse from
        from_header = headers.get("from", "")
        from_email = self._extract_email(from_header)
        from_name = self._extract_name(from_header)
        
        # Parse to/cc
        to_emails = self._parse_email_list(headers.get("to", ""))
        cc_emails = self._parse_email_list(headers.get("cc", ""))
        
        # Determine direction
        direction = "outbound" if mailbox_email.lower() in from_email.lower() else "inbound"
        
        # Parse date
        date_str = headers.get("date", "")
        try:
            from email.utils import parsedate_to_datetime
            timestamp = parsedate_to_datetime(date_str)
        except:
            timestamp = datetime.utcnow()
        
        # Check for attachments and extract body
        payload = msg_data.get("payload", {})
        parts = payload.get("parts", [])
        has_attachments = any(p.get("filename") for p in parts)
        attachment_count = sum(1 for p in parts if p.get("filename"))
        
        # Extract email body (plain text and HTML)
        body_plain, body_html = self._extract_body(payload)
        
        labels = msg_data.get("labelIds", [])
        
        doc = {
            "mailbox_id": mailbox_id,
            "gmail_message_id": msg_data["id"],
            "gmail_thread_id": msg_data.get("threadId"),
            "from_email": from_email,
            "from_name": from_name,
            "to_emails": to_emails,
            "cc_emails": cc_emails,
            "subject": headers.get("subject", "(No Subject)"),
            "snippet": msg_data.get("snippet", ""),
            "body_plain": body_plain,  # Added for AI classification
            "body_html": body_html,    # Added for display
            "timestamp": timestamp,
            "labels": labels,
            "direction": direction,
            "has_attachments": has_attachments,
            "attachment_count": attachment_count,
            "is_read": "UNREAD" not in labels,
            "is_starred": "STARRED" in labels,
            "size_estimate": msg_data.get("sizeEstimate", 0),
            "synced_at": datetime.utcnow(),
        }
        
        # Upsert
        self.emails.update_one(
            {"mailbox_id": mailbox_id, "gmail_message_id": msg_data["id"]},
            {"$set": doc},
            upsert=True
        )
    
    def _extract_body(self, payload: Dict) -> Tuple[str, str]:
        """Extract plain text and HTML body from email payload"""
        import base64
        
        body_plain = ""
        body_html = ""
        
        def decode_body(data: str) -> str:
            """Decode base64url encoded body"""
            try:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
            except:
                return ""
        
        def extract_from_parts(parts: List[Dict]):
            """Recursively extract body from parts"""
            nonlocal body_plain, body_html
            
            for part in parts:
                mime_type = part.get("mimeType", "")
                body_data = part.get("body", {}).get("data", "")
                
                if body_data:
                    decoded = decode_body(body_data)
                    if mime_type == "text/plain" and not body_plain:
                        body_plain = decoded
                    elif mime_type == "text/html" and not body_html:
                        body_html = decoded
                
                # Recurse into nested parts
                if part.get("parts"):
                    extract_from_parts(part["parts"])
        
        # Check if body is directly in payload (simple emails)
        body_data = payload.get("body", {}).get("data", "")
        mime_type = payload.get("mimeType", "")
        
        if body_data:
            decoded = decode_body(body_data)
            if "html" in mime_type:
                body_html = decoded
            else:
                body_plain = decoded
        
        # Extract from parts (multipart emails)
        if payload.get("parts"):
            extract_from_parts(payload["parts"])
        
        # If no plain text, strip HTML
        if not body_plain and body_html:
            import re
            body_plain = re.sub(r'<[^>]+>', ' ', body_html)
            body_plain = re.sub(r'\s+', ' ', body_plain).strip()
        
        return body_plain[:10000], body_html[:50000]  # Limit size for DB
    
    def _extract_email(self, header: str) -> str:
        """Extract email address from header"""
        import re
        match = re.search(r'<([^>]+)>', header)
        if match:
            return match.group(1)
        # Maybe it's just an email
        if "@" in header:
            return header.strip()
        return ""
    
    def _extract_name(self, header: str) -> Optional[str]:
        """Extract name from header"""
        import re
        match = re.match(r'^([^<]+)<', header)
        if match:
            return match.group(1).strip().strip('"')
        return None
    
    def _parse_email_list(self, header: str) -> List[str]:
        """Parse comma-separated email list"""
        if not header:
            return []
        
        emails = []
        for part in header.split(","):
            email = self._extract_email(part.strip())
            if email:
                emails.append(email)
        return emails
    
    # =========================================================================
    # EMAIL RETRIEVAL
    # =========================================================================
    
    def get_emails(
        self,
        mailbox_id: Optional[str] = None,
        direction: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get emails with filters.
        
        Args:
            mailbox_id: Filter by mailbox
            direction: Filter by direction (inbound/outbound)
            limit: Max results
            offset: Skip count
            search: Search in subject/from/to
            
        Returns:
            Dict with emails and total count
        """
        query = {}
        
        if mailbox_id:
            query["mailbox_id"] = mailbox_id
        
        if direction:
            query["direction"] = direction
        
        if search:
            query["$or"] = [
                {"subject": {"$regex": search, "$options": "i"}},
                {"from_email": {"$regex": search, "$options": "i"}},
                {"from_name": {"$regex": search, "$options": "i"}},
                {"snippet": {"$regex": search, "$options": "i"}},
            ]
        
        total = self.emails.count_documents(query)
        
        emails = list(
            self.emails.find(query)
            .sort("timestamp", -1)
            .skip(offset)
            .limit(limit)
        )
        
        for e in emails:
            e["id"] = str(e.pop("_id"))
        
        return {
            "emails": emails,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    
    def get_email_content(self, mailbox_id: str, gmail_message_id: str) -> Optional[Dict]:
        """
        Fetch full email content on-demand.
        
        Args:
            mailbox_id: Mailbox ID
            gmail_message_id: Gmail message ID
            
        Returns:
            Full email content
        """
        mailbox = self.get_mailbox(mailbox_id)
        if not mailbox:
            return None
        
        try:
            service = self._get_service(mailbox["email"])
            
            msg = service.users().messages().get(
                userId="me",
                id=gmail_message_id,
                format="full"
            ).execute()
            
            # Extract body
            body_html = None
            body_text = None
            
            def extract_body(payload):
                nonlocal body_html, body_text
                
                mime_type = payload.get("mimeType", "")
                
                if mime_type == "text/html":
                    data = payload.get("body", {}).get("data", "")
                    if data:
                        import base64
                        body_html = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                elif mime_type == "text/plain":
                    data = payload.get("body", {}).get("data", "")
                    if data:
                        import base64
                        body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                
                for part in payload.get("parts", []):
                    extract_body(part)
            
            extract_body(msg.get("payload", {}))
            
            return {
                "gmail_message_id": gmail_message_id,
                "body_html": body_html,
                "body_text": body_text or body_html,
                "raw": msg
            }
            
        except Exception as e:
            logger.error(f"Error fetching email content: {e}")
            return None
    
    # =========================================================================
    # STATISTICS
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics"""
        mailboxes = self.list_mailboxes()
        total_emails = self.emails.count_documents({})
        
        inbound = self.emails.count_documents({"direction": "inbound"})
        outbound = self.emails.count_documents({"direction": "outbound"})
        
        return {
            "mailbox_count": len(mailboxes),
            "total_emails": total_emails,
            "inbound_emails": inbound,
            "outbound_emails": outbound,
            "mailboxes": [
                {
                    "email": m["email"],
                    "email_count": m.get("email_count", 0),
                    "last_sync": m.get("last_sync_at"),
                    "is_active": m.get("is_active", True)
                }
                for m in mailboxes
            ]
        }
    
    # =========================================================================
    # SEND EMAIL via Gmail API
    # =========================================================================
    
    def send_email(
        self,
        from_email: str,
        to: List[str],
        subject: str,
        body_html: str,
        body_plain: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        reply_to_message_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        signature_html: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Send email via Gmail API using domain-wide delegation.
        
        Args:
            from_email: Sender email (must be a configured mailbox or alias)
            to: List of recipient emails
            subject: Email subject
            body_html: HTML body content
            body_plain: Plain text body (optional)
            cc: CC recipients (optional)
            bcc: BCC recipients (optional)
            reply_to_message_id: For threading replies
            thread_id: Gmail thread ID for replies
            signature_html: Email signature HTML to append
            attachments: List of dicts with keys: filename, content (base64 or bytes), mime_type
        
        Returns:
            Dict with success status and message_id or error
        """
        import base64
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders
        
        try:
            # Find the mailbox for this sender
            mailbox = self.mailboxes.find_one({
                "$or": [
                    {"email": from_email.lower()},
                    {"aliases.email": from_email.lower()},
                    {"aliases": from_email.lower()}  # Handle string aliases
                ],
                "is_active": True
            })
            
            if not mailbox:
                return {
                    "success": False,
                    "error": f"No active mailbox found for {from_email}"
                }
            
            # Get Gmail service for this mailbox
            gmail = self._get_service(mailbox["email"])
            
            # Append signature if provided
            final_body_html = body_html
            final_body_plain = body_plain or ""
            
            if signature_html:
                final_body_html = body_html + "<br><br>" + signature_html
                # Strip HTML for plain text signature
                import re
                sig_plain = re.sub(r'<[^>]+>', '', signature_html)
                final_body_plain = (body_plain or "") + "\n\n" + sig_plain
            
            # Create message — use 'mixed' when there are attachments, otherwise 'alternative'
            has_attachments = bool(attachments)
            if has_attachments:
                msg = MIMEMultipart("mixed")
                body_part = MIMEMultipart("alternative")
            else:
                msg = MIMEMultipart("alternative")
                body_part = msg
            
            msg["To"] = ", ".join(to)
            # Use formatted From with display name for better deliverability
            _display_name = mailbox.get("display_name", "")
            if _display_name:
                from email.utils import formataddr as _formataddr
                msg["From"] = _formataddr((_display_name, from_email))
            else:
                msg["From"] = from_email
            msg["Subject"] = subject
            
            if cc:
                msg["Cc"] = ", ".join(cc)
            
            # Reply-To (same as From; helps with deliverability)
            msg["Reply-To"] = from_email

            # List-Unsubscribe (required by Gmail/Yahoo bulk-sender guidelines)
            msg["List-Unsubscribe"] = f"<mailto:{from_email}?subject=unsubscribe>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

            # Add reply headers for threading
            if reply_to_message_id:
                msg["In-Reply-To"] = reply_to_message_id
                msg["References"] = reply_to_message_id
            
            # Add body parts (plain first, then HTML for proper rendering)
            if final_body_plain:
                body_part.attach(MIMEText(final_body_plain, "plain"))
            body_part.attach(MIMEText(final_body_html, "html"))
            
            # If mixed mode, attach the body_part as a sub-part
            if has_attachments:
                msg.attach(body_part)
                
                # Attach files
                for att in attachments:
                    filename = att.get("filename", "attachment")
                    mime_type = att.get("mime_type", "application/octet-stream")
                    content = att.get("content")  # base64 string or bytes
                    
                    maintype, subtype = mime_type.split("/", 1) if "/" in mime_type else ("application", "octet-stream")
                    part = MIMEBase(maintype, subtype)
                    
                    if isinstance(content, str):
                        # base64-encoded string
                        part.set_payload(base64.b64decode(content))
                    elif isinstance(content, bytes):
                        part.set_payload(content)
                    else:
                        continue
                    
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", "attachment", filename=filename)
                    msg.attach(part)
            
            # Encode for Gmail API
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            
            # Build request body
            send_body = {"raw": raw}
            if thread_id:
                send_body["threadId"] = thread_id
            
            # Send via Gmail API
            result = gmail.users().messages().send(
                userId="me",
                body=send_body
            ).execute()
            
            sent_message_id = result.get("id")
            
            # Store the sent email in our database
            sent_doc = {
                "mailbox_id": str(mailbox["_id"]),
                "gmail_message_id": sent_message_id,
                "provider_message_id": sent_message_id,
                "provider_thread_id": result.get("threadId", thread_id),
                "direction": "outbound",
                "from_address": {"email": from_email, "name": mailbox.get("display_name", "")},
                "to_addresses": [{"email": e, "name": ""} for e in to],
                "cc_addresses": [{"email": e, "name": ""} for e in (cc or [])],
                "subject": subject,
                "body_plain": final_body_plain,
                "body_html": final_body_html,
                "snippet": (body_plain or body_html[:200])[:200],
                "timestamp": datetime.utcnow(),
                "labels": ["SENT"],
                "has_attachments": has_attachments,
                "attachment_count": len(attachments) if attachments else 0,
                "synced_at": datetime.utcnow(),
                "processed": True,
                "is_read": True
            }
            self.emails.insert_one(sent_doc)
            
            logger.info(f"Email sent successfully via Gmail API from {from_email} to {to}")
            
            return {
                "success": True,
                "message_id": sent_message_id,
                "thread_id": result.get("threadId"),
                "from": from_email,
                "to": to
            }
            
        except HttpError as e:
            logger.error(f"Gmail API error sending email: {e}")
            return {
                "success": False,
                "error": f"Gmail API error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # =========================================================================
    # HISTORIC EMAIL SYNC (Background - Low Priority)
    # =========================================================================
    
    # Configuration for historic sync
    HISTORIC_BATCH_SIZE = 100  # Emails per batch
    HISTORIC_BATCH_DELAY = 2.0  # Seconds between batches (throttling)
    
    def check_has_historic_emails(self, mailbox_id: str) -> Dict[str, Any]:
        """
        Check if a mailbox has historic emails that haven't been downloaded yet.
        Compares local email count vs Gmail's total message count.
        
        Returns:
            Dict with has_historic, local_count, gmail_total, pending_count
        """
        mailbox = self.get_mailbox(mailbox_id)
        if not mailbox:
            return {"error": "Mailbox not found", "has_historic": False}
        
        email = mailbox["email"]
        historic_status = mailbox.get("historic_sync_status", "not_started")
        
        # If already completed, no need to check again
        if historic_status == "completed":
            return {
                "has_historic": False,
                "status": "completed",
                "local_count": mailbox.get("email_count", 0),
                "message": "Historic sync already completed"
            }
        
        try:
            service = self._get_service(email)
            profile = service.users().getProfile(userId="me").execute()
            gmail_total = profile.get("messagesTotal", 0)
            
            # Count local emails for this mailbox
            local_count = self.emails.count_documents({"mailbox_id": mailbox_id})
            
            # Calculate pending
            pending_count = max(0, gmail_total - local_count)
            has_historic = pending_count > 0
            
            # If has historic and status is not_started, mark as pending
            if has_historic and historic_status == "not_started":
                self.mailboxes.update_one(
                    {"_id": ObjectId(mailbox_id)},
                    {
                        "$set": {
                            "historic_sync_status": "pending",
                            "historic_sync_total": gmail_total,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
            
            return {
                "has_historic": has_historic,
                "status": historic_status if not has_historic else "pending",
                "local_count": local_count,
                "gmail_total": gmail_total,
                "pending_count": pending_count
            }
            
        except Exception as e:
            logger.error(f"Error checking historic emails for {email}: {e}")
            return {
                "has_historic": False,
                "error": str(e)
            }
    
    def get_mailboxes_needing_historic_sync(self) -> List[Dict]:
        """
        Get all mailboxes that need historic email sync.
        Returns mailboxes with status 'pending' or 'not_started' (needs check).
        """
        # Get mailboxes with pending status
        pending = list(self.mailboxes.find({
            "is_active": True,
            "historic_sync_status": "pending"
        }))
        
        # Also get not_started to check if they need sync
        not_started = list(self.mailboxes.find({
            "is_active": True,
            "$or": [
                {"historic_sync_status": "not_started"},
                {"historic_sync_status": {"$exists": False}}
            ]
        }))
        
        result = []
        
        # Add pending mailboxes
        for m in pending:
            m["id"] = str(m.pop("_id"))
            result.append(_serialize_doc(m))
        
        # Check not_started mailboxes and add if they have pending emails
        for m in not_started:
            mailbox_id = str(m["_id"])
            check_result = self.check_has_historic_emails(mailbox_id)
            if check_result.get("has_historic"):
                m["id"] = mailbox_id
                del m["_id"]
                m["historic_sync_status"] = "pending"
                m["historic_sync_total"] = check_result.get("gmail_total", 0)
                result.append(_serialize_doc(m))
        
        return result
    
    def historic_sync_batch(
        self,
        mailbox_id: str,
        batch_size: int = None
    ) -> Dict[str, Any]:
        """
        Sync a batch of historic emails for a mailbox.
        Uses pagination with cursor persistence for resumability.
        
        This method is designed to be called repeatedly until completion,
        with small batches to avoid blocking the main app.
        
        Args:
            mailbox_id: Mailbox ID to sync
            batch_size: Number of emails to fetch in this batch
            
        Returns:
            Dict with progress info and whether more emails remain
        """
        import time
        
        if batch_size is None:
            batch_size = self.HISTORIC_BATCH_SIZE
        
        mailbox = self.get_mailbox(mailbox_id)
        if not mailbox:
            return {"success": False, "error": "Mailbox not found"}
        
        email = mailbox["email"]
        historic_status = mailbox.get("historic_sync_status", "not_started")
        
        # Skip if already completed
        if historic_status == "completed":
            return {
                "success": True,
                "status": "completed",
                "message": "Historic sync already completed",
                "has_more": False
            }
        
        # Get resume cursor if exists
        page_token = mailbox.get("historic_sync_cursor")
        current_progress = mailbox.get("historic_sync_progress", 0)
        
        try:
            service = self._get_service(email)
            
            # Mark as in_progress if just starting
            if historic_status in ("not_started", "pending"):
                self.mailboxes.update_one(
                    {"_id": ObjectId(mailbox_id)},
                    {
                        "$set": {
                            "historic_sync_status": "in_progress",
                            "historic_sync_started_at": datetime.utcnow(),
                            "historic_sync_error": None,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
            
            # List messages with pagination
            list_params = {
                "userId": "me",
                "maxResults": batch_size,
            }
            if page_token:
                list_params["pageToken"] = page_token
            
            results = service.users().messages().list(**list_params).execute()
            
            messages = results.get("messages", [])
            next_page_token = results.get("nextPageToken")
            
            fetched_count = 0
            errors = 0
            
            # Fetch message details
            for msg in messages:
                try:
                    # Check if already exists (skip if so)
                    existing = self.emails.find_one({
                        "mailbox_id": mailbox_id,
                        "gmail_message_id": msg["id"]
                    })
                    
                    if existing:
                        # Already have this email, skip
                        fetched_count += 1
                        continue
                    
                    msg_data = service.users().messages().get(
                        userId="me",
                        id=msg["id"],
                        format="full"
                    ).execute()
                    
                    self._save_email_metadata(mailbox_id, email, msg_data)
                    fetched_count += 1
                    
                except Exception as e:
                    logger.warning(f"Error fetching historic message {msg['id']}: {e}")
                    errors += 1
            
            # Update progress and cursor
            new_progress = current_progress + fetched_count
            has_more = next_page_token is not None
            
            update_fields = {
                "historic_sync_progress": new_progress,
                "historic_sync_cursor": next_page_token,
                "email_count": self.emails.count_documents({"mailbox_id": mailbox_id}),
                "updated_at": datetime.utcnow()
            }
            
            # If no more pages, mark as completed
            if not has_more:
                update_fields["historic_sync_status"] = "completed"
                update_fields["historic_sync_completed_at"] = datetime.utcnow()
                update_fields["historic_sync_cursor"] = None
            
            self.mailboxes.update_one(
                {"_id": ObjectId(mailbox_id)},
                {"$set": update_fields}
            )
            
            logger.info(f"Historic sync batch for {email}: +{fetched_count} emails, progress: {new_progress}, has_more: {has_more}")
            
            return {
                "success": True,
                "status": "completed" if not has_more else "in_progress",
                "fetched": fetched_count,
                "errors": errors,
                "progress": new_progress,
                "has_more": has_more,
                "next_cursor": next_page_token
            }
            
        except HttpError as e:
            error_msg = str(e)
            logger.error(f"Gmail API error in historic sync for {email}: {error_msg}")
            
            # Handle rate limiting
            if "429" in error_msg or "rateLimitExceeded" in error_msg.lower():
                # Pause for rate limit
                self.mailboxes.update_one(
                    {"_id": ObjectId(mailbox_id)},
                    {
                        "$set": {
                            "historic_sync_status": "pending",  # Will retry later
                            "historic_sync_error": "Rate limited - will retry",
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                return {
                    "success": False,
                    "error": "Rate limited",
                    "retry_after": 60,
                    "has_more": True
                }
            
            self.mailboxes.update_one(
                {"_id": ObjectId(mailbox_id)},
                {
                    "$set": {
                        "historic_sync_error": error_msg,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            return {
                "success": False,
                "error": error_msg,
                "has_more": True
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Historic sync error for {email}: {error_msg}")
            
            self.mailboxes.update_one(
                {"_id": ObjectId(mailbox_id)},
                {
                    "$set": {
                        "historic_sync_error": error_msg,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            return {
                "success": False,
                "error": error_msg,
                "has_more": True
            }
    
    def get_historic_sync_status(self, mailbox_id: str = None) -> Dict[str, Any]:
        """
        Get historic sync status for a mailbox or all mailboxes.
        
        Args:
            mailbox_id: Optional specific mailbox, or None for all
            
        Returns:
            Status dict with progress info
        """
        if mailbox_id:
            mailbox = self.get_mailbox(mailbox_id)
            if not mailbox:
                return {"error": "Mailbox not found"}
            
            return {
                "mailbox_id": mailbox_id,
                "email": mailbox["email"],
                "status": mailbox.get("historic_sync_status", "not_started"),
                "progress": mailbox.get("historic_sync_progress", 0),
                "total": mailbox.get("historic_sync_total", 0),
                "started_at": mailbox.get("historic_sync_started_at"),
                "completed_at": mailbox.get("historic_sync_completed_at"),
                "error": mailbox.get("historic_sync_error"),
                "local_email_count": mailbox.get("email_count", 0)
            }
        
        # Get all mailboxes status
        mailboxes = list(self.mailboxes.find({"is_active": True}))
        
        statuses = []
        for m in mailboxes:
            statuses.append({
                "mailbox_id": str(m["_id"]),
                "email": m["email"],
                "status": m.get("historic_sync_status", "not_started"),
                "progress": m.get("historic_sync_progress", 0),
                "total": m.get("historic_sync_total", 0),
                "error": m.get("historic_sync_error")
            })
        
        # Summary
        total_pending = sum(1 for s in statuses if s["status"] == "pending")
        total_in_progress = sum(1 for s in statuses if s["status"] == "in_progress")
        total_completed = sum(1 for s in statuses if s["status"] == "completed")
        total_not_started = sum(1 for s in statuses if s["status"] == "not_started")
        
        return {
            "summary": {
                "total_mailboxes": len(statuses),
                "not_started": total_not_started,
                "pending": total_pending,
                "in_progress": total_in_progress,
                "completed": total_completed
            },
            "mailboxes": statuses
        }
