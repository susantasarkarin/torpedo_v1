"""
LEAD INGESTION SERVICE
Multiple data sources: Google Custom Search, CSV, Google Sheets

Cost Optimization:
    - Cache-first approach reduces Google CSE API calls by 70%+
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


def get_google_api_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Get Google API key and Custom Search Engine ID from database or env"""
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


# ============== GOOGLE CUSTOM SEARCH ==============

async def search_linkedin_leads(
    query: str,
    num_results: int = 10,
    start: int = 1,
    skip_cache: bool = False,
    deduplicate: bool = True
) -> List[dict]:
    """
    Search LinkedIn profiles using Google Custom Search API.
    
    COST OPTIMIZATION:
        - Checks cache first (70%+ hit rate target)
        - Caches responses for 48 hours
        - Deduplicates results against existing leads
    
    Args:
        query: Search query (e.g., "CEO automotive industry")
        num_results: Number of results to fetch (max 10 per request)
        start: Starting index for pagination
        skip_cache: Force fresh API call (bypass cache)
        deduplicate: Filter out leads that already exist in database
        
    Returns:
        List of parsed lead data
    """
    # Clean query - remove any existing site: restriction to avoid duplicates
    clean_query = re.sub(r'site:linkedin\.com[^\s]*\s*', '', query, flags=re.IGNORECASE).strip()
    
    # Construct LinkedIn-specific search query
    search_query = f"site:linkedin.com/in/ {clean_query}"
    
    # ===== CACHE CHECK =====
    if not skip_cache:
        cached = get_cached_response(search_query, provider="google_cse")
        if cached:
            leads = cached
            # Apply deduplication to cached results
            if deduplicate and leads:
                unique_leads, duplicates = check_duplicates_batch(leads)
                for dup in duplicates:
                    log_rejected_duplicate(dup, dup.get("_dedup_reason", "Duplicate"), "cache")
                return unique_leads
            return leads
    
    # ===== API CALL =====
    api_key, cse_id = get_google_api_credentials()
    
    if not api_key or not cse_id:
        raise ValueError("Google API Key and CSE ID are required. Configure in Settings.")
    
    # Validate API key format (should start with AIza)
    if not api_key.startswith("AIza"):
        raise ValueError(
            "Invalid Google API Key format. API keys start with 'AIza...'. "
            "You may have entered an OAuth client secret (GOCSPX-...) instead. "
            "Get your API key from Google Cloud Console > APIs & Services > Credentials."
        )
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": cse_id,
        "q": search_query,
        "num": min(num_results, 10),  # Google CSE max is 10 per request
        "start": start
    }
    
    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.get(url, params=params, timeout=15.0)  # Reduced timeout
        except httpx.TimeoutException:
            raise ValueError("Google API request timed out. Check your network connection.")
        except httpx.ConnectError:
            raise ValueError("Could not connect to Google API. Check network connectivity.")
        
        # Handle specific error responses with clear messages
        if response.status_code == 400:
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", "Bad Request")
            except:
                error_msg = response.text[:200]
            raise ValueError(f"Google API Error (400): {error_msg}")
        elif response.status_code == 401:
            raise ValueError("Google API key is invalid or expired. Update your API key in Settings.")
        elif response.status_code == 403:
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", "Access denied")
            except:
                error_msg = "Access denied"
            raise ValueError(f"Google API access denied (403): {error_msg}. Check your API key and ensure Custom Search API is enabled.")
        elif response.status_code == 429:
            raise ValueError("Google API rate limit exceeded. Wait and retry later.")
        elif response.status_code >= 500:
            raise ValueError(f"Google API server error ({response.status_code}). Try again later.")
        
        response.raise_for_status()
        data = response.json()
    
    leads = []
    items = data.get("items", [])
    
    for item in items:
        lead = parse_google_search_result(item)
        if lead:
            leads.append(lead)
    
    # ===== CACHE RESPONSE =====
    if leads:
        cache_response(search_query, leads, provider="google_cse")
    
    # ===== DEDUPLICATION =====
    if deduplicate and leads:
        unique_leads, duplicates = check_duplicates_batch(leads)
        for dup in duplicates:
            log_rejected_duplicate(dup, dup.get("_dedup_reason", "Duplicate"), "google_cse")
        return unique_leads
    
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
        search_query = f"site:linkedin.com/in/ {clean_query}"
        
        cached = get_cached_response(search_query, provider="google_cse")
        
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
    
    return leads


async def search_linkedin_leads_discovery(
    query: str,
    num_results: int = 10,
    skip_cache: bool = False
) -> List[dict]:
    """
    Search LinkedIn using discovery template (broader search, no /in/ restriction).
    
    Used for AI Discovery flow:
    - Template: site:linkedin.com "{designation}" "{company_name}"
    - No /in/ prefix for broader results
    - No designation blocklist (per user requirement)
    
    Args:
        query: Full search query (already formatted with site:linkedin.com)
        num_results: Number of results to fetch (max 10 per request)
        skip_cache: Force fresh API call
        
    Returns:
        List of parsed lead data
    """
    from .search_cache import get_cached_response, cache_response
    
    # ===== CACHE CHECK =====
    if not skip_cache:
        cached = get_cached_response(query, provider="google_cse")
        if cached:
            return cached
    
    # ===== API CALL =====
    api_key, cse_id = get_google_api_credentials()
    
    if not api_key or not cse_id:
        raise ValueError("Google API Key and CSE ID are required. Configure in Settings.")
    
    if not api_key.startswith("AIza"):
        raise ValueError("Invalid Google API Key format.")
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": cse_id,
        "q": query,  # Use query as-is (already includes site:linkedin.com)
        "num": min(num_results, 10)
    }
    
    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(url, params=params, timeout=30.0)
        
        if response.status_code == 400:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", "Bad Request")
            raise ValueError(f"Google API Error: {error_msg}")
        elif response.status_code == 403:
            raise ValueError("Google API access denied.")
        
        response.raise_for_status()
        data = response.json()
    
    leads = []
    items = data.get("items", [])
    
    for item in items:
        lead = parse_google_search_result_discovery(item)
        if lead:
            leads.append(lead)
    
    # ===== CACHE RESPONSE =====
    if leads:
        cache_response(query, leads, provider="google_cse")
    
    return leads


def parse_google_search_result_discovery(item: dict) -> Optional[dict]:
    """
    Parse a Google Custom Search result for discovery mode.
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
