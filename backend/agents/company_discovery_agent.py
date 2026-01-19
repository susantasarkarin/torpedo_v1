"""
Company Discovery Agent - Find companies matching ICP criteria using web search
"""

import logging
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, LEADS_PER_BATCH
from .schemas import (
    CompanyDiscoveryConfig,
    CompanyResult,
    CompanyDiscoveryResult,
)

logger = logging.getLogger(__name__)


class CompanyDiscoveryAgent(BaseAgent[CompanyDiscoveryResult]):
    """
    Agent that discovers companies matching Ideal Customer Profile (ICP) criteria.
    Uses ChatGPT with web search to find relevant companies.
    
    Input: ICP criteria (industries, sizes, locations, keywords)
    Output: List of 10 companies with domain, industry, size, etc.
    """
    
    agent_name = "company_discovery"
    agent_description = "Discovers companies matching ICP criteria via web search"
    output_model = CompanyDiscoveryResult
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.agent_config = CompanyDiscoveryConfig(**(config or {}))
    
    def get_system_prompt(self) -> str:
        return """You are an expert B2B company researcher. Your task is to find real companies that match specific criteria.

IMPORTANT RULES:
1. Only return REAL companies that you can verify exist
2. Include accurate company website domains (not LinkedIn URLs as domain)
3. Provide realistic employee count estimates
4. Return exactly 10 companies in JSON format
5. Do not make up or hallucinate company information
6. Focus on companies that are actively operating

OUTPUT FORMAT (JSON):
{
    "companies": [
        {
            "name": "Company Name",
            "domain": "company.com",
            "industry": "Industry Name",
            "size_estimate": "50-200",
            "headquarters": "City, Country",
            "description": "Brief description of what they do",
            "linkedin_url": "https://linkedin.com/company/...",
            "founded_year": "2015",
            "source_url": "URL where you found this info"
        }
    ],
    "query_used": "The search query you used",
    "total_found": 10
}"""
    
    def build_prompt(self, input_data: Any) -> str:
        """Build the search prompt from ICP criteria."""
        # Use config if no input provided
        if input_data is None:
            config = self.agent_config
        elif isinstance(input_data, dict):
            config = CompanyDiscoveryConfig(**input_data)
        elif isinstance(input_data, CompanyDiscoveryConfig):
            config = input_data
        else:
            config = self.agent_config
        
        # Build search criteria
        industries_str = ", ".join(config.industries) if config.industries else "any industry"
        sizes_str = ", ".join([s.value if hasattr(s, 'value') else str(s) for s in config.company_sizes]) if config.company_sizes else "any size"
        locations_str = ", ".join(config.locations) if config.locations else "worldwide"
        keywords_str = ", ".join(config.keywords) if config.keywords else ""
        exclude_str = ", ".join(config.exclude_keywords) if config.exclude_keywords else ""
        
        prompt = f"""Find 10 companies matching this Ideal Customer Profile (ICP):

**ICP Description:** {config.icp_description}

**Target Criteria:**
- Industries: {industries_str}
- Company Sizes (employees): {sizes_str}
- Locations: {locations_str}
{f"- Keywords to include: {keywords_str}" if keywords_str else ""}
{f"- Keywords to EXCLUDE: {exclude_str}" if exclude_str else ""}

**Requirements:**
1. Search the web to find real, active companies
2. Verify each company exists and has a working website
3. Include their actual domain (not linkedin.com)
4. Estimate employee count based on available data
5. Return exactly {LEADS_PER_BATCH} companies

Use web search to find companies and return them in the specified JSON format."""
        
        return prompt
    
    def parse_response(self, response_text: str) -> CompanyDiscoveryResult:
        """Parse the AI response into CompanyDiscoveryResult."""
        data = self._extract_json_from_response(response_text)
        
        companies = []
        for company_data in data.get("companies", []):
            try:
                company = CompanyResult(
                    name=company_data.get("name", ""),
                    domain=company_data.get("domain", ""),
                    industry=company_data.get("industry", ""),
                    size_estimate=company_data.get("size_estimate", ""),
                    headquarters=company_data.get("headquarters", ""),
                    description=company_data.get("description", ""),
                    linkedin_url=company_data.get("linkedin_url"),
                    founded_year=company_data.get("founded_year"),
                    source_url=company_data.get("source_url")
                )
                companies.append(company)
            except Exception as e:
                logger.warning(f"Failed to parse company: {e}")
                continue
        
        return CompanyDiscoveryResult(
            companies=companies,
            query_used=data.get("query_used", ""),
            total_found=len(companies)
        )
    
    def execute_with_web_search(self, input_data: Any = None) -> Any:
        """Execute with web search enabled (convenience method)."""
        return self.execute(input_data, use_web_search=True)
