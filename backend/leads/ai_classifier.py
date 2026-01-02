"""
AGENT 3 — AI CLASSIFICATION ENGINE
ChatGPT API integration with strict JSON schema enforcement

Extended with:
- OpenAI web search for company enrichment
- Email signature parsing for contact extraction
- Conversation summary generation
"""

import os
import re
import json
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
from openai import OpenAI
from pymongo import MongoClient
from dotenv import load_dotenv

from .models import (
    LeadRaw, AIClassificationOutput, AIClassificationLog,
    SeniorityLevel, Department, Persona, CompanySize, Region,
    BuyingRole, Gender, EmailThreadMessage
)

load_dotenv()


# ============== CONFIGURATION ==============

MODEL = "gpt-4o-mini"
TEMPERATURE = 0.1  # Low temperature for deterministic output
MAX_RETRIES = 3
RETRY_DELAY = 1.0

# Cost per 1K tokens (approximate for gpt-4o-mini)
INPUT_COST_PER_1K = 0.00015
OUTPUT_COST_PER_1K = 0.0006


def get_openai_api_key() -> Optional[str]:
    """
    Get OpenAI API key from database settings first, fallback to env var.
    """
    try:
        MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        settings_db = client["torpedo_settings"]
        app_settings = settings_db["app_settings"]
        
        stored = app_settings.find_one({"_id": "app_config"})
        if stored and stored.get("openai_api_key"):
            return stored["openai_api_key"]
    except Exception as e:
        print(f"Warning: Could not fetch OpenAI key from DB: {e}")
    
    # Fallback to environment variable
    return os.getenv("OPENAI_API_KEY")


# ============== PROMPT TEMPLATE ==============

