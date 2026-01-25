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
# Replaced Google CSE with OpenAI's web_search_preview for finding
# market research and consumer insights professionals

# Target industries for market research leads
MR_TARGET_INDUSTRIES = [
    "CPG/FMCG", "Retail", "E-commerce", "Healthcare/Pharma",
    "Financial Services/Banking", "Insurance", "Telecom",
    "Media & Entertainment", "Airlines/Travel", "Automotive",
    "Technology", "Consumer Electronics", "Food & Beverage",
    "Beauty & Personal Care", "Hospitality", "Gaming"
]

# Target markets (major regions)
MR_TARGET_MARKETS = [
    "United States", "United Kingdom", "Germany", "France",
    "Canada", "Australia", "Singapore", "India", "Japan",
    "Brazil", "Mexico", "Netherlands", "UAE", "South Africa"
]

# Target roles for market research buyers
MR_TARGET_ROLES = [
    "Director of Consumer Insights", "VP Consumer Insights",
    "Head of Market Research", "Director of Research",
    "Consumer Insights Manager", "Market Research Manager",
    "Director of Analytics", "VP of Analytics",
    "Head of Customer Insights", "Research & Insights Lead",
    "Brand Insights Director", "Shopper Insights Manager",
    "Category Insights Manager", "Voice of Customer Director"
]


async def perform_openai_web_search(query: str, num_results: int = 10) -> str:
    """
    Perform web search using OpenAI's Responses API with web_search_preview tool.
    
    This replaces Google CSE for finding LinkedIn profiles of market research
    and consumer insights professionals.
    
    Args:
        query: Search query for finding professionals
        num_results: Number of results to request
        
    Returns:
        Raw text response from OpenAI web search
    """
    api_key = get_openai_api_key()
    
    if not api_key:
        raise ValueError("OpenAI API key not configured. Please set it in Settings.")
    
    try:
        from openai import OpenAI
        client_ai = OpenAI(api_key=api_key)
        
        # Use Responses API with web_search_preview tool
        search_prompt = f"""Search the web and find {num_results} LinkedIn profiles matching this criteria:

SEARCH QUERY: {query}

TARGET AUDIENCE - Market Research & Consumer Insights Professionals who:
- Work at major brands, retailers, or consumer companies
- Purchase market research services, online panels, and consumer insights
- Hold decision-making authority for research budgets

PREFERRED JOB TITLES (prioritize these):
- Director/VP/Head of Consumer Insights
- Director/VP/Head of Market Research  
- Research & Analytics Director/Manager
- Customer Insights Lead/Manager
- Brand/Shopper Insights Manager
- Category Insights Director
- Voice of Customer Manager

INDUSTRIES TO FOCUS ON:
CPG/FMCG, Retail, E-commerce, Healthcare/Pharma, Financial Services, 
Insurance, Telecom, Media, Airlines/Travel, Automotive, Technology

EXCLUDE:
- CEOs, CTOs, CFOs, Founders (unless at research agencies)
- Software Engineers, Developers
- Generic Sales/Marketing roles without insights focus
- Recruiters, HR professionals

For each person found, provide:
1. Full Name
2. Job Title (must be insights/research/analytics focused)
3. Company Name
4. LinkedIn Profile URL (MUST be real URL from search results)
5. Location (city, country)
6. Company Industry
7. Seniority Level (VP, Director, Senior Manager, Manager)

Return as a structured list with all available information.
IMPORTANT: Only include REAL LinkedIn URLs found in search results. Never fabricate URLs."""

        response = client_ai.responses.create(
            model="gpt-4o-mini",
            tools=[{"type": "web_search_preview"}],
            input=search_prompt
        )
        
        # Extract content from response
        content = ""
        if hasattr(response, 'output'):
            for item in response.output:
                if hasattr(item, 'content'):
                    for block in item.content:
                        if hasattr(block, 'text'):
                            content += block.text
        
        logger.info(f"OpenAI web search completed for query: {query[:50]}...")
        return content
        
    except Exception as e:
        logger.error(f"OpenAI web search failed: {e}")
        raise ValueError(f"OpenAI web search error: {str(e)}")


