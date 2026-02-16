"""
OpenAI Web Search Lead Enrichment Module
Uses OpenAI's Responses API with web_search tool for live lead data discovery.

This module enriches potential client companies with detailed company and contact info
using real-time web search. Designed to work with the Potential Clients feature.

Governance Note:
- OpenAI: Web search, company discovery, web enrichment ONLY
- Gemini: Email classification (via ai_governance module)
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Literal
from functools import wraps

from openai import OpenAI
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============

# OpenAI model for web search
OPENAI_WEBSEARCH_MODEL = "gpt-4o"  # Required for web_search tool

# MongoDB collection name for enriched leads
ENRICHED_LEADS_COLLECTION = "potential_client_leads"

# Cache TTL for enriched data (7 days)
ENRICHMENT_CACHE_TTL_DAYS = 7

# Rate limiting
MAX_ENRICHMENTS_PER_MINUTE = 5
MAX_ENRICHMENTS_PER_HOUR = 60

# Default lead fields
LEAD_FIELD_SCHEMA = {
    # Lead Information
    "lead_stage": "Prospect",  # Prospect, Qualified, Contacted, etc.
    "email": None,
    "lead_name": None,  # Primary contact name
    "linkedin_url": None,
    "title": None,  # Job title
    "company": None,
    "location": None,
    "lead_source": "Cint API client list",
    "email_status": None,  # Valid, Invalid, Unknown
    "seniority_level": None,  # C-Level, VP, Director, Manager, etc.
    "department": None,  # Sales, Marketing, Operations, etc.
    "persona": None,  # Decision maker type
    "buying_role": None,  # Economic Buyer, Technical Buyer, etc.
    
    # Company Details
    "company_founded": None,
    "company_headquarters": None,
    "company_linkedin_url": None,
    "company_employee_count_range": None,
    "company_industry": None,
    "company_size": None,  # Small, Medium, Large, Enterprise
    "company_type": None,  # Market Research, Agency, Panel Provider, etc.
    "company_revenue_range": None,
    "company_domain": None,
    "company_website": None,
    
    # Metadata
    "enriched_at": None,
    "enrichment_source": "openai_websearch",
    "confidence_score": None,
    "citations": [],
}


# ============== DATABASE CONNECTION ==============

def get_db_connection():
    """Get MongoDB connection for enriched leads storage."""
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
    return client['email_automation'][ENRICHED_LEADS_COLLECTION]


def get_enrichment_logs_collection():
    """Get collection for enrichment logs."""
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
    return client['email_automation']['lead_enrichment_logs']


# ============== OPENAI CLIENT ==============

_openai_client: Optional[OpenAI] = None


def get_openai_client() -> OpenAI:
    """Get or create OpenAI client singleton."""
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            # Try to get from database settings
            try:
                mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
                client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
                settings = client['torpedo_settings']['app_settings'].find_one({"_id": "app_config"})
                if settings and settings.get("openai_api_key"):
                    api_key = settings["openai_api_key"]
            except Exception as e:
                logger.warning(f"Could not fetch OpenAI key from DB: {e}")
        
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


# ============== RATE LIMITING ==============

class EnrichmentRateLimiter:
    """Rate limiter for enrichment API calls."""
    
    def __init__(self):
        self.request_times: List[datetime] = []
    
    def is_allowed(self) -> bool:
        """Check if enrichment request is allowed."""
        now = datetime.utcnow()
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)
        
        # Clean old entries
        self.request_times = [t for t in self.request_times if t > hour_ago]
        
        # Check minute limit
        recent_minute = len([t for t in self.request_times if t > minute_ago])
        if recent_minute >= MAX_ENRICHMENTS_PER_MINUTE:
            return False
        
        # Check hourly limit
        if len(self.request_times) >= MAX_ENRICHMENTS_PER_HOUR:
            return False
        
        self.request_times.append(now)
        return True


rate_limiter = EnrichmentRateLimiter()


# ============== WEB SEARCH ENRICHMENT ==============

def build_enrichment_prompt(company_name: str, additional_context: Optional[str] = None) -> str:
    """Build the prompt for company/lead enrichment via web search."""
    context_section = ""
    if additional_context:
        context_section = f"\n\nAdditional Context: {additional_context}"
    
    return f"""Research the company "{company_name}" thoroughly using web search.{context_section}

Find and return the following information about this company in JSON format:

{{
  "lead_information": {{
    "lead_stage": "Prospect",
    "email": "<primary business contact email if found, or format pattern>",
    "lead_name": "<key contact name: CEO, VP Sales, or relevant decision maker>",
    "linkedin_url": "<LinkedIn profile URL of the key contact>",
    "title": "<job title of the key contact>",
    "company": "{company_name}",
    "location": "<company headquarters city, state/country>",
    "lead_source": "Cint API client list",
    "email_status": "Unknown",
    "seniority_level": "<C-Level|VP|Director|Manager|Senior|Mid-Level|Entry>",
    "department": "<most likely department: Sales|Marketing|Research|Operations>",
    "persona": "<Decision Maker|Influencer|Champion|End User>",
    "buying_role": "<Economic Buyer|Technical Buyer|User Buyer|Coach>"
  }},
  "company_details": {{
    "company_founded": "<year founded or 'Unknown'>",
    "company_headquarters": "<full address or city, state, country>",
    "company_linkedin_url": "<company LinkedIn page URL>",
    "company_employee_count_range": "<1-10|11-50|51-200|201-500|501-1000|1001-5000|5000+>",
    "company_industry": "<primary industry: Market Research|Data Analytics|Consumer Insights|Technology|etc.>",
    "company_size": "<Startup|Small|Medium|Large|Enterprise>",
    "company_type": "<Market Research Firm|Panel Provider|Data Company|Agency|Technology Company|etc.>",
    "company_revenue_range": "<$1M-$10M|$10M-$50M|$50M-$100M|$100M-$500M|$500M+|Unknown>",
    "company_domain": "<primary website domain>",
    "company_website": "<full website URL>"
  }},
  "confidence_score": <0.0 to 1.0 based on how much information was found>,
  "summary": "<1-2 sentence company description>"
}}

INSTRUCTIONS:
1. Use web search to find the most current information about this company
2. Focus on finding actual contact information for key decision makers
3. If the company appears to be in the market research, panel, or survey industry, prioritize finding operations/partnerships contacts
4. If you cannot find specific information, use "Unknown" rather than guessing
5. Include only verified information from search results
6. The confidence_score should reflect the completeness of data found (0.5+ means good coverage)

Respond ONLY with valid JSON. No explanations or markdown."""


def enrich_company_with_websearch(
    company_name: str,
    additional_context: Optional[str] = None,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Enrich a company/potential client using OpenAI web search.
    
    Args:
        company_name: Name of the company to research
        additional_context: Optional context (e.g., survey info, known industry)
        force_refresh: Skip cache and fetch fresh data
    
    Returns:
        Dictionary with enriched lead and company information
    """
    collection = get_db_connection()
    logs_collection = get_enrichment_logs_collection()
    start_time = time.time()
    
    # Check cache first (unless force refresh)
    if not force_refresh:
        cached = collection.find_one({
            "company": {"$regex": f"^{company_name}$", "$options": "i"},
            "enriched_at": {"$gte": datetime.utcnow() - timedelta(days=ENRICHMENT_CACHE_TTL_DAYS)}
        })
        if cached:
            cached["_id"] = str(cached["_id"])
            cached["from_cache"] = True
            logger.info(f"Returning cached enrichment for {company_name}")
            return cached
    
    # Check rate limit
    if not rate_limiter.is_allowed():
        logger.warning(f"Rate limit exceeded for enrichment")
        return {
            "error": "Rate limit exceeded. Please try again later.",
            "company": company_name,
            "success": False
        }
    
    try:
        client = get_openai_client()
        prompt = build_enrichment_prompt(company_name, additional_context)
        
        # Use the Responses API with web_search tool
        response = client.responses.create(
            model=OPENAI_WEBSEARCH_MODEL,
            tools=[{"type": "web_search"}],
            input=prompt
        )
        
        # Extract the response text
        response_text = ""
        citations = []
        
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if hasattr(content, 'text'):
                        response_text = content.text
                    if hasattr(content, 'annotations'):
                        for annotation in content.annotations:
                            if hasattr(annotation, 'url'):
                                citations.append({
                                    "url": annotation.url,
                                    "title": getattr(annotation, 'title', '')
                                })
        
        # Parse JSON response
        # Clean up markdown if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                data = json.loads(json_match.group())
            else:
                raise ValueError("Could not parse JSON from response")
        
        # Build enriched record
        enriched_record = {
            **LEAD_FIELD_SCHEMA.copy(),
            "company": company_name,
            "enriched_at": datetime.utcnow(),
            "enrichment_source": "openai_websearch",
            "citations": citations[:10],  # Limit citations
            "from_cache": False,
            "success": True
        }
        
        # Merge lead information
        if "lead_information" in data:
            for key, value in data["lead_information"].items():
                if key in enriched_record and value and value != "Unknown":
                    enriched_record[key] = value
        
        # Merge company details
        if "company_details" in data:
            for key, value in data["company_details"].items():
                if key in enriched_record and value and value != "Unknown":
                    enriched_record[key] = value
        
        # Set confidence and summary
        enriched_record["confidence_score"] = data.get("confidence_score", 0.5)
        enriched_record["summary"] = data.get("summary", "")
        
        # Store in database (upsert)
        collection.update_one(
            {"company": {"$regex": f"^{company_name}$", "$options": "i"}},
            {"$set": enriched_record},
            upsert=True
        )
        
        # Log enrichment
        latency_ms = int((time.time() - start_time) * 1000)
        logs_collection.insert_one({
            "company": company_name,
            "timestamp": datetime.utcnow(),
            "success": True,
            "latency_ms": latency_ms,
            "confidence_score": enriched_record["confidence_score"],
            "citations_count": len(citations),
            "model": OPENAI_WEBSEARCH_MODEL
        })
        
        # Add string ID for JSON serialization
        stored = collection.find_one({"company": {"$regex": f"^{company_name}$", "$options": "i"}})
        if stored:
            stored["_id"] = str(stored["_id"])
            return stored
        
        return enriched_record
        
    except Exception as e:
        logger.error(f"Error enriching company {company_name}: {str(e)}")
        
        # Log failure
        latency_ms = int((time.time() - start_time) * 1000)
        logs_collection.insert_one({
            "company": company_name,
            "timestamp": datetime.utcnow(),
            "success": False,
            "error": str(e),
            "latency_ms": latency_ms,
            "model": OPENAI_WEBSEARCH_MODEL
        })
        
        return {
            "error": str(e),
            "company": company_name,
            "success": False
        }


