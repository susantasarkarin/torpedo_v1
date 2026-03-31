"""
GMAIL LEADS EXTRACTION SERVICE
Issue 7: Pull leads from Gmail emails, categorize, and extract contact information

This module:
1. Pulls emails from multiple Gmail accounts
2. Categorizes emails into segments (promotional, outreach, discovery, etc.)
3. Uses AI to produce summaries of email conversations
4. Extracts and enriches contact information from emails
"""

import os
import re
import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

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
gmail_accounts_collection = gmail_db['accounts']


# ============== EMAIL SEGMENT CATEGORIES ==============

class EmailSegment(str, Enum):
    """Email categorization segments as per Issue 7"""
    PROMOTIONAL = "promotional"
    OUTREACH = "outreach"
    DISCOVERY = "discovery"
    PRESENTATION = "presentation"
    RFQ_PRICING = "rfq_pricing"
    NEGOTIATION = "negotiation"
    INVOICE = "invoice"
    BANKING = "banking"
    OTHERS = "others"


# Keyword patterns for segment classification
SEGMENT_KEYWORDS = {
    EmailSegment.PROMOTIONAL: [
        "newsletter", "subscribe", "unsubscribe", "promotion", "discount", "offer",
        "deal", "sale", "limited time", "special offer", "webinar invite", "event invite"
    ],
    EmailSegment.OUTREACH: [
        "reaching out", "introduction", "connect", "networking", "would like to discuss",
        "interested in", "opportunity", "partnership", "collaboration", "cold email"
    ],
    EmailSegment.DISCOVERY: [
        "discovery call", "learn more", "demo", "meeting request", "schedule a call",
        "introductory call", "initial discussion", "consultation", "assessment"
    ],
    EmailSegment.PRESENTATION: [
        "presentation", "proposal", "deck", "slides", "pitch", "solution overview",
        "product demo", "walkthrough", "capabilities", "case study"
    ],
    EmailSegment.RFQ_PRICING: [
        "quote", "pricing", "rfq", "rfp", "request for quote", "quotation",
        "price list", "cost", "estimate", "budget", "rates", "fees"
    ],
    EmailSegment.NEGOTIATION: [
        "negotiate", "counter offer", "terms", "conditions", "contract",
        "agreement", "sign", "approve", "revise", "discussion", "final offer"
    ],
    EmailSegment.INVOICE: [
        "invoice", "bill", "payment", "receipt", "amount due", "pay",
        "remittance", "statement", "balance", "overdue"
    ],
    EmailSegment.BANKING: [
        "bank", "wire transfer", "account details", "swift", "iban", "routing",
        "transaction", "credit", "debit", "financial"
    ]
}


@dataclass
class EmailLeadContact:
    """Contact information extracted from email"""
    # Core fields
    name: str
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    email_status: str = "Valid"  # From email so assumed valid
    title: str = ""
    linkedin_url: str = ""
    location: str = ""
    added_on: str = ""
    profile_picture: str = ""
    seniority_level: str = ""
    buying_role: str = ""
    gender: str = ""
    
    # Company fields
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
    
    # Email-specific metadata
    source_email_id: str = ""
    source_account: str = ""
    segment: str = ""
    conversation_summary: str = ""
    last_email_date: str = ""
    email_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConversationSummary:
    """Summary of an email conversation thread"""
    thread_id: str
    participants: List[str]
    subject: str
    segment: str
    email_count: int
    first_email_date: str
    last_email_date: str
    summary: str
    key_points: List[str]
    action_items: List[str]
    contacts_extracted: List[str]


# ============== SEGMENT CLASSIFICATION ==============

def classify_email_segment(subject: str, body: str) -> EmailSegment:
    """
    Classify an email into one of the predefined segments.
    Returns the most likely segment based on keyword matching.
    """
    text = f"{subject} {body}".lower()
    
    # Score each segment based on keyword matches
    scores = {}
    for segment, keywords in SEGMENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        scores[segment] = score
    
    # Return segment with highest score, default to OTHERS
    if max(scores.values()) > 0:
        return max(scores, key=scores.get)
    
    return EmailSegment.OTHERS


# ============== CONTACT EXTRACTION ==============