async def perform_google_search(query: str, num_results: int = 10) -> List[dict]:
    """
    LEGACY: Perform a Google Custom Search to find LinkedIn profiles.
    Kept for backward compatibility but OpenAI web search is now preferred.
    
    Args:
        query: Search query
        num_results: Number of results to fetch
        
    Returns:
        List of Google Search result items
    """
    api_key, cse_id = get_google_api_credentials()
    
    if not api_key or not cse_id:
        logger.warning("Google API credentials missing. Using OpenAI web search instead.")
        return []
        
    results = []
    
    # Google API allows max 10 per request
    pages = (num_results + 9) // 10
    
    async with httpx.AsyncClient() as http_client:
        for i in range(pages):
            start = i * 10 + 1
            if start > 100: break
            
            try:
                url = "https://www.googleapis.com/customsearch/v1"
                params = {
                    'q': query,
                    'key': api_key,
                    'cx': cse_id,
                    'num': min(10, num_results - len(results)),
                    'start': start
                }
                
                response = await http_client.get(url, params=params, timeout=15.0)
                
                if response.status_code == 200:
                    data = response.json()
                    items = data.get('items', [])
                    results.extend(items)
                    if not items:
                        break
                elif response.status_code == 429:
                    logger.warning("Google Search quota exceeded")
                    break
                else:
                    logger.error(f"Google Search error: {response.status_code}")
                    break
                    
                if len(results) >= num_results:
                    break
                    
            except Exception as e:
                logger.error(f"Google Search exception: {e}")
                break
                
    return results


async def search_linkedin_leads(
    query: str,
    num_results: int = 10,
    start: int = 1,
    skip_cache: bool = False,
    deduplicate: bool = True,
    use_openai_search: bool = True
) -> List[dict]:
    """
    Search LinkedIn profiles for market research & consumer insights professionals.
    
    NOW USES OpenAI Web Search (Responses API with web_search_preview tool)
    instead of Google CSE for better results and no separate API key needed.
    
    Args:
        query: Search query (designation, industry, location, etc.)
        num_results: Number of results to find
        start: Pagination start (legacy, ignored for OpenAI search)
        skip_cache: Force fresh search
        deduplicate: Remove duplicates from results
        use_openai_search: Use OpenAI web search (default True)
        
    Returns:
        List of lead dictionaries with LinkedIn profile information
    """
    # Clean query
    clean_query = re.sub(r'site:linkedin\.com[^\s]*\s*', '', query, flags=re.IGNORECASE).strip()
    cache_key = f"openai_linkedin_search:{clean_query}:{num_results}"
    
    # ===== CACHE CHECK =====
    if not skip_cache:
        cached = get_cached_response(cache_key, provider="openai_web")
        if cached:
            if deduplicate and cached:
                unique_leads, duplicates = check_duplicates_batch(cached)
                return unique_leads
            return cached
    
    # ===== OPENAI WEB SEARCH (PRIMARY) =====
    if use_openai_search:
        try:
            # Construct optimized search query for market research professionals
            search_query = f"{clean_query} LinkedIn profile market research consumer insights"
            
            # Perform OpenAI web search
            raw_response = await perform_openai_web_search(search_query, num_results)
            
            if not raw_response:
                logger.warning(f"No results from OpenAI web search for: {clean_query}")
                return []
            
            # Parse the response to extract leads
            leads = parse_openai_web_search_response(raw_response, num_results)
            
            if leads:
                # Set source
                for lead in leads:
                    lead["source"] = "openai_search"
                
                # Cache results
                cache_response(cache_key, leads, provider="openai_web")
                
                # Deduplicate
                if deduplicate:
                    unique_leads, duplicates = check_duplicates_batch(leads)
                    return unique_leads
                
                return leads
                
        except Exception as e:
            logger.error(f"OpenAI web search failed: {e}")
            # Fall through to Google CSE fallback
    
    # ===== GOOGLE CSE FALLBACK =====
    search_query = f"{clean_query} site:linkedin.com/in/"
    search_results = await perform_google_search(search_query, num_results)
    
    if not search_results:
        logger.warning(f"No results found for query: {clean_query}")
        return []
    
    # Parse Google results with OpenAI
    leads = await extract_leads_from_google_results(search_results, clean_query)
    
    if leads:
        cache_response(cache_key, leads, provider="openai_web")
        
        if deduplicate:
            unique_leads, duplicates = check_duplicates_batch(leads)
            return unique_leads
    
    return leads


