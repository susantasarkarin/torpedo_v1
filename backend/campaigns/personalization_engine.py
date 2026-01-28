"""
PERSONALIZATION ENGINE
======================

Dynamic email personalization with token replacement and multi-level personalization support.

Features:
- Token-based variable replacement ({{first_name}}, {{company}}, etc.)
- Three personalization levels: Light, Role-Based, and Deep
- Integration with OutreachComposerAgent for AI-generated personalization
- Fallback defaults for missing data
- Safe handling of None values and special characters

Usage:
    from campaigns.personalization_engine import PersonalizationEngine
    
    engine = PersonalizationEngine()
    
    lead_data = {
        "first_name": "John",
        "last_name": "Doe",
        "company_name": "Acme Corp",
        "title": "VP of Sales",
        "industry": "Technology"
    }
    
    content = "Hi {{first_name}}, I noticed {{company}} is in the {{industry}} space..."
    personalized = engine.personalize_content(content, lead_data, level=2)
"""

import logging
import re
from typing import Dict, Optional, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class PersonalizationEngine:
    """
    Engine for dynamic email personalization with multi-level support.
    
    Personalization Levels:
    - Level 1 (Light): Name, company, industry only - minimal personalization
    - Level 2 (Role-Based): + title, seniority, department, pain points - moderate personalization
    - Level 3 (Deep): + AI-generated custom context via OutreachComposerAgent - full personalization
    """
    
    # Token to lead field mapping
    TOKENS = {
        "first_name": "first_name",
        "last_name": "last_name",
        "full_name": None,  # Computed from first_name + last_name
        "company": "company_name",
        "company_name": "company_name",
        "title": "title",
        "job_title": "title",
        "industry": "industry",
        "seniority": "seniority",
        "seniority_level": "seniority",
        "department": "department",
        "pain_point": "pain_point",
        "use_case": "use_case",
        "value_proposition": "value_proposition",
        "location": "location",
        "city": "city",
        "state": "state",
        "country": "country",
        "email": "email",
        "phone": "phone",
        "linkedin": "linkedin_url",
        "website": "website",
        "employee_count": "employee_count",
        "revenue": "revenue",
        "technologies": "technologies",
    }
    
    # Fallback values when data is missing
    FALLBACKS = {
        "first_name": "there",
        "last_name": "",
        "full_name": "there",
        "company": "your company",
        "company_name": "your company",
        "title": "your role",
        "job_title": "your role",
        "industry": "your industry",
        "seniority": "your level",
        "seniority_level": "your level",
        "department": "your department",
        "pain_point": "operational efficiency",
        "use_case": "business growth",
        "value_proposition": "improved outcomes",
        "location": "your area",
        "city": "your city",
        "state": "your state",
        "country": "your region",
        "email": "",
        "phone": "",
        "linkedin": "",
        "website": "",
        "employee_count": "",
        "revenue": "",
        "technologies": "",
    }
    
    # Level 1: Light personalization - only these tokens
    LEVEL_1_TOKENS = {
        "first_name", "last_name", "full_name", 
        "company", "company_name", "industry"
    }
    
    # Level 2: Role-based personalization - Level 1 + these tokens
    LEVEL_2_TOKENS = LEVEL_1_TOKENS | {
        "title", "job_title", "seniority", "seniority_level",
        "department", "pain_point", "location", "city", "state", "country"
    }
    
    # Level 3: Deep personalization - all tokens + AI-generated context
    LEVEL_3_TOKENS = set(TOKENS.keys())
    
    def __init__(self, outreach_agent: Optional[Any] = None):
        """
        Initialize personalization engine.
        
        Args:
            outreach_agent: Optional OutreachComposerAgent for Level 3 personalization
        """
        self.outreach_agent = outreach_agent
        self.logger = logging.getLogger(__name__)
    
    def personalize_content(
        self,
        content: str,
        lead: Dict[str, Any],
        level: int = 2,
        campaign_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Personalize content by replacing tokens with lead data.
        
        Args:
            content: Content with {{token}} placeholders
            lead: Lead data dictionary
            level: Personalization level (1=Light, 2=Role-Based, 3=Deep)
            campaign_context: Optional campaign-specific context for Level 3
        
        Returns:
            Personalized content with tokens replaced
        
        Example:
            >>> engine = PersonalizationEngine()
            >>> lead = {"first_name": "John", "company_name": "Acme"}
            >>> engine.personalize_content("Hi {{first_name}} at {{company}}", lead, level=1)
            "Hi John at Acme"
        """
        if not content:
            return content
        
        if not isinstance(content, str):
            self.logger.warning(f"Content is not a string: {type(content)}")
            return str(content)
        
        # Determine allowed tokens based on level
        allowed_tokens = self._get_allowed_tokens(level)
        
        # Extract all tokens from content
        tokens = self._extract_tokens(content)
        
        # Build replacement dictionary
        replacements = {}
        for token in tokens:
            if token not in allowed_tokens:
                # Token not allowed at this level - replace with empty or fallback
                replacements[token] = self.FALLBACKS.get(token, "")
                continue
            
            # Get value from lead data
            value = self._get_token_value(token, lead)
            replacements[token] = value
        
        # Apply replacements
        personalized = self._apply_replacements(content, replacements)
        
        # Level 3: Add AI-generated context if agent is available
        if level == 3 and self.outreach_agent and campaign_context:
            personalized = self._add_ai_context(personalized, lead, campaign_context)
        
        return personalized
    
    def _get_allowed_tokens(self, level: int) -> set:
        """Get set of allowed tokens for personalization level."""
        if level == 1:
            return self.LEVEL_1_TOKENS
        elif level == 2:
            return self.LEVEL_2_TOKENS
        elif level >= 3:
            return self.LEVEL_3_TOKENS
        else:
            # Default to level 1 for invalid levels
            self.logger.warning(f"Invalid personalization level: {level}, defaulting to 1")
            return self.LEVEL_1_TOKENS
    
    def _extract_tokens(self, content: str) -> List[str]:
        """
        Extract all {{token}} patterns from content.
        
        Returns list of token names without braces.
        """
        pattern = r'\{\{([a-zA-Z0-9_]+)\}\}'
        matches = re.findall(pattern, content)
        return list(set(matches))  # Deduplicate
    
    def _get_token_value(self, token: str, lead: Dict[str, Any]) -> str:
        """
        Get value for a token from lead data.
        
        Handles special computed fields and fallbacks.
        """
        # Special computed field: full_name
        if token in ("full_name", "fullname"):
            first = lead.get("first_name", "").strip()
            last = lead.get("last_name", "").strip()
            if first and last:
                return f"{first} {last}"
            elif first:
                return first
            elif last:
                return last
            else:
                return self.FALLBACKS.get("full_name", "there")
        
        # Regular token mapping
        field_name = self.TOKENS.get(token)
        if not field_name:
            # Unknown token - return fallback
            return self.FALLBACKS.get(token, "")
        
        value = lead.get(field_name)
        
        # Handle None and empty values
        if value is None or value == "":
            return self.FALLBACKS.get(token, "")
        
        # Convert to string and clean
        value = str(value).strip()
        
        # Additional cleaning for specific field types
        if token in ("first_name", "last_name"):
            value = value.capitalize()
        
        return value
    
    def _apply_replacements(self, content: str, replacements: Dict[str, str]) -> str:
        """
        Apply token replacements to content.
        
        Handles both {{token}} and {{ token }} formats (with spaces).
        """
        result = content
        
        for token, value in replacements.items():
            # Replace {{token}} (no spaces)
            pattern1 = r'\{\{' + re.escape(token) + r'\}\}'
            result = re.sub(pattern1, value, result, flags=re.IGNORECASE)
            
            # Replace {{ token }} (with spaces)
            pattern2 = r'\{\{\s*' + re.escape(token) + r'\s*\}\}'
            result = re.sub(pattern2, value, result, flags=re.IGNORECASE)
        
        return result
    
    def _add_ai_context(
        self,
        content: str,
        lead: Dict[str, Any],
        campaign_context: Dict[str, Any]
    ) -> str:
        """
        Add AI-generated personalization context for Level 3.
        
        Integrates with OutreachComposerAgent to generate custom context.
        This is a hook for future AI enhancement.
        """
        if not self.outreach_agent:
            return content
        
        try:
            # This is a placeholder for future integration
            # The OutreachComposerAgent can be called here to enhance content
            # with AI-generated insights about the lead
            
            self.logger.info(f"Level 3 personalization requested for lead: {lead.get('email', 'unknown')}")
            
            # Future implementation:
            # ai_context = self.outreach_agent.generate_context(lead, campaign_context)
            # enhanced_content = self._merge_ai_context(content, ai_context)
            
            return content
            
        except Exception as e:
            self.logger.error(f"Error adding AI context: {e}")
            return content
    
    def batch_personalize(
        self,
        template: str,
        leads: List[Dict[str, Any]],
        level: int = 2,
        campaign_context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, str]]:
        """
        Personalize content for multiple leads in batch.
        
        Args:
            template: Template content with {{tokens}}
            leads: List of lead dictionaries
            level: Personalization level
            campaign_context: Optional campaign context
        
        Returns:
            List of dicts with 'email' and 'personalized_content' keys
        """
        results = []
        
        for lead in leads:
            try:
                personalized = self.personalize_content(
                    template,
                    lead,
                    level=level,
                    campaign_context=campaign_context
                )
                
                results.append({
                    "email": lead.get("email", ""),
                    "lead_id": lead.get("_id", lead.get("id", "")),
                    "personalized_content": personalized,
                    "personalization_level": level,
                    "status": "success"
                })
                
            except Exception as e:
                self.logger.error(f"Error personalizing for lead {lead.get('email', 'unknown')}: {e}")
                results.append({
                    "email": lead.get("email", ""),
                    "lead_id": lead.get("_id", lead.get("id", "")),
                    "personalized_content": template,  # Fallback to original
                    "personalization_level": level,
                    "status": "error",
                    "error": str(e)
                })
        
        return results
    
    def validate_template(self, template: str, level: int = 2) -> Dict[str, Any]:
        """
        Validate a template and return information about tokens.
        
        Args:
            template: Template content to validate
            level: Personalization level to validate against
        
        Returns:
            Dictionary with validation results:
            {
                "valid": bool,
                "tokens_found": List[str],
                "tokens_allowed": List[str],
                "tokens_blocked": List[str],
                "warnings": List[str]
            }
        """
        tokens = self._extract_tokens(template)
        allowed_tokens = self._get_allowed_tokens(level)
        
        tokens_allowed = [t for t in tokens if t in allowed_tokens]
        tokens_blocked = [t for t in tokens if t not in allowed_tokens]
        
        warnings = []
        
        # Check for unknown tokens
        unknown_tokens = [t for t in tokens if t not in self.TOKENS]
        if unknown_tokens:
            warnings.append(f"Unknown tokens found: {', '.join(unknown_tokens)}")
        
        # Check for tokens blocked by level
        if tokens_blocked:
            warnings.append(
                f"Tokens blocked at level {level}: {', '.join(tokens_blocked)}. "
                f"Increase personalization level to use these tokens."
            )
        
        return {
            "valid": len(unknown_tokens) == 0,
            "tokens_found": tokens,
            "tokens_allowed": tokens_allowed,
            "tokens_blocked": tokens_blocked,
            "unknown_tokens": unknown_tokens,
            "warnings": warnings,
            "personalization_level": level
        }
    
    def get_available_tokens(self, level: int = 2) -> Dict[str, str]:
        """
        Get list of available tokens for a personalization level.
        
        Args:
            level: Personalization level (1, 2, or 3)
        
        Returns:
            Dictionary mapping token names to descriptions
        """
        allowed = self._get_allowed_tokens(level)
        
        descriptions = {
            "first_name": "Recipient's first name",
            "last_name": "Recipient's last name",
            "full_name": "Recipient's full name (first + last)",
            "company": "Company name",
            "company_name": "Company name (alias)",
            "title": "Job title",
            "job_title": "Job title (alias)",
            "industry": "Industry/sector",
            "seniority": "Seniority level (e.g., Senior, Manager)",
            "seniority_level": "Seniority level (alias)",
            "department": "Department (e.g., Sales, Marketing)",
            "pain_point": "Identified pain point or challenge",
            "use_case": "Potential use case for product/service",
            "value_proposition": "Customized value proposition",
            "location": "Full location string",
            "city": "City",
            "state": "State/Province",
            "country": "Country",
            "email": "Email address",
            "phone": "Phone number",
            "linkedin": "LinkedIn profile URL",
            "website": "Company website",
            "employee_count": "Number of employees",
            "revenue": "Company revenue",
            "technologies": "Technologies used by company",
        }
        
        return {
            token: descriptions.get(token, "No description")
            for token in allowed
            if token in self.TOKENS
        }


# Convenience function for quick personalization
def personalize_content(
    content: str,
    lead: Dict[str, Any],
    level: int = 2,
    campaign_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Quick personalization function without instantiating engine.
    
    Args:
        content: Content with {{token}} placeholders
        lead: Lead data dictionary
        level: Personalization level (1=Light, 2=Role-Based, 3=Deep)
        campaign_context: Optional campaign-specific context
    
    Returns:
        Personalized content
    """
    engine = PersonalizationEngine()
    return engine.personalize_content(content, lead, level, campaign_context)


# Initialize OutreachComposerAgent integration (lazy loading)
def create_engine_with_ai(config: Optional[Dict[str, Any]] = None) -> PersonalizationEngine:
    """
    Create a PersonalizationEngine with AI integration enabled.
    
    Args:
        config: Configuration for OutreachComposerAgent
    
    Returns:
        PersonalizationEngine instance with AI agent
    """
    try:
        from agents.outreach_composer_agent import OutreachComposerAgent
        agent = OutreachComposerAgent(config=config)
        return PersonalizationEngine(outreach_agent=agent)
    except ImportError:
        logger.warning("OutreachComposerAgent not available, using engine without AI")
        return PersonalizationEngine()
    except Exception as e:
        logger.error(f"Error initializing OutreachComposerAgent: {e}")
        return PersonalizationEngine()
