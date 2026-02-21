"""
IMAP EMAIL LEADS EXTRACTION SERVICE
Issue 7: Pull leads from email accounts via IMAP, categorize, and extract contact information

This module uses IMAP/SMTP instead of Gmail API:
1. Connects to email accounts via IMAP
2. Fetches emails from inbox/folders (INBOX + Sent Items)
3. Categorizes emails into segments (promotional, outreach, discovery, etc.)
4. Uses AI to produce summaries of email conversations
5. Extracts and enriches contact information from emails
6. Auto-creates RFQs when rfq_pricing segment detected
7. Cross-inbox deduplication for 8 organizational inboxes
"""

import os
import re
import json
import email
import imaplib
import smtplib
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

from pymongo import MongoClient, ASCENDING
from bson import ObjectId
from dotenv import load_dotenv

# AI classifier for conversation summaries (lazy import to avoid circular imports)
_ai_classifier_module = None

def get_ai_classifier():
    """Lazy import of AI classifier to avoid circular imports"""
    global _ai_classifier_module
    if _ai_classifier_module is None:
        try:
            from . import ai_classifier as ai_module
            _ai_classifier_module = ai_module
        except ImportError as e:
            logger.warning(f"Could not import AI classifier: {e}")
            _ai_classifier_module = False  # Mark as unavailable
    return _ai_classifier_module if _ai_classifier_module else None

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']
gmail_db = client['torpedo_gmail']

# Collections
email_leads_collection = db['email_leads']
email_conversations_collection = db['email_conversations']
leads_enriched_collection = db['leads_enriched']
rfqs_collection = db['rfqs']
imap_accounts_collection = gmail_db['imap_accounts']
email_sync_log_collection = gmail_db['email_sync_log']
import_progress_collection = gmail_db['import_progress']

# Create indexes for deduplication
try:
    email_leads_collection.create_index("email", unique=True)
    email_sync_log_collection.create_index([("message_id", ASCENDING), ("inbox", ASCENDING)], unique=True)
    rfqs_collection.create_index("contact_email")
    rfqs_collection.create_index("rfq_id", unique=True)
except Exception as e:
    logger.warning(f"Index creation warning: {e}")


# ============== EMAIL SEGMENT CATEGORIES ==============

class EmailSegment(str, Enum):
    """Email categorization segments"""
    PROMOTIONAL = "promotional"
    OUTREACH = "outreach"
    DISCOVERY = "discovery"
    PRESENTATION = "presentation"
    RFQ_PRICING = "rfq_pricing"
    NEGOTIATION = "negotiation"
    INVOICE = "invoice"
    BANKING = "banking"
    OTHERS = "others"


# ============== IMAP ACCOUNT MODEL ==============

@dataclass
class IMAPAccount:
    """IMAP Email account configuration"""
    email: str
    display_name: str = ""
    imap_server: str = "imap.gmail.com"
    imap_port: int = 993
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    password: str = ""  # App password for Gmail
    use_ssl: bool = True
    is_active: bool = True
    is_default: bool = False
    created_at: datetime = None
    last_sync: datetime = None
    # Historical import settings
    historical_import_days: int = 30  # Options: 30, 90, 180, 365, 0 (all)
    initial_sync_completed: bool = False
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


# ============== SENT FOLDER NAMES ==============

SENT_FOLDER_NAMES = [
    "Sent",
    "Sent Items", 
    "Sent Mail",
    "[Gmail]/Sent Mail",
    "INBOX.Sent",
    "Sent Messages"
]


# ============== EMAIL LEAD CONTACT ==============

@dataclass
class EmailLeadContact:
    """Contact extracted from email - matches LeadInput schema"""
    name: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    email_status: str = "valid"
    title: str = ""
    linkedin_url: str = ""
    location: str = ""
    added_on: str = ""
    profile_picture: str = ""
    seniority_level: str = ""
    buying_role: str = ""
    gender: str = ""
    company_name: str = ""
    company_domain: str = ""
    company_website: str = ""
    company_employee_count: str = ""
    company_employee_count_range: str = ""
    company_founded: str = ""
    company_industry: str = ""
    company_type: str = ""
    company_headquarters: str = ""
    company_revenue_range: str = ""
    company_linkedin_url: str = ""
    company_crunchbase_url: str = ""
    company_funding_rounds: str = ""
    company_last_funding_round_amount: str = ""
    company_logo_url_primary: str = ""
    company_logo_url_secondary: str = ""
    snippet: str = ""
    source: str = "email_import"
    email_segment: str = ""


# ============== COMMON EMAIL PROVIDERS ==============

EMAIL_PROVIDERS = {
    "gmail.com": {"imap": "imap.gmail.com", "smtp": "smtp.gmail.com", "imap_port": 993, "smtp_port": 587},
    "googlemail.com": {"imap": "imap.gmail.com", "smtp": "smtp.gmail.com", "imap_port": 993, "smtp_port": 587},
    "outlook.com": {"imap": "outlook.office365.com", "smtp": "smtp.office365.com", "imap_port": 993, "smtp_port": 587},
    "hotmail.com": {"imap": "outlook.office365.com", "smtp": "smtp.office365.com", "imap_port": 993, "smtp_port": 587},
    "live.com": {"imap": "outlook.office365.com", "smtp": "smtp.office365.com", "imap_port": 993, "smtp_port": 587},
    "yahoo.com": {"imap": "imap.mail.yahoo.com", "smtp": "smtp.mail.yahoo.com", "imap_port": 993, "smtp_port": 587},
    "icloud.com": {"imap": "imap.mail.me.com", "smtp": "smtp.mail.me.com", "imap_port": 993, "smtp_port": 587},
    "zoho.com": {"imap": "imap.zoho.com", "smtp": "smtp.zoho.com", "imap_port": 993, "smtp_port": 587},
}


def get_provider_settings(email_address: str) -> Dict[str, Any]:
    """Get IMAP/SMTP settings based on email domain"""
    domain = email_address.split("@")[-1].lower()
    if domain in EMAIL_PROVIDERS:
        return EMAIL_PROVIDERS[domain]
    # Default to common settings
    return {
        "imap": f"imap.{domain}",
        "smtp": f"smtp.{domain}",
        "imap_port": 993,
        "smtp_port": 587
    }


# ============== SEGMENT CLASSIFICATION ==============

SEGMENT_KEYWORDS = {
    EmailSegment.PROMOTIONAL: [
        "newsletter", "unsubscribe", "marketing", "promotion", "discount", 
        "offer", "sale", "deals", "subscribe", "campaign", "broadcast"
    ],
    EmailSegment.OUTREACH: [
        "reaching out", "connect", "introduce myself", "partnership",
        "collaboration", "opportunity", "proposal", "interested in",
        "would love to", "quick call", "touch base"
    ],
    EmailSegment.DISCOVERY: [
        "demo", "learn more", "exploring", "considering", "evaluate",
        "research", "information about", "tell me more", "capabilities",
        "features", "how does", "discovery call"
    ],
    EmailSegment.PRESENTATION: [
        "presentation", "deck", "slides", "pitch", "proposal document",
        "overview", "solution", "walkthrough", "showcase"
    ],
    EmailSegment.RFQ_PRICING: [
        "rfq", "request for quote", "quotation", "pricing", "quote",
        "cost", "estimate", "budget", "price list", "rates",
        "proposal", "bid"
    ],
    EmailSegment.NEGOTIATION: [
        "negotiate", "terms", "contract", "agreement", "discount",
        "counter offer", "final offer", "best price", "deal",
        "closing", "sign", "commit"
    ],
    EmailSegment.INVOICE: [
        "invoice", "payment", "due", "billing", "receipt",
        "outstanding", "overdue", "remittance", "pay"
    ],
    EmailSegment.BANKING: [
        "bank", "account", "transfer", "wire", "ach",
        "routing", "swift", "iban", "transaction", "statement"
    ],
}


def classify_email_segment(subject: str, body: str, sender: str) -> EmailSegment:
    """Classify email into a segment based on content"""
    content = f"{subject} {body}".lower()
    
    # Count keyword matches for each segment
    segment_scores = {}
    for segment, keywords in SEGMENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in content)
        if score > 0:
            segment_scores[segment] = score
    
    # Return highest scoring segment
    if segment_scores:
        return max(segment_scores, key=segment_scores.get)
    
    return EmailSegment.OTHERS


