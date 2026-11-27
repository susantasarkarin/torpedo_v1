"""Blog posts of the company websites in Marketing > Websites, with visits, and
search engines told about new ones straight away (owner, 2026-11-27).

  sync()  every blog post in each site's sitemap.xml -> marketing_db.posts
          (source "site", status "published"); new posts -> Search Console
          sitemap resubmit (when the Google service account has access) + IndexNow
  visits  page views from the website tracker (email_automation.web_events),
          last 30 days and all time, stored on each post

Runs from the scheduler every 30 minutes and right after every website deploy
(05. Websites/_tools/deploy.sh calls `python -m marketing.site_posts`), so a new
post shows here and reaches search engines within a minute of going live.

    python -m marketing.site_posts            # sync now, print the report
"""
import html as H
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlparse

import requests

logger = logging.getLogger(__name__)

# site key (Marketing > Websites), base URL, blog path prefix, where the IndexNow key file is
SITES = [
    {"key": "COGENTIX", "name": "Cogentix Research", "url": "https://cogentixresearch.com", "prefix": "/blog/"},
    {"key": "SFW_BUSINESS", "name": "Survey Fieldwork (business)", "url": "https://business.surveyfieldwork.com", "prefix": "/blog/"},
    {"key": "BIMWAVE", "name": "BIMwave Solutions", "url": "https://www.bimwavesolutions.com", "prefix": "/blog/"},
    {"key": "SFW", "name": "Survey Fieldwork", "url": "https://surveyfieldwork.com", "prefix": "/blog/"},
]
INDEXNOW_KEY = "cd1d5c122fd44b9d9c7f5af64e47b0c1"   # public by design: served at /<key>.txt on every site
UA = {"User-Agent": "Mozilla/5.0 (compatible; TorpedoSiteSync/1.0; +https://torpedo.cogentixresearch.com)"}
GSC_WRITE_SCOPE = "https://www.googleapis.com/auth/webmasters"


def _gd():
    from database import get_database
    return get_database


def _get(url: str, timeout: int = 20) -> Optional[str]:
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        return r.text if r.status_code == 200 else None
    except requests.RequestException:
        return None


def blog_urls(site: Dict[str, Any], sitemap_xml: Optional[str]) -> List[str]:
    """Post URLs in a sitemap: under the blog prefix, not the blog index itself. Pure, for tests."""
    out = []
    for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap_xml or ""):
        path = urlparse(loc).path
        if path.startswith(site["prefix"]) and path.rstrip("/") != site["prefix"].rstrip("/") and not path.endswith("/index.html"):
            out.append(loc)
    return out


def page_meta(html_text: str) -> Dict[str, Any]:
    """Title, description and publish date from a post page. Pure, for tests."""
    h = html_text or ""
    title = H.unescape((re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S) or re.search(r"<title>(.*?)</title>", h, re.S) or [None, ""])[1])
    title = re.sub(r"<[^>]+>", "", title).strip()
    desc = H.unescape((re.search(r'<meta\s+name="description"\s+content="([^"]*)"', h) or [None, ""])[1]).strip()
    pub = (re.search(r'article:published_time"\s+content="([^"]+)"', h) or re.search(r'"datePublished"\s*:\s*"([^"]+)"', h) or [None, None])[1]
    mod = (re.search(r'article:modified_time"\s+content="([^"]+)"', h) or re.search(r'"dateModified"\s*:\s*"([^"]+)"', h) or [None, None])[1]

    def dt(v):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None) if v else None
        except ValueError:
            return None
    return {"title": title, "excerpt": desc, "published_at": dt(pub), "modified_at": dt(mod)}


def _ensure_site(db, site: Dict[str, Any]):
    col = db["websites"]
    doc = col.find_one({"key": site["key"]})
    if not doc:
        now = datetime.utcnow()
        col.insert_one({"key": site["key"], "name": site["name"], "url": site["url"], "created_at": now, "updated_at": now})
        doc = col.find_one({"key": site["key"]})
    return doc


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def visits(gd: Callable, url: str, now: datetime) -> Dict[str, int]:
    """Tracker page views of one post: last 30 days and all time (path with or without .html)."""
    u = urlparse(url)
    paths = {u.path, u.path[:-5] if u.path.endswith(".html") else u.path + ".html"}
    ev = gd("email_automation")["web_events"]
    q = {"type": "page_view", "host": _host(url), "path": {"$in": sorted(paths)}}
    return {"views_total": ev.count_documents(q),
            "views_30d": ev.count_documents({**q, "at": {"$gte": now - timedelta(days=30)}})}


