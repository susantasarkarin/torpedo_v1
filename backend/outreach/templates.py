"""
DEFAULT EMAIL TEMPLATES
=======================

Pre-built email templates for cold outreach and re-engagement campaigns.
Supports all personalization tokens and multiple sequences.
"""

from typing import Dict, List
from pymongo.database import Database
from .models import EmailTemplate, PersonalizationLevel


# ============== COLD OUTREACH TEMPLATES ==============

COLD_OUTREACH_TEMPLATES = {
    "email_1_introduction": {
        "name": "Email 1 - Introduction (Day 1)",
        "description": "Soft introduction with one clear pain point and outcome",
        "subject": "{{first_name}}, quick question about {{company}}",
        "body_html": """
<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <p>Hi {{first_name}},</p>
    
    <p>I noticed {{company}} is in the {{industry}} space, and wanted to reach out with a quick question.</p>
    
    <p>Most {{title}}s I work with struggle with {{pain_point}}. Is this something you're experiencing at {{company}}?</p>
    
    <p>We've helped similar organizations achieve [specific outcome] – happy to share more if it's relevant.</p>
    
    <p>Worth a quick 10-minute call?</p>
    
    <p>Best,<br>
    [Your Name]</p>
</div>
""",
        "category": "cold_outreach",
        "step_type": "introduction",
        "required_tokens": ["first_name", "company", "industry", "title", "pain_point"],
        "personalization_level": PersonalizationLevel.ROLE_BASED
    },
    
    "email_2_value_followup": {
        "name": "Email 2 - Value Follow-Up (Day 4)",
        "description": "Different angle with use case and social proof",
        "subject": "Re: Quick question about {{company}}",
        "body_html": """
<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <p>Hi {{first_name}},</p>
    
    <p>Following up on my previous email about {{pain_point}}.</p>
    
    <p>I wanted to share a quick example: {{use_case}}</p>
    
    <p><strong>Quick highlights:</strong></p>
    <ul>
        <li>✓ Reduced time spent on [task] by 40%</li>
        <li>✓ Improved [metric] by 25%</li>
        <li>✓ Simple implementation (< 2 weeks)</li>
    </ul>
    
    <p>Would this be valuable for {{company}}?</p>
    
    <p>Best,<br>
    [Your Name]</p>
</div>
""",
        "category": "cold_outreach",
        "step_type": "value_followup",
        "required_tokens": ["first_name", "company", "pain_point", "use_case"],
        "personalization_level": PersonalizationLevel.ROLE_BASED
    },
    
    "email_3_direct": {
        "name": "Email 3 - Direct / Break-Up (Day 7)",
        "description": "Concise with simple yes/no CTA",
        "subject": "Last check-in, {{first_name}}",
        "body_html": """
<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <p>Hi {{first_name}},</p>
    
    <p>I know you're busy – keeping this super brief.</p>
    
    <p>Is {{value_proposition}} something that's on your radar for {{company}} this quarter?</p>
    
    <p>Yes / No?</p>
    
    <p>Thanks,<br>
    [Your Name]</p>
</div>
""",
        "category": "cold_outreach",
        "step_type": "direct",
        "required_tokens": ["first_name", "value_proposition", "company"],
        "personalization_level": PersonalizationLevel.ROLE_BASED
    },
    
    "email_4_final_touch": {
        "name": "Email 4 - Final Touch (Day 12)",
        "description": "Polite close-the-loop message",
        "subject": "Closing the loop",
        "body_html": """
<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <p>Hi {{first_name}},</p>
    
    <p>I haven't heard back, so I'm assuming {{value_proposition}} isn't a priority for {{company}} right now.</p>
    
    <p>No worries at all – I'll close this loop on my end.</p>
    
    <p>If anything changes or you'd like to revisit this down the road, feel free to reach out. My door's always open.</p>
    
    <p>Best of luck with everything at {{company}}!</p>
    
    <p>Cheers,<br>
    [Your Name]</p>
</div>
""",
        "category": "cold_outreach",
        "step_type": "final_touch",
        "required_tokens": ["first_name", "value_proposition", "company"],
        "personalization_level": PersonalizationLevel.ROLE_BASED
    }
}


# ============== RE-ENGAGEMENT TEMPLATES ==============

