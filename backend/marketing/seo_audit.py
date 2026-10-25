"""Weekly technical SEO audit per company site (MARKETING_PLAN 3.3.2) + PageSpeed (3.3.3).

Read-only: GETs the public pages like a crawler (identifies itself, honours
robots.txt Disallow for its own crawl, max pages / politeness delay in config).
analyze_page() is pure. The sites are plain HTML + JS, so the audit also flags
pages whose raw HTML carries almost no text while shipping script (content
that only appears after JavaScript runs, which search engines may miss).

Writes seo_audits (one per site run) and seo_issues (open issues; an issue
not seen in the latest audit is closed). PageSpeed Insights results go to
cwv_results (works without a key at low volume; uses the pagespeed key from
Integrations when set).
"""
import hashlib
import json
import re
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from marketing import schema

UA = "TorpedoSEOAudit/1.0 (+https://torpedo.cogentixresearch.com; site owner's own audit)"
DEFAULTS = {"max_pages": 150, "delay_s": 0.5, "timeout_s": 15, "max_external_checks": 60, "max_image_checks": 80,
            "title_len": (30, 60), "meta_len": (70, 160), "max_depth_ok": 3, "min_text_words": 60,
            "heavy_image_kb": 300}
DOWNLOAD_EXT = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|zip|csv|jpe?g|png|gif|webp|svg|mp4|mp3)(\?|$)", re.I)
SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _norm(url: str) -> str:
    u, _ = urldefrag(url)
    p = urlparse(u)
    path = p.path or "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query else "")


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ɏ]{2,}", text or ""))


def analyze_page(html: str, url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    head = soup.head or soup
    title = (soup.title.get_text(strip=True) if soup.title else "") or ""
    meta = head.find("meta", attrs={"name": re.compile("^description$", re.I)})
    desc = (meta.get("content") or "").strip() if meta else ""
    canon = head.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, list) else [v]))
    robots = head.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    viewport = head.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
    hreflang = [l.get("hreflang") for l in head.find_all("link", hreflang=True)]
    ld_types: List[str] = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except ValueError:
            ld_types.append("INVALID")
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data if isinstance(data, list) else []
        for it in items:
            t = it.get("@type") if isinstance(it, dict) else None
            ld_types += t if isinstance(t, list) else [t] if t else []
    scripts = soup.find_all("script")
    script_bytes = sum(len(s.string or "") for s in scripts) + 20000 * sum(1 for s in scripts if s.get("src"))
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    body_text = soup.body.get_text(" ", strip=True) if soup.body else soup.get_text(" ", strip=True)
    links, images = [], []
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        if h.startswith(("mailto:", "tel:", "javascript:", "#", "data:")) or "wa.me/" in h or "/cdn-cgi/" in h:
            continue
        links.append(_norm(urljoin(url, h)))
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src:
            images.append({"src": urljoin(url, src), "alt": img.get("alt"), "loading": (img.get("loading") or "").lower()})
    return {"url": url, "title": title, "meta_description": desc, "h1": [h.get_text(" ", strip=True) for h in soup.find_all("h1")],
            "canonical": urljoin(url, canon.get("href")) if canon and canon.get("href") else None,
            "robots_meta": (robots.get("content") or "").lower() if robots else "", "viewport": bool(viewport),
            "hreflang": hreflang, "schema_types": sorted({t for t in ld_types if t}), "words": _words(body_text),
            "script_bytes": script_bytes, "links": sorted(set(links)), "images": images}


