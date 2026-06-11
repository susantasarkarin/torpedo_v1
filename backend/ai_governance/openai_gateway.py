"""
WEB GATEWAY - Claude-backed web search & external discovery
===========================================================
Historically this was the OpenAI gateway (web search only). The codebase is
now Claude-only: the same public API (class/function names kept so existing
imports keep working) is served by Anthropic Claude with its server-side
web_search tool — which performs REAL web searches, unlike the old
implementation that asked GPT to produce "results" from memory.

Boundaries preserved from the original design:
- ONLY web search / external lead discovery / web enrichment
- NEVER email classification, summarization, or background reprocessing
  (use ai_gateway for those)
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import anthropic

from .ai_gateway import _get_anthropic_api_key
from .claude_gateway import DEFAULT_MODEL, _governance_gate, _log_usage, _strip_markdown_json

logger = logging.getLogger(__name__)


class OpenAIWebSearchOnly(Exception):
    """Raised when this gateway is used for forbidden operations (name kept for compat)."""
    pass


class OpenAIGateway:
    """
    RESTRICTED web gateway — Claude-backed (class name kept for compat).

    - ONLY web search and external lead discovery
    - FORBIDDEN: email classification, summarization, background tasks
    """

    ALLOWED_OPERATIONS = frozenset({
        "web_search",
        "company_discovery",
        "external_lead_generation",
        "web_enrichment",
    })

    FORBIDDEN_OPERATIONS = frozenset({
        "email_classification",
        "email_summarization",
        "email_processing",
        "background_task",
        "scheduled_task",
        "cron_task",
    })

    def _validate_operation(self, operation: str) -> None:
        if operation in self.FORBIDDEN_OPERATIONS:
            raise OpenAIWebSearchOnly(
                f"Operation '{operation}' is FORBIDDEN for the web gateway. "
                "It may only be used for web search and external lead discovery. "
                "For email operations, use ai_gateway."
            )
        if operation not in self.ALLOWED_OPERATIONS:
            logger.warning(f"Operation '{operation}' is not in allowed list. Proceeding with caution.")

    def _search_call(self, instruction: str, query: str, max_uses: int = 5,
                     task_type: str = "web_search") -> str:
        """One governed Claude call with the server-side web_search tool."""
        _governance_gate()
        client = anthropic.Anthropic(api_key=_get_anthropic_api_key())
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=16000,
            system=instruction,
            tools=[{"type": "web_search_20260209", "name": "web_search",
                    "max_uses": max_uses}],
            messages=[{"role": "user", "content": query}],
        )
        _log_usage(task_type, DEFAULT_MODEL, response.usage, caller="web_gateway")
        return " ".join(b.text for b in response.content if b.type == "text").strip()

    @staticmethod
    def _parse_json(content: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(_strip_markdown_json(content))
        except json.JSONDecodeError:
            return None

    def web_search(self, query: str, num_results: int = 10,
                   search_type: str = "web_search") -> Dict[str, Any]:
        """Perform a real web search via Claude's server-side web_search tool."""
        self._validate_operation("web_search")
        try:
            content = self._search_call(
                "You are a research assistant. Search the web and return results as JSON only:\n"
                '{"results": [{"title": "...", "url": "...", "snippet": "..."}]}',
                f"Search the web for: {query}\nReturn up to {num_results} relevant results.",
                max_uses=max(1, min(num_results, 10)),
            )
            parsed = self._parse_json(content)
            if parsed is not None:
                return {"query": query, "results": parsed.get("results", []),
                        "searched_at": datetime.utcnow().isoformat(), "success": True}
            return {"query": query, "results": [], "raw_response": content,
                    "searched_at": datetime.utcnow().isoformat(), "success": True}
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return {"query": query, "results": [], "error": str(e), "success": False}

    def discover_leads_external(self, company_name: str = None, industry: str = None,
                                location: str = None,
                                job_titles: List[str] = None) -> Dict[str, Any]:
        """Discover leads from external (web) sources — NOT from emails."""
        self._validate_operation("external_lead_generation")

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
            content = self._search_call(
                "You are a B2B lead research assistant. Search the web for potential "
                "business contacts matching the criteria. Return JSON only:\n"
                '{"leads": [{"name": "Full Name", "title": "Job Title", "company": "Company Name", '
                '"linkedin_url": "https://linkedin.com/in/... or null", "source": "public_data"}]}',
                f"Find business contacts matching these criteria: {query}",
                task_type="external_lead_discovery",
            )
            parsed = self._parse_json(content)
            criteria = {"company_name": company_name, "industry": industry,
                        "location": location, "job_titles": job_titles}
            if parsed is not None:
                return {"leads": parsed.get("leads", []), "search_criteria": criteria,
                        "discovered_at": datetime.utcnow().isoformat(), "success": True}
            return {"leads": [], "raw_response": content,
                    "discovered_at": datetime.utcnow().isoformat(), "success": True}
        except Exception as e:
            logger.error(f"External lead discovery failed: {e}")
            return {"leads": [], "error": str(e), "success": False}

    def enrich_company_web(self, company_name: str, domain: str = None) -> Dict[str, Any]:
        """Enrich company information using real web search."""
        self._validate_operation("web_enrichment")
        try:
            content = self._search_call(
                "You are a business research assistant. Search the web for company "
                "information from public sources. Return JSON only:\n"
                '{"company_name": "Official Name", "industry": "Industry", '
                '"size": "1-10|11-50|51-200|201-500|501-1000|1001+", "location": "City, Country", '
                '"website": "https://...", "description": "Brief description", '
                '"founded": "Year or null", "linkedin_url": "https://linkedin.com/company/... or null"}',
                f"Research this company: {company_name} (domain: {domain or 'unknown'})",
                task_type="web_enrichment",
            )
            parsed = self._parse_json(content)
            if parsed is not None:
                return {"company": parsed, "enriched_at": datetime.utcnow().isoformat(),
                        "success": True}
            return {"company": {"company_name": company_name}, "raw_response": content,
                    "enriched_at": datetime.utcnow().isoformat(), "success": True}
        except Exception as e:
            logger.error(f"Company enrichment failed: {e}")
            return {"company": {"company_name": company_name}, "error": str(e), "success": False}


# ============== SINGLETON ==============

_gateway_instance: Optional[OpenAIGateway] = None


def get_openai_gateway() -> OpenAIGateway:
    """Get singleton gateway instance (name kept for compat — Claude-backed)."""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = OpenAIGateway()
    return _gateway_instance


# ============== CONVENIENCE FUNCTIONS ==============

def web_search(query: str, num_results: int = 10) -> Dict[str, Any]:
    return get_openai_gateway().web_search(query, num_results)


def discover_leads_external(company_name: str = None, industry: str = None,
                            location: str = None,
                            job_titles: List[str] = None) -> Dict[str, Any]:
    return get_openai_gateway().discover_leads_external(
        company_name, industry, location, job_titles
    )
