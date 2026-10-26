"""Marketing dashboard (module 13) KPIs and Command Centre feeds (MARKETING_PLAN 6.1-6.2).

Hooked into kpi.definitions (DEFS appended, module "marketing") and kpi.compute (FUNCS
registered, attention() called from needs_attention). Marketing-sourced = credited by the
last-non-direct attribution model to a channel other than outreach email; revenue is the
CRM's won / invoiced INR (attribution_results), never platform-reported conversions.
A KPI whose source is not connected yet returns None and the tile says so.
"""
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

MARKETING_CHANNELS = ("paid_search", "paid_social", "organic_search", "social", "referral", "whatsapp", "direct")

# (key, module, name, definition, sources, higher_is_better, unit, compute)
DEFS = [
    ("mkt_leads", "marketing", "Marketing-sourced leads", "Leads created in the period from a site form, lead form, social or WhatsApp",
     ["crm_db.leads", "email_automation.inbox_items"], True, "count", "mkt_leads"),
    ("mkt_rfqs", "marketing", "Marketing-sourced RFQs", "RFQs credited (last non-direct) to a non-outreach channel",
     ["email_automation.attribution_results"], True, "count", "mkt_rfqs"),
    ("mkt_won_inr", "marketing", "Marketing-sourced won ₹", "Won / invoiced INR credited (last non-direct) to marketing channels",
     ["email_automation.attribution_results"], True, "INR", "mkt_won_inr"),
    ("mkt_spend_inr", "marketing", "Ad spend", "Spend across ad platforms in the period", ["email_automation.ad_metrics_daily"], False, "INR", "mkt_spend_inr"),
    ("mkt_cost_per_rfq", "marketing", "Blended cost per RFQ", "Ad spend / marketing-sourced RFQs", ["email_automation.ad_metrics_daily",
     "email_automation.attribution_results"], False, "INR", "mkt_cost_per_rfq"),
    ("mkt_roas", "marketing", "ROAS", "Marketing-sourced won ₹ / ad spend", ["email_automation.ad_metrics_daily"], True, "x", "mkt_roas"),
    ("mkt_site_conversion", "marketing", "Visitor -> lead %", "Form leads / consented visitors", ["email_automation.web_events", "crm_db.leads"],
     True, "%", "mkt_site_conversion"),
    ("mkt_organic_clicks", "marketing", "Organic clicks", "Search Console clicks", ["email_automation.gsc_pages_daily"], True, "count", "mkt_organic_clicks"),
    ("mkt_avg_position", "marketing", "Avg position (target keywords)", "Mean Search Console position of the approved keywords",
     ["email_automation.keyword_positions"], False, "pos", "mkt_avg_position"),
    ("mkt_social_reach", "marketing", "Social reach", "Reach across company pages", ["email_automation.social_metrics_daily"], True, "count", "mkt_social_reach"),
    ("mkt_social_engagement", "marketing", "Social engagement rate", "Engagements / reach", ["email_automation.social_metrics_daily"], True, "%",
     "mkt_social_engagement"),
    ("mkt_inbox_sla_pct", "marketing", "Inbox answered within SLA", "Replied within the channel SLA / replied", ["email_automation.inbox_items"],
     True, "%", "mkt_inbox_sla_pct"),
    ("mkt_inbox_median_min", "marketing", "Inbox median response", "Minutes from message to approved reply", ["email_automation.inbox_items"],
     False, "min", "mkt_inbox_median_min"),
    ("mkt_decisions", "marketing", "Decision Engine", "Proposed / accepted / executed (shadow or live) in the period",
     ["email_automation.decisions"], True, "count", "mkt_decisions"),
    ("mkt_decision_impact", "marketing", "Decisions: measured impact", "Share of measured decisions better than baseline",
     ["email_automation.decision_outcomes"], True, "%", "mkt_decision_impact"),
    ("mkt_seo_open_issues", "marketing", "SEO open issues (high + medium)", "From the weekly crawl", ["email_automation.seo_issues"], False, "count",
     "mkt_seo_open_issues"),
    ("mkt_content_published", "marketing", "Content published / planned", "Published vs scheduled-for in the period",
     ["email_automation.content_items"], True, "%", "mkt_content_published"),
]

_FORM_SOURCES = ("website_form", "linkedin_lead_form", "facebook_lead_ad", "social", "whatsapp")


def _ea(gd):
    return gd("email_automation")


def _bq(bu):
    return {"bu": bu} if bu else {}


def mkt_leads(gd, since, until, bu):
    q = {"created_at": {"$gte": since, "$lt": until}, "source": {"$in": list(_FORM_SOURCES)}, "web_submissions.page": {"$not": {"$regex": "127\\.0\\.|localhost"}}}
    if bu:
        q["bu"] = bu
    return gd("crm_db")["leads"].count_documents(q)


def _attributed(gd, since, until, bu, event, field):
    tot = 0.0
    for r in _ea(gd)["attribution_results"].find({"model": "last_non_direct", "event": event, "conversion_at": {"$gte": since, "$lt": until}, **_bq(bu)}):
        for ch, x in (r.get("credits") or {}).items():
            if ch in MARKETING_CHANNELS:
                tot += float(x.get(field) or 0)
    return round(tot, 2)


