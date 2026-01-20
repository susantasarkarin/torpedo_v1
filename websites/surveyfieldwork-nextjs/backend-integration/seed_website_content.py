"""
Website Content Seeding Script
==============================

This script seeds the MongoDB database with the original WordPress content
so it can be managed via the CRM Marketing module.

Run this once after setting up the marketing router:
    python seed_website_content.py

Prerequisites:
    - MongoDB running
    - marketing.py router installed
    - MONGODB_URI environment variable set
"""

import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os

# MongoDB connection
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = "marketing_db"

# ============================================================================
# WEBSITE CONFIGURATION
# ============================================================================

WEBSITE_CONFIG = {
    "name": "Survey Fieldwork",
    "domain": "surveyfieldwork.com",
    "description": "Market Research & Data Collection Services",
    "logo": "/assets/images/logo.png",
    "favicon": "/favicon.ico",
    "status": "active",
    "colors": {
        "primary": "#0058CC",
        "secondary": "#1E293B",
        "accent": "#00A67E"
    },
    "fonts": {
        "heading": "Montserrat",
        "body": "Open Sans"
    },
    "default_seo": {
        "title": "Survey Fieldwork | Market Research & Data Collection Services",
        "description": "Survey Fieldwork offers comprehensive market research services including audience sampling, survey programming, qualitative fieldwork, and enterprise solutions. Trusted by 500+ clients worldwide.",
        "keywords": ["market research", "survey fieldwork", "audience sampling", "data collection"],
        "og_image": "/assets/images/og-home.jpg"
    },
    "gtm_id": "GTM-K5BX7PV2",
    "ga_id": "G-HFZMW72Z32",
    "linkedin_partner_id": "7281020",
    "custom_head": """
<!-- LinkedIn Insight Tag -->
<script type="text/javascript">
_linkedin_partner_id = "7281020";
window._linkedin_data_partner_ids = window._linkedin_data_partner_ids || [];
window._linkedin_data_partner_ids.push(_linkedin_partner_id);
</script>
""",
    "custom_body": "",
    "created_at": datetime.utcnow(),
    "updated_at": datetime.utcnow()
}

# ============================================================================
# NAVIGATION
# ============================================================================

HEADER_NAV = [
    {"id": "nav-1", "label": "Home", "link": "/", "type": "link", "order": 1},
    {"id": "nav-2", "label": "About Us", "link": "/#about", "type": "anchor", "order": 2},
    {
        "id": "nav-3", 
        "label": "Solutions", 
        "link": None, 
        "type": "dropdown", 
        "order": 3,
        "children": [
            {
                "id": "nav-3-1",
                "label": "Online Sampling",
                "link": None,
                "type": "dropdown",
                "children": [
                    {"id": "nav-3-1-1", "label": "Audience Sampling", "link": "/#audience-sampling", "type": "anchor"},
                    {"id": "nav-3-1-2", "label": "Enterprise Solutions", "link": "/#enterprise-solutions", "type": "anchor"},
                    {"id": "nav-3-1-3", "label": "Security Measures", "link": "/#security-measures", "type": "anchor"},
                ]
            },
            {"id": "nav-3-2", "label": "Survey Programming & Hosting", "link": "/#survey", "type": "anchor"},
            {"id": "nav-3-3", "label": "Qualitative Fieldwork", "link": "/#fieldwork", "type": "anchor"},
            {"id": "nav-3-4", "label": "Market Research & Insights", "link": "/#market-research", "type": "anchor"},
        ]
    },
    {"id": "nav-4", "label": "Blogs", "link": "/blog", "type": "link", "order": 4},
    {"id": "nav-5", "label": "Join Panel", "link": "https://panel.surveyfieldwork.com", "type": "link", "order": 5},
    {"id": "nav-6", "label": "Book Free Consultation", "link": "/#book", "type": "anchor", "order": 6},
]