def parse_openai_web_search_response(response_text: str, max_results: int = 10) -> List[dict]:
    """
    Parse OpenAI web search response to extract LinkedIn leads.
    
    Handles various response formats from the web_search_preview tool.
    
    Args:
        response_text: Raw text response from OpenAI web search
        max_results: Maximum number of results to extract
        
    Returns:
        List of parsed lead dictionaries
    """
    leads = []
    
    if not response_text:
        return leads
    
    # Try to extract JSON if present
    try:
        json_match = re.search(r'\[[\s\S]*?\]', response_text)
        if json_match:
            data = json.loads(json_match.group())
            if isinstance(data, list):
                for item in data[:max_results]:
                    lead = normalize_lead_data(item)
                    if lead.get("name") and lead.get("linkedin_url"):
                        leads.append(lead)
                return leads
    except json.JSONDecodeError:
        pass
    
    # Parse structured text response
    # Look for patterns like "Name: John Smith" or "1. John Smith"
    current_lead = {}
    
    for line in response_text.split('\n'):
        line = line.strip()
        if not line:
            if current_lead.get("name"):
                leads.append(normalize_lead_data(current_lead))
                current_lead = {}
            continue
        
        # Extract LinkedIn URL
        linkedin_match = re.search(r'(https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9\-]+/?)', line)
        if linkedin_match:
            current_lead["linkedin_url"] = linkedin_match.group(1)
        
        # Extract name (various patterns)
        name_patterns = [
            r'(?:Name|Full Name)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)',
            r'^\d+\.\s*\*?\*?([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\*?\*?',
            r'^\*\*([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\*\*',
        ]
        for pattern in name_patterns:
            match = re.search(pattern, line)
            if match:
                current_lead["name"] = match.group(1).strip()
                break
        
        # Extract title
        title_match = re.search(r'(?:Title|Job Title|Position|Role)[:\s]+(.+?)(?:\s+at\s+|$)', line, re.IGNORECASE)
        if title_match:
            current_lead["title"] = title_match.group(1).strip()
        
        # Extract company
        company_match = re.search(r'(?:Company|Organization|Employer)[:\s]+(.+?)(?:\s*[,\n]|$)', line, re.IGNORECASE)
        if company_match:
            current_lead["company_name"] = company_match.group(1).strip()
        
        # Extract "Title at Company" pattern
        at_pattern = re.search(r'([^,\n]+?)\s+at\s+([^,\n]+)', line, re.IGNORECASE)
        if at_pattern and not current_lead.get("title"):
            current_lead["title"] = at_pattern.group(1).strip()
            current_lead["company_name"] = at_pattern.group(2).strip()
        
        # Extract location
        location_match = re.search(r'(?:Location|Based in|City)[:\s]+(.+?)(?:\s*[,\n]|$)', line, re.IGNORECASE)
        if location_match:
            current_lead["location"] = location_match.group(1).strip()
        
        # Extract industry
        industry_match = re.search(r'(?:Industry|Sector)[:\s]+(.+?)(?:\s*[,\n]|$)', line, re.IGNORECASE)
        if industry_match:
            current_lead["company_industry"] = industry_match.group(1).strip()
        
        # Extract seniority
        seniority_match = re.search(r'(?:Seniority|Level)[:\s]+(.+?)(?:\s*[,\n]|$)', line, re.IGNORECASE)
        if seniority_match:
            current_lead["seniority_level"] = seniority_match.group(1).strip()
    
    # Add last lead if present
    if current_lead.get("name"):
        leads.append(normalize_lead_data(current_lead))
    
    return leads[:max_results]