def extract_name_from_email(email_address: str, display_name: str = "") -> Tuple[str, str, str]:
    """
    Extract full name, first name, and last name from email.
    Returns: (full_name, first_name, last_name)
    """
    # First try display name
    if display_name and display_name.strip():
        name = display_name.strip().strip('"').strip("'")
        # Remove any email in parentheses
        name = re.sub(r'\s*<[^>]+>\s*', '', name)
        name = re.sub(r'\s*\([^)]+\)\s*', '', name)
        name = name.strip()
        
        if name:
            parts = name.split()
            if len(parts) >= 2:
                return name, parts[0], " ".join(parts[1:])
            return name, parts[0] if parts else "", ""
    
    # Fall back to email local part
    local_part = email_address.split('@')[0] if '@' in email_address else email_address
    
    # Try to split on common separators
    for sep in ['.', '_', '-']:
        if sep in local_part:
            parts = local_part.split(sep)
            if len(parts) >= 2:
                first = parts[0].capitalize()
                last = ' '.join(p.capitalize() for p in parts[1:])
                return f"{first} {last}", first, last
    
    return local_part.capitalize(), local_part.capitalize(), ""


def extract_domain_from_email(email_address: str) -> str:
    """Extract domain from email address."""
    if '@' in email_address:
        return email_address.split('@')[1].lower()
    return ""


def extract_company_from_domain(domain: str) -> str:
    """
    Try to extract company name from email domain.
    Removes common email providers.
    """
    common_providers = [
        'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com',
        'icloud.com', 'mail.com', 'protonmail.com', 'zoho.com', 'yandex.com'
    ]
    
    if domain.lower() in common_providers:
        return ""
    
    # Extract company name from domain
    company = domain.split('.')[0] if '.' in domain else domain
    return company.capitalize()


def parse_email_signature(body: str) -> Dict[str, str]:
    """
    Try to extract information from email signature.
    Returns dict with extracted fields.
    """
    info = {}
    
    # Common patterns in signatures
    patterns = {
        'title': [
            r'(?:title|position|role):\s*([^\n]+)',
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*[|\-]\s*[A-Z]',
        ],
        'phone': [
            r'(?:phone|tel|mobile|cell)[\s:]*([+\d\s\-().]+)',
            r'\+\d{1,3}[\s\-]?\d{2,4}[\s\-]?\d{3,4}[\s\-]?\d{3,4}',
        ],
        'linkedin': [
            r'linkedin\.com/in/([a-zA-Z0-9\-]+)',
            r'(?:linkedin|li)[\s:]*(?:linkedin\.com/in/)?([a-zA-Z0-9\-]+)',
        ],
        'location': [
            r'(?:location|address|based in)[\s:]*([^\n]+)',
        ],
        'company': [
            r'(?:company|org|organization)[\s:]*([^\n]+)',
        ]
    }
    
    for field, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, body, re.IGNORECASE | re.MULTILINE)
            if match:
                info[field] = match.group(1).strip()
                break
    
    return info


# ============== EMAIL LEAD PROCESSING ==============

def process_email_to_lead(
    email_data: Dict[str, Any],
    account_id: str
) -> Optional[EmailLeadContact]:
    """
    Process a single email and extract lead contact information.
    """
    try:
        sender = email_data.get('sender', '')
        sender_name = email_data.get('sender_name', '')
        subject = email_data.get('subject', '')
        body = email_data.get('body_text', email_data.get('body', ''))
        email_date = email_data.get('date', datetime.utcnow().isoformat())
        thread_id = email_data.get('thread_id', '')
        email_id = email_data.get('id', '')
        
        # Extract email address
        email_match = re.search(r'<([^>]+@[^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', sender)
        email_address = email_match.group(1) or email_match.group(2) if email_match else sender
        
        if not email_address or '@' not in email_address:
            return None
        
        # Extract name
        full_name, first_name, last_name = extract_name_from_email(email_address, sender_name)
        
        # Extract domain and company
        domain = extract_domain_from_email(email_address)
        company_name = extract_company_from_domain(domain)
        
        # Parse signature for additional info
        signature_info = parse_email_signature(body)
        
        # Classify segment
        segment = classify_email_segment(subject, body)
        
        # Build LinkedIn URL if found
        linkedin_url = ""
        if signature_info.get('linkedin'):
            linkedin_id = signature_info['linkedin']
            if not linkedin_id.startswith('http'):
                linkedin_url = f"https://linkedin.com/in/{linkedin_id}"
            else:
                linkedin_url = linkedin_id
        
        # Create lead contact
        lead = EmailLeadContact(
            name=full_name,
            first_name=first_name,
            last_name=last_name,
            email=email_address,
            email_status="Valid",
            title=signature_info.get('title', ''),
            linkedin_url=linkedin_url,
            location=signature_info.get('location', ''),
            added_on=datetime.utcnow().isoformat(),
            company_name=company_name or signature_info.get('company', ''),
            company_domain=domain,
            company_website=f"https://{domain}" if domain else "",
            source_email_id=email_id,
            source_account=account_id,
            segment=segment.value,
            last_email_date=email_date,
            email_count=1
        )
        
        return lead
        
    except Exception as e:
        logger.error(f"Error processing email to lead: {e}")
        return None


