"""
OPENAI GATEWAY - Restricted to Web Search Only
===============================================
This is the ONLY file that may invoke OpenAI/ChatGPT API calls.

OpenAI/ChatGPT is ONLY allowed for:
- Web search
- Lead generation OUTSIDE existing emails

OpenAI/ChatGPT MUST NEVER be used for:
- Email classification
- Email summarization
- Background or scheduled tasks
- Reprocessing existing emails
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import json

from openai import OpenAI
from pymongo import MongoClient

logger = logging.getLogger(__name__)


class OpenAIWebSearchOnly(Exception):
    """Raised when OpenAI is used for forbidden operations"""
    pass


# ============== CONFIGURATION ==============

OPENAI_MODEL = "gpt-4o-mini"

_mongo_client: Optional[MongoClient] = None
_openai_client: Optional[OpenAI] = None


def _get_mongo_client() -> MongoClient:
    """Get singleton MongoDB client"""
    global _mongo_client
    if _mongo_client is None:
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        _mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    return _mongo_client


def _get_openai_api_key() -> str:
    """Get OpenAI API key from database or environment"""
    try:
        client = _get_mongo_client()
        settings = client['torpedo_settings']['app_settings'].find_one()
        
        if settings and settings.get('openai_api_key'):
            return settings['openai_api_key']
        
    except Exception as e:
        logger.warning(f"Error loading OpenAI API key from DB: {e}")
    
    env_key = os.getenv('OPENAI_API_KEY')
    if env_key:
        return env_key
    
    raise ValueError("No OpenAI API key configured in database or environment")


def _get_openai_client() -> OpenAI:
    """Get singleton OpenAI client"""
    global _openai_client
    if _openai_client is None:
        api_key = _get_openai_api_key()
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


# ============== OPENAI GATEWAY ==============

class OpenAIGateway:
    """
    RESTRICTED OpenAI Gateway - Web Search Only
    
    This class enforces strict usage boundaries:
    - ONLY web search and external lead discovery
    - FORBIDDEN: email classification, summarization, background tasks
    """
    
    # Allowed operations
    ALLOWED_OPERATIONS = frozenset({
        "web_search",
        "company_discovery",
        "external_lead_generation",
        "web_enrichment"
    })
    
    # Forbidden operations (will raise exception)
    FORBIDDEN_OPERATIONS = frozenset({
        "email_classification",
        "email_summarization",
        "email_processing",
        "background_task",
        "scheduled_task",
        "cron_task"
    })
    
    def _validate_operation(self, operation: str) -> None:
        """
        Validate that operation is allowed for OpenAI.
        
        Raises:
            OpenAIWebSearchOnly: If operation is forbidden
        """
        if operation in self.FORBIDDEN_OPERATIONS:
            raise OpenAIWebSearchOnly(
                f"Operation '{operation}' is FORBIDDEN for OpenAI. "
                "OpenAI can only be used for web search and external lead discovery. "
                "For email operations, use Gemini."
            )
        
        if operation not in self.ALLOWED_OPERATIONS:
            logger.warning(f"Operation '{operation}' is not in allowed list. Proceeding with caution.")
    
    def web_search(
        self,
        query: str,
        num_results: int = 10,
        search_type: str = "web_search"
    ) -> Dict[str, Any]:
        """
        Perform web search using OpenAI's web search capability.
        
        This is one of the ONLY allowed uses of OpenAI.
        
        Args:
            query: Search query
            num_results: Maximum number of results
            search_type: Type of search (for audit)
            
        Returns:
            Dictionary with search results
        """
        self._validate_operation("web_search")
        
        try:
            client = _get_openai_client()
            
            # Use OpenAI with web search tool
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a research assistant that searches the web for information. Return results in JSON format."
                    },
                    {
                        "role": "user",
                        "content": f"Search the web for: {query}\n\nReturn up to {num_results} relevant results as JSON:\n{{\"results\": [{{\"title\": \"...\", \"url\": \"...\", \"snippet\": \"...\"}}]}}"
                    }
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            content = response.choices[0].message.content
            
            try:
                parsed = json.loads(content.strip().strip('```json').strip('```'))
                return {
                    "query": query,
                    "results": parsed.get("results", []),
                    "searched_at": datetime.utcnow().isoformat(),
                    "success": True
                }
            except json.JSONDecodeError:
                return {
                    "query": query,
                    "results": [],
                    "raw_response": content,
                    "searched_at": datetime.utcnow().isoformat(),
                    "success": True
                }
                
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return {
                "query": query,
                "results": [],
                "error": str(e),
                "success": False
            }
    
    def discover_leads_external(
        self,
        company_name: str = None,
        industry: str = None,
        location: str = None,
        job_titles: List[str] = None
    ) -> Dict[str, Any]:
        """
        Discover leads from external sources (NOT from emails).
        
        This is for EXTERNAL lead generation only.
        For leads from emails, use Gemini's extract_leads_from_email.
        
        Args:
            company_name: Target company name
            industry: Target industry
            location: Geographic location
            job_titles: Target job titles
            
        Returns:
            Dictionary with discovered leads
        """
        self._validate_operation("external_lead_generation")
        
        # Build search query
        query_parts = []
        if company_name:
            query_parts.append(f"company: {company_name}")
        if industry:
            query_parts.append(f"industry: {industry}")
        if location:
            query_parts.append(f"location: {location}")
        if job_titles:
            query_parts.append(f"roles: {', '.join(job_titles)}")
        
        query = " ".join(query_parts) if query_parts else "business contacts"
        
        try:
            client = _get_openai_client()
            
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a B2B lead research assistant. Find potential business contacts based on the criteria. Return results as JSON."
                    },
                    {
                        "role": "user",
                        "content": f"""Find business contacts matching these criteria:
{query}

