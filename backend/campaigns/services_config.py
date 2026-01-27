"""
SERVICES CONFIGURATION
======================

Defines services offered by surveyfieldwork and cogentixresearch.
This configuration is used for personalized email campaigns.
"""

from typing import Dict, List, Any


# ============== SURVEY FIELDWORK SERVICES ==============

SURVEYFIELDWORK_SERVICES = {
    "company_name": "Survey Fieldwork",
    "domain": "surveyfieldwork.com",
    "sender_email": "indira@surveyfieldwork.com",
    "sender_name": "Indira",
    "email_signature": """
<div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; font-family: Arial, sans-serif;">
    <p style="margin: 0; font-size: 14px; color: #1f2937; font-weight: 600;">Best regards,</p>
    <p style="margin: 5px 0 0 0; font-size: 14px; color: #1f2937; font-weight: 600;">Indira</p>
    <p style="margin: 5px 0; font-size: 13px; color: #6b7280;">Business Development Manager</p>
    <p style="margin: 0; font-size: 13px; color: #0058CC; font-weight: 600;">Survey Fieldwork</p>
    <p style="margin: 5px 0; font-size: 12px; color: #6b7280;">A Division of Cogentix Research Pvt Ltd</p>
    <div style="margin-top: 10px;">
        <p style="margin: 3px 0; font-size: 12px; color: #6b7280;">📧 indira@surveyfieldwork.com</p>
        <p style="margin: 3px 0; font-size: 12px; color: #6b7280;">🌐 <a href="https://surveyfieldwork.com" style="color: #0058CC; text-decoration: none;">surveyfieldwork.com</a></p>
        <p style="margin: 3px 0; font-size: 12px; color: #6b7280;">📍 Kolkata, West Bengal, India</p>
    </div>
</div>
""",
    "services": [
        {
            "id": "audience_sampling",
            "name": "Audience Sampling",
            "short_description": "Access diverse, targeted respondent panels across B2B and B2C segments worldwide",
            "description": "Our audience sampling service provides access to a global panel of over 1 million verified respondents across 50+ countries. We offer quality-assured data collection with advanced screening and targeting capabilities to ensure you reach the right audience for your research needs.",
            "features": [
                "Global Panel Access - 50+ countries",
                "Quality Screening & Verification",
                "Niche Targeting (B2B & B2C)",
                "Real-time Quality Monitoring",
                "Multi-demographic Segmentation",
                "Fraud Detection & Prevention"
            ],
            "use_cases": [
                "Market research surveys",
                "Product testing",
                "Brand awareness studies",
                "Customer satisfaction research",
                "Ad testing"
            ]
        },
        {
            "id": "enterprise_solutions",
            "name": "Enterprise Solutions",
            "short_description": "Custom research solutions for large organizations with complex data collection needs",
            "description": "Tailored enterprise-grade research solutions designed for organizations with complex, multi-market data collection requirements. We provide dedicated support, custom panel development, and comprehensive project management for large-scale research initiatives.",
            "features": [
                "Custom Panel Development",
                "Multi-Market Studies",
                "Dedicated Account Manager",
                "Priority Support 24/7",
                "Advanced Analytics & Reporting",
                "White-label Solutions",
                "API Integration"
            ],
            "use_cases": [
                "Large-scale market research",
                "Multi-country studies",
                "Longitudinal tracking studies",
                "Custom panel communities",
                "Enterprise feedback programs"
            ]
        },
        {
            "id": "security_measures",
            "name": "Security Measures",
            "short_description": "Industry-leading security protocols for data integrity and fraud prevention",
            "description": "Comprehensive security infrastructure ensuring data integrity, respondent verification, and fraud prevention across all surveys. Our multi-layered approach combines advanced technology with human oversight to maintain the highest quality standards.",
            "features": [
                "AI-Powered Fraud Detection",
                "Multi-factor Respondent Verification",
                "Data Encryption (End-to-End)",
                "GDPR & CCPA Compliant",
                "ISO 27001 Certified",
                "Regular Security Audits",
                "Real-time Quality Checks"
            ],
            "use_cases": [
                "High-stakes research projects",
                "Sensitive data collection",
                "Regulated industry research",
                "Clinical trials recruitment",
                "Financial services research"
            ]
        },
        {
            "id": "survey_programming",
            "name": "Survey Programming & Hosting",
            "short_description": "Expert survey design and programming with secure hosting infrastructure",
            "description": "Professional survey programming and hosting services featuring custom logic, advanced routing, multimedia integration, and real-time data collection. Our platform supports all major survey formats and devices for seamless respondent experience.",
            "features": [
                "Custom Survey Programming",
                "Multi-device Compatibility",
                "Advanced Logic & Routing",
                "Multimedia Support",
                "Real-time Data Dashboards",
                "Secure Cloud Hosting",
                "Multi-language Support"
            ],
            "use_cases": [
                "Complex questionnaire design",
                "Multi-wave studies",
                "MaxDiff and Conjoint analysis",
                "Mobile-first surveys",
                "Video/audio integration"
            ]
        },
        {
            "id": "qualitative_fieldwork",
            "name": "Qualitative Fieldwork",
            "short_description": "In-depth qualitative research including focus groups and IDIs",
            "description": "Comprehensive qualitative research services including moderated focus groups, in-depth interviews, online communities, and ethnographic studies. Our experienced moderators extract deep insights that drive strategic decision-making.",
            "features": [
                "Focus Group Moderation",
                "In-Depth Interviews (IDIs)",
                "Online Community Management",
                "Ethnographic Studies",
                "Expert Moderators",
                "Multilingual Capabilities",
                "Video Recording & Transcription"
            ],
            "use_cases": [
                "Concept testing",
                "Brand perception studies",
                "Customer journey mapping",
                "Product development research",
                "User experience research"
            ]
        },
        {
            "id": "market_research",
            "name": "Market Research & Insights",
            "short_description": "Comprehensive market analysis and strategic insights",
            "description": "End-to-end market research and insights services combining quantitative and qualitative methodologies. We help businesses understand market dynamics, consumer behavior, and competitive landscapes to drive informed decision-making.",
            "features": [
                "Market Analysis & Sizing",
                "Consumer Insights & Segmentation",
                "Trend Forecasting",
                "Competitive Intelligence",
                "Brand Tracking Studies",
                "Customer Satisfaction Research",
                "Product Testing & Optimization"
            ],
            "use_cases": [
                "Market entry strategies",
                "Product launch planning",
                "Brand positioning",
                "Customer segmentation",
                "Competitive benchmarking"
            ]
        }
    ]
}


