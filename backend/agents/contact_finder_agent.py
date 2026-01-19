"""
Contact Finder Agent - Find decision-makers at target companies using web search
"""

import logging
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, LEADS_PER_BATCH
from .schemas import (
    ContactFinderConfig,
    ContactResult,
    ContactFinderResult,
)

logger = logging.getLogger(__name__)


class ContactFinderAgent(BaseAgent[ContactFinderResult]):
    """
    Agent that finds decision-makers at target companies.
    Uses ChatGPT with web search to find contacts with LinkedIn profiles and emails.
    
    Input: Company name/domain and target criteria (titles, decision levels)
    Output: List of 10 contacts with name, title, LinkedIn, email guess
    """
    
    agent_name = "contact_finder"
    agent_description = "Finds decision-makers at target companies via web search"
    output_model = ContactFinderResult
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.agent_config = ContactFinderConfig(**(config or {}))
    
    def get_system_prompt(self) -> str:
        return """You are an expert B2B contact researcher. Your task is to find real people who work at specified companies.

IMPORTANT RULES:
1. Only return REAL people with verifiable LinkedIn profiles
2. Focus on decision-makers and senior roles
3. Generate email guesses based on common patterns (firstname.lastname@domain.com, etc.)
4. Return exactly 10 contacts per company in JSON format
5. Do not make up or hallucinate contact information
6. Include LinkedIn profile URLs when available

EMAIL GUESS PATTERNS (try these in order):
- firstname.lastname@domain.com
- firstname@domain.com
- f.lastname@domain.com
- firstnamelastname@domain.com

OUTPUT FORMAT (JSON):
{
    "contacts": [
        {
            "full_name": "John Smith",
            "first_name": "John",
            "last_name": "Smith",
            "title": "VP of Sales",
            "company_name": "Acme Corp",
            "company_domain": "acme.com",
            "linkedin_url": "https://linkedin.com/in/johnsmith",
            "email_guess": "john.smith@acme.com",
            "decision_level": "VP",
            "department": "Sales",
            "location": "San Francisco, CA",
            "source_url": "URL where found"
        }
    ],
    "company_name": "Acme Corp",
    "company_domain": "acme.com",
    "total_found": 10
}"""
    
    def build_prompt(self, input_data: Any) -> str:
        """Build the search prompt for finding contacts at a company."""
        # Extract company info from input
        company_name = ""
        company_domain = ""
        
        if isinstance(input_data, dict):
            company_name = input_data.get("company_name", "")
            company_domain = input_data.get("company_domain", input_data.get("domain", ""))
        elif isinstance(input_data, str):
            # Assume it's a company name
            company_name = input_data
        
        config = self.agent_config
        
        # Build target criteria
        titles_str = ", ".join(config.target_titles) if config.target_titles else "any senior role"
        levels_str = ", ".join([l.value if hasattr(l, 'value') else str(l) for l in config.decision_levels]) if config.decision_levels else "any level"
        departments_str = ", ".join(config.departments) if config.departments else "any department"
        
        prompt = f"""Find 10 decision-makers at this company:

**Company:** {company_name}
**Domain:** {company_domain if company_domain else "unknown - please find it"}

**Target Contacts:**
- Job Titles: {titles_str}
- Decision Levels: {levels_str}
- Departments: {departments_str}

**Requirements:**
1. Search the web and LinkedIn to find real employees
2. Verify each person works at this company
3. Find their LinkedIn profile URL if available
4. Generate email guesses based on the company domain
5. Include their job title and department
6. Return exactly {LEADS_PER_BATCH} contacts

{"Include LinkedIn profile URLs for each contact." if config.include_linkedin else ""}
{"Generate email guesses based on common patterns." if config.include_email_guess else ""}

Use web search to find contacts and return them in the specified JSON format."""
        
        return prompt
    
    def parse_response(self, response_text: str) -> ContactFinderResult:
        """Parse the AI response into ContactFinderResult."""
        data = self._extract_json_from_response(response_text)
        
        contacts = []
        for contact_data in data.get("contacts", []):
            try:
                # Parse name if not split
                full_name = contact_data.get("full_name", "")
                first_name = contact_data.get("first_name", "")
                last_name = contact_data.get("last_name", "")
                
                if full_name and not first_name:
                    name_parts = full_name.split(" ", 1)
                    first_name = name_parts[0] if name_parts else ""
                    last_name = name_parts[1] if len(name_parts) > 1 else ""
                
                contact = ContactResult(
                    full_name=full_name or f"{first_name} {last_name}".strip(),
                    first_name=first_name,
                    last_name=last_name,
                    title=contact_data.get("title", ""),
                    company_name=contact_data.get("company_name", data.get("company_name", "")),
                    company_domain=contact_data.get("company_domain", data.get("company_domain", "")),
                    linkedin_url=contact_data.get("linkedin_url"),
                    email_guess=contact_data.get("email_guess"),
                    decision_level=contact_data.get("decision_level", "Unknown"),
                    department=contact_data.get("department", ""),
                    location=contact_data.get("location"),
                    source_url=contact_data.get("source_url")
                )
                contacts.append(contact)
            except Exception as e:
                logger.warning(f"Failed to parse contact: {e}")
                continue
        
        return ContactFinderResult(
            contacts=contacts,
            company_name=data.get("company_name", ""),
            company_domain=data.get("company_domain", ""),
            total_found=len(contacts)
        )
    
    def execute_with_web_search(self, company_name: str, company_domain: str = "") -> Any:
        """Execute with web search enabled (convenience method)."""
        return self.execute(
            {"company_name": company_name, "company_domain": company_domain},
            use_web_search=True
        )
    
    def find_contacts_for_companies(self, companies: List[Dict[str, str]]) -> List[ContactFinderResult]:
        """
        Find contacts for multiple companies.
        
        Args:
            companies: List of dicts with 'name' and 'domain' keys
            
        Returns:
            List of ContactFinderResult, one per company
        """
        results = []
        for company in companies:
            result = self.execute(
                {
                    "company_name": company.get("name", company.get("company_name", "")),
                    "company_domain": company.get("domain", company.get("company_domain", ""))
                },
                use_web_search=True
            )
            if result.success and result.data:
                results.append(ContactFinderResult(**result.data))
        return results
