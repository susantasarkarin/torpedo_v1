"""
PARALLEL EMAIL SYNC SERVICE
============================

Parallel email download for all accounts with:
- Concurrent downloads using ThreadPoolExecutor
- Dynamic email count detection (no fixed limits)
- Progress tracking per account
- Resume capability for interrupted downloads
- Batched progress updates to reduce MongoDB write load

Key Features:
1. Gets total email count before download starts
2. Downloads ALL emails (no 50,000 limit)
3. Parallel processing across multiple accounts
4. Real-time progress updates to MongoDB (batched every 50 emails or 2 seconds)
"""

import os
import imaplib
import email
import logging
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from time import time as get_time

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Use shared connection pools instead of creating standalone MongoClient
# This prevents connection exhaustion and ensures proper resource sharing
try:
    from db_pools import pool_manager, get_background_collection
    
    # Get collections from the background pool (optimized for sync operations)
    gmail_db = pool_manager.get_client('background')['torpedo_gmail']
    email_db = pool_manager.get_client('background')['email_automation']
    
    imap_accounts_collection = gmail_db['imap_accounts']
    parallel_sync_progress = gmail_db['parallel_sync_progress']
    email_sync_log = gmail_db['email_sync_log']
    email_leads_collection = email_db['email_leads']
    
    logger.info("Using shared MongoDB connection pool for email sync")
except ImportError:
    # Fallback to direct connection if db_pools not available
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    gmail_db = client['torpedo_gmail']
    email_db = client['email_automation']

    # Collections
    imap_accounts_collection = gmail_db['imap_accounts']
    parallel_sync_progress = gmail_db['parallel_sync_progress']
    email_sync_log = gmail_db['email_sync_log']
    email_leads_collection = email_db['email_leads']
    
    logger.warning("db_pools not available, using standalone MongoDB client")


# ============== CONFIGURATION ==============

MAX_PARALLEL_ACCOUNTS = 5  # Max accounts to sync in parallel
BATCH_SIZE = 100  # Emails to fetch per batch within an account
CONNECTION_TIMEOUT = 60  # IMAP connection timeout
PROGRESS_BATCH_SIZE = 50  # Update MongoDB every N emails
PROGRESS_BATCH_INTERVAL = 2.0  # Or every N seconds, whichever comes first


# ============== PROGRESS BUFFER ==============

