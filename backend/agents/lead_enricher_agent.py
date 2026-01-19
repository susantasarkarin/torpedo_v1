"""
Lead Enricher Agent - Enrich leads with missing data
"""

import logging
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, LEADS_PER_BATCH
from .schemas import (
    LeadEnricherConfig,
    EnrichedLeadResult,
    LeadEnricherResult,
)

logger = logging.getLogger(__name__)


class LeadEnricherAgent(BaseAgent[LeadEnricherResult]):
    """
    Agent that enriches leads with missing information.
    Uses ChatGPT with web search to fill in missing fields like email, phone, company size.
    
    Input: List of leads with partial information
    Output: Enriched leads with filled-in fields
    """
    
    agent_name = "lead_enricher"
    agent_description = "Enriches leads with missing information via web search"
    output_model = LeadEnricherResult
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.agent_config = LeadEnricherConfig(**(config or {}))
    
    def get_system_prompt(self) -> str:
        return """You are an expert B2B data enrichment specialist. Your task is to find and fill in missing information for leads.

IMPORTANT RULES:
1. Search the web to verify and enrich lead information
2. Generate email addresses based on common patterns when not found
3. Provide confidence scores for enriched fields
4. Only return verified/high-confidence information
5. Do not make up phone numbers unless found in public sources

EMAIL GENERATION PATTERNS (when email not found):
- firstname.lastname@domain.com (most common)
- firstname@domain.com
- f.lastname@domain.com
- firstnamelastname@domain.com

FIELDS TO ENRICH:
- email: Generate based on patterns or find online
- phone: Only if publicly available
- company_size: Estimate from LinkedIn/company website
- company_industry: From company description
- company_revenue: From funding/public data
- company_founded: From company website
- company_headquarters: From company website
- location: From LinkedIn profile

OUTPUT FORMAT (JSON):
{
    "enriched_leads": [
        {
            "lead_id": "original_lead_id",
            "full_name": "John Smith",
            "first_name": "John",
            "last_name": "Smith",
            "email": "john.smith@company.com",
            "email_confidence": 0.85,
            "phone": "+1-555-123-4567",
            "title": "VP of Sales",
            "linkedin_url": "https://linkedin.com/in/johnsmith",
            "location": "San Francisco, CA",
            "company_name": "Acme Corp",
            "company_domain": "acme.com",
            "company_size": "51-200",
            "company_industry": "Software",
            "company_revenue": "$10M-$50M",
            "company_founded": "2015",
            "company_headquarters": "San Francisco, CA",
            "fields_enriched": ["email", "company_size", "company_industry"],
            "enrichment_sources": ["linkedin", "company_website"]
        }
    ],
    "total_enriched": 10,
    "fields_updated": {
        "email": 8,
        "company_size": 10,
        "company_industry": 9
    }
}"""
    
    def build_prompt(self, input_data: Any) -> str:
        """Build the prompt for enriching a batch of leads."""
        leads = []
        
        if isinstance(input_data, list):
            leads = input_data
        elif isinstance(input_data, dict):
            leads = input_data.get("leads", [input_data])
        
        config = self.agent_config
        
        # Build fields to enrich string
        fields_str = ", ".join(config.fields_to_enrich) if config.fields_to_enrich else "all available fields"
        patterns_str = "\n".join([f"  - {p}" for p in config.email_patterns]) if config.email_patterns else ""
        
        # Format leads for the prompt
        leads_formatted = []
        for i, lead in enumerate(leads[:LEADS_PER_BATCH]):
            lead_str = f"""Lead {i+1}:
  - ID: {lead.get('lead_id', lead.get('_id', f'lead_{i+1}'))}
  - Name: {lead.get('full_name', lead.get('name', 'Unknown'))}
  - Title: {lead.get('title', 'Unknown')}
  - Company: {lead.get('company_name', 'Unknown')}
  - Domain: {lead.get('company_domain', lead.get('domain', 'Unknown'))}
  - LinkedIn: {lead.get('linkedin_url', 'Not provided')}
  - Current Email: {lead.get('email', 'Not provided')}"""
            leads_formatted.append(lead_str)
        
        leads_text = "\n\n".join(leads_formatted)
        
        prompt = f"""Enrich the following {len(leads_formatted)} leads with missing information:

{leads_text}

**Fields to Enrich:** {fields_str}

**Email Generation Patterns to Use:**
{patterns_str}

**Requirements:**
1. Search the web to find missing information for each lead
2. Generate email addresses using the patterns above when not found online
3. Provide confidence scores for generated emails (0.0-1.0)
4. {"Verify and correct existing data if inaccurate" if config.verify_existing_data else "Only fill in missing fields, don't change existing data"}
5. Track which fields were enriched for each lead

Return all {len(leads_formatted)} leads with enriched data in the specified JSON format."""
        
        return prompt
    
    def parse_response(self, response_text: str) -> LeadEnricherResult:
        """Parse the AI response into LeadEnricherResult."""
        data = self._extract_json_from_response(response_text)
        
        enriched_leads = []
        for lead_data in data.get("enriched_leads", []):
            try:
                enriched = EnrichedLeadResult(
                    lead_id=lead_data.get("lead_id", ""),
                    full_name=lead_data.get("full_name", ""),
                    first_name=lead_data.get("first_name", ""),
                    last_name=lead_data.get("last_name", ""),
                    email=lead_data.get("email"),
                    email_confidence=lead_data.get("email_confidence", 0.0),
                    phone=lead_data.get("phone"),
                    title=lead_data.get("title", ""),
                    linkedin_url=lead_data.get("linkedin_url", ""),
                    location=lead_data.get("location", ""),
                    company_name=lead_data.get("company_name", ""),
                    company_domain=lead_data.get("company_domain", ""),
                    company_size=lead_data.get("company_size", ""),
                    company_industry=lead_data.get("company_industry", ""),
                    company_revenue=lead_data.get("company_revenue"),
                    company_founded=lead_data.get("company_founded"),
                    company_headquarters=lead_data.get("company_headquarters"),
                    fields_enriched=lead_data.get("fields_enriched", []),
                    enrichment_sources=lead_data.get("enrichment_sources", [])
                )
                enriched_leads.append(enriched)
            except Exception as e:
                logger.warning(f"Failed to parse enriched lead: {e}")
                continue
        
        return LeadEnricherResult(
            enriched_leads=enriched_leads,
            total_enriched=len(enriched_leads),
            fields_updated=data.get("fields_updated", {})
        )
    
    def enrich_leads_batch(self, leads: List[Dict[str, Any]]) -> LeadEnricherResult:
        """
        Enrich a batch of leads.
        
        Args:
            leads: List of lead dicts with at least name and company
            
        Returns:
            LeadEnricherResult with enriched data
        """
        result = self.execute({"leads": leads}, use_web_search=True)
        if result.success and result.data:
            return LeadEnricherResult(**result.data)
        return LeadEnricherResult()
