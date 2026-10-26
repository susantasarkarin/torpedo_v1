"""Shadow-run report for M-CP3 (MARKETING_PLAN M6): after >= 14 days in shadow.

  decisions   per type: made, judged, share the owner would have accepted, executed (would execute),
              measured, predicted direction right, better than baseline
  freshness   per data source: newest row and how many hours old, flagged when older than its schedule allows
  coverage    per site: pages crawled vs pages with consented tracker events, forms wired, site check status
  ready       per type: whether it may go above L1 (go-live gate) -- the owner still decides at M-CP3
"""
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from marketing import config as mcfg, evaluation, schema

# source -> (collection, time field, max hours before it counts as stale)
SOURCES = {
    "web tracker": ("web_events", "at", 24), "touchpoints / attribution": ("touchpoints", "updated_at", 30),
    "Search Console": ("gsc_pages_daily", "updated_at", 30), "GA4": ("ga4_daily", "updated_at", 30),
    "ad platforms": ("ad_metrics_daily", "updated_at", 26), "social": ("social_metrics_daily", "updated_at", 30),
    "inbox": ("inbox_items", "at", 72), "SEO crawl": ("seo_audits", "started_at", 24 * 8), "PageSpeed": ("cwv_results", "updated_at", 24 * 8),
    "decisions": ("decisions", "created_at", 26), "content": ("content_items", "updated_at", 24 * 14),
}


def build(gd: Optional[Callable] = None, *, days: int = 14, now: Optional[datetime] = None, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    ea = gd(schema.DB)
    since = now - timedelta(days=days)
    dec: Dict[str, Dict[str, Any]] = {}
    first = next(iter(ea["decisions"].find({}).sort("created_at", 1).limit(1)), None)
    for d in ea["decisions"].find({"created_at": {"$gte": since}}):
        t = dec.setdefault(d["decision_type"], {"name": mcfg.DECISION_TYPES.get(d["decision_type"]), "made": 0, "judged": 0, "accepted": 0,
                                                "would_execute": 0, "measured": 0, "direction_right": 0, "better": 0})
        t["made"] += 1
        if d.get("human") in ("approved", "rejected"):
            t["judged"] += 1
            t["accepted"] += 1 if d["human"] == "approved" and not d.get("human_corrected") else 0
        t["would_execute"] += 1 if d.get("status") in ("shadow_executed", "executed") else 0
        o = d.get("outcome") or {}
        if o:
            t["measured"] += 1
            t["direction_right"] += 1 if o.get("direction_correct") else 0
            t["better"] += 1 if o.get("better_than_baseline") else 0
    for t, v in dec.items():
        v["acceptance"] = round(v["accepted"] / v["judged"], 3) if v["judged"] else None
        v["predicted_right"] = round(v["direction_right"] / v["measured"], 3) if v["measured"] else None
        g = evaluation.go_live_ok(t, gd, cfg=cfg, now=now)
        v["may_go_above_L1"] = g["ok"]
        v["gate"] = g["why"]
    fresh = {}
    for name, (col, field, max_h) in SOURCES.items():
        r = next(iter(ea[col].find({field: {"$exists": True}}).sort(field, -1).limit(1)), None)
        at = (r or {}).get(field)
        age = round((now - at).total_seconds() / 3600, 1) if isinstance(at, datetime) else None
        fresh[name] = {"newest": at, "hours_old": age, "status": "no data yet" if age is None else ("stale" if age > max_h else "fresh")}
    cov = {}
    try:
        from platform_core import config_store
        sites = config_store.get("web").get("sites") or []
    except Exception:
        sites = []
    for s in sites:
        audit = next(iter(ea["seo_audits"].find({"site": s["domain"]}).sort("started_at", -1).limit(1)), None) or {}
        pages = {p["url"] for p in audit.get("page_rows") or [] if p.get("status") == 200}
        tracked = set(ea["web_events"].distinct("path", {"host": s["domain"], "at": {"$gte": since}}))
        crawled_paths = {"/" + u.split("/", 3)[3] if u.count("/") >= 3 else "/" for u in pages}
        cov[s["domain"]] = {"bu": s.get("bu"), "pages_crawled": len(pages), "pages_with_events": len(tracked & crawled_paths) if pages else len(tracked),
                            "coverage_pct": round(100 * len(tracked & crawled_paths) / len(crawled_paths), 1) if crawled_paths else None,
                            "forms_14d": ea["web_events"].count_documents({"host": s["domain"], "type": "form_submit", "at": {"$gte": since}})}
    shadow_days = (now - first["created_at"]).days if first else 0
    return {"built_at": now, "window_days": days, "shadow_days": shadow_days, "min_shadow_days_met": shadow_days >= 14,
            "decisions": dec, "freshness": fresh, "tracking_coverage": cov, "mode": cfg.get("mode"),
            "note": "M-CP3: the owner approves going live one action type at a time (runbook §2)."}