def mkt_rfqs(gd, since, until, bu):
    return _attributed(gd, since, until, bu, "rfq", "credit")


def mkt_won_inr(gd, since, until, bu):
    return _attributed(gd, since, until, bu, "won", "value_inr")


def mkt_spend_inr(gd, since, until, bu):
    rows = list(_ea(gd)["ad_metrics_daily"].find({"level": "campaign", "date": {"$gte": since.strftime("%Y-%m-%d"),
                                                                                "$lt": until.strftime("%Y-%m-%d")}, **_bq(bu)}))
    return round(sum(float(r.get("spend_inr") or 0) for r in rows), 2) if rows else None


def mkt_cost_per_rfq(gd, since, until, bu):
    s, r = mkt_spend_inr(gd, since, until, bu), mkt_rfqs(gd, since, until, bu)
    return round(s / r, 2) if s is not None and r else None


def mkt_roas(gd, since, until, bu):
    s = mkt_spend_inr(gd, since, until, bu)
    return round(mkt_won_inr(gd, since, until, bu) / s, 2) if s else None


def mkt_site_conversion(gd, since, until, bu):
    ev = _ea(gd)["web_events"]
    v = len(ev.distinct("visitor_id", {"at": {"$gte": since, "$lt": until}, "visitor_id": {"$ne": None}, **_bq(bu)}))
    return round(100 * mkt_leads(gd, since, until, bu) / v, 2) if v else None


def mkt_organic_clicks(gd, since, until, bu):
    rows = list(_ea(gd)["gsc_pages_daily"].find({"date": {"$gte": since.strftime("%Y-%m-%d"), "$lt": until.strftime("%Y-%m-%d")}, **_bq(bu)},
                                                {"clicks": 1}))
    return int(sum(float(r.get("clicks") or 0) for r in rows)) if rows else None


def mkt_avg_position(gd, since, until, bu):
    rows = list(_ea(gd)["keyword_positions"].find({"date": {"$gte": since.strftime("%Y-%m-%d"), "$lt": until.strftime("%Y-%m-%d")}, **_bq(bu)},
                                                  {"position": 1}))
    return round(sum(float(r.get("position") or 0) for r in rows) / len(rows), 1) if rows else None


def _social(gd, since, until, bu):
    rows = list(_ea(gd)["social_metrics_daily"].find({"date": {"$gte": since.strftime("%Y-%m-%d"), "$lt": until.strftime("%Y-%m-%d")}, **_bq(bu)}))
    return rows


def mkt_social_reach(gd, since, until, bu):
    rows = _social(gd, since, until, bu)
    return int(sum(float(r.get("reach") or 0) for r in rows)) if rows else None


def mkt_social_engagement(gd, since, until, bu):
    rows = _social(gd, since, until, bu)
    reach = sum(float(r.get("reach") or 0) for r in rows)
    return round(100 * sum(float(r.get("engagement") or 0) for r in rows) / reach, 2) if reach else None


def _replied(gd, since, until, bu):
    return list(_ea(gd)["inbox_items"].find({"status": "replied", "replied_at": {"$gte": since, "$lt": until}, **_bq(bu)},
                                            {"sla_met": 1, "response_minutes": 1}))


def mkt_inbox_sla_pct(gd, since, until, bu):
    r = _replied(gd, since, until, bu)
    return round(100 * sum(1 for x in r if x.get("sla_met")) / len(r), 1) if r else None