SYSTEM_PROMPT = """You are a B2B lead enrichment and research expert with extensive knowledge of companies worldwide. Your task is to analyze LinkedIn profile information and DEEPLY RESEARCH to provide comprehensive lead data.

IMPORTANT: Use your extensive knowledge base to fill in as much information as possible. For well-known companies, you have accurate data - USE IT. Do NOT leave fields as null if you can reasonably infer or know the information.

You MUST respond with valid JSON only. No explanations, no markdown, just pure JSON.

Output Schema (STRICT - follow exactly):
{
  "first_name": "<string - extract first name from full name>",
  "last_name": "<string - extract last name from full name>",
  "predicted_email": "<string - generate most likely email using firstname.lastname@domain.com pattern, or firstname@domain.com for smaller companies>",
  "seniority_level": "C-Level" | "VP" | "Director" | "Manager" | "IC" | "Unknown",
  "department": "Sales" | "Marketing" | "Engineering" | "Operations" | "Finance" | "HR" | "Product" | "Other",
  "persona": "Decision Maker" | "Influencer" | "Gatekeeper" | "Practitioner",
  "buying_role": "Economic Buyer" | "Technical Buyer" | "User Buyer" | "Champion" | "Influencer" | "Unknown",
  "gender": "Male" | "Female" | "Unknown",
  "company_size": "Startup" | "SMB" | "Mid-Market" | "Enterprise",
  "region": "US" | "EU" | "APAC" | "LATAM" | "Other",
  "inferred_location": "<string - city/country - INFER from company HQ, title hints, or common locations for the role>",
  "company_name": "<string - current company name>",
  "company_domain": "<string - company domain e.g. 'company.com'>",
  "company_website": "<string - full company website URL with https://>",
  "company_employee_count": "<string - estimated employee count as number>",
  "company_employee_count_range": "<string - e.g. '1-10', '11-50', '51-200', '201-500', '501-1000', '1001-5000', '5001-10000', '10000+'>",
  "company_founded": "<string - year founded e.g. '2015'>",
  "company_industry": "<string - specific industry name>",
  "company_type": "<string - 'Public' | 'Private' | 'Startup' | 'Non-Profit' | 'Government'>",
  "company_headquarters": "<string - HQ city, state/country>",
  "company_revenue_range": "<string - e.g. '$1M-$10M', '$10M-$50M', '$50M-$100M', '$100M-$500M', '$500M-$1B', '$1B+'>",
  "company_linkedin_url": "<string - company LinkedIn URL in format https://linkedin.com/company/companyname>",
  "confidence_score": <float between 0.0 and 1.0>
}

DEEP RESEARCH INSTRUCTIONS:

1. NAME PARSING:
   - Split full name into first and last name
   - Handle prefixes (Dr., Mr., Mrs.) and suffixes (Jr., III, PhD)
   - For names like "John Smith, MBA" -> first: "John", last: "Smith"

2. EMAIL PREDICTION:
   - Generate a predicted email address using the person's name and company domain
   - Common patterns: firstname.lastname@domain.com, firstname@domain.com, flastname@domain.com
   - Use firstname.lastname@domain.com as the default pattern
   - Ensure email is lowercase and properly formatted
   - If company domain is unknown, try to infer it from company name (e.g., "Google" -> "google.com")

3. GENDER INFERENCE:
   - Use your knowledge of names worldwide to infer gender
   - Consider cultural context (Indian, Chinese, Western names, etc.)
   - Common names: John/Michael/David = Male, Sarah/Emily/Jennifer = Female
   - Only use "Unknown" if truly ambiguous

3. COMPANY RESEARCH (USE YOUR KNOWLEDGE):
   For well-known companies (Google, Microsoft, Salesforce, HubSpot, etc.), you KNOW:
   - Exact employee count ranges
   - Founding year
   - Headquarters location
   - Revenue ranges
   - Industry
   - Company type (Public/Private)
   - Website and domain
   
   For less known companies:
   - Infer domain from company name (e.g., "Acme Corp" -> "acmecorp.com")
   - Estimate size from context clues in title/snippet
   - Use industry keywords in title to determine industry
   - Infer headquarters from any location mentions

4. LOCATION INFERENCE:
   - Look for location clues in the snippet
   - If company HQ is known, use that as default
   - Look for country/city mentions in title
   - Use regional keywords (e.g., "APAC Sales" = Asia Pacific)

5. LINKEDIN URL CONSTRUCTION:
   - Company LinkedIn: https://linkedin.com/company/{company-slug}
   - Convert company name to slug (lowercase, hyphens for spaces)
   - Example: "Acme Corporation" -> "https://linkedin.com/company/acme-corporation"

Classification Rules:

SENIORITY:
- C-Level: CEO, CTO, CFO, COO, CMO, CRO, Chief, Founder, Co-Founder, President
- VP: Vice President, SVP, EVP, VP of, Head of (at large companies)
- Director: Director, Head of (at smaller companies), Principal
- Manager: Manager, Team Lead, Lead, Senior (in some contexts)
- IC: Individual Contributor, Analyst, Specialist, Engineer, Associate, Coordinator

PERSONA:
- Decision Maker: C-Level, VP with budget authority, Founders
- Influencer: Directors, Senior Managers, Principals
- Gatekeeper: Managers, Coordinators, Executive Assistants
- Practitioner: ICs, hands-on workers, engineers, analysts

BUYING ROLE:
- Economic Buyer: CFO, CEO, VP Finance, anyone controlling budget
- Technical Buyer: CTO, VP Engineering, IT Director, Technical Leads
- User Buyer: Department heads who will use the product
- Champion: Anyone who actively advocates (infer from enthusiastic language)
- Influencer: Has influence but no direct authority

COMPANY SIZE (by employee count):
- Startup: 1-50 employees
- SMB: 51-200 employees
- Mid-Market: 201-1000 employees
- Enterprise: 1000+ employees

REGION (infer from location/company HQ):
- US: United States, USA
- EU: Europe, UK, Germany, France, etc.
- APAC: Asia Pacific, India, China, Japan, Singapore, Australia
- LATAM: Latin America, Brazil, Mexico, Argentina
- Other: Middle East, Africa, etc.

Confidence score: How certain you are (0.0-1.0)
  - 0.9+: Well-known company with clear data
  - 0.7-0.9: Clear title, reasonable inferences
  - 0.5-0.7: Moderate inference required
  - <0.5: Significant guessing involved

REMEMBER: Your job is to FILL IN as much data as possible. Use your knowledge. Don't leave fields null unless truly impossible to determine."""


USER_PROMPT_TEMPLATE = """Analyze and deeply research this LinkedIn lead. Fill in ALL possible fields using your knowledge:

Name: {name}
Title: {title}
LinkedIn URL: {linkedin_url}
Additional Context: {snippet}
Known Location: {location}
Known Company: {company_name}
Known Email: {email}

INSTRUCTIONS:
1. Extract the company name from the title (e.g., "VP Sales at Google" -> Google)
2. Use your knowledge to fill in ALL company details for known companies
3. Infer the domain, website, LinkedIn URL from the company name
4. Determine employee count, revenue, founding year from your knowledge
5. Infer location from company HQ if not provided
6. Parse first/last name and infer gender
7. Fill in EVERY field possible - minimize null values

Respond with JSON only."""


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

def get_openai_client() -> OpenAI:
    api_key = get_openai_api_key()
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in settings or environment")
    return OpenAI(api_key=api_key)


