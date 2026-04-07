"""
CINT Survey Pool Cleanup Task
==============================

Runs every 5 minutes to:
1. Fetch ALL live surveys from CINT offerwall API (source of truth)
2. Cache them in-memory for instant access by traffic allocation
3. Mark closed/expired surveys in our cint_surveys MongoDB as inactive
4. Log cleanup stats for monitoring

Design principles:
- Non-blocking: runs in a background thread, never touches the event loop
- Lightweight: single API call + small batch DB updates
- Fail-safe: errors are logged but never crash the app
- Speed boost: cached offerwall data eliminates per-request API calls
"""

import os
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ============================================
# IN-MEMORY OFFERWALL CACHE
# ============================================
# This cache is the single source of truth for live CINT surveys.
# Updated every 5 minutes by the cleanup task.
# Read by traffic.py's fetch_cint_offerwall_candidates() for instant access.

_offerwall_cache: Dict = {
    "surveys": [],                  # Full list of survey dicts from offerwall API
    "survey_ids": set(),            # Set of live survey number strings (for fast lookup)
    "by_country": {},               # {country_lang_id: [survey_dicts]}
    "last_updated": None,           # datetime of last successful refresh
    "last_count": 0,                # Total surveys in last refresh
    "error": None,                  # Last error message if refresh failed
}
_cache_lock = threading.Lock()


def get_cached_offerwall() -> Dict:
    """Get the current offerwall cache (thread-safe read)."""
    with _cache_lock:
        return _offerwall_cache.copy()


def get_cached_surveys_for_country(country_lang_id: int) -> List[dict]:
    """
    Get cached surveys for a specific CountryLanguageID.
    Returns empty list if cache is stale (>10 min old) or empty.
    """
    with _cache_lock:
        # Check staleness
        if _offerwall_cache["last_updated"] is None:
            return []
        age = (datetime.utcnow() - _offerwall_cache["last_updated"]).total_seconds()
        if age > 600:  # 10 min staleness threshold
            logger.warning(f"[CintCleanup] Offerwall cache is stale ({age:.0f}s old)")
            return []
        
        return _offerwall_cache["by_country"].get(country_lang_id, [])


def get_live_survey_ids() -> Set[str]:
    """Get set of currently live survey IDs (for fast membership check)."""
    with _cache_lock:
        return _offerwall_cache["survey_ids"].copy()


def is_survey_live(survey_id: str) -> bool:
    """Check if a survey is currently live on CINT offerwall."""
    with _cache_lock:
        return str(survey_id) in _offerwall_cache["survey_ids"]


# ============================================
# OFFERWALL REFRESH (API call)
# ============================================

def _refresh_offerwall_cache() -> dict:
    """
    Fetch ALL surveys from CINT offerwall API and update the cache.
    
    Returns:
        {"total": int, "by_country": {id: count}, "error": str or None}
    """
    import httpx
    
    api_key = os.getenv("CINT_API_KEY")
    supplier_code = os.getenv("CINT_SUPPLIER_CODE", "6777")
    
    if not api_key or not supplier_code:
        return {"total": 0, "error": "Missing CINT_API_KEY or CINT_SUPPLIER_CODE"}
    
    try:
        headers = {
            "Authorization": api_key,
            "Accept": "application/json",
        }
        url = f"https://api.samplicio.us/Supply/v1/Surveys/AllOfferwall/{supplier_code}"
        
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=headers)
        
        if resp.status_code != 200:
            return {"total": 0, "error": f"Offerwall API returned {resp.status_code}"}
        
        surveys = resp.json().get("Surveys", [])
        
        # Build indexes
        survey_ids = set()
        by_country = {}
        
        for s in surveys:
            sid = str(s.get("SurveyNumber", ""))
            if sid:
                survey_ids.add(sid)
            
            clid = s.get("CountryLanguageID")
            if clid is not None:
                if clid not in by_country:
                    by_country[clid] = []
                by_country[clid].append(s)
        
        # Update cache atomically
        with _cache_lock:
            _offerwall_cache["surveys"] = surveys
            _offerwall_cache["survey_ids"] = survey_ids
            _offerwall_cache["by_country"] = by_country
            _offerwall_cache["last_updated"] = datetime.utcnow()
            _offerwall_cache["last_count"] = len(surveys)
            _offerwall_cache["error"] = None
        
        country_summary = {k: len(v) for k, v in sorted(by_country.items(), key=lambda x: -len(x[1]))[:10]}
        
        return {
            "total": len(surveys),
            "unique_ids": len(survey_ids),
            "countries": len(by_country),
            "top_countries": country_summary,
            "error": None,
        }
        
    except Exception as e:
        error_msg = f"Offerwall refresh error: {str(e)[:200]}"
        with _cache_lock:
            _offerwall_cache["error"] = error_msg
        return {"total": 0, "error": error_msg}


