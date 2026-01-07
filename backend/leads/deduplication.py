"""
LEAD DEDUPLICATION MODULE
Prevents duplicate leads from entering the database

Deduplication Strategies:
1. LinkedIn URL (primary key) - exact match
2. Email normalization - handles case, dots, plus signs
3. Name + Company fuzzy matching - catches slight variations
4. Phone number normalization

Collections:
    - dedup_index: Fast lookup index for deduplication checks
    - dedup_logs: Audit trail of rejected duplicates
"""

import os
import re
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Set, Any
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']

# Collections
dedup_index_collection = db['dedup_index']
dedup_logs_collection = db['dedup_logs']
leads_raw_collection = db['leads_raw']
leads_enriched_collection = db['leads_enriched']


# ============== INDEXES ==============

def ensure_dedup_indexes():
    """Create indexes for deduplication collections"""
    # Dedup index - fast lookups
    dedup_index_collection.create_index("linkedin_url_hash", unique=True, sparse=True)
    dedup_index_collection.create_index("email_hash", sparse=True)
    dedup_index_collection.create_index("name_company_hash", sparse=True)
    dedup_index_collection.create_index("created_at")
    
    # Logs index
    dedup_logs_collection.create_index("rejected_at")
    dedup_logs_collection.create_index("reason")
    dedup_logs_collection.create_index("source")
    
    print("✅ Deduplication indexes created")


# Initialize indexes on module load
try:
    ensure_dedup_indexes()
except Exception as e:
    print(f"Warning: Could not create dedup indexes: {e}")


# ============== NORMALIZATION FUNCTIONS ==============

def normalize_linkedin_url(url: str) -> str:
    """
    Normalize LinkedIn URL to a consistent format.
    
    Examples:
        https://www.linkedin.com/in/johndoe/ -> linkedin.com/in/johndoe
        http://linkedin.com/in/JohnDoe -> linkedin.com/in/johndoe
        linkedin.com/in/john-doe?trk=... -> linkedin.com/in/john-doe
    """
    if not url:
        return ""
    
    # Lowercase
    url = url.lower().strip()
    
    # Remove protocol
    url = re.sub(r'^https?://', '', url)
    
    # Remove www.
    url = re.sub(r'^www\.', '', url)
    
    # Remove trailing slash
    url = url.rstrip('/')
    
    # Remove query parameters
    url = url.split('?')[0]
    
    # Remove tracking parameters
    url = url.split('#')[0]
    
    return url


def normalize_email(email: str) -> str:
    """
    Normalize email to catch duplicates with variations.
    
    Handles:
        - Case insensitivity
        - Gmail dots (john.doe@gmail.com = johndoe@gmail.com)
        - Plus addressing (john+work@gmail.com = john@gmail.com)
        - Common domain aliases (googlemail.com = gmail.com)
    """
    if not email:
        return ""
    
    email = email.lower().strip()
    
    # Split local and domain parts
    if '@' not in email:
        return email
    
    local, domain = email.rsplit('@', 1)
    
    # Handle Gmail-specific normalizations
    gmail_domains = ['gmail.com', 'googlemail.com']
    if domain in gmail_domains:
        domain = 'gmail.com'
        # Remove dots from local part (Gmail ignores them)
        local = local.replace('.', '')
        # Remove plus addressing
        local = local.split('+')[0]
    
    # Handle other common plus addressing
    else:
        local = local.split('+')[0]
    
    return f"{local}@{domain}"


def normalize_name(name: str) -> str:
    """
    Normalize name for fuzzy matching.
    
    Handles:
        - Case insensitivity
        - Extra whitespace
        - Common prefixes (Dr., Mr., Ms., etc.)
        - Suffixes (Jr., Sr., III, PhD, etc.)
    """
    if not name:
        return ""
    
    name = name.lower().strip()
    
    # Remove common prefixes
    prefixes = [
        'dr.', 'dr', 'mr.', 'mr', 'ms.', 'ms', 'mrs.', 'mrs',
        'prof.', 'prof', 'professor', 'sir', 'dame'
    ]
    for prefix in prefixes:
        if name.startswith(prefix + ' '):
            name = name[len(prefix):].strip()
            break
    
    # Remove common suffixes
    suffixes = [
        'jr.', 'jr', 'sr.', 'sr', 'iii', 'ii', 'iv',
        'phd', 'ph.d.', 'md', 'm.d.', 'mba', 'cpa', 'esq', 'esq.'
    ]
    for suffix in suffixes:
        if name.endswith(' ' + suffix):
            name = name[:-len(suffix)].strip()
            break
    
    # Normalize whitespace
    name = ' '.join(name.split())
    
    # Remove special characters (keep letters, numbers, spaces)
    name = re.sub(r'[^a-z0-9\s]', '', name)
    
    return name