FOOTER_NAV = [
    {
        "id": "footer-solutions",
        "label": "Solutions",
        "type": "group",
        "children": [
            {"id": "f-1", "label": "Audience Sampling", "link": "/#audience-sampling", "type": "anchor"},
            {"id": "f-2", "label": "Enterprise Solutions", "link": "/#enterprise-solutions", "type": "anchor"},
            {"id": "f-3", "label": "Security Measures", "link": "/#security-measures", "type": "anchor"},
            {"id": "f-4", "label": "Survey Programming", "link": "/#survey", "type": "anchor"},
            {"id": "f-5", "label": "Qualitative Fieldwork", "link": "/#fieldwork", "type": "anchor"},
            {"id": "f-6", "label": "Market Research", "link": "/#market-research", "type": "anchor"},
        ]
    },
    {
        "id": "footer-company",
        "label": "Company",
        "type": "group",
        "children": [
            {"id": "f-7", "label": "About Us", "link": "/#about", "type": "anchor"},
            {"id": "f-8", "label": "Careers", "link": "/careers", "type": "link"},
            {"id": "f-9", "label": "Blog", "link": "/blog", "type": "link"},
            {"id": "f-10", "label": "Contact", "link": "/#book", "type": "anchor"},
        ]
    },
    {
        "id": "footer-legal",
        "label": "Legal",
        "type": "group",
        "children": [
            {"id": "f-11", "label": "Privacy Policy", "link": "/privacy-policy", "type": "link"},
            {"id": "f-12", "label": "Terms of Service", "link": "/terms", "type": "link"},
            {"id": "f-13", "label": "GDPR Compliance", "link": "/gdpr", "type": "link"},
        ]
    }
]

# ============================================================================
# HOME PAGE CONTENT
# ============================================================================