def mkt_inbox_median_min(gd, since, until, bu):
    m = sorted(x["response_minutes"] for x in _replied(gd, since, until, bu) if x.get("response_minutes") is not None)
    return m[len(m) // 2] if m else None


def mkt_decisions(gd, since, until, bu):
    d = _ea(gd)["decisions"]
    q = {"created_at": {"$gte": since, "$lt": until}, **_bq(bu)}
    return {"proposed": d.count_documents(q), "accepted": d.count_documents({**q, "human": "approved"}),
            "executed": d.count_documents({**q, "status": {"$in": ["executed", "shadow_executed"]}})}


def mkt_decision_impact(gd, since, until, bu):
    rows = list(_ea(gd)["decision_outcomes"].find({"measured_at": {"$gte": since, "$lt": until}, **_bq(bu)}, {"better_than_baseline": 1}))
    return round(100 * sum(1 for r in rows if r.get("better_than_baseline")) / len(rows), 1) if rows else None


def mkt_seo_open_issues(gd, since, until, bu):
    return _ea(gd)["seo_issues"].count_documents({"status": "open", "severity": {"$in": ["critical", "high", "medium"]}, **_bq(bu)})


def mkt_content_published(gd, since, until, bu):
    c = _ea(gd)["content_items"]
    planned = c.count_documents({"scheduled_for": {"$gte": since, "$lt": until}, **_bq(bu)})
    done = c.count_documents({"published_at": {"$gte": since, "$lt": until}, **_bq(bu)})
    return round(100 * done / planned, 1) if planned else None


FUNCS: Dict[str, Callable] = {d[7]: globals()[d[7]] for d in DEFS}


# ------------------------------------------------------------------ Command Centre feeds (6.2)
def attention(gd, now: datetime, add: Callable) -> None:
    """add(module, what, inr, since, owner, link, red) -- same contract as kpi.compute.needs_attention."""
    ea = _ea(gd)
    link_dec = "/admin/review-queue?type=marketing_decision"
    for d in ea["decisions"].find({"status": {"$in": ["in_review", "shadow_executed"]}, "decision_type": {"$in": ["D2", "D13"]},
                                   "created_at": {"$gte": now - timedelta(days=7)}}).limit(100):
        rid = d.get("rule_id") or ""
        what = {"d2_spend_no_rfq": "Campaign spending with 0 RFQs in 30 days", "d13_spend_spike": "Spend spike",
                "d13_ctr_crash": "CTR crash", "d13_tracker_silent": "Site tracker silent", "d13_conversion_drop": "Form submissions dropped"}
        add("marketing", f"{what.get(rid, rid)}: {d.get('entity_label') or d.get('entity_key')}", d.get("impact_inr"), d["created_at"],
            None, link_dec, rid in ("d2_spend_no_rfq", "d13_spend_spike", "d13_tracker_silent"))
    for a in ea["ad_accounts"].find({"$or": [{"billing_problem": True}, {"status": {"$in": ["DISABLED", "UNSETTLED", "PENDING_RISK_REVIEW"]}}]}):
        add("marketing", f"Ad account problem: {a.get('name') or a.get('account_id')} ({a.get('status') or 'billing'})", None,
            a.get("updated_at"), None, "/admin/marketing/integrations", True)
    n_dis = ea["ads"].count_documents({"review_status": {"$in": ["DISAPPROVED", "disapproved"]}})
    if n_dis:
        add("marketing", f"{n_dis} ads disapproved", None, now, None, "/admin/dashboards/marketing", True)
    for s in ea["gsc_sitemaps"].find({"errors": {"$gt": 0}}):
        add("marketing", f"Search Console: {s['errors']} sitemap error(s) on {s.get('path')}", None, s.get("updated_at"), None,
            "/admin/dashboards/marketing", True)
    for u in ea["gsc_url_index"].find({"verdict": "FAIL"}).limit(20):
        add("marketing", f"Not indexed: {u['url']} ({u.get('coverage')})", None, u.get("updated_at"), None, "/admin/dashboards/marketing", False)
    # pages losing > 30 % organic clicks week over week
    d0, d7, d14 = (now - timedelta(days=x) for x in (1, 8, 15))
    cur: Dict[str, float] = {}
    prev: Dict[str, float] = {}
    split = d7.strftime("%Y-%m-%d")
    for r in ea["gsc_pages_daily"].find({"date": {"$gte": d14.strftime("%Y-%m-%d"), "$lt": d0.strftime("%Y-%m-%d")}}, {"page": 1, "date": 1, "clicks": 1}):
        bucket = cur if r["date"] >= split else prev
        bucket[r["page"]] = bucket.get(r["page"], 0) + float(r.get("clicks") or 0)
    for page, p in prev.items():
        if p >= 20 and cur.get(page, 0) < 0.7 * p:
            add("marketing", f"Organic clicks down {round(100 * (1 - cur.get(page, 0) / p))}% w/w: {page}", None, d7, None,
                "/admin/dashboards/marketing", False)
    for it in ea["inbox_items"].find({"status": "open", "due_at": {"$lt": now}}).sort("due_at", 1).limit(100):
        add("marketing", f"Inbox past SLA: {it['channel'].replace('_', ' ')} — {(it.get('text') or '')[:60]}", None, it["due_at"], None,
            "/admin/marketing/inbox", now - it["due_at"] > timedelta(hours=8))
    for t in ea["whatsapp_templates"].find({"status": "rejected"}):
        add("marketing", f"WhatsApp template rejected: {t.get('name')}", None, t.get("updated_at"), None, "/admin/marketing/inbox", True)
    for d in ea["decisions"].find({"decision_type": "D10", "status": "in_review", "parameters.grade": "A",
                                   "created_at": {"$lt": now - timedelta(hours=24)}}).limit(50):
        add("marketing", f"High-intent lead not followed up in 24 h: {d.get('entity_label')}", None, d["created_at"], None, link_dec, True)
    for r in ea["review_queue_items"].find({"type": "marketing_stop_loss", "status": "pending"}):
        add("marketing", r.get("reason") or "Decision type auto-downgraded", None, r.get("created_at"), None, link_dec, True)
    old = ea["decisions"].count_documents({"status": "in_review", "created_at": {"$lt": now - timedelta(days=3)}})
    if old:
        first = ea["decisions"].find_one({"status": "in_review", "created_at": {"$lt": now - timedelta(days=3)}}, sort=[("created_at", 1)])
        add("marketing", f"{old} marketing recommendations waiting > 3 days", None, first["created_at"], None, link_dec, old > 10)
