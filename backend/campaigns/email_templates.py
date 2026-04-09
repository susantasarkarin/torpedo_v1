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


# ============== GENERIC INDUSTRY TEMPLATES (Template-Only Mode) ==============
# These templates are designed to work without any AI — purely placeholder-based.
# Organized by: industry → seniority → step (initial + 3 follow-ups)

INDUSTRY_SENIORITY_TEMPLATES = {
    # ---- SaaS / Technology ----
    "saas_clevel_initial": {
        "name": "SaaS C-Level Initial",
        "subject": "{{first_name}}, a strategic edge for {{company}}",
        "category": "outreach",
        "industry": "saas",
        "seniority": "c-level",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Running a SaaS company means every operational dollar needs to compound. I'm reaching out because we've helped companies like {{company}} streamline research operations and reduce data costs by 30-40%.</p>
    <p>At the executive level, the ROI conversation matters most — and we have the numbers to back it up across {{industry}} companies of your scale.</p>
    <p>Would a 15-minute call this week make sense to explore if there's a fit?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "industry", "signature"]
    },
    "saas_clevel_followup1": {
        "name": "SaaS C-Level Follow-up 1",
        "subject": "Re: Quick follow-up for {{company}}",
        "category": "follow_up",
        "industry": "saas",
        "seniority": "c-level",
        "step": "followup1",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>I know your inbox is competitive real estate, so I'll keep this brief.</p>
    <p>One of our SaaS clients reduced their market research turnaround from 6 weeks to 10 days while cutting panel costs by 35%. Happy to share the specifics if useful for {{company}}.</p>
    <p>Worth a quick chat?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "saas_clevel_followup2": {
        "name": "SaaS C-Level Follow-up 2",
        "subject": "{{first_name}} — one last thought",
        "category": "follow_up",
        "industry": "saas",
        "seniority": "c-level",
        "step": "followup2",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>I'll keep this to the point — if {{company}} is exploring ways to get faster, higher-quality market insights without scaling headcount, we should talk.</p>
    <p>If timing isn't right, no worries at all. I'll circle back in a few months.</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    "saas_vp_initial": {
        "name": "SaaS VP Initial",
        "subject": "{{first_name}}, improving {{department}} efficiency at {{company}}",
        "category": "outreach",
        "industry": "saas",
        "seniority": "vp",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>I noticed {{company}} is in the {{industry}} space. VPs in your position often tell us their biggest challenge is getting quality research data without blowing the budget.</p>
    <p>We specialize in helping {{industry}} companies optimize their data collection — faster turnaround, better quality controls, and cost efficiency.</p>
    <p>Would you have 15 minutes this week to see if we can help {{company}}'s {{department}} team?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "industry", "department", "signature"]
    },
    "saas_vp_followup1": {
        "name": "SaaS VP Follow-up 1",
        "subject": "Following up: data solutions for {{company}}",
        "category": "follow_up",
        "industry": "saas",
        "seniority": "vp",
        "step": "followup1",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Quick follow-up on my last note. Three things that set us apart for {{industry}} companies:</p>
    <ul>
        <li><strong>Speed:</strong> 50% faster turnaround than industry average</li>
        <li><strong>Quality:</strong> Multi-layered fraud detection and real-time monitoring</li>
        <li><strong>Scale:</strong> Access to 1M+ verified respondents in 50+ countries</li>
    </ul>
    <p>Happy to walk through specifics for {{company}} if helpful.</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "industry", "signature"]
    },

    "saas_director_initial": {
        "name": "SaaS Director Initial",
        "subject": "{{first_name}}, streamlining research at {{company}}",
        "category": "outreach",
        "industry": "saas",
        "seniority": "director",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>I'm reaching out because directors in the {{industry}} space consistently need reliable research partners who can deliver quality data on tight timelines.</p>
    <p>We work with companies like {{company}} to handle end-to-end data collection — from audience sampling to quality assurance — so your team can focus on analysis rather than logistics.</p>
    <p>Would it make sense to connect for a quick call?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "industry", "signature"]
    },
    "saas_director_followup1": {
        "name": "SaaS Director Follow-up 1",
        "subject": "Re: Research support for {{company}}",
        "category": "follow_up",
        "industry": "saas",
        "seniority": "director",
        "step": "followup1",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Wanted to follow up quickly. We recently helped a {{industry}} company complete a 12-country study in 3 weeks — their previous vendor took 8 weeks for the same scope.</p>
    <p>If {{company}} has similar challenges with research timelines or data quality, I'd love to share how we can help.</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "industry", "signature"]
    },

    "saas_manager_initial": {
        "name": "SaaS Manager Initial",
        "subject": "{{first_name}}, thought this might help {{company}}",
        "category": "outreach",
        "industry": "saas",
        "seniority": "manager",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>I know managing day-to-day research operations in {{industry}} can be demanding — vendor coordination, quality checks, timeline pressure.</p>
    <p>We handle all of that end-to-end for companies like {{company}}, so your team gets clean data without the operational overhead.</p>
    <p>Would you be open to a quick intro call to see if we're a fit?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "industry", "signature"]
    },

    # ---- Finance ----
    "finance_clevel_initial": {
        "name": "Finance C-Level Initial",
        "subject": "{{first_name}}, compliance-ready research for {{company}}",
        "category": "outreach",
        "industry": "finance",
        "seniority": "c-level",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>In financial services, data integrity and compliance aren't optional — they're the baseline. That's why companies like {{company}} work with ISO-certified partners who understand regulated environments.</p>
    <p>We provide enterprise-grade research infrastructure with full compliance documentation, audit trails, and GDPR-ready data handling.</p>
    <p>Would it be worth a brief conversation to explore how we can support {{company}}'s research needs?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "finance_clevel_followup1": {
        "name": "Finance C-Level Follow-up 1",
        "subject": "Re: Secure research solutions for {{company}}",
        "category": "follow_up",
        "industry": "finance",
        "seniority": "c-level",
        "step": "followup1",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Quick follow-up. A global financial services firm recently came to us after their previous vendor failed a compliance audit. We helped them rebuild their research infrastructure with full SOC 2 and ISO 27001 compliance in 4 weeks.</p>
    <p>If compliance or data security is a concern for {{company}}, happy to share how we handle it.</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    "finance_vp_initial": {
        "name": "Finance VP Initial",
        "subject": "{{first_name}}, faster insights for {{company}}",
        "category": "outreach",
        "industry": "finance",
        "seniority": "vp",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Financial services teams often struggle with slow research cycles and vendor reliability. At {{company}}, I imagine the pressure to deliver quality insights hasn't gotten any lighter.</p>
    <p>We help finance companies get reliable, compliant research data 50% faster through our global panel and automated quality controls.</p>
    <p>Would 15 minutes this week work to discuss how we can help your team?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    "finance_director_initial": {
        "name": "Finance Director Initial",
        "subject": "{{first_name}}, reliable research partner for {{company}}",
        "category": "outreach",
        "industry": "finance",
        "seniority": "director",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Directors in financial services tell us their top pain point is finding a research partner that's both fast and compliant. We've built our entire operation around solving that.</p>
    <p>For {{company}}, we can offer dedicated project management, real-time dashboards, and full compliance documentation.</p>
    <p>Interested in learning more?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    # ---- Healthcare ----
    "healthcare_clevel_initial": {
        "name": "Healthcare C-Level Initial",
        "subject": "{{first_name}}, research excellence for {{company}}",
        "category": "outreach",
        "industry": "healthcare",
        "seniority": "c-level",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Healthcare research demands precision, compliance, and access to hard-to-reach populations. Leading organizations like {{company}} need partners who understand IRB requirements and can deliver compliant results.</p>
    <p>We specialize in healthcare market research with access to verified HCP panels, patient communities, and payer networks — all with full regulatory compliance.</p>
    <p>Would a brief call make sense to explore if we can support {{company}}'s research objectives?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "healthcare_clevel_followup1": {
        "name": "Healthcare C-Level Follow-up 1",
        "subject": "Re: Healthcare research for {{company}}",
        "category": "follow_up",
        "industry": "healthcare",
        "seniority": "c-level",
        "step": "followup1",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>A pharma company recently came to us needing specialist physician respondents in 8 markets within 2 weeks. We delivered with 98% completion rate and full compliance documentation.</p>
    <p>If {{company}} faces similar challenges finding qualified respondents in regulated markets, I'd be happy to show how we can help.</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    "healthcare_vp_initial": {
        "name": "Healthcare VP Initial",
        "subject": "{{first_name}}, quality HCP panels for {{company}}",
        "category": "outreach",
        "industry": "healthcare",
        "seniority": "vp",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Getting quality data from healthcare professionals is notoriously difficult — low response rates, compliance hurdles, and niche audiences. At {{company}}, I imagine this is a familiar challenge.</p>
    <p>We maintain verified HCP panels across 30+ specialties and can deliver compliant results 40% faster than industry average.</p>
    <p>Would you have 15 minutes to explore if we can help your team?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    # ---- Professional Services ----
    "profservices_clevel_initial": {
        "name": "Professional Services C-Level Initial",
        "subject": "{{first_name}}, scaling research at {{company}}",
        "category": "outreach",
        "industry": "professional_services",
        "seniority": "c-level",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Professional services firms often need to scale research capacity quickly without adding permanent headcount. That's exactly what we help companies like {{company}} achieve.</p>
    <p>Think of us as your extended research team — global reach, certified quality, and the flexibility to ramp up or down based on project needs.</p>
    <p>Would it be worth connecting for a brief conversation?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "profservices_vp_initial": {
        "name": "Professional Services VP Initial",
        "subject": "{{first_name}}, research capacity for {{company}}",
        "category": "outreach",
        "industry": "professional_services",
        "seniority": "vp",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>When client projects demand fast turnarounds and global reach, having a reliable research partner makes all the difference. We work with professional services firms like {{company}} to handle fieldwork, sampling, and quality assurance end-to-end.</p>
    <p>This frees your team to focus on analysis and client delivery rather than vendor management.</p>
    <p>Would a quick call make sense to discuss how we can support your upcoming projects?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    # ---- Manufacturing ----
    "manufacturing_clevel_initial": {
        "name": "Manufacturing C-Level Initial",
        "subject": "{{first_name}}, market intelligence for {{company}}",
        "category": "outreach",
        "industry": "manufacturing",
        "seniority": "c-level",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Manufacturing companies making strategic decisions — new markets, product lines, or supply chain changes — need reliable market intelligence. We help companies like {{company}} gather that intelligence through targeted B2B research across global markets.</p>
    <p>Our niche B2B panels and industry-specific expertise make us the go-to partner for companies in your space.</p>
    <p>Would a brief call make sense to explore if we can add value?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    # ---- Generic (fallback for any industry) ----
    "generic_clevel_initial": {
        "name": "Generic C-Level Initial",
        "subject": "{{first_name}}, research solutions for {{company}}",
        "category": "outreach",
        "industry": "generic",
        "seniority": "c-level",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>I'm reaching out because we help companies like {{company}} make better decisions through high-quality market research and data collection.</p>
    <p>With access to 1M+ verified respondents globally, ISO certification, and AI-powered quality controls, we deliver reliable insights faster than traditional vendors.</p>
    <p>Would you be open to a brief conversation to explore how we can support {{company}}?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "generic_clevel_followup1": {
        "name": "Generic C-Level Follow-up 1",
        "subject": "Re: Follow-up for {{company}}",
        "category": "follow_up",
        "industry": "generic",
        "seniority": "c-level",
        "step": "followup1",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Just following up on my previous note. Happy to share case studies relevant to {{company}}'s industry or jump on a quick call at your convenience.</p>
    <p>If the timing isn't right, no problem — I'll check back in a few months.</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "generic_clevel_followup2": {
        "name": "Generic C-Level Follow-up 2",
        "subject": "{{first_name}} — closing the loop",
        "category": "follow_up",
        "industry": "generic",
        "seniority": "c-level",
        "step": "followup2",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Last note from me for now. If {{company}} ever needs a reliable research partner with global reach and enterprise-grade quality, we're here.</p>
    <p>Wishing you and the team continued success.</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    "generic_vp_initial": {
        "name": "Generic VP Initial",
        "subject": "{{first_name}}, improving research efficiency at {{company}}",
        "category": "outreach",
        "industry": "generic",
        "seniority": "vp",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>I'm reaching out because VPs in your position often need to balance research quality with {{department}} budget constraints. We help companies like {{company}} get better data faster, without the overhead.</p>
    <p>Our clients typically see 30-40% cost reductions and 50% faster turnaround after switching to us.</p>
    <p>Would a brief call this week make sense?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "department", "signature"]
    },
    "generic_vp_followup1": {
        "name": "Generic VP Follow-up 1",
        "subject": "Following up: research solutions for {{company}}",
        "category": "follow_up",
        "industry": "generic",
        "seniority": "vp",
        "step": "followup1",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Quick follow-up — here's what our clients value most:</p>
    <ul>
        <li><strong>Speed:</strong> Fast feasibility checks and project turnaround</li>
        <li><strong>Quality:</strong> Multi-layered quality controls with real-time monitoring</li>
        <li><strong>Flexibility:</strong> Scale up or down based on project needs</li>
    </ul>
    <p>Happy to share specifics for {{company}} if helpful.</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    "generic_director_initial": {
        "name": "Generic Director Initial",
        "subject": "{{first_name}}, a research partner for {{company}}",
        "category": "outreach",
        "industry": "generic",
        "seniority": "director",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Directors managing research operations need partners who deliver on time, on budget, and at quality. That's our core promise to companies like {{company}}.</p>
    <p>We handle the full research lifecycle — sampling, fieldwork, quality assurance — so your team can focus on insights and strategy.</p>
    <p>Would you be interested in a quick intro call?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "generic_director_followup1": {
        "name": "Generic Director Follow-up 1",
        "subject": "Re: Research support for {{company}}",
        "category": "follow_up",
        "industry": "generic",
        "seniority": "director",
        "step": "followup1",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Wanted to share a quick stat: our average project completion rate is 97%, with most projects finishing ahead of schedule.</p>
    <p>If {{company}} has upcoming research needs, I'd be happy to discuss how we can support.</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },

    "generic_manager_initial": {
        "name": "Generic Manager Initial",
        "subject": "{{first_name}}, making research easier at {{company}}",
        "category": "outreach",
        "industry": "generic",
        "seniority": "manager",
        "step": "initial",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Managing research projects day-to-day is no small task — vendor coordination, quality monitoring, deadline pressure. We handle all of that for companies like {{company}}.</p>
    <p>Our dedicated project managers, real-time dashboards, and automated quality checks mean less time on logistics and more time on analysis.</p>
    <p>Would a quick chat be helpful?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "generic_manager_followup1": {
        "name": "Generic Manager Follow-up 1",
        "subject": "Following up: operational support for {{company}}",
        "category": "follow_up",
        "industry": "generic",
        "seniority": "manager",
        "step": "followup1",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Just a quick follow-up. Here's how we make life easier for research managers:</p>
    <ul>
        <li>Dedicated project manager for each study</li>
        <li>Real-time progress dashboards</li>
        <li>Automated quality alerts and fraud detection</li>
    </ul>
    <p>Let me know if you'd like to see a demo.</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
}


# ============== TRIGGER-BASED TEMPLATES ==============
# Templates for specific trigger events (used in template-only mode)

TRIGGER_TEMPLATES = {
    "hiring_initial": {
        "name": "Trigger: Hiring",
        "subject": "{{first_name}}, congrats on the growth at {{company}}",
        "category": "outreach",
        "trigger": "hiring",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>I noticed {{company}} is growing the team — congrats. Scaling often means scaling your research capabilities too.</p>
    <p>We help growing companies build robust research operations without needing to hire a full in-house team. Think of us as your outsourced research department — global reach, certified quality, flexible capacity.</p>
    <p>Would it make sense to connect?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "expansion_initial": {
        "name": "Trigger: Market Expansion",
        "subject": "{{first_name}}, expanding into new markets?",
        "category": "outreach",
        "trigger": "expansion",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Companies expanding into new markets need local insights to make smart decisions. If {{company}} is exploring new geographies, our presence in 50+ countries means we can deliver localized research fast.</p>
    <p>We've helped companies validate new market opportunities in as little as 2 weeks. Happy to share specifics.</p>
    <p>Worth a quick conversation?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "funding_initial": {
        "name": "Trigger: Recent Funding",
        "subject": "{{first_name}}, congratulations on the funding",
        "category": "outreach",
        "trigger": "funding",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>Congrats on {{company}}'s recent funding round. Post-funding, companies often accelerate their go-to-market strategy — and that means needing better market intelligence, faster.</p>
    <p>We help companies turn funding momentum into market insights with rapid B2B and consumer research across 50+ countries.</p>
    <p>Would you be open to a brief chat about how we can support {{company}}'s growth plans?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "signature"]
    },
    "general_initial": {
        "name": "Trigger: General",
        "subject": "{{first_name}}, research solutions for {{company}}",
        "category": "outreach",
        "trigger": "general",
        "body_html": """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1f2937;">
    <p>Hi {{first_name}},</p>
    <p>I'm reaching out because companies in the {{industry}} space often need a reliable research partner for data collection, audience sampling, and quality assurance.</p>
    <p>We've helped hundreds of organizations make data-driven decisions with our global panel, ISO-certified processes, and dedicated project management.</p>
    <p>Would a brief conversation make sense to explore if there's a fit for {{company}}?</p>
    {{signature}}
</div>""",
        "variables": ["first_name", "company", "industry", "signature"]
    },
}


def get_template_only_template(
    industry: str = "generic",
    seniority: str = "vp",
    step: str = "initial",
    trigger: str = None,
    company: str = "surveyfieldwork"
) -> Dict[str, Any]:
    """
    Get the best-matching template for template-only mode.
    
    Matching priority: trigger > industry+seniority > generic+seniority > generic fallback
    
    Args:
        industry: Lead's industry (saas, finance, healthcare, professional_services, manufacturing, generic)
        seniority: Lead's seniority (c-level, vp, director, manager)
        step: Sequence step (initial, followup1, followup2)
        trigger: Optional trigger event (hiring, expansion, funding, general)
        company: Company for signature (surveyfieldwork or cogentixresearch)
    
    Returns:
        Template config dict with signature included
    """
    company_config = get_company_config(company)
    signature = company_config["email_signature"]
    
    # Normalize inputs
    industry = (industry or "generic").lower().replace(" ", "_")
    seniority = (seniority or "vp").lower().replace(" ", "-")
    step = (step or "initial").lower()
    
    # Map common industry names
    industry_map = {
        "technology": "saas", "software": "saas", "saas": "saas", "tech": "saas",
        "finance": "finance", "financial": "finance", "banking": "finance", "fintech": "finance",
        "healthcare": "healthcare", "pharma": "healthcare", "medical": "healthcare", "biotech": "healthcare",
        "professional_services": "profservices", "consulting": "profservices", "legal": "profservices",
        "manufacturing": "manufacturing", "industrial": "manufacturing",
    }
    industry = industry_map.get(industry, industry)
    
    # Map seniority
    seniority_map = {
        "c-level": "clevel", "c_level": "clevel", "clevel": "clevel",
        "ceo": "clevel", "cto": "clevel", "cfo": "clevel", "coo": "clevel",
        "vp": "vp", "vice_president": "vp",
        "director": "director", "head": "director",
        "manager": "manager", "senior": "manager",
    }
    seniority_key = seniority_map.get(seniority, "vp")
    
    # Try trigger template first (for initial step only)
    if trigger and step == "initial":
        trigger_key = f"{trigger.lower()}_initial"
        if trigger_key in TRIGGER_TEMPLATES:
            template = TRIGGER_TEMPLATES[trigger_key].copy()
            if '{{signature}}' in template['body_html']:
                template['body_html_with_signature'] = template['body_html'].replace('{{signature}}', signature)
            return template
    
    # Try exact match: industry_seniority_step
    key = f"{industry}_{seniority_key}_{step}"
    if key in INDUSTRY_SENIORITY_TEMPLATES:
        template = INDUSTRY_SENIORITY_TEMPLATES[key].copy()
        if '{{signature}}' in template['body_html']:
            template['body_html_with_signature'] = template['body_html'].replace('{{signature}}', signature)
        return template
    
    # Fallback: generic_seniority_step
    key = f"generic_{seniority_key}_{step}"
    if key in INDUSTRY_SENIORITY_TEMPLATES:
        template = INDUSTRY_SENIORITY_TEMPLATES[key].copy()
        if '{{signature}}' in template['body_html']:
            template['body_html_with_signature'] = template['body_html'].replace('{{signature}}', signature)
        return template
    
    # Final fallback: generic_vp_initial
    template = INDUSTRY_SENIORITY_TEMPLATES["generic_vp_initial"].copy()
    if '{{signature}}' in template['body_html']:
        template['body_html_with_signature'] = template['body_html'].replace('{{signature}}', signature)
    return template
