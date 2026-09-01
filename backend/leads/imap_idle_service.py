"""
IMAP IDLE SERVICE - Real-time Email Monitoring
Implements IMAP IDLE for 8 organizational inboxes with real-time email detection.

Features:
- Background threads for each inbox using IMAP IDLE
- Auto-reconnection on connection drops
- New email detection and processing
- Integration with lead creation and RFQ auto-detection
"""

import os
import time
import email
import imaplib
import logging
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

from pymongo import MongoClient
from dotenv import load_dotenv


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    try:
        from ..database import get_client
    except ImportError:
        from database import get_client
    return get_client()


load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
client = _get_pooled_client()
db = client['email_automation']
gmail_db = client['torpedo_gmail']

# Collections
imap_accounts_collection = gmail_db['imap_accounts']
idle_status_collection = gmail_db['idle_status']


# ============== IMAP IDLE WATCHER ==============

@dataclass
class IdleWatcherConfig:
    """Configuration for IDLE watcher"""
    email: str
    password: str
    imap_server: str = "imap.gmail.com"
    imap_port: int = 993
    use_ssl: bool = True
    folders: List[str] = field(default_factory=lambda: ["INBOX"])
    idle_timeout: int = 29 * 60  # 29 minutes (IMAP IDLE timeout is typically 30 min)
    reconnect_delay: int = 5  # seconds


