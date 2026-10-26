"""SEO planning (MARKETING_PLAN 3.3.4-3.3.6): keywords + positions, opportunities, content gaps, fix plans and packages.

keywords         Claude's starting list per BU (status proposed; the owner approves / edits), topped up with the
                 BU's highest-impression Search Console queries. Positions for the top 50 per BU come from
                 gsc_queries_daily (impression-weighted), daily -> keyword_positions.
opportunities    queries with impressions >= N at position 8-20, or position < 8 with CTR under the floor.
content_gaps     services without a page, queries ranking with an unrelated page, client questions (anonymised),
                 competitors' topics (config marketing.competitors) -> content_gaps (feeds D8 and the calendar).
fix plans        per site, the concrete change for each crawl issue (new title / meta / canonical / schema /
                 robots / sitemap) with reason and expected effect -> seo_fix_plans.
apply_package    applies a fix plan to a COPY of the site's files (the owner's zip) and writes a zip of only the
                 changed files + CHANGES.md + rollback note. Never touches the live site.
"""
import html
import json
import os
import re
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from marketing import schema

SEED_KEYWORDS = {
    "SFW": ["online survey panel india", "market research fieldwork india", "cati services india", "cawi survey india",
            "b2b sample provider india", "panel company india", "survey programming services", "healthcare panel india",
            "data collection agency india", "consumer panel india", "online sample provider", "f2f fieldwork india"],
    "COGENTIX": ["market research company india", "consumer insights agency india", "brand health tracking", "mystery shopping india",
                 "customer satisfaction survey india", "ux research india", "qualitative research india", "usage and attitude study",
                 "esg consumer research", "fmcg market research india", "concept testing", "nps survey india"],
    "BIM": ["bim services india", "scan to bim services", "bim modeling services", "revit modeling services", "mep coordination services",
            "clash detection services", "bim outsourcing india", "cad to bim conversion", "lod 400 bim", "point cloud to bim",
            "bim for hospitals", "4d bim scheduling"],
}
SERVICES = {   # what each BU sells, for the "service without a page" check
    "SFW": ["cati", "cawi", "online panel", "b2b sample", "healthcare panel", "survey programming", "face to face", "data processing"],
    "COGENTIX": ["brand health", "mystery shopping", "customer satisfaction", "ux research", "qualitative", "concept testing", "esg"],
    "BIM": ["scan to bim", "revit", "mep coordination", "clash detection", "cad to bim", "point cloud", "4d", "family creation"],
}
_PII = [re.compile(p) for p in (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", r"\+?\d[\d\s-]{8,}\d", r"https?://\S+")]


def seed_keywords(gd: Callable, now: Optional[datetime] = None) -> int:
    now = now or datetime.utcnow()
    col, n = gd(schema.DB)["keywords"], 0
    for bu, kws in SEED_KEYWORDS.items():
        for k in kws:
            if not col.find_one({"bu": bu, "keyword": k}):
                col.insert_one(schema.stamp({"keyword": k, "status": "proposed", "origin": "claude_seed"}, bu=bu, source="seo_plan", now=now))
                n += 1
    return n


def _queries(ea, since: str) -> Dict[tuple, Dict[str, float]]:
    agg: Dict[tuple, Dict[str, float]] = defaultdict(lambda: {"impressions": 0.0, "clicks": 0.0, "pos_x_impr": 0.0})
    for r in ea["gsc_queries_daily"].find({"date": {"$gte": since}}, {"bu": 1, "query": 1, "page": 1, "impressions": 1, "clicks": 1, "position": 1}):
        a = agg[(r.get("bu"), r["query"].lower())]
        i = float(r.get("impressions") or 0)
        a["impressions"] += i
        a["clicks"] += float(r.get("clicks") or 0)
        a["pos_x_impr"] += float(r.get("position") or 0) * i
        a.setdefault("pages", set()).add(r.get("page"))
    return agg


def track_positions(gd: Callable, *, now: Optional[datetime] = None, top_n: int = 50, add_top_queries: int = 15) -> Dict[str, Any]:
    """Daily: impression-weighted position for each tracked keyword (approved first, then proposed, then the BU's
    biggest GSC queries) over the last 7 days."""
    now = now or datetime.utcnow()
    ea = gd(schema.DB)
    seed_keywords(gd, now)
    agg = _queries(ea, (now - timedelta(days=7)).strftime("%Y-%m-%d"))
    col = ea["keywords"]
    for bu in schema.BUS:
        have = {k["keyword"] for k in col.find({"bu": bu})}
        top = sorted(((q, a) for (b, q), a in agg.items() if b == bu and q not in have), key=lambda x: -x[1]["impressions"])[:add_top_queries]
        for q, _ in top:
            col.insert_one(schema.stamp({"keyword": q, "status": "proposed", "origin": "gsc_top_query"}, bu=bu, source="seo_plan", now=now))
    day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = 0
    for bu in schema.BUS:
        kws = sorted(col.find({"bu": bu, "status": {"$in": ["approved", "proposed"]}}), key=lambda k: (k["status"] != "approved",))[:top_n]
        for k in kws:
            a = agg.get((bu, k["keyword"]))
            doc = {"keyword_id": str(k["_id"]), "keyword": k["keyword"], "date": day,
                   "impressions": a["impressions"] if a else 0, "clicks": a["clicks"] if a else 0,
                   "position": round(a["pos_x_impr"] / a["impressions"], 1) if a and a["impressions"] else None}
            f, u = schema.upsert_ops(doc, ["keyword_id", "date"], bu=bu, source="gsc", now=now)
            ea["keyword_positions"].update_one(f, u, upsert=True)
            rows += 1
    return {"positions": rows}


def opportunities(gd: Callable, *, now: Optional[datetime] = None, min_impr: int = 100, low_ctr: float = 0.02) -> List[Dict[str, Any]]:
    now = now or datetime.utcnow()
    out = []
    for (bu, q), a in _queries(gd(schema.DB), (now - timedelta(days=28)).strftime("%Y-%m-%d")).items():
        if a["impressions"] < min_impr:
            continue
        pos = a["pos_x_impr"] / a["impressions"]
        ctr = a["clicks"] / a["impressions"]
        if 8 <= pos <= 20 or (pos < 8 and ctr < low_ctr):
            out.append({"bu": bu, "query": q, "impressions": int(a["impressions"]), "clicks": int(a["clicks"]), "position": round(pos, 1),
                        "ctr": round(ctr, 4), "why": "page 2 (8-20): small gains move it to page 1" if pos >= 8 else "ranks well but few click: rewrite title / meta"})
    return sorted(out, key=lambda o: -o["impressions"])


def anonymise(text: str) -> str:
    t = text or ""
    for p in _PII:
        t = p.sub("…", t)
    return re.sub(r"\s+", " ", t).strip()


def content_gaps(gd: Callable, *, now: Optional[datetime] = None, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    now = now or datetime.utcnow()
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    ea = gd(schema.DB)
    sites = {}
    for a in ea["seo_audits"].find({}).sort("started_at", -1):
        sites.setdefault(a.get("bu"), a)
    found: List[Dict[str, Any]] = []
    for bu, svcs in SERVICES.items():
        audit = sites.get(bu) or {}
        text = " ".join(" ".join(str(p.get(k) or "") for k in ("url", "title", "h1")) for p in audit.get("page_rows") or []).lower()
        if not text:
            continue
        for s in svcs:
            if s not in text:
                found.append({"bu": bu, "kind": "service_without_page", "topic": s,
                              "suggestion": f"A dedicated page for '{s}' (what, how, timelines, FAQ, CTA)"})
    for (bu, q), a in _queries(ea, (now - timedelta(days=28)).strftime("%Y-%m-%d")).items():
        if a["impressions"] < 100 or not bu:
            continue
        words = [w for w in re.findall(r"[a-z0-9]{3,}", q) if w not in ("india", "services", "company", "agency")]
        if words and not any(any(w in (p or "").lower() for w in words) for p in a.get("pages") or []):
            found.append({"bu": bu, "kind": "query_without_matching_page", "topic": q, "impressions": int(a["impressions"]),
                          "suggestion": f"Ranks for '{q}' with an unrelated page: write a page / article answering it"})
    for it in ea["inbox_items"].find({"category": {"$in": ["positive", "rfq", "support"]}, "at": {"$gte": now - timedelta(days=180)}}).limit(500):
        for sent in re.split(r"(?<=[?])\s+", it.get("text") or ""):
            if sent.strip().endswith("?") and 15 <= len(sent) <= 200:
                found.append({"bu": it.get("bu"), "kind": "client_question", "topic": anonymise(sent),
                              "suggestion": "Answer it in an FAQ (FAQPage schema) or a short article"})
    for bu, comps in (cfg.get("competitors") or {}).items():
        for c in comps or []:
            found.append({"bu": bu, "kind": "competitor", "topic": c if isinstance(c, str) else c.get("name"),
                          "suggestion": "Review their service pages and blog topics we do not cover"})
    col, n = ea["content_gaps"], 0
    for g in found:
        if g.get("bu") not in schema.BUS:
            continue
        if col.find_one({"bu": g["bu"], "kind": g["kind"], "topic": g["topic"]}):
            continue
        col.insert_one(schema.stamp({**g, "status": "open"}, bu=g["bu"], source="seo_plan", now=now))
        n += 1
    return {"new_gaps": n}


# ------------------------------------------------------------------ fix plans (3.3.6)
BRAND = {"SFW": "Survey Fieldwork", "COGENTIX": "Cogentix Research", "BIM": "BIM Wave Solutions"}


def _title(page: Dict[str, Any], bu: str) -> str:
    base = ((page.get("h1") or [None])[0] or page.get("title") or "").strip()
    brand = BRAND.get(bu, "")
    base = re.sub(r"\s*[|–-]\s*" + re.escape(brand) + r".*$", "", base, flags=re.I)
    squash = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())
    # "About BIMwave Solutions" already names the brand: no " | BIM Wave Solutions" suffix
    t = base if brand and squash(brand) in squash(base) else f"{base} | {brand}".strip(" |")
    if len(t) <= 60:
        return t
    # too long with the brand: the heading alone, cut at a word (no "…" in a search result)
    cut = base if len(base) <= 60 else base[:60].rsplit(" ", 1)[0]
    return cut.rstrip(" ,:;-–|")


def fix_plan(gd: Callable, site: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Concrete changes for the open crawl issues of one site; each with the reason and expected effect."""
    now = now or datetime.utcnow()
    ea = gd(schema.DB)
    audit = ea["seo_audits"].find_one({"site": site}, sort=[("started_at", -1)]) or {}
    bu = audit.get("bu")
    pages = {p["url"]: p for p in audit.get("page_rows") or []}
    changes: List[Dict[str, Any]] = []
    for i in ea["seo_issues"].find({"site": site, "status": "open"}):
        p, url = pages.get(i["url"], {}), i["url"]
        c = None
        if i["code"] in ("title_missing", "title_length", "title_duplicate"):
            c = {"type": "title", "value": _title(p, bu), "reason": i["detail"], "effect": "a unique, complete title in Google results (CTR)"}
        elif i["code"] in ("meta_missing", "meta_length", "meta_duplicate"):
            c = {"type": "meta_description", "value": None, "reason": i["detail"],
                 "effect": "a description Google can show; write 70-160 chars per page (Qwen drafts it in the content calendar)"}
        elif i["code"] == "canonical_missing":
            c = {"type": "canonical", "value": url, "reason": i["detail"], "effect": "one URL per page; no duplicate-content split"}
        elif i["code"] == "schema_org_missing":
            c = {"type": "jsonld", "value": {"@context": "https://schema.org", "@type": "Organization", "name": BRAND.get(bu, site),
                                             "url": f"https://{site}/"}, "reason": i["detail"], "effect": "brand panel / sitelinks eligibility"}
        elif i["code"] in ("robots_missing", "robots_no_sitemap"):
            c = {"type": "robots_txt", "value": f"User-agent: *\nAllow: /\nSitemap: https://{site}/sitemap.xml\n", "reason": i["detail"],
                 "effect": "crawlers find the sitemap"}
        elif i["code"] in ("sitemap_missing", "sitemap_incomplete"):
            c = {"type": "sitemap_xml", "value": sorted(u for u, pg in pages.items() if pg.get("status") == 200), "reason": i["detail"],
                 "effect": "every page submitted for indexing"}
        elif i["code"] == "img_no_lazy":
            c = {"type": "img_lazy", "value": None, "reason": i["detail"], "effect": "faster LCP on mobile"}
        elif i["code"] == "img_alt_missing":
            c = {"type": "img_alt", "value": None, "reason": i["detail"], "effect": "image search + accessibility"}
        elif i["code"] == "viewport_missing":
            c = {"type": "viewport", "value": "width=device-width, initial-scale=1", "reason": i["detail"], "effect": "mobile-friendly"}
        if c:
            changes.append({"url": url, "issue": i["code"], **c})
    seen, uniq = set(), []
    for c in changes:
        k = (c["url"] if c["type"] not in ("robots_txt", "sitemap_xml") else "site", c["type"])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    plan = {"site": site, "bu": bu, "changes": uniq, "built_at": now, "audit_at": audit.get("started_at")}
    ea["seo_fix_plans"].update_one({"site": site}, {"$set": schema.stamp(plan, bu=bu if bu in schema.BUS else None, source="seo_plan", now=now)},
                                   upsert=True)
    return plan


def _file_for(root: str, url: str) -> Optional[str]:
    path = urlparse(url).path.lstrip("/") or "index.html"
    if path.endswith("/"):
        path += "index.html"
    cand = [path, path + ".html", os.path.join(path, "index.html")]
    return next((os.path.join(root, c) for c in cand if os.path.isfile(os.path.join(root, c))), None)


def _set_head(htm: str, tag_re: str, new_tag: str) -> str:
    if re.search(tag_re, htm, re.I | re.S):
        return re.sub(tag_re, new_tag.replace("\\", "\\\\"), htm, count=1, flags=re.I | re.S)
    return re.sub(r"</head>", new_tag + "\n</head>", htm, count=1, flags=re.I)


def apply_package(plan: Dict[str, Any], site_root: str, out_dir: str) -> Dict[str, Any]:
    """Apply a fix plan to a COPY of the site (site_root is the unzipped owner upload) -> out_dir/<site>-SEO-fix.zip
    with only changed files, CHANGES.md (every change, reason, effect) and ROLLBACK.md."""
    work = os.path.join(out_dir, "work")
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(site_root, work)
    changed, log = set(), []
    for c in plan["changes"]:
        if c["type"] == "robots_txt":
            open(os.path.join(work, "robots.txt"), "w", encoding="utf-8").write(c["value"])
            changed.add("robots.txt"); log.append(c); continue
        if c["type"] == "sitemap_xml":
            body = "".join(f"  <url><loc>{html.escape(u)}</loc></url>\n" for u in c["value"])
            open(os.path.join(work, "sitemap.xml"), "w", encoding="utf-8").write(
                f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n')
            changed.add("sitemap.xml"); log.append(c); continue
        f = _file_for(work, c["url"])
        if not f or c.get("value") is None:
            if c.get("value") is None:
                log.append({**c, "note": "needs written copy / per-image text: listed, not auto-applied"})
            continue
        htm = open(f, encoding="utf-8", errors="replace").read()
        new = htm
        if c["type"] == "title":
            new = _set_head(htm, r"<title>.*?</title>", f"<title>{html.escape(c['value'])}</title>")
        elif c["type"] == "canonical":
            new = _set_head(htm, r"<link[^>]+rel=[\"']canonical[\"'][^>]*>", f'<link rel="canonical" href="{html.escape(c["value"])}">')
        elif c["type"] == "viewport":
            new = _set_head(htm, r"<meta[^>]+name=[\"']viewport[\"'][^>]*>", f'<meta name="viewport" content="{c["value"]}">')
        elif c["type"] == "jsonld" and '"Organization"' not in htm:
            new = re.sub(r"</head>", f'<script type="application/ld+json">{json.dumps(c["value"])}</script>\n</head>', htm, count=1, flags=re.I)
        if new != htm:
            open(f, "w", encoding="utf-8").write(new)
            changed.add(os.path.relpath(f, work).replace("\\", "/"))
            log.append(c)
    zpath = os.path.join(out_dir, f"{plan['site']}-SEO-fix-changed-files.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(changed):
            z.write(os.path.join(work, rel), rel)
        z.writestr("CHANGES.md", "# SEO fix package — " + plan["site"] + "\n\n" + "\n".join(
            f"- **{c['type']}** {c['url']}: {c.get('note') or ('→ ' + str(c['value'])[:120])}  \n  reason: {c['reason']}; expected: {c['effect']}"
            for c in log) + "\n")
        z.writestr("ROLLBACK.md", "Upload the backup of each listed file from the original zip (same paths) to undo.\n"
                                  "Files changed:\n" + "\n".join(f"- {r}" for r in sorted(changed)) + "\n")
    shutil.rmtree(work, ignore_errors=True)
    return {"zip": zpath, "files_changed": sorted(changed), "changes": len(log)}
