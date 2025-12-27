"""
IMAP EMAIL LEADS EXTRACTION SERVICE
Issue 7: Pull leads from email accounts via IMAP, categorize, and extract contact information

This module uses IMAP/SMTP instead of Gmail API:
1. Connects to email accounts via IMAP
2. Fetches emails from inbox/folders
3. Categorizes emails into segments (promotional, outreach, discovery, etc.)
4. Uses AI to produce summaries of email conversations
5. Extracts and enriches contact information from emails
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

from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

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
imap_accounts_collection = gmail_db['imap_accounts']


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
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


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
    if not name and email_addr:
        # Try to get name from email prefix
        name = email_addr.split("@")[0].replace(".", " ").replace("_", " ").title()
    
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
    """Try to extract information from email signature"""
    info = {
        "title": "",
        "company": "",
        "phone": "",
        "linkedin": ""
    }
    
    lines = body.split("\n")
    
    # Look for signature patterns in last 15 lines
    signature_lines = lines[-15:] if len(lines) > 15 else lines
    
    for line in signature_lines:
        line = line.strip()
        
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
            r'(Sales|Marketing|Engineering|Operations|Product|Business Development)'
        ]
        for pattern in title_patterns:
            if re.search(pattern, line, re.I) and not info["title"]:
                info["title"] = line[:100]  # Take first 100 chars
                break
    
    return info


# ============== IMAP CONNECTION ==============

def connect_imap(account: IMAPAccount) -> imaplib.IMAP4_SSL:
    """Connect to IMAP server"""
    try:
        if account.use_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port)
        else:
            imap = imaplib.IMAP4(account.imap_server, account.imap_port)
        
        imap.login(account.email, account.password)
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
    is_default: bool = False
) -> Dict[str, Any]:
    """Add a new IMAP email account"""
    
    # Get provider settings if not specified
    if not imap_server or not smtp_server:
        provider = get_provider_settings(email_address)
        imap_server = imap_server or provider["imap"]
        imap_port = imap_port or provider["imap_port"]
        smtp_server = smtp_server or provider["smtp"]
        smtp_port = smtp_port or provider["smtp_port"]
    
    # Test connection
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
    except Exception as e:
        return {
            "success": False,
            "message": f"Connection test failed: {str(e)}"
        }
    
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
    
    # Create account
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
        "last_sync": None
    }
    
    imap_accounts_collection.insert_one(account_doc)
    
    return {
        "success": True,
        "message": f"Account {email_address} added successfully"
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
