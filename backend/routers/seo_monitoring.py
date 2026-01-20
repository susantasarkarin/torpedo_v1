"""
SEO & CONTENT MONITORING ROUTER
================================

AI-accessible endpoints for SEO analysis and content monitoring.
Used by AI agents to analyze website content and provide recommendations.

Endpoints:
- GET /api/seo/analyze/{website_id} - Full SEO analysis
- GET /api/seo/scores/{website_id} - SEO scores history
- POST /api/seo/scan/{website_id} - Trigger SEO scan
- GET /api/content/audit/{website_id} - Content audit
- GET /api/content/suggestions/{website_id} - AI content suggestions
"""

import os
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from bson import ObjectId
from pymongo import MongoClient, DESCENDING
from collections import Counter

# ============== LOGGING ==============
logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

marketing_db = client["marketing_db"]

websites_collection = marketing_db["websites"]
pages_collection = marketing_db["pages"]
blog_posts_collection = marketing_db["blog_posts"]
seo_scans_collection = marketing_db["seo_scans"]
content_versions_collection = marketing_db["content_versions"]

# Create indexes
try:
    seo_scans_collection.create_index([("website_id", 1), ("created_at", -1)])
    content_versions_collection.create_index([("resource_type", 1), ("resource_id", 1), ("version", -1)])
    logger.info("SEO collection indexes created")
except Exception as e:
    logger.warning(f"Could not create SEO indexes: {e}")


# ============== ROUTER ==============
router = APIRouter(prefix="/api/seo", tags=["SEO & Content Monitoring"])


# ============== SCHEMAS ==============

class SeoIssue(BaseModel):
    type: str  # error, warning, info
    category: str  # title, meta, content, images, links, performance
    message: str
    page_slug: Optional[str] = None
    recommendation: str


class SeoScore(BaseModel):
    overall: int  # 0-100
    technical: int
    content: int
    performance: int
    accessibility: int


class SeoAnalysis(BaseModel):
    website_id: str
    website_name: str
    domain: str
    scanned_at: str
    scores: SeoScore
    issues: List[SeoIssue]
    page_count: int
    blog_count: int
    recommendations: List[str]


class ContentAuditItem(BaseModel):
    type: str  # page, blog_post
    slug: str
    title: str
    status: str
    word_count: int
    has_meta_description: bool
    has_og_image: bool
    last_updated: str
    seo_score: int


class ContentAudit(BaseModel):
    website_id: str
    audited_at: str
    total_pages: int
    total_posts: int
    published_pages: int
    published_posts: int
    items: List[ContentAuditItem]
    issues: List[str]


class ContentVersion(BaseModel):
    id: str
    resource_type: str  # page, blog_post, navigation
    resource_id: str
    version: int
    changes: Dict[str, Any]
    changed_by: Optional[str] = None
    created_at: str


class ContentSuggestion(BaseModel):
    type: str  # seo, readability, engagement
    priority: str  # high, medium, low
    page_slug: Optional[str] = None
    current_value: Optional[str] = None
    suggested_value: Optional[str] = None
    reason: str


# ============== HELPER FUNCTIONS ==============

def count_words(text: str) -> int:
    """Count words in text, handling HTML"""
    if not text:
        return 0
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', str(text))
    # Split and count
    words = clean.split()
    return len(words)


def extract_text_from_sections(sections: list) -> str:
    """Extract all text content from page sections"""
    texts = []
    for section in sections:
        content = section.get("content", {})
        for key, value in content.items():
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict):
                        texts.extend(str(v) for v in item.values() if isinstance(v, str))
    return " ".join(texts)


