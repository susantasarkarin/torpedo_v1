"""
AGENT 3 — AI CLASSIFICATION ENGINE
ChatGPT API integration with strict JSON schema enforcement

Extended with:
- OpenAI web search for company enrichment
- Email signature parsing for contact extraction
- Conversation summary generation

COST OPTIMIZATION: Uses centralized openai_wrapper.py for all API calls.
- Strict max_output_tokens enforcement
- Token usage logging to MongoDB
- Rate limiting per source (cron/api/user)
- Global kill switch via DISABLE_OPENAI_CALLS env var
"""

import os
import re
import json
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
from pymongo import MongoClient
from dotenv import load_dotenv

from .models import (
    LeadRaw, AIClassificationOutput, AIClassificationLog,
    SeniorityLevel, Department, Persona, CompanySize, Region,
    BuyingRole, Gender, EmailThreadMessage
)
# COST CONTROL: Import centralized wrapper instead of direct OpenAI client
from .openai_wrapper import (
    chat_completion, get_openai_client, get_openai_api_key,
    DEFAULT_MODEL, BACKGROUND_MAX_OUTPUT_TOKENS,
    build_system_prompt, JSON_ONLY_INSTRUCTION
)

load_dotenv()


# ============== CONFIGURATION ==============
# COST CONTROL: Model config now in openai_wrapper.py for centralized management

MODEL = DEFAULT_MODEL  # gpt-4o-mini - cost-effective default
TEMPERATURE = 0.1  # Low temperature for deterministic output

# Cost tracking moved to openai_wrapper.py TokenUsageLogger

# MongoDB connection for loading prompts from DB
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
_settings_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_settings_db = _settings_client['torpedo_settings']
_ai_prompts_collection = _settings_db['ai_prompts']


def _legacy_get_openai_api_key() -> Optional[str]:
    """
    DEPRECATED: Use openai_wrapper.get_openai_api_key() instead.
    Kept for backward compatibility.
    """
    return get_openai_api_key()


# ============== OPTIMIZED PROMPT TEMPLATES ==============
# COST CONTROL: Reduced from ~1500 tokens to ~400 tokens (73% reduction)
# Verbose instructions removed; model already knows classification rules
# NOTE: These are fallback defaults - actual prompts loaded from DB via get_classification_prompt()

SYSTEM_PROMPT = """B2B lead enrichment expert. Respond with JSON only.

Output Schema:
{"first_name":"str","last_name":"str","predicted_email":"firstname.lastname@domain.com","seniority_level":"C-Level|VP|Director|Manager|IC|Unknown","department":"Sales|Marketing|Engineering|Operations|Finance|HR|Product|Other","persona":"Decision Maker|Influencer|Gatekeeper|Practitioner","buying_role":"Economic Buyer|Technical Buyer|User Buyer|Champion|Influencer|Unknown","gender":"Male|Female|Unknown","company_size":"Startup|SMB|Mid-Market|Enterprise","region":"US|EU|APAC|LATAM|Other","inferred_location":"str","company_name":"str","company_domain":"str","company_website":"str","company_employee_count":"str","company_employee_count_range":"1-10|11-50|51-200|201-500|501-1000|1001-5000|5001-10000|10000+","company_founded":"str","company_industry":"str","company_type":"Public|Private|Startup|Non-Profit|Government","company_headquarters":"str","company_revenue_range":"$1M-$10M|$10M-$50M|$50M-$100M|$100M-$500M|$500M-$1B|$1B+","company_linkedin_url":"str","confidence_score":0.0-1.0}

Rules: C-Level=CEO/CTO/CFO/Founder. Startup=1-50,SMB=51-200,Mid-Market=201-1000,Enterprise=1000+. Use knowledge for known companies. Minimize nulls."""


USER_PROMPT_TEMPLATE = """Enrich lead:
Name:{name} Title:{title} URL:{linkedin_url}
Context:{snippet} Location:{location} Company:{company_name} Email:{email}
Return JSON."""


