"""
PUBLIC WEBSITE API
==================

Unauthenticated read-only API for Next.js websites to fetch content.
This router does NOT require authentication - it's consumed by the public websites.

Endpoints:
- GET /api/website/config - Website settings, scripts, navigation
- GET /api/website/page/{slug} - Page content by slug
- GET /api/website/blog - List published blog posts
- GET /api/website/blog/{slug} - Single blog post
- GET /api/website/sitemap - Sitemap data for SEO

Security:
- Read-only access
- Only returns published content
- Keyed by domain (extracted from request origin/host)
"""

import os
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel
from bson import ObjectId
from pymongo import MongoClient, DESCENDING

# ============== LOGGING ==============
logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

# Marketing database (shared with marketing.py)
marketing_db = client["marketing_db"]

websites_collection = marketing_db["websites"]
pages_collection = marketing_db["pages"]
blog_posts_collection = marketing_db["blog_posts"]
navigation_collection = marketing_db["navigation"]

# ============== ROUTER ==============
router = APIRouter(prefix="/api/website", tags=["Public Website API"])


# ============== SCHEMAS ==============

class PublicWebsiteConfig(BaseModel):
    name: str
    domain: str
    logo: Optional[str] = None
    favicon: Optional[str] = None
    colors: Optional[dict] = None
    fonts: Optional[dict] = None
    defaultSeo: Optional[dict] = None
    gtmId: Optional[str] = None
    gaId: Optional[str] = None
    linkedinPartnerId: Optional[str] = None
    customHead: Optional[str] = None
    customBody: Optional[str] = None
    headerNav: List[dict] = []
    footerNav: List[dict] = []


class PublicPageSection(BaseModel):
    id: str
    type: str
    order: int
    content: dict


class PublicPage(BaseModel):
    slug: str
    title: str
    sections: List[dict]
    seo: Optional[dict] = None


class PublicBlogPost(BaseModel):
    slug: str
    title: str
    excerpt: Optional[str] = None
    content: Optional[dict] = None
    featured_image: Optional[str] = None
    author_name: Optional[str] = None
    categories: List[str] = []
    tags: List[str] = []
    published_at: Optional[str] = None


class PublicBlogListItem(BaseModel):
    slug: str
    title: str
    excerpt: Optional[str] = None
    featured_image: Optional[str] = None
    author_name: Optional[str] = None
    categories: List[str] = []
    published_at: Optional[str] = None


class SitemapEntry(BaseModel):
    loc: str
    lastmod: Optional[str] = None
    changefreq: str = "weekly"
    priority: float = 0.5


# ============== HELPER FUNCTIONS ==============

def get_domain_from_request(request: Request) -> str:
    """Extract domain from request headers"""
    # Check X-Forwarded-Host first (for reverse proxy setups)
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        return forwarded_host.split(":")[0].lower()
    
    # Check Origin header (for CORS requests)
    origin = request.headers.get("origin")
    if origin:
        # Remove protocol (http:// or https://)
        domain = origin.replace("https://", "").replace("http://", "")
        return domain.split(":")[0].lower()
    
    # Fallback to Host header
    host = request.headers.get("host", "")
    return host.split(":")[0].lower()


def get_website_by_domain(domain: str) -> dict:
    """Get website by domain or raise 404"""
    # Try exact match first
    website = websites_collection.find_one({
        "domain": domain,
        "status": "active"
    })
    
    if not website:
        # Try with/without www
        alt_domain = f"www.{domain}" if not domain.startswith("www.") else domain.replace("www.", "")
        website = websites_collection.find_one({
            "domain": alt_domain,
            "status": "active"
        })
    
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    
    return website


def serialize_datetime(dt) -> Optional[str]:
    """Convert datetime to ISO string"""
    if isinstance(dt, datetime):
        return dt.isoformat()
    return None


# ============== ENDPOINTS ==============

