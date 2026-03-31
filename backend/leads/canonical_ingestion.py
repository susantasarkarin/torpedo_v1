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
leads_enriched = _db['leads_enriched']  # Also update enriched collection for full display
ingestion_log = _db['ingestion_log']

# Ensure unique index on email (THE deduplication key for email-based leads)
try:
    leads_raw.create_index([("email", ASCENDING)], unique=True, sparse=True)
    logger.info("Unique index on email created/verified")
except Exception as e:
    logger.warning(f"Could not create email index: {e}")

# Ensure unique index on linkedin_url for leads without email (sparse to allow NULLs)
try:
    leads_raw.create_index([("linkedin_url", ASCENDING)], unique=True, sparse=True)
    logger.info("Unique index on linkedin_url created/verified")
except Exception as e:
    logger.warning(f"Could not create linkedin_url index: {e}")


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
VALID_BRACKETS = {'lead', 'contact', 'account'}
UNKNOWN_COMPANY_VALUES = {'unknown', 'n/a', 'na', '-', '--', 'not available', 'none'}


def is_unknown_company(value: Any) -> bool:
    """Return True when company value is a placeholder like 'unknown' or empty."""
    if value is None:
        return True
    v = str(value).strip().lower()
    return v in UNKNOWN_COMPANY_VALUES or v == ''


def determine_lead_bracket(lead_data: Dict[str, Any]) -> str:
    """
    Categorize a lead into a bracket based on data completeness.
    
    Rules:
    - 'contact': Has first_name + company + title/position (fully developed person record)
    - 'account': Has company data but no individual person details (company-level record)
    - 'lead': Everything else (raw/minimal entries needing enrichment)
    
    Returns: 'lead', 'contact', or 'account'
    """
    has_first_name = bool(lead_data.get('first_name'))
    has_last_name = bool(lead_data.get('last_name'))
    has_company = bool(lead_data.get('company') or lead_data.get('company_name'))
    has_title = bool(lead_data.get('title'))
    has_email = bool(lead_data.get('email'))
    has_linkedin = bool(lead_data.get('linkedin_url'))
    
    # Contact: person with enough identity data
    # Need at least name + company, or name + title, or name + linkedin
    if has_first_name and (has_company or has_title or has_linkedin):
        return 'contact'
    
    # Account: has company data but no person details
    if has_company and not has_first_name and not has_email:
        return 'account'
    
    # Default: lead (raw entry needing development)
    return 'lead'


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