def notify_search_engines(site: Dict[str, Any], new_urls: List[str]) -> Dict[str, Any]:
    """IndexNow (Bing, Yandex; Bing feeds ChatGPT search) and a Search Console sitemap resubmit."""
    out: Dict[str, Any] = {}
    host = urlparse(site["url"]).hostname
    try:
        r = requests.post("https://api.indexnow.org/indexnow", timeout=20, headers={"Content-Type": "application/json; charset=utf-8"},
                          data=json.dumps({"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{site['url']}/{INDEXNOW_KEY}.txt",
                                           "urlList": new_urls + [f"{site['url']}/sitemap.xml"]}))
        out["indexnow"] = r.status_code
    except requests.RequestException as e:
        out["indexnow"] = f"error: {e}"[:120]
    out["search_console"] = submit_sitemap(site)
    return out


def submit_sitemap(site: Dict[str, Any]) -> str:
    """Resubmit the site's sitemap in Search Console. Needs Integrations > Google service
    account, added as an Owner of the Search Console property. Tries the Domain property
    (sc-domain:) first, then the URL-prefix property."""
    try:
        from marketing import credentials
        raw = (credentials.secrets("google_service_account") or {}).get("service_account_json")
        if not raw:
            return "skipped: no Google service account in Integrations"
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        sa = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=[GSC_WRITE_SCOPE])
        http = AuthorizedSession(sa)
        sitemap = f"{site['url']}/sitemap.xml"
        root_domain = ".".join((urlparse(site["url"]).hostname or "").split(".")[-2:])
        for prop in (f"sc-domain:{root_domain}", site["url"] + "/"):
            r = http.put(f"https://www.googleapis.com/webmasters/v3/sites/{quote(prop, safe='')}/sitemaps/{quote(sitemap, safe='')}", timeout=30)
            if r.status_code in (200, 204):
                return f"submitted ({prop})"
        return f"not submitted: {r.status_code} {r.text[:120]}"
    except Exception as e:  # never break the sync over Search Console
        return f"error: {e}"[:160]


def sync(gd: Optional[Callable] = None, now: Optional[datetime] = None, notify: bool = True) -> Dict[str, Any]:
    gd = gd or _gd()
    now = now or datetime.utcnow()
    db = gd("marketing_db")
    posts = db["posts"]
    report: Dict[str, Any] = {"at": now, "sites": {}, "new": []}
    for site in SITES:
        site_doc = _ensure_site(db, site)
        xml = _get(f"{site['url']}/sitemap.xml")
        if xml is None:
            report["sites"][site["key"]] = "sitemap not reachable"
            continue
        urls = blog_urls(site, xml)
        new_urls = []
        for url in urls:
            existing = posts.find_one({"published_url": url}, {"_id": 1, "title": 1})
            v = visits(gd, url, now)
            if existing and existing.get("title"):
                posts.update_one({"_id": existing["_id"]}, {"$set": {**v, "views_updated_at": now, "live": True}})
                continue
            meta = page_meta(_get(url) or "")
            doc = {"title": meta["title"] or url.rsplit("/", 1)[-1], "excerpt": meta["excerpt"], "published_url": url,
                   "site_id": str(site_doc["_id"]), "site_key": site["key"], "status": "published", "source": "site",
                   "published_at": meta["published_at"], "modified_at": meta["modified_at"], "live": True,
                   **v, "views_updated_at": now, "updated_at": now}
            posts.update_one({"published_url": url}, {"$set": doc, "$setOnInsert": {"created_at": now, "discovered_at": now}}, upsert=True)
            new_urls.append(url)
        # posts no longer in the sitemap stay listed, marked as not live
        posts.update_many({"site_key": site["key"], "source": "site", "published_url": {"$nin": urls}}, {"$set": {"live": False}})
        site_rep: Dict[str, Any] = {"posts": len(urls), "new": len(new_urls)}
        if new_urls and notify:
            site_rep["search_engines"] = notify_search_engines(site, new_urls)
        report["sites"][site["key"]] = site_rep
        report["new"] += new_urls
    db["post_syncs"].insert_one(dict(report))
    report.pop("_id", None)
    return report


if __name__ == "__main__":
    print(json.dumps(sync(), default=str, indent=1))