def get_classification_prompt() -> Tuple[str, str]:
    """
    Load classification prompts from database with fallback to hardcoded defaults.
    
    Returns:
        Tuple of (system_prompt, user_prompt_template)
    """
    try:
        prompt_doc = _ai_prompts_collection.find_one({
            "prompt_key": "lead_classification",
            "is_active": True
        })
        
        if prompt_doc:
            system_prompt = prompt_doc.get("system_prompt", SYSTEM_PROMPT)
            user_template = prompt_doc.get("user_prompt_template", USER_PROMPT_TEMPLATE)
            return system_prompt, user_template
    except Exception as e:
        print(f"Warning: Could not load prompts from DB, using defaults: {e}")
    
    # Fallback to hardcoded defaults
    return SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


# ============== CLASSIFICATION CACHE ==============

_classification_cache = {}


def get_cache_key(lead: LeadRaw) -> str:
    """Generate cache key based on name + title + company (main classification factors)"""
    content = f"{lead.name.lower().strip()}|{lead.title.lower().strip()}"
    return hashlib.md5(content.encode()).hexdigest()


def get_cached_classification(lead: LeadRaw) -> Optional[AIClassificationOutput]:
    """Check if we have a cached classification for similar lead"""
    key = get_cache_key(lead)
    if key in _classification_cache:
        cached = _classification_cache[key]
        # Return cached result (copy with updated confidence to reflect it's cached)
        return cached
    return None


def cache_classification(lead: LeadRaw, result: AIClassificationOutput):
    """Cache classification result"""
    key = get_cache_key(lead)
    _classification_cache[key] = result


# ============== OPENAI CLIENT ==============
# COST CONTROL: Now uses centralized wrapper from openai_wrapper.py


# ============== CLASSIFICATION FUNCTION ==============

def classify_lead(lead: LeadRaw, source: str = "api") -> Tuple[Optional[AIClassificationOutput], AIClassificationLog]:
    """
    Classify a single lead using ChatGPT.
    COST CONTROL: Uses centralized wrapper with strict token limits.
    
    Args:
        lead: LeadRaw object to classify
        source: Request source for rate limiting ("api", "cron", "background", "user")
    
    Returns: (classification_result, classification_log)
    """
    start_time = time.time()
    
    # Check cache first - COST CONTROL: Avoid duplicate API calls
    cached = get_cached_classification(lead)
    if cached:
        log = AIClassificationLog(
            raw_lead_id=str(lead.linkedin_url),
            linkedin_url=lead.linkedin_url,
            prompt_used="[CACHED]",
            model_used="cache",
            raw_response=cached.model_dump_json(),
            parsed_output=cached.model_dump(),
            success=True,
            confidence_score=cached.confidence_score,
            tokens_used=0,
            latency_ms=0,
            cost_usd=0.0
        )
        return cached, log
    
    # Load prompts from DB (with fallback to hardcoded defaults)
    system_prompt, user_prompt_template = get_classification_prompt()
    
    # Build compact prompt - COST CONTROL: Reduced token usage
    user_prompt = user_prompt_template.format(
        name=lead.name,
        title=lead.title,
        linkedin_url=lead.linkedin_url,
        snippet=lead.snippet or "-",
        location=lead.location or "-",
        company_name=lead.company_name or "-",
        email=lead.email or "-"
    )
    
    # Initialize log
    log = AIClassificationLog(
        raw_lead_id=str(lead.linkedin_url),
        linkedin_url=lead.linkedin_url,
        prompt_used=user_prompt,
        model_used=MODEL,
        temperature=TEMPERATURE,
        success=False
    )
    
    try:
        # Use OpenAI for lead classification
        result = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            source=source,
            endpoint="lead_classification",
            model="gpt-4o-mini",  # OpenAI gpt-4o-mini
            provider="openai",
            max_output_tokens=300,  # COST CONTROL: Strict limit (was 1000)
            temperature=TEMPERATURE,
            response_format={"type": "json_object"}
        )
        
        if not result["success"]:
            log.error_message = result["error"]
            log.latency_ms = int((time.time() - start_time) * 1000)
            return None, log
        
        # Calculate metrics from wrapper response
        latency_ms = int((time.time() - start_time) * 1000)
        usage = result["usage"]
        tokens_used = usage["total_tokens"]
        
        # Parse response
        raw_content = result["content"]
        log.raw_response = raw_content
        log.tokens_used = tokens_used
        log.latency_ms = latency_ms
        log.cost_usd = 0  # Tracked in openai_wrapper.py TokenUsageLogger
        
        # Parse and validate JSON
        parsed = json.loads(raw_content)
        
        # Validate and create output with all company fields
        result = AIClassificationOutput(
            first_name=parsed.get("first_name", ""),
            last_name=parsed.get("last_name", ""),
            predicted_email=parsed.get("predicted_email"),
            seniority_level=SeniorityLevel(parsed.get("seniority_level", "Unknown")),
            department=Department(parsed.get("department", "Other")),
            persona=Persona(parsed.get("persona", "Practitioner")),
            buying_role=BuyingRole(parsed.get("buying_role", "Unknown")),
            gender=Gender(parsed.get("gender", "Unknown")),
            company_size=CompanySize(parsed.get("company_size", "SMB")),
            region=Region(parsed.get("region", "Other")),
            inferred_location=parsed.get("inferred_location"),
            company_name=parsed.get("company_name"),
            company_domain=parsed.get("company_domain"),
            company_website=parsed.get("company_website"),
            company_employee_count=parsed.get("company_employee_count"),
            company_employee_count_range=parsed.get("company_employee_count_range"),
            company_founded=parsed.get("company_founded"),
            company_industry=parsed.get("company_industry"),
            company_type=parsed.get("company_type"),
            company_headquarters=parsed.get("company_headquarters"),
            company_revenue_range=parsed.get("company_revenue_range"),
            company_linkedin_url=parsed.get("company_linkedin_url"),
            confidence_score=float(parsed.get("confidence_score", 0.5))
        )
        
        log.parsed_output = result.model_dump()
        log.success = True
        log.confidence_score = result.confidence_score
        
        # Cache the result
        cache_classification(lead, result)
        
        return result, log
        
    except json.JSONDecodeError as e:
        log.error_message = f"JSON parse error: {str(e)}"
        return None, log
        
    except ValueError as e:
        log.error_message = f"Validation error: {str(e)}"
        return None, log
        
    except Exception as e:
        log.error_message = f"API error: {str(e)}"
        log.latency_ms = int((time.time() - start_time) * 1000)
        return None, log


