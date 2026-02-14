"""
TEMPLATE RENDERER
=================

Template-based email rendering with token replacement.

Token System:
- {{first_name}} - Lead first name
- {{last_name}} - Lead last name
- {{full_name}} - First + Last name
- {{company}} - Company name
- {{industry}} - Industry
- {{title}} - Job title
- {{ai_context_block}} - AI-generated contextual paragraph
- {{ai_hook}} - AI-generated hook sentence (Heavy only)
- {{signature}} - Dynamic mailbox signature

Rules:
- Signature is pulled dynamically per mailbox
- Signature is NOT stored in template
- AI context block is inserted at {{ai_context_block}} placeholder
- All tokens have fallback values
"""

import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List
from pymongo.database import Database

from .models import PersonalizationLevel

logger = logging.getLogger(__name__)


class TemplateRenderer:
    """
    Renders email templates with token replacement.
    
    Responsibilities:
    - Replace tokens with lead data
    - Insert AI context block
    - Append dynamic signature
    - Handle missing data gracefully
    """
    
    # Token to field mapping
    TOKEN_MAPPING = {
        "first_name": "first_name",
        "last_name": "last_name",
        "full_name": None,  # Computed
        "company": "company",
        "company_name": "company",
        "industry": "industry",
        "title": "title",
        "job_title": "title",
        "email": "email",
        "ai_context_block": "ai_context_block",
        "ai_hook": "ai_hook",
        "signature": None,  # Dynamic
    }
    
    # Fallback values for missing tokens
    FALLBACKS = {
        "first_name": "there",
        "last_name": "",
        "full_name": "there",
        "company": "your company",
        "company_name": "your company",
        "industry": "your industry",
        "title": "your role",
        "job_title": "your role",
        "email": "",
        "ai_context_block": "",
        "ai_hook": "",
        "signature": "",
    }
    
    def __init__(self, db: Database):
        """
        Initialize template renderer.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.templates_collection = db["outreach_templates_v2"]
    
    def render_email(
        self,
        template_id: str,
        lead_data: Dict[str, Any],
        ai_context_block: Optional[str] = None,
        ai_hook: Optional[str] = None,
        signature_html: str = "",
        signature_plain: str = "",
        personalization_level: PersonalizationLevel = PersonalizationLevel.LIGHT
    ) -> Dict[str, str]:
        """
        Render email template with full personalization.
        
        Args:
            template_id: Template to render
            lead_data: Lead data for token replacement
            ai_context_block: Pre-generated AI context block
            ai_hook: Pre-generated AI hook sentence (Heavy only)
            signature_html: HTML signature to append
            signature_plain: Plain text signature to append
            personalization_level: Level of personalization applied
            
        Returns:
            Dictionary with 'subject', 'body_html', 'body_plain'
        """
        # Get template
        template = self.templates_collection.find_one({"template_id": template_id})
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        # Prepare token values
        token_values = self._prepare_token_values(
            lead_data,
            ai_context_block,
            ai_hook,
            signature_html
        )
        
        # Render subject
        subject = self._replace_tokens(template["subject"], token_values)
        
        # Render body HTML
        body_html = self._replace_tokens(template["body_html"], token_values)
        
        # Append signature if not already in template
        if signature_html and "{{signature}}" not in template["body_html"]:
            body_html = body_html + f"\n\n{signature_html}"
        
        # Render body plain
        body_plain = template.get("body_plain", "")
        if body_plain:
            plain_tokens = token_values.copy()
            plain_tokens["signature"] = signature_plain
            body_plain = self._replace_tokens(body_plain, plain_tokens)
        else:
            # Generate plain text from HTML
            body_plain = self._html_to_plain(body_html)
        
        return {
            "subject": subject.strip(),
            "body_html": body_html.strip(),
            "body_plain": body_plain.strip(),
        }
    
    def render_quick(
        self,
        subject: str,
        body_html: str,
        lead_data: Dict[str, Any],
        signature_html: str = ""
    ) -> Dict[str, str]:
        """
        Quick render without template lookup.
        
        Args:
            subject: Subject template
            body_html: HTML body template
            lead_data: Lead data
            signature_html: Signature to append
            
        Returns:
            Rendered email
        """
        token_values = self._prepare_token_values(
            lead_data,
            ai_context_block=None,
            ai_hook=None,
            signature=signature_html
        )
        
        rendered_subject = self._replace_tokens(subject, token_values)
        rendered_body = self._replace_tokens(body_html, token_values)
        
        # Append signature
        if signature_html and "{{signature}}" not in body_html:
            rendered_body = rendered_body + f"\n\n{signature_html}"
        
        return {
            "subject": rendered_subject.strip(),
            "body_html": rendered_body.strip(),
            "body_plain": self._html_to_plain(rendered_body).strip(),
        }
    
    def _prepare_token_values(
        self,
        lead_data: Dict[str, Any],
        ai_context_block: Optional[str],
        ai_hook: Optional[str],
        signature: str
    ) -> Dict[str, str]:
        """
        Prepare token values from lead data.
        """
        values = {}
        
        # Map standard tokens
        for token, field in self.TOKEN_MAPPING.items():
            if field:
                value = lead_data.get(field)
                if value:
                    values[token] = str(value)
                else:
                    values[token] = self.FALLBACKS.get(token, "")
        
        # Compute full_name
        first = lead_data.get("first_name", "")
        last = lead_data.get("last_name", "")
        if first or last:
            values["full_name"] = f"{first} {last}".strip()
        else:
            values["full_name"] = self.FALLBACKS["full_name"]
        
        # Add AI blocks
        if ai_context_block:
            values["ai_context_block"] = ai_context_block
        else:
            values["ai_context_block"] = ""
        
        if ai_hook:
            values["ai_hook"] = ai_hook
        else:
            values["ai_hook"] = ""
        
        # Add signature
        values["signature"] = signature
        
        # Add custom fields
        custom = lead_data.get("custom_fields", {})
        for key, value in custom.items():
            values[key] = str(value) if value else ""
        
        return values
    
    def _replace_tokens(self, text: str, values: Dict[str, str]) -> str:
        """
        Replace {{token}} placeholders in text.
        """
        def replace_match(match):
            token = match.group(1).strip()
            return values.get(token, self.FALLBACKS.get(token, ""))
        
        # Match {{token}} with optional whitespace
        pattern = r'\{\{\s*(\w+)\s*\}\}'
        return re.sub(pattern, replace_match, text)
    
    def _html_to_plain(self, html: str) -> str:
        """
        Convert HTML to plain text.
        """
        # Remove style and script tags
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Convert line breaks
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?p[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?div[^>]*>', '\n', text, flags=re.IGNORECASE)
        
        # Remove remaining tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Decode entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")
        
        # Normalize whitespace
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        
        return text.strip()
    
    # ============== TEMPLATE MANAGEMENT ==============
    
    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Get template by ID"""
        return self.templates_collection.find_one({"template_id": template_id})
    
    def list_templates(
        self,
        company_brand: Optional[str] = None,
        step_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List templates with filters.
        
        Args:
            company_brand: Filter by brand
            step_type: Filter by step type
            
        Returns:
            List of template documents
        """
        query: Dict[str, Any] = {"is_active": True}
        
        if company_brand:
            query["company_brand"] = company_brand
        
        if step_type:
            query["step_type"] = step_type
        
        return list(self.templates_collection.find(query))
    
    def create_template(
        self,
        name: str,
        subject: str,
        body_html: str,
        step_type: str = "initial",
        company_brand: str = "surveyfieldwork",
        description: Optional[str] = None
    ) -> str:
        """
        Create new email template.
        
        Args:
            name: Template name
            subject: Subject line template
            body_html: HTML body template
            step_type: Step type (initial, follow_up_1, etc.)
            company_brand: Company brand
            description: Optional description
            
        Returns:
            Created template ID
        """
        from bson import ObjectId
        
        # Extract tokens from template
        tokens = list(set(re.findall(r'\{\{(\w+)\}\}', subject + body_html)))
        
        template_id = str(ObjectId())
        
        doc = {
            "template_id": template_id,
            "name": name,
            "description": description,
            "subject": subject,
            "body_html": body_html,
            "body_plain": self._html_to_plain(body_html),
            "step_type": step_type,
            "tokens": tokens,
            "company_brand": company_brand,
            "category": "outreach",
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        
        self.templates_collection.insert_one(doc)
        logger.info(f"Created template {template_id}: {name}")
        
        return template_id
    
    def validate_template(self, template_id: str) -> Dict[str, Any]:
        """
        Validate template for required tokens.
        
        Returns:
            Validation result with warnings
        """
        template = self.get_template(template_id)
        if not template:
            return {"valid": False, "error": "Template not found"}
        
        tokens = template.get("tokens", [])
        
        warnings = []
        
        # Check for common issues
        if "first_name" not in tokens:
            warnings.append("Template missing {{first_name}} - email may seem impersonal")
        
        if "signature" not in tokens and "{{signature}}" not in template.get("body_html", ""):
            warnings.append("Template missing {{signature}} - signature will be appended at end")
        
        # Check for unknown tokens
        known_tokens = set(self.TOKEN_MAPPING.keys())
        for token in tokens:
            if token not in known_tokens:
                warnings.append(f"Unknown token {{{{token}}}} - will use fallback or custom field")
        
        return {
            "valid": True,
            "tokens_found": tokens,
            "warnings": warnings
        }


# ============== DEFAULT TEMPLATES ==============

def create_default_templates(db: Database, company_brand: str = "surveyfieldwork"):
    """
    Create default enterprise outreach templates.
    """
    renderer = TemplateRenderer(db)
    
    templates = [
        {
            "name": f"{company_brand.title()} - Initial Outreach",
            "step_type": "initial",
            "subject": "{{first_name}}, quick question about {{company}}",
            "body_html": """
<div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
    <p>Hi {{first_name}},</p>
    
    <p>I hope this email finds you well. I noticed {{company}} is in the {{industry}} space and wanted to reach out.</p>
    
    {{ai_context_block}}
    
    <p>We specialize in helping organizations like yours gather high-quality insights through:</p>
    <ul>
        <li><strong>Global Audience Sampling</strong> - Access to verified respondents across 50+ countries</li>
        <li><strong>Survey Programming & Hosting</strong> - Professional survey design</li>
        <li><strong>Quality Assurance</strong> - AI-powered fraud detection</li>
    </ul>
    
    <p>Would you be open to a brief 15-minute conversation to explore how we can support your research needs?</p>
    
    <p>Looking forward to hearing from you.</p>
    
    {{signature}}
</div>
""",
        },
        {
            "name": f"{company_brand.title()} - Follow-up 1",
            "step_type": "follow_up_1",
            "subject": "Re: Quick question about {{company}}",
            "body_html": """
<div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
    <p>Hi {{first_name}},</p>
    
    <p>I wanted to follow up on my previous email. I understand you're busy, so I'll keep this brief.</p>
    
    <p>Many {{title}}s I've worked with in {{industry}} found value in:</p>
    <ul>
        <li>Fast turnaround times with real-time data collection</li>
        <li>Multi-layered quality controls and fraud prevention</li>
        <li>Access to niche B2B audiences at scale</li>
    </ul>
    
    <p>Would a 10-minute call next week work to discuss your current research priorities?</p>
    
    {{signature}}
</div>
""",
        },
        {
            "name": f"{company_brand.title()} - Follow-up 2",
            "step_type": "follow_up_2",
            "subject": "Re: Quick question about {{company}}",
            "body_html": """
<div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
    <p>Hi {{first_name}},</p>
    
    <p>I know inboxes get overwhelming. Just wanted to circle back one more time.</p>
    
    <p>Is market research or consumer insights something {{company}} is focusing on this quarter?</p>
    
    <p>If so, I'd love to share how we've helped similar companies in {{industry}} achieve better research outcomes.</p>
    
    <p>Either way, no pressure – just let me know.</p>
    
    {{signature}}
</div>
""",
        },
        {
            "name": f"{company_brand.title()} - Breakup",
            "step_type": "follow_up_3",
            "subject": "Closing the loop",
            "body_html": """
<div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
    <p>Hi {{first_name}},</p>
    
    <p>I haven't heard back, so I'm assuming research services aren't a priority for {{company}} right now.</p>
    
    <p>No worries at all – I'll close this loop on my end.</p>
    
    <p>If anything changes or you'd like to revisit this down the road, feel free to reach out. My inbox is always open.</p>
    
    <p>Best of luck with everything!</p>
    
    {{signature}}
</div>
""",
        },
    ]
    
    created_ids = []
    for template in templates:
        existing = renderer.templates_collection.find_one({
            "name": template["name"],
            "company_brand": company_brand
        })
        
        if not existing:
            template_id = renderer.create_template(
                name=template["name"],
                subject=template["subject"],
                body_html=template["body_html"],
                step_type=template["step_type"],
                company_brand=company_brand,
            )
            created_ids.append(template_id)
            logger.info(f"Created default template: {template['name']}")
    
    return created_ids
