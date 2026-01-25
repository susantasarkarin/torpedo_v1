"""
CANONICAL LEAD INGESTION MODULE
================================
Single entry point for ALL lead sources.
Every lead from Gmail, CSV, or Web Search MUST pass through ingest_lead().

NO EXCEPTIONS. NO BYPASSES.
"""

import os
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_db = _client['email_automation']
leads_raw = _db['leads_raw']
ingestion_log = _db['ingestion_log']

# Ensure unique index on email (THE deduplication key)
try:
    leads_raw.create_index([("email", ASCENDING)], unique=True, sparse=True)
    logger.info("Unique index on email created/verified")
except Exception as e:
    logger.warning(f"Could not create email index: {e}")


def log_ingestion_event(email: str, source: str, action: str, lead_id: str = None, error: str = None):
    """Log ingestion events for monitoring and debugging."""
    try:
        ingestion_log.insert_one({
            'email': email,
            'source': source,
            'action': action,  # 'inserted', 'updated', 'skipped', 'error'
            'lead_id': lead_id,
            'error': error,
            'timestamp': datetime.utcnow()
        })
    except Exception as e:
        logger.warning(f"Could not log ingestion event: {e}")


# =============================================================================
# CANONICAL LEAD SCHEMA
# =============================================================================

REQUIRED_FIELDS = {'email'}
ENRICHMENT_REQUIRED_FIELDS = {'first_name', 'company'}  # If missing, trigger enrichment

VALID_SOURCES = {'gmail', 'websearch', 'csv'}
VALID_CLASSIFICATIONS = {'client', 'vendor', 'irrelevant', 'unknown', 'pending'}


def normalize_email(email: str) -> Optional[str]:
    """
    Normalize email: lowercase, trim, validate format.
    Returns None if invalid.
    """
    if not email:
        return None
    
    email = email.lower().strip()
    
    # Basic email validation
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return None
    
    return email


def normalize_payload(payload: Dict[str, Any], source: str, source_detail: str) -> Dict[str, Any]:
    """
    Normalize incoming payload to canonical schema.
    """
    email = normalize_email(payload.get('email', ''))
    
    if not email:
        raise ValueError("Invalid or missing email address")
    
    # Extract and clean name fields
    first_name = (payload.get('first_name') or '').strip() or None
    last_name = (payload.get('last_name') or '').strip() or None
    
    # If we have a full name but not first/last, try to split
    if not first_name and payload.get('name'):
        name = payload.get('name', '').strip()
        parts = name.split(' ', 1)
        first_name = parts[0] if parts else None
        last_name = parts[1] if len(parts) > 1 else None
    
    now = datetime.utcnow()
    
    return {
        'email': email,
        'first_name': first_name,
        'last_name': last_name,
        'name': payload.get('name', '').strip() or f"{first_name or ''} {last_name or ''}".strip() or None,
        'company': (payload.get('company') or payload.get('company_name') or '').strip() or None,
        'company_domain': (payload.get('company_domain') or '').strip() or None,
        'title': (payload.get('title') or payload.get('job_title') or '').strip() or None,
        'phone': (payload.get('phone') or '').strip() or None,
        'linkedin_url': (payload.get('linkedin_url') or payload.get('linkedin') or '').strip() or None,
        'location': (payload.get('location') or '').strip() or None,
        'source': source if source in VALID_SOURCES else 'unknown',
        'source_detail': source_detail,
        'classification': 'pending',
        'classification_confidence': 0.0,
        'enrichment_status': 'pending',
        'created_at': now,
        'updated_at': now,
    }


def needs_enrichment(lead: Dict[str, Any]) -> bool:
    """
    Check if lead needs enrichment.
    Returns True if any enrichment-required field is missing.
    """
    for field in ENRICHMENT_REQUIRED_FIELDS:
        if not lead.get(field):
            return True
    return False