def page_issues(p: Dict[str, Any], cfg=DEFAULTS) -> List[Dict[str, Any]]:
    out, url = [], p["url"]

    def add(code, sev, detail, fix):
        out.append({"code": code, "severity": sev, "url": url, "detail": detail, "fix": fix})

    tl, ml = cfg["title_len"], cfg["meta_len"]
    if not p["title"]:
        add("title_missing", "high", "no <title>", "add a unique 30-60 character title with the main service + brand")
    elif not tl[0] <= len(p["title"]) <= tl[1]:
        add("title_length", "low", f"title is {len(p['title'])} chars", f"keep titles {tl[0]}-{tl[1]} characters")
    if not p["meta_description"]:
        add("meta_missing", "medium", "no meta description", "add a 70-160 character description that sells the click")
    elif not ml[0] <= len(p["meta_description"]) <= ml[1]:
        add("meta_length", "low", f"meta description is {len(p['meta_description'])} chars", f"keep {ml[0]}-{ml[1]} characters")
    if not p["h1"]:
        add("h1_missing", "medium", "no <h1>", "one <h1> naming the page's topic")
    elif len(p["h1"]) > 1:
        add("h1_multiple", "low", f"{len(p['h1'])} <h1> tags", "keep one <h1>; use <h2> for sections")
    if not p["canonical"]:
        add("canonical_missing", "low", "no canonical link", "add <link rel=canonical> to the page's own URL")
    elif _norm(p["canonical"]) != _norm(url) and urlparse(p["canonical"]).path != urlparse(url).path:
        add("canonical_other", "medium", f"canonical points to {p['canonical']}", "check the canonical is intended")
    if "noindex" in p["robots_meta"]:
        add("noindex", "high", "meta robots noindex", "remove noindex unless the page should stay out of Google")
    if not p["viewport"]:
        add("viewport_missing", "high", "no mobile viewport meta", '<meta name="viewport" content="width=device-width, initial-scale=1">')
    if p["words"] < cfg["min_text_words"] and p["script_bytes"] > 5000:
        add("js_only_content", "high", f"only {p['words']} words in the HTML; content is built by JavaScript",
            "put the main text in the HTML (pre-render) so search engines can read it")
    missing_alt = [i["src"] for i in p["images"] if not (i.get("alt") or "").strip()]
    if missing_alt:
        add("img_alt_missing", "low", f"{len(missing_alt)} image(s) without alt text", "describe each image in alt=\"…\"")
    if len(p["images"]) > 2 and not any(i["loading"] == "lazy" for i in p["images"][2:]):
        add("img_no_lazy", "low", "below-the-fold images load eagerly", 'add loading="lazy" to images below the fold')
    return out


def site_issues(pages: Dict[str, Dict[str, Any]], depth: Dict[str, int], sitemap_urls: List[str],
                robots_txt: Optional[str], cfg=DEFAULTS) -> List[Dict[str, Any]]:
    out = []

    def add(code, sev, url, detail, fix):
        out.append({"code": code, "severity": sev, "url": url, "detail": detail, "fix": fix})

    ok = {u: p for u, p in pages.items() if p.get("status") == 200}
    same_page = lambda us: len({re.sub(r"/index\.html?$", "/", u) for u in us}) == 1
    for u in ok:
        if re.search(r"/index\.html?$", u) and re.sub(r"/index\.html?$", "/", u) in ok:
            add("index_html_duplicate", "low", u, f"{u} and {re.sub(r'/index[.]html?$', '/', u)} serve the same page",
                "link to the folder URL (/) everywhere and set a canonical on index.html")
    for field, code in (("title", "title_duplicate"), ("meta_description", "meta_duplicate")):
        seen: Dict[str, List[str]] = {}
        for u, p in ok.items():
            if p.get(field):
                seen.setdefault(p[field].strip().lower(), []).append(u)
        for v, us in seen.items():
            if len(us) > 1 and not same_page(us):
                add(code, "medium", us[0], f"{len(us)} pages share this {field.replace('_', ' ')}: {', '.join(us[:5])}",
                    "make each page's title / description unique")
    for u, p in pages.items():
        st = p.get("status")
        if isinstance(st, int) and st >= 400:
            add("broken_page", "high", u, f"HTTP {st}; linked from {', '.join(p.get('linked_from', [])[:3])}",
                "fix or remove the link, or redirect the URL")
        if st == "redirect" and p.get("linked_from"):
            add("internal_redirect", "low", u, f"links to {u} redirect to {p['target']} (from {', '.join(p['linked_from'][:3])})",
                "link straight to the final URL")
    for u, d in depth.items():
        if d > cfg["max_depth_ok"] and u in ok:
            add("deep_page", "low", u, f"{d} clicks from the home page", "link it from a menu or a hub page")
    linked = {l for p in ok.values() for l in p.get("links", [])}
    linked |= {p["target"] for u, p in pages.items() if p.get("status") == "redirect" and u in linked}
    for u in sitemap_urls:
        if _norm(u) not in linked and urlparse(u).path not in ("", "/"):
            add("orphan_page", "medium", u, "in the sitemap but no crawlable <a href> links to it "
                "(menus built by JavaScript are not followed by every search engine)",
                "link it with a plain <a href> from the menu or a related page")
    if robots_txt is None:
        add("robots_missing", "medium", "/robots.txt", "no robots.txt", "add robots.txt with a Sitemap: line")
    elif "sitemap:" not in robots_txt.lower():
        add("robots_no_sitemap", "low", "/robots.txt", "robots.txt has no Sitemap: line", "add Sitemap: https://<site>/sitemap.xml")
    if not sitemap_urls:
        add("sitemap_missing", "high", "/sitemap.xml", "no sitemap.xml (or it is empty / invalid)",
            "add sitemap.xml listing every page; submit it in Search Console")
    crawled = set(ok)
    missing = [u for u in crawled if u not in {_norm(x) for x in sitemap_urls}]
    if sitemap_urls and missing:
        add("sitemap_incomplete", "low", "/sitemap.xml", f"{len(missing)} crawled pages not in the sitemap: {', '.join(sorted(missing)[:5])}",
            "add them to sitemap.xml")
    home = next((p for u, p in ok.items() if urlparse(u).path in ("", "/")), None)
    if home is not None and "Organization" not in home.get("schema_types", []):
        add("schema_org_missing", "medium", home["url"], "home page has no Organization structured data",
            "add JSON-LD Organization (name, url, logo, sameAs, contactPoint)")
    if ok and not any(t in p.get("schema_types", []) for p in ok.values() for t in ("Service", "FAQPage")):
        add("schema_service_missing", "low", "site", "no Service or FAQPage structured data on any page",
            "add Service JSON-LD on service pages, FAQPage where there are FAQs")
    return out