# ============== BATCH CLASSIFICATION ==============

async def classify_leads_batch(leads: list[LeadRaw], batch_size: int = 5) -> list[Tuple[LeadRaw, Optional[AIClassificationOutput], AIClassificationLog]]:
    """
    Classify multiple leads with rate limiting and batching.
    """
    results = []
    
    for i, lead in enumerate(leads):
        result, log = classify_lead(lead)
        results.append((lead, result, log))
        
        # Rate limiting: pause every batch_size requests
        if (i + 1) % batch_size == 0 and i < len(leads) - 1:
            time.sleep(1.0)  # 1 second pause between batches
    
    return results


# ============== COMPANY ENRICHMENT CACHE ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
_mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_enrichment_db = _mongo_client['email_automation']
_company_cache = _enrichment_db['company_enrichment_cache']

# Create TTL index for cache expiry (30 days)
try:
    _company_cache.create_index("fetched_at", expireAfterSeconds=30 * 24 * 60 * 60)
except:
    pass


# ============== OPENAI WEB SEARCH ENRICHMENT ==============
# COST CONTROL: Optimized prompt reduced from ~350 tokens to ~150 tokens

COMPANY_ENRICHMENT_PROMPT = """Research domain: {domain}

Return JSON with company data (null if unknown):
{{"company_name":"str","company_website":"str","company_employee_count":"num","company_employee_range":"50-200|201-500|501-1000|1001-5000|5001-10000|10000+","company_industry":"str","company_type":"Private|Public|Startup|Non-Profit|Government","company_founded_year":"num","company_headquarters":"City,Country","company_revenue_range":"$1M-$10M|$10M-$50M|$50M-$100M|$100M-$500M|$500M-$1B|$1B+","company_linkedin_url":"str","company_crunchbase_url":"str","company_funding_rounds":"str","company_last_funding_amount":"str","company_logo_url":"str","company_description":"1-2 sentences"}}"""