def normalize_lead_data(item: dict) -> dict:
    """Normalize lead data to standard format."""
    return {
        "name": str(item.get("name", item.get("full_name", ""))).strip(),
        "title": str(item.get("title", item.get("job_title", item.get("position", "")))).strip(),
        "linkedin_url": str(item.get("linkedin_url", item.get("url", item.get("profile_url", "")))).strip(),
        "company_name": str(item.get("company_name", item.get("company", item.get("organization", "")))).strip(),
        "location": str(item.get("location", item.get("city", ""))).strip(),
        "seniority_level": str(item.get("seniority_level", item.get("seniority", ""))).strip(),
        "department": str(item.get("department", "Insights")).strip(),
        "company_industry": str(item.get("company_industry", item.get("industry", ""))).strip(),
        "company_size": str(item.get("company_size", "")).strip(),
        "email": str(item.get("email", "")).strip(),
        "snippet": str(item.get("snippet", item.get("description", ""))).strip(),
        "source": "openai_search"
    }


async def extract_leads_from_google_results(search_results: List[dict], query: str) -> List[dict]:
    """
    Extract leads from Google search results using OpenAI.
    This is the fallback when OpenAI web search is not available.
    """
    api_key = get_openai_api_key()
    if not api_key:
        # Fallback to regex parsing
        leads = [parse_google_search_result(item) for item in search_results]
        return [l for l in leads if l]
    
    try:
        from openai import OpenAI
        client_ai = OpenAI(api_key=api_key)
        
        search_context = []
        for item in search_results:
            search_context.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", "")
            })
        
        extraction_prompt = f"""Extract LinkedIn profile information from these search results:
{json.dumps(search_context, indent=2)}

Query: {query}
Target: Market research and consumer insights professionals

Return JSON with "leads" array containing objects with:
- name, title, linkedin_url, company_name, location, seniority_level, department, snippet

Only include real profiles with valid LinkedIn URLs (/in/)."""

        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Extract lead data. Return valid JSON only."},
                {"role": "user", "content": extraction_prompt}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)
        parsed_leads = data.get("leads", data.get("profiles", []))
        
        leads = []
        for item in parsed_leads:
            lead = normalize_lead_data(item)
            if lead.get("name") and lead.get("linkedin_url"):
                leads.append(lead)
        
        return leads
        
    except Exception as e:
        logger.error(f"OpenAI extraction failed: {e}")
        leads = [parse_google_search_result(item) for item in search_results]
        return [l for l in leads if l]


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
    Search LinkedIn using OpenAI Web Search (Responses API) for discovery.
    
    NOW USES OpenAI's web_search_preview tool for REAL web search results.
    This finds market research and consumer insights professionals.
    
    Args:
        query: Full search query
        num_results: Number of results to fetch
        skip_cache: Force fresh API call
        
    Returns:
        List of parsed lead data
    """
    from .search_cache import get_cached_response, cache_response
    
    cache_key = f"discovery:{query}:{num_results}"
    
    # ===== CACHE CHECK =====
    if not skip_cache:
        cached = get_cached_response(cache_key, provider="openai_web")
        if cached:
            return cached
    
    # ===== OPENAI WEB SEARCH =====
    api_key = get_openai_api_key()
    
    if not api_key:
        raise ValueError("OpenAI API Key is required. Configure in Settings.")
    
    try:
        from openai import OpenAI
        client_ai = OpenAI(api_key=api_key)
    except ImportError:
        raise ValueError("OpenAI package not installed.")
    
    # Extract search criteria from the query
    clean_query = re.sub(r'site:linkedin\.com[^\s]*\s*', '', query, flags=re.IGNORECASE).strip()
    
    search_prompt = f"""Search the web for LinkedIn profiles of market research and consumer insights professionals matching: {clean_query}

**TARGET AUDIENCE - Decision makers who purchase:**
- Market research services and online panels
- Consumer insights research  
- Survey fieldwork and data collection
- Analytics and dashboarding solutions

**PREFERRED ROLES (prioritize these):**
- Director/VP/Head of Consumer Insights
- Director/VP/Head of Market Research
- Research & Analytics Director/Manager
- Customer Insights Lead/Manager
- Brand/Shopper Insights Manager
- Category Insights Director
- Voice of Customer Manager

**TARGET INDUSTRIES:**
CPG/FMCG, Retail, E-commerce, Healthcare/Pharma, Financial Services/Banking,
Insurance, Telecom, Media & Entertainment, Airlines/Travel, Automotive, Technology

**EXCLUDE:** CEO, CTO, CFO, Founders, Software Engineers, generic Sales/Marketing roles

Find up to {num_results} REAL professionals with LinkedIn profiles.

