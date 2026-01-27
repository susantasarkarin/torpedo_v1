"""
EMAIL TEMPLATES FOR CAMPAIGNS
==============================

Pre-defined email templates for surveyfieldwork and cogentixresearch outreach campaigns.
Templates support personalization variables and include email signatures.
"""

from typing import Dict, List, Any
from .services_config import get_company_config


# ============== TEMPLATE DEFINITIONS ==============

# Survey Fieldwork Templates
SURVEYFIELDWORK_TEMPLATES = {
    "initial_outreach": {
        "name": "Initial Outreach - Survey Fieldwork",
        "subject": "{{first_name}}, Transform Your Research with Quality Data",
        "category": "outreach",
        "body_html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p style="margin-bottom: 15px;">Hi {{first_name}},</p>
    
    <p style="margin-bottom: 15px;">
        I hope this email finds you well. I'm reaching out from <strong>Survey Fieldwork</strong>, 
        a leading provider of market research and data collection services.
    </p>
    
    <p style="margin-bottom: 15px;">
        We specialize in helping organizations like {{company}} gather high-quality insights through:
    </p>
    
    <ul style="margin-bottom: 15px; line-height: 1.8;">
        <li><strong>Global Audience Sampling</strong> - Access to 1M+ verified respondents across 50+ countries</li>
        <li><strong>Survey Programming & Hosting</strong> - Professional survey design with secure infrastructure</li>
        <li><strong>Quality Assurance</strong> - AI-powered fraud detection and real-time monitoring</li>
        <li><strong>Qualitative Research</strong> - Focus groups, IDIs, and community management</li>
    </ul>
    
    <p style="margin-bottom: 15px;">
        With over 15 years of industry experience and ISO 27001 certification, we've helped hundreds 
        of businesses make data-driven decisions with confidence.
    </p>
    
    <p style="margin-bottom: 15px;">
        Would you be interested in a brief conversation to explore how we can support your research needs? 
        I'd be happy to share relevant case studies and discuss custom solutions for {{company}}.
    </p>
    
    <p style="margin-bottom: 15px;">
        Looking forward to connecting with you.
    </p>
    
    {{signature}}
</div>
""",
        "variables": ["first_name", "company", "signature"]
    },
    
    "follow_up_week1": {
        "name": "Follow-up Week 1 - Survey Fieldwork",
        "subject": "Following up: Research solutions for {{company}}",
        "category": "follow_up",
        "body_html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p style="margin-bottom: 15px;">Hi {{first_name}},</p>
    
    <p style="margin-bottom: 15px;">
        I wanted to follow up on my previous email about how <strong>Survey Fieldwork</strong> can 
        support your market research initiatives.
    </p>
    
    <p style="margin-bottom: 15px;">
        I understand you're busy, so I'll keep this brief. Here are three quick highlights that set us apart:
    </p>
    
    <div style="margin-bottom: 15px; padding: 15px; background-color: #f3f4f6; border-left: 4px solid #0058CC;">
        <p style="margin: 5px 0;"><strong>✓ Speed:</strong> Fast turnaround times with real-time data collection</p>
        <p style="margin: 5px 0;"><strong>✓ Quality:</strong> Multi-layered quality controls and fraud prevention</p>
        <p style="margin: 5px 0;"><strong>✓ Scale:</strong> From niche B2B audiences to large consumer panels</p>
    </div>
    
    <p style="margin-bottom: 15px;">
        Many of our clients in {{industry}} have seen significant improvements in their research outcomes 
        after partnering with us.
    </p>
    
    <p style="margin-bottom: 15px;">
        Would next week work for a 15-minute call to discuss your specific needs?
    </p>
    
    {{signature}}
</div>
""",
        "variables": ["first_name", "company", "industry", "signature"]
    },
    
    "follow_up_week2": {
        "name": "Follow-up Week 2 - Survey Fieldwork",
        "subject": "Quick question about {{company}}'s research needs",
        "category": "follow_up",
        "body_html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p style="margin-bottom: 15px;">Hi {{first_name}},</p>
    
    <p style="margin-bottom: 15px;">
        I hope you've had a chance to review my previous emails. I wanted to reach out one more time 
        as I believe <strong>Survey Fieldwork</strong> could be a valuable partner for {{company}}.
    </p>
    
    <p style="margin-bottom: 15px;">
        <strong>Here's a recent success story:</strong>
    </p>
    
    <div style="margin-bottom: 15px; padding: 15px; background-color: #f0f9ff; border-left: 4px solid #0058CC;">
        <p style="margin: 5px 0; font-style: italic;">
            "Survey Fieldwork helped us complete a 12-country B2B study in just 3 weeks. Their quality 
            controls caught issues our previous vendor missed, and the data quality was exceptional."
        </p>
        <p style="margin: 10px 0 0 0; font-size: 13px; color: #6b7280;">
            - Research Director, Global Technology Company
        </p>
    </div>
    
    <p style="margin-bottom: 15px;">
        I'd love to learn more about your current research challenges and share how we can help. 
        Even if you're not looking right now, I'd appreciate the opportunity to connect for future projects.
    </p>
    
    <p style="margin-bottom: 15px;">
        Can we schedule a brief call this week or next?
    </p>
    
    {{signature}}
</div>
""",
        "variables": ["first_name", "company", "signature"]
    },
    
    "follow_up_week3": {
        "name": "Follow-up Week 3 - Survey Fieldwork",
        "subject": "Last follow-up: Resources for {{company}}",
        "category": "follow_up",
        "body_html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p style="margin-bottom: 15px;">Hi {{first_name}},</p>
    
    <p style="margin-bottom: 15px;">
        I understand timing isn't always right, and I don't want to clutter your inbox further. 
        This will be my last follow-up for now.
    </p>
    
    <p style="margin-bottom: 15px;">
        Before I close the loop, I wanted to share some helpful resources that you might find valuable:
    </p>
    
    <ul style="margin-bottom: 15px; line-height: 1.8;">
        <li><a href="https://surveyfieldwork.com/blog" style="color: #0058CC;">Industry insights and best practices</a></li>
        <li><a href="https://surveyfieldwork.com/#audience-sampling" style="color: #0058CC;">Learn about our global panel capabilities</a></li>
        <li><a href="https://surveyfieldwork.com/#book" style="color: #0058CC;">Free consultation booking</a></li>
    </ul>
    
    <p style="margin-bottom: 15px;">
        If your research needs change in the future, please don't hesitate to reach out. 
        We'd be happy to help {{company}} achieve better research outcomes.
    </p>
    
    <p style="margin-bottom: 15px;">
        Wishing you continued success!
    </p>
    
    {{signature}}
</div>
""",
        "variables": ["first_name", "company", "signature"]
    }
}