# ============== CLASSIFICATION FUNCTION ==============

def classify_lead(lead: LeadRaw) -> Tuple[Optional[AIClassificationOutput], AIClassificationLog]:
    """
    Classify a single lead using ChatGPT.
    Returns: (classification_result, classification_log)
    """
    start_time = time.time()
    
    # Check cache first
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
    
    # Build prompt with all available context
    user_prompt = USER_PROMPT_TEMPLATE.format(
        name=lead.name,
        title=lead.title,
        linkedin_url=lead.linkedin_url,
        snippet=lead.snippet or "Not provided",
        location=lead.location or "Not provided",
        company_name=lead.company_name or "Not provided",
        email=lead.email or "Not provided"
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
        client = get_openai_client()
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=TEMPERATURE,
            response_format={"type": "json_object"},
            max_tokens=1000  # Increased for comprehensive responses
        )
        
        # Calculate metrics
        latency_ms = int((time.time() - start_time) * 1000)
        tokens_used = response.usage.total_tokens if response.usage else 0
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        cost_usd = (input_tokens / 1000 * INPUT_COST_PER_1K) + (output_tokens / 1000 * OUTPUT_COST_PER_1K)
        
        # Parse response
        raw_content = response.choices[0].message.content
        log.raw_response = raw_content
        log.tokens_used = tokens_used
        log.latency_ms = latency_ms
        log.cost_usd = cost_usd
        
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

COMPANY_ENRICHMENT_PROMPT = """Search the web for company information about the domain: {domain}

Research and provide comprehensive company data. Return a JSON object with these fields (use null if information is not found):

{{
    "company_name": "Official company name",
    "company_website": "Full website URL with https://",
    "company_employee_count": "Estimated employee count as number",
    "company_employee_range": "Range like '50-200', '201-500', '501-1000', '1001-5000', '5001-10000', '10000+'",
    "company_industry": "Primary industry",
    "company_type": "Private, Public, Startup, Non-Profit, or Government",
    "company_founded_year": "Year founded as number",
    "company_headquarters": "City, State/Country",
    "company_revenue_range": "Revenue range like '$1M-$10M', '$10M-$50M', '$50M-$100M', '$100M-$500M', '$500M-$1B', '$1B+'",
    "company_linkedin_url": "Company LinkedIn URL",
    "company_crunchbase_url": "Crunchbase profile URL if exists",
    "company_funding_rounds": "Funding stages like 'Seed, Series A, Series B'",
    "company_last_funding_amount": "Last funding amount like '$5M', '$50M'",
    "company_logo_url": "Company logo URL",
    "company_description": "Brief company description (1-2 sentences)"
}}

Be thorough in your web search. For well-known companies, provide accurate data. For lesser-known companies, search their website, LinkedIn, and Crunchbase for information."""


def enrich_company_via_websearch(domain: str) -> Dict[str, Any]:
    """
    Use OpenAI with web search to enrich company data based on domain.
    Results are cached for 30 days.
    
    Args:
        domain: Company domain (e.g., 'example.com')
        
    Returns:
        Dictionary with company enrichment data
    """
    if not domain:
        return {}
    
    # Check cache first
    cached = _company_cache.find_one({"domain": domain})
    if cached and cached.get("fetched_at"):
        cache_age = datetime.utcnow() - cached["fetched_at"]
        if cache_age < timedelta(days=30):
            return cached.get("data", {})
    
    try:
        client = get_openai_client()
        
        # Use GPT-4o with web search capability
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a business research assistant. Search the web thoroughly to find company information. Return only valid JSON."
                },
                {
                    "role": "user",
                    "content": COMPANY_ENRICHMENT_PROMPT.format(domain=domain)
                }
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=1500
        )
        
        # Parse response
        raw_content = response.choices[0].message.content
        data = json.loads(raw_content)
        
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

SIGNATURE_EXTRACTION_PROMPT = """Extract contact information from this email signature/body. Look for patterns typically found in email signatures.

Email content:
{email_body}

Return a JSON object with these fields (use null if not found):
{{
    "full_name": "Person's full name",
    "first_name": "First name",
    "last_name": "Last name",
    "title": "Job title/position",
    "phone": "Phone number (any format)",
    "mobile": "Mobile number if different from phone",
    "linkedin_url": "LinkedIn profile URL",
    "location": "City, State/Country",
    "company_name": "Company name from signature"
}}

Focus on the signature block, usually at the end of the email. Common patterns:
- Name on first line of signature
- Title below name
- Phone numbers with various formats
- LinkedIn URLs
- Location in signature"""