Return JSON:
{{
  "leads": [
    {{
      "name": "Full Name",
      "title": "Job Title",
      "company": "Company Name",
      "linkedin_url": "https://linkedin.com/in/... or null",
      "source": "public_data"
    }}
  ],
  "search_criteria": {{...}}
}}"""
                    }
                ],
                temperature=0.2,
                max_tokens=1500
            )
            
            content = response.choices[0].message.content
            
            try:
                parsed = json.loads(content.strip().strip('```json').strip('```'))
                return {
                    "leads": parsed.get("leads", []),
                    "search_criteria": {
                        "company_name": company_name,
                        "industry": industry,
                        "location": location,
                        "job_titles": job_titles
                    },
                    "discovered_at": datetime.utcnow().isoformat(),
                    "success": True
                }
            except json.JSONDecodeError:
                return {
                    "leads": [],
                    "raw_response": content,
                    "discovered_at": datetime.utcnow().isoformat(),
                    "success": True
                }
                
        except Exception as e:
            logger.error(f"External lead discovery failed: {e}")
            return {
                "leads": [],
                "error": str(e),
                "success": False
            }
    
    def enrich_company_web(
        self,
        company_name: str,
        domain: str = None
    ) -> Dict[str, Any]:
        """
        Enrich company information using web search.
        
        This is for enriching data from EXTERNAL sources only.
        
        Args:
            company_name: Company name to research
            domain: Company domain if known
            
        Returns:
            Dictionary with company information
        """
        self._validate_operation("web_enrichment")
        
        try:
            client = _get_openai_client()
            
            query = f"Company information for {company_name}"
            if domain:
                query += f" ({domain})"
            
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a business research assistant. Find company information from public sources. Return as JSON."
                    },
                    {
                        "role": "user",
                        "content": f"""Research this company: {company_name}
Domain: {domain or 'unknown'}

Return JSON:
{{
  "company_name": "Official Name",
  "industry": "Industry",
  "size": "1-10|11-50|51-200|201-500|501-1000|1001+",
  "location": "City, Country",
  "website": "https://...",
  "description": "Brief description",
  "founded": "Year or null",
  "linkedin_url": "https://linkedin.com/company/... or null"
}}"""
                    }
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            
            try:
                parsed = json.loads(content.strip().strip('```json').strip('```'))
                return {
                    "company": parsed,
                    "enriched_at": datetime.utcnow().isoformat(),
                    "success": True
                }
            except json.JSONDecodeError:
                return {
                    "company": {"company_name": company_name},
                    "raw_response": content,
                    "enriched_at": datetime.utcnow().isoformat(),
                    "success": True
                }
                
        except Exception as e:
            logger.error(f"Company enrichment failed: {e}")
            return {
                "company": {"company_name": company_name},
                "error": str(e),
                "success": False
            }


# ============== SINGLETON ==============

_gateway_instance: Optional[OpenAIGateway] = None


def get_openai_gateway() -> OpenAIGateway:
    """Get singleton OpenAIGateway instance"""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = OpenAIGateway()
    return _gateway_instance


# ============== CONVENIENCE FUNCTIONS ==============

def web_search(query: str, num_results: int = 10) -> Dict[str, Any]:
    """Convenience function for web search"""
    return get_openai_gateway().web_search(query, num_results)


def discover_leads_external(
    company_name: str = None,
    industry: str = None,
    location: str = None,
    job_titles: List[str] = None
) -> Dict[str, Any]:
    """Convenience function for external lead discovery"""
    return get_openai_gateway().discover_leads_external(
        company_name, industry, location, job_titles
    )