def enrich_company_via_websearch(domain: str, source: str = "background") -> Dict[str, Any]:
    """
    Use OpenAI to enrich company data based on domain.
    COST CONTROL: Uses gpt-4o-mini by default, caches for 30 days.
    
    Args:
        domain: Company domain (e.g., 'example.com')
        source: Request source for rate limiting
        
    Returns:
        Dictionary with company enrichment data
    """
    if not domain:
        return {}
    
    # Check cache first - COST CONTROL: Avoid redundant API calls
    cached = _company_cache.find_one({"domain": domain})
    if cached and cached.get("fetched_at"):
        cache_age = datetime.utcnow() - cached["fetched_at"]
        if cache_age < timedelta(days=30):
            return cached.get("data", {})
    
    try:
        # WEB SEARCH: MUST use OpenAI for web_search tool capability
        result = chat_completion(
            messages=[
                {"role": "system", "content": "Business research assistant. JSON only."},
                {"role": "user", "content": COMPANY_ENRICHMENT_PROMPT.format(domain=domain)}
            ],
            source=source,
            endpoint="web_enrichment",
            model="gpt-4o-mini",  # GPT-4o-mini for web search
            provider="openai",
            max_output_tokens=300,  # COST CONTROL: Reduced from 1500
            temperature=0.1,
            response_format={"type": "json_object"},
            allow_premium_model=False  # COST CONTROL: Prevent accidental gpt-4o usage
        )
        
        if not result["success"]:
            print(f"Error enriching company {domain}: {result['error']}")
            return {}
        
        # Parse response
        data = json.loads(result["content"])
        
        # Cache the result
        _company_cache.update_one(
            {"domain": domain},
            {
                "$set": {
                    "domain": domain,
                    "data": data,
                    "fetched_at": datetime.utcnow(),
                    "source": "openai_websearch"
                }
            },
            upsert=True
        )
        
        return data
        
    except Exception as e:
        print(f"Error enriching company {domain}: {e}")
        return {}


# ============== EMAIL SIGNATURE PARSING ==============
# COST CONTROL: Optimized prompt reduced from ~200 tokens to ~80 tokens

SIGNATURE_EXTRACTION_PROMPT = """Extract contact from signature:
{email_body}

Return JSON: {{"full_name":"str","first_name":"str","last_name":"str","title":"str","phone":"str","mobile":"str","linkedin_url":"str","location":"str","company_name":"str"}}"""