def batch_enrich_companies(
    company_names: List[str],
    delay_between_requests: float = 2.0
) -> List[Dict[str, Any]]:
    """
    Batch enrich multiple companies with rate limiting.
    
    Args:
        company_names: List of company names to enrich
        delay_between_requests: Delay in seconds between API calls
        
    Returns:
        List of enrichment results
    """
    results = []
    
    for i, company in enumerate(company_names):
        logger.info(f"Enriching company {i+1}/{len(company_names)}: {company}")
        
        result = enrich_company_with_websearch(company)
        results.append(result)
        
        # Add delay between requests (skip for last item)
        if i < len(company_names) - 1:
            time.sleep(delay_between_requests)
    
    return results


def get_enriched_lead(company_name: str) -> Optional[Dict[str, Any]]:
    """
    Get an existing enriched lead record.
    
    Args:
        company_name: Company name to look up
        
    Returns:
        Enriched lead record or None if not found
    """
    collection = get_db_connection()
    
    record = collection.find_one({
        "company": {"$regex": f"^{company_name}$", "$options": "i"}
    })
    
    if record:
        record["_id"] = str(record["_id"])
        return record
    
    return None


def get_all_enriched_leads(
    limit: int = 100,
    skip: int = 0,
    min_confidence: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Get all enriched leads with pagination.
    
    Args:
        limit: Maximum records to return
        skip: Records to skip (for pagination)
        min_confidence: Minimum confidence score filter
        
    Returns:
        List of enriched lead records
    """
    collection = get_db_connection()
    
    query = {}
    if min_confidence > 0:
        query["confidence_score"] = {"$gte": min_confidence}
    
    records = list(collection.find(query).sort("enriched_at", -1).skip(skip).limit(limit))
    
    for record in records:
        record["_id"] = str(record["_id"])
    
    return records


def get_unenriched_companies(known_companies: List[str]) -> List[str]:
    """
    Get list of companies that haven't been enriched yet.
    
    Args:
        known_companies: List of all known company names
        
    Returns:
        List of company names that need enrichment
    """
    collection = get_db_connection()
    
    # Get all enriched company names
    enriched_cursor = collection.find(
        {"enriched_at": {"$gte": datetime.utcnow() - timedelta(days=ENRICHMENT_CACHE_TTL_DAYS)}},
        {"company": 1}
    )
    enriched_names = {doc["company"].lower() for doc in enriched_cursor}
    
    # Return companies not in enriched set
    return [c for c in known_companies if c.lower() not in enriched_names]


def get_enrichment_stats() -> Dict[str, Any]:
    """Get statistics about lead enrichment."""
    collection = get_db_connection()
    logs_collection = get_enrichment_logs_collection()
    
    total_enriched = collection.count_documents({})
    high_confidence = collection.count_documents({"confidence_score": {"$gte": 0.7}})
    
    # Recent activity (last 24 hours)
    yesterday = datetime.utcnow() - timedelta(hours=24)
    recent_enrichments = logs_collection.count_documents({
        "timestamp": {"$gte": yesterday},
        "success": True
    })
    recent_failures = logs_collection.count_documents({
        "timestamp": {"$gte": yesterday},
        "success": False
    })
    
    return {
        "total_enriched": total_enriched,
        "high_confidence_count": high_confidence,
        "enrichments_last_24h": recent_enrichments,
        "failures_last_24h": recent_failures,
        "cache_ttl_days": ENRICHMENT_CACHE_TTL_DAYS
    }


# ============== BACKGROUND ENRICHMENT ==============

async def auto_enrich_new_companies(company_names: List[str]):
    """
    Auto-enrich newly discovered companies in the background.
    Should be called when new potential clients are detected.
    
    Args:
        company_names: List of new company names to enrich
    """
    # Get unenriched companies
    unenriched = get_unenriched_companies(company_names)
    
    if not unenriched:
        logger.info("No new companies to enrich")
        return {"enriched": 0, "total": len(company_names)}
    
    logger.info(f"Auto-enriching {len(unenriched)} new companies")
    
    # Enrich with rate limiting (limit to 10 at a time for background jobs)
    to_enrich = unenriched[:10]
    results = batch_enrich_companies(to_enrich, delay_between_requests=3.0)
    
    success_count = len([r for r in results if r.get("success", False)])
    
    return {
        "enriched": success_count,
        "failed": len(to_enrich) - success_count,
        "remaining": len(unenriched) - len(to_enrich),
        "total": len(company_names)
    }