def normalize_company(company: str) -> str:
    """
    Normalize company name for matching.
    
    Handles:
        - Case insensitivity
        - Common suffixes (Inc., LLC, Ltd., etc.)
        - The/the prefix
    """
    if not company:
        return ""
    
    company = company.lower().strip()
    
    # Remove "the" prefix
    if company.startswith('the '):
        company = company[4:]
    
    # Remove common suffixes
    suffixes = [
        'inc.', 'inc', 'incorporated',
        'llc', 'l.l.c.', 'llp', 'l.l.p.',
        'ltd.', 'ltd', 'limited',
        'corp.', 'corp', 'corporation',
        'co.', 'co', 'company',
        'pvt.', 'pvt', 'private',
        'plc', 'p.l.c.',
        'gmbh', 's.a.', 'b.v.', 'n.v.'
    ]
    for suffix in suffixes:
        if company.endswith(' ' + suffix):
            company = company[:-len(suffix)].strip()
            break
    
    # Normalize whitespace
    company = ' '.join(company.split())
    
    # Remove special characters
    company = re.sub(r'[^a-z0-9\s]', '', company)
    
    return company


# ============== HASH GENERATION ==============

def generate_linkedin_hash(linkedin_url: str) -> str:
    """Generate hash for LinkedIn URL lookup"""
    normalized = normalize_linkedin_url(linkedin_url)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode()).hexdigest()


def generate_email_hash(email: str) -> str:
    """Generate hash for email lookup"""
    normalized = normalize_email(email)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode()).hexdigest()


def generate_name_company_hash(name: str, company: str) -> str:
    """Generate hash for name+company fuzzy match"""
    normalized_name = normalize_name(name)
    normalized_company = normalize_company(company)
    
    if not normalized_name:
        return ""
    
    # Combine name and company
    combined = f"{normalized_name}|{normalized_company}"
    return hashlib.sha256(combined.encode()).hexdigest()


# ============== DEDUPLICATION CHECK ==============

class DuplicateCheckResult:
    """Result of a deduplication check"""
    def __init__(
        self,
        is_duplicate: bool,
        reason: Optional[str] = None,
        existing_lead_id: Optional[str] = None,
        match_type: Optional[str] = None,
        confidence: float = 1.0
    ):
        self.is_duplicate = is_duplicate
        self.reason = reason
        self.existing_lead_id = existing_lead_id
        self.match_type = match_type  # "linkedin_url", "email", "name_company"
        self.confidence = confidence  # 1.0 for exact match, lower for fuzzy


def check_duplicate(
    linkedin_url: Optional[str] = None,
    email: Optional[str] = None,
    name: Optional[str] = None,
    company_name: Optional[str] = None,
    check_enriched: bool = True
) -> DuplicateCheckResult:
    """
    Check if a lead is a duplicate.
    
    Priority:
        1. LinkedIn URL (exact match) - highest confidence
        2. Email (normalized match) - high confidence
        3. Name + Company (fuzzy match) - medium confidence
    
    Args:
        linkedin_url: LinkedIn profile URL
        email: Email address
        name: Full name
        company_name: Company name
        check_enriched: Also check leads_enriched collection
        
    Returns:
        DuplicateCheckResult with match details
    """
    
    # Check 1: LinkedIn URL (most reliable)
    if linkedin_url:
        linkedin_hash = generate_linkedin_hash(linkedin_url)
        if linkedin_hash:
            # Check dedup index
            existing = dedup_index_collection.find_one({"linkedin_url_hash": linkedin_hash})
            if existing:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    reason=f"LinkedIn URL already exists",
                    existing_lead_id=str(existing.get("lead_id")),
                    match_type="linkedin_url",
                    confidence=1.0
                )
            
            # Check raw collection directly
            normalized_url = normalize_linkedin_url(linkedin_url)
            raw_match = leads_raw_collection.find_one({
                "linkedin_url": {"$regex": f".*{re.escape(normalized_url)}.*", "$options": "i"}
            })
            if raw_match:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    reason=f"LinkedIn URL exists in leads_raw",
                    existing_lead_id=str(raw_match.get("_id")),
                    match_type="linkedin_url",
                    confidence=1.0
                )
            
            # Check enriched collection
            if check_enriched:
                enriched_match = leads_enriched_collection.find_one({
                    "linkedin_url": {"$regex": f".*{re.escape(normalized_url)}.*", "$options": "i"}
                })
                if enriched_match:
                    return DuplicateCheckResult(
                        is_duplicate=True,
                        reason=f"LinkedIn URL exists in leads_enriched",
                        existing_lead_id=str(enriched_match.get("_id")),
                        match_type="linkedin_url",
                        confidence=1.0
                    )
    
    # Check 2: Email (normalized)
    if email:
        email_hash = generate_email_hash(email)
        if email_hash:
            existing = dedup_index_collection.find_one({"email_hash": email_hash})
            if existing:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    reason=f"Email already exists (normalized match)",
                    existing_lead_id=str(existing.get("lead_id")),
                    match_type="email",
                    confidence=0.95
                )
    
    # Check 3: Name + Company (fuzzy)
    if name and company_name:
        name_company_hash = generate_name_company_hash(name, company_name)
        if name_company_hash:
            existing = dedup_index_collection.find_one({"name_company_hash": name_company_hash})
            if existing:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    reason=f"Name + Company combination already exists",
                    existing_lead_id=str(existing.get("lead_id")),
                    match_type="name_company",
                    confidence=0.85
                )
    
    # No duplicate found
    return DuplicateCheckResult(is_duplicate=False)