class ProgressBuffer:
    """
    Buffers progress updates to reduce MongoDB write frequency.
    Flushes every PROGRESS_BATCH_SIZE emails or PROGRESS_BATCH_INTERVAL seconds.
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._buffer: Dict[str, Dict[str, Any]] = {}  # email -> pending updates
        self._last_flush: Dict[str, float] = {}  # email -> last flush time
        self._email_counts: Dict[str, int] = {}  # email -> emails since last flush
        self._initialized = True
    
    def add_update(self, email_address: str, updates: Dict[str, Any], force: bool = False) -> bool:
        """
        Buffer an update. Returns True if buffer was flushed.
        
        Args:
            email_address: Account email
            updates: Dict of fields to update
            force: Force immediate flush (for status changes)
        """
        with self._lock:
            # Merge with existing pending updates
            if email_address not in self._buffer:
                self._buffer[email_address] = {}
                self._last_flush[email_address] = get_time()
                self._email_counts[email_address] = 0
            
            self._buffer[email_address].update(updates)
            self._email_counts[email_address] += 1
            
            # Check if we should flush
            should_flush = force
            if not should_flush:
                # Flush on status changes (important events)
                status = updates.get("status")
                if status in ("completed", "error", "cancelled", "connecting", "counting", "downloading"):
                    should_flush = True
            
            if not should_flush:
                # Flush every PROGRESS_BATCH_SIZE emails
                if self._email_counts[email_address] >= PROGRESS_BATCH_SIZE:
                    should_flush = True
            
            if not should_flush:
                # Flush every PROGRESS_BATCH_INTERVAL seconds
                if get_time() - self._last_flush.get(email_address, 0) >= PROGRESS_BATCH_INTERVAL:
                    should_flush = True
            
            if should_flush:
                self._flush_one(email_address)
                return True
            
            return False
    
    def _flush_one(self, email_address: str):
        """Flush buffered updates for one account."""
        if email_address not in self._buffer or not self._buffer[email_address]:
            return
        
        updates = self._buffer[email_address]
        updates["updated_at"] = datetime.utcnow()
        
        try:
            parallel_sync_progress.update_one(
                {"email": email_address},
                {"$set": updates},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error flushing progress for {email_address}: {e}")
        
        # Reset buffer for this account
        self._buffer[email_address] = {}
        self._last_flush[email_address] = get_time()
        self._email_counts[email_address] = 0
    
    def flush_all(self):
        """Flush all pending updates."""
        with self._lock:
            for email_address in list(self._buffer.keys()):
                self._flush_one(email_address)


# Global progress buffer instance
_progress_buffer = ProgressBuffer()


@dataclass
class SyncProgress:
    """Track sync progress for a single account"""
    email: str
    status: str = "pending"  # pending, connecting, counting, downloading, processing, completed, error
    total_emails: int = 0
    downloaded: int = 0
    processed: int = 0
    new_leads: int = 0
    updated_leads: int = 0
    errors: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_folder: str = ""
    folders_completed: List[str] = field(default_factory=list)


@dataclass
class IMAPAccountConfig:
    """IMAP account configuration"""
    email: str
    password: str
    imap_server: str = "imap.gmail.com"
    imap_port: int = 993
    use_ssl: bool = True
    display_name: str = ""


# ============== SENT FOLDER NAMES ==============

SENT_FOLDER_NAMES = [
    "[Gmail]/Sent Mail",
    "Sent",
    "Sent Items",
    "Sent Mail",
    "INBOX.Sent",
    "Sent Messages"
]


# ============== UTILITY FUNCTIONS ==============

def decode_email_header(header_value: str) -> str:
    """Decode email header value"""
    if not header_value:
        return ""
    try:
        decoded_parts = decode_header(header_value)
        result = ""
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result += part.decode(encoding or 'utf-8', errors='ignore')
            else:
                result += part
        return result.strip()
    except Exception:
        return str(header_value) if header_value else ""


def get_email_body(msg) -> str:
    """Extract email body from message"""
    body = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or 'utf-8'
                            body = payload.decode(charset, errors='ignore')
                            break
                    except Exception:
                        continue
                        
                elif content_type == "text/html" and "attachment" not in content_disposition and not body:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or 'utf-8'
                            body = payload.decode(charset, errors='ignore')
                    except Exception:
                        continue
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                body = payload.decode(charset, errors='ignore')
    except Exception as e:
        logger.warning(f"Error extracting body: {e}")
    
    return body[:10000] if body else ""  # Limit body size


def connect_imap(account: IMAPAccountConfig) -> imaplib.IMAP4:
    """Establish IMAP connection"""
    try:
        if account.use_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port, timeout=CONNECTION_TIMEOUT)
        else:
            imap = imaplib.IMAP4(account.imap_server, account.imap_port)
        
        imap.login(account.email, account.password)
        return imap
    except Exception as e:
        logger.error(f"IMAP connection failed for {account.email}: {e}")
        raise


def update_progress(email_address: str, updates: Dict[str, Any], force: bool = False):
    """
    Update sync progress in MongoDB using buffered writes.
    
    Updates are batched to reduce MongoDB write load:
    - Writes every 50 emails OR every 2 seconds, whichever comes first
    - Status changes (completed, error, etc.) are written immediately
    
    Args:
        email_address: Account email
        updates: Dict of fields to update
        force: Force immediate write to MongoDB
    """
    # Status changes should always flush immediately
    status = updates.get("status")
    if status in ("completed", "error", "cancelled"):
        force = True
    
    _progress_buffer.add_update(email_address, updates, force=force)


def flush_all_progress():
    """Flush all pending progress updates to MongoDB."""
    _progress_buffer.flush_all()


def is_sync_cancelled(email_address: str) -> bool:
    """Check if sync has been cancelled for this mailbox"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=3, decode_responses=True)
        cancel_key = f"sync:cancel:{email_address}"
        return r.get(cancel_key) == "1"
    except:
        return False