# ============================================
# DB CLEANUP (mark stale surveys inactive)
# ============================================

def _cleanup_stale_surveys_in_db(live_survey_ids: Set[str]) -> dict:
    """
    Mark surveys in cint_surveys DB that are no longer on the offerwall as inactive.
    
    Uses small batch updates to avoid locking the collection.
    
    Args:
        live_survey_ids: Set of survey_id strings currently live on offerwall
    
    Returns:
        {"checked": int, "deactivated": int, "already_inactive": int, "error": str or None}
    """
    from pymongo import MongoClient
    
    try:
        from ..database import get_client
    except ImportError:
        from database import get_client
    
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        return {"checked": 0, "deactivated": 0, "error": "MONGO_URI not set"}
    
    if not live_survey_ids:
        return {"checked": 0, "deactivated": 0, "error": "No live surveys to compare against"}
    
    try:
        client = get_client()
        try:
            cint_db = client["cint_research"]
            cint_collection = cint_db["cint_surveys"]
            
            # Count currently active in DB
            active_count = cint_collection.count_documents({"is_active": True})
            
            if active_count == 0:
                return {"checked": 0, "deactivated": 0, "already_inactive": 0, "error": None}
            
            # Find active surveys NOT in the live offerwall set
            # Process in small batches to avoid holding locks
            BATCH_SIZE = 500
            total_deactivated = 0
            total_checked = 0
            
            cursor = cint_collection.find(
                {"is_active": True},
                {"survey_id": 1, "_id": 1}
            ).batch_size(BATCH_SIZE)
            
            stale_ids = []
            
            for doc in cursor:
                total_checked += 1
                sid = str(doc.get("survey_id", ""))
                
                if sid and sid not in live_survey_ids:
                    stale_ids.append(doc["_id"])
                
                # Flush batch
                if len(stale_ids) >= BATCH_SIZE:
                    result = cint_collection.update_many(
                        {"_id": {"$in": stale_ids}},
                        {"$set": {
                            "is_active": False,
                            "is_active_in_pool": False,
                            "deactivated_at": datetime.utcnow(),
                            "deactivation_reason": "not_on_offerwall",
                        }}
                    )
                    total_deactivated += result.modified_count
                    stale_ids = []
                    
                    # Small sleep between batches to reduce DB pressure
                    time.sleep(0.05)
            
            # Final batch
            if stale_ids:
                result = cint_collection.update_many(
                    {"_id": {"$in": stale_ids}},
                    {"$set": {
                        "is_active": False,
                        "is_active_in_pool": False,
                        "deactivated_at": datetime.utcnow(),
                        "deactivation_reason": "not_on_offerwall",
                    }}
                )
                total_deactivated += result.modified_count
            
            # Also reactivate surveys that ARE on offerwall but marked inactive
            # (surveys can come back online)
            if live_survey_ids:
                live_int_ids = []
                for sid in live_survey_ids:
                    try:
                        live_int_ids.append(int(sid))
                    except (ValueError, TypeError):
                        pass
                
                if live_int_ids:
                    # Process reactivation in batches too
                    reactivated = 0
                    for i in range(0, len(live_int_ids), BATCH_SIZE):
                        batch = live_int_ids[i:i + BATCH_SIZE]
                        result = cint_collection.update_many(
                            {
                                "survey_id": {"$in": batch},
                                "is_active": False,
                                "deactivation_reason": "not_on_offerwall",
                            },
                            {"$set": {
                                "is_active": True,
                                "reactivated_at": datetime.utcnow(),
                            },
                            "$unset": {
                                "deactivation_reason": "",
                                "deactivated_at": "",
                            }}
                        )
                        reactivated += result.modified_count
                        time.sleep(0.05)
                    
                    if reactivated > 0:
                        logger.info(f"[CintCleanup] Reactivated {reactivated} surveys that came back online")
            
            return {
                "checked": total_checked,
                "active_before": active_count,
                "deactivated": total_deactivated,
                "live_on_offerwall": len(live_survey_ids),
                "error": None,
            }
            
        finally:
            pass  # Shared pool — do not close
            
    except Exception as e:
        return {"checked": 0, "deactivated": 0, "error": f"DB cleanup error: {str(e)[:200]}"}


