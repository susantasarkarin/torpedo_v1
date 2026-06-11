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
        'classification_status': 'AwaitingEnrichment',  # Gate: classifier only runs after enrichment
        'classification_attempts': 0,
        'enrichment_status': 'needed',  # Triggers the enrichment job immediately
        'lead_bracket': 'lead',  # Will be recalculated after enrichment
        'icp_segment': icp_segment or None,
        'stage': 'already_contacted' if source == 'gmail' else None,
        # Email content fields (from mail_pool_extractor)
        'subject': (payload.get('subject') or '').strip() or None,
        'notes': (payload.get('notes') or '').strip() or None,
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
            logger.warning("sync_to_enriched: lead has neither email nor linkedin_url â€” skipping")
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
            # Email content context
            'subject': lead_data.get('subject'),  # Source email subject line
            'notes': lead_data.get('notes'),  # Source email body (first 2000 chars)
        }
        
        # Remove None values to avoid overwriting with nulls
        enriched_doc = {k: v for k, v in enriched_doc.items() if v is not None}

        # Merge ICP basket classification (rule-based, no AI needed)
        enriched_doc.update(compute_icp_basket(lead_data))

        # Upsert key: email (primary) or linkedin_url (fallback for no-email leads).
        # IMPORTANT: When a lead was originally stored by linkedin_url (no email) and
        # now has an email after enrichment, we must find the existing record first to
        # avoid creating duplicates. Try linkedin_url first when both are present.
        existing_by_linkedin = None
        if _email and _linkedin:
            existing_by_linkedin = leads_enriched.find_one({'linkedin_url': _linkedin}, {'_id': 1})

        if existing_by_linkedin:
            # Update the existing linkedin-keyed record with the new email
            dedup_filter = {'_id': existing_by_linkedin['_id']}
        elif _email:
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

    # "C-Level" is how the data actually arrives â€” include it alongside c-suite
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

    # â”€â”€ PRIMARY PATH: use existing icp_segment if present â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    SEG_TO_BASKET = {
        "survey_fieldwork": ("A", "Survey Fieldwork", ["survey_fieldwork"]),
        "cogentix":         ("B", "Cogentix Research", ["cogentix"]),
        "bimwave":          ("C", "BIMwave", ["bimwave"]),
        "dual_fit":         ("D", "Dual Fit: SFW + Cogentix", ["survey_fieldwork", "cogentix"]),
    }
    if existing_seg and existing_seg in SEG_TO_BASKET:
        basket_code, basket_name, icp_tags = SEG_TO_BASKET[existing_seg]
    else:
        # â”€â”€ FALLBACK: keyword scoring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        def _match_ind(ind_val, kw_list):
            """Bidirectional match: keyword in industry OR industry in keyword."""
            return any((kw in ind_val or ind_val in kw) for kw in kw_list if len(kw) >= 4)

        def _score_sfw():
            s = 0
            if _match_ind(industry, MR_IND):          s += 4
            if any(k in full_text for k in MR_KW):    s += 2
            if any(d in dept for d in MR_DEPT):        s += 3
            return s

        def _score_brand():
            s = 0
            if _match_ind(industry, BRAND_IND):        s += 4
            if any(k in full_text for k in BRAND_KW):  s += 2
            if any(d in dept for d in BRAND_DEPT):     s += 3
            return s

        def _score_aec():
            s = 0
            if _match_ind(industry, AEC_IND):          s += 4
            if any(k in full_text for k in AEC_KW):    s += 2
            if any(d in dept for d in AEC_DEPT):       s += 3
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

    # â”€â”€ FIT TIER: seniority + persona signals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ PERSONA LABEL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

def _strip_guessed_email_if_unverified(normalized: Dict[str, Any]) -> None:
    """
    For websearch leads: strip the email if the domain has no CSV-verified
    email pattern.  This prevents Google-Search-guessed emails from entering
    the system.  The email field is set to None and email_status to
    'pending_pattern' so pattern discovery (CSV / Skrapp) can fill it later.
    """
    email = normalized.get('email')
    if not email:
        return

    domain = email.split('@')[1] if '@' in email else ''
    if not domain:
        return

    try:
        from .email_pattern_system import get_pattern_system
        ps = get_pattern_system()
        existing = ps.patterns_collection.find_one(
            {"domain": domain},
            {"confidence": 1, "high_bounce_risk": 1},
        )
        if existing:
            # Strip if domain has known bounce problems regardless of confidence
            if existing.get("high_bounce_risk"):
                pass  # Fall through to strip
            elif existing.get("confidence", 0) >= 0.65:
                return  # Good pattern â€” keep the email
    except Exception:
        pass  # If pattern system unavailable, strip to be safe

    # No verified pattern â€” strip the guessed email
    logger.info(f"Stripping guessed email {email} (no verified pattern for {domain})")
    normalized['email'] = None
    normalized['email_status'] = 'pending_pattern'
    # Preserve the guessed email for reference
    normalized['guessed_email'] = email