# ============== EMAIL PARSING ==============

def decode_email_header(header_value):
    """Decode email header to string"""
    if header_value is None:
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


def get_email_body(msg) -> str:
    """Extract plain text body from email message"""
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
                    # Basic HTML stripping
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


def extract_name_from_email(email_str: str) -> Tuple[str, str, str]:
    """Extract name and email from email string like 'John Doe <john@example.com>'"""
    name, email_addr = parseaddr(email_str)
    
    # Check if the extracted name is actually just the email address (common in some clients)
    if name == email_addr:
        name = ""
        
    is_fallback = False
    if not name and email_addr:
        # Try to get name from email prefix as a LAST resort
        prefix = email_addr.split("@")[0]
        # Skip generic prefixes
        generic_prefixes = ["info", "sales", "support", "admin", "contact", "hello", "mail", "off", "office"]
        if prefix.lower() not in generic_prefixes:
            name = prefix.replace(".", " ").replace("_", " ").title()
            is_fallback = True
    
    # Split into first and last name
    parts = name.split() if name else []
    first_name = parts[0] if parts else ""
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
    
    return name, first_name, last_name


def extract_domain_from_email(email_addr: str) -> str:
    """Extract domain from email address"""
    if "@" in email_addr:
        return email_addr.split("@")[-1].lower()
    return ""


def parse_email_signature(body: str) -> Dict[str, str]:
    """Try to extract information from email signature using regex"""
    info = {
        "name": "",
        "title": "",
        "company": "",
        "phone": "",
        "linkedin": ""
    }
    
    if not body:
        return info
        
    lines = body.split("\n")
    
    # Look for signature patterns in last 20 lines (extended from 15)
    signature_lines = lines[-20:] if len(lines) > 20 else lines
    
    # Common signature start patterns
    sign_off_patterns = [r'^Best regards,?', r'^Regards,?', r'^Thanks,?', r'^Sincerely,?', r'^Kind regards,?', r'^Cheers,?']
    
    for i, line in enumerate(signature_lines):
        line = line.strip()
        if not line:
            continue
            
        # LinkedIn URL
        linkedin_match = re.search(r'linkedin\.com/in/([a-zA-Z0-9\-]+)', line, re.I)
        if linkedin_match and not info["linkedin"]:
            info["linkedin"] = f"https://linkedin.com/in/{linkedin_match.group(1)}"
        
        # Phone number patterns
        phone_match = re.search(r'[\+]?[(]?[0-9]{1,3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}', line)
        if phone_match and not info["phone"]:
            info["phone"] = phone_match.group()
        
        # Title patterns (common job titles)
        title_patterns = [
            r'(CEO|CTO|CFO|COO|CMO|CRO|VP|Director|Manager|Head of|Founder|Partner|President)',
            r'(Sales|Marketing|Engineering|Operations|Product|Business Development|Account Executive)'
        ]
        for pattern in title_patterns:
            if re.search(pattern, line, re.I) and not info["title"]:
                info["title"] = line[:100]  # Take first 100 chars
                break

        # Attempt to find name - it's usually 1-2 lines after a sign-off or right before a title
        for pattern in sign_off_patterns:
            if re.match(pattern, line, re.I):
                # The next non-empty line is likely the name
                for j in range(i + 1, min(i + 4, len(signature_lines))):
                    next_line = signature_lines[j].strip()
                    if next_line and not any(re.match(p, next_line, re.I) for p in sign_off_patterns):
                        # Basic check: name should be 2-3 words, no numbers, not a title
                        if 1 <= len(next_line.split()) <= 4 and not any(char.isdigit() for char in next_line):
                             if not any(re.search(tp, next_line, re.I) for tp in title_patterns):
                                 if not info["name"]:
                                     info["name"] = next_line
                                     break
    
    return info


# ============== IMAP CONNECTION ==============

def connect_imap(account: IMAPAccount) -> imaplib.IMAP4_SSL:
    """Connect to IMAP server"""
    try:
        logger.info(f"📧 [IMAP] Connecting to {account.imap_server}:{account.imap_port} for {account.email}...")
        if account.use_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port)
        else:
            imap = imaplib.IMAP4(account.imap_server, account.imap_port)
        
        imap.login(account.email, account.password)
        logger.info(f"✅ [IMAP] Successfully logged in to {account.email}")
        return imap
    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP login failed for {account.email}: {e}")
        raise ValueError(f"IMAP authentication failed: {str(e)}")
    except Exception as e:
        logger.error(f"IMAP connection failed for {account.email}: {e}")
        raise ValueError(f"IMAP connection failed: {str(e)}")


def fetch_emails_imap(
    account: IMAPAccount,
    folder: str = "INBOX",
    max_emails: int = 100,
    since_days: int = 30,
    segments: List[str] = None
) -> List[Dict[str, Any]]:
    """Fetch emails from IMAP server"""
    emails = []
    
    try:
        imap = connect_imap(account)
        
        # Select folder
        status, _ = imap.select(folder)
        if status != "OK":
            logger.warning(f"Could not select folder {folder}")
            imap.logout()
            return emails
        
        # Calculate date filter
        since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        
        # Search for emails
        status, message_numbers = imap.search(None, f'(SINCE "{since_date}")')
        if status != "OK":
            imap.logout()
            return emails
        
        message_ids = message_numbers[0].split()
        
        # Get latest emails (up to max_emails)
        message_ids = message_ids[-max_emails:] if len(message_ids) > max_emails else message_ids
        
        for msg_id in message_ids:
            try:
                status, msg_data = imap.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Parse email
                subject = decode_email_header(msg.get("Subject", ""))
                from_header = decode_email_header(msg.get("From", ""))
                to_header = decode_email_header(msg.get("To", ""))
                date_str = msg.get("Date", "")
                body = get_email_body(msg)
                
                # Parse sender
                _, sender_email = parseaddr(from_header)
                sender_name, first_name, last_name = extract_name_from_email(from_header)
                
                # Classify segment
                segment = classify_email_segment(subject, body, sender_email)
                
                # Filter by segments if specified
                if segments and segment.value not in segments:
                    continue
                
                # Parse date
                try:
                    email_date = parsedate_to_datetime(date_str)
                except:
                    email_date = datetime.now()
                
                # Extract signature info
                sig_info = parse_email_signature(body)
                
                # Use signature name if header name is missing or generic
                if not sender_name and sig_info.get("name"):
                    sender_name = sig_info["name"]
                    parts = sender_name.split()
                    first_name = parts[0] if parts else ""
                    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                
                email_data = {
                    "message_id": msg.get("Message-ID", str(msg_id)),
                    "subject": subject,
                    "from_email": sender_email,
                    "from_name": sender_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "to": to_header,
                    "date": email_date.isoformat() if email_date else "",
                    "body": body[:5000],  # Limit body length
                    "segment": segment.value,
                    "title": sig_info.get("title", ""),
                    "linkedin_url": sig_info.get("linkedin", ""),
                    "phone": sig_info.get("phone", ""),
                    "domain": extract_domain_from_email(sender_email),
                    "account_email": account.email
                }
                
                emails.append(email_data)
                
            except Exception as e:
                logger.warning(f"Error parsing email {msg_id}: {e}")
                continue
        
        imap.close()
        imap.logout()
        
    except Exception as e:
        logger.error(f"Error fetching emails: {e}")
        raise
    
    return emails


# ============== MULTI-FOLDER SYNC WITH DEDUPLICATION ==============