# ============================================
# DELETE OLD SURVEYS (>3 days) — CINT + CPX
# ============================================

def _delete_old_surveys(max_age_days: int = 3) -> dict:
    """
    Permanently delete old survey documents from BOTH cint_surveys and cpx_surveys.
    
    CINT: deletes inactive surveys older than max_age_days (by received_at),
          plus orphan docs with no received_at field.
    CPX:  deletes surveys older than max_age_days (by last_updated),
          since CPX docs use last_updated instead of received_at.
    
    Processes in batches to avoid locking collections.
    
    Args:
        max_age_days: Delete surveys older than this (default: 3 days)
    
    Returns:
        {"cint_deleted": int, "cint_orphans": int, "cpx_deleted": int, "error": str or None}
    """
    from pymongo import MongoClient
    
    try:
        from ..database import get_client
    except ImportError:
        from database import get_client

    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        return {"cint_deleted": 0, "cint_orphans": 0, "cpx_deleted": 0, "error": "MONGO_URI not set"}
    
    try:
        client = get_client()
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_age_days)
            BATCH_SIZE = 500
            
            # ---- CINT: cint_research.cint_surveys ----
            cint_collection = client["cint_research"]["cint_surveys"]
            
            # 1a. Delete inactive CINT surveys older than cutoff (by received_at)
            cint_deleted = 0
            while True:
                old_docs = list(cint_collection.find(
                    {
                        "is_active": False,
                        "received_at": {"$lt": cutoff},
                    },
                    {"_id": 1},
                ).limit(BATCH_SIZE))
                
                if not old_docs:
                    break
                
                ids = [d["_id"] for d in old_docs]
                result = cint_collection.delete_many({"_id": {"$in": ids}})
                cint_deleted += result.deleted_count
                time.sleep(0.05)
            
            # 1b. Delete CINT orphan documents with no received_at field
            cint_orphans = 0
            while True:
                orphan_docs = list(cint_collection.find(
                    {
                        "received_at": {"$exists": False},
                        "is_active": False,
                    },
                    {"_id": 1},
                ).limit(BATCH_SIZE))
                
                if not orphan_docs:
                    break
                
                ids = [d["_id"] for d in orphan_docs]
                result = cint_collection.delete_many({"_id": {"$in": ids}})
                cint_orphans += result.deleted_count
                time.sleep(0.05)
            
            # ---- CPX: cpx_research.cpx_surveys ----
            cpx_collection = client["cpx_research"]["cpx_surveys"]
            
            # 2. Delete CPX surveys older than cutoff (by last_updated)
            #    CPX docs don't have is_active, they use is_active_in_pool
            cpx_deleted = 0
            while True:
                old_docs = list(cpx_collection.find(
                    {
                        "last_updated": {"$lt": cutoff},
                    },
                    {"_id": 1},
                ).limit(BATCH_SIZE))
                
                if not old_docs:
                    break
                
                ids = [d["_id"] for d in old_docs]
                result = cpx_collection.delete_many({"_id": {"$in": ids}})
                cpx_deleted += result.deleted_count
                time.sleep(0.05)
            
            return {
                "cint_deleted": cint_deleted,
                "cint_orphans": cint_orphans,
                "cpx_deleted": cpx_deleted,
                "error": None,
            }
            
        finally:
            pass  # Shared pool — do not close
            
    except Exception as e:
        return {"cint_deleted": 0, "cint_orphans": 0, "cpx_deleted": 0, "error": f"Delete error: {str(e)[:200]}"}


# ============================================
# MAIN CLEANUP TASK (called by scheduler)
# ============================================

