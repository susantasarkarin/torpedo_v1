"""
Search results the model never got to.

When the local model is busy, extraction stashes the Google results in
email_automation.extraction_backlog "for a later re-run of the same query".
But a query that is tapped out is never run again, so its results waited
forever: on 2026-10-01 the backlog held 6,550 results -- 2,236 LinkedIn
profiles, 766 of them people who were not leads yet. Search quota spent, no
lead.

Each run claims stashed batches, keeps only LinkedIn profiles that are not
leads already (most of a batch is pages, posts and people we have), and hands
those to the same model extraction the search job uses (grounded against the
results). The LinkedIn title rules were tried first and rejected: they cut
titles short and took "Directors" or "Research and Insights at Aston Martin
F1" for a company. When the model is busy the batch goes back to the stash and
the run stops; the next run carries on. Leads are imported through the normal
pipeline, tagged with the ICP of the job that ran the query; their email
addresses come from leads/email_builder.py.
"""
import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

_SLUG = re.compile(r"linkedin\.com/in/([^/?#]+)", re.I)


def profile_slug(url: str) -> str:
    m = _SLUG.search(url or "")
    return m.group(1).lower() if m else ""


def known_slugs(db) -> Set[str]:
    out = set()
    for d in db["leads_enriched"].find({"linkedin_url": {"$regex": "linkedin"}}, {"linkedin_url": 1}):
        s = profile_slug(d.get("linkedin_url"))
        if s:
            out.add(s)
    return out


def _icp_for_query(db, query: str, cache: Dict[str, Optional[str]]) -> Optional[str]:
    if query not in cache:
        job = db["web_search_jobs"].find_one({"query_combinations": query}, {"config.icp_id": 1})
        cache[query] = ((job or {}).get("config") or {}).get("icp_id")
    return cache[query]


def new_profiles(results, have: Set[str]):
    """LinkedIn profile results for people who are not leads yet, once each."""
    out, seen = [], set()
    for r in results or []:
        s = profile_slug(r.get("link"))
        if s and s not in have and s not in seen:
            seen.add(s)
            out.append(r)
    return out


def drain(limit: int = 10, now: Optional[datetime] = None, db=None) -> Dict[str, Any]:
    from leads.ingestion import extract_leads_from_google_results
    from leads.models import LeadInput
    from leads.service import import_leads
    if db is None:
        from database import get_client
        db = get_client()["email_automation"]
    now = now or datetime.utcnow()
    col = db["extraction_backlog"]
    have = known_slugs(db)
    fields = set(LeadInput.model_fields) if hasattr(LeadInput, "model_fields") else set(LeadInput.__fields__)
    stats = {"batches": 0, "nothing_new": 0, "profiles": 0, "extracted": 0, "imported": 0, "model_busy": False}
    icps: Dict[str, Optional[str]] = {}
    for _ in range(limit):
        doc = col.find_one_and_update({"status": "pending"}, {"$set": {"status": "draining", "updated_at": now}},
                                      sort=[("created_at", 1)])
        if not doc:
            break
        stats["batches"] += 1
        fresh = new_profiles(doc.get("results"), have)
        if not fresh:
            stats["nothing_new"] += 1
            col.update_one({"_id": doc["_id"]}, {"$set": {"status": "consumed", "consumed_by": "drain",
                                                          "consumed_at": now, "imported": 0,
                                                          "note": "no profiles that are not leads already"}})
            continue
        stats["profiles"] += len(fresh)
        query = doc.get("query") or ""
        leads = asyncio.run(extract_leads_from_google_results(fresh, query, start=int(doc.get("start") or 1)))
        if not leads:
            back = col.find_one({"_id": doc["_id"]}, {"status": 1}) or {}
            if back.get("status") == "pending":  # the model was busy; extraction re-stashed it
                stats["model_busy"] = True
                break
            col.update_one({"_id": doc["_id"]}, {"$set": {"status": "consumed", "consumed_by": "drain",
                                                          "consumed_at": now, "imported": 0}})
            continue
        stats["extracted"] += len(leads)
        inputs = [LeadInput(**{**{k: v for k, v in l.items() if k in fields}, "source": "websearch"})
                  for l in leads if l.get("name") and l.get("linkedin_url")]
        try:
            res = import_leads(inputs, icp_segment=_icp_for_query(db, query, icps))
        except Exception as e:
            logger.warning("backlog_drain: import failed for %r: %s", query[:60], e)
            col.update_one({"_id": doc["_id"]}, {"$set": {"status": "pending", "drain_error": str(e)[:300]}})
            continue
        stats["imported"] += res.imported
        have.update(profile_slug(l.linkedin_url) for l in inputs)
        col.update_one({"_id": doc["_id"]}, {"$set": {"status": "consumed", "consumed_by": "drain",
                                                      "consumed_at": now, "imported": res.imported}})
    if stats["batches"]:
        logger.info("[BacklogDrain] %s", stats)
    return stats