@router.get("/config", response_model=PublicWebsiteConfig)
async def get_website_config(request: Request, domain: Optional[str] = Query(default=None)):
    """
    Get website configuration including settings, scripts, and navigation.
    Domain can be passed as query param or extracted from request headers.
    """
    target_domain = domain or get_domain_from_request(request)
    
    if not target_domain:
        raise HTTPException(status_code=400, detail="Domain not specified")
    
    website = get_website_by_domain(target_domain)
    website_id = str(website["_id"])
    
    # Get settings
    settings = website.get("settings", {}) or {}
    scripts = website.get("scripts", {}) or {}
    
    # Get navigation
    header_nav = navigation_collection.find_one({"website_id": website_id, "location": "header"})
    footer_nav = navigation_collection.find_one({"website_id": website_id, "location": "footer"})
    
    return PublicWebsiteConfig(
        name=website["name"],
        domain=website["domain"],
        logo=settings.get("logo"),
        favicon=settings.get("favicon"),
        colors=settings.get("colors"),
        fonts=settings.get("fonts"),
        defaultSeo=settings.get("defaultSeo"),
        gtmId=scripts.get("gtmId"),
        gaId=scripts.get("gaId"),
        linkedinPartnerId=scripts.get("linkedinPartnerId"),
        customHead=scripts.get("customHead"),
        customBody=scripts.get("customBody"),
        headerNav=header_nav.get("items", []) if header_nav else [],
        footerNav=footer_nav.get("items", []) if footer_nav else []
    )


@router.get("/page/{slug:path}", response_model=PublicPage)
async def get_page(slug: str, request: Request, domain: Optional[str] = Query(default=None)):
    """
    Get a published page by slug.
    Slug can include path segments (e.g., 'about', 'services/research')
    """
    target_domain = domain or get_domain_from_request(request)
    website = get_website_by_domain(target_domain)
    website_id = str(website["_id"])
    
    # Normalize slug
    slug = slug.strip("/")
    if not slug:
        slug = "home"  # Default home page
    
    page = pages_collection.find_one({
        "website_id": website_id,
        "slug": slug,
        "status": "published"
    })
    
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    return PublicPage(
        slug=page["slug"],
        title=page["title"],
        sections=page.get("sections", []),
        seo=page.get("seo")
    )


@router.get("/blog", response_model=List[PublicBlogListItem])
async def list_blog_posts(
    request: Request,
    domain: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50)
):
    """
    List published blog posts with pagination.
    Can filter by category or tag.
    """
    target_domain = domain or get_domain_from_request(request)
    website = get_website_by_domain(target_domain)
    website_id = str(website["_id"])
    
    # Build query
    query = {
        "website_id": website_id,
        "status": "published"
    }
    
    if category:
        query["categories"] = category
    if tag:
        query["tags"] = tag
    
    # Calculate skip
    skip = (page - 1) * limit
    
    posts = list(blog_posts_collection.find(query)
                 .sort("published_at", DESCENDING)
                 .skip(skip)
                 .limit(limit))
    
    return [
        PublicBlogListItem(
            slug=p["slug"],
            title=p["title"],
            excerpt=p.get("excerpt"),
            featured_image=p.get("featured_image"),
            author_name=p.get("author_name"),
            categories=p.get("categories", []),
            published_at=serialize_datetime(p.get("published_at"))
        )
        for p in posts
    ]


@router.get("/blog/count")
async def get_blog_count(
    request: Request,
    domain: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None)
):
    """Get total count of published blog posts (for pagination)"""
    target_domain = domain or get_domain_from_request(request)
    website = get_website_by_domain(target_domain)
    website_id = str(website["_id"])
    
    query = {
        "website_id": website_id,
        "status": "published"
    }
    
    if category:
        query["categories"] = category
    if tag:
        query["tags"] = tag
    
    count = blog_posts_collection.count_documents(query)
    
    return {"count": count}


