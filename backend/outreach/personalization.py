"""
PERSONALIZATION ENGINE
=====================

Dynamic email personalization system supporting three levels:
- Level 1 (Light): Name, company, industry
- Level 2 (Role-Based - Default): + Title, seniority, department, pain points
- Level 3 (Deep): + Company-specific context, triggers, insights

Supported tokens:
- {{first_name}}, {{last_name}}, {{company}}, {{title}}
- {{industry}}, {{seniority}}, {{department}}
- {{pain_point}}, {{use_case}}, {{value_proposition}}
"""

import re
from typing import Dict, List, Optional, Any
from .models import OutreachLead, PersonalizationLevel, EmailTemplate


class PersonalizationEngine:
    """
    Engine for generating personalized email content from templates and lead data.
    """
    
    # Token definitions by personalization level
    LEVEL_TOKENS = {
        PersonalizationLevel.LIGHT: [
            "first_name",
            "last_name",
            "company",
            "industry"
        ],
        PersonalizationLevel.ROLE_BASED: [
            "first_name",
            "last_name",
            "company",
            "industry",
            "title",
            "seniority",
            "department",
            "pain_point"
        ],
        PersonalizationLevel.DEEP: [
            "first_name",
            "last_name",
            "company",
            "industry",
            "title",
            "seniority",
            "department",
            "pain_point",
            "use_case",
            "value_proposition",
            "custom_context"
        ]
    }
    
    def __init__(self):
        """Initialize the personalization engine."""
        pass
    
    def extract_tokens(self, text: str) -> List[str]:
        """
        Extract all personalization tokens from a text string.
        
        Args:
            text: Text containing {{tokens}}
        
        Returns:
            List of unique token names
        """
        pattern = r'\{\{(\w+)\}\}'
        tokens = re.findall(pattern, text)
        return list(set(tokens))
    
    def get_required_tokens(self, template: EmailTemplate) -> List[str]:
        """
        Get all required tokens from a template.
        
        Args:
            template: Email template
        
        Returns:
            List of required token names
        """
        subject_tokens = self.extract_tokens(template.subject)
        body_tokens = self.extract_tokens(template.body_html)
        return list(set(subject_tokens + body_tokens))
    
    def get_available_tokens(self, level: PersonalizationLevel) -> List[str]:
        """
        Get available tokens for a personalization level.
        
        Args:
            level: Personalization level
        
        Returns:
            List of available token names
        """
        return self.LEVEL_TOKENS.get(level, [])
    
    def build_token_data(
        self,
        lead: OutreachLead,
        level: PersonalizationLevel,
        custom_data: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """
        Build token replacement dictionary from lead data.
        
        Args:
            lead: Lead with personalization data
            level: Personalization level to use
            custom_data: Additional custom token values
        
        Returns:
            Dictionary of token name -> value
        """
        data = {}
        available_tokens = self.get_available_tokens(level)
        
        # Map lead fields to tokens
        token_mapping = {
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "company": lead.company,
            "industry": lead.industry or "your industry",
            "title": lead.title or "your role",
            "seniority": lead.seniority.value if lead.seniority else "professional",
            "department": lead.department.value if lead.department else "team",
            "pain_point": lead.pain_point or "business challenges",
            "use_case": lead.use_case or "similar organizations",
            "value_proposition": lead.value_proposition or "tailored solutions"
        }
        
        # Only include tokens available at this level
        for token in available_tokens:
            if token in token_mapping:
                data[token] = str(token_mapping[token])
        
        # Add custom data
        if custom_data:
            for key, value in custom_data.items():
                if key in available_tokens or level == PersonalizationLevel.DEEP:
                    data[key] = value
        
        # Add custom fields from lead
        if lead.custom_fields and level == PersonalizationLevel.DEEP:
            for key, value in lead.custom_fields.items():
                data[key] = str(value)
        
        return data
    
    def render_template(
        self,
        template: EmailTemplate,
        lead: OutreachLead,
        level: Optional[PersonalizationLevel] = None,
        custom_data: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """
        Render an email template with personalization.
        
        Args:
            template: Email template to render
            lead: Lead data for personalization
            level: Personalization level (uses lead's level if not specified)
            custom_data: Additional custom tokens
        
        Returns:
            Dictionary with 'subject', 'body_html', 'body_plain'
        
        Raises:
            ValueError: If required tokens are missing
        """
        # Use lead's personalization level if not specified
        if level is None:
            level = lead.personalization_level
        
        # Build token data
        token_data = self.build_token_data(lead, level, custom_data)
        
        # Check for required tokens
        required_tokens = self.get_required_tokens(template)
        missing_tokens = [t for t in required_tokens if t not in token_data]
        
        if missing_tokens:
            raise ValueError(
                f"Missing required tokens for personalization level {level.value}: "
                f"{', '.join(missing_tokens)}"
            )
        
        # Render subject
        subject = self._replace_tokens(template.subject, token_data)
        
        # Render body
        body_html = self._replace_tokens(template.body_html, token_data)
        body_plain = ""
        
        if template.body_plain:
            body_plain = self._replace_tokens(template.body_plain, token_data)
        else:
            # Generate plain text from HTML if not provided
            body_plain = self._html_to_plain(body_html)
        
        return {
            "subject": subject,
            "body_html": body_html,
            "body_plain": body_plain,
            "tokens_used": token_data
        }
    
    def _replace_tokens(self, text: str, data: Dict[str, str]) -> str:
        """
        Replace all {{tokens}} in text with values from data.
        
        Args:
            text: Text with {{tokens}}
            data: Token name -> value mapping
        
        Returns:
            Text with tokens replaced
        """
        result = text
        for token, value in data.items():
            placeholder = f"{{{{{token}}}}}"
            result = result.replace(placeholder, str(value))
        
        # Replace any remaining tokens with empty string (fallback)
        result = re.sub(r'\{\{\w+\}\}', '', result)
        
        return result
    
    def _html_to_plain(self, html: str) -> str:
        """
        Convert HTML to plain text.
        
        Args:
            html: HTML content
        
        Returns:
            Plain text version
        """
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', html)
        
        # Decode common HTML entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def validate_template(
        self,
        template: EmailTemplate,
        level: PersonalizationLevel
    ) -> Dict[str, Any]:
        """
        Validate if a template can be used at a given personalization level.
        
        Args:
            template: Template to validate
            level: Personalization level
        
        Returns:
            Validation result with 'valid', 'missing_tokens', 'warnings'
        """
        required_tokens = self.get_required_tokens(template)
        available_tokens = self.get_available_tokens(level)
        
        missing_tokens = [t for t in required_tokens if t not in available_tokens]
        
        return {
            "valid": len(missing_tokens) == 0,
            "missing_tokens": missing_tokens,
            "warnings": [
                f"Token '{token}' is not available at level {level.value}"
                for token in missing_tokens
            ]
        }
    
    def get_token_preview(self, lead: OutreachLead) -> Dict[str, Any]:
        """
        Get a preview of all available tokens for a lead at each level.
        
        Args:
            lead: Lead to preview
        
        Returns:
            Dictionary mapping levels to token data
        """
        preview = {}
        
        for level in PersonalizationLevel:
            preview[level.value] = self.build_token_data(lead, level)
        
        return preview


# Utility function for quick rendering
def personalize_email(
    template: EmailTemplate,
    lead: OutreachLead,
    level: Optional[PersonalizationLevel] = None,
    custom_data: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """
    Quick utility to personalize an email template.
    
    Args:
        template: Email template
        lead: Lead data
        level: Personalization level (optional)
        custom_data: Additional custom tokens (optional)
    
    Returns:
        Personalized email content
    """
    engine = PersonalizationEngine()
    return engine.render_template(template, lead, level, custom_data)