def fetch_emails_multi_folder(
    account: IMAPAccount,
    folders: List[str] = None,
    max_emails_per_folder: int = 100,
    since_days: int = 30,
    segments: List[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetch emails from multiple folders (INBOX + Sent) with direction tracking.
    
    Args:
        account: IMAP account configuration
        folders: List of folders to fetch from (None = INBOX + Sent)
        max_emails_per_folder: Maximum emails per folder
        since_days: Only fetch emails from last N days
        segments: List of segments to filter (None = all)
        
    Returns:
        List of email data dictionaries with direction field
    """
    if folders is None:
        folders = ["INBOX"] + SENT_FOLDER_NAMES[:1]
    
    all_emails = []
    
    logger.info(f"📬 [IMAP] Starting email fetch for {account.email} (last {since_days} days, max {max_emails_per_folder}/folder)")
    
    try:
        imap = connect_imap(account)
        
        # List available folders to find the correct sent folder
        status, folder_list = imap.list()
        available_folders = []
        if status == "OK":
            for folder_data in folder_list:
                if isinstance(folder_data, bytes):
                    # Parse folder name from response
                    folder_str = folder_data.decode('utf-8', errors='ignore')
                    # Extract folder name (last part after delimiter)
                    parts = folder_str.split('"')
                    if len(parts) >= 2:
                        available_folders.append(parts[-2])
        
        # Find the actual sent folder
        sent_folder = None
        for sf in SENT_FOLDER_NAMES:
            if sf in available_folders or sf.lower() in [f.lower() for f in available_folders]:
                sent_folder = sf
                break
        
        folders_to_fetch = ["INBOX"]
        if sent_folder:
            folders_to_fetch.append(sent_folder)
        
        since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        
        for folder in folders_to_fetch:
            try:
                # Determine direction based on folder
                is_sent = folder.upper() != "INBOX"
                direction = "sent" if is_sent else "received"
                
                logger.info(f"📂 [IMAP] Fetching from folder: {folder} ({direction})")
                
                # Select folder
                status, _ = imap.select(folder)
                if status != "OK":
                    logger.warning(f"Could not select folder {folder}")
                    continue
                
                # Search for emails
                status, message_numbers = imap.search(None, f'(SINCE "{since_date}")')
                if status != "OK":
                    continue
                
                message_ids = message_numbers[0].split()
                total_in_folder = len(message_ids)
                message_ids = message_ids[-max_emails_per_folder:] if len(message_ids) > max_emails_per_folder else message_ids
                logger.info(f"📊 [IMAP] Found {total_in_folder} emails in {folder}, processing {len(message_ids)}")
                
                for msg_id in message_ids:
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
                        
                        # Parse addresses
                        _, from_email = parseaddr(from_header)
                        from_name, first_name, last_name = extract_name_from_email(from_header)
                        to_emails = [parseaddr(addr.strip())[1] for addr in to_header.split(",") if addr.strip()]
                        cc_emails = [parseaddr(addr.strip())[1] for addr in cc_header.split(",") if addr.strip()] if cc_header else []
                        
                        # Classify segment
                        segment = classify_email_segment(subject, body, from_email)
                        
                        # Filter by segments if specified
                        if segments and segment.value not in segments:
                            continue
                        
                        # Parse date
                        try:
                            email_date = parsedate_to_datetime(date_str)
                        except:
                            email_date = datetime.utcnow()
                        
                        # Extract signature info
                        sig_info = parse_email_signature(body)
                        
                        # Use signature name if header name is missing or generic
                        if not from_name and sig_info.get("name"):
                            from_name = sig_info["name"]
                            parts = from_name.split()
                            first_name = parts[0] if parts else ""
                            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                        
                        # Get attachments
                        attachments = []
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_disposition() == "attachment":
                                    filename = part.get_filename()
                                    if filename:
                                        attachments.append(decode_email_header(filename))
                        
                        # Determine the contact email (who we're communicating with)
                        if is_sent:
                            # For sent emails, the contact is the recipient
                            contact_email = to_emails[0] if to_emails else ""
                            contact_name = ""  # We may not have the recipient's name
                        else:
                            # For received emails, the contact is the sender
                            contact_email = from_email
                            contact_name = from_name
                        
                        email_data = {
                            "message_id": message_id,
                            "subject": subject,
                            "from_email": from_email,
                            "from_name": from_name,
                            "first_name": first_name,
                            "last_name": last_name,
                            "to_emails": to_emails,
                            "cc_emails": cc_emails,
                            "date": email_date,
                            "body": body[:5000],
                            "body_preview": body[:200],
                            "segment": segment.value,
                            "direction": direction,
                            "folder": folder,
                            "title": sig_info.get("title", ""),
                            "linkedin_url": sig_info.get("linkedin", ""),
                            "phone": sig_info.get("phone", ""),
                            "contact_email": contact_email,
                            "contact_name": contact_name,
                            "domain": extract_domain_from_email(contact_email),
                            "inbox_used": account.email,
                            "attachments": attachments
                        }
                        
                        all_emails.append(email_data)
                        
                    except Exception as e:
                        logger.warning(f"Error parsing email {msg_id} in {folder}: {e}")
                        continue
                        
            except Exception as e:
                logger.warning(f"Error processing folder {folder}: {e}")
                continue
        
        imap.logout()
        logger.info(f"✅ [IMAP] Completed fetch for {account.email}: {len(all_emails)} emails retrieved")
        
    except Exception as e:
        logger.error(f"❌ [IMAP] Error fetching emails from {account.email}: {e}")
        raise
    
    return all_emails


def is_email_already_processed(message_id: str, inbox: str) -> bool:
    """Check if an email has already been processed (for cross-inbox dedup)"""
    existing = email_sync_log_collection.find_one({
        "message_id": message_id,
        "inbox": inbox
    })
    return existing is not None


def mark_email_processed(message_id: str, inbox: str, contact_email: str):
    """Mark an email as processed in the sync log"""
    try:
        email_sync_log_collection.insert_one({
            "message_id": message_id,
            "inbox": inbox,
            "contact_email": contact_email,
            "processed_at": datetime.utcnow()
        })
    except Exception as e:
        # Duplicate key error is expected for already processed emails
        pass


def generate_rfq_id() -> str:
    """Generate a unique RFQ ID in format RFQ-YYYY-NNNN"""
    year = datetime.utcnow().year
    
    # Find the highest RFQ number for this year
    latest = rfqs_collection.find_one(
        {"rfq_id": {"$regex": f"^RFQ-{year}-"}},
        sort=[("rfq_id", -1)]
    )
    
    if latest:
        # Extract the number and increment
        try:
            last_num = int(latest["rfq_id"].split("-")[-1])
            new_num = last_num + 1
        except:
            new_num = 1
    else:
        new_num = 1
    
    return f"RFQ-{year}-{new_num:04d}"


def extract_rfq_value(body: str, subject: str = "") -> Tuple[Optional[float], str]:
    """
    Extract monetary value from email body using regex and patterns.
    Returns (value, currency)
    """
    text = f"{subject} {body}".lower()
    
    # Currency patterns
    patterns = [
        # USD patterns
        (r'\$\s*([\d,]+(?:\.\d{2})?)\s*(?:usd|dollars?)?', 'USD'),
        (r'([\d,]+(?:\.\d{2})?)\s*(?:usd|dollars?)', 'USD'),
        # INR patterns
        (r'₹\s*([\d,]+(?:\.\d{2})?)', 'INR'),
        (r'([\d,]+(?:\.\d{2})?)\s*(?:inr|rupees?)', 'INR'),
        # EUR patterns
        (r'€\s*([\d,]+(?:\.\d{2})?)', 'EUR'),
        (r'([\d,]+(?:\.\d{2})?)\s*(?:eur|euros?)', 'EUR'),
        # GBP patterns
        (r'£\s*([\d,]+(?:\.\d{2})?)', 'GBP'),
        # Generic with k/m suffixes
        (r'\$\s*([\d.]+)\s*k\b', 'USD'),  # $50k
        (r'\$\s*([\d.]+)\s*m\b', 'USD'),  # $5m
    ]
    
    max_value = None
    detected_currency = 'USD'
    
    for pattern, currency in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                # Clean the number
                num_str = match.replace(',', '').strip()
                value = float(num_str)
                
                # Handle k/m suffixes
                if 'k' in pattern:
                    value *= 1000
                elif 'm' in pattern:
                    value *= 1000000
                
                # Keep the largest value found
                if max_value is None or value > max_value:
                    max_value = value
                    detected_currency = currency
                    
            except ValueError:
                continue
    
    return max_value, detected_currency


def create_or_update_rfq(email_data: Dict[str, Any], lead_id: str = None, rfq_details: Dict[str, Any] = None) -> Optional[str]:
    """
    Create or update an RFQ from email data with AI-extracted details.
    Returns the RFQ ID if created/updated, None otherwise.
    
    Args:
        email_data: Email information (contact_email, subject, body, etc.)
        lead_id: Optional lead ID to link
        rfq_details: AI-extracted RFQ details (loi, ir, country, sample_size, etc.)
    """
    contact_email = email_data.get("contact_email", "")
    if not contact_email:
        return None
    
    # If no lead_id provided, try to find an existing lead by email
    if not lead_id:
        existing_lead = email_leads_collection.find_one({"email": {"$regex": f"^{contact_email}$", "$options": "i"}})
        if existing_lead:
            lead_id = str(existing_lead["_id"])
            logger.info(f"Found existing lead {lead_id} for RFQ contact {contact_email}")
    
    # Extract value from email
    extracted_value, currency = extract_rfq_value(
        email_data.get("body", ""),
        email_data.get("subject", "")
    )
    
    # Use AI-extracted details if available
    rfq_details = rfq_details or {}
    
    # Check if RFQ already exists for this contact
    existing_rfq = rfqs_collection.find_one({"contact_email": contact_email})
    
    source_email = {
        "message_id": email_data.get("message_id", ""),
        "subject": email_data.get("subject", ""),
        "inbox": email_data.get("inbox_used", ""),
        "date": email_data.get("date", datetime.utcnow()),
        "extracted_amount": extracted_value
    }
    
    if existing_rfq:
        # Update existing RFQ
        update_data = {
            "$push": {"source_emails": source_email},
            "$set": {"updated_at": datetime.utcnow()}
        }
        
        # Backfill lead_id if not set on existing RFQ
        if lead_id and not existing_rfq.get("lead_id"):
            update_data["$set"]["lead_id"] = lead_id
            logger.info(f"Backfilling lead_id {lead_id} for existing RFQ {existing_rfq['rfq_id']}")
        
        # Update extracted value if new value is higher
        if extracted_value and (not existing_rfq.get("extracted_value") or extracted_value > existing_rfq.get("extracted_value", 0)):
            update_data["$set"]["extracted_value"] = extracted_value
            update_data["$set"]["extracted_currency"] = currency
        
        # Update AI-extracted fields if not already set
        if rfq_details:
            if rfq_details.get("loi") and not existing_rfq.get("loi"):
                update_data["$set"]["loi"] = rfq_details.get("loi")
            if rfq_details.get("ir") and not existing_rfq.get("ir"):
                update_data["$set"]["ir"] = rfq_details.get("ir")
            if rfq_details.get("country") and not existing_rfq.get("country"):
                update_data["$set"]["country"] = rfq_details.get("country")
            if rfq_details.get("sample_size") and not existing_rfq.get("sample_size"):
                update_data["$set"]["sample_size"] = rfq_details.get("sample_size")
            if rfq_details.get("methodology") and not existing_rfq.get("methodology"):
                update_data["$set"]["methodology"] = rfq_details.get("methodology")
            if rfq_details.get("target_audience") and not existing_rfq.get("target_audience"):
                update_data["$set"]["target_audience"] = rfq_details.get("target_audience")
            if rfq_details.get("study_type") and not existing_rfq.get("study_type"):
                update_data["$set"]["study_type"] = rfq_details.get("study_type")
        
        rfqs_collection.update_one(
            {"_id": existing_rfq["_id"]},
            update_data
        )
        
        return existing_rfq["rfq_id"]
    else:
        # Create new RFQ with AI-extracted details
        rfq_id = generate_rfq_id()
        
        # Determine priority based on urgency indicators
        priority = "medium"
        subject = email_data.get("subject", "").lower()
        if any(word in subject for word in ["urgent", "asap", "rush", "priority"]):
            priority = "high"
        
        rfq_doc = {
            "rfq_id": rfq_id,
            "contact_email": contact_email,
            "lead_id": lead_id,
            "title": rfq_details.get("title") or email_data.get("subject", "RFQ Request"),
            "description": email_data.get("body_preview", ""),
            "extracted_value": extracted_value,
            "extracted_currency": rfq_details.get("currency") or currency,
            "manual_value": None,
            "manual_currency": None,
            # AI-extracted RFQ fields
            "methodology": rfq_details.get("methodology"),
            "loi": rfq_details.get("loi"),
            "ir": rfq_details.get("ir"),
            "sample_size": rfq_details.get("sample_size"),
            "country": rfq_details.get("country"),
            "target_audience": rfq_details.get("target_audience"),
            "timeline": rfq_details.get("timeline"),
            "study_type": rfq_details.get("study_type"),
            "additional_requirements": rfq_details.get("additional_requirements"),
            # Sender info
            "sender_name": email_data.get("sender_name", ""),
            "sender_company": email_data.get("sender_company", ""),
            "sender_title": email_data.get("sender_title", ""),
            # Standard fields
            "source_emails": [source_email],
            "status": "pending",
            "priority": priority,
            "received_date": email_data.get("date", datetime.utcnow()),
            "due_date": None,
            "quoted_date": None,
            "closed_date": None,
            "summary": email_data.get("ai_summary", ""),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "auto"
        }
        
        rfqs_collection.insert_one(rfq_doc)
        logger.info(f"Created RFQ {rfq_id} for {contact_email} - LOI: {rfq_details.get('loi')}, IR: {rfq_details.get('ir')}, Country: {rfq_details.get('country')}, N: {rfq_details.get('sample_size')}")
        
        return rfq_id


# ============== LEAD IMPORT ==============

def import_leads_from_emails(
    account_emails: List[str] = None,
    max_emails: int = 500,
    segments: List[str] = None,
    since_days: int = 30
) -> Dict[str, Any]:
    """
    Import leads from email accounts via IMAP
    
    Args:
        account_emails: List of account emails to fetch from (None = all active)
        max_emails: Maximum emails to process per account
        segments: List of segments to filter (None = all)
        since_days: Only fetch emails from last N days
        
    Returns:
        Dict with import statistics
    """
    # Get accounts
    query = {"is_active": True}
    if account_emails:
        query["email"] = {"$in": account_emails}
    
    accounts = list(imap_accounts_collection.find(query))
    
    if not accounts:
        return {
            "success": False,
            "message": "No active IMAP accounts found",
            "emails_processed": 0,
            "leads_imported": 0,
            "duplicates": 0
        }
    
    total_emails = 0
    total_leads = 0
    total_duplicates = 0
    errors = []
    
    for account_doc in accounts:
        try:
            account = IMAPAccount(
                email=account_doc["email"],
                display_name=account_doc.get("display_name", ""),
                imap_server=account_doc.get("imap_server", "imap.gmail.com"),
                imap_port=account_doc.get("imap_port", 993),
                password=account_doc.get("password", ""),
                use_ssl=account_doc.get("use_ssl", True)
            )
            
            if not account.password:
                errors.append(f"No password configured for {account.email}")
                continue
            
            # Fetch emails
            emails = fetch_emails_imap(
                account=account,
                max_emails=max_emails,
                since_days=since_days,
                segments=segments
            )
            
            total_emails += len(emails)
            
            # Convert to leads
            for email_data in emails:
                # Skip if no valid sender email
                sender_email = email_data.get("from_email", "")
                if not sender_email or sender_email == account.email:
                    continue
                
                # Skip common no-reply addresses
                if any(x in sender_email.lower() for x in ["noreply", "no-reply", "mailer-daemon", "postmaster"]):
                    continue
                
                # Check for duplicate
                existing = email_leads_collection.find_one({"email": sender_email})
                if existing:
                    total_duplicates += 1
                    continue
                
                # Create lead
                lead = EmailLeadContact(
                    email=sender_email,
                    name=email_data.get("from_name", ""),
                    first_name=email_data.get("first_name", ""),
                    last_name=email_data.get("last_name", ""),
                    title=email_data.get("title", ""),
                    linkedin_url=email_data.get("linkedin_url", ""),
                    company_domain=email_data.get("domain", ""),
                    company_website=f"https://{email_data.get('domain', '')}" if email_data.get("domain") else "",
                    snippet=email_data.get("body", "")[:500],
                    email_segment=email_data.get("segment", ""),
                    added_on=datetime.utcnow().isoformat(),
                    source="email_import"
                )
                
                # Insert lead
                email_leads_collection.insert_one(asdict(lead))
                total_leads += 1
            
            # Update last sync time
            imap_accounts_collection.update_one(
                {"email": account.email},
                {"$set": {"last_sync": datetime.utcnow()}}
            )
            
        except Exception as e:
            errors.append(f"Error processing {account_doc['email']}: {str(e)}")
            logger.error(f"Error processing account {account_doc['email']}: {e}")
    
    return {
        "success": True,
        "message": f"Imported {total_leads} leads from {total_emails} emails",
        "emails_processed": total_emails,
        "leads_imported": total_leads,
        "duplicates": total_duplicates,
        "errors": errors if errors else None
    }


# ============== ENHANCED LEAD IMPORT WITH EMAIL THREADS ==============

def process_email_for_lead(email_data: Dict[str, Any], inbox: str) -> Dict[str, Any]:
    """
    Process a single email and create/update lead with email thread.
    Handles cross-inbox deduplication and auto-RFQ creation.
    
    Returns statistics about the operation.
    """
    stats = {
        "new_lead": False,
        "updated_lead": False,
        "rfq_created": False,
        "skipped": False,
        "error": None
    }
    
    contact_email = email_data.get("contact_email", "")
    message_id = email_data.get("message_id", "")
    
    # Skip if no valid contact email
    if not contact_email:
        stats["skipped"] = True
        return stats
    
    # Skip common no-reply addresses
    skip_patterns = ["noreply", "no-reply", "mailer-daemon", "postmaster", "bounce", "notifications"]
    if any(x in contact_email.lower() for x in skip_patterns):
        stats["skipped"] = True
        return stats
    
    # Check if this specific email has been processed (cross-inbox dedup)
    if is_email_already_processed(message_id, inbox):
        stats["skipped"] = True
        return stats
    
    try:
        # Create email thread entry
        email_thread = {
            "message_id": message_id,
            "thread_id": None,  # Could be extracted from email headers
            "subject": email_data.get("subject", ""),
            "body_preview": email_data.get("body_preview", ""),
            "body_full": email_data.get("body", ""),
            "direction": email_data.get("direction", "received"),
            "inbox_used": inbox,
            "from_email": email_data.get("from_email", ""),
            "to_emails": email_data.get("to_emails", []),
            "cc_emails": email_data.get("cc_emails", []),
            "date": email_data.get("date", datetime.utcnow()),
            "attachments": email_data.get("attachments", []),
            "segment": email_data.get("segment", "others")
        }
        
        # Check if lead exists by email
        existing_lead = email_leads_collection.find_one({"email": contact_email})
        
        if existing_lead:
            # Update existing lead with new email thread
            update_result = email_leads_collection.update_one(
                {"email": contact_email},
                {
                    "$push": {"email_threads": email_thread},
                    "$addToSet": {
                        "seen_in_inboxes": inbox,
                        "email_message_ids": message_id
                    },
                    "$set": {
                        "last_email_date": email_data.get("date", datetime.utcnow()),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            stats["updated_lead"] = True
            lead_id = str(existing_lead["_id"])
        else:
            # Create new lead
            lead_doc = {
                "email": contact_email,
                "name": email_data.get("contact_name", "") or email_data.get("from_name", ""),
                "first_name": email_data.get("first_name", ""),
                "last_name": email_data.get("last_name", ""),
                "title": email_data.get("title", ""),
                "linkedin_url": email_data.get("linkedin_url", ""),
                "phone": email_data.get("phone", ""),
                "location": "",
                "company_name": "",
                "company_domain": email_data.get("domain", ""),
                "company_website": f"https://{email_data.get('domain', '')}" if email_data.get("domain") else "",
                "email_segment": email_data.get("segment", ""),
                "source": "email_import",
                "email_threads": [email_thread],
                "seen_in_inboxes": [inbox],
                "email_message_ids": [message_id],
                "last_email_date": email_data.get("date", datetime.utcnow()),
                "conversation_summary": "",
                "rfq_ids": [],
                "added_on": datetime.utcnow(),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                # Enrichment fields (to be filled by AI)
                "enriched_at": None,
                "enrichment_source": None
            }
            
            result = email_leads_collection.insert_one(lead_doc)
            lead_id = str(result.inserted_id)
            stats["new_lead"] = True
        
        # Mark email as processed
        mark_email_processed(message_id, inbox, contact_email)
        
        # Auto-create RFQ if:
        # 1. Segment is rfq_pricing (keyword-based), OR
        # 2. AI detected is_rfq=true, OR
        # 3. Category is 'client' (business inquiry)
        should_create_rfq = (
            email_data.get("segment") == "rfq_pricing" or
            email_data.get("is_rfq") == True or
            email_data.get("category") == "client"
        )
        
        if should_create_rfq:
            # Get AI-extracted RFQ details if available
            rfq_details = email_data.get("rfq_details", {})
            
            # Add sender info to email_data for RFQ
            email_data["sender_name"] = email_data.get("contact_name", "") or email_data.get("from_name", "")
            email_data["sender_company"] = email_data.get("company_name", "")
            email_data["sender_title"] = email_data.get("title", "")
            email_data["ai_summary"] = email_data.get("summary", "")
            
            rfq_id = create_or_update_rfq(email_data, lead_id, rfq_details)
            if rfq_id:
                # Link RFQ to lead
                email_leads_collection.update_one(
                    {"email": contact_email},
                    {"$addToSet": {"rfq_ids": rfq_id}}
                )
                stats["rfq_created"] = True
        
        # Trigger AI conversation summary update (async)
        try:
            ai_classifier = get_ai_classifier()
            if ai_classifier and hasattr(ai_classifier, 'update_lead_conversation_summary'):
                # Only update summary for leads with multiple emails (for efficiency)
                lead = email_leads_collection.find_one({"email": contact_email})
                if lead and len(lead.get("email_threads", [])) > 0:
                    ai_classifier.update_lead_conversation_summary(contact_email)
        except Exception as ai_error:
            logger.warning(f"AI summary update skipped for {contact_email}: {ai_error}")
        
    except Exception as e:
        stats["error"] = str(e)
        logger.error(f"Error processing email for {contact_email}: {e}")
    
    return stats


def import_emails_enhanced(
    account_emails: List[str] = None,
    max_emails_per_folder: int = 250,
    since_days: int = 30,
    segments: List[str] = None,
    trigger_enrichment: bool = True,
    progress_callback: callable = None
) -> Dict[str, Any]:
    """
    Enhanced email import with:
    - Multi-folder sync (INBOX + Sent Items)
    - Cross-inbox deduplication
    - Email thread tracking per lead
    - Auto-RFQ creation for rfq_pricing segment
    - AI enrichment trigger (optional)
    
    Args:
        account_emails: List of account emails to fetch from (None = all active)
        max_emails_per_folder: Maximum emails per folder per account
        since_days: Only fetch emails from last N days
        segments: List of segments to filter (None = all)
        trigger_enrichment: Whether to trigger AI enrichment for new leads
        progress_callback: Optional callback function(processed, total, leads, rfqs) for progress updates
        
    Returns:
        Dict with detailed import statistics
    """
    # Get accounts
    query = {"is_active": True}
    if account_emails:
        query["email"] = {"$in": account_emails}
    
    accounts = list(imap_accounts_collection.find(query))
    
    if not accounts:
        return {
            "success": False,
            "message": "No active IMAP accounts found",
            "stats": {}
        }
    
    total_stats = {
        "emails_processed": 0,
        "new_leads": 0,
        "updated_leads": 0,
        "rfqs_created": 0,
        "skipped": 0,
        "errors": []
    }
    
    for account_doc in accounts:
        try:
            account = IMAPAccount(
                email=account_doc["email"],
                display_name=account_doc.get("display_name", ""),
                imap_server=account_doc.get("imap_server", "imap.gmail.com"),
                imap_port=account_doc.get("imap_port", 993),
                password=account_doc.get("password", ""),
                use_ssl=account_doc.get("use_ssl", True),
                historical_import_days=account_doc.get("historical_import_days", 30)
            )
            
            if not account.password:
                total_stats["errors"].append(f"No password for {account.email}")
                logger.warning(f"⚠️ [Email Import] No password configured for {account.email}, skipping")
                continue
            
            logger.info(f"📥 [Email Import] Fetching emails from {account.email}...")
            
            # Use account's historical import setting if this is initial sync
            effective_days = since_days
            if not account_doc.get("initial_sync_completed", False):
                effective_days = account.historical_import_days if account.historical_import_days > 0 else 365 * 5  # 5 years for "all"
            
            # Fetch emails from multiple folders
            emails = fetch_emails_multi_folder(
                account=account,
                max_emails_per_folder=max_emails_per_folder,
                since_days=effective_days,
                segments=segments
            )
            
            total_emails = len(emails)
            processed_count = 0
            
            logger.info(f"📧 [Email Import] Downloaded {total_emails} emails from {account.email}, now processing and classifying...")
            
            # Process each email
            for email_data in emails:
                result = process_email_for_lead(email_data, account.email)
                
                processed_count += 1
                total_stats["emails_processed"] += 1
                
                if result["new_lead"]:
                    total_stats["new_leads"] += 1
                if result["updated_lead"]:
                    total_stats["updated_leads"] += 1
                if result["rfq_created"]:
                    total_stats["rfqs_created"] += 1
                if result["skipped"]:
                    total_stats["skipped"] += 1
                if result["error"]:
                    total_stats["errors"].append(result["error"])
                
                # Call progress callback every 5 emails or at the end
                if progress_callback and (processed_count % 5 == 0 or processed_count == total_emails):
                    progress_callback(
                        processed_count, 
                        total_emails, 
                        total_stats["new_leads"],
                        total_stats["rfqs_created"]
                    )
            
            # Update sync status
            imap_accounts_collection.update_one(
                {"email": account.email},
                {
                    "$set": {
                        "last_sync": datetime.utcnow(),
                        "initial_sync_completed": True
                    }
                }
            )
            
            logger.info(f"✅ [Email Import] Completed {account.email}: {len(emails)} emails, {total_stats['new_leads']} new leads, {total_stats['updated_leads']} updated")
            
        except Exception as e:
            total_stats["errors"].append(f"{account_doc['email']}: {str(e)}")
            logger.error(f"❌ [Email Import] Error processing account {account_doc['email']}: {e}")
    
    logger.info(f"🏁 [Email Import] All accounts complete: {total_stats['emails_processed']} emails, {total_stats['new_leads']} leads, {total_stats['rfqs_created']} RFQs")
    
    return {
        "success": True,
        "message": f"Processed {total_stats['emails_processed']} emails, created {total_stats['new_leads']} leads, updated {total_stats['updated_leads']} leads, created {total_stats['rfqs_created']} RFQs",
        "stats": total_stats
    }


def run_historical_import(
    account_email: str,
    days: int = 30
) -> Dict[str, Any]:
    """
    Run historical import for a specific account.
    Updates progress in import_progress_collection for UI tracking.
    
    Args:
        account_email: Email address of the account to import from
        days: Number of days to import (0 = all available)
        
    Returns:
        Import statistics
    """
    logger.info(f"🚀 [Historical Import] Starting import for {account_email}, last {days} days")
    
    # Initialize progress tracking
    import_progress_collection.update_one(
        {"email": account_email},
        {
            "$set": {
                "status": "in_progress",
                "started_at": datetime.utcnow(),
                "days_requested": days,
                "processed_count": 0,
                "total_count": 0,
                "leads_created": 0,
                "rfqs_created": 0,
                "error": None,
                "phase": "connecting"
            }
        },
        upsert=True
    )
    
    # Progress callback to update database
    def update_progress(processed, total, leads_created, rfqs_created):
        import_progress_collection.update_one(
            {"email": account_email},
            {
                "$set": {
                    "processed_count": processed,
                    "total_count": total,
                    "leads_created": leads_created,
                    "rfqs_created": rfqs_created,
                    "phase": "classifying" if processed > 0 else "fetching"
                }
            }
        )
    
    try:
        # Update phase to "fetching"
        import_progress_collection.update_one(
            {"email": account_email},
            {"$set": {"phase": "fetching"}}
        )
        
        # Update account's historical import setting
        imap_accounts_collection.update_one(
            {"email": account_email},
            {"$set": {"historical_import_days": days}}
        )
        
        # Run import with progress callback
        result = import_emails_enhanced(
            account_emails=[account_email],
            max_emails_per_folder=1000,  # Higher limit for historical import
            since_days=days if days > 0 else 365 * 10,  # 10 years for "all"
            trigger_enrichment=True,
            progress_callback=update_progress
        )
        
        # Update progress with completion
        import_progress_collection.update_one(
            {"email": account_email},
            {
                "$set": {
                    "status": "completed",
                    "completed_at": datetime.utcnow(),
                    "emails_processed": result.get("stats", {}).get("emails_processed", 0),
                    "leads_created": result.get("stats", {}).get("new_leads", 0),
                    "leads_updated": result.get("stats", {}).get("updated_leads", 0),
                    "rfqs_created": result.get("stats", {}).get("rfqs_created", 0)
                }
            }
        )
        
        stats = result.get("stats", {})
        logger.info(f"✅ [Historical Import] Completed for {account_email}: {stats.get('emails_processed', 0)} emails, {stats.get('new_leads', 0)} new leads")
        
        return result
        
    except Exception as e:
        # Update progress with error
        logger.error(f"❌ [Historical Import] Failed for {account_email}: {e}")
        import_progress_collection.update_one(
            {"email": account_email},
            {
                "$set": {
                    "status": "error",
                    "error": str(e),
                    "completed_at": datetime.utcnow()
                }
            }
        )
        raise


def get_import_progress(account_email: str) -> Optional[Dict[str, Any]]:
    """Get the import progress for a specific account"""
    progress = import_progress_collection.find_one({"email": account_email})
    if progress:
        progress["_id"] = str(progress["_id"])
    return progress


# ============== ACCOUNT MANAGEMENT ==============

def add_imap_account(
    email_address: str,
    password: str,
    display_name: str = "",
    imap_server: str = None,
    imap_port: int = None,
    smtp_server: str = None,
    smtp_port: int = None,
    use_ssl: bool = True,
    is_default: bool = False,
    skip_validation: bool = False
) -> Dict[str, Any]:
    """Add a new IMAP email account
    
    Args:
        skip_validation: If True, save credentials without testing connection first.
                        Useful when IMAP connection is blocked but you want to store credentials.
    """
    
    # Normalize empty strings to None for proper auto-detection
    imap_server = imap_server.strip() if imap_server else None
    smtp_server = smtp_server.strip() if smtp_server else None
    
    # Get provider settings for auto-detection
    provider = get_provider_settings(email_address)
    logger.info(f"Adding IMAP account for {email_address}, provider detected: {provider}")
    
    # Use provider defaults if not specified
    if not imap_server:
        imap_server = provider["imap"]
    if not smtp_server:
        smtp_server = provider["smtp"]
    if imap_port is None:
        imap_port = provider["imap_port"]
    if smtp_port is None:
        smtp_port = provider["smtp_port"]
    
    # Ensure ports have default values as fallback
    imap_port = imap_port or 993
    smtp_port = smtp_port or 587
    
    logger.info(f"Final IMAP settings: server={imap_server}, port={imap_port}")
    
    # Test connection (unless skipped)
    connection_verified = False
    if not skip_validation:
        try:
            test_account = IMAPAccount(
                email=email_address,
                password=password,
                imap_server=imap_server,
                imap_port=imap_port,
                use_ssl=use_ssl
            )
            imap = connect_imap(test_account)
            imap.logout()
            connection_verified = True
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection test failed: {str(e)}. Use 'skip_validation=true' to save anyway."
            }
    else:
        logger.info(f"Skipping IMAP validation for {email_address} - credentials will be saved without testing")
    
    # Check if account exists
    existing = imap_accounts_collection.find_one({"email": email_address})
    if existing:
        return {
            "success": False,
            "message": "Account already exists"
        }
    
    # If setting as default, unset other defaults
    if is_default:
        imap_accounts_collection.update_many({}, {"$set": {"is_default": False}})
    
    # Create account with initial_sync_completed = False to trigger full sync
    account_doc = {
        "email": email_address,
        "display_name": display_name or email_address.split("@")[0],
        "imap_server": imap_server,
        "imap_port": imap_port,
        "smtp_server": smtp_server,
        "smtp_port": smtp_port,
        "password": password,  # Note: In production, encrypt this!
        "use_ssl": use_ssl,
        "is_active": True,
        "is_default": is_default,
        "created_at": datetime.utcnow(),
        "last_sync": None,
        "initial_sync_completed": False,  # Flag for full sync on first run
        "historical_import_days": 0  # 0 = all available emails
    }
    
    imap_accounts_collection.insert_one(account_doc)
    
    # Automatically trigger full historical import in background
    import threading
    def run_initial_sync():
        try:
            logger.info(f"🚀 [Auto-Sync] Starting automatic full sync for new account {email_address}")
            run_historical_import(email_address, days=0)  # 0 = all emails
            logger.info(f"✅ [Auto-Sync] Completed automatic full sync for {email_address}")
        except Exception as e:
            logger.error(f"❌ [Auto-Sync] Failed automatic sync for {email_address}: {e}")
    
    sync_thread = threading.Thread(target=run_initial_sync, daemon=True)
    sync_thread.start()
    
    return {
        "success": True,
        "message": f"Account {email_address} added successfully. Full mailbox sync started in background."
    }


def get_imap_accounts() -> List[Dict[str, Any]]:
    """Get all IMAP accounts (without passwords)"""
    accounts = list(imap_accounts_collection.find({}, {"password": 0}))
    for acc in accounts:
        acc["_id"] = str(acc["_id"])
    return accounts


def remove_imap_account(email_address: str) -> Dict[str, Any]:
    """Remove an IMAP account"""
    result = imap_accounts_collection.delete_one({"email": email_address})
    if result.deleted_count > 0:
        return {"success": True, "message": "Account removed"}
    return {"success": False, "message": "Account not found"}


def test_imap_connection(email_address: str) -> Dict[str, Any]:
    """Test IMAP connection for an account"""
    account_doc = imap_accounts_collection.find_one({"email": email_address})
    if not account_doc:
        return {"success": False, "message": "Account not found"}
    
    try:
        account = IMAPAccount(
            email=account_doc["email"],
            password=account_doc.get("password", ""),
            imap_server=account_doc.get("imap_server", "imap.gmail.com"),
            imap_port=account_doc.get("imap_port", 993),
            use_ssl=account_doc.get("use_ssl", True)
        )
        imap = connect_imap(account)
        
        # Get mailbox info
        status, count = imap.select("INBOX")
        imap.logout()
        
        return {
            "success": True,
            "message": "Connection successful",
            "inbox_status": status
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Connection failed: {str(e)}"
        }


# ============== UTILITY FUNCTIONS ==============

def get_email_leads(
    limit: int = 100,
    skip: int = 0,
    segment: str = None
) -> List[Dict[str, Any]]:
    """Get imported email leads"""
    query = {}
    if segment:
        query["email_segment"] = segment
    
    leads = list(
        email_leads_collection.find(query)
        .sort("added_on", -1)
        .skip(skip)
        .limit(limit)
    )
    
    for lead in leads:
        lead["_id"] = str(lead["_id"])
    
    return leads


def get_segment_statistics() -> Dict[str, int]:
    """Get count of leads by segment"""
    pipeline = [
        {"$group": {"_id": "$email_segment", "count": {"$sum": 1}}}
    ]
    
    results = list(email_leads_collection.aggregate(pipeline))
    
    stats = {seg.value: 0 for seg in EmailSegment}
    for result in results:
        if result["_id"] in stats:
            stats[result["_id"]] = result["count"]
    
    return stats


def detect_aliases_from_sent(email_address: str, max_emails: int = 500) -> Dict[str, Any]:
    """
    Detect aliases by scanning sent emails and finding unique 'From' addresses.
    This helps find send-as aliases configured in the mailbox.
    
    Args:
        email_address: The primary email address
        max_emails: Maximum number of sent emails to scan
        
    Returns:
        Dict with detected aliases and status
    """
    logger.info(f"🔍 [Alias Detection] Scanning sent emails for {email_address}...")
    
    account_doc = imap_accounts_collection.find_one({"email": email_address})
    if not account_doc:
        return {"success": False, "message": "Account not found", "aliases": []}
    
    try:
        account = IMAPAccount(
            email=account_doc["email"],
            password=account_doc.get("password", ""),
            imap_server=account_doc.get("imap_server", "imap.gmail.com"),
            imap_port=account_doc.get("imap_port", 993),
            use_ssl=account_doc.get("use_ssl", True)
        )
        
        imap = connect_imap(account)
        
        # Find the Sent folder
        sent_folder = None
        for folder_name in SENT_FOLDER_NAMES:
            status, _ = imap.select(folder_name)
            if status == "OK":
                sent_folder = folder_name
                break
        
        if not sent_folder:
            imap.logout()
            return {
                "success": False,
                "message": "Could not find Sent folder",
                "aliases": []
            }
        
        # Search for recent sent emails
        since_days = 180  # Look at last 6 months of sent emails
        since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        status, message_numbers = imap.search(None, f'(SINCE "{since_date}")')
        
        if status != "OK":
            imap.logout()
            return {
                "success": False,
                "message": "Failed to search sent folder",
                "aliases": []
            }
        
        message_ids = message_numbers[0].split()
        # Get most recent emails
        message_ids = message_ids[-max_emails:] if len(message_ids) > max_emails else message_ids
        
        logger.info(f"📧 [Alias Detection] Scanning {len(message_ids)} sent emails...")
        
        # Collect unique From addresses
        from_addresses = {}  # email -> {name, count}
        
        for msg_id in message_ids:
            try:
                # Fetch just the From header
                status, msg_data = imap.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
                if status != "OK":
                    continue
                
                header_data = msg_data[0][1]
                if isinstance(header_data, bytes):
                    header_data = header_data.decode('utf-8', errors='ignore')
                
                # Parse From header
                from_match = re.search(r'From:\s*(.+)', header_data, re.IGNORECASE)
                if from_match:
                    from_str = from_match.group(1).strip()
                    name, email_addr = parseaddr(from_str)
                    
                    if email_addr:
                        email_lower = email_addr.lower()
                        if email_lower not in from_addresses:
                            from_addresses[email_lower] = {
                                "email": email_addr,
                                "name": name or "",
                                "count": 0
                            }
                        from_addresses[email_lower]["count"] += 1
                        
            except Exception as e:
                continue
        
        imap.logout()
        
        # Process detected addresses
        primary_email = email_address.lower()
        detected_aliases = []
        
        for email_lower, info in from_addresses.items():
            if email_lower != primary_email:
                detected_aliases.append({
                    "email": info["email"],
                    "name": info["name"],
                    "is_primary": False,
                    "emails_sent": info["count"],
                    "detected_from": "sent_folder"
                })
        
        # Sort by usage count
        detected_aliases.sort(key=lambda x: x["emails_sent"], reverse=True)
        
        logger.info(f"✅ [Alias Detection] Found {len(detected_aliases)} aliases for {email_address}")
        
        # Get existing aliases
        existing_aliases = account_doc.get("aliases", [])
        existing_emails = {a["email"].lower() for a in existing_aliases}
        
        # Find new aliases (not already added)
        new_aliases = [a for a in detected_aliases if a["email"].lower() not in existing_emails]
        
        return {
            "success": True,
            "message": f"Found {len(detected_aliases)} aliases ({len(new_aliases)} new)",
            "aliases": detected_aliases,
            "new_aliases": new_aliases,
            "existing_aliases": existing_aliases,
            "total_scanned": len(message_ids)
        }
        
    except Exception as e:
        logger.error(f"❌ [Alias Detection] Error for {email_address}: {e}")
        return {
            "success": False,
            "message": f"Error detecting aliases: {str(e)}",
            "aliases": []
        }


def add_detected_aliases(email_address: str, aliases_to_add: List[Dict] = None) -> Dict[str, Any]:
    """
    Add detected aliases to an account.
    If aliases_to_add is None, auto-detect and add all.
    
    Args:
        email_address: The primary email address
        aliases_to_add: Optional list of aliases to add. If None, auto-detect.
        
    Returns:
        Result with added aliases
    """
    account_doc = imap_accounts_collection.find_one({"email": email_address})
    if not account_doc:
        return {"success": False, "message": "Account not found"}
    
    # If no aliases provided, detect them
    if aliases_to_add is None:
        detection_result = detect_aliases_from_sent(email_address)
        if not detection_result["success"]:
            return detection_result
        aliases_to_add = detection_result.get("new_aliases", [])
    
    if not aliases_to_add:
        return {"success": True, "message": "No new aliases to add", "added": 0}
    
    # Get existing aliases
    existing_aliases = account_doc.get("aliases", [])
    existing_emails = {a["email"].lower() for a in existing_aliases}
    
    # Add new aliases
    added_count = 0
    for alias in aliases_to_add:
        if alias["email"].lower() not in existing_emails:
            new_alias = {
                "email": alias["email"],
                "name": alias.get("name", ""),
                "is_primary": False,
                "added_at": datetime.utcnow().isoformat(),
                "source": "auto_detected"
            }
            existing_aliases.append(new_alias)
            existing_emails.add(alias["email"].lower())
            added_count += 1
    
    # Update in database
    imap_accounts_collection.update_one(
        {"email": email_address},
        {"$set": {"aliases": existing_aliases}}
    )
    
    logger.info(f"✅ [Alias] Added {added_count} aliases to {email_address}")
    
    return {
        "success": True,
        "message": f"Added {added_count} aliases",
        "added": added_count,
        "total_aliases": len(existing_aliases)
    }


# ============================================================================
# PARALLEL SYNC & AI AGENTS INTEGRATION
# ============================================================================

def run_parallel_import_with_ai(
    account_emails: List[str] = None,
    since_days: int = 0,
    run_agent1: bool = True,
    run_agent2: bool = True,
    max_parallel_accounts: int = 5
) -> Dict[str, Any]:
    """
    Complete email import pipeline with parallel downloads and AI agents.
    
    This is the RECOMMENDED way to import emails:
    1. Parallel download from all accounts (no limits)
    2. Process emails into leads
    3. Run Agent 1 to create summaries
    4. Run Agent 2 to categorize leads
    
    Args:
        account_emails: List of specific accounts (None = all active)
        since_days: Only fetch emails from last N days (0 = all)
        run_agent1: Run AI summary generation
        run_agent2: Run AI categorization
        max_parallel_accounts: Max concurrent downloads
        
    Returns:
        Complete import statistics
    """
    import time
    
    results = {
        "sync": None,
        "leads_processed": 0,
        "agent1": None,
        "agent2": None,
        "success": True
    }
    
    try:
        # Import parallel sync module
        from .parallel_email_sync import parallel_sync_all_accounts
        
        logger.info("🚀 [Full Pipeline] Starting parallel email import with AI agents...")
        
        # Step 1: Parallel sync all accounts
        logger.info("📥 [Step 1] Running parallel email download...")
        sync_result = parallel_sync_all_accounts(
            account_emails=account_emails,
            since_days=since_days,
            max_parallel=max_parallel_accounts
        )
        results["sync"] = {
            "total_accounts": sync_result.get("total_accounts", 0),
            "successful_accounts": sync_result.get("successful_accounts", 0),
            "total_emails": sync_result.get("total_emails", 0)
        }
        
        # Step 2: Process downloaded emails into leads
        all_emails = sync_result.get("all_emails", [])
        if all_emails:
            logger.info(f"📧 [Step 2] Processing {len(all_emails)} emails into leads...")
            
            # Group emails by contact
            emails_by_contact = {}
            for email_data in all_emails:
                contact_email = email_data.get("contact_email", "")
                if contact_email:
                    if contact_email not in emails_by_contact:
                        emails_by_contact[contact_email] = []
                    emails_by_contact[contact_email].append(email_data)
            
            # Process each contact's emails
            for contact_email, emails in emails_by_contact.items():
                try:
                    process_email_for_lead(emails[0], emails[0].get("account_email", ""))
                    
                    # Add to email_threads for AI processing
                    email_leads_collection.update_one(
                        {"email": contact_email},
                        {"$addToSet": {"email_threads": {"$each": emails}}}
                    )
                    results["leads_processed"] += 1
                except Exception as e:
                    logger.warning(f"Error processing lead {contact_email}: {e}")
            
            logger.info(f"✅ [Step 2] Processed {results['leads_processed']} leads")
        
        # Step 3: Run Agent 1 (AI Summaries)
        if run_agent1 and results["leads_processed"] > 0:
            try:
                from .ai_email_agents import agent1_batch_process
                
                logger.info("🤖 [Step 3] Running Agent 1 - AI Summaries...")
                
                # Get leads that need summaries
                leads = list(email_leads_collection.find({
                    "email_threads.0": {"$exists": True},
                    "$or": [
                        {"conversation_summary": {"$exists": False}},
                        {"conversation_summary": ""}
                    ]
                }).limit(100))
                
                if leads:
                    leads_to_process = [
                        {"contact_email": lead["email"], "emails": lead.get("email_threads", [])}
                        for lead in leads
                    ]
                    
                    agent1_results = agent1_batch_process(leads_to_process)
                    successful = sum(1 for r in agent1_results if r.get("success"))
                    
                    results["agent1"] = {
                        "processed": len(agent1_results),
                        "successful": successful
                    }
                    logger.info(f"✅ [Step 3] Agent 1 complete: {successful}/{len(agent1_results)} summaries generated")
                
            except ImportError as e:
                logger.warning(f"Agent 1 not available: {e}")
                results["agent1"] = {"error": str(e)}
        
        # Step 4: Run Agent 2 (Categorization)
        if run_agent2:
            try:
                from .ai_email_agents import run_batch_categorization
                
                logger.info("🏷️ [Step 4] Running Agent 2 - Categorization...")
                
                agent2_result = run_batch_categorization(limit=500)
                
                results["agent2"] = {
                    "categories": len(agent2_result.get("categories", [])),
                    "categorized": len(agent2_result.get("categorized_leads", []))
                }
                
                logger.info(f"✅ [Step 4] Agent 2 complete: {results['agent2']['categorized']} leads categorized")
                
            except ImportError as e:
                logger.warning(f"Agent 2 not available: {e}")
                results["agent2"] = {"error": str(e)}
        
        logger.info("🏁 [Full Pipeline] Complete!")
        
    except ImportError as e:
        logger.error(f"Parallel sync module not available: {e}")
        results["success"] = False
        results["error"] = str(e)
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        results["success"] = False
        results["error"] = str(e)
    
    return results


def get_pipeline_status() -> Dict[str, Any]:
    """
    Get status of parallel sync and AI agents.
    """
    status = {
        "parallel_sync": {"available": False},
        "ai_agents": {"available": False},
        "accounts": [],
        "summary": {}
    }
    
    # Check parallel sync
    try:
        from .parallel_email_sync import get_parallel_sync_status
        sync_status = get_parallel_sync_status()
        status["parallel_sync"] = {
            "available": True,
            **sync_status
        }
    except ImportError:
        pass
    
    # Check AI agents
    try:
        from .ai_email_agents import get_agents_status
        agent_status = get_agents_status()
        status["ai_agents"] = {
            "available": True,
            **agent_status
        }
    except ImportError:
        pass
    
    # Get account info
    accounts = list(imap_accounts_collection.find({"is_active": True}, {"password": 0}))
    for acc in accounts:
        acc["_id"] = str(acc["_id"])
    status["accounts"] = accounts
    
    # Summary stats
    status["summary"] = {
        "total_accounts": len(accounts),
        "total_leads": email_leads_collection.count_documents({}),
        "leads_with_threads": email_leads_collection.count_documents({"email_threads.0": {"$exists": True}}),
        "leads_with_summaries": email_leads_collection.count_documents({"conversation_summary": {"$exists": True, "$ne": ""}}),
        "categorized_leads": email_leads_collection.count_documents({"ai_category_id": {"$exists": True}})
    }
    
    return status