def _robots_disallows(txt: str) -> List[str]:
    rules, applies = [], False
    for line in (txt or "").splitlines():
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            applies = v == "*" or "torpedo" in v.lower()
        elif k == "disallow" and applies and v:
            rules.append(v)
    return rules


def _sitemap_urls(fetch, base: str, robots_txt: Optional[str]) -> List[str]:
    locs = [l.split(":", 1)[1].strip() for l in (robots_txt or "").splitlines() if l.lower().startswith("sitemap:")]
    todo, urls, seen = deque(locs or [urljoin(base, "/sitemap.xml")]), [], set()
    while todo and len(seen) < 10:
        sm = todo.popleft()
        if sm in seen:
            continue
        seen.add(sm)
        st, body, _ = fetch(sm)
        if st != 200 or not body:
            continue
        found = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
        if "<sitemapindex" in body:
            todo.extend(found)
        else:
            urls += found
    return urls


def crawl(domain: str, fetch: Callable[[str], Tuple[Optional[int], str, List[str]]], cfg=DEFAULTS,
          head: Optional[Callable[[str], Tuple[Optional[int], Optional[int]]]] = None) -> Dict[str, Any]:
    """fetch(url) -> (status, html, redirect_chain); head(url) -> (status, bytes)."""
    base = f"https://{domain}/"
    st, robots_txt, _ = fetch(urljoin(base, "/robots.txt"))
    if st is None or (isinstance(st, int) and st >= 429):        # throttled / timed out: one retry before "missing"
        time.sleep(max(cfg["delay_s"], 2))
        st, robots_txt, _ = fetch(urljoin(base, "/robots.txt"))
    robots_txt = robots_txt if st == 200 else None
    disallow = _robots_disallows(robots_txt or "")
    sitemap = _sitemap_urls(fetch, base, robots_txt)
    hosts = {domain, f"www.{domain}", domain.removeprefix("www.")}
    pages: Dict[str, Dict[str, Any]] = {}
    depth = {_norm(base): 0}
    q = deque([_norm(base)] + [_norm(u) for u in sitemap if urlparse(u).hostname in hosts])
    for u in list(q)[1:]:
        depth.setdefault(u, 99)
    externals: Dict[str, List[str]] = {}
    while q and len(pages) < cfg["max_pages"]:
        url = q.popleft()
        if url in pages or any(urlparse(url).path.startswith(d) for d in disallow) or DOWNLOAD_EXT.search(url):
            continue
        status, html, chain = fetch(url)
        final = _norm(chain[-1]) if chain else url
        if final != url:
            # one record per real page: the redirecting URL is kept only as a redirect
            pages[url] = {"url": url, "status": "redirect", "target": final, "redirects": chain, "linked_from": []}
            if final in pages or urlparse(final).hostname not in hosts:
                continue
            depth.setdefault(final, depth.get(url, 0))
            url, chain = final, []
        rec: Dict[str, Any] = {"url": url, "status": status, "redirects": chain, "linked_from": []}
        if status == 200 and html:
            rec.update(analyze_page(html, url))
            for l in rec["links"]:
                h = urlparse(l).hostname
                if h in hosts:
                    if l not in depth or depth[l] > depth.get(url, 0) + 1:
                        depth[l] = depth.get(url, 0) + 1
                    if l not in pages:
                        q.append(l)
                elif h:
                    externals.setdefault(l, []).append(url)
        pages[url] = rec
        time.sleep(cfg["delay_s"])
    for u, p in pages.items():
        for l in p.get("links", []):
            if l in pages:
                pages[l]["linked_from"].append(u)
    issues = [i for p in pages.values() if p.get("status") == 200 for i in page_issues(p, cfg)]
    issues += site_issues(pages, {u: d for u, d in depth.items() if d < 99}, sitemap, robots_txt, cfg)
    if head:
        for ext, src in list(externals.items())[:cfg["max_external_checks"]]:
            s, _ = head(ext)
            if s is not None and s >= 400 and s not in (401, 403, 429, 999):
                issues.append({"code": "broken_external", "severity": "medium", "url": src[0],
                               "detail": f"{ext} returns {s}", "fix": "update or remove the link"})
        imgs = {i["src"]: p["url"] for p in pages.values() for i in p.get("images", [])}
        for src, page in list(imgs.items())[:cfg["max_image_checks"]]:
            s, size = head(src)
            if size and size > cfg["heavy_image_kb"] * 1024:
                issues.append({"code": "img_heavy", "severity": "medium", "url": page,
                               "detail": f"{src} is {size // 1024} KB", "fix": "compress and serve as WebP (fix package)"})
            elif src.lower().split("?")[0].endswith((".png", ".jpg", ".jpeg")) and size and size > 100 * 1024:
                issues.append({"code": "img_not_webp", "severity": "low", "url": page,
                               "detail": f"{src} ({size // 1024} KB) could be WebP", "fix": "offer a WebP version"})
    issues.sort(key=lambda i: (SEV[i["severity"]], i["code"], i["url"]))
    return {"domain": domain, "pages": pages, "sitemap_urls": sitemap, "robots_txt": robots_txt is not None,
            "issues": issues}


