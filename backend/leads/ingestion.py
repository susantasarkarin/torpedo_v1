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
    search_prompt = f"""Search for LinkedIn profiles matching this criteria: {clean_query}

Find up to {num_results} LinkedIn profiles. For each profile found, provide:
1. Full name
2. Job title/position
3. LinkedIn profile URL (must be linkedin.com/in/...)
4. Brief professional description

Format the response as a JSON array with objects containing:
- name: Full name
- title: Job title
- linkedin_url: Full LinkedIn profile URL
- snippet: Brief professional description

Only include profiles with valid linkedin.com/in/ URLs."""

    try:
        # Use GPT-4o with web search tool
        response = client_ai.responses.create(
            model="gpt-4o",
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
                    {"role": "system", "content": "You are a professional recruiter assistant that helps find LinkedIn profiles. Always return valid JSON."},
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
                    lead = {
                        "name": item.get("name", "").strip(),
                        "title": item.get("title", "").strip(),
                        "linkedin_url": item.get("linkedin_url", "").strip(),
                        "snippet": item.get("snippet", item.get("description", "")).strip(),
                        "source": "openai_search"
                    }
                    # Validate LinkedIn URL
                    if lead["name"] and "linkedin.com/in/" in lead.get("linkedin_url", ""):
                        leads.append(lead)
                    elif lead["name"]:
                        # Try to accept leads without URL but with valid name
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
                "name": name.strip(),
                "title": title.strip(),
                "linkedin_url": "",
                "snippet": "",
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
    
    search_prompt = f"""Search for LinkedIn profiles matching: {clean_query}

Find up to {num_results} relevant professionals on LinkedIn. For each profile:
1. Full name
2. Job title
3. Company name
4. LinkedIn profile URL
5. Brief description

Return as JSON array with: name, title, linkedin_url, company_name, snippet"""

    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional recruiter finding LinkedIn profiles. Return valid JSON arrays only."},
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