def deduplicate_and_merge(existing: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge new data into existing lead.
    Rule: Never overwrite non-null with null.
    """
    merged = existing.copy()
    
    for key, new_val in new_data.items():
        if key in ('_id', 'created_at'):
            continue  # Never overwrite these
        
        if key == 'updated_at':
            merged[key] = new_val
            continue
        
        existing_val = merged.get(key)
        
        # Only update if new value is non-null AND (existing is null OR key is 'source_detail')
        if new_val is not None and (existing_val is None or key == 'source_detail'):
            merged[key] = new_val
    
    return merged


# =============================================================================
# AI CLASSIFICATION (Wrapper)
# =============================================================================

def classify_lead_ai(lead: Dict[str, Any]) -> Tuple[str, float]:
    """
    Call AI classification for a lead.
    Returns (classification, confidence).
    """
    try:
        from .ai_classifier import classify_lead as ai_classify, LeadRaw
        
        # Build LeadRaw object for classifier
        lead_obj = LeadRaw(
            name=lead.get('name') or '',
            title=lead.get('title') or '',
            linkedin_url=lead.get('linkedin_url') or '',
            snippet=lead.get('source_detail') or '',
            source=lead.get('source') or 'unknown',
            location=lead.get('location'),
            email=lead.get('email'),
            company_name=lead.get('company'),
        )
        
        result, log = ai_classify(lead_obj, source='ingestion')
        
        if result:
            # Map classifier output to simple classification
            # The classifier returns persona/department - we simplify to client/vendor/irrelevant
            persona = getattr(result, 'persona', None)
            if persona and persona.value in ('Decision Maker', 'Champion', 'Influencer'):
                return 'client', result.confidence_score
            elif persona and persona.value == 'Blocker':
                return 'vendor', result.confidence_score
            else:
                return 'unknown', result.confidence_score
        
        return 'unknown', 0.0
        
    except Exception as e:
        logger.error(f"AI classification failed: {e}")
        return 'unknown', 0.0


# =============================================================================
# MAIN INGESTION FUNCTION
# =============================================================================

def ingest_lead(
    payload: Dict[str, Any],
    source: str,
    source_detail: str,
    skip_classification: bool = False
) -> Dict[str, Any]:
    """
    CANONICAL LEAD INGESTION FUNCTION
    ==================================
    ALL lead sources MUST call this function.
    
    Pipeline:
    1. normalize_payload
    2. deduplicate_by_email
    3. validate_fields
    4. conditional_enrichment
    5. AI_classification
    6. insert_into_leads_raw
    
    Args:
        payload: Raw lead data from source
        source: 'gmail' | 'websearch' | 'csv'
        source_detail: Additional context (e.g., 'email_extraction', 'linkedin_search')
        skip_classification: Skip AI classification (for batch processing)
    
    Returns:
        {
            'success': bool,
            'action': 'inserted' | 'updated' | 'skipped',
            'lead_id': str | None,
            'email': str,
            'error': str | None
        }
    """
    result = {
        'success': False,
        'action': None,
        'lead_id': None,
        'email': None,
        'error': None
    }
    
    try:
        # Step 1: Normalize payload
        normalized = normalize_payload(payload, source, source_detail)
        result['email'] = normalized['email']
        
    except ValueError as e:
        result['error'] = str(e)
        logger.warning(f"Lead rejected: {e}")
        return result
    
    try:
        # Step 2: Check for existing lead (deduplication by email)
        existing = leads_raw.find_one({'email': normalized['email']})
        
        if existing:
            # Merge data (never overwrite non-null with null)
            merged = deduplicate_and_merge(existing, normalized)
            merged['updated_at'] = datetime.utcnow()
            
            # Step 3: Conditional enrichment
            if needs_enrichment(merged):
                merged['enrichment_status'] = 'needed'
            else:
                merged['enrichment_status'] = 'skipped'
            
            # Step 4: AI classification (if not already classified and not skipped)
            if not skip_classification and merged.get('classification') == 'pending':
                classification, confidence = classify_lead_ai(merged)
                merged['classification'] = classification
                merged['classification_confidence'] = confidence
            
            # Update existing lead
            leads_raw.update_one(
                {'_id': existing['_id']},
                {'$set': merged}
            )
            
            result['success'] = True
            result['action'] = 'updated'
            result['lead_id'] = str(existing['_id'])
            
        else:
            # New lead
            
            # Step 3: Conditional enrichment
            if needs_enrichment(normalized):
                normalized['enrichment_status'] = 'needed'
            else:
                normalized['enrichment_status'] = 'skipped'
            
            # Step 4: AI classification (if not skipped)
            if not skip_classification:
                classification, confidence = classify_lead_ai(normalized)
                normalized['classification'] = classification
                normalized['classification_confidence'] = confidence
            
            # Step 5: Insert into leads_raw
            insert_result = leads_raw.insert_one(normalized)
            
            result['success'] = True
            result['action'] = 'inserted'
            result['lead_id'] = str(insert_result.inserted_id)
        
        # Log the ingestion event
        log_ingestion_event(
            email=result['email'],
            source=source,
            action=result['action'],
            lead_id=result['lead_id']
        )
        logger.info(f"Lead {result['action']}: {result['email']} (source={source})")
        
    except DuplicateKeyError:
        # Race condition - another process inserted this email
        result['action'] = 'skipped'
        result['success'] = True
        log_ingestion_event(
            email=normalized['email'],
            source=source,
            action='skipped',
            error='duplicate_key_race_condition'
        )
        logger.info(f"Lead skipped (race condition): {normalized['email']}")
        
    except Exception as e:
        result['error'] = str(e)
        log_ingestion_event(
            email=normalized.get('email') or payload.get('email', 'unknown'),
            source=source,
            action='error',
            error=str(e)
        )
        logger.error(f"Lead ingestion failed: {e}")
    
    return result


def ingest_leads_batch(
    payloads: List[Dict[str, Any]],
    source: str,
    source_detail: str,
    skip_classification: bool = False
) -> Dict[str, Any]:
    """
    Batch ingestion for multiple leads.
    
    Returns:
        {
            'total': int,
            'inserted': int,
            'updated': int,
            'skipped': int,
            'errors': int,
            'results': List[dict]
        }
    """
    results = {
        'total': len(payloads),
        'inserted': 0,
        'updated': 0,
        'skipped': 0,
        'errors': 0,
        'results': []
    }
    
    for payload in payloads:
        result = ingest_lead(payload, source, source_detail, skip_classification)
        results['results'].append(result)
        
        if result['action'] == 'inserted':
            results['inserted'] += 1
        elif result['action'] == 'updated':
            results['updated'] += 1
        elif result['action'] == 'skipped':
            results['skipped'] += 1
        
        if result['error']:
            results['errors'] += 1
    
    return results


# =============================================================================
# SKIP PATTERNS FOR EMAIL EXTRACTION
# =============================================================================

SKIP_EMAIL_PATTERNS = [
    'noreply', 'no-reply', 'donotreply', 'mailer-daemon', 'postmaster',
    'bounce', 'notifications', 'alert', 'system', 'auto', 'newsletter',
    'unsubscribe', 'feedback', 'support@', 'info@', 'hello@', 'contact@'
]

INTERNAL_DOMAINS = ['surveyfieldwork.com', 'cogentixresearch.com']


def should_skip_email(email: str) -> bool:
    """Check if email should be skipped (system emails, internal, etc.)"""
    if not email:
        return True
    
    email_lower = email.lower()
    
    # Skip system emails
    for pattern in SKIP_EMAIL_PATTERNS:
        if pattern in email_lower:
            return True
    
    # Skip internal domains
    domain = email_lower.split('@')[-1] if '@' in email_lower else ''
    if domain in INTERNAL_DOMAINS:
        return True
    
    return False


def extract_lead_from_email(email_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract lead payload from an email document.
    Returns None if email should be skipped.
    """
    from_email = email_doc.get('from_email', '')
    from_name = email_doc.get('from_name', '')
    
    if should_skip_email(from_email):
        return None
    
    # Extract domain for company
    domain = from_email.split('@')[-1] if '@' in from_email else None
    
    return {
        'email': from_email,
        'name': from_name,
        'company_domain': domain,
        'source_email_id': str(email_doc.get('_id', '')),
    }