def check_duplicates_batch(leads: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """
    Check a batch of leads for duplicates.
    
    Args:
        leads: List of lead dicts
        
    Returns:
        Tuple of (unique_leads, duplicate_leads)
    """
    unique = []
    duplicates = []
    
    # Track within-batch duplicates
    seen_linkedin_urls: Set[str] = set()
    seen_emails: Set[str] = set()
    seen_name_companies: Set[str] = set()
    
    for lead in leads:
        # Check within-batch first
        linkedin_url = lead.get("linkedin_url", "")
        email = lead.get("email", "")
        name = lead.get("name", "")
        company = lead.get("company_name", "")
        
        # Within-batch dedup
        is_batch_dup = False
        
        if linkedin_url:
            normalized_url = normalize_linkedin_url(linkedin_url)
            if normalized_url in seen_linkedin_urls:
                is_batch_dup = True
                lead["_dedup_reason"] = "Duplicate within batch (LinkedIn URL)"
            else:
                seen_linkedin_urls.add(normalized_url)
        
        if not is_batch_dup and email:
            normalized_email = normalize_email(email)
            if normalized_email in seen_emails:
                is_batch_dup = True
                lead["_dedup_reason"] = "Duplicate within batch (Email)"
            else:
                seen_emails.add(normalized_email)
        
        if is_batch_dup:
            duplicates.append(lead)
            continue
        
        # Check against database
        result = check_duplicate(
            linkedin_url=linkedin_url,
            email=email,
            name=name,
            company_name=company
        )
        
        if result.is_duplicate:
            lead["_dedup_reason"] = result.reason
            lead["_dedup_existing_id"] = result.existing_lead_id
            lead["_dedup_match_type"] = result.match_type
            lead["_dedup_confidence"] = result.confidence
            duplicates.append(lead)
        else:
            unique.append(lead)
    
    return unique, duplicates


# ============== INDEX MANAGEMENT ==============

def add_to_dedup_index(
    lead_id: str,
    linkedin_url: Optional[str] = None,
    email: Optional[str] = None,
    name: Optional[str] = None,
    company_name: Optional[str] = None
) -> bool:
    """
    Add a lead to the deduplication index.
    Call this after successfully inserting a lead.
    
    Args:
        lead_id: MongoDB ObjectId as string
        linkedin_url: LinkedIn profile URL
        email: Email address
        name: Full name
        company_name: Company name
        
    Returns:
        True if added successfully
    """
    index_doc = {
        "lead_id": lead_id,
        "created_at": datetime.utcnow()
    }
    
    if linkedin_url:
        linkedin_hash = generate_linkedin_hash(linkedin_url)
        if linkedin_hash:
            index_doc["linkedin_url_hash"] = linkedin_hash
    
    if email:
        email_hash = generate_email_hash(email)
        if email_hash:
            index_doc["email_hash"] = email_hash
    
    if name:
        name_company_hash = generate_name_company_hash(name, company_name or "")
        if name_company_hash:
            index_doc["name_company_hash"] = name_company_hash
    
    # Only insert if we have at least one hash
    if not any(k.endswith("_hash") for k in index_doc):
        return False
    
    try:
        dedup_index_collection.insert_one(index_doc)
        return True
    except DuplicateKeyError:
        # Already indexed
        return True
    except Exception as e:
        print(f"Error adding to dedup index: {e}")
        return False


def remove_from_dedup_index(lead_id: str) -> bool:
    """Remove a lead from the deduplication index (e.g., when deleting a lead)"""
    try:
        result = dedup_index_collection.delete_one({"lead_id": lead_id})
        return result.deleted_count > 0
    except Exception as e:
        print(f"Error removing from dedup index: {e}")
        return False


def rebuild_dedup_index() -> Dict[str, int]:
    """
    Rebuild the entire deduplication index from leads_raw and leads_enriched.
    Use this for initial setup or recovery.
    
    Returns:
        Dict with counts of indexed leads
    """
    print("🔄 Rebuilding deduplication index...")
    
    # Clear existing index
    dedup_index_collection.delete_many({})
    
    indexed_raw = 0
    indexed_enriched = 0
    
    # Index raw leads
    for lead in leads_raw_collection.find({}, {
        "_id": 1, "linkedin_url": 1, "email": 1, "name": 1, "company_name": 1
    }):
        add_to_dedup_index(
            lead_id=str(lead["_id"]),
            linkedin_url=lead.get("linkedin_url"),
            email=lead.get("email"),
            name=lead.get("name"),
            company_name=lead.get("company_name")
        )
        indexed_raw += 1
    
    # Index enriched leads (may overlap, but that's okay)
    for lead in leads_enriched_collection.find({}, {
        "_id": 1, "linkedin_url": 1, "predicted_email": 1,
        "first_name": 1, "last_name": 1, "company_name": 1
    }):
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        add_to_dedup_index(
            lead_id=str(lead["_id"]),
            linkedin_url=lead.get("linkedin_url"),
            email=lead.get("predicted_email"),
            name=name,
            company_name=lead.get("company_name")
        )
        indexed_enriched += 1
    
    print(f"✅ Indexed {indexed_raw} raw leads, {indexed_enriched} enriched leads")
    
    return {
        "indexed_raw": indexed_raw,
        "indexed_enriched": indexed_enriched,
        "total": indexed_raw + indexed_enriched
    }


# ============== LOGGING ==============

def log_rejected_duplicate(lead: Dict, reason: str, source: str = "import"):
    """Log a rejected duplicate for audit purposes"""
    dedup_logs_collection.insert_one({
        "lead_data": lead,
        "reason": reason,
        "source": source,
        "rejected_at": datetime.utcnow()
    })


def get_duplicate_stats(days: int = 7) -> Dict[str, Any]:
    """Get statistics on rejected duplicates"""
    since = datetime.utcnow() - timedelta(days=days)
    
    pipeline = [
        {"$match": {"rejected_at": {"$gte": since}}},
        {"$group": {
            "_id": "$reason",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]
    
    by_reason = list(dedup_logs_collection.aggregate(pipeline))
    total = sum(r["count"] for r in by_reason)
    
    return {
        "period_days": days,
        "total_rejected": total,
        "by_reason": {r["_id"]: r["count"] for r in by_reason}
    }


# ============== CLI INTERFACE ==============

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) == 1:
        print("\n=== Lead Deduplication Status ===")
        
        index_count = dedup_index_collection.count_documents({})
        raw_count = leads_raw_collection.count_documents({})
        enriched_count = leads_enriched_collection.count_documents({})
        
        print(f"\nIndex Status:")
        print(f"  Indexed Leads:    {index_count}")
        print(f"  Raw Leads:        {raw_count}")
        print(f"  Enriched Leads:   {enriched_count}")
        
        stats = get_duplicate_stats()
        print(f"\nRejected Duplicates (last {stats['period_days']} days):")
        print(f"  Total Rejected:   {stats['total_rejected']}")
        for reason, count in stats.get("by_reason", {}).items():
            print(f"  - {reason}: {count}")
        
    elif sys.argv[1] == "rebuild":
        result = rebuild_dedup_index()
        print(f"✓ Rebuilt index: {result}")
        
    elif sys.argv[1] == "check":
        if len(sys.argv) < 3:
            print("Usage: python deduplication.py check <linkedin_url>")
        else:
            result = check_duplicate(linkedin_url=sys.argv[2])
            print(f"Is Duplicate: {result.is_duplicate}")
            if result.is_duplicate:
                print(f"Reason: {result.reason}")
                print(f"Existing ID: {result.existing_lead_id}")
                print(f"Match Type: {result.match_type}")
                print(f"Confidence: {result.confidence}")
    else:
        print("Usage:")
        print("  python deduplication.py              # View status")
        print("  python deduplication.py rebuild      # Rebuild index from leads")
        print("  python deduplication.py check <url>  # Check if URL is duplicate")