HOME_PAGE = {
    "slug": "home",
    "title": "Home",
    "status": "published",
    "is_homepage": True,
    "sections": [
        {
            "id": "hero",
            "type": "hero",
            "order": 1,
            "content": {
                "badges": ["Trusted", "Experienced", "Professional"],
                "headline": "Where Data Meets Strategy",
                "subheadline": "Partner with us to gain a competitive edge, seize opportunities, and drive success in your industry. Experience the power of market research and unlock your business's full potential today.",
                "primary_cta": {"label": "Book Free Consultation", "href": "/#book"},
                "secondary_cta": {"label": "Learn More", "href": "/#about"},
                "stats": [
                    {"value": "50+", "label": "Countries"},
                    {"value": "1M+", "label": "Respondents"},
                    {"value": "500+", "label": "Projects"}
                ],
                "background_image": None
            }
        },
        {
            "id": "services",
            "type": "services",
            "order": 2,
            "content": {
                "section_title": "Our Solutions",
                "headline": "Comprehensive Research Services",
                "description": "From audience sampling to market insights, we provide end-to-end research solutions tailored to your business needs.",
                "services": [
                    {
                        "id": "audience-sampling",
                        "icon": "Users",
                        "title": "Audience Sampling",
                        "description": "Access diverse, targeted respondent panels across B2B and B2C segments worldwide. Quality-assured data collection for your research needs.",
                        "features": ["Global Panel Access", "Quality Screening", "Niche Targeting"],
                        "color": "primary",
                        "link": "/#audience-sampling"
                    },
                    {
                        "id": "enterprise-solutions",
                        "icon": "Building2",
                        "title": "Enterprise Solutions",
                        "description": "Custom research solutions designed for large organizations with complex data collection requirements and multi-market studies.",
                        "features": ["Custom Panels", "Multi-Market Studies", "Dedicated Support"],
                        "color": "accent",
                        "link": "/#enterprise-solutions"
                    },
                    {
                        "id": "security-measures",
                        "icon": "Shield",
                        "title": "Security Measures",
                        "description": "Industry-leading security protocols to ensure data integrity, respondent verification, and fraud prevention in all surveys.",
                        "features": ["Fraud Detection", "Data Encryption", "GDPR Compliant"],
                        "color": "primary",
                        "link": "/#security-measures"
                    },
                    {
                        "id": "survey-programming",
                        "icon": "MonitorPlay",
                        "title": "Survey Programming & Hosting",
                        "description": "Expert survey design and programming services with secure hosting infrastructure for seamless data collection.",
                        "features": ["Custom Programming", "Multi-device Support", "Real-time Tracking"],
                        "color": "accent",
                        "link": "/#survey"
                    },
                    {
                        "id": "qualitative-fieldwork",
                        "icon": "MessageCircle",
                        "title": "Qualitative Fieldwork",
                        "description": "In-depth qualitative research including focus groups, IDIs, online communities, and ethnographic studies.",
                        "features": ["Focus Groups", "In-Depth Interviews", "Online Communities"],
                        "color": "primary",
                        "link": "/#fieldwork"
                    },
                    {
                        "id": "market-research",
                        "icon": "TrendingUp",
                        "title": "Market Research & Insights",
                        "description": "Comprehensive market analysis and strategic insights to drive business decisions and identify growth opportunities.",
                        "features": ["Market Analysis", "Consumer Insights", "Trend Forecasting"],
                        "color": "accent",
                        "link": "/#market-research"
                    }
                ]
            }
        },
        {
            "id": "about",
            "type": "about",
            "order": 3,
            "content": {
                "section_title": "About Us",
                "headline": "Your Trusted Partner in Market Research",
                "description": "Survey Fieldwork, a division of Cogentix Research Pvt Ltd, is a leading provider of data collection and market research services. With over 15 years of industry experience, we've helped hundreds of businesses make data-driven decisions.",
                "additional_text": "Our global panel of over 1 million respondents spans 50+ countries, enabling us to deliver quality insights across diverse markets and demographics. We combine cutting-edge technology with rigorous quality controls to ensure every data point is accurate and actionable.",
                "features": [
                    "ISO 27001 Certified Data Security",
                    "GDPR & CCPA Compliant Processes",
                    "ESOMAR Member Organization",
                    "Real-time Quality Monitoring",
                    "Multi-language Support",
                    "24/7 Technical Assistance"
                ],
                "highlights": [
                    {"icon": "Globe", "value": "50+", "label": "Countries Covered"},
                    {"icon": "Users", "value": "1M+", "label": "Panel Members"},
                    {"icon": "Award", "value": "15+", "label": "Years Experience"}
                ],
                "image": "/assets/images/about-team.jpg"
            }
        },
        {
            "id": "testimonials",
            "type": "testimonials",
            "order": 4,
            "content": {
                "section_title": "Testimonials",
                "headline": "What Our Clients Say",
                "description": "Don't just take our word for it. Here's what industry leaders have to say about working with Survey Fieldwork.",
                "testimonials": [
                    {
                        "id": "t1",
                        "name": "Sarah Johnson",
                        "role": "Head of Research",
                        "company": "Global Insights Inc.",
                        "image": "/assets/images/testimonials/sarah.jpg",
                        "content": "Survey Fieldwork has been our go-to partner for panel research. Their quality controls and fast turnaround times have consistently exceeded our expectations.",
                        "rating": 5
                    },
                    {
                        "id": "t2",
                        "name": "Michael Chen",
                        "role": "Market Research Director",
                        "company": "TechCorp Solutions",
                        "image": "/assets/images/testimonials/michael.jpg",
                        "content": "The team at Survey Fieldwork truly understands B2B research. Their ability to reach niche audiences has been invaluable for our product development.",
                        "rating": 5
                    },
                    {
                        "id": "t3",
                        "name": "Emma Williams",
                        "role": "VP of Consumer Insights",
                        "company": "RetailMax",
                        "image": "/assets/images/testimonials/emma.jpg",
                        "content": "Working with Survey Fieldwork has transformed how we collect consumer data. Their security measures and GDPR compliance give us complete peace of mind.",
                        "rating": 5
                    },
                    {
                        "id": "t4",
                        "name": "David Kumar",
                        "role": "Research Manager",
                        "company": "HealthFirst Research",
                        "image": "/assets/images/testimonials/david.jpg",
                        "content": "The qualitative fieldwork services are exceptional. Their moderators are skilled at extracting deep insights that drive our strategic decisions.",
                        "rating": 5
                    }
                ],
                "clients": [
                    {"name": "Client 1", "logo": "/assets/images/clients/client1.png"},
                    {"name": "Client 2", "logo": "/assets/images/clients/client2.png"},
                    {"name": "Client 3", "logo": "/assets/images/clients/client3.png"},
                    {"name": "Client 4", "logo": "/assets/images/clients/client4.png"}
                ]
            }
        },
        {
            "id": "cta",
            "type": "cta",
            "order": 5,
            "content": {
                "badge": "Ready to Get Started?",
                "headline": "Transform Your Research with Data-Driven Insights",
                "description": "Join hundreds of businesses that trust Survey Fieldwork for their market research needs. Let's unlock your business's full potential together.",
                "primary_cta": {"label": "Book Free Consultation", "href": "/#book"},
                "secondary_cta": {"label": "Join Our Panel", "href": "https://panel.surveyfieldwork.com"},
                "stats": [
                    {"value": "50+", "label": "Countries"},
                    {"value": "1M+", "label": "Panel Members"},
                    {"value": "500+", "label": "Projects"},
                    {"value": "98%", "label": "Satisfaction"}
                ]
            }
        },
        {
            "id": "contact",
            "type": "contact",
            "order": 6,
            "content": {
                "section_title": "Contact Us",
                "headline": "Book Your Free Consultation",
                "description": "Ready to unlock the power of data-driven insights? Get in touch with our team to discuss your research needs and how we can help you achieve your goals.",
                "benefits": [
                    "Free initial consultation",
                    "Custom solutions for every budget",
                    "Fast turnaround times",
                    "Dedicated project manager"
                ],
                "contact_info": [
                    {"icon": "Mail", "title": "Email Us", "details": "info@surveyfieldwork.com", "href": "mailto:info@surveyfieldwork.com"},
                    {"icon": "Phone", "title": "Call Us", "details": "+91 98765 43210", "href": "tel:+919876543210"},
                    {"icon": "MapPin", "title": "Visit Us", "details": "Kolkata, West Bengal, India", "href": "#"},
                    {"icon": "Clock", "title": "Working Hours", "details": "Mon - Fri: 9AM - 6PM IST", "href": "#"}
                ],
                "form_endpoint": "/api/contact",
                "zoho_form_url": "https://forms.zohopublic.in/cogentixresearch/form/WebsiteForm/formperma/..."
            }
        }
    ],
    "seo": {
        "title": "Survey Fieldwork | Market Research & Data Collection Services",
        "description": "Survey Fieldwork offers comprehensive market research services including audience sampling, survey programming, qualitative fieldwork, and enterprise solutions. Trusted by 500+ clients worldwide.",
        "keywords": ["market research", "survey fieldwork", "audience sampling", "data collection", "qualitative research"],
        "og_image": "/assets/images/og-home.jpg",
        "focus_keyword": "market research services",
        "canonical_url": "https://surveyfieldwork.com"
    },
    "seo_score": 82,
    "last_seo_analysis": datetime.utcnow(),
    "created_at": datetime.utcnow(),
    "updated_at": datetime.utcnow()
}