REENGAGEMENT_TEMPLATES = {
    "soft_drip_educational": {
        "name": "Re-engagement - Soft Drip (Educational)",
        "description": "Educational content with soft/no CTA",
        "subject": "Thought this might interest you, {{first_name}}",
        "body_html": """
<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <p>Hi {{first_name}},</p>
    
    <p>I came across an interesting insight about {{industry}} that I thought you might find valuable.</p>
    
    <p><strong>[Share industry insight, trend, or case study]</strong></p>
    
    <p>We've been seeing this trend across several {{department}} teams – especially in companies similar to {{company}}.</p>
    
    <p>Thought it might be relevant for you!</p>
    
    <p>Best,<br>
    [Your Name]</p>
</div>
""",
        "category": "reengagement",
        "step_type": "soft_drip",
        "required_tokens": ["first_name", "industry", "department", "company"],
        "personalization_level": PersonalizationLevel.ROLE_BASED
    },
    
    "trigger_job_change": {
        "name": "Re-engagement - Job Change Trigger",
        "description": "Congratulations on new role",
        "subject": "Congrats on the new role, {{first_name}}!",
        "body_html": """
<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <p>Hi {{first_name}},</p>
    
    <p>Congratulations on your new role as {{title}} at {{company}}!</p>
    
    <p>I reached out a few months ago about {{value_proposition}}, and with your new position, thought it might be worth reconnecting.</p>
    
    <p>Many {{title}}s I work with prioritize [specific initiative] in their first 90 days.</p>
    
    <p>Would a quick conversation be helpful as you're settling in?</p>
    
    <p>Best,<br>
    [Your Name]</p>
</div>
""",
        "category": "reengagement",
        "step_type": "trigger_job_change",
        "required_tokens": ["first_name", "title", "company", "value_proposition"],
        "personalization_level": PersonalizationLevel.ROLE_BASED
    },
    
    "reset_outreach": {
        "name": "Re-engagement - Reset Outreach",
        "description": "Fresh angle, new approach",
        "subject": "New approach for {{company}}",
        "body_html": """
<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <p>Hi {{first_name}},</p>
    
    <p>I reached out a while back but wanted to try a different angle.</p>
    
    <p>We just launched a new solution specifically for {{industry}} companies dealing with {{pain_point}}.</p>
    
    <p>It's designed for teams like yours at {{company}} – here's what makes it different:</p>
    
    <ul>
        <li>[Key differentiator 1]</li>
        <li>[Key differentiator 2]</li>
        <li>[Key differentiator 3]</li>
    </ul>
    
    <p>Open to a fresh conversation?</p>
    
    <p>Best,<br>
    [Your Name]</p>
</div>
""",
        "category": "reengagement",
        "step_type": "reset_outreach",
        "required_tokens": ["first_name", "company", "industry", "pain_point"],
        "personalization_level": PersonalizationLevel.ROLE_BASED
    }
}


# ============== BEHAVIOR-BASED VARIANTS ==============

BEHAVIOR_VARIANTS = {
    "opened_no_reply": {
        "subject_variants": [
            "Quick follow-up for {{company}}",
            "{{first_name}} - following up",
            "Re: {{company}}"
        ],
        "cta_variants": [
            "Worth a 10-minute call?",
            "Can I share more details?",
            "Should we schedule a quick chat?"
        ]
    },
    "not_opened": {
        "subject_variants": [
            "{{company}} + [Your Solution]",
            "Question about {{company}}",
            "{{first_name}}, are you the right person?"
        ]
    },
    "clicked_no_reply": {
        "subject_variants": [
            "Saw you checked out the link, {{first_name}}",
            "Following up on {{company}}"
        ],
        "cta_variants": [
            "Would a demo be helpful?",
            "Should we walk through this together?",
            "Want to discuss the details?"
        ]
    }
}


def seed_templates(db: Database) -> Dict[str, str]:
    """
    Seed database with default email templates.
    
    Args:
        db: MongoDB database
    
    Returns:
        Dictionary mapping template keys to IDs
    """
    templates_collection = db["outreach_templates"]
    template_ids = {}
    
    # Seed cold outreach templates
    for key, template_data in COLD_OUTREACH_TEMPLATES.items():
        # Check if template exists
        existing = templates_collection.find_one({"name": template_data["name"]})
        
        if existing:
            template_ids[key] = str(existing["_id"])
        else:
            # Create template
            template = EmailTemplate(
                name=template_data["name"],
                description=template_data.get("description"),
                subject=template_data["subject"],
                body_html=template_data["body_html"],
                category=template_data["category"],
                step_type=template_data.get("step_type"),
                required_tokens=template_data["required_tokens"],
                personalization_level=template_data["personalization_level"]
            )
            
            result = templates_collection.insert_one(template.model_dump())
            template_ids[key] = str(result.inserted_id)
    
    # Seed re-engagement templates
    for key, template_data in REENGAGEMENT_TEMPLATES.items():
        existing = templates_collection.find_one({"name": template_data["name"]})
        
        if existing:
            template_ids[key] = str(existing["_id"])
        else:
            template = EmailTemplate(
                name=template_data["name"],
                description=template_data.get("description"),
                subject=template_data["subject"],
                body_html=template_data["body_html"],
                category=template_data["category"],
                step_type=template_data.get("step_type"),
                required_tokens=template_data["required_tokens"],
                personalization_level=template_data["personalization_level"]
            )
            
            result = templates_collection.insert_one(template.model_dump())
            template_ids[key] = str(result.inserted_id)
    
    return template_ids


def get_template_variants(behavior: str) -> Dict[str, List[str]]:
    """
    Get template variants for specific behavior.
    
    Args:
        behavior: Behavior type (opened_no_reply, not_opened, clicked_no_reply)
    
    Returns:
        Dictionary with variants
    """
    return BEHAVIOR_VARIANTS.get(behavior, {})