# Cogentix Research Templates
COGENTIXRESEARCH_TEMPLATES = {
    "initial_outreach": {
        "name": "Initial Outreach - Cogentix Research",
        "subject": "{{first_name}}, Elevate Your Research Strategy",
        "category": "outreach",
        "body_html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p style="margin-bottom: 15px;">Hi {{first_name}},</p>
    
    <p style="margin-bottom: 15px;">
        I hope this message finds you well. I'm reaching out from <strong>Cogentix Research</strong>, 
        a specialized research consulting and technology solutions provider.
    </p>
    
    <p style="margin-bottom: 15px;">
        We help organizations like {{company}} optimize their research operations through:
    </p>
    
    <ul style="margin-bottom: 15px; line-height: 1.8;">
        <li><strong>Panel Management</strong> - Custom panel recruitment and engagement programs</li>
        <li><strong>Data Analytics</strong> - Advanced analytics and interactive visualization</li>
        <li><strong>Technology Solutions</strong> - Custom platforms and research automation</li>
        <li><strong>Research Consulting</strong> - Strategy development and methodology design</li>
    </ul>
    
    <p style="margin-bottom: 15px;">
        Our team of specialists brings deep industry expertise across healthcare, financial services, 
        technology, and more. We're ISO certified and maintain the highest compliance standards.
    </p>
    
    <p style="margin-bottom: 15px;">
        I'd love to learn more about {{company}}'s research objectives and explore how we can 
        add value to your initiatives.
    </p>
    
    <p style="margin-bottom: 15px;">
        Would you be open to a brief introductory call?
    </p>
    
    {{signature}}
</div>
""",
        "variables": ["first_name", "company", "signature"]
    },
    
    "follow_up_week1": {
        "name": "Follow-up Week 1 - Cogentix Research",
        "subject": "Following up: Research consulting for {{company}}",
        "category": "follow_up",
        "body_html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p style="margin-bottom: 15px;">Hi {{first_name}},</p>
    
    <p style="margin-bottom: 15px;">
        I wanted to follow up on my previous email regarding <strong>Cogentix Research</strong>'s 
        specialized services for {{company}}.
    </p>
    
    <p style="margin-bottom: 15px;">
        Here's how we're different from typical research vendors:
    </p>
    
    <div style="margin-bottom: 15px; padding: 15px; background-color: #f0fdf4; border-left: 4px solid #10B981;">
        <p style="margin: 5px 0;"><strong>✓ Consulting First:</strong> We design solutions, not just execute tasks</p>
        <p style="margin: 5px 0;"><strong>✓ Technology Edge:</strong> Proprietary tools and custom platforms</p>
        <p style="margin: 5px 0;"><strong>✓ Industry Expertise:</strong> Specialized knowledge in regulated sectors</p>
    </div>
    
    <p style="margin-bottom: 15px;">
        Many of our clients come to us when they need to solve complex research challenges that 
        require more than standard fieldwork services.
    </p>
    
    <p style="margin-bottom: 15px;">
        Are there any specific research challenges you're currently facing that we could discuss?
    </p>
    
    {{signature}}
</div>
""",
        "variables": ["first_name", "company", "signature"]
    },
    
    "follow_up_week2": {
        "name": "Follow-up Week 2 - Cogentix Research",
        "subject": "Thought this might interest {{company}}",
        "category": "follow_up",
        "body_html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p style="margin-bottom: 15px;">Hi {{first_name}},</p>
    
    <p style="margin-bottom: 15px;">
        I hope you're doing well. I wanted to share a recent project that might resonate with 
        {{company}}'s needs.
    </p>
    
    <div style="margin-bottom: 15px; padding: 15px; background-color: #f0fdf4; border-left: 4px solid #10B981;">
        <p style="margin: 5px 0; font-weight: 600;">Case Study: Healthcare Research Optimization</p>
        <p style="margin: 10px 0 5px 0;">
            We helped a pharmaceutical company reduce their panel management costs by 40% while 
            improving data quality through:
        </p>
        <ul style="margin: 10px 0 5px 20px;">
            <li>Custom panel recruitment strategy</li>
            <li>Automated quality monitoring</li>
            <li>Real-time analytics dashboard</li>
        </ul>
        <p style="margin: 10px 0 0 0; font-size: 13px; color: #6b7280;">
            Project completed in 8 weeks with full compliance documentation.
        </p>
    </div>
    
    <p style="margin-bottom: 15px;">
        If you're exploring ways to optimize your research operations or facing similar challenges, 
        I'd be happy to share more details and discuss how we could help {{company}}.
    </p>
    
    <p style="margin-bottom: 15px;">
        Do you have 20 minutes for a call this week?
    </p>
    
    {{signature}}
</div>
""",
        "variables": ["first_name", "company", "signature"]
    },
    
    "follow_up_week3": {
        "name": "Follow-up Week 3 - Cogentix Research",
        "subject": "Final note: Resources for {{company}}",
        "category": "follow_up",
        "body_html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p style="margin-bottom: 15px;">Hi {{first_name}},</p>
    
    <p style="margin-bottom: 15px;">
        I appreciate your time and don't want to fill your inbox unnecessarily. 
        This will be my final outreach for now.
    </p>
    
    <p style="margin-bottom: 15px;">
        Before signing off, I wanted to ensure you have access to resources that might be helpful:
    </p>
    
    <ul style="margin-bottom: 15px; line-height: 1.8;">
        <li><strong>Free Consultation:</strong> 30-minute research strategy assessment</li>
        <li><strong>Compliance Guide:</strong> Latest GDPR and data privacy best practices</li>
        <li><strong>ROI Calculator:</strong> Estimate potential savings with optimized research ops</li>
    </ul>
    
    <p style="margin-bottom: 15px;">
        If your situation changes or you'd like to explore partnership opportunities in the future, 
        please feel free to reach out. We're always here to help {{company}} achieve research excellence.
    </p>
    
    <p style="margin-bottom: 15px;">
        All the best with your initiatives!
    </p>
    
    {{signature}}
</div>
""",
        "variables": ["first_name", "company", "signature"]
    }
}