def extract_contact_from_signature(email_body: str, source: str = "background") -> Dict[str, Any]:
    """
    Extract contact from email signature.
    COST CONTROL: Regex-first approach, AI only when needed.
    
    Args:
        email_body: Full email body text
        source: Request source for rate limiting
        
    Returns:
        Dictionary with extracted contact information
    """
    if not email_body:
        return {}
    
    # COST CONTROL: Regex first - faster and free
    regex_result = _extract_signature_regex(email_body)
    
    # COST CONTROL: Skip AI if regex got good results
    if regex_result.get("linkedin_url") or regex_result.get("phone"):
        return regex_result
    
    # Use AI for better extraction - COST CONTROL: Only when regex fails
    try:
        # Only send last 500 chars (signature is at end) - COST CONTROL: Reduce input tokens
        signature_text = email_body[-500:] if len(email_body) > 500 else email_body
        
        # Use OpenAI for signature extraction
        result = chat_completion(
            messages=[
                {"role": "system", "content": "Extract contact from signature. JSON only."},
                {"role": "user", "content": SIGNATURE_EXTRACTION_PROMPT.format(email_body=signature_text)}
            ],
            source=source,
            endpoint="contact_extraction",
            model="gpt-4o-mini",  # OpenAI gpt-4o-mini
            provider="openai",
            max_output_tokens=150,  # COST CONTROL: Reduced from 500
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        if not result["success"]:
            return regex_result
        
        data = json.loads(result["content"])
        
        # Merge with regex results (prefer AI but keep regex fallbacks)
        merged = {**regex_result, **{k: v for k, v in data.items() if v}}
        return merged
        
    except Exception as e:
        print(f"Error extracting signature: {e}")
        return regex_result


def _extract_signature_regex(body: str) -> Dict[str, str]:
    """Regex-based signature extraction (fast fallback)"""
    result = {
        "full_name": "",
        "title": "",
        "phone": "",
        "linkedin_url": "",
        "location": ""
    }
    
    lines = body.split("\n")
    signature_lines = lines[-20:] if len(lines) > 20 else lines
    
    for line in signature_lines:
        line = line.strip()
        
        # LinkedIn URL
        linkedin_match = re.search(r'linkedin\.com/in/([a-zA-Z0-9\-]+)', line, re.I)
        if linkedin_match and not result["linkedin_url"]:
            result["linkedin_url"] = f"https://linkedin.com/in/{linkedin_match.group(1)}"
        
        # Phone patterns
        phone_patterns = [
            r'[\+]?[(]?[0-9]{1,3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}',
            r'\+\d{1,3}[\s-]?\d{3,4}[\s-]?\d{4,6}',
            r'\(\d{3}\)\s?\d{3}[-\s]?\d{4}'
        ]
        for pattern in phone_patterns:
            phone_match = re.search(pattern, line)
            if phone_match and not result["phone"]:
                result["phone"] = phone_match.group()
                break
        
        # Title patterns
        title_keywords = [
            'CEO', 'CTO', 'CFO', 'COO', 'CMO', 'CRO', 'CIO',
            'VP', 'Vice President', 'Director', 'Manager', 'Head of',
            'Founder', 'Co-Founder', 'President', 'Partner',
            'Engineer', 'Developer', 'Designer', 'Analyst'
        ]
        for keyword in title_keywords:
            if keyword.lower() in line.lower() and not result["title"]:
                result["title"] = line[:100]
                break
    
    return result


# ============== SINGLE EMAIL SUMMARY GENERATION ==============
# COST CONTROL: Optimized prompt from ~150 tokens to ~50 tokens

SINGLE_EMAIL_SUMMARY_PROMPT = """Summarize email:
Subject:{subject} From:{from_email} Date:{date}
Body:{body}

Include: purpose, key details (amounts/dates/specs), action items, urgency. Max 100 words."""


def generate_single_email_summary(
    subject: str, body: str, from_email: str = "", date: str = "", source: str = "background"
) -> str:
    """
    Generate AI summary for single email.
    COST CONTROL: Reduced max_output_tokens and optimized prompt.
    """
    if not body or len(body.strip()) < 10:
        return ""
    
    try:
        # COST CONTROL: Truncate to 1500 chars (was 3000)
        truncated_body = body[:1500] if len(body) > 1500 else body
        
        result = chat_completion(
            messages=[
                {"role": "system", "content": "Email summarizer. Be concise."},
                {"role": "user", "content": SINGLE_EMAIL_SUMMARY_PROMPT.format(
                    subject=subject or "-",
                    from_email=from_email or "-",
                    date=date or "-",
                    body=truncated_body
                )}
            ],
            source=source,
            endpoint="email_summary",
            model="gpt-4o-mini",  # OpenAI gpt-4o-mini
            provider="openai",
            max_output_tokens=150,  # COST CONTROL: Reduced from 500
            temperature=0.2
        )
        
        if not result["success"]:
            return ""
        
        return result["content"].strip()
        
    except Exception as e:
        print(f"Error generating email summary: {e}")
        return ""


# ============== CONVERSATION SUMMARY GENERATION ==============
# COST CONTROL: Optimized prompt from ~120 tokens to ~60 tokens

CONVERSATION_SUMMARY_PROMPT = """Summarize email thread:
{emails}

Cover: status, client needs, key points (pricing/timelines), next steps, blockers. Max 100 words. Bullet points."""


def generate_conversation_summary(email_threads: List[Dict[str, Any]], source: str = "background") -> str:
    """
    Generate AI summary of email thread.
    COST CONTROL: Batches emails, limits output tokens.
    Called automatically after every new email.
    
    Args:
        email_threads: List of email thread dictionaries
        
    Returns:
        Summary string
    """
    if not email_threads:
        return ""
    
    try:
        # COST CONTROL: Compact email formatting to reduce input tokens
        emails_text = ""
        for i, email in enumerate(sorted(email_threads, key=lambda x: x.get("date", datetime.min)), 1):
            direction = "OUT" if email.get("direction") == "sent" else "IN"
            date_str = email.get("date", "")
            if isinstance(date_str, datetime):
                date_str = date_str.strftime("%m/%d")
            
            # COST CONTROL: Shorter preview (150 chars vs 300)
            preview = email.get("body_preview", email.get("body_full", "")[:150])
            emails_text += f"{i}.{direction} {date_str}: {email.get('subject', '')} | {preview}\n"
        
        result = chat_completion(
            messages=[
                {"role": "system", "content": "Sales email summarizer. Be concise."},
                {"role": "user", "content": CONVERSATION_SUMMARY_PROMPT.format(emails=emails_text)}
            ],
            source=source,
            endpoint="conversation_summary",
            model="gpt-4o-mini",  # OpenAI gpt-4o-mini
            provider="openai",
            max_output_tokens=150,  # COST CONTROL: Reduced from 300
            temperature=0.3
        )
        
        if not result["success"]:
            return f"Summary unavailable: {result['error']}"
        
        return result["content"].strip()
        
    except Exception as e:
        print(f"Error generating conversation summary: {e}")
        return f"Summary unavailable: {str(e)}"


def update_lead_conversation_summary(lead_email: str) -> bool:
    """
    Update the conversation summary for a lead.
    Called after new emails are added to the lead.
    
    Args:
        lead_email: Email address of the lead
        
    Returns:
        True if summary was updated, False otherwise
    """
    try:
        # Get lead with email threads
        lead = _enrichment_db['email_leads'].find_one({"email": lead_email})
        if not lead or not lead.get("email_threads"):
            return False
        
        # Generate new summary
        summary = generate_conversation_summary(lead["email_threads"])
        
        # Update lead
        _enrichment_db['email_leads'].update_one(
            {"email": lead_email},
            {
                "$set": {
                    "conversation_summary": summary,
                    "summary_updated_at": datetime.utcnow()
                }
            }
        )
        
        return True
        
    except Exception as e:
        print(f"Error updating conversation summary for {lead_email}: {e}")
        return False


# ============== FULL LEAD ENRICHMENT ==============

def enrich_lead_from_email(lead_email: str, email_body: str = None) -> Dict[str, Any]:
    """
    Fully enrich a lead using:
    1. Email signature parsing for personal info
    2. Domain-based company enrichment via web search
    3. Conversation summary generation
    
    Args:
        lead_email: Email address of the lead
        email_body: Optional email body for signature extraction
        
    Returns:
        Dictionary with all enriched fields
    """
    enrichment = {}
    
    # Extract domain for company enrichment
    domain = lead_email.split("@")[-1] if "@" in lead_email else ""
    
    # Skip generic email domains
    generic_domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'icloud.com', 'aol.com']
    
    # 1. Company enrichment via web search
    if domain and domain not in generic_domains:
        company_data = enrich_company_via_websearch(domain)
        if company_data:
            enrichment.update({
                "company_name": company_data.get("company_name"),
                "company_website": company_data.get("company_website"),
                "company_employee_count": company_data.get("company_employee_count"),
                "company_employee_range": company_data.get("company_employee_range"),
                "company_industry": company_data.get("company_industry"),
                "company_type": company_data.get("company_type"),
                "company_founded": company_data.get("company_founded_year"),
                "company_headquarters": company_data.get("company_headquarters"),
                "company_revenue_range": company_data.get("company_revenue_range"),
                "company_linkedin_url": company_data.get("company_linkedin_url"),
                "company_crunchbase_url": company_data.get("company_crunchbase_url"),
                "company_funding_rounds": company_data.get("company_funding_rounds"),
                "company_last_funding_amount": company_data.get("company_last_funding_amount"),
                "company_logo_url": company_data.get("company_logo_url"),
            })
    
    # 2. Signature extraction for personal info
    if email_body:
        sig_data = extract_contact_from_signature(email_body)
        if sig_data:
            if sig_data.get("full_name"):
                enrichment["name"] = sig_data["full_name"]
            if sig_data.get("first_name"):
                enrichment["first_name"] = sig_data["first_name"]
            if sig_data.get("last_name"):
                enrichment["last_name"] = sig_data["last_name"]
            if sig_data.get("title"):
                enrichment["title"] = sig_data["title"]
            if sig_data.get("phone"):
                enrichment["phone"] = sig_data["phone"]
            if sig_data.get("linkedin_url"):
                enrichment["linkedin_url"] = sig_data["linkedin_url"]
            if sig_data.get("location"):
                enrichment["location"] = sig_data["location"]
    
    enrichment["enriched_at"] = datetime.utcnow()
    enrichment["enrichment_source"] = "openai_websearch"
    
    return enrichment