def run_cint_survey_cleanup():
    """
    Main cleanup task — called every 5 minutes by APScheduler.
    
    Runs synchronously in a background thread (APScheduler handles threading).
    Does NOT block the async event loop.
    
    Steps:
    1. Refresh offerwall cache from CINT API
    2. Mark stale surveys as inactive in MongoDB
    3. Delete inactive surveys older than 3 days
    4. Log stats
    """
    start_time = time.time()
    
    try:
        logger.info("[CintCleanup] 🔄 Starting survey pool cleanup...")
        
        # Step 1: Refresh offerwall cache
        refresh_result = _refresh_offerwall_cache()
        
        if refresh_result.get("error"):
            logger.error(f"[CintCleanup] ❌ Offerwall refresh failed: {refresh_result['error']}")
            return
        
        logger.info(
            f"[CintCleanup] 📡 Offerwall refreshed: "
            f"{refresh_result['total']} surveys, "
            f"{refresh_result.get('countries', 0)} countries"
        )
        
        # Step 2: Mark stale surveys as inactive
        live_ids = get_live_survey_ids()
        cleanup_result = _cleanup_stale_surveys_in_db(live_ids)
        
        if cleanup_result.get("error"):
            logger.warning(f"[CintCleanup] ⚠️ DB cleanup warning: {cleanup_result['error']}")
        else:
            deactivated = cleanup_result.get("deactivated", 0)
            checked = cleanup_result.get("checked", 0)
            
            if deactivated > 0:
                logger.info(
                    f"[CintCleanup] 🧹 Deactivated {deactivated}/{checked} stale surveys "
                    f"(offerwall has {len(live_ids)} live)"
                )
            else:
                logger.info(
                    f"[CintCleanup] ✅ Pool is clean — {checked} active in DB, "
                    f"{len(live_ids)} live on offerwall"
                )
        
        # Step 3: Delete old surveys (>3 days) from both CINT and CPX
        delete_result = _delete_old_surveys(max_age_days=3)
        
        if delete_result.get("error"):
            logger.warning(f"[CintCleanup] ⚠️ Delete warning: {delete_result['error']}")
        else:
            cint_del = delete_result.get("cint_deleted", 0)
            cint_orph = delete_result.get("cint_orphans", 0)
            cpx_del = delete_result.get("cpx_deleted", 0)
            
            if cint_del > 0 or cint_orph > 0 or cpx_del > 0:
                parts = []
                if cint_del > 0:
                    parts.append(f"CINT: {cint_del} old")
                if cint_orph > 0:
                    parts.append(f"{cint_orph} orphans")
                if cpx_del > 0:
                    parts.append(f"CPX: {cpx_del} old")
                logger.info(f"[CintCleanup] 🗑️ Deleted surveys >3 days — {', '.join(parts)}")
        
        elapsed = time.time() - start_time
        logger.info(f"[CintCleanup] ⏱️ Cleanup completed in {elapsed:.1f}s")
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[CintCleanup] ❌ Cleanup task failed after {elapsed:.1f}s: {e}")
        import traceback
        traceback.print_exc()


# ============================================
# ASYNC WRAPPER (for APScheduler async scheduler)
# ============================================

async def async_cint_survey_cleanup():
    """
    Async wrapper that runs the cleanup in a thread pool.
    APScheduler's AsyncIOScheduler needs async functions,
    but our cleanup is synchronous (DB + HTTP calls).
    Running in a thread prevents blocking the event loop.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_cint_survey_cleanup)


# ============================================
# MANUAL TRIGGER (for testing / admin API)
# ============================================

def trigger_cleanup_now() -> dict:
    """
    Trigger an immediate cleanup (useful for admin endpoints or testing).
    Returns the cleanup stats.
    """
    start = time.time()
    
    refresh = _refresh_offerwall_cache()
    if refresh.get("error"):
        return {"status": "error", "error": refresh["error"], "elapsed": time.time() - start}
    
    live_ids = get_live_survey_ids()
    cleanup = _cleanup_stale_surveys_in_db(live_ids)
    delete = _delete_old_surveys(max_age_days=3)
    
    return {
        "status": "ok",
        "offerwall_total": refresh["total"],
        "offerwall_countries": refresh.get("countries", 0),
        "db_checked": cleanup.get("checked", 0),
        "db_deactivated": cleanup.get("deactivated", 0),
        "cint_deleted": delete.get("cint_deleted", 0),
        "cint_orphans": delete.get("cint_orphans", 0),
        "cpx_deleted": delete.get("cpx_deleted", 0),
        "elapsed": round(time.time() - start, 2),
    }