def _store_csv_email_pattern(normalized: Dict[str, Any]) -> None:
    """
    For CSV leads with a valid email: analyse existing leads for the domain
    and store/update the email pattern.  This builds the verified-pattern DB
    that websearch and Skrapp leads can lean on later.
    """
    email = normalized.get('email')
    if not email or '@' not in email:
        return
    domain = email.split('@')[1]
    if domain in PERSONAL_EMAIL_PROVIDERS:
        return
    try:
        from .email_pattern_system import get_pattern_system
        ps = get_pattern_system()
        # Only run CSV analysis â€” do NOT guess/discover
        pattern = ps._analyze_patterns_from_known_emails(domain)
        if pattern:
            ps._store_pattern(pattern)
            logger.debug(f"CSV email pattern stored for {domain}: {pattern.get('pattern')}")
    except Exception as e:
        logger.debug(f"CSV pattern analysis skipped for {domain}: {e}")


def _discover_and_apply_email_pattern(normalized: Dict[str, Any]) -> None:
    """
    For leads without an email: try to discover the org email pattern via
    Skrapp.io (Tier 2.5) and apply it to this lead + other leads of the
    same domain.  Falls back to firstname.lastname@domain guess if Skrapp
    has no result or is unavailable.
    """
    import re as _re
    EMAIL_RE = _re.compile(r'^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$')

    domain = normalized.get('company_domain')
    if not domain or domain in PERSONAL_EMAIL_PROVIDERS:
        return

    # â”€â”€ Tier 1: Skrapp pattern lookup / discovery â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        from .email_pattern_system import get_pattern_system
        ps = get_pattern_system()

        existing = ps._lookup_database(domain)
        if existing:
            pattern_str = existing.get("pattern")
        else:
            first = normalized.get('first_name') or 'test'
            last = normalized.get('last_name') or 'user'
            pattern_str = ps.discover_company_email_pattern(domain, first, last)

        if pattern_str and not normalized.get('email') and normalized.get('first_name'):
            first = (normalized.get('first_name') or '').lower().strip()
            last = (normalized.get('last_name') or '').lower().strip()
            try:
                derived = pattern_str.format(
                    first=first, last=last,
                    f=first[0] if first else '',
                    l=last[0] if last else '',
                    domain=domain,
                )
                if '@' in derived and EMAIL_RE.match(derived):
                    normalized['email'] = derived
                    normalized['email_status'] = 'pattern_derived'
                    normalized['email_source'] = 'pattern_derived'
            except (KeyError, IndexError):
                pass

        if pattern_str:
            ps.apply_pattern_to_domain_leads(domain, pattern_str)

    except Exception as e:
        logger.debug(f"Skrapp pattern lookup skipped for {domain}: {e}")

    # â”€â”€ Tier 2 fallback: construct firstname.lastname@domain â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Runs regardless of whether Skrapp succeeded or threw an exception.
    if not normalized.get('email') and normalized.get('first_name') and domain:
        first = (normalized.get('first_name') or '').lower().strip()
        last = (normalized.get('last_name') or '').lower().strip()
        # Strip non-email chars (e.g. unicode marks, spaces) from name parts
        first = _re.sub(r'[^a-z0-9]', '', first)
        last = _re.sub(r'[^a-z0-9]', '', last)
        if first:
            guessed = f"{first}.{last}@{domain}" if last else f"{first}@{domain}"
            if EMAIL_RE.match(guessed):
                normalized['email'] = guessed
                normalized['email_status'] = 'predicted'
                normalized['email_source'] = 'name_domain_guess'