class IMAPIdleWatcher:
    """
    Watches a single IMAP account using IDLE command for real-time email notifications.
    Spawns one thread per folder being watched.
    """
    
    def __init__(
        self,
        config: IdleWatcherConfig,
        on_new_email: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ):
        self.config = config
        self.on_new_email = on_new_email
        self._imap_connections: Dict[str, imaplib.IMAP4_SSL] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._running = False
        self._stop_event = threading.Event()
        
    def start(self) -> bool:
        """Start IDLE watchers for all configured folders"""
        if self._running:
            logger.warning(f"IDLE watcher for {self.config.email} already running")
            return False
        
        self._running = True
        self._stop_event.clear()
        
        for folder in self.config.folders:
            thread = threading.Thread(
                target=self._watch_folder,
                args=(folder,),
                name=f"IDLE-{self.config.email}-{folder}",
                daemon=True
            )
            self._threads[folder] = thread
            thread.start()
            logger.info(f"Started IDLE watcher for {self.config.email}/{folder}")
        
        # Update status in DB
        self._update_status("running")
        return True
    
    def stop(self):
        """Stop all IDLE watchers"""
        self._running = False
        self._stop_event.set()
        
        # Close all IMAP connections
        for folder, imap in self._imap_connections.items():
            try:
                imap.close()
                imap.logout()
            except:
                pass
        
        self._imap_connections.clear()
        self._threads.clear()
        
        # Update status in DB
        self._update_status("stopped")
        logger.info(f"Stopped IDLE watcher for {self.config.email}")
    
    def is_running(self) -> bool:
        return self._running
    
    def _update_status(self, status: str, error: str = None):
        """Update watcher status in MongoDB"""
        idle_status_collection.update_one(
            {"email": self.config.email},
            {
                "$set": {
                    "status": status,
                    "last_update": datetime.utcnow(),
                    "error": error,
                    "folders": self.config.folders
                }
            },
            upsert=True
        )
    
    def _connect_imap(self) -> imaplib.IMAP4_SSL:
        """Create new IMAP connection"""
        if self.config.use_ssl:
            imap = imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port)
        else:
            imap = imaplib.IMAP4(self.config.imap_server, self.config.imap_port)
        
        imap.login(self.config.email, self.config.password)
        return imap
    
    def _watch_folder(self, folder: str):
        """Watch a single folder using IDLE (runs in a thread)"""
        while self._running and not self._stop_event.is_set():
            try:
                imap = self._connect_imap()
                self._imap_connections[folder] = imap
                
                # Select folder
                status, data = imap.select(folder)
                if status != "OK":
                    logger.warning(f"Could not select folder {folder} for {self.config.email}")
                    time.sleep(self.config.reconnect_delay)
                    continue
                
                # Get initial message count
                initial_count = int(data[0])
                logger.info(f"Watching {self.config.email}/{folder} ({initial_count} messages)")
                
                while self._running and not self._stop_event.is_set():
                    try:
                        # Start IDLE
                        imap.send(b'%s IDLE\r\n' % imap._new_tag())
                        
                        # Wait for response (with timeout)
                        start_time = time.time()
                        while time.time() - start_time < self.config.idle_timeout:
                            if self._stop_event.is_set():
                                break
                            
                            # Check for new data (non-blocking with timeout)
                            try:
                                line = imap.readline()
                                if line:
                                    line_str = line.decode('utf-8', errors='ignore')
                                    
                                    # Check for EXISTS notification (new email)
                                    if 'EXISTS' in line_str:
                                        # Extract new message count
                                        parts = line_str.split()
                                        if len(parts) >= 2:
                                            new_count = int(parts[1])
                                            if new_count > initial_count:
                                                # New email(s) arrived!
                                                logger.info(f"New email in {self.config.email}/{folder}")
                                                
                                                # End IDLE to fetch new emails
                                                imap.send(b'DONE\r\n')
                                                time.sleep(0.5)
                                                
                                                # Fetch new emails
                                                self._fetch_new_emails(imap, folder, initial_count, new_count)
                                                initial_count = new_count
                                                break
                                    
                                    # Check for IDLE continuation
                                    if line_str.startswith('+'):
                                        continue
                                    
                            except imaplib.IMAP4.abort:
                                break
                            except Exception as e:
                                if "timed out" not in str(e).lower():
                                    logger.warning(f"IDLE read error: {e}")
                                break
                        
                        # End IDLE before timeout
                        try:
                            imap.send(b'DONE\r\n')
                            time.sleep(0.5)
                        except:
                            pass
                        
                        # NOOP to keep connection alive
                        try:
                            imap.noop()
                        except:
                            break
                        
                    except imaplib.IMAP4.abort as e:
                        logger.warning(f"IMAP abort for {self.config.email}/{folder}: {e}")
                        break
                    except Exception as e:
                        logger.error(f"IDLE error for {self.config.email}/{folder}: {e}")
                        break
                
                # Cleanup connection
                try:
                    imap.close()
                    imap.logout()
                except:
                    pass
                
            except Exception as e:
                logger.error(f"Connection error for {self.config.email}/{folder}: {e}")
                self._update_status("error", str(e))
            
            # Reconnect delay
            if self._running and not self._stop_event.is_set():
                logger.info(f"Reconnecting to {self.config.email}/{folder} in {self.config.reconnect_delay}s")
                time.sleep(self.config.reconnect_delay)
    
    def _fetch_new_emails(self, imap: imaplib.IMAP4_SSL, folder: str, old_count: int, new_count: int):
        """Fetch newly arrived emails"""
        try:
            # Fetch messages from old_count+1 to new_count
            for msg_num in range(old_count + 1, new_count + 1):
                status, msg_data = imap.fetch(str(msg_num).encode(), "(RFC822)")
                if status != "OK":
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Parse email
                email_data = self._parse_email(msg, folder)
                
                if email_data and self.on_new_email:
                    self.on_new_email(self.config.email, email_data)
                    
        except Exception as e:
            logger.error(f"Error fetching new emails: {e}")
    
    def _parse_email(self, msg, folder: str) -> Optional[Dict[str, Any]]:
        """Parse email message into structured data"""
        try:
            # Decode headers
            subject = self._decode_header(msg.get("Subject", ""))
            from_header = self._decode_header(msg.get("From", ""))
            to_header = self._decode_header(msg.get("To", ""))
            cc_header = self._decode_header(msg.get("Cc", ""))
            date_str = msg.get("Date", "")
            message_id = msg.get("Message-ID", "")
            
            # Parse addresses
            _, from_email = parseaddr(from_header)
            to_emails = [parseaddr(addr)[1] for addr in to_header.split(",") if addr.strip()]
            cc_emails = [parseaddr(addr)[1] for addr in cc_header.split(",") if addr.strip()] if cc_header else []
            
            # Get body
            body = self._get_email_body(msg)
            
            # Parse date
            try:
                email_date = parsedate_to_datetime(date_str)
            except:
                email_date = datetime.utcnow()
            
            # Determine direction
            direction = "received" if folder.upper() in ["INBOX"] else "sent"
            
            # Get attachments
            attachments = []
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_disposition() == "attachment":
                        filename = part.get_filename()
                        if filename:
                            attachments.append(self._decode_header(filename))
            
            return {
                "message_id": message_id,
                "subject": subject,
                "from_email": from_email,
                "from_name": self._decode_header(parseaddr(from_header)[0]),
                "to_emails": to_emails,
                "cc_emails": cc_emails,
                "date": email_date,
                "body": body[:5000],
                "body_preview": body[:200],
                "folder": folder,
                "direction": direction,
                "attachments": attachments,
                "inbox_used": self.config.email
            }
            
        except Exception as e:
            logger.error(f"Error parsing email: {e}")
            return None
    
    def _decode_header(self, header_value: str) -> str:
        """Decode email header to string"""
        if not header_value:
            return ""
        
        decoded_parts = decode_header(header_value)
        result = ""
        for content, charset in decoded_parts:
            if isinstance(content, bytes):
                try:
                    result += content.decode(charset or 'utf-8', errors='ignore')
                except:
                    result += content.decode('utf-8', errors='ignore')
            else:
                result += str(content)
        return result
    
    def _get_email_body(self, msg) -> str:
        """Extract plain text body from email message"""
        import re
        body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='ignore')
                        break
                    except:
                        continue
                elif content_type == "text/html" and not body:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        html_body = payload.decode(charset, errors='ignore')
                        body = re.sub(r'<[^>]+>', '', html_body)
                    except:
                        continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or 'utf-8'
                body = payload.decode(charset, errors='ignore')
            except:
                body = str(msg.get_payload())
        
        return body.strip()