# ============== COGENTIX RESEARCH SERVICES ==============

COGENTIXRESEARCH_SERVICES = {
    "company_name": "Cogentix Research",
    "domain": "cogentixresearch.com",
    "sender_email": "meera@cogentixresearch.com",
    "sender_name": "Meera",
    "email_signature": """
<div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; font-family: Arial, sans-serif;">
    <p style="margin: 0; font-size: 14px; color: #1f2937; font-weight: 600;">Best regards,</p>
    <p style="margin: 5px 0 0 0; font-size: 14px; color: #1f2937; font-weight: 600;">Meera</p>
    <p style="margin: 5px 0; font-size: 13px; color: #6b7280;">Senior Research Consultant</p>
    <p style="margin: 0; font-size: 13px; color: #10B981; font-weight: 600;">Cogentix Research Pvt Ltd</p>
    <div style="margin-top: 10px;">
        <p style="margin: 3px 0; font-size: 12px; color: #6b7280;">📧 meera@cogentixresearch.com</p>
        <p style="margin: 3px 0; font-size: 12px; color: #6b7280;">🌐 <a href="https://cogentixresearch.com" style="color: #10B981; text-decoration: none;">cogentixresearch.com</a></p>
        <p style="margin: 3px 0; font-size: 12px; color: #6b7280;">📍 Kolkata, West Bengal, India</p>
    </div>
</div>
""",
    "services": [
        {
            "id": "panel_management",
            "name": "Panel Management & Recruitment",
            "short_description": "Comprehensive panel management and recruitment services",
            "description": "Full-service panel management including recruitment, profiling, engagement, and quality maintenance. We build and manage custom panels tailored to your specific research requirements with ongoing quality assurance.",
            "features": [
                "Custom Panel Recruitment",
                "Panel Profiling & Segmentation",
                "Engagement & Retention Programs",
                "Quality Assurance & Validation",
                "Panel Health Monitoring",
                "Incentive Management",
                "Multi-channel Recruitment"
            ],
            "use_cases": [
                "Building proprietary panels",
                "Niche audience recruitment",
                "Panel refresh & expansion",
                "Community panel management",
                "B2B panel development"
            ]
        },
        {
            "id": "data_analytics",
            "name": "Data Analytics & Visualization",
            "short_description": "Advanced analytics and interactive data visualization",
            "description": "Transform raw data into actionable insights with our advanced analytics and visualization services. We use cutting-edge tools and techniques to uncover patterns, trends, and opportunities in your research data.",
            "features": [
                "Advanced Statistical Analysis",
                "Predictive Modeling",
                "Interactive Dashboards",
                "Custom Reporting",
                "Data Mining & Pattern Recognition",
                "Machine Learning Applications",
                "Real-time Analytics"
            ],
            "use_cases": [
                "Complex data analysis",
                "Predictive analytics",
                "Customer behavior modeling",
                "Market trend analysis",
                "Performance tracking"
            ]
        },
        {
            "id": "consulting_services",
            "name": "Research Consulting Services",
            "short_description": "Strategic research consulting and methodology design",
            "description": "Expert research consulting services helping organizations design, implement, and optimize their research strategies. Our consultants bring deep industry expertise to solve complex research challenges.",
            "features": [
                "Research Strategy Development",
                "Methodology Design",
                "Questionnaire Development",
                "Sample Design & Planning",
                "Research Training Programs",
                "Quality Audits",
                "Best Practices Implementation"
            ],
            "use_cases": [
                "Research program setup",
                "Methodology optimization",
                "Team training & development",
                "Quality improvement initiatives",
                "Research governance"
            ]
        },
        {
            "id": "technology_solutions",
            "name": "Research Technology Solutions",
            "short_description": "Custom technology platforms for research operations",
            "description": "Innovative technology solutions including custom survey platforms, panel management systems, and research automation tools. We build scalable, secure technology infrastructure for modern research operations.",
            "features": [
                "Custom Survey Platforms",
                "Panel Management Systems",
                "API Development & Integration",
                "Mobile Research Apps",
                "Automation Tools",
                "Cloud Infrastructure",
                "White-label Solutions"
            ],
            "use_cases": [
                "Platform development",
                "System integration",
                "Research automation",
                "Mobile data collection",
                "Custom tool development"
            ]
        },
        {
            "id": "compliance_quality",
            "name": "Compliance & Quality Assurance",
            "short_description": "Ensuring research compliance and maintaining quality standards",
            "description": "Comprehensive compliance and quality assurance services ensuring your research meets all regulatory requirements and industry standards. We maintain certifications and implement best practices across all operations.",
            "features": [
                "GDPR & CCPA Compliance",
                "ISO Certifications",
                "ESOMAR Standards",
                "Quality Management Systems",
                "Data Privacy Audits",
                "Compliance Training",
                "Regular Quality Reviews"
            ],
            "use_cases": [
                "Compliance audits",
                "Quality certification",
                "Privacy compliance",
                "Industry standards implementation",
                "Risk management"
            ]
        },
        {
            "id": "specialized_research",
            "name": "Specialized Research Services",
            "short_description": "Industry-specific and methodology-specific research expertise",
            "description": "Specialized research services across various industries and methodologies including healthcare, financial services, technology, and more. Our experts understand sector-specific challenges and regulatory requirements.",
            "features": [
                "Healthcare Research",
                "Financial Services Research",
                "Technology & IT Research",
                "Pharma & Clinical Research",
                "Automotive Research",
                "Retail & E-commerce Research",
                "Telecommunications Research"
            ],
            "use_cases": [
                "Industry-specific studies",
                "Regulatory compliance research",
                "Specialized methodologies",
                "Professional audiences",
                "Vertical expertise projects"
            ]
        }
    ]
}