# ============================================================================
# BLOG POSTS
# ============================================================================

BLOG_POSTS = [
    {
        "slug": "future-online-panel-research-2024",
        "title": "The Future of Online Panel Research: Trends to Watch in 2024",
        "excerpt": "Discover the key trends shaping the online panel research industry and how to prepare your research strategy for the coming year.",
        "content": {
            "type": "html",
            "body": """<p>The landscape of online panel research is evolving rapidly, driven by technological advancements and changing respondent expectations. As we look ahead to 2024, several key trends are emerging that will shape how we conduct market research.</p>
            
<h2>1. AI-Powered Quality Control</h2>
<p>Artificial intelligence is revolutionizing how we ensure data quality. Advanced algorithms can now detect fraudulent responses in real-time, analyzing patterns in response timing, consistency, and even linguistic markers to identify bad actors before they contaminate your data.</p>

<h2>2. Mobile-First Research Design</h2>
<p>With over 60% of survey responses now coming from mobile devices, designing mobile-first surveys is no longer optional. This means rethinking question formats, reducing survey length, and optimizing for touch-screen interactions.</p>

<h2>3. Passive Data Collection</h2>
<p>Traditional surveys are being supplemented with passive data collection methods. With proper consent, researchers can now gather behavioral data that provides richer insights than self-reported information alone.</p>

<h2>4. Privacy-First Approaches</h2>
<p>With regulations like GDPR and CCPA becoming more stringent, privacy-first research methodologies are essential. This includes anonymization techniques, consent management, and transparent data handling practices.</p>

<h2>5. Hybrid Research Methods</h2>
<p>The future lies in combining quantitative and qualitative methods seamlessly. Video interviews, online communities, and traditional surveys are being integrated to provide more comprehensive insights.</p>

<h2>Conclusion</h2>
<p>Staying ahead of these trends will be crucial for researchers looking to deliver high-quality insights in 2024 and beyond. At Survey Fieldwork, we're continuously innovating to ensure our clients have access to the latest research methodologies.</p>"""
        },
        "featured_image": "/assets/images/blog/post1.jpg",
        "author_name": "Dr. Sarah Johnson",
        "author_avatar": "/assets/images/team/sarah.jpg",
        "author_bio": "Head of Research at Survey Fieldwork with 15+ years of experience in market research.",
        "categories": ["Industry Trends"],
        "tags": ["Market Research", "Trends", "AI", "Data Quality"],
        "status": "published",
        "published_at": datetime(2024, 1, 15),
        "seo": {
            "title": "Future of Online Panel Research 2024 | Survey Fieldwork",
            "description": "Discover key trends in online panel research for 2024 including AI quality control, mobile-first design, and privacy-first approaches.",
            "focus_keyword": "online panel research trends",
            "keywords": ["panel research", "research trends 2024", "AI in research", "mobile surveys"]
        },
        "seo_score": 78,
        "read_time": "5 min read",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    },
    {
        "slug": "data-quality-b2b-market-research",
        "title": "How to Ensure Data Quality in B2B Market Research",
        "excerpt": "Learn proven strategies for maintaining high data quality standards in your B2B research projects.",
        "content": {
            "type": "html",
            "body": """<p>Data quality is the foundation of any successful B2B market research project. Poor quality data leads to flawed insights and misguided business decisions. In this comprehensive guide, we'll explore proven strategies for maintaining high data quality standards.</p>

<h2>Why Data Quality Matters in B2B Research</h2>
<p>B2B research presents unique challenges compared to B2C studies. Decision-makers are harder to reach, sample sizes are typically smaller, and the stakes of each response are higher. This makes data quality even more critical.</p>

<h2>Key Strategies for Ensuring Quality</h2>

<h3>1. Robust Screening Questions</h3>
<p>Implement multi-layered screening to verify respondent qualifications. Include trap questions and consistency checks throughout the survey.</p>

<h3>2. Professional Panel Partners</h3>
<p>Work with reputable panel providers who maintain strict quality standards and regularly clean their databases.</p>

<h3>3. Real-time Quality Monitoring</h3>
<p>Use automated tools to flag suspicious response patterns as they occur, allowing for immediate intervention.</p>

<h3>4. Manual Data Review</h3>
<p>Complement automated checks with human review of open-ended responses and overall response patterns.</p>

<h2>Best Practices Summary</h2>
<ul>
<li>Use multiple verification touchpoints</li>
<li>Set realistic completion time thresholds</li>
<li>Include attention check questions</li>
<li>Validate company and job title information</li>
<li>Remove speeders and straight-liners</li>
</ul>

<p>At Survey Fieldwork, we implement all these strategies and more to ensure every B2B research project delivers actionable, reliable insights.</p>"""
        },
        "featured_image": "/assets/images/blog/post2.jpg",
        "author_name": "Michael Chen",
        "author_avatar": "/assets/images/team/michael.jpg",
        "author_bio": "Senior Research Director specializing in B2B methodology.",
        "categories": ["Best Practices"],
        "tags": ["B2B Research", "Data Quality", "Best Practices"],
        "status": "published",
        "published_at": datetime(2024, 1, 10),
        "seo": {
            "title": "B2B Market Research Data Quality Guide | Survey Fieldwork",
            "description": "Learn proven strategies for maintaining high data quality in B2B market research projects.",
            "focus_keyword": "B2B data quality",
            "keywords": ["B2B research", "data quality", "research methodology"]
        },
        "seo_score": 75,
        "read_time": "7 min read",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    },
    {
        "slug": "gdpr-compliance-market-research-guide",
        "title": "GDPR Compliance in Market Research: A Complete Guide",
        "excerpt": "Everything you need to know about maintaining GDPR compliance in your market research activities.",
        "content": {
            "type": "html",
            "body": """<p>The General Data Protection Regulation (GDPR) has fundamentally changed how market researchers collect, process, and store personal data. This comprehensive guide covers everything you need to know to ensure compliance.</p>

<h2>Understanding GDPR in Research Context</h2>
<p>GDPR applies to any research involving EU residents, regardless of where your company is located. The regulation emphasizes transparency, consent, and data minimization.</p>

<h2>Key GDPR Principles for Researchers</h2>

<h3>1. Lawful Basis for Processing</h3>
<p>You must have a valid legal basis for processing personal data. For market research, this is typically consent or legitimate interest.</p>

<h3>2. Informed Consent</h3>
<p>Participants must understand what data you're collecting and how it will be used. Consent must be freely given, specific, informed, and unambiguous.</p>

<h3>3. Data Minimization</h3>
<p>Only collect data that is necessary for your research objectives. Avoid collecting sensitive data unless absolutely required.</p>

<h3>4. Right to Access and Erasure</h3>
<p>Respondents have the right to access their data and request its deletion. Implement processes to handle such requests promptly.</p>

<h2>Practical Implementation Steps</h2>
<ul>
<li>Update privacy notices and consent forms</li>
<li>Implement data protection by design</li>
<li>Maintain records of processing activities</li>
<li>Train staff on GDPR requirements</li>
<li>Establish data breach response procedures</li>
</ul>

<p>Survey Fieldwork maintains full GDPR compliance across all our research activities, ensuring your projects meet the highest standards of data protection.</p>"""
        },
        "featured_image": "/assets/images/blog/post3.jpg",
        "author_name": "Emma Williams",
        "author_avatar": "/assets/images/team/emma.jpg",
        "author_bio": "Compliance Officer and Data Privacy Expert.",
        "categories": ["Compliance"],
        "tags": ["GDPR", "Compliance", "Data Privacy", "Research Ethics"],
        "status": "published",
        "published_at": datetime(2024, 1, 5),
        "seo": {
            "title": "GDPR Compliance for Market Research | Survey Fieldwork",
            "description": "Complete guide to GDPR compliance in market research including consent, data handling, and respondent rights.",
            "focus_keyword": "GDPR market research",
            "keywords": ["GDPR compliance", "data privacy", "research compliance", "EU regulations"]
        },
        "seo_score": 80,
        "read_time": "10 min read",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
]

# ============================================================================
# SEO TRACKING INITIAL RECORDS
# ============================================================================

SEO_TRACKING_RECORDS = [
    {
        "page_slug": "home",
        "date": datetime(2024, 1, 1),
        "score": 75,
        "issues_count": 8,
        "keywords_tracked": ["market research", "survey fieldwork", "audience sampling"]
    },
    {
        "page_slug": "home",
        "date": datetime(2024, 1, 8),
        "score": 78,
        "issues_count": 6,
        "keywords_tracked": ["market research", "survey fieldwork", "audience sampling"]
    },
    {
        "page_slug": "home",
        "date": datetime(2024, 1, 15),
        "score": 82,
        "issues_count": 4,
        "keywords_tracked": ["market research", "survey fieldwork", "audience sampling"]
    }
]

# ============================================================================
# MAIN SEEDING FUNCTION
# ============================================================================

async def seed_database():
    """Seed the marketing database with initial content"""
    
    print("Connecting to MongoDB...")
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    
    try:
        # 1. Seed Website
        print("\n1. Seeding website configuration...")
        websites_col = db["websites"]
        
        # Check if website exists
        existing = await websites_col.find_one({"domain": WEBSITE_CONFIG["domain"]})
        if existing:
            print(f"   Website {WEBSITE_CONFIG['domain']} already exists. Updating...")
            await websites_col.update_one(
                {"domain": WEBSITE_CONFIG["domain"]},
                {"$set": {**WEBSITE_CONFIG, "updated_at": datetime.utcnow()}}
            )
            website_id = existing["_id"]
        else:
            result = await websites_col.insert_one(WEBSITE_CONFIG)
            website_id = result.inserted_id
            print(f"   Created website with ID: {website_id}")
        
        # 2. Seed Navigation
        print("\n2. Seeding navigation...")
        nav_col = db["navigation"]
        await nav_col.delete_many({"website_id": website_id})
        
        for nav_item in HEADER_NAV:
            await nav_col.insert_one({
                **nav_item,
                "website_id": website_id,
                "location": "header",
                "created_at": datetime.utcnow()
            })
        
        for nav_item in FOOTER_NAV:
            await nav_col.insert_one({
                **nav_item,
                "website_id": website_id,
                "location": "footer",
                "created_at": datetime.utcnow()
            })
        print(f"   Created {len(HEADER_NAV)} header and {len(FOOTER_NAV)} footer nav items")
        
        # 3. Seed Home Page
        print("\n3. Seeding home page...")
        pages_col = db["pages"]
        
        existing_page = await pages_col.find_one({
            "website_id": website_id,
            "slug": "home"
        })
        
        page_data = {
            **HOME_PAGE,
            "website_id": website_id
        }
        
        if existing_page:
            await pages_col.update_one(
                {"_id": existing_page["_id"]},
                {"$set": {**page_data, "updated_at": datetime.utcnow()}}
            )
            print("   Updated home page")
        else:
            await pages_col.insert_one(page_data)
            print("   Created home page")
        
        # 4. Seed Blog Posts
        print("\n4. Seeding blog posts...")
        blog_col = db["blog_posts"]
        
        for post in BLOG_POSTS:
            existing_post = await blog_col.find_one({
                "website_id": website_id,
                "slug": post["slug"]
            })
            
            post_data = {
                **post,
                "website_id": website_id
            }
            
            if existing_post:
                await blog_col.update_one(
                    {"_id": existing_post["_id"]},
                    {"$set": {**post_data, "updated_at": datetime.utcnow()}}
                )
            else:
                await blog_col.insert_one(post_data)
        
        print(f"   Seeded {len(BLOG_POSTS)} blog posts")
        
        # 5. Seed SEO Tracking Records
        print("\n5. Seeding SEO tracking records...")
        seo_col = db["seo_tracking"]
        
        for record in SEO_TRACKING_RECORDS:
            await seo_col.insert_one({
                **record,
                "website_id": website_id
            })
        
        print(f"   Seeded {len(SEO_TRACKING_RECORDS)} SEO tracking records")
        
        print("\n" + "="*50)
        print("✅ Database seeding completed successfully!")
        print(f"   Website ID: {website_id}")
        print(f"   Domain: {WEBSITE_CONFIG['domain']}")
        print("="*50)
        
    except Exception as e:
        print(f"\n❌ Error seeding database: {e}")
        raise
    finally:
        client.close()

# ============================================================================
# RUN
# ============================================================================

if __name__ == "__main__":
    asyncio.run(seed_database())
