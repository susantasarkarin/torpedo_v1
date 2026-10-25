"""Search Console + GA4 daily import (MARKETING_PLAN 3.3.1, 3.2.2). Read-only APIs.

Credentials: Integrations > "Google service account" (service_account_json
secret; settings gsc_sites = {"SFW": "sc-domain:surveyfieldwork.com", ...},
ga4_property_ids = {"COGENTIX": ["123", "456"], ...}). Until they are entered
the job is a no-op that says so.

Search Console data lags 2-3 days, so each run re-reads the last `days`
(default 5) and upserts: idempotent. Written:
  gsc_queries_daily  date x query x page x country x device
  gsc_pages_daily    date x page
  gsc_sitemaps       latest status per sitemap (errors / warnings / submitted)
  gsc_url_index      URL Inspection verdict for each sitemap URL (weekly, capped)
  ga4_daily          date x channel group x source/medium x device x country
Not available from any Google API: the Page indexing (coverage) report as a
whole, and Manual actions -- the URL Inspection rows stand in for the first;
the second stays a manual check (runbook).
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from marketing import credentials, schema

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly", "https://www.googleapis.com/auth/analytics.readonly"]
GSC = "https://searchconsole.googleapis.com/webmasters/v3"
INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
GA4 = "https://analyticsdata.googleapis.com/v1beta"
ROW_LIMIT = 25000
GA4_DIMS = ["date", "sessionDefaultChannelGroup", "sessionSource", "sessionMedium", "deviceCategory", "country"]
GA4_METRICS = ["sessions", "totalUsers", "newUsers", "engagedSessions", "averageSessionDuration", "screenPageViews", "keyEvents"]


class NotConfigured(RuntimeError):
    pass


def session_from_credentials(gd=None):
    """An authorised requests session for the service account (token refreshed by google-auth)."""
    cred = credentials.secrets("google_service_account", gd)
    raw = cred.get("service_account_json")
    if not raw:
        raise NotConfigured("Google service account not entered (Integrations)")
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    sa = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    return AuthorizedSession(sa), cred.get("settings") or {}


def _per_bu(setting) -> List[tuple]:
    """{"SFW": "x"} / {"COGENTIX": ["a", "b"]} / "x" -> [(bu, value)]."""
    if isinstance(setting, dict):
        return [(bu, v) for bu, vals in setting.items() for v in (vals if isinstance(vals, list) else [vals]) if v]
    if isinstance(setting, list):
        return [(None, v) for v in setting if v]
    return [(None, setting)] if setting else []


def _check(r):
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:
            msg = r.text[:200]
        raise RuntimeError(f"HTTP {r.status_code}: {msg[:200]}")
    return r.json()


def gsc_rows(http, site: str, start: str, end: str, dims: List[str]) -> List[Dict[str, Any]]:
    out, start_row = [], 0
    while True:
        body = {"startDate": start, "endDate": end, "dimensions": dims, "rowLimit": ROW_LIMIT, "startRow": start_row,
                "dataState": "all"}
        data = _check(http.post(f"{GSC}/sites/{quote(site, safe='')}/searchAnalytics/query", json=body, timeout=120))
        rows = data.get("rows") or []
        for r in rows:
            d = dict(zip(dims, r["keys"]))
            d.update(clicks=r.get("clicks", 0), impressions=r.get("impressions", 0), ctr=r.get("ctr", 0),
                     position=r.get("position", 0))
            out.append(d)
        if len(rows) < ROW_LIMIT:
            return out
        start_row += ROW_LIMIT


def ga4_rows(http, prop: str, start: str, end: str) -> List[Dict[str, Any]]:
    out, offset = [], 0
    while True:
        body = {"dateRanges": [{"startDate": start, "endDate": end}], "dimensions": [{"name": d} for d in GA4_DIMS],
                "metrics": [{"name": m} for m in GA4_METRICS], "limit": 100000, "offset": offset}
        data = _check(http.post(f"{GA4}/properties/{prop}:runReport", json=body, timeout=120))
        for r in data.get("rows") or []:
            d = {k: v["value"] for k, v in zip(GA4_DIMS, r["dimensionValues"])}
            d.update({k: float(v["value"]) for k, v in zip(GA4_METRICS, r["metricValues"])})
            d["date"] = f"{d['date'][:4]}-{d['date'][4:6]}-{d['date'][6:]}"
            out.append(d)
        offset += 100000
        if offset >= int(data.get("rowCount") or 0):
            return out


def _dims_key(d: Dict[str, Any], dims: List[str]) -> str:
    return hashlib.sha1("|".join(str(d.get(k)) for k in dims).encode()).hexdigest()


def run(gd: Optional[Callable] = None, *, days: int = 5, apply: bool = True, inspect: bool = False,
        now: Optional[datetime] = None, http=None, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from pymongo import UpdateOne
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    try:
        if http is None:
            http, settings = session_from_credentials(gd)
    except NotConfigured as e:
        return {"skipped": str(e)}
    settings = settings or {}
    end = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    ea = gd(schema.DB)
    rep: Dict[str, Any] = {"window": [start, end], "gsc": {}, "ga4": {}, "errors": []}

    for bu, site in _per_bu(settings.get("gsc_sites")):
        try:
            q = gsc_rows(http, site, start, end, ["date", "query", "page", "country", "device"])
            p = gsc_rows(http, site, start, end, ["date", "page"])
            ops = [UpdateOne(*schema.upsert_ops({**r, "site": site}, ["site", "date", "query", "page", "country", "device"],
                                                bu=bu, source="gsc", now=now), upsert=True) for r in q]
            pops = [UpdateOne(*schema.upsert_ops({**r, "site": site}, ["site", "date", "page"], bu=bu, source="gsc", now=now),
                              upsert=True) for r in p]
            sm = _check(http.get(f"{GSC}/sites/{quote(site, safe='')}/sitemaps", timeout=60)).get("sitemap") or []
            if apply:
                for i in range(0, len(ops), 2000):
                    ea["gsc_queries_daily"].bulk_write(ops[i:i + 2000], ordered=False)
                for i in range(0, len(pops), 2000):
                    ea["gsc_pages_daily"].bulk_write(pops[i:i + 2000], ordered=False)
                for s in sm:
                    ea["gsc_sitemaps"].update_one({"site": site, "path": s.get("path")}, {"$set": schema.stamp(
                        {"site": site, "path": s.get("path"), "last_submitted": s.get("lastSubmitted"),
                         "last_downloaded": s.get("lastDownloaded"), "errors": int(s.get("errors") or 0),
                         "warnings": int(s.get("warnings") or 0), "is_pending": s.get("isPending"),
                         "contents": s.get("contents")}, bu=bu, source="gsc", now=now, new=False)}, upsert=True)
            rep["gsc"][site] = {"query_rows": len(q), "page_rows": len(p), "sitemaps": len(sm),
                                "sitemap_errors": sum(int(s.get("errors") or 0) for s in sm)}
            if inspect:
                rep["gsc"][site]["inspected"] = _inspect(http, ea, site, bu, now, apply)
        except Exception as e:
            rep["errors"].append(f"gsc {site}: {str(e)[:200]}")

    for bu, prop in _per_bu(settings.get("ga4_property_ids")):
        try:
            rows = ga4_rows(http, str(prop), start, end)
            ops = [UpdateOne(*schema.upsert_ops({**r, "property_id": str(prop), "dims_key": _dims_key(r, GA4_DIMS)},
                                                ["property_id", "date", "dims_key"], bu=bu, source="ga4", now=now), upsert=True)
                   for r in rows]
            if apply and ops:
                ea["ga4_daily"].bulk_write(ops, ordered=False)
            rep["ga4"][str(prop)] = {"rows": len(rows), "sessions": int(sum(r["sessions"] for r in rows))}
        except Exception as e:
            rep["errors"].append(f"ga4 {prop}: {str(e)[:200]}")

    try:
        credentials.mark("google_service_account", ok=not rep["errors"], error="; ".join(rep["errors"])[:300] or None, gd=gd)
    except Exception:
        pass
    return rep


def _inspect(http, ea, site: str, bu, now, apply: bool, cap: int = 200) -> int:
    """URL Inspection for each page the latest crawl found (2,000/day/property quota; we use <= cap)."""
    domain = site.replace("sc-domain:", "").replace("https://", "").replace("http://", "").strip("/").removeprefix("www.")
    page_rows = ea["seo_audits"].find_one({"site": domain}, sort=[("started_at", -1)]) or {}
    urls = [p["url"] for p in page_rows.get("page_rows") or [] if p.get("status") == 200][:cap]
    n = 0
    for u in urls:
        data = _check(http.post(INSPECT, json={"inspectionUrl": u, "siteUrl": site}, timeout=60))
        res = (data.get("inspectionResult") or {}).get("indexStatusResult") or {}
        if apply:
            ea["gsc_url_index"].update_one({"url": u}, {"$set": schema.stamp(
                {"url": u, "site": site, "verdict": res.get("verdict"), "coverage": res.get("coverageState"),
                 "indexing": res.get("indexingState"), "last_crawl": res.get("lastCrawlTime"),
                 "google_canonical": res.get("googleCanonical"), "robots": res.get("robotsTxtState")},
                bu=bu, source="gsc_inspect", now=now, new=False)}, upsert=True)
        n += 1
    return n


def tracker_vs_ga4(gd: Optional[Callable] = None, *, days: int = 7, now: Optional[datetime] = None,
                   threshold: float = 0.2) -> List[Dict[str, Any]]:
    """3.2.2: per BU, sessions in GA4 vs consented tracker sessions; flag a gap > 20%."""
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    ea = gd(schema.DB)
    ga = {}
    for r in ea["ga4_daily"].aggregate([{"$match": {"date": {"$gte": since.strftime("%Y-%m-%d")}}},
                                        {"$group": {"_id": "$bu", "s": {"$sum": "$sessions"}}}]):
        ga[r["_id"]] = r["s"]
    tr = {}
    for r in ea["web_sessions"].aggregate([{"$match": {"started_at": {"$gte": since}}}, {"$group": {"_id": "$bu", "s": {"$sum": 1}}}]):
        tr[r["_id"]] = r["s"]
    out = []
    for bu in sorted(set(ga) | set(tr), key=str):
        g, t = ga.get(bu, 0), tr.get(bu, 0)
        gap = abs(g - t) / max(g, t) if max(g, t) else 0
        out.append({"bu": bu, "ga4_sessions": g, "tracker_sessions": t, "gap": round(gap, 3), "flag": gap > threshold,
                    "note": "tracker counts consented visits only; GA4 also models unconsented ones" if gap > threshold else ""})
    return out
