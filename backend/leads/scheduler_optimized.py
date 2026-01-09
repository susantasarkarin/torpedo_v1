"""
OPTIMIZED LEAD INGESTION SCHEDULER (Cost Optimized)
Integrates all cost optimization modules:
- Smart query generation (Phase 2)
- Search caching (Phase 1)
- Deduplication (Phase 1)
- URL validation (Phase 4)
- Batch enrichment (Phase 4)

Expected savings: 66% reduction in Google Cloud costs
"""

import os
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from threading import Thread, Event
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ============== CONFIGURATION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']

# Scheduler state collection
scheduler_state_collection = db['scheduler_state']
scheduler_logs_collection = db['scheduler_logs']

# Settings DB
_settings_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_settings_db = _settings_client['torpedo_settings']
_app_settings = _settings_db['app_settings']


def get_rate_limits():
    """Get rate limits from settings (legacy - returns defaults only)"""
    return {"hourly": 50, "daily": 400, "query_delay": 3, "enabled": True}


def get_optimization_settings():
    """Get cost optimization settings"""
    try:
        cfg = _app_settings.find_one({"_id": "app_config"})
        if cfg:
            return {
                # Caching
                "cache_enabled": cfg.get("search_cache_enabled", True),
                "cache_ttl_hours": cfg.get("search_cache_ttl_hours", 48),
                
                # Deduplication
                "dedup_enabled": cfg.get("dedup_enabled", True),
                
                # Smart queries
                "smart_queries_enabled": cfg.get("smart_queries_enabled", True),
                
                # URL validation
                "url_validation_enabled": cfg.get("url_validation_enabled", True),
                
                # Batch enrichment
                "batch_enrichment_enabled": cfg.get("batch_enrichment_enabled", True),
                "batch_min_size": cfg.get("batch_enrichment_min_size", 10),
            }
    except Exception:
        pass
    return {
        "cache_enabled": True,
        "cache_ttl_hours": 48,
        "dedup_enabled": True,
        "smart_queries_enabled": True,
        "url_validation_enabled": True,
        "batch_enrichment_enabled": True,
        "batch_min_size": 10
    }


# Conservative targets for $50/month budget
HOURLY_TARGET = 50
DAILY_TARGET = 400

QUERIES_PER_BATCH = 5
RESULTS_PER_QUERY = 10
BATCH_DELAY_SECONDS = 120
QUERY_DELAY_SECONDS = 3

# Classification settings
CLASSIFICATION_BATCH_SIZE = 50
CLASSIFICATION_DELAY_SECONDS = 30


# ============== SCHEDULER STATE ==============