For each person, provide:
1. Full Name
2. Job Title (must be insights/research/analytics focused)
3. Company Name
4. LinkedIn Profile URL (MUST be REAL URL from search results)
5. Location (city, country)
6. Company Industry
7. Seniority Level (VP, Director, Senior Manager, Manager)
8. Department (Insights, Research, Analytics)

CRITICAL:
- ONLY include insights/research/analytics professionals
- ONLY use LinkedIn URLs actually found in search results
- NEVER fabricate or guess URLs
- Real LinkedIn URLs have format: linkedin.com/in/name-randomchars"""

    try:
        # Use Responses API with web_search_preview tool
        response = client_ai.responses.create(
            model="gpt-4o-mini",
            tools=[{"type": "web_search_preview"}],
            input=search_prompt
        )
        
        # Extract content from response
        response_text = ""
        if hasattr(response, 'output'):
            for item in response.output:
                if hasattr(item, 'content'):
                    for block in item.content:
                        if hasattr(block, 'text'):
                            response_text += block.text
        
        logger.info(f"OpenAI discovery search completed for: {clean_query[:50]}...")
        
    except Exception as e:
        logger.error(f"OpenAI web search failed: {e}")
        raise ValueError(f"OpenAI API error: {str(e)}")
    
    # Parse response
    leads = parse_openai_web_search_response(response_text, num_results)
    
    # Update source to discovery
    for lead in leads:
        lead["source"] = "ai_discovery"
    
    # ===== CACHE RESPONSE =====
    if leads:
        cache_response(cache_key, leads, provider="openai_web")
    
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

Format results with:
- company_name: Company name
- company_linkedin_url: LinkedIn company page URL
- company_domain: Website domain
- company_headquarters: HQ location
- company_size: Employee range (e.g., "1001-5000")
- company_industry: Specific industry
- description: Brief company description
- is_research_company: true/false (whether they are a market research/panel company)
- research_needs: Description of likely research/insights needs

CRITICAL: Only include REAL companies with verified information."""

    try:
        # Use Responses API with web_search_preview for real company data
        response = client_ai.responses.create(
            model="gpt-4o-mini",
            tools=[{"type": "web_search_preview"}],
            input=f"You are a B2B market researcher identifying top companies in {industry} in {region_name}.\n\n{search_prompt}"
        )
        
        # Extract content from response
        response_text = ""
        if hasattr(response, 'output'):
            for item in response.output:
                if hasattr(item, 'content'):
                    for block in item.content:
                        if hasattr(block, 'text'):
                            response_text += block.text
        
        logger.info(f"Company discovery completed for {industry} in {region_name}")
        
    except Exception as e:
        logger.error(f"OpenAI web search failed for company discovery: {e}")
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
                        "company_name": str(item.get("company_name", "")).strip(),
                        "company_linkedin_url": str(item.get("company_linkedin_url", "")).strip(),
                        "company_domain": str(item.get("company_domain", "")).strip(),
                        "company_headquarters": str(item.get("company_headquarters", "")).strip(),
                        "company_size": str(item.get("company_size", "")).strip(),
                        "company_industry": str(item.get("company_industry", industry)).strip(),
                        "description": str(item.get("description", "")).strip(),
                        "is_research_company": item.get("is_research_company", False),
                        "research_needs": str(item.get("research_needs", "")).strip(),
                        "region": region
                    }
                    if company["company_name"]:
                        companies.append(company)
    except json.JSONDecodeError:
        # Try parsing structured text if JSON fails
        companies = parse_company_list_from_text(response_text, num_companies, industry, region)
    
    # ===== CACHE RESPONSE =====
    if companies:
        cache_response(cache_key, companies, provider="openai_companies")
    
    return companies