def normalize_payload(payload: Dict[str, Any], source: str, source_detail: str, icp_segment: Optional[str] = None) -> Dict[str, Any]:
    """
    Normalize incoming payload to canonical schema.
    Email is optional when linkedin_url is present (e.g. web/LinkedIn search leads).
    icp_segment: optional ICP slug (e.g. 'bimwave') to tag this lead at ingestion time.
    """
    email = normalize_email(payload.get('email', ''))
    linkedin_url = (payload.get('linkedin_url') or payload.get('linkedin') or '').strip() or None

    if not email and not linkedin_url:
        raise ValueError("Lead must have at least one identifier: email or linkedin_url")

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
    company_raw = (payload.get('company') or payload.get('company_name') or '').strip()
    company_clean = None if is_unknown_company(company_raw) else company_raw

    return {
        'email': email,
        'first_name': first_name,
        'last_name': last_name,
        'name': payload.get('name', '').strip() or f"{first_name or ''} {last_name or ''}".strip() or None,
        'company': company_clean,
        'company_domain': (payload.get('company_domain') or '').strip() or None,
        'title': (payload.get('title') or payload.get('job_title') or '').strip() or None,
        'phone': (payload.get('phone') or '').strip() or None,
        'linkedin_url': linkedin_url,
        'location': (payload.get('location') or '').strip() or None,
        'source': source if source in VALID_SOURCES else 'unknown',
        'source_detail': source_detail,
        'classification': 'pending',
        'classification_confidence': 0.0,
        'classification_status': 'Pending',  # Capital-P matches ClassificationStatus enum
        'classification_attempts': 0,
        'enrichment_status': 'pending',
        'lead_bracket': 'lead',  # Will be recalculated after enrichment
        'icp_segment': icp_segment or None,
        'stage': 'already_contacted' if source == 'gmail' else None,
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
# SYNC TO LEADS_ENRICHED (For frontend display)
# =============================================================================

def sync_to_enriched(lead_data: Dict[str, Any], raw_lead_id: str) -> Optional[str]:
    """
    Sync a classified lead to leads_enriched collection.
    This is required because the frontend reads from leads_enriched.
    Uses email as primary dedup key; falls back to linkedin_url for no-email leads.

    Returns the enriched lead ID if successful, None otherwise.
    """
    try:
        # Determine dedup key: prefer email, fall back to linkedin_url
        _email = lead_data.get('email')
        _linkedin = lead_data.get('linkedin_url')
        if not _email and not _linkedin:
            logger.warning("sync_to_enriched: lead has neither email nor linkedin_url — skipping")
            return None

        # Clean "Unknown" placeholders left by AI classifier
        _last = (lead_data.get('last_name') or '').strip()
        if _last.lower() == 'unknown':
            _last = ''
        _first = (lead_data.get('first_name') or '').strip()
        _name_raw = (lead_data.get('name') or '').strip()
        if _name_raw.lower().endswith(' unknown'):
            _name_raw = _name_raw[:-8].strip()
        _clean_name = _name_raw or f"{_first} {_last}".strip() or None
        _clean_title = lead_data.get('title')
        if _clean_title and _clean_title.strip().lower() == 'unknown':
            _clean_title = None

        # Build enriched lead document
        enriched_doc = {
            'raw_lead_id': raw_lead_id,
            'icp_segment': lead_data.get('icp_segment'),
            # Personal Info
            'name': _clean_name,
            'first_name': _first or None,
            'last_name': _last or None,
            'email': lead_data.get('email'),
            'email_status': lead_data.get('email_status', 'Unknown'),
            'title': _clean_title,
            'linkedin_url': lead_data.get('linkedin_url'),
            'location': lead_data.get('location') or lead_data.get('inferred_location'),
            # Metadata
            'added_on': lead_data.get('created_at') or datetime.utcnow(),
            'source': lead_data.get('source'),
            'snippet': lead_data.get('source_detail'),
            'stage': lead_data.get('stage'),
            # AI Classification
            'seniority_level': lead_data.get('seniority_level'),
            'buying_role': lead_data.get('buying_role'),
            'department': lead_data.get('department'),
            'persona': lead_data.get('persona'),
            'gender': lead_data.get('gender'),
            'company_size': lead_data.get('company_size'),
            'region': lead_data.get('region'),
            'confidence_score': lead_data.get('confidence_score', 0.0),
            # Company Info
            'company_name': lead_data.get('company_name') or lead_data.get('company'),
            'company_domain': lead_data.get('company_domain'),
            'company_website': lead_data.get('company_website'),
            'company_employee_count': lead_data.get('company_employee_count'),
            'company_employee_count_range': lead_data.get('company_employee_count_range'),
            'company_founded': lead_data.get('company_founded'),
            'company_industry': lead_data.get('company_industry'),
            'company_type': lead_data.get('company_type'),
            'company_headquarters': lead_data.get('company_headquarters'),
            'company_revenue_range': lead_data.get('company_revenue_range'),
            'company_linkedin_url': lead_data.get('company_linkedin_url'),
            # Timestamps
            'classified_at': lead_data.get('classified_at') or datetime.utcnow(),
            'updated_at': datetime.utcnow(),
            # Lead bracket categorization
            'lead_bracket': lead_data.get('lead_bracket', 'lead'),
        }
        
        # Remove None values to avoid overwriting with nulls
        enriched_doc = {k: v for k, v in enriched_doc.items() if v is not None}

        # Merge ICP basket classification (rule-based, no AI needed)
        enriched_doc.update(compute_icp_basket(lead_data))

        # Upsert key: email (primary) or linkedin_url (fallback for no-email leads)
        if _email:
            dedup_filter = {'email': _email}
        else:
            dedup_filter = {'linkedin_url': _linkedin}

        result = leads_enriched.update_one(
            dedup_filter,
            {'$set': enriched_doc, '$setOnInsert': {'created_at': datetime.utcnow()}},
            upsert=True
        )

        # Get the enriched lead ID
        if result.upserted_id:
            return str(result.upserted_id)
        else:
            existing = leads_enriched.find_one(dedup_filter)
            if existing:
                return str(existing['_id'])

        return None
        
    except Exception as e:
        logger.error(f"Failed to sync to leads_enriched: {e}")
        return None



def compute_icp_basket(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rule-based 5-basket ICP classification.
    Primary: uses existing icp_segment field (set by enrichment pipeline).
    Fallback: keyword/industry scoring.
    Returns dict with basket/tier/persona fields ready for $set.
    """
    import re as _re

    def _n(v):
        return (v or "").lower().strip()

    title        = _n(lead.get("title"))
    dept         = _n(lead.get("department"))
    seniority    = _n(lead.get("seniority_level"))
    # persona/buying_role: check multiple fields
    buying_role  = _n(
        lead.get("buying_role") or lead.get("persona") or ""
    )
    industry     = _n(lead.get("company_industry") or lead.get("industry") or "")
    revenue_raw  = _n(lead.get("company_revenue_range") or "")
    existing_seg = _n(lead.get("icp_segment") or "")
    full_text    = " ".join([
        title, dept, industry,
        _n(lead.get("company") or lead.get("company_name") or ""),
    ])

    def _revenue_gte(rev, min_m):
        nums = _re.findall(r"\d+", rev.replace(",", ""))
        if not nums:
            return False
        low = int(nums[0])
        if "billion" in rev:
            low *= 1000
        return low >= min_m

    # "C-Level" is how the data actually arrives — include it alongside c-suite
    HIGH_TITLES = {
        "vp", "vice president", "c-suite", "c-level", "ceo", "cto", "cfo", "coo",
        "cmo", "cro", "chro", "cio", "cpo", "director", "svp", "evp",
        "president", "owner", "founder", "co-founder", "partner",
        "managing director", "md", "head of", "head,",
    }
    MID_TITLES = {"manager", "senior", "principal", "lead", "specialist"}

    def _is_high():
        combined = title + " " + seniority
        return any(t in combined for t in HIGH_TITLES)

    def _is_mid():
        combined = title + " " + seniority
        return any(t in combined for t in MID_TITLES)

    def _is_dm():
        # Check buying_role AND persona field (data stores "Decision Maker")
        combined = buying_role + " " + _n(lead.get("persona") or "")
        return any(k in combined for k in (
            "decision maker", "economic buyer", "decision", "influencer", "champion"
        ))

    # ── PRIMARY PATH: use existing icp_segment if present ──────────────────
    SEG_TO_BASKET = {
        "survey_fieldwork": ("A", "Survey Fieldwork", ["survey_fieldwork"]),
        "cogentix":         ("B", "Cogentix Research", ["cogentix"]),
        "bimwave":          ("C", "BIMwave", ["bimwave"]),
        "dual_fit":         ("D", "Dual Fit: SFW + Cogentix", ["survey_fieldwork", "cogentix"]),
    }
    if existing_seg and existing_seg in SEG_TO_BASKET:
        basket_code, basket_name, icp_tags = SEG_TO_BASKET[existing_seg]
    else:
        # ── FALLBACK: keyword scoring ────────────────────────────────────────
        MR_IND   = ["market research", "research agency", "consumer insights",
                    "data collection", "panel services", "fieldwork", "survey research"]
        MR_DEPT  = ["research", "insights", "field services", "sampling"]
        MR_KW    = ["panel", "fieldwork", "survey", "cati", "cawi", "tracker",
                    "quantitative", "sample", "respondent", "omnibus"]

        BRAND_IND  = ["fmcg", "consumer goods", "retail", "healthcare", "pharma",
                      "media", "advertising", "marketing and advertising",
                      "financial services", "brand consulting", "cpg",
                      "insurance", "telecom", "food & beverage", "beverage",
                      "beauty", "personal care", "apparel", "consumer electronics"]
        BRAND_DEPT = ["marketing", "brand", "consumer insights", "strategy",
                      "product", "growth", "communications"]
        BRAND_KW   = ["brand health", "ad effectiveness", "concept testing", "nps",
                      "brand tracking", "brand equity", "awareness", "purchase intent"]

        AEC_IND  = ["architecture", "construction", "engineering", "real estate",
                    "interior design", "infrastructure", "bim"]
        AEC_DEPT = ["architecture", "engineering", "project management",
                    "construction", "design", "bim"]
        AEC_KW   = ["revit", "bim", "ifc", "aec", "autocad", "navisworks",
                    "civil engineering", "structural", "mechanical engineering"]

        def _score_sfw():
            s = 0
            if any(i in industry for i in MR_IND):   s += 4
            if any(k in full_text for k in MR_KW):   s += 2
            if any(d in dept for d in MR_DEPT):       s += 3
            if _is_high():                            s += 2
            if _is_dm():                              s += 2
            return s

        def _score_brand():
            s = 0
            if any(i in industry for i in BRAND_IND): s += 4
            if any(k in full_text for k in BRAND_KW): s += 2
            if any(d in dept for d in BRAND_DEPT):    s += 3
            if _is_high():                            s += 2
            if _is_dm():                              s += 2
            if _revenue_gte(revenue_raw, 10):         s += 2
            return s

        def _score_aec():
            s = 0
            if any(i in industry for i in AEC_IND):  s += 4
            if any(k in full_text for k in AEC_KW):  s += 2
            if any(d in dept for d in AEC_DEPT):     s += 3
            return s

        THRESHOLD = 4
        sfw_s   = _score_sfw()
        brand_s = _score_brand()
        aec_s   = _score_aec()

        q_sfw   = sfw_s   >= THRESHOLD
        q_brand = brand_s >= THRESHOLD
        q_aec   = aec_s   >= THRESHOLD

        if not q_sfw and not q_brand and not q_aec:
            basket_code, basket_name, icp_tags = "E", "Nurture / Unqualified", ["nurture"]
        elif q_sfw and q_brand:
            basket_code, basket_name, icp_tags = "D", "Dual Fit: SFW + Cogentix", ["survey_fieldwork", "cogentix"]
        elif q_aec:
            basket_code, basket_name, icp_tags = "C", "BIMwave", ["bimwave"]
        elif q_sfw:
            basket_code, basket_name, icp_tags = "A", "Survey Fieldwork", ["survey_fieldwork"]
        else:
            basket_code, basket_name, icp_tags = "B", "Cogentix Research", ["cogentix"]

    # ── FIT TIER: seniority + persona signals ───────────────────────────────
    high = _is_high()
    dm   = _is_dm()

    if high and dm and _revenue_gte(revenue_raw, 50):
        fit_tier, fit_label = 1, "Hot"
    elif high and (dm or _revenue_gte(revenue_raw, 10)):
        fit_tier, fit_label = 2, "Warm"
    elif high or dm or _is_mid():
        fit_tier, fit_label = 2, "Warm"
    else:
        fit_tier, fit_label = 3, "Cold"

    # ── PERSONA LABEL ────────────────────────────────────────────────────────
    ctx = title + " " + dept + " " + seniority + " " + buying_role
    if any(k in ctx for k in ("ceo", "cto", "cfo", "coo", "cmo", "cro",
                               "svp", "evp", "president", "c-suite", "c-level")):
        persona_label = "Executive Sponsor"
    elif "research" in dept or "insights" in dept:
        persona_label = "Research Buyer"
    elif "marketing" in dept or "brand" in dept:
        persona_label = "Brand Strategist"
    elif any(d in dept for d in ("architecture", "engineering", "construction", "bim", "design")):
        persona_label = "AEC Operator"
    elif "influencer" in buying_role or "champion" in buying_role:
        persona_label = "Influencer / Recommender"
    elif high:
        persona_label = "Executive Sponsor"
    elif dm:
        persona_label = "Decision Maker"
    else:
        persona_label = "Influencer / Recommender"

    return {
        "icp_tags": icp_tags,
        "classification_basket": basket_code,
        "classification_basket_name": basket_name,
        "fit_tier": fit_tier,
        "fit_tier_label": fit_label,
        "persona_label": persona_label,
        "classification_confidence": "High" if existing_seg else "Medium",
        "classified_at": datetime.utcnow(),
    }


# =============================================================================
# AI CLASSIFICATION (Wrapper)
# =============================================================================

def classify_lead_ai(lead: Dict[str, Any]) -> Tuple[str, float, Optional[Dict[str, Any]]]:
    """
    Call AI classification for a lead.
    Returns (classification, confidence, full_result_dict).
    
    The full_result_dict contains all enrichment fields:
    - seniority_level, department, persona, buying_role, gender
    - company_size, region, inferred_location
    - company_name, company_domain, company_website, etc.
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
                classification = 'client'
            elif persona and persona.value == 'Blocker':
                classification = 'vendor'
            else:
                classification = 'unknown'
            
            # Extract all enrichment fields from the AI result
            full_result = {
                'first_name': result.first_name,
                'last_name': result.last_name,
                'predicted_email': result.predicted_email,
                'seniority_level': result.seniority_level.value if result.seniority_level else None,
                'department': result.department.value if result.department else None,
                'persona': result.persona.value if result.persona else None,
                'buying_role': result.buying_role.value if result.buying_role else None,
                'gender': result.gender.value if result.gender else None,
                'company_size': result.company_size.value if result.company_size else None,
                'region': result.region.value if result.region else None,
                'inferred_location': result.inferred_location,
                'company_name': result.company_name,
                'company_domain': result.company_domain,
                'company_website': result.company_website,
                'company_employee_count': result.company_employee_count,
                'company_employee_count_range': result.company_employee_count_range,
                'company_founded': result.company_founded,
                'company_industry': result.company_industry,
                'company_type': result.company_type,
                'company_headquarters': result.company_headquarters,
                'company_revenue_range': result.company_revenue_range,
                'company_linkedin_url': result.company_linkedin_url,
                'confidence_score': result.confidence_score,
            }
            
            return classification, result.confidence_score, full_result
        
        return 'unknown', 0.0, None
        
    except Exception as e:
        logger.error(f"AI classification failed: {e}")
        return 'unknown', 0.0, None


# =============================================================================
# MAIN INGESTION FUNCTION
# =============================================================================

def ingest_lead(
    payload: Dict[str, Any],
    source: str,
    source_detail: str,
    skip_classification: bool = False,
    icp_segment: Optional[str] = None,
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
        normalized = normalize_payload(payload, source, source_detail, icp_segment=icp_segment)
        result['email'] = normalized['email']

        # Strict rule: skip records with unknown company placeholders.
        input_company = payload.get('company') or payload.get('company_name')
        if is_unknown_company(input_company):
            result['success'] = True
            result['action'] = 'skipped'
            result['error'] = 'unknown_company'
            logger.info("Lead skipped: unknown company value")
            return result
        
    except ValueError as e:
        result['error'] = str(e)
        logger.warning(f"Lead rejected: {e}")
        return result
    
    try:
        # Step 2: Check for existing lead (dedup by email, or linkedin_url for no-email leads)
        if normalized['email']:
            existing = leads_raw.find_one({'email': normalized['email']})
        else:
            existing = leads_raw.find_one({'linkedin_url': normalized['linkedin_url']})
        
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
                classification, confidence, full_result = classify_lead_ai(merged)
                merged['classification'] = classification
                merged['classification_confidence'] = confidence

                # Store all AI enrichment fields if classification succeeded
                if full_result:
                    merged['classification_status'] = 'Classified'
                    # Personal enrichment fields
                    if full_result.get('first_name') and not merged.get('first_name'):
                        merged['first_name'] = full_result['first_name']
                    if full_result.get('last_name') and not merged.get('last_name'):
                        merged['last_name'] = full_result['last_name']
                    if full_result.get('predicted_email') and not merged.get('email'):
                        merged['email'] = full_result['predicted_email']
                    if full_result.get('inferred_location') and not merged.get('location'):
                        merged['location'] = full_result['inferred_location']
                    
                    # AI Classification fields (always update from AI)
                    merged['seniority_level'] = full_result.get('seniority_level')
                    merged['department'] = full_result.get('department')
                    merged['persona'] = full_result.get('persona')
                    merged['buying_role'] = full_result.get('buying_role')
                    merged['gender'] = full_result.get('gender')
                    merged['company_size'] = full_result.get('company_size')
                    merged['region'] = full_result.get('region')
                    merged['confidence_score'] = full_result.get('confidence_score', confidence)
                    
                    # Company enrichment fields (prefer AI over existing)
                    if full_result.get('company_name') and not is_unknown_company(full_result.get('company_name')):
                        merged['company'] = full_result['company_name']
                        merged['company_name'] = full_result['company_name']
                    if full_result.get('company_domain') and not merged.get('company_domain'):
                        merged['company_domain'] = full_result['company_domain']
                    if full_result.get('company_website'):
                        merged['company_website'] = full_result['company_website']
                    if full_result.get('company_employee_count'):
                        merged['company_employee_count'] = full_result['company_employee_count']
                    if full_result.get('company_employee_count_range'):
                        merged['company_employee_count_range'] = full_result['company_employee_count_range']
                    if full_result.get('company_founded'):
                        merged['company_founded'] = full_result['company_founded']
                    if full_result.get('company_industry'):
                        merged['company_industry'] = full_result['company_industry']
                    if full_result.get('company_type'):
                        merged['company_type'] = full_result['company_type']
                    if full_result.get('company_headquarters'):
                        merged['company_headquarters'] = full_result['company_headquarters']
                    if full_result.get('company_revenue_range'):
                        merged['company_revenue_range'] = full_result['company_revenue_range']
                    if full_result.get('company_linkedin_url'):
                        merged['company_linkedin_url'] = full_result['company_linkedin_url']
                    
                    merged['classified_at'] = datetime.utcnow()
                else:
                    merged['classification_status'] = 'Failed'

            # Recalculate bracket after merging
            merged['lead_bracket'] = determine_lead_bracket(merged)
            
            # Update existing lead
            leads_raw.update_one(
                {'_id': existing['_id']},
                {'$set': merged}
            )
            result['email'] = normalized.get('email')
            
            # Sync to leads_enriched for frontend display (if classified or gmail)
            if merged.get('classification_status') == 'Classified' or source == 'gmail':
                enriched_id = sync_to_enriched(merged, str(existing['_id']))
                if enriched_id:
                    leads_raw.update_one(
                        {'_id': existing['_id']},
                        {'$set': {'enriched_lead_id': enriched_id}}
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
                classification, confidence, full_result = classify_lead_ai(normalized)
                normalized['classification'] = classification
                normalized['classification_confidence'] = confidence
                
                # Store all AI enrichment fields if classification succeeded
                if full_result:
                    normalized['classification_status'] = 'Classified'
                    # Personal enrichment fields
                    if full_result.get('first_name') and not normalized.get('first_name'):
                        normalized['first_name'] = full_result['first_name']
                    if full_result.get('last_name') and not normalized.get('last_name'):
                        normalized['last_name'] = full_result['last_name']
                    if full_result.get('predicted_email') and not normalized.get('email'):
                        normalized['email'] = full_result['predicted_email']
                    if full_result.get('inferred_location') and not normalized.get('location'):
                        normalized['location'] = full_result['inferred_location']
                    
                    # AI Classification fields (always update from AI)
                    normalized['seniority_level'] = full_result.get('seniority_level')
                    normalized['department'] = full_result.get('department')
                    normalized['persona'] = full_result.get('persona')
                    normalized['buying_role'] = full_result.get('buying_role')
                    normalized['gender'] = full_result.get('gender')
                    normalized['company_size'] = full_result.get('company_size')
                    normalized['region'] = full_result.get('region')
                    normalized['confidence_score'] = full_result.get('confidence_score', confidence)
                    
                    # Company enrichment fields (prefer AI over existing)
                    if full_result.get('company_name') and not is_unknown_company(full_result.get('company_name')):
                        normalized['company'] = full_result['company_name']
                        normalized['company_name'] = full_result['company_name']
                    if full_result.get('company_domain') and not normalized.get('company_domain'):
                        normalized['company_domain'] = full_result['company_domain']
                    if full_result.get('company_website'):
                        normalized['company_website'] = full_result['company_website']
                    if full_result.get('company_employee_count'):
                        normalized['company_employee_count'] = full_result['company_employee_count']
                    if full_result.get('company_employee_count_range'):
                        normalized['company_employee_count_range'] = full_result['company_employee_count_range']
                    if full_result.get('company_founded'):
                        normalized['company_founded'] = full_result['company_founded']
                    if full_result.get('company_industry'):
                        normalized['company_industry'] = full_result['company_industry']
                    if full_result.get('company_type'):
                        normalized['company_type'] = full_result['company_type']
                    if full_result.get('company_headquarters'):
                        normalized['company_headquarters'] = full_result['company_headquarters']
                    if full_result.get('company_revenue_range'):
                        normalized['company_revenue_range'] = full_result['company_revenue_range']
                    if full_result.get('company_linkedin_url'):
                        normalized['company_linkedin_url'] = full_result['company_linkedin_url']
                    
                    normalized['classified_at'] = datetime.utcnow()
                else:
                    normalized['classification_status'] = 'Failed'

            # Step 5: Determine lead bracket
            normalized['lead_bracket'] = determine_lead_bracket(normalized)
            
            # Step 6: Insert into leads_raw
            insert_result = leads_raw.insert_one(normalized)

            # Sync to leads_enriched for frontend display (if classified or gmail)
            if normalized.get('classification_status') == 'Classified' or source == 'gmail':
                enriched_id = sync_to_enriched(normalized, str(insert_result.inserted_id))
                if enriched_id:
                    leads_raw.update_one(
                        {'_id': insert_result.inserted_id},
                        {'$set': {'enriched_lead_id': enriched_id}}
                    )

            # Post-insert: Skrapp company email pattern discovery
            # Runs when lead has no email but we have a company domain + name
            domain = normalized.get('company_domain')
            if not normalized.get('email') and domain:
                try:
                    from .email_pattern_system import get_pattern_system
                    ps = get_pattern_system()
                    first = normalized.get('first_name') or 'test'
                    last = normalized.get('last_name') or 'user'
                    pattern_str = ps.discover_company_email_pattern(domain, first, last)
                    if pattern_str:
                        ps.apply_pattern_to_domain_leads(domain, pattern_str)
                except Exception as _skrapp_err:
                    logger.debug(f"Skrapp pattern discovery skipped: {_skrapp_err}")

            result['success'] = True
            result['action'] = 'inserted'
            result['lead_id'] = str(insert_result.inserted_id)
            result['email'] = normalized.get('email')
        
        # Log the ingestion event
        _log_email = result.get('email') or normalized.get('linkedin_url') or 'unknown'
        log_ingestion_event(
            email=_log_email,
            source=source,
            action=result['action'],
            lead_id=result['lead_id']
        )
        logger.info(f"Lead {result['action']}: {_log_email} (source={source})")
        
    except DuplicateKeyError:
        # Race condition — another process inserted this lead
        result['action'] = 'skipped'
        result['success'] = True
        _dup_id = (normalized.get('email') or normalized.get('linkedin_url') or
                   payload.get('email') or payload.get('linkedin_url') or 'unknown')
        log_ingestion_event(
            email=_dup_id,
            source=source,
            action='skipped',
            error='duplicate_key_race_condition'
        )
        logger.info(f"Lead skipped (race condition): {_dup_id}")
        
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
    skip_classification: bool = False,
    icp_segment: Optional[str] = None,
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
        result = ingest_lead(payload, source, source_detail, skip_classification, icp_segment=icp_segment)
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

# Personal email providers — don't derive company name from these
PERSONAL_EMAIL_PROVIDERS = {
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com',
    'icloud.com', 'mail.com', 'protonmail.com', 'zoho.com', 'yandex.com',
    'live.com', 'msn.com', 'me.com', 'mac.com', 'comcast.net',
    'att.net', 'verizon.net', 'sbcglobal.net', 'cox.net',
    'rediffmail.com', 'ymail.com', 'rocketmail.com',
}


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


def _extract_name_parts(email_address: str, display_name: str = ""):
    """
    Extract first_name, last_name from display name or email address.
    Returns (full_name, first_name, last_name).
    """
    # Priority 1: Display name
    if display_name and display_name.strip():
        name = display_name.strip().strip('"').strip("'")
        # Remove email in angle brackets: "John Smith <john@example.com>"
        name = re.sub(r'\s*<[^>]+>\s*', '', name)
        # Remove email in parentheses: "John Smith (john@example.com)"
        name = re.sub(r'\s*\([^)]+\)\s*', '', name)
        name = name.strip()

        if name:
            parts = name.split()
            if len(parts) >= 2:
                return name, parts[0], " ".join(parts[1:])
            return name, parts[0] if parts else "", ""

    # Priority 2: Parse email local part (before @)
    local_part = email_address.split('@')[0] if '@' in email_address else email_address

    # Try common separators: john.smith, john_smith, john-smith
    for sep in ['.', '_', '-']:
        if sep in local_part:
            parts = local_part.split(sep)
            if len(parts) >= 2:
                first = parts[0].capitalize()
                last = ' '.join(p.capitalize() for p in parts[1:])
                return f"{first} {last}", first, last

    # Last resort: use local part as first name
    return local_part.capitalize(), local_part.capitalize(), ""


def _extract_company_from_domain(domain: str):
    """
    Derive company name from email domain.
    Returns company name string or empty string for personal providers.
    """
    if not domain:
        return ""

    domain_lower = domain.lower()

    # Don't derive company from personal providers
    if domain_lower in PERSONAL_EMAIL_PROVIDERS:
        return ""

    # Extract company from domain: "acme.com" -> "Acme", "acme.co.uk" -> "Acme"
    parts = domain_lower.split('.')
    # Remove TLDs
    tld_parts = {'com', 'org', 'net', 'co', 'io', 'uk', 'us', 'in', 'au', 'de', 'fr', 'ca', 'ai', 'app', 'dev'}
    company_parts = [p for p in parts if p not in tld_parts]

    if company_parts:
        # Take first meaningful part, capitalize properly
        raw = company_parts[0]
        # Handle multi-word company names with hyphens
        return ' '.join(word.capitalize() for word in raw.split('-'))

    return ""


def _parse_signature_fields(body: str):
    """
    Parse email body/signature for title, phone, LinkedIn URL, location and company.
    Returns dict with extracted fields.
    """
    info = {}
    if not body:
        return info

    # Only look at the last ~30 lines (signature area)
    lines = body.strip().split('\n')
    signature_area = '\n'.join(lines[-30:]) if len(lines) > 30 else body

    # Title patterns
    title_patterns = [
        r'(?:title|position|role|designation)\s*[:\-]\s*([^\n]+)',
        # "John Smith | VP of Sales | Acme Corp" — grab middle segment
        r'^[A-Z][a-z]+\s+[A-Z][a-z]+\s*[|–\-]\s*([^|–\-\n]+)\s*[|–\-]',
    ]
    for pat in title_patterns:
        m = re.search(pat, signature_area, re.IGNORECASE | re.MULTILINE)
        if m:
            info['title'] = m.group(1).strip()
            break

    # Phone patterns
    phone_patterns = [
        r'(?:phone|tel|mobile|cell|direct|office|fax)\s*[:\-]?\s*(\+?[\d\s\-\(\)\.]{7,20})',
        r'(\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4})',
    ]
    for pat in phone_patterns:
        m = re.search(pat, signature_area, re.IGNORECASE)
        if m:
            phone = re.sub(r'[^\d+\-\(\)\s]', '', m.group(1)).strip()
            if len(re.sub(r'[^\d]', '', phone)) >= 7:
                info['phone'] = phone
                break

    # LinkedIn
    linkedin_match = re.search(
        r'(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-]+)',
        signature_area, re.IGNORECASE
    )
    if linkedin_match:
        info['linkedin_url'] = f"https://linkedin.com/in/{linkedin_match.group(1)}"

    # Company from signature: "Company Name" on a standalone line or after "|"
    company_patterns = [
        r'(?:company|organization|org)\s*[:\-]\s*([^\n]+)',
    ]
    for pat in company_patterns:
        m = re.search(pat, signature_area, re.IGNORECASE)
        if m:
            info['company'] = m.group(1).strip()
            break

    # Location
    location_patterns = [
        r'(?:location|address|city|based in)\s*[:\-]\s*([^\n]+)',
    ]
    for pat in location_patterns:
        m = re.search(pat, signature_area, re.IGNORECASE)
        if m:
            info['location'] = m.group(1).strip()
            break

    return info


def extract_lead_from_email(email_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract lead payload from an email document.
    Returns None if email should be skipped.
    
    Extracts:
    - email, first_name, last_name, name
    - company_name (from domain or signature)
    - company_domain
    - title, phone, linkedin_url (from signature)
    """
    from_email = email_doc.get('from_email', '')
    from_name = email_doc.get('from_name', '')
    
    if should_skip_email(from_email):
        return None
    
    # Extract domain
    domain = from_email.split('@')[-1].lower() if '@' in from_email else ''
    
    # Extract name parts (first, last)
    full_name, first_name, last_name = _extract_name_parts(from_email, from_name)
    
    # Extract company from domain
    company_name = _extract_company_from_domain(domain)
    
    # Parse email body/signature for additional fields
    body = email_doc.get('body_text', email_doc.get('body', email_doc.get('snippet', '')))
    sig_info = _parse_signature_fields(body) if body else {}
    
    # Prefer signature company over domain-derived company
    if sig_info.get('company'):
        company_name = sig_info['company']
    
    payload = {
        'email': from_email,
        'name': full_name,
        'first_name': first_name,
        'last_name': last_name,
        'company_name': company_name,
        'company_domain': domain,
        'title': sig_info.get('title', ''),
        'phone': sig_info.get('phone', ''),
        'linkedin_url': sig_info.get('linkedin_url', ''),
        'location': sig_info.get('location', ''),
        'source_email_id': str(email_doc.get('_id', '')),
    }
    
    return payload
