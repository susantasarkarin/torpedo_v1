"""Marketing dashboard sections (MARKETING_PLAN 6.1 Sections, 3.2.1, 3.8.3). Computed from stored rows only;
a section whose source is not connected says so ("no data yet") instead of showing zeros.

website      traffic by source (first-party tracker, consented sessions), new vs returning, device, top entry pages,
             funnel visit -> form start -> submit -> lead -> RFQ -> won INR, form abandonment, tracking health
seo          clicks / impressions / CTR / position trend (weekly), open issues by severity, CWV pass rate, opportunities
paid         per platform + campaign: spend, leads, RFQs, CPL, cost per RFQ, ROAS, pacing vs monthly cap,
             search-term waste, creative fatigue
social       reach, engagement per platform; WhatsApp conversations, opt-ins, template status
content      pieces by status, top pieces by leads, calendar adherence
attribution  channel mix by model (switch), average touches and days to RFQ
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from marketing import attribution, schema


def _ymd(d):
    return d.strftime("%Y-%m-%d")


def _device(ua: str) -> str:
    u = (ua or "").lower()
    return "mobile" if any(k in u for k in ("mobi", "android", "iphone")) else "tablet" if "ipad" in u or "tablet" in u else "desktop"


def website(gd, since, until, bu=None) -> Dict[str, Any]:
    ea = gd(schema.DB)
    q = {"started_at": {"$gte": since, "$lt": until}, **({"bu": bu} if bu else {})}
    sessions = list(ea["web_sessions"].find(q))
    if not sessions:
        anon = ea["web_events"].count_documents({"type": "page_view", "visitor_id": None, "at": {"$gte": since, "$lt": until}})
        return {"no_data": True, "anonymous_page_views": anon}
    src = Counter(attribution.channel({"kind": "visit", "utm": s.get("utm"), "click_ids": s.get("click_ids"), "referrer": s.get("referrer")})
                  for s in sessions)
    first_seen = {v["visitor_id"]: v.get("first_seen") for v in ea["web_visitors"].find({"visitor_id": {"$in": [s["visitor_id"] for s in sessions]}})}
    new = sum(1 for s in sessions if first_seen.get(s["visitor_id"]) and first_seen[s["visitor_id"]] >= since)
    entry = Counter((s.get("landing") or "").split("?")[0] for s in sessions).most_common(10)
    ev = Counter()
    devices = Counter()
    for e in ea["web_events"].find({"at": {"$gte": since, "$lt": until}, "visitor_id": {"$ne": None}, **({"bu": bu} if bu else {})},
                                   {"type": 1, "ua": 1, "visitor_id": 1}):
        ev[e["type"]] += 1
        if e["type"] == "page_view":
            devices[_device(e.get("ua"))] += 1
    leads = gd("crm_db")["leads"].count_documents({"source": "website_form", "created_at": {"$gte": since, "$lt": until}, **({"bu": bu} if bu else {})})
    rfq = won = 0
    won_inr = 0.0
    for r in ea["attribution_results"].find({"model": "last_non_direct", "conversion_at": {"$gte": since, "$lt": until}, **({"bu": bu} if bu else {})}):
        if not any(ch in r.get("credits", {}) for ch in ("organic_search", "paid_search", "paid_social", "social", "referral", "direct")):
            continue
        if r["event"] == "rfq":
            rfq += 1
        elif r["event"] == "won":
            won += 1
            won_inr += float(r.get("value_inr") or 0)
    starts, subs, aband = ev["form_start"], ev["form_submit"], ev["form_abandon"]
    try:
        from platform_core import config_store
        sites = config_store.get("web").get("sites") or []
    except Exception:
        sites = []
    health = {}
    for s in sites:
        last = next(iter(ea["web_events"].find({"host": s["domain"]}).sort("at", -1).limit(1)), None)
        health[s["domain"]] = {"last_event": (last or {}).get("at"), "silent_hours": round((until - last["at"]).total_seconds() / 3600, 1) if last else None}
    return {"sessions": len(sessions), "visitors": len({s["visitor_id"] for s in sessions}), "new_visitors": new,
            "returning_visitors": len({s["visitor_id"] for s in sessions}) - new, "by_source": dict(src), "devices": dict(devices),
            "top_entry_pages": entry, "funnel": {"visits": len(sessions), "form_starts": starts, "form_submits": subs, "leads": leads,
                                                 "rfqs": rfq, "won": won, "won_inr": round(won_inr, 2)},
            "form_abandonment_pct": round(100 * aband / starts, 1) if starts else None, "tracking_health": health}


def seo(gd, since, until, bu=None) -> Dict[str, Any]:
    ea = gd(schema.DB)
    weeks = defaultdict(lambda: {"clicks": 0.0, "impressions": 0.0, "pos_x": 0.0})
    for r in ea["gsc_pages_daily"].find({"date": {"$gte": _ymd(since), "$lt": _ymd(until)}, **({"bu": bu} if bu else {})}):
        w = datetime.strptime(r["date"], "%Y-%m-%d").strftime("%G-W%V")
        i = float(r.get("impressions") or 0)
        weeks[w]["clicks"] += float(r.get("clicks") or 0)
        weeks[w]["impressions"] += i
        weeks[w]["pos_x"] += float(r.get("position") or 0) * i
    trend = [{"week": w, "clicks": int(v["clicks"]), "impressions": int(v["impressions"]),
              "ctr": round(v["clicks"] / v["impressions"], 4) if v["impressions"] else None,
              "position": round(v["pos_x"] / v["impressions"], 1) if v["impressions"] else None} for w, v in sorted(weeks.items())]
    sev = Counter(i["severity"] for i in ea["seo_issues"].find({"status": "open", **({"bu": bu} if bu else {})}, {"severity": 1}))
    cwv = list(ea["cwv_results"].find({"date": {"$gte": _ymd(since)}, **({"bu": bu} if bu else {})}))
    passed = sum(1 for c in cwv if (c.get("field_overall") or "").upper() == "FAST" or (c.get("score") or 0) >= 90)
    from marketing import seo_plan
    return {"trend": trend or None, "no_gsc_data": not trend, "open_issues": dict(sev),
            "cwv_pass_pct": round(100 * passed / len(cwv), 1) if cwv else None, "cwv_checks": len(cwv),
            "opportunities": [o for o in seo_plan.opportunities(gd) if not bu or o["bu"] == bu][:15]}


def paid(gd, since, until, bu=None, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ea = gd(schema.DB)
    rows = list(ea["ad_metrics_daily"].find({"level": "campaign", "date": {"$gte": _ymd(since), "$lt": _ymd(until)}, **({"bu": bu} if bu else {})}))
    if not rows:
        return {"no_data": True}
    camps = defaultdict(lambda: defaultdict(float))
    names = {}
    for r in rows:
        k = (r["platform"], r["entity_id"])
        names[k] = r.get("name") or r["entity_id"]
        for f in ("spend_inr", "clicks", "impressions", "leads", "rfqs", "won_inr"):
            camps[k][f] += float(r.get(f) or 0)
        camps[k]["bu"] = r.get("bu")
    table = []
    for (plat, cid), m in camps.items():
        table.append({"platform": plat, "campaign": names[(plat, cid)], "bu": m["bu"], "spend_inr": round(m["spend_inr"]), "leads": m["leads"],
                      "rfqs": m["rfqs"], "cpl_inr": round(m["spend_inr"] / m["leads"]) if m["leads"] else None,
                      "cost_per_rfq_inr": round(m["spend_inr"] / m["rfqs"]) if m["rfqs"] else None,
                      "roas": round(m["won_inr"] / m["spend_inr"], 2) if m["spend_inr"] else None})
    caps = ((cfg or {}).get("budget") or {}).get("monthly_cap_inr") or {}
    month0 = until.replace(day=1)
    pacing = {}
    mspend = defaultdict(float)
    for r in ea["ad_metrics_daily"].find({"level": "campaign", "date": {"$gte": _ymd(month0)}}):
        mspend[(r.get("bu"), r["platform"])] += float(r.get("spend_inr") or 0)
    days_in, day_n = 30, max(1, (until - month0).days)
    for (b, p), s in mspend.items():
        cap = (caps.get(b) or {}).get(p)
        pacing[f"{b}/{p}"] = {"month_spend_inr": round(s), "cap_inr": cap,
                              "pacing_pct": round(100 * (s / day_n * days_in) / cap, 1) if cap else None}
    waste = defaultdict(float)
    for t in ea["search_terms"].find({"date": {"$gte": _ymd(since), "$lt": _ymd(until)}, "leads": {"$in": [0, 0.0, None]}}):
        waste[t["term"]] += float(t.get("spend_inr") or 0)
    fatigue = [{"ad": a.get("name") or a["entity_id"], "platform": a["platform"], "frequency": a.get("frequency")}
               for a in ea["ad_metrics_daily"].find({"level": "ad", "date": {"$gte": _ymd(until - timedelta(days=7))}, "frequency": {"$gte": 4}}).limit(20)]
    return {"campaigns": sorted(table, key=lambda x: -x["spend_inr"]), "pacing": pacing,
            "search_term_waste_inr": round(sum(waste.values())), "top_waste_terms": sorted(waste.items(), key=lambda x: -x[1])[:10],
            "creative_fatigue": fatigue}


def social(gd, since, until, bu=None) -> Dict[str, Any]:
    ea = gd(schema.DB)
    per = defaultdict(lambda: {"reach": 0.0, "engagement": 0.0})
    for r in ea["social_metrics_daily"].find({"date": {"$gte": _ymd(since), "$lt": _ymd(until)}, **({"bu": bu} if bu else {})}):
        per[r["platform"]]["reach"] += float(r.get("reach") or 0)
        per[r["platform"]]["engagement"] += float(r.get("engagement") or 0)
    wa_conv = len({i.get("phone_hash") for i in ea["inbox_items"].find({"channel": "whatsapp", "at": {"$gte": since, "$lt": until},
                                                                         **({"bu": bu} if bu else {})}, {"phone_hash": 1})})
    optins = ea["whatsapp_optins"].count_documents({"granted": True, **({"bu": bu} if bu else {})})
    optouts = ea["whatsapp_optins"].count_documents({"granted": False, **({"bu": bu} if bu else {})})
    tpl = Counter(t.get("status") for t in ea["whatsapp_templates"].find({**({"bu": bu} if bu else {})}, {"status": 1}))
    return {"platforms": {p: {**v, "engagement_rate_pct": round(100 * v["engagement"] / v["reach"], 2) if v["reach"] else None} for p, v in per.items()} or None,
            "whatsapp": {"conversations": wa_conv, "opt_ins": optins, "opt_outs": optouts, "templates": dict(tpl)}}


def content(gd, since, until, bu=None) -> Dict[str, Any]:
    ea = gd(schema.DB)
    st = Counter(c["status"] for c in ea["content_items"].find({**({"bu": bu} if bu else {})}, {"status": 1}))
    planned = ea["content_items"].count_documents({"scheduled_for": {"$gte": since, "$lt": until}, **({"bu": bu} if bu else {})})
    on_time = ea["content_items"].count_documents({"scheduled_for": {"$gte": since, "$lt": until}, "status": "published", **({"bu": bu} if bu else {})})
    from marketing import content as C
    return {"by_status": dict(st), "adherence_pct": round(100 * on_time / planned, 1) if planned else None,
            "top_by_leads": [p for p in C.performance(gd, days=max(7, (until - since).days)) if not bu or p["bu"] == bu][:10]}


def attribution_mix(gd, since, until, bu=None, model: str = attribution.DEFAULT_MODEL) -> Dict[str, Any]:
    if model not in attribution.MODELS:
        raise ValueError(f"model must be one of {attribution.MODELS}")
    ea = gd(schema.DB)
    mix: Dict[str, Dict[str, Dict[str, float]]] = {"rfq": defaultdict(float), "won": defaultdict(float), "won_inr": defaultdict(float)}
    touches, days = [], []
    for r in ea["attribution_results"].find({"model": model, "conversion_at": {"$gte": since, "$lt": until}, **({"bu": bu} if bu else {})}):
        for ch, x in (r.get("credits") or {}).items():
            if r["event"] not in ("rfq", "won"):
                continue
            mix[r["event"]][ch] += float(x.get("credit") or 0)
            if r["event"] == "won":
                mix["won_inr"][ch] += float(x.get("value_inr") or 0)
        if r["event"] == "rfq":
            touches.append(r.get("touches") or 0)
            if r.get("days_to_convert") is not None:
                days.append(r["days_to_convert"])
    assisted = Counter()
    for r in ea["attribution_results"].find({"model": "position_based", "event": "rfq", "conversion_at": {"$gte": since, "$lt": until}}):
        path = r.get("path") or []
        for ch in set(path[:-1]) - {path[-1] if path else None}:
            assisted[ch] += 1
    return {"model": model, "models": list(attribution.MODELS), "rfq_by_channel": {k: round(v, 2) for k, v in mix["rfq"].items()},
            "won_by_channel": {k: round(v, 2) for k, v in mix["won"].items()}, "won_inr_by_channel": {k: round(v) for k, v in mix["won_inr"].items()},
            "assisted_rfqs": dict(assisted), "avg_touches_to_rfq": round(sum(touches) / len(touches), 1) if touches else None,
            "avg_days_to_rfq": round(sum(days) / len(days), 1) if days else None}


def all_sections(gd: Callable, *, days: int = 30, bu: Optional[str] = None, model: str = attribution.DEFAULT_MODEL,
                 now: Optional[datetime] = None, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    out = {"period_days": days, "bu": bu or "ALL", "built_at": now}
    for name, fn in (("website", website), ("seo", seo), ("social", social), ("content", content)):
        try:
            out[name] = fn(gd, since, now, bu)
        except Exception as e:      # one broken source must not blank the page
            out[name] = {"error": str(e)[:150]}
    try:
        out["paid"] = paid(gd, since, now, bu, cfg)
    except Exception as e:
        out["paid"] = {"error": str(e)[:150]}
    try:
        out["attribution"] = attribution_mix(gd, since, now, bu, model)
    except ValueError:
        raise
    except Exception as e:
        out["attribution"] = {"error": str(e)[:150]}
    return out