def clear_sync_cancellation(email_address: str):
    """Clear the cancellation flag"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=3, decode_responses=True)
        cancel_key = f"sync:cancel:{email_address}"
        r.delete(cancel_key)
    except:
        pass


# ============== EMAIL COUNT FUNCTIONS ==============

def get_total_email_count(account: IMAPAccountConfig, since_days: int = 0) -> Dict[str, int]:
    """
    Get total email count for an account across folders.
    
    Args:
        account: IMAP account configuration
        since_days: Only count emails from last N days (0 = all)
        
    Returns:
        Dict with folder names and counts
    """
    folder_counts = {}
    
    try:
        imap = connect_imap(account)
        
        # Get INBOX count
        status, _ = imap.select("INBOX")
        if status == "OK":
            if since_days > 0:
                since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
                status, message_numbers = imap.search(None, f'(SINCE "{since_date}")')
            else:
                status, message_numbers = imap.search(None, 'ALL')
            
            if status == "OK" and message_numbers[0]:
                folder_counts["INBOX"] = len(message_numbers[0].split())
            else:
                folder_counts["INBOX"] = 0
        
        # Find and count Sent folder
        for sent_folder in SENT_FOLDER_NAMES:
            try:
                status, _ = imap.select(sent_folder)
                if status == "OK":
                    if since_days > 0:
                        since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
                        status, message_numbers = imap.search(None, f'(SINCE "{since_date}")')
                    else:
                        status, message_numbers = imap.search(None, 'ALL')
                    
                    if status == "OK" and message_numbers[0]:
                        folder_counts[sent_folder] = len(message_numbers[0].split())
                    else:
                        folder_counts[sent_folder] = 0
                    break  # Found the sent folder
            except Exception:
                continue
        
        imap.logout()
        
    except Exception as e:
        logger.error(f"Error counting emails for {account.email}: {e}")
        folder_counts["error"] = str(e)
    
    return folder_counts


def get_all_accounts_email_count(since_days: int = 0) -> Dict[str, Any]:
    """
    Get email counts for all active accounts.
    
    Returns:
        Dict with account emails as keys, folder counts as values
    """
    accounts = list(imap_accounts_collection.find({"is_active": True}))
    result = {}
    
    for account_doc in accounts:
        account = IMAPAccountConfig(
            email=account_doc["email"],
            password=account_doc.get("password", ""),
            imap_server=account_doc.get("imap_server", "imap.gmail.com"),
            imap_port=account_doc.get("imap_port", 993),
            use_ssl=account_doc.get("use_ssl", True)
        )
        
        if not account.password:
            result[account.email] = {"error": "No password configured"}
            continue
        
        counts = get_total_email_count(account, since_days)
        result[account.email] = counts
    
    return result


# ============== PARALLEL SYNC FUNCTIONS ==============

def download_all_emails_for_account(
    account: IMAPAccountConfig,
    since_days: int = 0,
    progress_callback: Optional[Callable] = None
) -> List[Dict[str, Any]]:
    """
    Download ALL emails from an account (no limit).
    
    Args:
        account: IMAP account configuration
        since_days: Only fetch emails from last N days (0 = all)
        progress_callback: Optional callback(downloaded, total) for progress updates
        
    Returns:
        List of email data dictionaries
    """
    all_emails = []
    
    try:
        imap = connect_imap(account)
        update_progress(account.email, {"status": "connecting", "current_folder": ""})
        
        # Get available folders
        folders_to_sync = ["INBOX"]
        status, folder_list = imap.list()
        if status == "OK":
            for folder_data in folder_list:
                if isinstance(folder_data, bytes):
                    folder_str = folder_data.decode('utf-8', errors='ignore')
                    # Check for sent folder
                    for sent_name in SENT_FOLDER_NAMES:
                        if sent_name.lower() in folder_str.lower():
                            folders_to_sync.append(sent_name)
                            break
        
        # Remove duplicates
        folders_to_sync = list(dict.fromkeys(folders_to_sync))
        
        # Count total emails first
        total_count = 0
        folder_counts = {}
        
        update_progress(account.email, {"status": "counting"})
        
        for folder in folders_to_sync:
            try:
                status, _ = imap.select(folder)
                if status != "OK":
                    continue
                
                if since_days > 0:
                    since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
                    status, message_numbers = imap.search(None, f'(SINCE "{since_date}")')
                else:
                    status, message_numbers = imap.search(None, 'ALL')
                
                if status == "OK" and message_numbers[0]:
                    count = len(message_numbers[0].split())
                    folder_counts[folder] = count
                    total_count += count
                else:
                    folder_counts[folder] = 0
                    
            except Exception as e:
                logger.warning(f"Error counting folder {folder}: {e}")
                continue
        
        update_progress(account.email, {
            "status": "downloading",
            "total_emails": total_count,
            "folder_counts": folder_counts
        })
        
        downloaded_count = 0
        
        # Download from each folder
        for folder in folders_to_sync:
            if folder not in folder_counts or folder_counts[folder] == 0:
                continue
            
            is_sent = folder.upper() != "INBOX"
            direction = "sent" if is_sent else "received"
            
            update_progress(account.email, {"current_folder": folder})
            
            try:
                status, _ = imap.select(folder)
                if status != "OK":
                    continue
                
                if since_days > 0:
                    since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
                    status, message_numbers = imap.search(None, f'(SINCE "{since_date}")')
                else:
                    status, message_numbers = imap.search(None, 'ALL')
                
                if status != "OK" or not message_numbers[0]:
                    continue
                
                message_ids = message_numbers[0].split()
                
                logger.info(f"📧 [{account.email}] Downloading {len(message_ids)} emails from {folder}")
                
                # Download in batches
                for i in range(0, len(message_ids), BATCH_SIZE):
                    # Check for cancellation before each batch
                    if is_sync_cancelled(account.email):
                        logger.info(f"🛑 [{account.email}] Sync cancelled by user")
                        update_progress(account.email, {
                            "status": "cancelled",
                            "downloaded": downloaded_count,
                            "completed_at": datetime.utcnow()
                        })
                        clear_sync_cancellation(account.email)
                        imap.logout()
                        return all_emails
                    
                    batch_ids = message_ids[i:i + BATCH_SIZE]
                    
                    for msg_id in batch_ids:
                        try:
                            status, msg_data = imap.fetch(msg_id, "(RFC822)")
                            if status != "OK":
                                continue
                            
                            raw_email = msg_data[0][1]
                            msg = email.message_from_bytes(raw_email)
                            
                            # Parse email
                            message_id = msg.get("Message-ID", f"{account.email}_{folder}_{msg_id}")
                            subject = decode_email_header(msg.get("Subject", ""))
                            from_header = decode_email_header(msg.get("From", ""))
                            to_header = decode_email_header(msg.get("To", ""))
                            cc_header = decode_email_header(msg.get("Cc", ""))
                            date_str = msg.get("Date", "")
                            body = get_email_body(msg)
                            
                            # Parse sender
                            _, sender_email = parseaddr(from_header)
                            sender_name = from_header.split('<')[0].strip().strip('"') if '<' in from_header else ""
                            
                            # Parse date
                            try:
                                email_date = parsedate_to_datetime(date_str)
                            except:
                                email_date = datetime.now()
                            
                            # Determine contact email based on direction
                            if is_sent:
                                # For sent emails, the contact is the recipient
                                _, contact_email = parseaddr(to_header)
                            else:
                                # For received emails, the contact is the sender
                                contact_email = sender_email
                            
                            email_data = {
                                "message_id": message_id,
                                "subject": subject,
                                "from_email": sender_email,
                                "from_name": sender_name,
                                "to": to_header,
                                "cc": cc_header,
                                "date": email_date.isoformat() if email_date else "",
                                "body": body,
                                "direction": direction,
                                "folder": folder,
                                "contact_email": contact_email,
                                "account_email": account.email
                            }
                            
                            all_emails.append(email_data)
                            downloaded_count += 1
                            
                            # Update progress with current email details for SSE
                            update_progress(account.email, {
                                "downloaded": downloaded_count,
                                "current_email_id": str(message_id)[:50],
                                "current_subject": subject[:100] if subject else ""
                            })
                            
                        except Exception as e:
                            logger.warning(f"Error parsing email {msg_id}: {e}")
                            continue
                    
                    # Update progress after each batch (redundant but ensures consistency)
                    update_progress(account.email, {"downloaded": downloaded_count})
                    
                    if progress_callback:
                        progress_callback(downloaded_count, total_count)
                
                update_progress(account.email, {
                    "folders_completed": list(set(
                        (parallel_sync_progress.find_one({"email": account.email}) or {}).get("folders_completed", []) + [folder]
                    ))
                })
                
            except Exception as e:
                logger.error(f"Error downloading from folder {folder}: {e}")
                continue
        
        imap.logout()
        
        update_progress(account.email, {
            "status": "completed",
            "downloaded": downloaded_count,
            "completed_at": datetime.utcnow()
        })
        
    except Exception as e:
        logger.error(f"Error syncing {account.email}: {e}")
        update_progress(account.email, {
            "status": "error",
            "errors": [str(e)],
            "completed_at": datetime.utcnow()
        })
        raise
    
    return all_emails


def sync_single_account(
    account_doc: Dict[str, Any],
    since_days: int = 0
) -> Dict[str, Any]:
    """
    Sync a single account - wrapper for ThreadPoolExecutor.
    
    Returns:
        Sync result with statistics
    """
    account = IMAPAccountConfig(
        email=account_doc["email"],
        password=account_doc.get("password", ""),
        imap_server=account_doc.get("imap_server", "imap.gmail.com"),
        imap_port=account_doc.get("imap_port", 993),
        use_ssl=account_doc.get("use_ssl", True),
        display_name=account_doc.get("display_name", "")
    )
    
    result = {
        "email": account.email,
        "success": False,
        "total_emails": 0,
        "downloaded": 0,
        "error": None
    }
    
    if not account.password:
        result["error"] = "No password configured"
        return result
    
    try:
        # Initialize progress
        update_progress(account.email, {
            "status": "pending",
            "started_at": datetime.utcnow(),
            "total_emails": 0,
            "downloaded": 0,
            "processed": 0,
            "errors": []
        })
        
        # Download all emails
        emails = download_all_emails_for_account(account, since_days)
        
        result["success"] = True
        result["downloaded"] = len(emails)
        result["emails"] = emails  # Include emails for further processing
        
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error syncing {account.email}: {e}")
    
    return result


def parallel_sync_all_accounts(
    account_emails: Optional[List[str]] = None,
    since_days: int = 0,
    max_parallel: int = MAX_PARALLEL_ACCOUNTS
) -> Dict[str, Any]:
    """
    Sync all (or specified) accounts in parallel.
    Downloads ALL emails with no limit.
    
    Args:
        account_emails: List of specific accounts to sync (None = all active)
        since_days: Only fetch emails from last N days (0 = all)
        max_parallel: Maximum number of parallel sync operations
        
    Returns:
        Overall sync result with per-account statistics
    """
    # Get accounts
    query = {"is_active": True}
    if account_emails:
        query["email"] = {"$in": account_emails}
    
    accounts = list(imap_accounts_collection.find(query))
    
    if not accounts:
        return {
            "success": False,
            "message": "No active accounts found",
            "accounts": {}
        }
    
    logger.info(f"🚀 Starting parallel sync for {len(accounts)} accounts (max {max_parallel} parallel)")
    
    # Store sync session
    sync_session = {
        "_id": datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
        "started_at": datetime.utcnow(),
        "accounts": [a["email"] for a in accounts],
        "since_days": since_days,
        "status": "in_progress"
    }
    gmail_db['sync_sessions'].insert_one(sync_session)
    
    results = {}
    all_emails = []
    
    # Use ThreadPoolExecutor for parallel downloads
    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        future_to_account = {
            executor.submit(sync_single_account, account_doc, since_days): account_doc["email"]
            for account_doc in accounts
        }
        
        for future in as_completed(future_to_account):
            account_email = future_to_account[future]
            try:
                result = future.result()
                results[account_email] = result
                
                if result.get("success") and result.get("emails"):
                    all_emails.extend(result["emails"])
                    logger.info(f"✅ {account_email}: {result['downloaded']} emails downloaded")
                else:
                    logger.warning(f"⚠️ {account_email}: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                logger.error(f"❌ {account_email}: {e}")
                results[account_email] = {
                    "email": account_email,
                    "success": False,
                    "error": str(e)
                }
    
    # Update sync session
    gmail_db['sync_sessions'].update_one(
        {"_id": sync_session["_id"]},
        {
            "$set": {
                "completed_at": datetime.utcnow(),
                "status": "completed",
                "total_emails": len(all_emails),
                "results": {k: {**v, "emails": None} for k, v in results.items()}  # Remove emails from stored results
            }
        }
    )
    
    # Calculate totals
    total_downloaded = sum(r.get("downloaded", 0) for r in results.values())
    successful_accounts = sum(1 for r in results.values() if r.get("success"))
    
    logger.info(f"🏁 Parallel sync complete: {successful_accounts}/{len(accounts)} accounts, {total_downloaded} total emails")
    
    return {
        "success": True,
        "message": f"Downloaded {total_downloaded} emails from {successful_accounts} accounts",
        "total_accounts": len(accounts),
        "successful_accounts": successful_accounts,
        "total_emails": total_downloaded,
        "accounts": {k: {**v, "emails": None} for k, v in results.items()},  # Don't include actual emails in response
        "all_emails": all_emails,  # Include for further processing
        "session_id": sync_session["_id"]
    }


def get_parallel_sync_status() -> Dict[str, Any]:
    """Get current status of all parallel sync operations"""
    progress_docs = list(parallel_sync_progress.find({}))
    
    result = {
        "accounts": [],
        "summary": {
            "total": len(progress_docs),
            "completed": 0,
            "in_progress": 0,
            "errors": 0
        }
    }
    
    for doc in progress_docs:
        doc["_id"] = str(doc["_id"])
        result["accounts"].append(doc)
        
        if doc.get("status") == "completed":
            result["summary"]["completed"] += 1
        elif doc.get("status") == "error":
            result["summary"]["errors"] += 1
        elif doc.get("status") in ["pending", "connecting", "counting", "downloading", "processing"]:
            result["summary"]["in_progress"] += 1
    
    return result


# ============== BACKGROUND SYNC TRIGGER ==============

_sync_lock = threading.Lock()
_sync_running = False


def start_background_parallel_sync(
    account_emails: Optional[List[str]] = None,
    since_days: int = 0
) -> Dict[str, Any]:
    """
    Start parallel sync in background thread.
    
    Returns immediately with session ID for tracking.
    """
    global _sync_running
    
    with _sync_lock:
        if _sync_running:
            return {
                "success": False,
                "message": "Sync already in progress"
            }
        _sync_running = True
    
    def run_sync():
        global _sync_running
        try:
            parallel_sync_all_accounts(account_emails, since_days)
        finally:
            with _sync_lock:
                _sync_running = False
    
    thread = threading.Thread(target=run_sync, daemon=True)
    thread.start()
    
    return {
        "success": True,
        "message": "Background sync started",
        "check_status_endpoint": "/gmail/parallel-sync/status"
    }