@router.get("/blog/categories")
async def get_blog_categories(request: Request, domain: Optional[str] = Query(default=None)):
    """Get all unique blog categories for a website"""
    target_domain = domain or get_domain_from_request(request)
    website = get_website_by_domain(target_domain)
    website_id = str(website["_id"])
    
    categories = blog_posts_collection.distinct("categories", {
        "website_id": website_id,
        "status": "published"
    })
    
    return {"categories": categories}


@router.get("/blog/tags")
async def get_blog_tags(request: Request, domain: Optional[str] = Query(default=None)):
    """Get all unique blog tags for a website"""
    target_domain = domain or get_domain_from_request(request)
    website = get_website_by_domain(target_domain)
    website_id = str(website["_id"])
    
    tags = blog_posts_collection.distinct("tags", {
        "website_id": website_id,
        "status": "published"
    })
    
    return {"tags": tags}


@router.get("/blog/{slug}", response_model=PublicBlogPost)
async def get_blog_post(slug: str, request: Request, domain: Optional[str] = Query(default=None)):
    """Get a single published blog post by slug"""
    target_domain = domain or get_domain_from_request(request)
    website = get_website_by_domain(target_domain)
    website_id = str(website["_id"])
    
    post = blog_posts_collection.find_one({
        "website_id": website_id,
        "slug": slug,
        "status": "published"
    })
    
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found")
    
    return PublicBlogPost(
        slug=post["slug"],
        title=post["title"],
        excerpt=post.get("excerpt"),
        content=post.get("content"),
        featured_image=post.get("featured_image"),
        author_name=post.get("author_name"),
        categories=post.get("categories", []),
        tags=post.get("tags", []),
        published_at=serialize_datetime(post.get("published_at"))
    )


@router.get("/sitemap", response_model=List[SitemapEntry])
async def get_sitemap(request: Request, domain: Optional[str] = Query(default=None)):
    """
    Get sitemap data for SEO.
    Returns all published pages and blog posts.
    """
    target_domain = domain or get_domain_from_request(request)
    website = get_website_by_domain(target_domain)
    website_id = str(website["_id"])
    
    base_url = f"https://{website['domain']}"
    entries = []
    
    # Add pages
    pages = pages_collection.find({
        "website_id": website_id,
        "status": "published"
    })
    
    for page in pages:
        slug = page["slug"]
        url = f"{base_url}/" if slug == "home" else f"{base_url}/{slug}"
        entries.append(SitemapEntry(
            loc=url,
            lastmod=serialize_datetime(page.get("updated_at")),
            changefreq="weekly" if slug != "home" else "daily",
            priority=1.0 if slug == "home" else 0.8
        ))
    
    # Add blog posts
    posts = blog_posts_collection.find({
        "website_id": website_id,
        "status": "published"
    })
    
    for post in posts:
        entries.append(SitemapEntry(
            loc=f"{base_url}/blog/{post['slug']}",
            lastmod=serialize_datetime(post.get("published_at") or post.get("updated_at")),
            changefreq="monthly",
            priority=0.6
        ))
    
    return entries


@router.get("/recent-posts", response_model=List[PublicBlogListItem])
async def get_recent_posts(
    request: Request,
    domain: Optional[str] = Query(default=None),
    limit: int = Query(default=3, ge=1, le=10)
):
    """Get recent blog posts (for homepage widgets)"""
    target_domain = domain or get_domain_from_request(request)
    website = get_website_by_domain(target_domain)
    website_id = str(website["_id"])
    
    posts = list(blog_posts_collection.find({
        "website_id": website_id,
        "status": "published"
    }).sort("published_at", DESCENDING).limit(limit))
    
    return [
        PublicBlogListItem(
            slug=p["slug"],
            title=p["title"],
            excerpt=p.get("excerpt"),
            featured_image=p.get("featured_image"),
            author_name=p.get("author_name"),
            categories=p.get("categories", []),
            published_at=serialize_datetime(p.get("published_at"))
        )
        for p in posts
    ]
