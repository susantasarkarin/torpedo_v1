"""
Marketing > Websites and Marketing > Media (2026-10-02: both were linked from
the Marketing section and existed nowhere).

Websites  the company sites with live health checks (up/down, response time,
          SSL days left, title and meta description present).
Posts     blog posts written here. A post for a WordPress site publishes there
          when WP_<KEY>_USER and WP_<KEY>_APP_PASSWORD are in .env (KEY = the
          site's key, e.g. SFW); otherwise it stays a draft to copy across.
Media     uploaded images, video, PDFs and documents (25 MB each), kept on
          disk under MARKETING_MEDIA_DIR.
"""
import os
import re
import socket
import ssl
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from bson import ObjectId
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from session_state import verify_session

router = APIRouter(prefix="/api/marketing", tags=["Marketing"], dependencies=[Depends(verify_session)])

DEFAULT_SITES = [
    {"key": "COGENTIX", "name": "Cogentix Research", "url": "https://cogentixresearch.com"},
    {"key": "SFW", "name": "Survey Fieldwork", "url": "https://surveyfieldwork.com"},
    {"key": "BIMWAVE", "name": "BIMwave Solutions", "url": "https://bimwavesolutions.com"},
]
MEDIA_DIR = os.getenv("MARKETING_MEDIA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "media"))
MEDIA_MAX = 25 * 1024 * 1024
MEDIA_TYPES = ("image/", "video/", "application/pdf", "application/msword", "application/vnd.openxmlformats",
               "application/vnd.ms-", "text/plain", "text/csv")


def _db():
    from database import get_database
    return get_database("marketing_db")


def _ser(d: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(d)
    d["_id"] = str(d["_id"])
    return d


# ----------------------------------------------------------------- websites
def _sites():
    col = _db()["websites"]
    if col.estimated_document_count() == 0:
        now = datetime.utcnow()
        col.insert_many([{**s, "created_at": now} for s in DEFAULT_SITES])
    return col


def _ssl_days(host: str) -> Optional[int]:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as s:
                exp = datetime.strptime(s.getpeercert()["notAfter"], "%b %d %H:%M:%S %Y %Z")
        return (exp - datetime.utcnow()).days
    except Exception:
        return None


def check_site(url: str) -> Dict[str, Any]:
    host = urlparse(url).hostname or ""
    out: Dict[str, Any] = {"checked_at": datetime.utcnow()}
    t = time.time()
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "CogentixSiteMonitor/1.0"})
        html = r.text[:200000]
        out.update({
            "status_code": r.status_code, "up": r.status_code < 400, "response_ms": int((time.time() - t) * 1000),
            "title": (re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S) or [None, ""])[1].strip()[:200],
            "has_meta_description": bool(re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'][^"\']{10,}', html, re.I)),
            "wordpress": "/wp-content/" in html or "wp-json" in html,
        })
    except Exception as e:
        out.update({"up": False, "status_code": None, "error": str(e)[:200], "response_ms": int((time.time() - t) * 1000)})
    out["ssl_days_left"] = _ssl_days(host) if url.startswith("https") and host else None
    return out


@router.get("/websites")
def list_websites():
    return {"websites": [_ser(s) for s in _sites().find().sort("name", 1)]}


@router.post("/websites")
def add_website(payload: Dict[str, Any] = Body(...)):
    url = (payload.get("url") or "").strip().rstrip("/")
    if not re.match(r"^https?://[^/\s]+\.[^/\s]+", url):
        raise HTTPException(status_code=400, detail="Enter a full address, e.g. https://example.com")
    name = (payload.get("name") or urlparse(url).hostname or url).strip()
    key = re.sub(r"[^A-Z0-9]", "", (payload.get("key") or name).upper())[:20] or "SITE"
    doc = {"name": name, "url": url, "key": key, "created_at": datetime.utcnow()}
    doc["_id"] = _sites().insert_one(doc).inserted_id
    return _ser(doc)


@router.delete("/websites/{site_id}")
def delete_website(site_id: str):
    _sites().delete_one({"_id": ObjectId(site_id)})
    return {"ok": True}


@router.post("/websites/check")
def check_websites():
    """Check every site now and remember the result."""
    col = _sites()
    out = []
    for s in col.find():
        res = check_site(s["url"])
        col.update_one({"_id": s["_id"]}, {"$set": {"last_check": res}})
        out.append(_ser({**s, "last_check": res}))
    return {"websites": out}


# -------------------------------------------------------------------- posts
def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:80] or uuid.uuid4().hex[:8]


@router.get("/posts")
def list_posts():
    return {"posts": [_ser(p) for p in _db()["posts"].find().sort("updated_at", -1)]}


_POST_FIELDS = ("title", "slug", "site_id", "excerpt", "body", "meta_title", "meta_description", "status")