class OptimizedSchedulerState:
    """Persistent scheduler state with optimization metrics"""
    
    def __init__(self):
        self.load_state()
    
    def load_state(self):
        """Load state from database"""
        state = scheduler_state_collection.find_one({"_id": "lead_scheduler"})
        if state:
            self.is_running = state.get("is_running", False)
            self.started_at = state.get("started_at")
            self.last_run_at = state.get("last_run_at")
            self.leads_today = state.get("leads_today", 0)
            self.leads_this_hour = state.get("leads_this_hour", 0)
            self.queries_today = state.get("queries_today", 0)
            self.current_hour = state.get("current_hour", datetime.utcnow().hour)
            self.current_day = state.get("current_day", datetime.utcnow().date().isoformat())
            self.search_config = state.get("search_config", {})
            self.error_count = state.get("error_count", 0)
            self.last_error = state.get("last_error")
            
            # Optimization metrics
            self.cache_hits_today = state.get("cache_hits_today", 0)
            self.dedup_blocked_today = state.get("dedup_blocked_today", 0)
            self.queries_saved_today = state.get("queries_saved_today", 0)
            self.urls_validated_today = state.get("urls_validated_today", 0)
            self.batch_enriched_today = state.get("batch_enriched_today", 0)
        else:
            self.reset_state()
    
    def reset_state(self):
        """Reset to default state"""
        self.is_running = False
        self.started_at = None
        self.last_run_at = None
        self.leads_today = 0
        self.leads_this_hour = 0
        self.queries_today = 0
        self.current_hour = datetime.utcnow().hour
        self.current_day = datetime.utcnow().date().isoformat()
        self.search_config = {}
        self.error_count = 0
        self.last_error = None
        
        # Optimization metrics
        self.cache_hits_today = 0
        self.dedup_blocked_today = 0
        self.queries_saved_today = 0
        self.urls_validated_today = 0
        self.batch_enriched_today = 0
        
        self.save_state()
    
    def save_state(self):
        """Persist state to database"""
        scheduler_state_collection.update_one(
            {"_id": "lead_scheduler"},
            {"$set": {
                "is_running": self.is_running,
                "started_at": self.started_at,
                "last_run_at": self.last_run_at,
                "leads_today": self.leads_today,
                "leads_this_hour": self.leads_this_hour,
                "queries_today": self.queries_today,
                "current_hour": self.current_hour,
                "current_day": self.current_day,
                "search_config": self.search_config,
                "error_count": self.error_count,
                "last_error": self.last_error,
                
                # Optimization metrics
                "cache_hits_today": self.cache_hits_today,
                "dedup_blocked_today": self.dedup_blocked_today,
                "queries_saved_today": self.queries_saved_today,
                "urls_validated_today": self.urls_validated_today,
                "batch_enriched_today": self.batch_enriched_today,
            }},
            upsert=True
        )
    
    def reset_hourly_if_needed(self):
        """Reset hourly counter if hour changed"""
        current_hour = datetime.utcnow().hour
        if current_hour != self.current_hour:
            self.leads_this_hour = 0
            self.current_hour = current_hour
            self.save_state()
    
    def reset_daily_if_needed(self):
        """Reset daily counters if day changed"""
        current_day = datetime.utcnow().date().isoformat()
        if current_day != self.current_day:
            self.leads_today = 0
            self.queries_today = 0
            self.cache_hits_today = 0
            self.dedup_blocked_today = 0
            self.queries_saved_today = 0
            self.urls_validated_today = 0
            self.batch_enriched_today = 0
            self.current_day = current_day
            self.save_state()
    
    def log_activity(self, activity_type: str, details: dict):
        """Log scheduler activity"""
        scheduler_logs_collection.insert_one({
            "timestamp": datetime.utcnow(),
            "type": activity_type,
            "details": details
        })


# Global state
scheduler_state = OptimizedSchedulerState()
stop_event = Event()
scheduler_thread: Optional[Thread] = None


# ============== SMART QUERY GENERATION ==============

async def get_optimized_queries(config: dict, count: int = 10) -> List[str]:
    """
    Generate queries using AI query generator if enabled,
    otherwise fall back to basic query generation.
    """
    settings = get_optimization_settings()
    
    if settings.get("smart_queries_enabled", True):
        try:
            from .query_generator import generate_search_plan
            
            industry = config.get("industry", "Technology")
            roles = config.get("designations", ["CEO", "CTO", "VP"])
            regions = config.get("countries", ["United States"])
            
            # Generate plan for each role
            all_queries = []
            for role in roles[:3]:  # Limit to first 3 roles
                region = regions[0] if regions else ""
                queries = generate_search_plan(
                    persona=role,
                    industry=industry,
                    location=region,
                    count=count // len(roles[:3]) + 1
                )
                all_queries.extend(queries)
            
            if all_queries:
                print(f"[Optimizer] Generated {len(all_queries)} smart queries")
                return all_queries[:count]
        
        except Exception as e:
            print(f"[Optimizer] Smart query generation failed: {e}, using fallback")
    
    # Fallback to basic generation
    return _generate_basic_queries(config, count)