def _auto_enroll_in_outreach(lead_data: Dict[str, Any], enriched_id: str) -> None:
    """
    Auto-enroll a newly classified lead into the matching active cold-outreach
    campaign, if one exists.  Basket E (Nurture) leads are skipped.
    """
    basket = lead_data.get('classification_basket')
    email = lead_data.get('email')
    if not basket or basket == 'E' or not email:
        return

    try:
        from pymongo import MongoClient as _MC
        import os as _os
        _uri = _os.getenv('MONGO_URI') or _os.getenv('MONGO_URI') or 'mongodb://localhost:27017/'
        _torpedo_db = _MC(_uri, serverSelectionTimeoutMS=5000)[_os.getenv('MONGO_DB_NAME', 'torpedo')]
        campaigns_col = _torpedo_db['outreach_campaigns_v2']
        outreach_leads = _torpedo_db['outreach_leads_v2']
        suppression = _torpedo_db['outreach_bounce_suppression']

        email_lower = email.lower().strip()

        # Check suppression
        if suppression.find_one({'email': email_lower}):
            return

        BASKET_BUSINESS_MAP = {'A': 'sfw', 'B': 'cogentix', 'C': 'bimwave'}

        if basket == 'D':
            # Dual Fit: enroll into all 3 active campaigns with staggered starts
            SEQUENCE_DURATION_DAYS = 12
            DUAL_FIT_GAP_DAYS = 21
            sequence_window = SEQUENCE_DURATION_DAYS + DUAL_FIT_GAP_DAYS
            now = datetime.utcnow()
            campaigns_found = []
            for biz in ['sfw', 'cogentix', 'bimwave']:
                c = campaigns_col.find_one({'business': biz, 'is_active': True})
                if c:
                    campaigns_found.append((biz, c))
            for seq_idx, (biz, campaign) in enumerate(campaigns_found):
                cid = campaign['campaign_id']
                if outreach_leads.find_one({'email': email_lower, 'campaign_id': cid}):
                    continue
                from datetime import timedelta
                start_offset = timedelta(days=seq_idx * sequence_window)
                _basket = {'sfw': 'A', 'cogentix': 'B', 'bimwave': 'C'}.get(biz, 'A')
                outreach_leads.insert_one({
                    'lead_id': enriched_id,
                    'campaign_id': cid,
                    'email': email_lower,
                    'name': lead_data.get('name', ''),
                    'first_name': lead_data.get('first_name') or (lead_data.get('name') or '').split()[0] if lead_data.get('name') else '',
                    'company_name': lead_data.get('company_name') or lead_data.get('company', ''),
                    'title': lead_data.get('title', ''),
                    'company_industry': lead_data.get('company_industry', ''),
                    'seniority_level': lead_data.get('seniority_level', ''),
                    'classification_basket': 'D',
                    'lead_service_type': {'sfw': 'data_services', 'cogentix': 'consumer_insights', 'bimwave': 'bimwave'}.get(biz, 'data_services'),
                    'personalization_level': 'medium',
                    'workflow_status': 'not_started' if seq_idx == 0 else 'pending_scheduled',
                    'current_step': 0,
                    'next_send_at': now + start_offset,
                    'dual_fit': True,
                    'dual_fit_sequence_index': seq_idx + 1,
                    'enrolled_at': now,
                    'created_at': now,
                    'updated_at': now,
                    # Carry forward for pre-send bounce-risk guard
                    'email_source': lead_data.get('email_source'),
                })
            return

        # Regular basket (A/B/C)
        biz = BASKET_BUSINESS_MAP.get(basket)
        if not biz:
            return
        campaign = campaigns_col.find_one({'business': biz, 'is_active': True})
        if not campaign:
            logger.debug(f"No active campaign for basket {basket} ({biz}) â€” skipping auto-enrollment")
            return
        cid = campaign['campaign_id']

        # Already enrolled?
        if outreach_leads.find_one({'email': email_lower, 'campaign_id': cid}):
            return

        now = datetime.utcnow()
        outreach_leads.insert_one({
            'lead_id': enriched_id,
            'campaign_id': cid,
            'email': email_lower,
            'name': lead_data.get('name', ''),
            'first_name': lead_data.get('first_name') or (lead_data.get('name') or '').split()[0] if lead_data.get('name') else '',
            'company_name': lead_data.get('company_name') or lead_data.get('company', ''),
            'title': lead_data.get('title', ''),
            'company_industry': lead_data.get('company_industry', ''),
            'seniority_level': lead_data.get('seniority_level', ''),
            'classification_basket': basket,
            'lead_service_type': {'A': 'data_services', 'B': 'consumer_insights', 'C': 'bimwave'}.get(basket, 'data_services'),
            'personalization_level': 'medium',
            'workflow_status': 'not_started',
            'current_step': 0,
            'next_send_at': now,
            'enrolled_at': now,
            'created_at': now,
            'updated_at': now,
            # Carry forward for pre-send bounce-risk guard
            'email_source': lead_data.get('email_source'),
        })
        logger.info(f"Auto-enrolled {email_lower} into campaign {cid} (basket {basket})")

    except Exception as e:
        logger.debug(f"Auto-enrollment skipped for {email}: {e}")


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
    2. Strip guessed emails (websearch) / Store CSV email pattern
    3. deduplicate_by_email
    4. Discover email pattern via Skrapp if needed
    5. Determine lead bracket
    6. insert_into_leads_raw
    7. ALWAYS run rule-based ICP basket classification + sync to leads_enriched
    8. Auto-enroll into matching cold outreach campaign
    
    NOTE: AI classification (Gemini) is NO LONGER run at import time.
          It can still be triggered manually via bulk-classify.
    
    Args:
        payload: Raw lead data from source
        source: 'gmail' | 'websearch' | 'csv'
        source_detail: Additional context (e.g., 'email_extraction', 'linkedin_search')
        skip_classification: Legacy param (AI classification disabled at import regardless)
        icp_segment: Optional ICP slug to tag this lead
    
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

        # Strict rule: skip records where company was explicitly provided as a garbage placeholder.
        # Do NOT skip leads with no company info (e.g. LinkedIn CSE results).
        input_company = payload.get('company') or payload.get('company_name')
        if input_company and is_unknown_company(input_company):
            result['success'] = True
            result['action'] = 'skipped'
            result['error'] = 'unknown_company'
            logger.info("Lead skipped: unknown company value")
            return result

        # Step 2a: For CSV leads â€” store the email pattern from known emails
        if source == 'csv' and normalized.get('email'):
            _store_csv_email_pattern(normalized)

        # Step 2b: For websearch leads â€” strip guessed emails unless verified
        if source == 'websearch' and normalized.get('email'):
            _strip_guessed_email_if_unverified(normalized)

    except ValueError as e:
        result['error'] = str(e)
        logger.warning(f"Lead rejected: {e}")
        return result
    
    try:
        # Step 3: Check for existing lead (dedup by email, or linkedin_url for no-email leads)
        if normalized['email']:
            existing = leads_raw.find_one({'email': normalized['email']})
        else:
            existing = leads_raw.find_one({'linkedin_url': normalized['linkedin_url']})
        
        if existing:
            # Merge data (never overwrite non-null with null)
            merged = deduplicate_and_merge(existing, normalized)
            merged['updated_at'] = datetime.utcnow()

            # Conditional enrichment status
            if needs_enrichment(merged):
                merged['enrichment_status'] = 'needed'
            else:
                merged['enrichment_status'] = 'skipped'

            # Recalculate bracket after merging
            merged['lead_bracket'] = determine_lead_bracket(merged)
            
            # Update existing lead
            leads_raw.update_one(
                {'_id': existing['_id']},
                {'$set': merged}
            )
            result['email'] = merged.get('email') or normalized.get('email')
            
            # ALWAYS sync to leads_enriched with ICP basket (rule-based, no AI)
            enriched_id = sync_to_enriched(merged, str(existing['_id']))
            if enriched_id:
                leads_raw.update_one(
                    {'_id': existing['_id']},
                    {'$set': {'enriched_lead_id': enriched_id}}
                )
                # Auto-enroll into outreach if basket is A-D and has email
                _auto_enroll_in_outreach(merged, enriched_id)
            
            result['success'] = True
            result['action'] = 'updated'
            result['lead_id'] = str(existing['_id'])
            
        else:
            # New lead
            
            # Conditional enrichment status
            if needs_enrichment(normalized):
                normalized['enrichment_status'] = 'needed'
            else:
                normalized['enrichment_status'] = 'skipped'

            # Step 4: Discover email pattern via Skrapp if lead has no email
            if not normalized.get('email') and normalized.get('company_domain'):
                _discover_and_apply_email_pattern(normalized)

            # Step 5: Determine lead bracket
            normalized['lead_bracket'] = determine_lead_bracket(normalized)
            
            # Step 6: Insert into leads_raw
            insert_result = leads_raw.insert_one(normalized)

            # Step 7: ALWAYS sync to leads_enriched with ICP basket (rule-based, no AI)
            enriched_id = sync_to_enriched(normalized, str(insert_result.inserted_id))
            if enriched_id:
                leads_raw.update_one(
                    {'_id': insert_result.inserted_id},
                    {'$set': {'enriched_lead_id': enriched_id}}
                )
                # Step 8: Auto-enroll into outreach if basket is A-D and has email
                _auto_enroll_in_outreach(normalized, enriched_id)

            result['success'] = True
            result['action'] = 'inserted'
            result['lead_id'] = str(insert_result.inserted_id)
            result['email'] = normalized.get('email')

            # Mirror new leads into the canonical CRM spine (best-effort)
            try:
                from app.services.spine_connector import mirror_lead_to_spine
                mirror_lead_to_spine(normalized, source=source,
                                     source_id=result['lead_id'])
            except Exception as _spine_err:
                logger.debug(f"spine mirror skipped: {_spine_err}")

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
        # Race condition â€” another process inserted this lead
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

# Personal email providers â€” don't derive company name from these
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
        # "John Smith | VP of Sales | Acme Corp" â€” grab middle segment
        r'^[A-Z][a-z]+\s+[A-Z][a-z]+\s*[|â€“\-]\s*([^|â€“\-\n]+)\s*[|â€“\-]',
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