def analyze_seo_issues(website: dict, pages: list, posts: list) -> List[dict]:
    """Analyze website for SEO issues"""
    issues = []
    
    # Website-level checks
    settings = website.get("settings", {})
    
    if not settings.get("defaultSeo", {}).get("title"):
        issues.append({
            "type": "warning",
            "category": "meta",
            "message": "No default SEO title set",
            "recommendation": "Set a default SEO title in website settings"
        })
    
    if not settings.get("defaultSeo", {}).get("description"):
        issues.append({
            "type": "warning", 
            "category": "meta",
            "message": "No default meta description set",
            "recommendation": "Set a default meta description (150-160 characters)"
        })
    
    if not settings.get("logo"):
        issues.append({
            "type": "info",
            "category": "branding",
            "message": "No logo configured",
            "recommendation": "Add a logo for brand consistency"
        })
    
    # Page-level checks
    for page in pages:
        slug = page.get("slug", "unknown")
        seo = page.get("seo", {})
        sections = page.get("sections", [])
        
        # Title checks
        if not seo.get("title"):
            issues.append({
                "type": "error",
                "category": "title",
                "message": f"Page '{slug}' has no SEO title",
                "page_slug": slug,
                "recommendation": "Add a unique, descriptive title (50-60 characters)"
            })
        elif len(seo.get("title", "")) > 60:
            issues.append({
                "type": "warning",
                "category": "title",
                "message": f"Page '{slug}' title is too long ({len(seo['title'])} chars)",
                "page_slug": slug,
                "recommendation": "Keep title under 60 characters"
            })
        
        # Meta description checks
        if not seo.get("description"):
            issues.append({
                "type": "error",
                "category": "meta",
                "message": f"Page '{slug}' has no meta description",
                "page_slug": slug,
                "recommendation": "Add a meta description (150-160 characters)"
            })
        elif len(seo.get("description", "")) > 160:
            issues.append({
                "type": "warning",
                "category": "meta",
                "message": f"Page '{slug}' meta description is too long",
                "page_slug": slug,
                "recommendation": "Keep meta description under 160 characters"
            })
        
        # Content checks
        text = extract_text_from_sections(sections)
        word_count = count_words(text)
        
        if word_count < 300:
            issues.append({
                "type": "warning",
                "category": "content",
                "message": f"Page '{slug}' has thin content ({word_count} words)",
                "page_slug": slug,
                "recommendation": "Aim for at least 300 words per page for better SEO"
            })
        
        # OG Image check
        if not seo.get("ogImage"):
            issues.append({
                "type": "info",
                "category": "social",
                "message": f"Page '{slug}' has no Open Graph image",
                "page_slug": slug,
                "recommendation": "Add an OG image for better social sharing"
            })
    
    # Blog post checks
    for post in posts:
        slug = post.get("slug", "unknown")
        
        if not post.get("excerpt"):
            issues.append({
                "type": "warning",
                "category": "content",
                "message": f"Blog post '{slug}' has no excerpt",
                "page_slug": slug,
                "recommendation": "Add an excerpt for better previews and SEO"
            })
        
        if not post.get("featured_image"):
            issues.append({
                "type": "info",
                "category": "images",
                "message": f"Blog post '{slug}' has no featured image",
                "page_slug": slug,
                "recommendation": "Add a featured image for visual appeal"
            })
        
        if not post.get("categories") or len(post.get("categories", [])) == 0:
            issues.append({
                "type": "warning",
                "category": "organization",
                "message": f"Blog post '{slug}' has no categories",
                "page_slug": slug,
                "recommendation": "Categorize posts for better organization"
            })
    
    return issues


def calculate_seo_score(issues: list, pages: list, posts: list) -> dict:
    """Calculate SEO scores based on issues"""
    # Count issues by type
    errors = sum(1 for i in issues if i.get("type") == "error")
    warnings = sum(1 for i in issues if i.get("type") == "warning")
    
    # Base scores
    technical = 100
    content = 100
    performance = 85  # Default (would need real performance data)
    accessibility = 80  # Default (would need real accessibility data)
    
    # Deduct for issues
    technical -= errors * 10
    technical -= warnings * 5
    
    # Content score based on page/post quality
    total_items = len(pages) + len(posts)
    if total_items > 0:
        items_with_meta = sum(1 for p in pages if p.get("seo", {}).get("description"))
        items_with_meta += sum(1 for p in posts if p.get("excerpt"))
        content = int((items_with_meta / total_items) * 100)
    
    # Ensure scores are in range
    technical = max(0, min(100, technical))
    content = max(0, min(100, content))
    
    overall = int((technical * 0.3 + content * 0.4 + performance * 0.15 + accessibility * 0.15))
    
    return {
        "overall": overall,
        "technical": technical,
        "content": content,
        "performance": performance,
        "accessibility": accessibility
    }


def generate_recommendations(issues: list, scores: dict) -> List[str]:
    """Generate actionable recommendations"""
    recommendations = []
    
    # Group issues by category
    categories = Counter(i.get("category") for i in issues)
    
    if categories.get("title", 0) > 0:
        recommendations.append("Review and optimize page titles for all pages - keep under 60 characters")
    
    if categories.get("meta", 0) > 0:
        recommendations.append("Add meta descriptions to all pages - aim for 150-160 characters")
    
    if categories.get("content", 0) > 0:
        recommendations.append("Expand thin content pages to at least 300+ words")
    
    if categories.get("images", 0) > 0:
        recommendations.append("Add featured images to all blog posts for better engagement")
    
    if scores.get("technical", 100) < 80:
        recommendations.append("Fix critical SEO errors to improve technical score")
    
    if scores.get("content", 100) < 70:
        recommendations.append("Improve content quality with better meta descriptions and excerpts")
    
    if len(recommendations) == 0:
        recommendations.append("Great job! Your SEO is in good shape. Consider adding more content.")
    
    return recommendations