def _generate_basic_queries(config: dict, count: int = 10) -> List[str]:
    """Basic query generation (fallback)"""
    queries = []
    
    designations = config.get("designations", ["CEO", "CTO", "Founder", "VP", "Director"])
    countries = config.get("countries", ["United States", "United Kingdom", "Germany"])
    
    industries = [
        "Technology", "Software", "SaaS", "FinTech", "Healthcare",
        "E-commerce", "Manufacturing", "Consulting", "Cybersecurity"
    ]
    
    for _ in range(count):
        parts = []
        
        if designations:
            parts.append(f'"{random.choice(designations)}"')
        
        if random.random() > 0.3:
            parts.append(random.choice(industries))
        
        if countries:
            parts.append(random.choice(countries))
        
        if parts:
            queries.append(" ".join(parts))
    
    return list(set(queries))[:count]


# ============== OPTIMIZED SEARCH ==============

async def run_optimized_search_batch(
    queries: List[str], 
    state: OptimizedSchedulerState
) -> Dict[str, int]:
    """
    Run search batch with full optimization stack:
    - Cache first
    - Deduplication
    - URL validation
    """
    from .ingestion import search_linkedin_leads_batch
    from .search_cache import get_cache_stats
    from .deduplication import get_dedup_stats
    from .service import import_leads
    from .models import LeadInput
    
    settings = get_optimization_settings()
    
    stats = {
        "queries_executed": 0,
        "cache_hits": 0,
        "leads_found": 0,
        "duplicates_blocked": 0,
        "leads_imported": 0,
        "urls_validated": 0,
        "invalid_urls": 0
    }
    
    all_leads = []
    seen_urls = set()
    
    for query in queries:
        if stop_event.is_set():
            break
        
        state.reset_hourly_if_needed()
        state.reset_daily_if_needed()
        
        if state.leads_this_hour >= HOURLY_TARGET:
            print(f"[Optimizer] Hourly target reached")
            break
        
        if state.leads_today >= DAILY_TARGET:
            print(f"[Optimizer] Daily target reached")
            break
        
        try:
            # Use batch search which includes caching and dedup
            result = await search_linkedin_leads_batch(
                queries=[query],
                num_results=RESULTS_PER_QUERY,
                enable_cache=settings.get("cache_enabled", True),
                enable_dedup=settings.get("dedup_enabled", True)
            )
            
            stats["queries_executed"] += 1
            stats["cache_hits"] += result.get("cache_hits", 0)
            
            leads = result.get("leads", [])
            
            # Local dedup
            for lead in leads:
                url = lead.get("linkedin_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_leads.append(lead)
                else:
                    stats["duplicates_blocked"] += 1
            
            stats["leads_found"] += len(leads)
            
            await asyncio.sleep(QUERY_DELAY_SECONDS)
            
        except Exception as e:
            state.error_count += 1
            state.last_error = str(e)
            print(f"[Optimizer] Search error: {e}")
            await asyncio.sleep(10)
    
    # Validate URLs if enabled
    if settings.get("url_validation_enabled", True) and all_leads:
        try:
            from .url_validator import filter_valid_leads
            
            valid_leads, validation_stats = await filter_valid_leads(all_leads)
            
            stats["urls_validated"] = validation_stats.get("total", 0)
            stats["invalid_urls"] = validation_stats.get("invalid", 0)
            
            all_leads = valid_leads
            print(f"[Optimizer] URL validation: {len(valid_leads)} valid, {stats['invalid_urls']} invalid")
            
        except Exception as e:
            print(f"[Optimizer] URL validation failed: {e}, using all leads")
    
    # Import validated leads
    if all_leads:
        try:
            lead_inputs = [LeadInput(**lead) for lead in all_leads]
            result = import_leads(lead_inputs)
            
            stats["leads_imported"] = result.imported
            stats["duplicates_blocked"] += result.duplicates
            
            # Update state
            state.leads_today += result.imported
            state.leads_this_hour += result.imported
            state.queries_today += stats["queries_executed"]
            state.cache_hits_today += stats["cache_hits"]
            state.dedup_blocked_today += stats["duplicates_blocked"]
            state.urls_validated_today += stats["urls_validated"]
            state.last_run_at = datetime.utcnow()
            state.save_state()
            
            state.log_activity("optimized_search", stats)
            
        except Exception as e:
            print(f"[Optimizer] Import error: {e}")
    
    return stats


# ============== OPTIMIZED CLASSIFICATION ==============

async def run_optimized_classification(
    state: OptimizedSchedulerState
) -> Dict[str, int]:
    """
    Run classification with batch API optimization.
    """
    settings = get_optimization_settings()
    
    stats = {
        "classified": 0,
        "failed": 0,
        "queued_for_batch": 0
    }
    
    if settings.get("batch_enrichment_enabled", True):
        try:
            from .batch_enrichment import (
                run_batch_enrichment_cycle,
                queue_leads_for_batch_enrichment,
                MIN_BATCH_SIZE
            )
            from bson import ObjectId
            
            # Get pending leads
            leads_raw = db['leads_raw']
            pending = list(leads_raw.find({
                "classification_status": {"$in": [None, "pending"]}
            }).limit(CLASSIFICATION_BATCH_SIZE))
            
            if len(pending) >= MIN_BATCH_SIZE:
                # Queue for batch enrichment
                lead_ids = [str(lead["_id"]) for lead in pending]
                job_id = queue_leads_for_batch_enrichment(lead_ids)
                
                stats["queued_for_batch"] = len(lead_ids)
                print(f"[Optimizer] Queued {len(lead_ids)} leads for batch enrichment")
                
                # Mark as queued
                leads_raw.update_many(
                    {"_id": {"$in": [ObjectId(lid) for lid in lead_ids]}},
                    {"$set": {"classification_status": "queued_batch"}}
                )
            
            # Run batch cycle (check/process completed batches)
            cycle_result = run_batch_enrichment_cycle()
            stats["classified"] = cycle_result.get("completed_processed", 0)
            
            state.batch_enriched_today += stats["classified"]
            state.save_state()
            
            state.log_activity("batch_enrichment", {
                "queued": stats["queued_for_batch"],
                "processed": stats["classified"],
                "submitted": cycle_result.get("batches_submitted", 0)
            })
            
        except Exception as e:
            print(f"[Optimizer] Batch enrichment error: {e}, falling back to regular")
            # Fallback to regular classification
            return await _run_regular_classification(state)
    else:
        return await _run_regular_classification(state)
    
    return stats


async def _run_regular_classification(state: OptimizedSchedulerState) -> Dict[str, int]:
    """Regular classification (fallback)"""
    from .service import classify_pending_leads
    
    try:
        success, failure = classify_pending_leads(CLASSIFICATION_BATCH_SIZE)
        
        state.log_activity("classification_batch", {
            "success": success,
            "failure": failure
        })
        
        return {"classified": success, "failed": failure, "queued_for_batch": 0}
        
    except Exception as e:
        state.error_count += 1
        state.last_error = str(e)
        return {"classified": 0, "failed": 0, "queued_for_batch": 0}


# ============== MAIN LOOP ==============

async def optimized_scheduler_loop():
    """
    Main scheduler loop with all optimizations enabled.
    """
    global scheduler_state
    
    print("[Optimizer] Starting COST-OPTIMIZED lead scheduler...")
    print(f"[Optimizer] Targets: {HOURLY_TARGET}/hour, {DAILY_TARGET}/day")
    
    settings = get_optimization_settings()
    print(f"[Optimizer] Optimizations enabled:")
    print(f"  - Caching: {settings['cache_enabled']}")
    print(f"  - Deduplication: {settings['dedup_enabled']}")
    print(f"  - Smart Queries: {settings['smart_queries_enabled']}")
    print(f"  - URL Validation: {settings['url_validation_enabled']}")
    print(f"  - Batch Enrichment: {settings['batch_enrichment_enabled']}")
    
    scheduler_state.is_running = True
    scheduler_state.started_at = datetime.utcnow()
    scheduler_state.save_state()
    
    cycle_count = 0
    
    while not stop_event.is_set():
        try:
            scheduler_state.reset_hourly_if_needed()
            scheduler_state.reset_daily_if_needed()
            
            # Check daily limit
            if scheduler_state.leads_today >= DAILY_TARGET:
                print(f"[Optimizer] Daily target reached. Waiting until midnight...")
                now = datetime.utcnow()
                tomorrow = now.replace(hour=0, minute=0, second=0) + timedelta(days=1)
                wait_seconds = (tomorrow - now).total_seconds()
                
                while wait_seconds > 0 and not stop_event.is_set():
                    await asyncio.sleep(min(60, wait_seconds))
                    wait_seconds -= 60
                continue
            
            # Check hourly limit
            if scheduler_state.leads_this_hour >= HOURLY_TARGET:
                print(f"[Optimizer] Hourly target reached. Waiting for next hour...")
                now = datetime.utcnow()
                next_hour = now.replace(minute=0, second=0) + timedelta(hours=1)
                wait_seconds = (next_hour - now).total_seconds()
                
                while wait_seconds > 0 and not stop_event.is_set():
                    await asyncio.sleep(min(60, wait_seconds))
                    wait_seconds -= 60
                continue
            
            cycle_count += 1
            print(f"\n[Optimizer] === Cycle {cycle_count} ===")
            print(f"[Optimizer] Progress: {scheduler_state.leads_today}/{DAILY_TARGET} today, {scheduler_state.leads_this_hour}/{HOURLY_TARGET} this hour")
            print(f"[Optimizer] Savings: {scheduler_state.cache_hits_today} cache hits, {scheduler_state.dedup_blocked_today} duplicates blocked")
            
            # Phase 1: Generate optimized queries
            queries = await get_optimized_queries(scheduler_state.search_config, QUERIES_PER_BATCH)
            
            # Phase 2: Optimized search
            search_stats = await run_optimized_search_batch(queries, scheduler_state)
            print(f"[Optimizer] Search: {search_stats['leads_imported']} imported, {search_stats['cache_hits']} cache hits")
            
            if stop_event.is_set():
                break
            
            # Phase 3: Optimized classification
            class_stats = await run_optimized_classification(scheduler_state)
            print(f"[Optimizer] Classification: {class_stats['classified']} done, {class_stats['queued_for_batch']} queued")
            
            if stop_event.is_set():
                break
            
            print(f"[Optimizer] Cycle complete. Pausing for {BATCH_DELAY_SECONDS}s...")
            await asyncio.sleep(BATCH_DELAY_SECONDS)
            
        except Exception as e:
            print(f"[Optimizer] Loop error: {e}")
            scheduler_state.error_count += 1
            scheduler_state.last_error = str(e)
            scheduler_state.save_state()
            await asyncio.sleep(30)
    
    scheduler_state.is_running = False
    scheduler_state.save_state()
    print("[Optimizer] Scheduler stopped.")


def _run_async_loop():
    """Run async scheduler in thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(optimized_scheduler_loop())
    finally:
        loop.close()


# ============== PUBLIC API ==============

def start_optimized_scheduler(config: Optional[dict] = None) -> dict:
    """Start the cost-optimized scheduler."""
    global scheduler_thread, scheduler_state, stop_event
    
    if scheduler_state.is_running:
        return {
            "success": False,
            "message": "Scheduler already running",
            "status": get_optimized_status()
        }
    
    stop_event.clear()
    
    if config:
        scheduler_state.search_config = config
        scheduler_state.save_state()
    
    scheduler_thread = Thread(target=_run_async_loop, daemon=True)
    scheduler_thread.start()
    
    return {
        "success": True,
        "message": "Cost-optimized scheduler started",
        "optimizations": get_optimization_settings()
    }


def stop_optimized_scheduler() -> dict:
    """Stop the scheduler."""
    global stop_event, scheduler_state
    
    if not scheduler_state.is_running:
        return {"success": False, "message": "Scheduler not running"}
    
    stop_event.set()
    
    if scheduler_thread:
        scheduler_thread.join(timeout=5)
    
    scheduler_state.is_running = False
    scheduler_state.save_state()
    
    return {"success": True, "message": "Scheduler stopped"}


def get_optimized_status() -> dict:
    """Get scheduler status with optimization metrics."""
    scheduler_state.load_state()
    
    return {
        "is_running": scheduler_state.is_running,
        "started_at": scheduler_state.started_at.isoformat() if scheduler_state.started_at else None,
        "last_run_at": scheduler_state.last_run_at.isoformat() if scheduler_state.last_run_at else None,
        
        # Progress
        "leads_today": scheduler_state.leads_today,
        "leads_this_hour": scheduler_state.leads_this_hour,
        "queries_today": scheduler_state.queries_today,
        
        "targets": {
            "hourly": HOURLY_TARGET,
            "daily": DAILY_TARGET
        },
        
        "progress": {
            "hourly_percent": round((scheduler_state.leads_this_hour / HOURLY_TARGET) * 100, 1),
            "daily_percent": round((scheduler_state.leads_today / DAILY_TARGET) * 100, 1)
        },
        
        # Cost optimization metrics
        "cost_savings": {
            "cache_hits_today": scheduler_state.cache_hits_today,
            "duplicates_blocked_today": scheduler_state.dedup_blocked_today,
            "queries_saved_today": scheduler_state.queries_saved_today,
            "urls_validated_today": scheduler_state.urls_validated_today,
            "batch_enriched_today": scheduler_state.batch_enriched_today,
            
            # Estimated savings (approximate)
            "estimated_cse_savings_inr": scheduler_state.cache_hits_today * 0.42,  # ₹0.42 per query saved
            "estimated_openai_savings_inr": scheduler_state.batch_enriched_today * 0.01,  # ₹0.01 per batch lead
        },
        
        "optimizations": get_optimization_settings(),
        "search_config": scheduler_state.search_config,
        "error_count": scheduler_state.error_count,
        "last_error": scheduler_state.last_error
    }


# ============== CLI ==============

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Cost-Optimized Lead Scheduler")
        print("\nUsage:")
        print("  python scheduler_optimized.py start    # Start scheduler")
        print("  python scheduler_optimized.py stop     # Stop scheduler")
        print("  python scheduler_optimized.py status   # Show status")
        print("\nExpected savings: 66% reduction in Google Cloud costs")
    
    elif sys.argv[1] == "start":
        result = start_optimized_scheduler()
        print(f"\n{result['message']}")
        if result.get("optimizations"):
            print("\nOptimizations:")
            for k, v in result["optimizations"].items():
                print(f"  {k}: {v}")
    
    elif sys.argv[1] == "stop":
        result = stop_optimized_scheduler()
        print(result["message"])
    
    elif sys.argv[1] == "status":
        status = get_optimized_status()
        print("\n=== Scheduler Status ===")
        print(f"  Running: {status['is_running']}")
        print(f"  Leads Today: {status['leads_today']}/{status['targets']['daily']}")
        print(f"\n=== Cost Savings Today ===")
        savings = status.get("cost_savings", {})
        print(f"  Cache Hits: {savings.get('cache_hits_today', 0)}")
        print(f"  Duplicates Blocked: {savings.get('duplicates_blocked_today', 0)}")
        print(f"  Batch Enriched: {savings.get('batch_enriched_today', 0)}")
        print(f"  Estimated CSE Savings: ₹{savings.get('estimated_cse_savings_inr', 0):.2f}")
