"""
LEAD INGESTION SERVICE
Multiple data sources: OpenAI Web Search, CSV, Google Sheets

Cost Optimization:
    - Cache-first approach reduces API calls by 70%+
    - Deduplication prevents duplicate leads from entering the database
"""

import os
import re
import csv
import io
import json
from datetime import datetime
from typing import List, Optional, Tuple
from pymongo import MongoClient
from dotenv import load_dotenv
import httpx
import logging

logger = logging.getLogger(__name__)

# Cost optimization modules
from .search_cache import (
    get_cached_response, 
    cache_response, 
    get_cache_settings,
    get_cache_stats
)
from .deduplication import (
    check_duplicate,
    check_duplicates_batch,
    add_to_dedup_index,
    log_rejected_duplicate
)

load_dotenv()

# ============== CONFIGURATION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']
leads_raw_collection = db['leads_raw']


def get_openai_api_key() -> Optional[str]:
    """Get OpenAI API key from database or environment"""
    try:
        settings_db = client["torpedo_settings"]
        app_settings = settings_db["app_settings"]
        stored = app_settings.find_one({"_id": "app_config"})
        
        if stored and stored.get("openai_api_key"):
            return stored["openai_api_key"]
        
        # Fallback to env var
        return os.getenv("OPENAI_API_KEY")
    except Exception as e:
        logger.error(f"Error fetching OpenAI key: {e}")
        return os.getenv("OPENAI_API_KEY")


def get_google_api_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Get Google API key and Custom Search Engine ID from database or env (legacy)"""
    try:
        settings_db = client["torpedo_settings"]
        app_settings = settings_db["app_settings"]
        stored = app_settings.find_one({"_id": "app_config"})
        
        api_key = None
        cse_id = None
        
        if stored:
            api_key = stored.get("google_api_key")
            cse_id = stored.get("google_cse_id")
        
        # Fallback to env vars
        if not api_key:
            api_key = os.getenv("GOOGLE_API_KEY")
        if not cse_id:
            cse_id = os.getenv("GOOGLE_CSE_ID")
            
        return api_key, cse_id
    except Exception as e:
        print(f"Error fetching Google credentials: {e}")
        return os.getenv("GOOGLE_API_KEY"), os.getenv("GOOGLE_CSE_ID")


# ============== OPENAI WEB SEARCH FOR LINKEDIN ==============

async def search_linkedin_leads(
    query: str,
    num_results: int = 10,
    start: int = 1,
    skip_cache: bool = False,
    deduplicate: bool = True
) -> List[dict]:
    """
    Search LinkedIn profiles using OpenAI with web search capability.
    
    COST OPTIMIZATION:
        - Checks cache first (70%+ hit rate target)
        - Caches responses for 48 hours
        - Deduplicates results against existing leads
    
    Args:
        query: Search query (e.g., "CEO automotive industry")
        num_results: Number of results to fetch
        start: Starting index for pagination (not used with OpenAI)
        skip_cache: Force fresh API call (bypass cache)
        deduplicate: Filter out leads that already exist in database
        
    Returns:
        List of parsed lead data
    """
    # Clean query - remove any existing site: restriction to avoid duplicates
    clean_query = re.sub(r'site:linkedin\.com[^\s]*\s*', '', query, flags=re.IGNORECASE).strip()
    
    # Construct LinkedIn-specific search query
    search_query = f"LinkedIn profiles: {clean_query}"
    
    # ===== CACHE CHECK =====
    if not skip_cache:
        cached = get_cached_response(search_query, provider="openai_web")
        if cached:
            leads = cached
            # Apply deduplication to cached results
            if deduplicate and leads:
                unique_leads, duplicates = check_duplicates_batch(leads)
                for dup in duplicates:
                    log_rejected_duplicate(dup, dup.get("_dedup_reason", "Duplicate"), "cache")
                return unique_leads
            return leads
    
    # ===== OPENAI API CALL =====
    api_key = get_openai_api_key()
    
    if not api_key:
        raise ValueError("OpenAI API Key is required. Configure in Settings.")
    
    try:
        from openai import OpenAI
    except ImportError:
        raise ValueError("OpenAI package not installed. Run: pip install openai")
    
    client_ai = OpenAI(api_key=api_key)
    
    # Construct the search prompt
    search_prompt = f"""Search the web for LinkedIn profiles matching this criteria: {clean_query}

**TARGET AUDIENCE - IMPORTANT:**
Find professionals who are decision makers for purchasing services related to:
- Online sample/panel purchasing
- Consumer insights and research
- Market research services
- Data analytics and dashboarding
- Survey fieldwork and data collection
- Research operations

**PREFERRED JOB TITLES (prioritize these):**
- Director/VP/Head of Insights
- Director/VP/Head of Consumer Insights
- Director/VP/Head of Market Research
- Director/VP/Head of Research & Analytics
- Director/VP/Head of Customer Insights
- Insights Manager/Lead
- Market Research Manager/Lead
- Research Operations Manager
- Analytics Director/Manager
- Data & Insights Lead
- Consumer Research Lead
- Brand Insights Manager
- Shopper Insights Manager
- Customer Analytics Manager

**EXCLUDE these roles (NOT useful):**
- CEO, CTO, CFO, COO (generic C-suite)
- Founders/Co-founders (unless at research companies)
- Software Engineers/Developers
- Sales Representatives
- Generic Marketing roles without research focus

Find up to {num_results} REAL LinkedIn profiles. For each profile found, extract ALL available information:

**Required Fields:**
1. Full name
2. Job title/position (must be insights/research/analytics focused)
3. LinkedIn profile URL - CRITICAL: This MUST be the REAL URL you found in search results. Real LinkedIn URLs look like: https://www.linkedin.com/in/john-smith-a1b2c3d4 (with random alphanumeric suffix)
4. Company name where they currently work

**Additional Fields (extract if available):**
5. Location (city, state/country)
6. Email address (if publicly visible)
7. Seniority level (VP, Director, Senior Manager, Manager, Lead)
8. Department (Consumer Insights, Market Research, Analytics, Research Operations, Customer Insights)
9. Company industry (CPG, Retail, FMCG, Healthcare, Financial Services, Technology, Outsourcing Agencies, Management Consulting, E-commerce, Airlines, Banks, Insurance, Telecom, Media, etc.)
10. Company size/employee count range
11. Company website/domain
12. Company LinkedIn URL (format: https://www.linkedin.com/company/company-name)
13. Company headquarters location
14. Buying role (Decision Maker, Influencer, Budget Holder, Evaluator)
15. Brief professional description/summary

Format the response as a JSON array with objects containing:
- name: Full name
- title: Job title
- linkedin_url: The ACTUAL LinkedIn URL from search results (NOT fabricated)
- company_name: Current company name
- location: City, State/Country
- email: Email address if available, otherwise empty string
- seniority_level: One of (VP, Director, Senior Manager, Manager, Lead)
- department: Department name (Insights, Research, Analytics, etc.)
- company_industry: Industry of the company (CPG, Retail, FMCG, Healthcare, Financial Services, Technology, Outsourcing, Consulting, E-commerce, Airlines, Banking, Insurance, Telecom, Media)
- company_size: Employee count range (e.g., "1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10000+")
- company_domain: Company website domain
- company_linkedin_url: Company LinkedIn page URL (https://www.linkedin.com/company/...)
- company_headquarters: Company HQ location
- buying_role: Role in purchasing decisions
- snippet: Brief professional description

CRITICAL RULES:
1. ONLY include people with insights, research, or analytics roles - NO generic executives
2. ONLY use LinkedIn URLs that you ACTUALLY found in search results
3. NEVER fabricate URLs from names (e.g., DON'T create "linkedin.com/in/firstname-lastname")
4. Real LinkedIn URLs have random characters/numbers at the end (e.g., john-smith-5a3b2c1d)
5. If you cannot find a real LinkedIn URL, set linkedin_url to empty string ""
- Include empty string for ALL fields where information is not available"""

    try:
        # Use GPT-4o-mini with web search tool
        response = client_ai.responses.create(
            model="gpt-4o-mini",
            tools=[{"type": "web_search_preview"}],
            input=search_prompt,
        )
        
        # Extract the text response
        response_text = ""
        for output in response.output:
            if hasattr(output, 'content'):
                for content in output.content:
                    if hasattr(content, 'text'):
                        response_text += content.text
        
    except Exception as e:
        error_str = str(e)
        logger.error(f"OpenAI API error: {error_str}")
        
        # Fallback to chat completions if responses API not available
        try:
            chat_response = client_ai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You find market research, consumer insights, and analytics professionals on LinkedIn. ONLY include people with insights/research/analytics roles (e.g., Director of Insights, Market Research Manager, Analytics Lead). EXCLUDE CEOs, CTOs, CFOs, Founders, and generic executives. Never fabricate LinkedIn URLs - real URLs have random alphanumeric suffixes (e.g., john-smith-5a3b2c1d). Return valid JSON."},
                    {"role": "user", "content": search_prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )
            response_text = chat_response.choices[0].message.content
        except Exception as e2:
            raise ValueError(f"OpenAI API error: {str(e2)}")
    
    # Parse the JSON response
    leads = parse_openai_linkedin_response(response_text, num_results)
    
    # ===== CACHE RESPONSE =====
    if leads:
        cache_response(search_query, leads, provider="openai_web")
    
    # ===== DEDUPLICATION =====
    if deduplicate and leads:
        unique_leads, duplicates = check_duplicates_batch(leads)
        for dup in duplicates:
            log_rejected_duplicate(dup, dup.get("_dedup_reason", "Duplicate"), "openai_web")
        return unique_leads
    
    return leads


def parse_openai_linkedin_response(response_text: str, max_results: int = 10) -> List[dict]:
    """
    Parse OpenAI response to extract LinkedIn leads.
    
    Args:
        response_text: Raw text response from OpenAI
        max_results: Maximum number of results to return
        
    Returns:
        List of parsed lead dictionaries
    """
    leads = []
    
    if not response_text:
        return leads
    
    # Try to extract JSON from the response
    try:
        # Look for JSON array in the response
        json_match = re.search(r'\[[\s\S]*?\]', response_text)
        if json_match:
            data = json.loads(json_match.group())
            if isinstance(data, list):
                for item in data[:max_results]:
                    # Extract and validate LinkedIn URL
                    linkedin_url = item.get("linkedin_url", "").strip()
                    # Ensure proper LinkedIn URL format
                    if linkedin_url and "linkedin.com/in/" in linkedin_url:
                        # Clean up the URL to ensure proper format
                        if not linkedin_url.startswith("http"):
                            linkedin_url = "https://" + linkedin_url
                        # Ensure https
                        linkedin_url = linkedin_url.replace("http://", "https://")
                    
                    lead = {
                        # Lead Information
                        "name": item.get("name", "").strip(),
                        "title": item.get("title", "").strip(),
                        "linkedin_url": linkedin_url,
                        "email": item.get("email", "").strip(),
                        "location": item.get("location", "").strip(),
                        "seniority_level": item.get("seniority_level", "").strip(),
                        "department": item.get("department", "").strip(),
                        "buying_role": item.get("buying_role", "").strip(),
                        "snippet": item.get("snippet", item.get("description", "")).strip(),
                        
                        # Company Information
                        "company_name": item.get("company_name", item.get("company", "")).strip(),
                        "company_industry": item.get("company_industry", "").strip(),
                        "company_size": item.get("company_size", "").strip(),
                        "company_domain": item.get("company_domain", "").strip(),
                        "company_linkedin_url": item.get("company_linkedin_url", "").strip(),
                        "company_headquarters": item.get("company_headquarters", "").strip(),
                        
                        # Metadata
                        "source": "openai_search"
                    }
                    # Validate - must have name
                    if lead["name"]:
                        leads.append(lead)
    except json.JSONDecodeError:
        pass
    
    # If JSON parsing failed, try to extract structured data manually
    if not leads:
        # Look for name patterns like "1. John Doe - CEO"
        pattern = r'(?:\d+\.?\s*)?([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\s*[-–]\s*([^|\n]+)'
        matches = re.findall(pattern, response_text)
        
        for name, title in matches[:max_results]:
            lead = {
                # Lead Information
                "name": name.strip(),
                "title": title.strip(),
                "linkedin_url": "",
                "email": "",
                "location": "",
                "seniority_level": "",
                "department": "",
                "buying_role": "",
                "snippet": "",
                
                # Company Information
                "company_name": "",
                "company_industry": "",
                "company_size": "",
                "company_domain": "",
                "company_linkedin_url": "",
                "company_headquarters": "",
                
                # Metadata
                "source": "openai_search"
            }
            leads.append(lead)
        
        # Try to find LinkedIn URLs and associate them
        url_pattern = r'linkedin\.com/in/([a-zA-Z0-9\-]+)'
        urls = re.findall(url_pattern, response_text)
        
        for i, url_slug in enumerate(urls):
            if i < len(leads):
                leads[i]["linkedin_url"] = f"https://www.linkedin.com/in/{url_slug}"
    
    return leads


async def search_linkedin_leads_batch(
    queries: List[str],
    num_results_per_query: int = 10,
    deduplicate: bool = True
) -> Tuple[List[dict], dict]:
    """
    Search multiple queries efficiently with caching.
    
    Args:
        queries: List of search queries
        num_results_per_query: Results per query (max 10)
        deduplicate: Filter out existing leads
        
    Returns:
        Tuple of (all_leads, stats_dict)
    """
    all_leads = []
    stats = {
        "total_queries": len(queries),
        "cache_hits": 0,
        "api_calls": 0,
        "leads_found": 0,
        "duplicates_filtered": 0
    }
    
    for query in queries:
        # Check cache first
        clean_query = re.sub(r'site:linkedin\.com[^\s]*\s*', '', query, flags=re.IGNORECASE).strip()
        search_query = f"LinkedIn profiles: {clean_query}"
        
        cached = get_cached_response(search_query, provider="openai_web")
        
        if cached:
            stats["cache_hits"] += 1
            leads = cached
        else:
            stats["api_calls"] += 1
            leads = await search_linkedin_leads(
                query=query,
                num_results=num_results_per_query,
                skip_cache=True,  # Already checked
                deduplicate=False  # Do batch dedup at end
            )
        
        all_leads.extend(leads)
    
    # Batch deduplication at the end
    if deduplicate and all_leads:
        unique_leads, duplicates = check_duplicates_batch(all_leads)
        stats["duplicates_filtered"] = len(duplicates)
        stats["leads_found"] = len(unique_leads)
        return unique_leads, stats
    
    stats["leads_found"] = len(all_leads)
    return all_leads, stats


async def search_linkedin_leads_discovery(
    query: str,
    num_results: int = 10,
    skip_cache: bool = False
) -> List[dict]:
    """
    Search LinkedIn using OpenAI for discovery (broader search).
    
    Used for AI Discovery flow:
    - Broader search for professionals
    - No designation blocklist (per user requirement)
    
    Args:
        query: Full search query
        num_results: Number of results to fetch
        skip_cache: Force fresh API call
        
    Returns:
        List of parsed lead data
    """
    from .search_cache import get_cached_response, cache_response
    
    # ===== CACHE CHECK =====
    if not skip_cache:
        cached = get_cached_response(query, provider="openai_web")
        if cached:
            return cached
    
    # ===== OPENAI API CALL =====
    api_key = get_openai_api_key()
    
    if not api_key:
        raise ValueError("OpenAI API Key is required. Configure in Settings.")
    
    try:
        from openai import OpenAI
    except ImportError:
        raise ValueError("OpenAI package not installed.")
    
    client_ai = OpenAI(api_key=api_key)
    
    # Extract search criteria from the query
    clean_query = re.sub(r'site:linkedin\.com[^\s]*\s*', '', query, flags=re.IGNORECASE).strip()
    
    search_prompt = f"""Search the web for LinkedIn profiles matching: {clean_query}

**TARGET AUDIENCE - Find decision makers who purchase:**
- Online sample/panel services
- Consumer insights research
- Market research services  
- Analytics and dashboarding solutions
- Survey fieldwork and data collection

**PREFERRED ROLES (prioritize):**
- Director/VP/Head of Insights, Consumer Insights, Market Research
- Research & Analytics Director/Manager
- Customer Insights Lead
- Research Operations Manager
- Analytics Director/Manager
- Brand/Shopper Insights Manager

**EXCLUDE:** CEO, CTO, CFO, Founders, Software Engineers, generic Sales roles

Find up to {num_results} REAL professionals. Extract ALL information:

**Required:**
1. Full name
2. Job title (must be insights/research/analytics focused)
3. Company name
4. LinkedIn URL - MUST be REAL URL with random suffix (e.g., john-smith-5a3b2c1d)

**Additional:**
5. Location
6. Email (if visible)
7. Seniority (VP, Director, Senior Manager, Manager, Lead)
8. Department (Insights, Research, Analytics)
9. Company industry (CPG, Retail, FMCG, Healthcare, Financial Services, Tech, Outsourcing, Consulting, E-commerce, Airlines, Banks, Insurance, Telecom, Media)
10. Company size
11. Company domain
12. Company LinkedIn URL
13. Company headquarters
14. Buying role (Decision Maker, Budget Holder, Influencer)
15. Brief description

Return as JSON array with: name, title, linkedin_url, company_name, location, email, seniority_level, department, company_industry, company_size, company_domain, company_linkedin_url, company_headquarters, buying_role, snippet

CRITICAL: 
- ONLY include insights/research/analytics professionals - NO generic executives
- ONLY use LinkedIn URLs actually found in search results
- NEVER fabricate URLs from names
- Real LinkedIn URLs have random characters (e.g., john-smith-5a3b2c1d)
- Use empty string for unavailable fields."""

    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You find market research, consumer insights, and analytics professionals on LinkedIn. ONLY include people with insights/research/analytics roles - NO CEOs, CTOs, or generic executives. Never fabricate LinkedIn URLs - real URLs have random alphanumeric suffixes. Return valid JSON arrays only."},
                {"role": "user", "content": search_prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )
        response_text = response.choices[0].message.content
    except Exception as e:
        raise ValueError(f"OpenAI API error: {str(e)}")
    
    # Parse response
    leads = parse_openai_linkedin_response(response_text, num_results)
    
    # Update source to discovery
    for lead in leads:
        lead["source"] = "ai_discovery"
    
    # ===== CACHE RESPONSE =====
    if leads:
        cache_response(query, leads, provider="openai_web")
    
    return leads


# ============== TWO-PHASE COMPANY-FIRST DISCOVERY ==============

# Industry segments to target
TARGET_INDUSTRIES = [
    "CPG/FMCG",
    "Retail",
    "E-commerce", 
    "Healthcare/Pharma",
    "Financial Services/Banking",
    "Insurance",
    "Telecom",
    "Media & Entertainment",
    "Airlines/Travel",
    "Management Consulting",
    "Outsourcing/BPO",
    "Technology",
    "Market Research/Panel Companies"  # Special handling - pitch different services
]

# Regions to search
TARGET_REGIONS = {
    "US": "United States",
    "Canada": "Canada", 
    "Europe": "Europe (UK, Germany, France, Netherlands, Spain, Italy)",
    "Middle East": "Middle East (UAE, Saudi Arabia, Qatar, Kuwait)",
    "APAC": "Asia Pacific (Singapore, Australia, Japan, South Korea, Hong Kong)",
    "India": "India"
}


async def discover_top_companies(
    industry: str,
    region: str,
    num_companies: int = 50,
    skip_cache: bool = False
) -> List[dict]:
    """
    Phase 1: Discover top companies in a specific industry and region.
    
    Args:
        industry: Industry segment (e.g., "CPG/FMCG", "Retail")
        region: Region key (e.g., "US", "Europe", "India")
        num_companies: Number of companies to find (default 50)
        skip_cache: Force fresh API call
        
    Returns:
        List of company data dictionaries
    """
    from .search_cache import get_cached_response, cache_response
    
    region_name = TARGET_REGIONS.get(region, region)
    cache_key = f"companies:{industry}:{region}:{num_companies}"
    
    # ===== CACHE CHECK =====
    if not skip_cache:
        cached = get_cached_response(cache_key, provider="openai_companies")
        if cached:
            return cached
    
    # ===== OPENAI API CALL =====
    api_key = get_openai_api_key()
    
    if not api_key:
        raise ValueError("OpenAI API Key is required. Configure in Settings.")
    
    try:
        from openai import OpenAI
    except ImportError:
        raise ValueError("OpenAI package not installed.")
    
    client_ai = OpenAI(api_key=api_key)
    
    # Determine if this is a market research company search
    is_research_company = "research" in industry.lower() or "panel" in industry.lower()
    
    search_prompt = f"""Search the web to find the top {num_companies} companies in the {industry} industry in {region_name}.

**REQUIREMENTS:**
- Find REAL, established companies (not startups unless significant)
- Companies should have substantial market presence in {region_name}
- Include company LinkedIn page URL if available

**For each company, provide:**
1. Company name
2. Company LinkedIn URL (https://www.linkedin.com/company/...)
3. Company website/domain
4. Headquarters location
5. Employee count range
6. Brief description of what they do
7. Whether they likely have consumer insights/market research needs

{"**NOTE: These are MARKET RESEARCH/PANEL companies - we will pitch Online Panel Services and Questionnaire Programming to them.**" if is_research_company else "**NOTE: These are END-CLIENT companies who need market research services - we will pitch Consumer Insights, Sample/Panel purchasing, Analytics, and Dashboarding.**"}

Format as JSON array with:
- company_name: Company name
- company_linkedin_url: LinkedIn company page URL
- company_domain: Website domain
- company_headquarters: HQ location
- company_size: Employee range (e.g., "1001-5000")
- company_industry: Specific industry
- description: Brief company description
- is_research_company: true/false (whether they are a market research/panel company)
- research_needs: Description of likely research/insights needs

CRITICAL: Only include REAL companies with verified information. Use empty string for unavailable fields."""

    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are a B2B market researcher identifying top companies in {industry} in {region_name}. Only return real, verifiable companies. Return valid JSON arrays."},
                {"role": "user", "content": search_prompt}
            ],
            temperature=0.3,
            max_tokens=4000
        )
        response_text = response.choices[0].message.content
    except Exception as e:
        raise ValueError(f"OpenAI API error: {str(e)}")
    
    # Parse response
    companies = []
    try:
        json_match = re.search(r'\[[\s\S]*\]', response_text)
        if json_match:
            data = json.loads(json_match.group())
            if isinstance(data, list):
                for item in data[:num_companies]:
                    company = {
                        "company_name": item.get("company_name", "").strip(),
                        "company_linkedin_url": item.get("company_linkedin_url", "").strip(),
                        "company_domain": item.get("company_domain", "").strip(),
                        "company_headquarters": item.get("company_headquarters", "").strip(),
                        "company_size": item.get("company_size", "").strip(),
                        "company_industry": item.get("company_industry", industry).strip(),
                        "description": item.get("description", "").strip(),
                        "is_research_company": item.get("is_research_company", False),
                        "research_needs": item.get("research_needs", "").strip(),
                        "region": region
                    }
                    if company["company_name"]:
                        companies.append(company)
    except json.JSONDecodeError:
        pass
    
    # ===== CACHE RESPONSE =====
    if companies:
        cache_response(cache_key, companies, provider="openai_companies")
    
    return companies


async def find_decision_makers_in_company(
    company: dict,
    num_contacts: int = 5,
    skip_cache: bool = False
) -> List[dict]:
    """
    Phase 2: Find decision makers within a specific company.
    
    Args:
        company: Company data dictionary from Phase 1
        num_contacts: Number of contacts to find per company
        skip_cache: Force fresh API call
        
    Returns:
        List of lead dictionaries
    """
    from .search_cache import get_cached_response, cache_response
    
    company_name = company.get("company_name", "")
    is_research_company = company.get("is_research_company", False)
    
    cache_key = f"contacts:{company_name}:{num_contacts}"
    
    # ===== CACHE CHECK =====
    if not skip_cache:
        cached = get_cached_response(cache_key, provider="openai_contacts")
        if cached:
            return cached
    
    # ===== OPENAI API CALL =====
    api_key = get_openai_api_key()
    
    if not api_key:
        raise ValueError("OpenAI API Key is required.")
    
    try:
        from openai import OpenAI
    except ImportError:
        raise ValueError("OpenAI package not installed.")
    
    client_ai = OpenAI(api_key=api_key)
    
    # Different target roles based on company type
    if is_research_company:
        target_roles = """**TARGET ROLES for Market Research/Panel Company (pitch: Online Panel Services, Questionnaire Programming, Survey Scripting):**
- Director/VP of Operations
- Director/VP of Field Operations  
- Head of Sample/Panel Operations
- Research Operations Manager
- Project Director/Manager
- Director of Technology/IT
- Procurement Manager
- Vendor Manager
- COO (for smaller research firms)"""
        service_pitch = "Online Panel Services, Questionnaire Programming, Survey Scripting, Data Collection"
    else:
        target_roles = """**TARGET ROLES for End-Client Company (pitch: Consumer Insights, Sample Purchasing, Analytics, Dashboarding):**
- Director/VP/Head of Consumer Insights
- Director/VP/Head of Market Research
- Director/VP of Customer Insights
- Director/VP of Analytics
- Research & Insights Manager
- Brand Insights Manager
- Shopper Insights Manager
- Customer Analytics Lead
- Head of Data & Analytics
- Research Operations Manager"""
        service_pitch = "Consumer Insights, Online Sample/Panel Purchasing, Market Research, Analytics, Dashboarding"
    
    search_prompt = f"""Search LinkedIn for decision makers at {company_name} who would purchase or influence purchasing of: {service_pitch}

{target_roles}

Find up to {num_contacts} REAL professionals at {company_name}.

**For each person, extract:**
1. Full name
2. Job title
3. LinkedIn profile URL (MUST be REAL URL with random alphanumeric suffix, e.g., john-smith-5a3b2c1d)
4. Email (if publicly visible)
5. Location
6. Seniority level (VP, Director, Senior Manager, Manager, Lead)
7. Department

**Company Context:**
- Company: {company_name}
- Industry: {company.get("company_industry", "")}
- Company LinkedIn: {company.get("company_linkedin_url", "")}
- Company Website: {company.get("company_domain", "")}
- Is Market Research Company: {is_research_company}
- Service Pitch: {service_pitch}

Format as JSON array with:
- name: Full name
- title: Job title  
- linkedin_url: REAL LinkedIn URL (NOT fabricated)
- email: Email if available
- location: Location
- seniority_level: Seniority
- department: Department
- company_name: "{company_name}"
- company_industry: "{company.get("company_industry", "")}"
- company_linkedin_url: "{company.get("company_linkedin_url", "")}"
- company_domain: "{company.get("company_domain", "")}"
- company_size: "{company.get("company_size", "")}"
- company_headquarters: "{company.get("company_headquarters", "")}"
- is_research_company: {str(is_research_company).lower()}
- service_pitch: "{service_pitch}"
- buying_role: Decision Maker/Influencer/Budget Holder

CRITICAL:
- ONLY include people who work at {company_name}
- ONLY use REAL LinkedIn URLs from search results
- NEVER fabricate URLs - real URLs have random suffixes (e.g., john-smith-5a3b2c1d)
- Use empty string for unavailable fields"""

    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You find decision makers at {company_name} who purchase research/insights services. Only return real LinkedIn profiles with verified URLs. Real LinkedIn URLs have random alphanumeric suffixes. Return valid JSON arrays."},
                {"role": "user", "content": search_prompt}
            ],
            temperature=0.3,
            max_tokens=3000
        )
        response_text = response.choices[0].message.content
    except Exception as e:
        raise ValueError(f"OpenAI API error: {str(e)}")
    
    # Parse response
    leads = []
    try:
        json_match = re.search(r'\[[\s\S]*\]', response_text)
        if json_match:
            data = json.loads(json_match.group())
            if isinstance(data, list):
                for item in data[:num_contacts]:
                    # Validate LinkedIn URL
                    linkedin_url = item.get("linkedin_url", "").strip()
                    if linkedin_url and "linkedin.com/in/" in linkedin_url:
                        if not linkedin_url.startswith("http"):
                            linkedin_url = "https://" + linkedin_url
                        linkedin_url = linkedin_url.replace("http://", "https://")
                    
                    lead = {
                        # Lead Information
                        "name": item.get("name", "").strip(),
                        "title": item.get("title", "").strip(),
                        "linkedin_url": linkedin_url,
                        "email": item.get("email", "").strip(),
                        "location": item.get("location", "").strip(),
                        "seniority_level": item.get("seniority_level", "").strip(),
                        "department": item.get("department", "").strip(),
                        "buying_role": item.get("buying_role", "Decision Maker").strip(),
                        
                        # Company Information (from Phase 1)
                        "company_name": company_name,
                        "company_industry": company.get("company_industry", ""),
                        "company_size": company.get("company_size", ""),
                        "company_domain": company.get("company_domain", ""),
                        "company_linkedin_url": company.get("company_linkedin_url", ""),
                        "company_headquarters": company.get("company_headquarters", ""),
                        
                        # Service context
                        "is_research_company": is_research_company,
                        "service_pitch": service_pitch,
                        "region": company.get("region", ""),
                        
                        # Metadata
                        "source": "openai_company_search",
                        "snippet": item.get("snippet", "")
                    }
                    if lead["name"]:
                        leads.append(lead)
    except json.JSONDecodeError:
        pass
    
    # ===== CACHE RESPONSE =====
    if leads:
        cache_response(cache_key, leads, provider="openai_contacts")
    
    return leads


async def run_full_company_discovery(
    industries: List[str] = None,
    regions: List[str] = None,
    companies_per_segment: int = 50,
    contacts_per_company: int = 5,
    skip_cache: bool = False
) -> Tuple[List[dict], dict]:
    """
    Run full two-phase discovery: Find companies, then find decision makers.
    
    Args:
        industries: List of industries to search (default: all)
        regions: List of regions to search (default: all)
        companies_per_segment: Companies to find per industry/region combo
        contacts_per_company: Contacts to find per company
        skip_cache: Force fresh API calls
        
    Returns:
        Tuple of (all_leads, stats_dict)
    """
    if industries is None:
        industries = TARGET_INDUSTRIES
    if regions is None:
        regions = list(TARGET_REGIONS.keys())
    
    all_leads = []
    all_companies = []
    stats = {
        "industries_searched": len(industries),
        "regions_searched": len(regions),
        "total_companies_found": 0,
        "total_leads_found": 0,
        "research_companies": 0,
        "end_client_companies": 0,
        "errors": []
    }
    
    # Phase 1: Discover companies
    logger.info(f"Phase 1: Discovering companies across {len(industries)} industries x {len(regions)} regions")
    
    for industry in industries:
        for region in regions:
            try:
                companies = await discover_top_companies(
                    industry=industry,
                    region=region,
                    num_companies=companies_per_segment,
                    skip_cache=skip_cache
                )
                all_companies.extend(companies)
                stats["total_companies_found"] += len(companies)
                
                # Count research vs end-client companies
                for c in companies:
                    if c.get("is_research_company"):
                        stats["research_companies"] += 1
                    else:
                        stats["end_client_companies"] += 1
                        
                logger.info(f"Found {len(companies)} companies in {industry} - {region}")
            except Exception as e:
                error_msg = f"Error discovering {industry} in {region}: {str(e)}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)
    
    # Phase 2: Find decision makers in each company
    logger.info(f"Phase 2: Finding decision makers in {len(all_companies)} companies")
    
    for company in all_companies:
        try:
            leads = await find_decision_makers_in_company(
                company=company,
                num_contacts=contacts_per_company,
                skip_cache=skip_cache
            )
            all_leads.extend(leads)
            logger.info(f"Found {len(leads)} contacts at {company.get('company_name')}")
        except Exception as e:
            error_msg = f"Error finding contacts at {company.get('company_name')}: {str(e)}"
            logger.error(error_msg)
            stats["errors"].append(error_msg)
    
    stats["total_leads_found"] = len(all_leads)
    
    # Deduplication
    if all_leads:
        unique_leads, duplicates = check_duplicates_batch(all_leads)
        stats["duplicates_filtered"] = len(duplicates)
        stats["unique_leads"] = len(unique_leads)
        return unique_leads, stats
    
    return all_leads, stats


async def discover_leads_by_region(
    region: str,
    industries: List[str] = None,
    companies_per_industry: int = 50,
    contacts_per_company: int = 5
) -> Tuple[List[dict], dict]:
    """
    Convenience function: Run discovery for a single region.
    """
    return await run_full_company_discovery(
        industries=industries,
        regions=[region],
        companies_per_segment=companies_per_industry,
        contacts_per_company=contacts_per_company
    )


def parse_google_search_result_discovery(item: dict) -> Optional[dict]:
    """
    Parse a Google Custom Search result for discovery mode (legacy).
    More lenient than standard parser - accepts any LinkedIn URL.
    """
    link = item.get("link", "")
    
    # Accept any LinkedIn URL (not just /in/ profiles)
    if "linkedin.com" not in link:
        return None
    
    title = item.get("title", "")
    snippet = item.get("snippet", "")
    
    # Extract name and job title from the Google search title
    name, job_title = extract_name_and_title(title)
    
    # Try to extract company from snippet
    company_name = ""
    if snippet:
        # Common patterns: "at Company", "@ Company", "| Company"
        import re
        company_match = re.search(r'(?:at|@|\|)\s+([A-Z][^|•·\-\n]+?)(?:\s*[|•·\-]|$)', snippet)
        if company_match:
            company_name = company_match.group(1).strip()
    
    # Try to extract location from snippet
    location = ""
    location_match = re.search(r'(?:Location|Based in|Located in)[:\s]+([^|•·\n]+)', snippet, re.IGNORECASE)
    if location_match:
        location = location_match.group(1).strip()
    
    return {
        "name": name or title.split(" - ")[0].strip(),
        "title": job_title,
        "linkedin_url": link,
        "snippet": snippet[:300] if snippet else "",
        "company_name": company_name,
        "location": location,
        "source": "ai_discovery"
    }


def parse_google_search_result(item: dict) -> Optional[dict]:
    """
    Parse a Google Custom Search result into lead format.
    """
    link = item.get("link", "")
    
    # Only process LinkedIn profile URLs
    if "linkedin.com/in/" not in link:
        return None
    
    title = item.get("title", "")
    snippet = item.get("snippet", "")
    
    # Extract name and job title from the Google search title
    # Format is usually: "Name - Title - LinkedIn"
    name, job_title = extract_name_and_title(title)
    
    if not name:
        return None
    
    return {
        "name": name,
        "title": job_title or "",
        "linkedin_url": link,
        "snippet": snippet,
        "source": "google_search"
    }


def extract_name_and_title(search_title: str) -> Tuple[str, str]:
    """
    Extract name and job title from LinkedIn search result title.
    Typical format: "John Doe - CEO at Company - LinkedIn"
    """
    # Remove " - LinkedIn" suffix
    title = re.sub(r'\s*[-–]\s*LinkedIn\s*$', '', search_title, flags=re.IGNORECASE)
    
    # Split by " - " or " – "
    parts = re.split(r'\s*[-–]\s*', title)
    
    if len(parts) >= 2:
        name = parts[0].strip()
        job_title = parts[1].strip()
        return name, job_title
    elif len(parts) == 1:
        return parts[0].strip(), ""
    
    return "", ""


# ============== CSV IMPORT ==============

def parse_csv_leads(csv_content: str, delimiter: str = ",") -> List[dict]:
    """
    Parse CSV content into lead format.
    Supports all lead fields including company data.
    
    Returns:
        List of parsed leads
    """
    leads = []
    reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)
    
    # Full column mapping for all supported fields
    column_mapping = {
        "name": ["name", "full_name", "fullname", "full name", "contact_name", "contact name"],
        "first_name": ["first_name", "firstname", "first", "given_name"],
        "last_name": ["last_name", "lastname", "last", "surname"],
        "email": ["email", "email_address", "e-mail", "mail", "work_email"],
        "email_status": ["email_status", "emailstatus", "email status", "status", "valid"],
        "title": ["title", "job_title", "jobtitle", "job title", "position", "role", "designation"],
        "linkedin_url": ["linkedin_url", "linkedin", "linkedinurl", "linkedin url", "profile_url", "url"],
        "location": ["location", "city", "country", "region", "geo"],
        "company_name": ["company_name", "companyname", "company", "organization", "employer", "company name"],
        "company_domain": ["company_domain", "companydomain", "domain", "website_domain"],
        "company_website": ["company_website", "companywebsite", "website", "company_url", "company website"],
        "company_employee_count": ["company_employee_count", "employees", "employee_count", "headcount", "size"],
        "company_employee_count_range": ["company_employee_count_range", "employee_range", "size_range", "company_size"],
        "company_founded": ["company_founded", "founded", "year_founded", "founded_year", "established"],
        "company_industry": ["company_industry", "industry", "sector", "vertical"],
        "company_type": ["company_type", "type", "business_type"],
        "company_headquarters": ["company_headquarters", "headquarters", "hq", "hq_location", "main_office"],
        "company_revenue_range": ["company_revenue_range", "revenue_range", "revenue", "annual_revenue"],
        "company_linkedin_url": ["company_linkedin_url", "company_linkedin", "company linkedin"],
        "snippet": ["snippet", "bio", "description", "about", "summary", "headline"]
    }
    
    for row in reader:
        lead = parse_csv_row(row, column_mapping)
        if lead and (lead.get("name") or lead.get("linkedin_url")):
            leads.append(lead)
    
    return leads


def parse_csv_row(row: dict, column_mapping: dict) -> Optional[dict]:
    """Parse a single CSV row into lead format with all fields."""
    # Normalize row keys to lowercase
    normalized_row = {k.lower().strip().replace(" ", "_"): v for k, v in row.items()}
    
    lead = {"source": "csv_import"}
    
    for target_field, possible_columns in column_mapping.items():
        for col in possible_columns:
            normalized_col = col.lower().replace(" ", "_")
            if normalized_col in normalized_row and normalized_row[normalized_col]:
                lead[target_field] = str(normalized_row[normalized_col]).strip()
                break
        
        # Set default empty string if not found (only for required fields)
        if target_field not in lead:
            if target_field in ["name", "title", "linkedin_url", "snippet"]:
                lead[target_field] = ""
    
    # Require at least name or linkedin_url to be valid
    if not lead.get("name") and not lead.get("linkedin_url"):
        return None
    
    # If name is missing, try to construct from first/last name
    if not lead.get("name") and (lead.get("first_name") or lead.get("last_name")):
        lead["name"] = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    
    return lead


# ============== GOOGLE SHEETS IMPORT ==============

async def import_from_google_sheet(
    spreadsheet_id: str,
    sheet_name: str = "Sheet1",
    range_notation: str = "A:Z"
) -> List[dict]:
    """
    Import leads from a Google Sheet.
    
    Args:
        spreadsheet_id: Google Sheets document ID
        sheet_name: Name of the sheet tab
        range_notation: Cell range to read (default: all columns)
        
    Returns:
        List of parsed leads
    """
    api_key, _ = get_google_api_credentials()
    
    if not api_key:
        raise ValueError("Google API Key is required. Configure in Settings.")
    
    # Construct the Sheets API URL
    range_param = f"{sheet_name}!{range_notation}"
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_param}"
    
    params = {
        "key": api_key,
        "valueRenderOption": "FORMATTED_VALUE"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=30.0)
        
        if response.status_code == 403:
            raise ValueError("Sheet is not publicly accessible. Make it 'Anyone with the link can view'.")
        
        response.raise_for_status()
        data = response.json()
    
    values = data.get("values", [])
    
    if len(values) < 2:
        return []  # Need at least header + 1 data row
    
    # First row is headers
    headers = [h.lower().strip() for h in values[0]]
    
    # Parse remaining rows
    leads = []
    for row in values[1:]:
        # Pad row with empty strings if shorter than headers
        padded_row = row + [""] * (len(headers) - len(row))
        row_dict = dict(zip(headers, padded_row))
        
        lead = parse_google_sheet_row(row_dict)
        if lead and lead.get("name"):
            leads.append(lead)
    
    return leads


def parse_google_sheet_row(row: dict) -> Optional[dict]:
    """Parse a Google Sheet row into lead format."""
    column_mapping = {
        "name": ["name", "full_name", "fullname", "full name", "contact_name", "contact name"],
        "title": ["title", "job_title", "jobtitle", "job title", "position", "role"],
        "linkedin_url": ["linkedin_url", "linkedin", "linkedinurl", "linkedin url", "profile_url", "url"],
        "snippet": ["snippet", "bio", "description", "about", "summary", "headline"]
    }
    
    lead = {"source": "google_sheets"}
    
    for target_field, possible_columns in column_mapping.items():
        for col in possible_columns:
            if col in row and row[col]:
                lead[target_field] = str(row[col]).strip()
                break
        
        if target_field not in lead:
            lead[target_field] = ""
    
    if not lead.get("name"):
        return None
    
    return lead


# ============== APOLLO.IO IMPORT (FUTURE) ==============

async def import_from_apollo(api_key: str, search_params: dict) -> List[dict]:
    """
    Import leads from Apollo.io API.
    Placeholder for future implementation.
    """
    # Apollo API: https://apolloio.github.io/apollo-api-docs/
    raise NotImplementedError("Apollo.io integration coming soon")


# ============== ZOOMINFO IMPORT (FUTURE) ==============

async def import_from_zoominfo(api_key: str, search_params: dict) -> List[dict]:
    """
    Import leads from ZoomInfo API.
    Placeholder for future implementation.
    """
    raise NotImplementedError("ZoomInfo integration coming soon")


# ============== UNIFIED IMPORT FUNCTION ==============

async def import_leads_from_source(
    source_type: str,
    **kwargs
) -> List[dict]:
    """
    Unified import function that routes to the appropriate source handler.
    
    Args:
        source_type: One of "google_search", "csv", "google_sheets", "json"
        **kwargs: Source-specific parameters
        
    Returns:
        List of parsed leads
    """
    if source_type == "google_search":
        return await search_linkedin_leads(
            query=kwargs.get("query", ""),
            num_results=kwargs.get("num_results", 10),
            start=kwargs.get("start", 1)
        )
    
    elif source_type == "csv":
        return parse_csv_leads(
            csv_content=kwargs.get("content", ""),
            delimiter=kwargs.get("delimiter", ",")
        )
    
    elif source_type == "google_sheets":
        return await import_from_google_sheet(
            spreadsheet_id=kwargs.get("spreadsheet_id", ""),
            sheet_name=kwargs.get("sheet_name", "Sheet1"),
            range_notation=kwargs.get("range", "A:Z")
        )
    
    elif source_type == "json":
        # Direct JSON import
        content = kwargs.get("content", "[]")
        if isinstance(content, str):
            data = json.loads(content)
        else:
            data = content
        
        if isinstance(data, dict):
            data = [data]
        
        # Normalize to expected format
        leads = []
        for item in data:
            lead = {
                "name": item.get("name", ""),
                "title": item.get("title", ""),
                "linkedin_url": item.get("linkedin_url", item.get("linkedin", "")),
                "snippet": item.get("snippet", item.get("bio", item.get("description", ""))),
                "source": "json_import"
            }
            if lead["name"]:
                leads.append(lead)
        
        return leads
    
    else:
        raise ValueError(f"Unknown source type: {source_type}")