# ============== IDLE MANAGER ==============

class IMAPIdleManager:
    """
    Manages IMAP IDLE watchers for all organizational email accounts.
    Provides centralized start/stop and status monitoring.
    """
    
    def __init__(self, on_new_email: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self._watchers: Dict[str, IMAPIdleWatcher] = {}
        self._on_new_email = on_new_email
        self._running = False
    
    def start_all(self) -> Dict[str, Any]:
        """Start IDLE watchers for all active IMAP accounts"""
        accounts = list(imap_accounts_collection.find({"is_active": True}))
        
        started = []
        errors = []
        
        for account in accounts:
            try:
                email_addr = account["email"]
                
                # Skip if already watching
                if email_addr in self._watchers and self._watchers[email_addr].is_running():
                    continue
                
                # Determine folders to watch
                folders = ["INBOX"]
                # Try to add Sent folder
                sent_folders = ["Sent", "Sent Items", "[Gmail]/Sent Mail", "INBOX.Sent"]
                folders.extend(sent_folders[:1])  # Add primary sent folder
                
                config = IdleWatcherConfig(
                    email=email_addr,
                    password=account.get("password", ""),
                    imap_server=account.get("imap_server", "imap.gmail.com"),
                    imap_port=account.get("imap_port", 993),
                    use_ssl=account.get("use_ssl", True),
                    folders=folders
                )
                
                watcher = IMAPIdleWatcher(config, self._on_new_email)
                if watcher.start():
                    self._watchers[email_addr] = watcher
                    started.append(email_addr)
                else:
                    errors.append(f"{email_addr}: Failed to start")
                    
            except Exception as e:
                errors.append(f"{account.get('email', 'unknown')}: {str(e)}")
        
        self._running = len(started) > 0
        
        return {
            "success": len(errors) == 0,
            "started": started,
            "errors": errors,
            "total_watchers": len(self._watchers)
        }
    
    def stop_all(self) -> Dict[str, Any]:
        """Stop all IDLE watchers"""
        stopped = []
        
        for email_addr, watcher in self._watchers.items():
            try:
                watcher.stop()
                stopped.append(email_addr)
            except Exception as e:
                logger.error(f"Error stopping watcher for {email_addr}: {e}")
        
        self._watchers.clear()
        self._running = False
        
        return {
            "success": True,
            "stopped": stopped
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all IDLE watchers"""
        statuses = []
        
        # Get from DB for persistence across restarts
        db_statuses = list(idle_status_collection.find({}))
        
        for status in db_statuses:
            email_addr = status.get("email", "")
            statuses.append({
                "email": email_addr,
                "status": status.get("status", "unknown"),
                "last_update": status.get("last_update"),
                "error": status.get("error"),
                "folders": status.get("folders", []),
                "in_memory": email_addr in self._watchers
            })
        
        return {
            "running": self._running,
            "total_watchers": len(self._watchers),
            "accounts": statuses
        }
    
    def start_account(self, email_addr: str) -> Dict[str, Any]:
        """Start IDLE watcher for a specific account"""
        account = imap_accounts_collection.find_one({"email": email_addr})
        if not account:
            return {"success": False, "error": "Account not found"}
        
        if email_addr in self._watchers and self._watchers[email_addr].is_running():
            return {"success": True, "message": "Already running"}
        
        try:
            folders = ["INBOX", "Sent"]
            
            config = IdleWatcherConfig(
                email=email_addr,
                password=account.get("password", ""),
                imap_server=account.get("imap_server", "imap.gmail.com"),
                imap_port=account.get("imap_port", 993),
                use_ssl=account.get("use_ssl", True),
                folders=folders
            )
            
            watcher = IMAPIdleWatcher(config, self._on_new_email)
            if watcher.start():
                self._watchers[email_addr] = watcher
                return {"success": True, "message": f"Started IDLE for {email_addr}"}
            else:
                return {"success": False, "error": "Failed to start watcher"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def stop_account(self, email_addr: str) -> Dict[str, Any]:
        """Stop IDLE watcher for a specific account"""
        if email_addr not in self._watchers:
            return {"success": False, "error": "Watcher not found"}
        
        try:
            self._watchers[email_addr].stop()
            del self._watchers[email_addr]
            return {"success": True, "message": f"Stopped IDLE for {email_addr}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============== GLOBAL INSTANCE ==============

# This will be initialized with the email processor callback
_idle_manager: Optional[IMAPIdleManager] = None


def get_idle_manager() -> IMAPIdleManager:
    """Get or create the global IDLE manager"""
    global _idle_manager
    if _idle_manager is None:
        _idle_manager = IMAPIdleManager()
    return _idle_manager


def set_email_processor(processor: Callable[[str, Dict[str, Any]], None]):
    """Set the email processor callback for the IDLE manager"""
    global _idle_manager
    _idle_manager = IMAPIdleManager(on_new_email=processor)