def _http(cfg=DEFAULTS):
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = UA

    def fetch(url):
        try:
            r = s.get(url, timeout=cfg["timeout_s"], allow_redirects=True)
            chain = [h.url for h in r.history] + ([r.url] if r.history else [])
            ctype = r.headers.get("content-type", "")
            body = r.text if ("html" in ctype or "xml" in ctype or "text" in ctype) else ""
            return r.status_code, body, chain
        except Exception:
            return None, "", []

    def head(url):
        try:
            r = s.head(url, timeout=cfg["timeout_s"], allow_redirects=True)
            if r.status_code in (405, 501):
                r = s.get(url, timeout=cfg["timeout_s"], stream=True)
                r.close()
            n = r.headers.get("content-length")
            return r.status_code, int(n) if n and n.isdigit() else None
        except Exception:
            return None, None
    return fetch, head


def issue_key(site: str, i: Dict[str, Any]) -> str:
    return hashlib.sha1(f"{site}|{i['code']}|{i['url']}|{i['detail'][:80] if i['code'].startswith(('broken', 'img_')) else ''}"
                        .encode()).hexdigest()


def run(gd: Optional[Callable] = None, *, apply: bool = True, sites: Optional[List[Dict[str, Any]]] = None,
        now: Optional[datetime] = None, fetchers=None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    if sites is None:
        from platform_core import config_store
        sites = config_store.get("web").get("sites") or []
    now = now or datetime.utcnow()
    fetch, head = fetchers or _http()
    ea = gd(schema.DB)
    rep = {}
    for s in sites:
        t0 = time.time()
        res = crawl(s["domain"], fetch, head=head)
        sev: Dict[str, int] = {}
        for i in res["issues"]:
            sev[i["severity"]] = sev.get(i["severity"], 0) + 1
        summary = {"site": s["domain"], "pages": len(res["pages"]), "ok_pages": sum(1 for p in res["pages"].values() if p.get("status") == 200),
                   "issues": len(res["issues"]), "by_severity": sev, "sitemap_urls": len(res["sitemap_urls"]),
                   "robots_txt": res["robots_txt"], "secs": round(time.time() - t0, 1)}
        rep[s["domain"]] = summary
        if not apply:
            continue
        audit = schema.stamp({**summary, "started_at": now,
                              "page_rows": [{k: p.get(k) for k in ("url", "status", "title", "meta_description", "h1", "words",
                                                                   "schema_types", "canonical")} for p in res["pages"].values()]},
                             bu=s.get("bu"), source="seo_crawler", now=now)
        aid = ea["seo_audits"].insert_one(audit).inserted_id
        keys = set()
        for i in res["issues"]:
            k = issue_key(s["domain"], i)
            keys.add(k)
            ea["seo_issues"].update_one(
                {"key": k},
                {"$set": {**i, "site": s["domain"], "bu": s.get("bu"), "source": "seo_crawler", "status": "open",
                          "audit_id": aid, "last_seen": now, "updated_at": now},
                 "$setOnInsert": {"first_seen": now, "created_at": now}}, upsert=True)
        ea["seo_issues"].update_many({"site": s["domain"], "status": "open", "key": {"$nin": sorted(keys)}},
                                     {"$set": {"status": "fixed", "fixed_at": now, "updated_at": now}})
    return rep


# ------------------------------------------------------------------ PageSpeed (3.3.3)
PSI = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def pagespeed(url: str, strategy: str, key: Optional[str] = None, get=None) -> Dict[str, Any]:
    if get is None:
        import requests
        get = requests.get
    params = {"url": url, "strategy": strategy, "category": "performance"}
    if key:
        params["key"] = key
    r = get(PSI, params=params, timeout=90)
    data = r.json() if hasattr(r, "json") else r
    if getattr(r, "status_code", 200) != 200:
        raise RuntimeError(f"PageSpeed {getattr(r, 'status_code', '?')}: {str(data.get('error', {}).get('message', ''))[:200]}")
    lr = data.get("lighthouseResult", {})
    audits = lr.get("audits", {})
    field = (data.get("loadingExperience") or {}).get("metrics") or {}

    def fp(k):
        m = field.get(k) or {}
        return {"p75": m.get("percentile"), "category": m.get("category")} if m else None
    return {"url": url, "strategy": strategy,
            "score": round(100 * (lr.get("categories", {}).get("performance", {}).get("score") or 0)),
            "lab": {"lcp_ms": audits.get("largest-contentful-paint", {}).get("numericValue"),
                    "cls": audits.get("cumulative-layout-shift", {}).get("numericValue"),
                    "tbt_ms": audits.get("total-blocking-time", {}).get("numericValue")},
            "field": {"lcp": fp("LARGEST_CONTENTFUL_PAINT_MS"), "inp": fp("INTERACTION_TO_NEXT_PAINT"),
                      "cls": fp("CUMULATIVE_LAYOUT_SHIFT_SCORE")},
            "field_overall": (data.get("loadingExperience") or {}).get("overall_category")}


def pagespeed_run(gd: Optional[Callable] = None, *, now: Optional[datetime] = None, get=None) -> Dict[str, Any]:
    """Key pages per site (Integrations > PageSpeed 'urls' setting, else each site's home page), mobile + desktop."""
    if gd is None:
        from database import get_database as gd
    from marketing import credentials
    from platform_core import config_store
    now = now or datetime.utcnow()
    try:
        cred = credentials.secrets("pagespeed", gd)
    except Exception:
        cred = {"settings": {}}
    sites = config_store.get("web").get("sites") or []
    urls = cred.get("settings", {}).get("urls") or [f"https://{s['domain']}/" for s in sites]
    bu_of = {s["domain"]: s.get("bu") for s in sites}
    ea, out = gd(schema.DB), {"ok": 0, "errors": []}
    for u in urls:
        for strat in ("mobile", "desktop"):
            try:
                res = pagespeed(u, strat, cred.get("api_key"), get=get)
            except Exception as e:
                out["errors"].append(f"{u} {strat}: {str(e)[:120]}")
                continue
            host = (urlparse(u).hostname or "").removeprefix("www.")
            doc = schema.stamp({**res, "date": now.strftime("%Y-%m-%d"), "site": host}, bu=bu_of.get(host), source="pagespeed", now=now)
            ea["cwv_results"].update_one({"url": u, "strategy": strat, "date": doc["date"]}, {"$set": doc}, upsert=True)
            out["ok"] += 1
    try:
        credentials.mark("pagespeed", ok=not out["errors"], error="; ".join(out["errors"])[:300] or None, gd=gd)
    except Exception:
        pass
    return out