# ============== HELPER FUNCTIONS ==============

def get_template_config(company: str, template_name: str) -> Dict[str, Any]:
    """
    Get email template configuration.
    
    Args:
        company: Company identifier ('surveyfieldwork' or 'cogentixresearch')
        template_name: Template name (e.g., 'initial_outreach', 'follow_up_week1')
    
    Returns:
        Template configuration dictionary with signature included
    """
    company_lower = company.lower()
    
    # Get company config for signature
    company_config = get_company_config(company)
    signature = company_config["email_signature"]
    
    # Get template
    if 'surveyfield' in company_lower:
        templates = SURVEYFIELDWORK_TEMPLATES
    elif 'cogentix' in company_lower:
        templates = COGENTIXRESEARCH_TEMPLATES
    else:
        raise ValueError(f"Unknown company: {company}")
    
    if template_name not in templates:
        raise ValueError(f"Template {template_name} not found for {company}")
    
    template = templates[template_name].copy()
    
    # Add signature to body if {{signature}} placeholder exists
    if '{{signature}}' in template['body_html']:
        template['body_html_with_signature'] = template['body_html'].replace('{{signature}}', signature)
    else:
        template['body_html_with_signature'] = template['body_html'] + signature
    
    return template


def list_templates(company: str = None) -> Dict[str, List[str]]:
    """
    List available templates.
    
    Args:
        company: Optional company filter
    
    Returns:
        Dictionary with company names as keys and template names as values
    """
    if company:
        company_lower = company.lower()
        if 'surveyfield' in company_lower:
            return {"surveyfieldwork": list(SURVEYFIELDWORK_TEMPLATES.keys())}
        elif 'cogentix' in company_lower:
            return {"cogentixresearch": list(COGENTIXRESEARCH_TEMPLATES.keys())}
        else:
            raise ValueError(f"Unknown company: {company}")
    
    return {
        "surveyfieldwork": list(SURVEYFIELDWORK_TEMPLATES.keys()),
        "cogentixresearch": list(COGENTIXRESEARCH_TEMPLATES.keys())
    }


def render_template(template_config: Dict[str, Any], variables: Dict[str, Any]) -> Dict[str, str]:
    """
    Render template with variables.
    
    Args:
        template_config: Template configuration from get_template_config()
        variables: Dictionary of variable values (e.g., {"first_name": "John", "company": "Acme"})
    
    Returns:
        Dictionary with rendered subject and body_html
    """
    subject = template_config["subject"]
    body_html = template_config.get("body_html_with_signature", template_config["body_html"])
    
    # Replace variables
    for key, value in variables.items():
        if key == "signature":
            continue  # Signature already included
        placeholder = "{{" + key + "}}"
        subject = subject.replace(placeholder, str(value))
        body_html = body_html.replace(placeholder, str(value))
    
    return {
        "subject": subject,
        "body_html": body_html
    }