# ============== AI SUMMARY (using OpenAI) ==============

def generate_conversation_summary(
    emails: List[Dict[str, Any]],
    use_ai: bool = True
) -> ConversationSummary:
    """
    Generate a summary of an email conversation thread.
    Uses OpenAI if available, falls back to basic extraction.
    """
    if not emails:
        return None
    
    # Sort emails by date
    sorted_emails = sorted(emails, key=lambda x: x.get('date', ''))
    
    # Extract participants
    participants = set()
    for email in sorted_emails:
        sender = email.get('sender', '')
        email_match = re.search(r'<([^>]+@[^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+)', sender)
        if email_match:
            participants.add(email_match.group(1) or email_match.group(2))
        for recipient in email.get('recipients', []):
            if '@' in recipient:
                participants.add(recipient)
    
    first_email = sorted_emails[0]
    last_email = sorted_emails[-1]
    
    # Classify segment
    all_text = " ".join([
        f"{e.get('subject', '')} {e.get('body_text', '')}" 
        for e in sorted_emails
    ])
    segment = classify_email_segment(first_email.get('subject', ''), all_text)
    
    # Generate summary
    summary = ""
    key_points = []
    action_items = []
    
    if use_ai:
        try:
            summary, key_points, action_items = _generate_ai_summary(sorted_emails)
        except Exception as e:
            logger.warning(f"AI summary failed, using basic extraction: {e}")
            summary, key_points, action_items = _generate_basic_summary(sorted_emails)
    else:
        summary, key_points, action_items = _generate_basic_summary(sorted_emails)
    
    return ConversationSummary(
        thread_id=first_email.get('thread_id', ''),
        participants=list(participants),
        subject=first_email.get('subject', 'No Subject'),
        segment=segment.value,
        email_count=len(sorted_emails),
        first_email_date=first_email.get('date', ''),
        last_email_date=last_email.get('date', ''),
        summary=summary,
        key_points=key_points,
        action_items=action_items,
        contacts_extracted=[p for p in participants]
    )


def _generate_basic_summary(emails: List[Dict[str, Any]]) -> Tuple[str, List[str], List[str]]:
    """Generate basic summary without AI."""
    if not emails:
        return "", [], []
    
    first_email = emails[0]
    last_email = emails[-1]
    
    summary = f"Email thread with {len(emails)} messages. "
    summary += f"Subject: {first_email.get('subject', 'No Subject')}. "
    summary += f"Started on {first_email.get('date', 'unknown date')}. "
    
    if len(emails) > 1:
        summary += f"Last reply on {last_email.get('date', 'unknown date')}."
    
    key_points = [f"Thread contains {len(emails)} email(s)"]
    action_items = []
    
    # Look for common action keywords in the last email
    last_body = last_email.get('body_text', '').lower()
    action_keywords = ['please', 'could you', 'can you', 'let me know', 'schedule', 'send', 'review']
    for keyword in action_keywords:
        if keyword in last_body:
            action_items.append(f"Follow up needed (found '{keyword}' in last email)")
            break
    
    return summary, key_points, action_items


def _generate_ai_summary(emails: List[Dict[str, Any]], source: str = "background") -> Tuple[str, List[str], List[str]]:
    """
    Generate AI-powered summary using Gemini.
    """
    try:
        from ai_governance import get_gemini_gateway  # type: ignore
        gw = get_gemini_gateway()

        first_email = emails[0] if emails else {}
        subject = first_email.get('subject', '')
        thread_id = first_email.get('thread_id', first_email.get('id', 'thread'))

        body_parts = []
        for email in emails:
            sender = email.get('sender_name', email.get('sender', ''))
            date = email.get('date', '')
            body = email.get('body_text', '')[:400]
            body_parts.append(f"From: {sender} ({date})\n{body}")
        combined_body = "\n---\n".join(body_parts)

        result = gw.summarize_email(
            email_id=thread_id,
            subject=subject,
            body=combined_body,
            max_length=300,
        )

        if result.get('success'):
            return (
                result.get('summary', ''),
                result.get('key_points', []),
                [],
            )
        return "", [], []
    except Exception as e:
        logger.warning(f"AI summary (Gemini) failed: {e}")
        return "", [], []


