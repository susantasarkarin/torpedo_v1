"""Marketing data layer (MARKETING_PLAN Section 5). Pure registry + helpers.

All marketing collections live in email_automation, next to the tracker's
existing web_events / web_visitors (extended, not duplicated). Every record
carries bu, source, created_at, updated_at (+ site / account where relevant);
stamp() fills them. ensure_indexes() is a dry run unless apply=True.
marketing_config is not a collection: it is the "marketing" section of
platform_core.config_store (marketing/config.py).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

DB = "email_automation"
BUS = ("SFW", "COGENTIX", "BIM")

D = [("date", 1), ("bu", 1)]          # the "date + bu" index on every daily table

# name -> ([(keys, opts)], retention); retention None = keep
COLLECTIONS: Dict[str, Tuple[List[Tuple[Any, Dict[str, Any]]], Optional[str]]] = {
    # web (3.1 / 3.2) -- web_events + web_visitors already exist
    "web_sites": ([("domain", {"unique": True}), ("bu", {})], None),
    "web_visitors": ([("visitor_id", {"unique": True}), ("contact_id", {"sparse": True}), ("lead_id", {"sparse": True}),
                      ("last_seen", {})], None),
    "web_sessions": ([("session_id", {"unique": True}), ("visitor_id", {}), ([("started_at", 1), ("bu", 1)], {})], "13m"),
    "web_events": ([("visitor_id", {}), ([("at", 1), ("bu", 1)], {}), ("type", {})], "13m"),
    "consents": ([("visitor_id", {}), ("at", {})], None),                 # permanent
    # identity + attribution (3.8)
    "touchpoints": ([("tp_key", {"unique": True}), ([("lead_id", 1), ("at", 1)], {}),("contact_id", {"sparse": True}), ("visitor_id", {"sparse": True}),
                     ("click_ids.gclid", {"sparse": True}), ("click_ids.fbclid", {"sparse": True}),
                     ("click_ids.li_fat_id", {"sparse": True}), ("campaign_id", {"sparse": True})], None),
    "attribution_results": ([([("lead_id", 1), ("conversion_id", 1), ("model", 1)], {"unique": True}),
                             ([("bu", 1), ("model", 1), ("event", 1)], {})], None),
    # analytics + SEO (3.2 / 3.3)
    "ga4_daily": ([([("property_id", 1), ("date", 1), ("dims_key", 1)], {"unique": True}), (D, {})], None),
    "gsc_queries_daily": ([([("site", 1), ("date", 1), ("query", 1), ("page", 1), ("country", 1), ("device", 1)],
                            {"unique": True}), (D, {})], None),
    "gsc_pages_daily": ([([("site", 1), ("date", 1), ("page", 1)], {"unique": True}), (D, {})], None),
    "gsc_sitemaps": ([([("site", 1), ("path", 1)], {"unique": True})], None),            # beyond Section 5: GSC sitemaps
    "gsc_url_index": ([("url", {"unique": True}), ("site", {})], None),                  # URL Inspection verdicts
    "seo_audits": ([([("site", 1), ("started_at", -1)], {})], None),
    "seo_issues": ([("key", {"unique": True}), ([("site", 1), ("status", 1), ("severity", 1)], {}), ("audit_id", {})], None),
    "cwv_results": ([([("url", 1), ("strategy", 1), ("date", 1)], {}), (D, {})], None),
    "keywords": ([([("bu", 1), ("keyword", 1)], {"unique": True})], None),
    "keyword_positions": ([([("keyword_id", 1), ("date", 1)], {"unique": True}), (D, {})], None),
    "content_gaps": ([([("bu", 1), ("status", 1)], {})], None),
    "seo_fix_plans": ([("site", {"unique": True})], None),
    # paid (3.4)
    "ad_accounts": ([([("platform", 1), ("account_id", 1)], {"unique": True}), ("bu", {})], None),
    "ad_campaigns": ([([("platform", 1), ("campaign_id", 1)], {"unique": True}), ("bu", {})], None),
    "ad_groups": ([([("platform", 1), ("group_id", 1)], {"unique": True}), ("campaign_id", {})], None),
    "ads": ([([("platform", 1), ("ad_id", 1)], {"unique": True}), ("campaign_id", {})], None),
    "ad_metrics_daily": ([([("platform", 1), ("level", 1), ("entity_id", 1), ("date", 1)], {"unique": True}),
                          ("campaign_id", {}), (D, {})], None),
    "search_terms": ([([("campaign_id", 1), ("term", 1), ("date", 1)], {"unique": True}), (D, {})], None),
    "offline_conversion_uploads": ([([("platform", 1), ("lead_id", 1), ("event", 1)], {"unique": True}),
                                    ("status", {})], None),
    "audiences": ([([("bu", 1), ("platform", 1), ("name", 1)], {"unique": True})], None),
    # social + inbox (3.5 / 3.7)
    "social_accounts": ([([("platform", 1), ("account_id", 1)], {"unique": True}), ("bu", {})], None),
    "social_posts": ([([("platform", 1), ("post_id", 1)], {"unique": True, "sparse": True}), ("content_item_id", {})], None),
    "social_metrics_daily": ([([("platform", 1), ("entity_id", 1), ("date", 1)], {"unique": True}), (D, {})], None),
    "inbox_items": ([([("channel", 1), ("external_id", 1)], {"unique": True}), ([("status", 1), ("due_at", 1)], {}), ("phone_hash", {"sparse": True}),
                     ("contact_id", {"sparse": True}), ("lead_id", {"sparse": True})], None),
    "whatsapp_optins": ([("phone_hash", {}), ("contact_id", {"sparse": True})], None),   # permanent
    "marketing_touches": ([([("lead_id", 1), ("at", -1)], {}), ("phone_hash", {"sparse": True}), ("email", {"sparse": True})], None),
    "lead_form_pending": ([("leadgen_id", {"unique": True}), ("status", {})], None),      # Lead Ads ids awaiting fetch
    "whatsapp_templates": ([([("bu", 1), ("name", 1), ("language", 1)], {"unique": True})], None),
    # content (3.6)
    "content_items": ([([("bu", 1), ("channel", 1), ("status", 1)], {}), ("scheduled_for", {"sparse": True})], None),
    "brand_voice": ([("bu", {"unique": True})], None),
    # decision engine (Section 4)
    "experiments": ([([("bu", 1), ("status", 1)], {})], None),
    "decision_candidates": ([([("decision_type", 1), ("status", 1)], {}), ([("entity_key", 1), ("created_at", -1)], {})], None),
    "decisions": ([([("decision_type", 1), ("status", 1)], {}), ([("entity_key", 1), ("created_at", -1)], {}),
                   ("candidate_id", {})], None),
    "decision_outcomes": ([("decision_id", {"unique": True}), ([("decision_type", 1), ("measured_at", -1)], {})], None),
    "marketing_eval_cases": ([("key", {"unique": True}), ("decision_type", {})], None),
    "marketing_eval_runs": ([("at", -1)], None),
    "marketing_reports": ([("week", {"unique": True})], None),
    "marketing_kpi_snapshots": ([([("kpi", 1), ("date", 1), ("bu", 1)], {"unique": True}), (D, {})], None),
}


def stamp(doc: Dict[str, Any], *, bu: Optional[str], source: str, now: Optional[datetime] = None,
          new: bool = True) -> Dict[str, Any]:
    """Required fields on every marketing record. bu is one of BUS, or None for a cross-BU row."""
    if bu is not None and bu not in BUS:
        raise ValueError(f"unknown bu {bu!r}")
    if not source:
        raise ValueError("source is required")
    now = now or datetime.utcnow()
    out = dict(doc, bu=bu, source=source, updated_at=now)
    if new:
        out.setdefault("created_at", now)
    return out


def upsert_ops(doc: Dict[str, Any], key_fields: List[str], *, bu: Optional[str], source: str,
               now: Optional[datetime] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(filter, update) for an idempotent import row: created_at is set on insert only."""
    now = now or datetime.utcnow()
    body = stamp(doc, bu=bu, source=source, now=now, new=False)
    return {k: doc[k] for k in key_fields}, {"$set": body, "$setOnInsert": {"created_at": now}}


def ensure_indexes(client, apply: bool = False) -> Dict[str, Any]:
    plan = [(name, keys, opts) for name, (idx, _) in COLLECTIONS.items() for keys, opts in idx]
    rep = {"db": DB, "collections": len(COLLECTIONS), "indexes_planned": len(plan), "created": []}
    if apply:
        db = client[DB]
        for name, keys, opts in plan:
            rep["created"].append(f"{name}.{db[name].create_index(keys, background=True, **opts)}")
    return rep
