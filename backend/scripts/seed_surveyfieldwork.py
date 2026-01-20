"""
SEED DEFAULT WEBSITE CONTENT
============================

Seeds the marketing_db with the default Survey Fieldwork website content.
This allows the website to be editable via CRM while having sensible defaults.

Run: python -m backend.scripts.seed_surveyfieldwork
"""

import os
import sys
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["marketing_db"]


def seed_surveyfieldwork():
    """Seed Survey Fieldwork website with default content"""
    
    print("🌱 Seeding Survey Fieldwork website...")
    
    now = datetime.utcnow()
    
    # ============== WEBSITE ==============
    website_data = {
        "name": "Survey Fieldwork",
        "domain": "surveyfieldwork.com",
        "status": "active",
        "settings": {
            "logo": "/assets/images/logo.png",
            "logoWhite": "/assets/images/logo-white.png",
            "favicon": "/favicon.ico",
            "colors": {
                "primary": "#0058CC",
                "primaryLight": "#3B82F6",
                "accent": "#10B981",
                "secondary": "#1E293B"
            },
            "fonts": {
                "heading": "Montserrat",
                "body": "Open Sans"
            },
            "defaultSeo": {
                "title": "Survey Fieldwork | Market Research & Data Collection Services",
                "description": "Survey Fieldwork provides premium market research services including audience sampling, survey programming, qualitative fieldwork, and enterprise solutions. Trusted partner for data-driven insights.",
                "ogImage": "/assets/images/og-image.jpg"
            }
        },
        "scripts": {
            "gtmId": "GTM-K5BX7PV2",
            "gaId": "G-HFZMW72Z32",
            "linkedinPartnerId": "7281020",
            "customHead": "",
            "customBody": ""
        },
        "created_at": now,
        "updated_at": now
    }
    
    # Check if website exists
    existing = db.websites.find_one({"domain": "surveyfieldwork.com"})
    if existing:
        website_id = str(existing["_id"])
        db.websites.update_one({"_id": existing["_id"]}, {"$set": {**website_data, "updated_at": now}})
        print(f"  ✓ Updated existing website: {website_id}")
    else:
        result = db.websites.insert_one(website_data)
        website_id = str(result.inserted_id)
        print(f"  ✓ Created website: {website_id}")
    
    # ============== NAVIGATION ==============
    header_nav = {
        "website_id": website_id,
        "location": "header",
        "items": [
            {"id": "nav-1", "label": "Home", "link": "/", "type": "link"},
            {"id": "nav-2", "label": "About Us", "link": "/#about", "type": "anchor"},
            {
                "id": "nav-3", 
                "label": "Solutions", 
                "type": "dropdown",
                "children": [
                    {
                        "id": "nav-3-1",
                        "label": "Online Sampling",
                        "type": "dropdown",
                        "children": [
                            {"id": "nav-3-1-1", "label": "Audience Sampling", "link": "/#audience-sampling", "type": "anchor"},
                            {"id": "nav-3-1-2", "label": "Enterprise Solutions", "link": "/#enterprise-solutions", "type": "anchor"},
                            {"id": "nav-3-1-3", "label": "Security Measures", "link": "/#security-measures", "type": "anchor"}
                        ]
                    },
                    {"id": "nav-3-2", "label": "Survey Programming & Hosting", "link": "/#survey", "type": "anchor"},
                    {"id": "nav-3-3", "label": "Qualitative Fieldwork", "link": "/#fieldwork", "type": "anchor"},
                    {"id": "nav-3-4", "label": "Market Research & Insights", "link": "/#market-research", "type": "anchor"}
                ]
            },
            {"id": "nav-4", "label": "Blogs", "link": "/blog", "type": "link"},
            {"id": "nav-5", "label": "Join Panel", "link": "https://panel.surveyfieldwork.com", "type": "link"},
            {"id": "nav-6", "label": "Book Free Consultation", "link": "/#book", "type": "anchor"}
        ],
        "updated_at": now
    }
    
    db.navigation.delete_one({"website_id": website_id, "location": "header"})
    db.navigation.insert_one(header_nav)
    print("  ✓ Created header navigation")
    
    footer_nav = {
        "website_id": website_id,
        "location": "footer",
        "items": [
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
                    {"id": "f-6", "label": "Market Research", "link": "/#market-research", "type": "anchor"}
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
                    {"id": "f-10", "label": "Contact", "link": "/#book", "type": "anchor"}
                ]
            },
            {
                "id": "footer-legal",
                "label": "Legal",
                "type": "group",
                "children": [
                    {"id": "f-11", "label": "Privacy Policy", "link": "/privacy-policy", "type": "link"},
                    {"id": "f-12", "label": "Terms of Service", "link": "/terms", "type": "link"},
                    {"id": "f-13", "label": "Cookie Policy", "link": "/cookies", "type": "link"},
                    {"id": "f-14", "label": "GDPR Compliance", "link": "/gdpr", "type": "link"}
                ]
            }
        ],
        "updated_at": now
    }
    
    db.navigation.delete_one({"website_id": website_id, "location": "footer"})
    db.navigation.insert_one(footer_nav)
    print("  ✓ Created footer navigation")
    
    # ============== HOME PAGE ==============
    home_page = {
        "website_id": website_id,
        "slug": "home",
        "title": "Home",
        "sections": [
            {
                "id": "hero",
                "type": "hero",
                "order": 1,
                "content": {
                    "headline": "Where Data Meets Strategy",
                    "subheadline": "Partner with us to gain a competitive edge, seize opportunities, and drive success in your industry. Experience the power of market research and unlock your business's full potential today.",
                    "primaryCta": {"label": "Book Free Consultation", "link": "/#book"},
                    "secondaryCta": {"label": "Learn More", "link": "/#about"},
                    "trustBadges": ["Trusted", "Experienced", "Professional"],
                    "stats": [
                        {"value": "50+", "label": "Countries"},
                        {"value": "1M+", "label": "Respondents"},
                        {"value": "500+", "label": "Projects"}
                    ],
                    "image": "/assets/images/hero-visual.png"
                }
            },
            {
                "id": "services",
                "type": "services",
                "order": 2,
                "content": {
                    "badge": "Our Solutions",
                    "headline": "Comprehensive Research Services",
                    "subheadline": "From audience sampling to market insights, we provide end-to-end research solutions tailored to your business needs.",
                    "services": [
                        {
                            "icon": "users",
                            "title": "Audience Sampling",
                            "description": "Access diverse, targeted respondent panels across B2B and B2C segments worldwide. Quality-assured data collection for your research needs.",
                            "features": ["Global Panel Access", "Quality Screening", "Niche Targeting"],
                            "link": "/#audience-sampling"
                        },
                        {
                            "icon": "building",
                            "title": "Enterprise Solutions",
                            "description": "Custom research solutions designed for large organizations with complex data collection requirements and multi-market studies.",
                            "features": ["Custom Panels", "Multi-Market Studies", "Dedicated Support"],
                            "link": "/#enterprise-solutions"
                        },
                        {
                            "icon": "shield",
                            "title": "Security Measures",
                            "description": "Industry-leading security protocols to ensure data integrity, respondent verification, and fraud prevention in all surveys.",
                            "features": ["Fraud Detection", "Data Encryption", "GDPR Compliant"],
                            "link": "/#security-measures"
                        },
                        {
                            "icon": "monitor",
                            "title": "Survey Programming & Hosting",
                            "description": "Expert survey design and programming services with secure hosting infrastructure for seamless data collection.",
                            "features": ["Custom Programming", "Multi-device Support", "Real-time Tracking"],
                            "link": "/#survey"
                        },
                        {
                            "icon": "message",
                            "title": "Qualitative Fieldwork",
                            "description": "In-depth qualitative research including focus groups, IDIs, online communities, and ethnographic studies.",
                            "features": ["Focus Groups", "In-Depth Interviews", "Online Communities"],
                            "link": "/#fieldwork"
                        },
                        {
                            "icon": "trending",
                            "title": "Market Research & Insights",
                            "description": "Comprehensive market analysis and strategic insights to drive business decisions and identify growth opportunities.",
                            "features": ["Market Analysis", "Consumer Insights", "Trend Forecasting"],
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
                    "badge": "About Us",
                    "headline": "Your Trusted Partner in Market Research",
                    "description": "Survey Fieldwork, a division of Cogentix Research Pvt Ltd, is a leading provider of data collection and market research services. With over 15 years of industry experience, we've helped hundreds of businesses make data-driven decisions.",
                    "secondaryText": "Our global panel of over 1 million respondents spans 50+ countries, enabling us to deliver quality insights across diverse markets and demographics. We combine cutting-edge technology with rigorous quality controls to ensure every data point is accurate and actionable.",
                    "features": [
                        "ISO 27001 Certified Data Security",
                        "GDPR & CCPA Compliant Processes",
                        "ESOMAR Member Organization",
                        "Real-time Quality Monitoring",
                        "Multi-language Support",
                        "24/7 Technical Assistance"
                    ],
                    "highlights": [
                        {"icon": "globe", "value": "50+", "label": "Countries Covered"},
                        {"icon": "users", "value": "1M+", "label": "Panel Members"},
                        {"icon": "award", "value": "15+", "label": "Years Experience"}
                    ],
                    "image": "/assets/images/about-team.jpg"
                }
            },
            {
                "id": "testimonials",
                "type": "testimonials",
                "order": 4,
                "content": {
                    "badge": "Testimonials",
                    "headline": "What Our Clients Say",
                    "subheadline": "Don't just take our word for it. Here's what industry leaders have to say about working with Survey Fieldwork.",
                    "testimonials": [
                        {
                            "name": "Sarah Johnson",
                            "role": "Head of Research",
                            "company": "Global Insights Inc.",
                            "content": "Survey Fieldwork has been our go-to partner for panel research. Their quality controls and fast turnaround times have consistently exceeded our expectations.",
                            "rating": 5,
                            "image": "/assets/images/testimonials/sarah.jpg"
                        },
                        {
                            "name": "Michael Chen",
                            "role": "Market Research Director",
                            "company": "TechCorp Solutions",
                            "content": "The team at Survey Fieldwork truly understands B2B research. Their ability to reach niche audiences has been invaluable for our product development.",
                            "rating": 5,
                            "image": "/assets/images/testimonials/michael.jpg"
                        },
                        {
                            "name": "Emma Williams",
                            "role": "VP of Consumer Insights",
                            "company": "RetailMax",
                            "content": "Working with Survey Fieldwork has transformed how we collect consumer data. Their security measures and GDPR compliance give us complete peace of mind.",
                            "rating": 5,
                            "image": "/assets/images/testimonials/emma.jpg"
                        },
                        {
                            "name": "David Kumar",
                            "role": "Research Manager",
                            "company": "HealthFirst Research",
                            "content": "The qualitative fieldwork services are exceptional. Their moderators are skilled at extracting deep insights that drive our strategic decisions.",
                            "rating": 5,
                            "image": "/assets/images/testimonials/david.jpg"
                        }
                    ],
                    "clientLogos": [
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
                    "subheadline": "Join hundreds of businesses that trust Survey Fieldwork for their market research needs. Let's unlock your business's full potential together.",
                    "primaryCta": {"label": "Book Free Consultation", "link": "/#book"},
                    "secondaryCta": {"label": "Join Our Panel", "link": "https://panel.surveyfieldwork.com"},
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
                    "badge": "Contact Us",
                    "headline": "Book Your Free Consultation",
                    "subheadline": "Ready to unlock the power of data-driven insights? Get in touch with our team to discuss your research needs and how we can help you achieve your goals.",
                    "contactInfo": [
                        {"icon": "mail", "title": "Email Us", "details": "info@surveyfieldwork.com", "link": "mailto:info@surveyfieldwork.com"},
                        {"icon": "phone", "title": "Call Us", "details": "+91 98765 43210", "link": "tel:+919876543210"},
                        {"icon": "map", "title": "Visit Us", "details": "Kolkata, West Bengal, India"},
                        {"icon": "clock", "title": "Working Hours", "details": "Mon - Fri: 9AM - 6PM IST"}
                    ],
                    "formFields": ["name", "email", "company", "phone", "service", "message"],
                    "serviceOptions": [
                        "Audience Sampling",
                        "Enterprise Solutions",
                        "Survey Programming & Hosting",
                        "Qualitative Fieldwork",
                        "Market Research & Insights",
                        "Other"
                    ],
                    "features": [
                        "Free initial consultation",
                        "Custom solutions for every budget",
                        "Fast turnaround times",
                        "Dedicated project manager"
                    ]
                }
            }
        ],
        "seo": {
            "title": "Survey Fieldwork | Market Research & Data Collection Services",
            "description": "Survey Fieldwork provides premium market research services including audience sampling, survey programming, qualitative fieldwork, and enterprise solutions. Trusted partner for data-driven insights.",
            "ogImage": "/assets/images/og-image.jpg"
        },
        "status": "published",
        "published_at": now,
        "created_at": now,
        "updated_at": now
    }
    
    db.pages.delete_one({"website_id": website_id, "slug": "home"})
    db.pages.insert_one(home_page)
    print("  ✓ Created home page with all sections")
    
    # ============== BLOG POSTS ==============
    blog_posts = [
        {
            "website_id": website_id,
            "slug": "future-online-panel-research-2024",
            "title": "The Future of Online Panel Research: Trends to Watch in 2024",
            "excerpt": "Discover the key trends shaping the online panel research industry and how to prepare your research strategy for the coming year.",
            "content": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "The landscape of online panel research is evolving rapidly, driven by technological advancements and changing respondent expectations. As we look ahead to 2024, several key trends are emerging that will shape how we conduct market research."}]},
                    {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "1. AI-Powered Quality Control"}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "Artificial intelligence is revolutionizing how we ensure data quality. Advanced algorithms can now detect fraudulent responses in real-time, analyzing patterns in response timing, consistency, and even linguistic markers to identify bad actors before they contaminate your data."}]},
                    {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "2. Mobile-First Research Design"}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "With over 60% of survey responses now coming from mobile devices, designing mobile-first surveys is no longer optional. This means rethinking question formats, reducing survey length, and optimizing for touch-screen interactions."}]},
                    {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "3. Privacy-First Approaches"}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "With regulations like GDPR and CCPA becoming more stringent, privacy-first research methodologies are essential. This includes anonymization techniques, consent management, and transparent data handling practices."}]}
                ]
            },
            "featured_image": "/assets/images/blog/post1.jpg",
            "author_id": "system",
            "author_name": "Survey Fieldwork Team",
            "categories": ["Industry Trends"],
            "tags": ["Market Research", "Trends", "AI", "Data Quality"],
            "status": "published",
            "published_at": datetime(2024, 1, 15),
            "created_at": now,
            "updated_at": now
        },
        {
            "website_id": website_id,
            "slug": "data-quality-b2b-market-research",
            "title": "How to Ensure Data Quality in B2B Market Research",
            "excerpt": "Learn proven strategies for maintaining high data quality standards in your B2B research projects.",
            "content": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Data quality is the foundation of successful B2B market research. Poor quality data leads to flawed insights, wasted resources, and potentially costly business decisions. Here's how to ensure your B2B research meets the highest quality standards."}]},
                    {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Understanding B2B Data Quality Challenges"}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "B2B research presents unique challenges compared to consumer research. Decision-makers are harder to reach, sample sizes are often smaller, and the stakes for accurate data are higher."}]}
                ]
            },
            "featured_image": "/assets/images/blog/post2.jpg",
            "author_id": "system",
            "author_name": "Survey Fieldwork Team",
            "categories": ["Best Practices"],
            "tags": ["B2B Research", "Data Quality", "Best Practices"],
            "status": "published",
            "published_at": datetime(2024, 1, 10),
            "created_at": now,
            "updated_at": now
        },
        {
            "website_id": website_id,
            "slug": "gdpr-compliance-market-research-guide",
            "title": "GDPR Compliance in Market Research: A Complete Guide",
            "excerpt": "Everything you need to know about maintaining GDPR compliance in your market research activities.",
            "content": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "The General Data Protection Regulation (GDPR) has fundamentally changed how market researchers collect, process, and store personal data. Understanding and maintaining compliance is essential for any organization conducting research in the EU or with EU citizens."}]}
                ]
            },
            "featured_image": "/assets/images/blog/post3.jpg",
            "author_id": "system",
            "author_name": "Survey Fieldwork Team",
            "categories": ["Compliance"],
            "tags": ["GDPR", "Compliance", "Data Privacy", "Regulations"],
            "status": "published",
            "published_at": datetime(2024, 1, 5),
            "created_at": now,
            "updated_at": now
        }
    ]
    
    # Clear existing and insert new
    db.blog_posts.delete_many({"website_id": website_id})
    db.blog_posts.insert_many(blog_posts)
    print(f"  ✓ Created {len(blog_posts)} blog posts")
    
    # ============== SUMMARY ==============
    print("\n✅ Survey Fieldwork website seeded successfully!")
    print(f"   Website ID: {website_id}")
    print(f"   Domain: surveyfieldwork.com")
    print(f"   Pages: 1 (home)")
    print(f"   Blog Posts: {len(blog_posts)}")
    print(f"   Navigation: header + footer")
    
    return website_id


if __name__ == "__main__":
    seed_surveyfieldwork()