@router.post("/posts")
def create_post(payload: Dict[str, Any] = Body(...)):
    if not (payload.get("title") or "").strip():
        raise HTTPException(status_code=400, detail="A post needs a title")
    now = datetime.utcnow()
    doc = {k: payload.get(k) for k in _POST_FIELDS if k in payload}
    doc.setdefault("slug", _slug(doc["title"]))
    doc.setdefault("status", "draft")
    doc.update({"created_at": now, "updated_at": now})
    doc["_id"] = _db()["posts"].insert_one(doc).inserted_id
    return _ser(doc)


@router.put("/posts/{post_id}")
def update_post(post_id: str, payload: Dict[str, Any] = Body(...)):
    upd = {k: payload.get(k) for k in _POST_FIELDS if k in payload}
    upd["updated_at"] = datetime.utcnow()
    res = _db()["posts"].update_one({"_id": ObjectId(post_id)}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Post not found")
    return _ser(_db()["posts"].find_one({"_id": ObjectId(post_id)}))


@router.delete("/posts/{post_id}")
def delete_post(post_id: str):
    _db()["posts"].delete_one({"_id": ObjectId(post_id)})
    return {"ok": True}


def _wp_auth(site: Dict[str, Any]):
    user = os.getenv(f"WP_{site.get('key', '')}_USER")
    pw = os.getenv(f"WP_{site.get('key', '')}_APP_PASSWORD")
    return (user, pw) if user and pw else None


@router.post("/posts/{post_id}/publish")
def publish_post(post_id: str):
    """Publish to the post's WordPress site (as a WordPress draft first time,
    so it is reviewed there before going live)."""
    post = _db()["posts"].find_one({"_id": ObjectId(post_id)})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    site = _sites().find_one({"_id": ObjectId(post["site_id"])}) if post.get("site_id") else None
    if not site:
        raise HTTPException(status_code=400, detail="Choose the website this post belongs to")
    auth = _wp_auth(site)
    if not auth:
        raise HTTPException(status_code=400, detail=(
            f"{site['name']} is not connected. Add WP_{site['key']}_USER and WP_{site['key']}_APP_PASSWORD "
            "(a WordPress application password) to the server .env -- or copy the HTML into the site."))
    body = {"title": post.get("title"), "content": post.get("body") or "", "excerpt": post.get("excerpt") or "",
            "slug": post.get("slug"), "status": "draft"}
    base = site["url"].rstrip("/") + "/wp-json/wp/v2/posts"
    url = f"{base}/{post['wp_id']}" if post.get("wp_id") else base
    r = requests.post(url, json=body, auth=auth, timeout=30)
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"WordPress said {r.status_code}: {r.text[:200]}")
    data = r.json()
    _db()["posts"].update_one({"_id": post["_id"]}, {"$set": {
        "wp_id": data.get("id"), "published_url": data.get("link"), "status": "sent_to_site",
        "sent_at": datetime.utcnow(), "updated_at": datetime.utcnow()}})
    return {"ok": True, "wp_id": data.get("id"), "link": data.get("link")}


# -------------------------------------------------------------------- media
@router.get("/media")
def list_media():
    return {"media": [_ser(m) for m in _db()["media"].find({}, {"path": 0}).sort("uploaded_at", -1)]}


@router.post("/media")
async def upload_media(file: UploadFile = File(...)):
    mime = file.content_type or "application/octet-stream"
    if not mime.startswith(MEDIA_TYPES):
        raise HTTPException(status_code=400, detail="Images, video, PDF, Office documents, text and CSV only")
    data = await file.read()
    if len(data) > MEDIA_MAX:
        raise HTTPException(status_code=400, detail="File too large (max 25 MB)")
    os.makedirs(MEDIA_DIR, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "file")[-80:]
    stored = f"{uuid.uuid4().hex[:12]}_{safe}"
    with open(os.path.join(MEDIA_DIR, stored), "wb") as fh:
        fh.write(data)
    doc = {"filename": file.filename or safe, "stored_name": stored, "path": os.path.join(MEDIA_DIR, stored),
           "mime_type": mime, "size_bytes": len(data), "uploaded_at": datetime.utcnow()}
    doc["_id"] = _db()["media"].insert_one(doc).inserted_id
    doc.pop("path")
    return _ser(doc)


@router.get("/media/{media_id}/file")
def get_media_file(media_id: str):
    m = _db()["media"].find_one({"_id": ObjectId(media_id)})
    if not m or not os.path.isfile(m.get("path") or ""):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(m["path"], media_type=m.get("mime_type"), filename=m.get("filename"))


@router.delete("/media/{media_id}")
def delete_media(media_id: str):
    m = _db()["media"].find_one_and_delete({"_id": ObjectId(media_id)})
    if m and m.get("path") and os.path.isfile(m["path"]):
        os.remove(m["path"])
    return {"ok": True}
