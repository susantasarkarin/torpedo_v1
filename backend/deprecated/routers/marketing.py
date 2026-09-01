"""
MARKETING ROUTER
================

Website CMS and Marketing management endpoints.

Endpoints:
- GET/POST /marketing/websites/ - Website CRUD
- GET/PUT/DELETE /marketing/websites/{id} - Single website operations
- GET/POST /marketing/websites/{id}/pages/ - Page CRUD
- GET/POST /marketing/websites/{id}/blog/ - Blog post CRUD
- GET/PUT /marketing/websites/{id}/navigation/ - Navigation management
- GET/POST /marketing/media/ - Media library
- GET /marketing/dashboard - Dashboard metrics
- GET /marketing/analytics/ - Analytics overview
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File, Form
from pydantic import BaseModel, Field
from bson import ObjectId
from pymongo import MongoClient, DESCENDING

# RBAC
from rbac.decorators import require_permission
from rbac.permissions import Permissions

# ============== LOGGING ==============
logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

# Marketing database
marketing_db = client["marketing_db"]

# Collections
websites_collection = marketing_db["websites"]
pages_collection = marketing_db["pages"]
blog_posts_collection = marketing_db["blog_posts"]
navigation_collection = marketing_db["navigation"]
media_collection = marketing_db["media"]
analytics_collection = marketing_db["analytics_snapshots"]

# Create indexes
try:
    websites_collection.create_index("domain", unique=True)
    pages_collection.create_index([("website_id", 1), ("slug", 1)], unique=True)
    blog_posts_collection.create_index([("website_id", 1), ("slug", 1)], unique=True)
    blog_posts_collection.create_index([("website_id", 1), ("status", 1), ("published_at", -1)])
    navigation_collection.create_index([("website_id", 1), ("location", 1)], unique=True)
    media_collection.create_index("website_id")
    logger.info("Marketing collection indexes created")
except Exception as e:
    logger.warning(f"Could not create marketing indexes: {e}")


# ============== ROUTER ==============
router = APIRouter(prefix="/marketing", tags=["Marketing"])


# ============== SCHEMAS ==============

class WebsiteSettings(BaseModel):
    logo: Optional[str] = None
    favicon: Optional[str] = None
    colors: Optional[Dict[str, str]] = None
    fonts: Optional[Dict[str, str]] = None
    defaultSeo: Optional[Dict[str, str]] = None


class WebsiteScripts(BaseModel):
    gtmId: Optional[str] = None
    gaId: Optional[str] = None
    linkedinPartnerId: Optional[str] = None
    customHead: Optional[str] = None
    customBody: Optional[str] = None


class WebsiteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    domain: str = Field(..., min_length=3, max_length=255)
    status: str = Field(default="draft")  # draft, active, maintenance
    settings: Optional[WebsiteSettings] = None
    scripts: Optional[WebsiteScripts] = None


class WebsiteUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    settings: Optional[WebsiteSettings] = None
    scripts: Optional[WebsiteScripts] = None


class WebsiteResponse(BaseModel):
    id: str
    name: str
    domain: str
    status: str
    settings: Optional[Dict[str, Any]] = None
    scripts: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str


class PageSection(BaseModel):
    id: str
    type: str
    order: int = 0
    content: Dict[str, Any] = {}


class PageSeo(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    ogImage: Optional[str] = None


class PageCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=255)
    title: str = Field(..., min_length=1, max_length=255)
    sections: List[PageSection] = []
    seo: Optional[PageSeo] = None
    status: str = Field(default="draft")  # draft, published


class PageUpdate(BaseModel):
    title: Optional[str] = None
    sections: Optional[List[PageSection]] = None
    seo: Optional[PageSeo] = None
    status: Optional[str] = None


class PageResponse(BaseModel):
    id: str
    website_id: str
    slug: str
    title: str
    sections: List[Dict[str, Any]] = []
    seo: Optional[Dict[str, Any]] = None
    status: str
    published_at: Optional[str] = None
    created_at: str
    updated_at: str


class BlogPostCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=255)
    title: str = Field(..., min_length=1, max_length=255)
    excerpt: Optional[str] = None
    content: Dict[str, Any] = {}  # Rich text JSON (TipTap format)
    featured_image: Optional[str] = None
    categories: List[str] = []
    tags: List[str] = []
    status: str = Field(default="draft")  # draft, scheduled, published
    scheduled_at: Optional[datetime] = None


class BlogPostUpdate(BaseModel):
    title: Optional[str] = None
    excerpt: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    featured_image: Optional[str] = None
    categories: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class BlogPostResponse(BaseModel):
    id: str
    website_id: str
    slug: str
    title: str
    excerpt: Optional[str] = None
    content: Dict[str, Any] = {}
    featured_image: Optional[str] = None
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    categories: List[str] = []
    tags: List[str] = []
    status: str
    scheduled_at: Optional[str] = None
    published_at: Optional[str] = None
    created_at: str
    updated_at: str


class NavigationItem(BaseModel):
    id: str
    label: str
    link: Optional[str] = None
    type: str = "link"  # link, anchor, dropdown
    children: Optional[List['NavigationItem']] = None


NavigationItem.model_rebuild()


class NavigationUpdate(BaseModel):
    items: List[NavigationItem]


class NavigationResponse(BaseModel):
    id: str
    website_id: str
    location: str  # header, footer
    items: List[Dict[str, Any]]
    updated_at: str


class MediaItem(BaseModel):
    id: str
    website_id: Optional[str] = None
    filename: str
    original_name: str
    url: str
    type: str  # image, video, document, lottie
    size: int
    dimensions: Optional[Dict[str, int]] = None
    alt_text: Optional[str] = None
    created_at: str


class DashboardMetrics(BaseModel):
    total_websites: int
    total_pages: int
    total_blog_posts: int
    published_pages: int
    published_posts: int
    draft_posts: int
    recent_posts: List[Dict[str, Any]]


# ============== HELPER FUNCTIONS ==============

def serialize_doc(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serializable dict"""
    if doc is None:
        return None
    result = dict(doc)
    if "_id" in result:
        result["id"] = str(result.pop("_id"))
    for key, value in result.items():
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def get_website_or_404(website_id: str) -> dict:
    """Get website by ID or raise 404"""
    try:
        website = websites_collection.find_one({"_id": ObjectId(website_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid website ID")
    
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    return website


# ============== DASHBOARD ==============

@router.get("/dashboard", response_model=DashboardMetrics)
async def get_dashboard():
    """Get marketing dashboard metrics"""
    
    total_websites = websites_collection.count_documents({})
    total_pages = pages_collection.count_documents({})
    total_blog_posts = blog_posts_collection.count_documents({})
    published_pages = pages_collection.count_documents({"status": "published"})
    published_posts = blog_posts_collection.count_documents({"status": "published"})
    draft_posts = blog_posts_collection.count_documents({"status": "draft"})
    
    # Recent posts
    recent = list(blog_posts_collection.find().sort("created_at", DESCENDING).limit(5))
    recent_posts = [serialize_doc(p) for p in recent]
    
    return DashboardMetrics(
        total_websites=total_websites,
        total_pages=total_pages,
        total_blog_posts=total_blog_posts,
        published_pages=published_pages,
        published_posts=published_posts,
        draft_posts=draft_posts,
        recent_posts=recent_posts
    )


# ============== WEBSITES ==============

@router.get("/websites/", response_model=List[WebsiteResponse])
async def list_websites():
    """List all websites"""
    websites = list(websites_collection.find().sort("name", 1))
    return [WebsiteResponse(**serialize_doc(w)) for w in websites]


@router.post("/websites/", response_model=WebsiteResponse)
async def create_website(data: WebsiteCreate):
    """Create a new website"""
    
    # Check if domain already exists
    existing = websites_collection.find_one({"domain": data.domain.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Domain already exists")
    
    website = {
        "name": data.name,
        "domain": data.domain.lower(),
        "status": data.status,
        "settings": data.settings.dict() if data.settings else {},
        "scripts": data.scripts.dict() if data.scripts else {},
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    
    result = websites_collection.insert_one(website)
    website["_id"] = result.inserted_id
    
    # Create default navigation
    for location in ["header", "footer"]:
        navigation_collection.insert_one({
            "website_id": str(result.inserted_id),
            "location": location,
            "items": [],
            "updated_at": datetime.utcnow()
        })
    
    return WebsiteResponse(**serialize_doc(website))


@router.get("/websites/{website_id}", response_model=WebsiteResponse)
async def get_website(website_id: str):
    """Get website by ID"""
    website = get_website_or_404(website_id)
    return WebsiteResponse(**serialize_doc(website))


@router.put("/websites/{website_id}", response_model=WebsiteResponse)
async def update_website(website_id: str, data: WebsiteUpdate):
    """Update website"""
    website = get_website_or_404(website_id)
    
    update_data = {"updated_at": datetime.utcnow()}
    if data.name is not None:
        update_data["name"] = data.name
    if data.status is not None:
        update_data["status"] = data.status
    if data.settings is not None:
        update_data["settings"] = data.settings.dict()
    if data.scripts is not None:
        update_data["scripts"] = data.scripts.dict()
    
    websites_collection.update_one(
        {"_id": ObjectId(website_id)},
        {"$set": update_data}
    )
    
    updated = websites_collection.find_one({"_id": ObjectId(website_id)})
    return WebsiteResponse(**serialize_doc(updated))


@router.delete("/websites/{website_id}")
async def delete_website(website_id: str):
    """Delete website and all associated content"""
    website = get_website_or_404(website_id)
    
    # Delete associated content
    pages_collection.delete_many({"website_id": website_id})
    blog_posts_collection.delete_many({"website_id": website_id})
    navigation_collection.delete_many({"website_id": website_id})
    media_collection.delete_many({"website_id": website_id})
    
    # Delete website
    websites_collection.delete_one({"_id": ObjectId(website_id)})
    
    return {"message": "Website deleted successfully"}


# ============== PAGES ==============

@router.get("/websites/{website_id}/pages/", response_model=List[PageResponse])
async def list_pages(website_id: str):
    """List all pages for a website"""
    get_website_or_404(website_id)
    
    pages = list(pages_collection.find({"website_id": website_id}).sort("title", 1))
    return [PageResponse(**serialize_doc(p)) for p in pages]


@router.post("/websites/{website_id}/pages/", response_model=PageResponse)
async def create_page(website_id: str, data: PageCreate):
    """Create a new page"""
    get_website_or_404(website_id)
    
    # Check if slug already exists
    existing = pages_collection.find_one({"website_id": website_id, "slug": data.slug})
    if existing:
        raise HTTPException(status_code=400, detail="Page with this slug already exists")
    
    page = {
        "website_id": website_id,
        "slug": data.slug,
        "title": data.title,
        "sections": [s.dict() for s in data.sections],
        "seo": data.seo.dict() if data.seo else {},
        "status": data.status,
        "published_at": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    
    result = pages_collection.insert_one(page)
    page["_id"] = result.inserted_id
    
    return PageResponse(**serialize_doc(page))


@router.get("/websites/{website_id}/pages/{page_id}", response_model=PageResponse)
async def get_page(website_id: str, page_id: str):
    """Get page by ID"""
    get_website_or_404(website_id)
    
    try:
        page = pages_collection.find_one({"_id": ObjectId(page_id), "website_id": website_id})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid page ID")
    
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    return PageResponse(**serialize_doc(page))


@router.put("/websites/{website_id}/pages/{page_id}", response_model=PageResponse)
async def update_page(website_id: str, page_id: str, data: PageUpdate):
    """Update page"""
    get_website_or_404(website_id)
    
    try:
        page = pages_collection.find_one({"_id": ObjectId(page_id), "website_id": website_id})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid page ID")
    
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    update_data = {"updated_at": datetime.utcnow()}
    if data.title is not None:
        update_data["title"] = data.title
    if data.sections is not None:
        update_data["sections"] = [s.dict() for s in data.sections]
    if data.seo is not None:
        update_data["seo"] = data.seo.dict()
    if data.status is not None:
        update_data["status"] = data.status
        if data.status == "published" and page.get("published_at") is None:
            update_data["published_at"] = datetime.utcnow()
    
    pages_collection.update_one(
        {"_id": ObjectId(page_id)},
        {"$set": update_data}
    )
    
    updated = pages_collection.find_one({"_id": ObjectId(page_id)})
    return PageResponse(**serialize_doc(updated))


@router.delete("/websites/{website_id}/pages/{page_id}")
async def delete_page(website_id: str, page_id: str):
    """Delete page"""
    get_website_or_404(website_id)
    
    result = pages_collection.delete_one({"_id": ObjectId(page_id), "website_id": website_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Page not found")
    
    return {"message": "Page deleted successfully"}


@router.post("/websites/{website_id}/pages/{page_id}/publish")
async def publish_page(website_id: str, page_id: str):
    """Publish a page"""
    get_website_or_404(website_id)
    
    result = pages_collection.update_one(
        {"_id": ObjectId(page_id), "website_id": website_id},
        {"$set": {
            "status": "published",
            "published_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Page not found")
    
    return {"message": "Page published successfully"}


# ============== BLOG POSTS ==============

@router.get("/websites/{website_id}/blog/", response_model=List[BlogPostResponse])
async def list_blog_posts(
    website_id: str,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100)
):
    """List blog posts for a website"""
    get_website_or_404(website_id)
    
    query = {"website_id": website_id}
    if status:
        query["status"] = status
    
    posts = list(blog_posts_collection.find(query).sort("created_at", DESCENDING).limit(limit))
    return [BlogPostResponse(**serialize_doc(p)) for p in posts]


@router.post("/websites/{website_id}/blog/", response_model=BlogPostResponse)
async def create_blog_post(website_id: str, data: BlogPostCreate):
    """Create a new blog post"""
    get_website_or_404(website_id)
    
    # Check if slug already exists
    existing = blog_posts_collection.find_one({"website_id": website_id, "slug": data.slug})
    if existing:
        raise HTTPException(status_code=400, detail="Blog post with this slug already exists")
    
    post = {
        "website_id": website_id,
        "slug": data.slug,
        "title": data.title,
        "excerpt": data.excerpt,
        "content": data.content,
        "featured_image": data.featured_image,
        "author_id": None,  # TODO: Get from current user
        "categories": data.categories,
        "tags": data.tags,
        "status": data.status,
        "scheduled_at": data.scheduled_at,
        "published_at": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    
    result = blog_posts_collection.insert_one(post)
    post["_id"] = result.inserted_id
    
    return BlogPostResponse(**serialize_doc(post))


@router.get("/websites/{website_id}/blog/{post_id}", response_model=BlogPostResponse)
async def get_blog_post(website_id: str, post_id: str):
    """Get blog post by ID"""
    get_website_or_404(website_id)
    
    try:
        post = blog_posts_collection.find_one({"_id": ObjectId(post_id), "website_id": website_id})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid post ID")
    
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found")
    
    return BlogPostResponse(**serialize_doc(post))


@router.put("/websites/{website_id}/blog/{post_id}", response_model=BlogPostResponse)
async def update_blog_post(website_id: str, post_id: str, data: BlogPostUpdate):
    """Update blog post"""
    get_website_or_404(website_id)
    
    try:
        post = blog_posts_collection.find_one({"_id": ObjectId(post_id), "website_id": website_id})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid post ID")
    
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found")
    
    update_data = {"updated_at": datetime.utcnow()}
    
    for field in ["title", "excerpt", "content", "featured_image", "categories", "tags", "status", "scheduled_at"]:
        value = getattr(data, field, None)
        if value is not None:
            update_data[field] = value
    
    if data.status == "published" and post.get("published_at") is None:
        update_data["published_at"] = datetime.utcnow()
    
    blog_posts_collection.update_one(
        {"_id": ObjectId(post_id)},
        {"$set": update_data}
    )
    
    updated = blog_posts_collection.find_one({"_id": ObjectId(post_id)})
    return BlogPostResponse(**serialize_doc(updated))


@router.delete("/websites/{website_id}/blog/{post_id}")
async def delete_blog_post(website_id: str, post_id: str):
    """Delete blog post"""
    get_website_or_404(website_id)
    
    result = blog_posts_collection.delete_one({"_id": ObjectId(post_id), "website_id": website_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Blog post not found")
    
    return {"message": "Blog post deleted successfully"}


@router.post("/websites/{website_id}/blog/{post_id}/publish")
async def publish_blog_post(website_id: str, post_id: str):
    """Publish a blog post"""
    get_website_or_404(website_id)
    
    result = blog_posts_collection.update_one(
        {"_id": ObjectId(post_id), "website_id": website_id},
        {"$set": {
            "status": "published",
            "published_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Blog post not found")
    
    return {"message": "Blog post published successfully"}


# ============== NAVIGATION ==============

@router.get("/websites/{website_id}/navigation/", response_model=List[NavigationResponse])
async def list_navigation(website_id: str):
    """Get all navigation menus for a website"""
    get_website_or_404(website_id)
    
    navs = list(navigation_collection.find({"website_id": website_id}))
    return [NavigationResponse(**serialize_doc(n)) for n in navs]


@router.get("/websites/{website_id}/navigation/{location}", response_model=NavigationResponse)
async def get_navigation(website_id: str, location: str):
    """Get navigation by location (header/footer)"""
    get_website_or_404(website_id)
    
    nav = navigation_collection.find_one({"website_id": website_id, "location": location})
    if not nav:
        # Create default empty navigation
        nav = {
            "website_id": website_id,
            "location": location,
            "items": [],
            "updated_at": datetime.utcnow()
        }
        result = navigation_collection.insert_one(nav)
        nav["_id"] = result.inserted_id
    
    return NavigationResponse(**serialize_doc(nav))


@router.put("/websites/{website_id}/navigation/{location}", response_model=NavigationResponse)
async def update_navigation(website_id: str, location: str, data: NavigationUpdate):
    """Update navigation menu"""
    get_website_or_404(website_id)
    
    items = [item.dict() for item in data.items]
    
    result = navigation_collection.update_one(
        {"website_id": website_id, "location": location},
        {"$set": {
            "items": items,
            "updated_at": datetime.utcnow()
        }},
        upsert=True
    )
    
    nav = navigation_collection.find_one({"website_id": website_id, "location": location})
    return NavigationResponse(**serialize_doc(nav))


# ============== MEDIA LIBRARY ==============

@router.get("/media/", response_model=List[MediaItem])
async def list_media(
    website_id: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200)
):
    """List media items"""
    query = {}
    if website_id:
        query["website_id"] = website_id
    if type:
        query["type"] = type
    
    items = list(media_collection.find(query).sort("created_at", DESCENDING).limit(limit))
    return [MediaItem(**serialize_doc(item)) for item in items]


@router.post("/media/upload")
async def upload_media(
    file: UploadFile = File(...),
    website_id: Optional[str] = Form(default=None),
    alt_text: Optional[str] = Form(default=None)
):
    """Upload a media file"""
    
    # Determine file type
    content_type = file.content_type or ""
    if content_type.startswith("image/"):
        file_type = "image"
    elif content_type.startswith("video/"):
        file_type = "video"
    elif file.filename and file.filename.endswith(".json"):
        file_type = "lottie"
    else:
        file_type = "document"
    
    # Generate unique filename
    import uuid
    ext = os.path.splitext(file.filename)[1] if file.filename else ""
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    
    # In production, upload to S3/GCS/etc.
    # For now, save to local uploads folder
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads", "media")
    os.makedirs(upload_dir, exist_ok=True)
    
    file_path = os.path.join(upload_dir, unique_filename)
    content = await file.read()
    
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Get file size
    file_size = len(content)
    
    # Create media record
    media_item = {
        "website_id": website_id,
        "filename": unique_filename,
        "original_name": file.filename,
        "url": f"/uploads/media/{unique_filename}",
        "type": file_type,
        "size": file_size,
        "dimensions": None,  # TODO: Get image dimensions
        "alt_text": alt_text,
        "created_at": datetime.utcnow()
    }
    
    result = media_collection.insert_one(media_item)
    media_item["_id"] = result.inserted_id
    
    return MediaItem(**serialize_doc(media_item))


@router.delete("/media/{media_id}")
async def delete_media(media_id: str):
    """Delete a media item"""
    
    try:
        media = media_collection.find_one({"_id": ObjectId(media_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media ID")
    
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    
    # Delete file from disk
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads", "media")
    file_path = os.path.join(upload_dir, media["filename"])
    if os.path.exists(file_path):
        os.remove(file_path)
    
    # Delete from database
    media_collection.delete_one({"_id": ObjectId(media_id)})
    
    return {"message": "Media deleted successfully"}


# ============== ANALYTICS ==============

@router.get("/websites/{website_id}/analytics/")
async def get_website_analytics(
    website_id: str,
    days: int = Query(default=30, ge=1, le=90)
):
    """Get website analytics (placeholder - integrate with GA4 API)"""
    get_website_or_404(website_id)
    
    # TODO: Integrate with Google Analytics 4 API
    # For now, return placeholder data
    return {
        "website_id": website_id,
        "period_days": days,
        "pageviews": 0,
        "sessions": 0,
        "users": 0,
        "bounce_rate": 0,
        "avg_session_duration": 0,
        "top_pages": [],
        "traffic_sources": [],
        "message": "Analytics integration pending - connect GA4 API"
    }


@router.get("/analytics/overview")
async def get_analytics_overview(
    days: int = Query(default=30, ge=1, le=90)
):
    """Get analytics overview for all websites"""
    
    websites = list(websites_collection.find({"status": "active"}))
    
    # TODO: Aggregate analytics from all websites
    return {
        "period_days": days,
        "total_websites": len(websites),
        "total_pageviews": 0,
        "total_sessions": 0,
        "websites": [
            {
                "id": str(w["_id"]),
                "name": w["name"],
                "domain": w["domain"],
                "pageviews": 0,
                "sessions": 0
            }
            for w in websites
        ],
        "message": "Analytics integration pending - connect GA4 API"
    }