# ============== MAIN SERVICE FUNCTIONS ==============

def get_gmail_accounts() -> List[Dict[str, Any]]:
    """Get all configured Gmail accounts."""
    accounts = list(gmail_accounts_collection.find({}, {'_id': 0}))
    return accounts


def import_leads_from_gmail(
    account_ids: Optional[List[str]] = None,
    max_emails: int = 100,
    date_from: Optional[str] = None,
    segments: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Import leads from Gmail accounts.
    
    Args:
        account_ids: List of account IDs to process (None for all)
        max_emails: Maximum emails to process per account
        date_from: Only process emails after this date (ISO format)
        segments: Filter to specific segments
    
    Returns:
        Import statistics
    """
    stats = {
        'accounts_processed': 0,
        'emails_processed': 0,
        'leads_extracted': 0,
        'leads_imported': 0,
        'duplicates': 0,
        'errors': []
    }
    
    # Get accounts to process
    query = {}
    if account_ids:
        query['account_id'] = {'$in': account_ids}
    
    accounts = list(gmail_accounts_collection.find(query))
    
    if not accounts:
        stats['errors'].append("No Gmail accounts found")
        return stats
    
    for account in accounts:
        account_id = account.get('account_id', str(account.get('_id', '')))
        
        try:
            # Get cached emails for this account
            email_query = {'account_id': account_id}
            if date_from:
                email_query['date'] = {'$gte': date_from}
            
            emails = list(gmail_db['email_cache'].find(email_query).limit(max_emails))
            
            stats['accounts_processed'] += 1
            stats['emails_processed'] += len(emails)
            
            for email_data in emails:
                lead = process_email_to_lead(email_data, account_id)
                
                if lead:
                    # Filter by segment if specified
                    if segments and lead.segment not in segments:
                        continue
                    
                    stats['leads_extracted'] += 1
                    
                    # Check for duplicate
                    existing = email_leads_collection.find_one({'email': lead.email})
                    if existing:
                        # Update existing with new conversation data
                        email_leads_collection.update_one(
                            {'email': lead.email},
                            {
                                '$inc': {'email_count': 1},
                                '$set': {'last_email_date': lead.last_email_date}
                            }
                        )
                        stats['duplicates'] += 1
                    else:
                        # Insert new lead
                        email_leads_collection.insert_one(lead.to_dict())
                        stats['leads_imported'] += 1
                        
        except Exception as e:
            logger.error(f"Error processing account {account_id}: {e}")
            stats['errors'].append(f"Account {account_id}: {str(e)}")
    
    return stats


def get_email_leads(
    segment: Optional[str] = None,
    account_id: Optional[str] = None,
    page: int = 1,
    limit: int = 50
) -> Tuple[List[Dict], int]:
    """
    Get email leads with filtering and pagination.
    """
    query = {}
    if segment:
        query['segment'] = segment
    if account_id:
        query['source_account'] = account_id
    
    total = email_leads_collection.count_documents(query)
    skip = (page - 1) * limit
    
    leads = list(email_leads_collection.find(query)
                 .skip(skip)
                 .limit(limit)
                 .sort('last_email_date', -1))
    
    # Convert ObjectId to string
    for lead in leads:
        lead['_id'] = str(lead['_id'])
    
    return leads, total


def get_conversation_summaries(
    account_id: Optional[str] = None,
    segment: Optional[str] = None,
    page: int = 1,
    limit: int = 20
) -> Tuple[List[Dict], int]:
    """
    Get email conversation summaries.
    """
    query = {}
    if account_id:
        query['source_account'] = account_id
    if segment:
        query['segment'] = segment
    
    total = email_conversations_collection.count_documents(query)
    skip = (page - 1) * limit
    
    conversations = list(email_conversations_collection.find(query)
                         .skip(skip)
                         .limit(limit)
                         .sort('last_email_date', -1))
    
    for conv in conversations:
        conv['_id'] = str(conv['_id'])
    
    return conversations, total


def get_segment_statistics() -> Dict[str, int]:
    """Get lead counts by segment."""
    pipeline = [
        {'$group': {'_id': '$segment', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}}
    ]
    
    results = list(email_leads_collection.aggregate(pipeline))
    return {r['_id']: r['count'] for r in results if r['_id']}