# ============== HELPER FUNCTIONS ==============

def get_company_config(company: str) -> Dict[str, Any]:
    """
    Get company configuration by name.
    
    Args:
        company: Company identifier ('surveyfieldwork' or 'cogentixresearch')
    
    Returns:
        Company configuration dictionary
    """
    company_lower = company.lower()
    
    if 'surveyfield' in company_lower or company_lower == 'surveyfieldwork':
        return SURVEYFIELDWORK_SERVICES
    elif 'cogentix' in company_lower or company_lower == 'cogentixresearch':
        return COGENTIXRESEARCH_SERVICES
    else:
        raise ValueError(f"Unknown company: {company}. Use 'surveyfieldwork' or 'cogentixresearch'")


def get_service_by_id(company: str, service_id: str) -> Dict[str, Any]:
    """
    Get specific service details.
    
    Args:
        company: Company identifier
        service_id: Service identifier
    
    Returns:
        Service configuration dictionary
    """
    config = get_company_config(company)
    
    for service in config["services"]:
        if service["id"] == service_id:
            return service
    
    raise ValueError(f"Service {service_id} not found for {company}")


def list_all_services() -> Dict[str, List[Dict[str, str]]]:
    """
    List all services from both companies.
    
    Returns:
        Dictionary with company names as keys and list of services as values
    """
    return {
        "surveyfieldwork": [
            {"id": s["id"], "name": s["name"], "description": s["short_description"]}
            for s in SURVEYFIELDWORK_SERVICES["services"]
        ],
        "cogentixresearch": [
            {"id": s["id"], "name": s["name"], "description": s["short_description"]}
            for s in COGENTIXRESEARCH_SERVICES["services"]
        ]
    }