# ============== ENDPOINTS ==============

@router.get("/analyze/{website_id}", response_model=SeoAnalysis)
async def analyze_website_seo(website_id: str):
    """
    Full SEO analysis for a website.
    
    This endpoint is designed for AI agents to analyze website SEO.
    Returns scores, issues, and recommendations.
    """
    try:
        website = websites_collection.find_one({"_id": ObjectId(website_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid website ID")
    
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    
    # Get all pages and posts
    pages = list(pages_collection.find({"website_id": website_id}))
    posts = list(blog_posts_collection.find({"website_id": website_id}))
    
    # Analyze
    issues = analyze_seo_issues(website, pages, posts)
    scores = calculate_seo_score(issues, pages, posts)
    recommendations = generate_recommendations(issues, scores)
    
    # Save scan result
    scan_doc = {
        "website_id": website_id,
        "scores": scores,
        "issues_count": len(issues),
        "created_at": datetime.utcnow()
    }
    seo_scans_collection.insert_one(scan_doc)
    
    return SeoAnalysis(
        website_id=website_id,
        website_name=website.get("name", "Unknown"),
        domain=website.get("domain", ""),
        scanned_at=datetime.utcnow().isoformat(),
        scores=SeoScore(**scores),
        issues=[SeoIssue(**i) for i in issues],
        page_count=len(pages),
        blog_count=len(posts),
        recommendations=recommendations
    )


@router.get("/scores/{website_id}")
async def get_seo_scores_history(
    website_id: str,
    days: int = Query(default=30, ge=1, le=365)
):
    """
    Get historical SEO scores for trending.
    
    Returns scores over time for AI to analyze trends.
    """
    try:
        ObjectId(website_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid website ID")
    
    since = datetime.utcnow() - timedelta(days=days)
    
    scans = list(seo_scans_collection.find(
        {"website_id": website_id, "created_at": {"$gte": since}},
        {"_id": 0, "scores": 1, "issues_count": 1, "created_at": 1}
    ).sort("created_at", 1))
    
    return {
        "website_id": website_id,
        "period_days": days,
        "scans": [
            {
                "date": s["created_at"].isoformat(),
                "scores": s["scores"],
                "issues_count": s["issues_count"]
            }
            for s in scans
        ]
    }


@router.post("/scan/{website_id}")
async def trigger_seo_scan(website_id: str):
    """
    Trigger a new SEO scan.
    
    Useful for AI agents to request fresh analysis after changes.
    """
    # Just call the analyze endpoint
    return await analyze_website_seo(website_id)


@router.get("/content/audit/{website_id}", response_model=ContentAudit)
async def audit_website_content(website_id: str):
    """
    Content audit for a website.
    
    Returns detailed content inventory with quality metrics.
    """
    try:
        website = websites_collection.find_one({"_id": ObjectId(website_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid website ID")
    
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    
    pages = list(pages_collection.find({"website_id": website_id}))
    posts = list(blog_posts_collection.find({"website_id": website_id}))
    
    items = []
    issues = []
    
    # Audit pages
    for page in pages:
        seo = page.get("seo", {})
        sections = page.get("sections", [])
        text = extract_text_from_sections(sections)
        word_count = count_words(text)
        
        # Calculate simple SEO score for item
        score = 100
        if not seo.get("title"):
            score -= 20
        if not seo.get("description"):
            score -= 20
        if not seo.get("ogImage"):
            score -= 10
        if word_count < 300:
            score -= 20
        
        items.append(ContentAuditItem(
            type="page",
            slug=page.get("slug", ""),
            title=page.get("title", "Untitled"),
            status=page.get("status", "draft"),
            word_count=word_count,
            has_meta_description=bool(seo.get("description")),
            has_og_image=bool(seo.get("ogImage")),
            last_updated=page.get("updated_at", datetime.utcnow()).isoformat() if isinstance(page.get("updated_at"), datetime) else str(page.get("updated_at", "")),
            seo_score=max(0, score)
        ))
    
    # Audit posts
    for post in posts:
        content = post.get("content", {})
        content_text = str(content) if content else ""
        word_count = count_words(content_text + (post.get("excerpt", "") or ""))
        
        score = 100
        if not post.get("excerpt"):
            score -= 20
        if not post.get("featured_image"):
            score -= 15
        if not post.get("categories"):
            score -= 10
        if word_count < 500:
            score -= 20
        
        items.append(ContentAuditItem(
            type="blog_post",
            slug=post.get("slug", ""),
            title=post.get("title", "Untitled"),
            status=post.get("status", "draft"),
            word_count=word_count,
            has_meta_description=bool(post.get("excerpt")),
            has_og_image=bool(post.get("featured_image")),
            last_updated=post.get("updated_at", datetime.utcnow()).isoformat() if isinstance(post.get("updated_at"), datetime) else str(post.get("updated_at", "")),
            seo_score=max(0, score)
        ))
    
    # Identify issues
    low_score_items = [i for i in items if i.seo_score < 60]
    if low_score_items:
        issues.append(f"{len(low_score_items)} items have SEO scores below 60%")
    
    draft_count = sum(1 for i in items if i.status == "draft")
    if draft_count > 0:
        issues.append(f"{draft_count} items are still in draft status")
    
    thin_content = [i for i in items if i.word_count < 300 and i.type == "page"]
    if thin_content:
        issues.append(f"{len(thin_content)} pages have thin content (<300 words)")
    
    return ContentAudit(
        website_id=website_id,
        audited_at=datetime.utcnow().isoformat(),
        total_pages=len(pages),
        total_posts=len(posts),
        published_pages=sum(1 for p in pages if p.get("status") == "published"),
        published_posts=sum(1 for p in posts if p.get("status") == "published"),
        items=items,
        issues=issues
    )


@router.get("/content/suggestions/{website_id}")
async def get_content_suggestions(website_id: str):
    """
    AI-generated content suggestions.
    
    Provides specific suggestions for improving content and SEO.
    """
    try:
        website = websites_collection.find_one({"_id": ObjectId(website_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid website ID")
    
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    
    pages = list(pages_collection.find({"website_id": website_id}))
    posts = list(blog_posts_collection.find({"website_id": website_id}))
    
    suggestions = []
    
    # Analyze pages for suggestions
    for page in pages:
        seo = page.get("seo", {})
        slug = page.get("slug", "")
        title = page.get("title", "")
        
        if not seo.get("title"):
            suggestions.append(ContentSuggestion(
                type="seo",
                priority="high",
                page_slug=slug,
                current_value=None,
                suggested_value=f"{title} | {website.get('name', 'Survey Fieldwork')}",
                reason="Page is missing SEO title. Suggested format: 'Page Title | Brand Name'"
            ))
        
        if not seo.get("description"):
            suggestions.append(ContentSuggestion(
                type="seo",
                priority="high",
                page_slug=slug,
                current_value=None,
                suggested_value="Add a 150-160 character description summarizing this page's content",
                reason="Meta descriptions improve click-through rates from search results"
            ))
    
    # Analyze posts
    for post in posts:
        slug = post.get("slug", "")
        
        if not post.get("excerpt"):
            suggestions.append(ContentSuggestion(
                type="seo",
                priority="medium",
                page_slug=slug,
                current_value=None,
                suggested_value="Write a 2-3 sentence excerpt summarizing the post",
                reason="Excerpts are used for meta descriptions and post previews"
            ))
        
        tags = post.get("tags", [])
        if len(tags) < 3:
            suggestions.append(ContentSuggestion(
                type="engagement",
                priority="low",
                page_slug=slug,
                current_value=f"{len(tags)} tags",
                suggested_value="Add 3-5 relevant tags",
                reason="Tags improve content discoverability and internal linking"
            ))
    
    # General suggestions
    if len(posts) < 5:
        suggestions.append(ContentSuggestion(
            type="engagement",
            priority="medium",
            page_slug=None,
            current_value=f"{len(posts)} blog posts",
            suggested_value="Publish at least 10 blog posts",
            reason="Regular blogging improves SEO and establishes authority"
        ))
    
    return {
        "website_id": website_id,
        "generated_at": datetime.utcnow().isoformat(),
        "total_suggestions": len(suggestions),
        "suggestions": [s.model_dump() for s in suggestions]
    }


@router.get("/content/versions/{resource_type}/{resource_id}")
async def get_content_versions(
    resource_type: str,
    resource_id: str,
    limit: int = Query(default=10, ge=1, le=100)
):
    """
    Get version history for a resource.
    
    Tracks changes to pages and posts for audit purposes.
    """
    if resource_type not in ["page", "blog_post", "navigation"]:
        raise HTTPException(status_code=400, detail="Invalid resource type")
    
    versions = list(content_versions_collection.find(
        {"resource_type": resource_type, "resource_id": resource_id},
        {"_id": 0}
    ).sort("version", -1).limit(limit))
    
    return {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "versions": versions
    }