def parse_company_list_from_text(text: str, max_companies: int, industry: str, region: str) -> List[dict]:
    """Parse company list from structured text response."""
    companies = []
    current_company = {}
    
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            if current_company.get("company_name"):
                companies.append(current_company)
                current_company = {}
            continue
        
        # Extract company name from numbered list
        name_match = re.match(r'^\d+\.\s*\*?\*?([^*:\n]+)', line)
        if name_match:
            if current_company.get("company_name"):
                companies.append(current_company)
            current_company = {
                "company_name": name_match.group(1).strip(),
                "company_industry": industry,
                "region": region
            }
        
        # Extract LinkedIn URL
        linkedin_match = re.search(r'(https?://(?:www\.)?linkedin\.com/company/[a-zA-Z0-9\-]+/?)', line)
        if linkedin_match:
            current_company["company_linkedin_url"] = linkedin_match.group(1)
        
        # Extract website
        website_match = re.search(r'(?:website|domain)[:\s]+([a-zA-Z0-9\-\.]+\.[a-z]{2,})', line, re.IGNORECASE)
        if website_match:
            current_company["company_domain"] = website_match.group(1)
    
    if current_company.get("company_name"):
        companies.append(current_company)
    
    return companies[:max_companies]


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
    
    # ===== OPENAI WEB SEARCH =====
    api_key = get_openai_api_key()
    
    if not api_key:
        raise ValueError("OpenAI API Key is required.")
    
    try:
        from openai import OpenAI
        client_ai = OpenAI(api_key=api_key)
    except ImportError:
        raise ValueError("OpenAI package not installed.")
    
    # Different target roles based on company type
    if is_research_company:
        target_roles = """**TARGET ROLES for Market Research/Panel Company:**
- Director/VP of Operations
- Director/VP of Field Operations  
- Head of Sample/Panel Operations
- Research Operations Manager
- Project Director/Manager
- Director of Technology/IT
- Procurement Manager
- Vendor Manager"""
        service_pitch = "Online Panel Services, Questionnaire Programming, Survey Scripting, Data Collection"
    else:
        target_roles = """**TARGET ROLES for End-Client Company:**
- Director/VP/Head of Consumer Insights
- Director/VP/Head of Market Research
- Director/VP of Customer Insights
- Director/VP of Analytics
- Research & Insights Manager
- Brand Insights Manager
- Shopper Insights Manager
- Customer Analytics Lead
- Head of Data & Analytics"""
        service_pitch = "Consumer Insights, Online Sample/Panel Purchasing, Market Research, Analytics, Dashboarding"
    
    search_prompt = f"""Search the web for LinkedIn profiles of decision makers at {company_name} who would purchase: {service_pitch}

{target_roles}

Find up to {num_contacts} REAL professionals at {company_name}.

**Company Context:**
- Company: {company_name}
- Industry: {company.get("company_industry", "")}
- Company LinkedIn: {company.get("company_linkedin_url", "")}
- Company Website: {company.get("company_domain", "")}

For each person found, provide:
1. Full name
2. Job title
3. LinkedIn profile URL (MUST be REAL URL from search results)
4. Location
5. Seniority level (VP, Director, Senior Manager, Manager)
6. Department

CRITICAL:
- ONLY include people who work at {company_name}
- ONLY use REAL LinkedIn URLs from search results
- NEVER fabricate URLs"""

    try:
        # Use Responses API with web_search_preview for real profiles
        response = client_ai.responses.create(
            model="gpt-4o-mini",
            tools=[{"type": "web_search_preview"}],
            input=search_prompt
        )
        
        # Extract content from response
        response_text = ""
        if hasattr(response, 'output'):
            for item in response.output:
                if hasattr(item, 'content'):
                    for block in item.content:
                        if hasattr(block, 'text'):
                            response_text += block.text
        
        logger.info(f"Contact discovery completed for {company_name}")
        
    except Exception as e:
        logger.error(f"OpenAI web search failed for {company_name}: {e}")
        raise ValueError(f"OpenAI API error: {str(e)}")
    
    # Parse response
    leads = parse_openai_web_search_response(response_text, num_contacts)
    
    # Add company context to each lead
    for lead in leads:
        lead["company_name"] = company_name
        lead["company_industry"] = company.get("company_industry", "")
        lead["company_size"] = company.get("company_size", "")
        lead["company_domain"] = company.get("company_domain", "")
        lead["company_linkedin_url"] = company.get("company_linkedin_url", "")
        lead["company_headquarters"] = company.get("company_headquarters", "")
        lead["is_research_company"] = is_research_company
        lead["service_pitch"] = service_pitch
        lead["region"] = company.get("region", "")
        lead["source"] = "ai_discovery"
    
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