def extract_contact_from_signature(email_body: str) -> Dict[str, Any]:
    """
    Use AI to extract contact information from email signature.
    Falls back to regex patterns if AI unavailable.
    
    Args:
        email_body: Full email body text
        
    Returns:
        Dictionary with extracted contact information
    """
    if not email_body:
        return {}
    
    # First try regex extraction (faster, no API cost)
    regex_result = _extract_signature_regex(email_body)
    
    # If we got good results from regex, return them
    if regex_result.get("linkedin_url") or regex_result.get("phone"):
        return regex_result
    
    # Use AI for better extraction
    try:
        client = get_openai_client()
        
        # Only send last 1000 chars (signature is usually at the end)
        signature_text = email_body[-1000:] if len(email_body) > 1000 else email_body
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You extract contact information from email signatures. Return only valid JSON."
                },
                {
                    "role": "user",
                    "content": SIGNATURE_EXTRACTION_PROMPT.format(email_body=signature_text)
                }
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=500
        )
        
        data = json.loads(response.choices[0].message.content)
        
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

SINGLE_EMAIL_SUMMARY_PROMPT = """Analyze this email and provide a brief, actionable summary.

Subject: {subject}
From: {from_email}
Date: {date}

Email Body:
{body}

Generate a 2-3 sentence summary that captures:
- The main purpose/request of this email
- Any key details (amounts, dates, product names, action items)
- The tone/urgency level

Keep the summary under 50 words. Be specific and concise."""


def generate_single_email_summary(subject: str, body: str, from_email: str = "", date: str = "") -> str:
    """
    Generate an AI summary for a single email.
    
    Args:
        subject: Email subject line
        body: Email body text
        from_email: Sender email address
        date: Email date
        
    Returns:
        Summary string (or empty string on error)
    """
    if not body or len(body.strip()) < 10:
        return ""
    
    try:
        client = get_openai_client()
        
        # Truncate body if too long
        truncated_body = body[:3000] if len(body) > 3000 else body
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are an email assistant that creates brief, actionable summaries. Be concise and focus on what matters for business decisions."
                },
                {
                    "role": "user",
                    "content": SINGLE_EMAIL_SUMMARY_PROMPT.format(
                        subject=subject or "(no subject)",
                        from_email=from_email or "Unknown",
                        date=date or "Unknown",
                        body=truncated_body
                    )
                }
            ],
            temperature=0.2,
            max_tokens=100
        )
        
        summary = response.choices[0].message.content.strip()
        return summary
        
    except Exception as e:
        print(f"Error generating email summary: {e}")
        return ""


# ============== CONVERSATION SUMMARY GENERATION ==============

CONVERSATION_SUMMARY_PROMPT = """Analyze this email thread and provide a concise business summary.

Emails (in chronological order):
{emails}

Generate a summary that covers:
1. **Current Status**: What is the current state of this conversation?
2. **Client Needs**: What does the client/prospect want or need?
3. **Key Points**: Important details discussed (pricing, timelines, requirements)
4. **Next Steps**: What action is needed next?
5. **Blockers**: Any obstacles or concerns mentioned?

Keep the summary under 150 words. Be specific and actionable. Use bullet points for clarity.

Return as plain text, not JSON."""


def generate_conversation_summary(email_threads: List[Dict[str, Any]]) -> str:
    """
    Generate an AI summary of email conversation threads.
    Called automatically after every new email.
    
    Args:
        email_threads: List of email thread dictionaries
        
    Returns:
        Summary string
    """
    if not email_threads:
        return ""
    
    try:
        client = get_openai_client()
        
        # Format emails for the prompt
        emails_text = ""
        for i, email in enumerate(sorted(email_threads, key=lambda x: x.get("date", datetime.min)), 1):
            direction = "↗️ SENT" if email.get("direction") == "sent" else "↙️ RECEIVED"
            date_str = email.get("date", "Unknown date")
            if isinstance(date_str, datetime):
                date_str = date_str.strftime("%Y-%m-%d %H:%M")
            
            emails_text += f"""
--- Email {i} ({direction}) - {date_str} ---
Subject: {email.get("subject", "No subject")}
From: {email.get("from_email", "Unknown")}
Preview: {email.get("body_preview", email.get("body_full", "")[:300])}

"""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a sales assistant that summarizes email conversations. Be concise, specific, and focus on actionable insights."
                },
                {
                    "role": "user",
                    "content": CONVERSATION_SUMMARY_PROMPT.format(emails=emails_text)
                }
            ],
            temperature=0.3,
            max_tokens=300
        )
        
        summary = response.choices[0].message.content.strip()
        return summary
        
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
