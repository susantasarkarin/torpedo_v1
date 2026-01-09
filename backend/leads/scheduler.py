"""
LEAD INGESTION SCHEDULER
Automated lead search and validation loop
Target: 500 leads/hour (10,000 leads/day)
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

# ============== SCHEDULER CONSTANTS ==============

# MongoDB connection for dynamic rate limits
_settings_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_settings_db = _settings_client['torpedo_settings']
_app_settings = _settings_db['app_settings']

def get_rate_limits():
    """Get rate limits from settings (legacy - returns defaults only)"""
    return {"hourly": 50, "daily": 400, "query_delay": 3, "enabled": True}

# Conservative defaults for $50/month budget (400 queries/day)
HOURLY_TARGET = 50  # Reduced from 500
DAILY_TARGET = 400  # Reduced from 10000 for cost control

# Google CSE limits: 100 queries/day free, then $5 per 1000 queries
# Budget: $50/month = ~10,000 paid queries + 3,000 free = 13,000/month = ~430/day
QUERIES_PER_BATCH = 5  # Reduced from 10
RESULTS_PER_QUERY = 10  # Max results per Google CSE query
BATCH_DELAY_SECONDS = 120  # Increased pause between batches (2 minutes)
QUERY_DELAY_SECONDS = 3  # Increased delay between queries

# Classification rate limiting
CLASSIFICATION_BATCH_SIZE = 50  # Leads to classify per batch
CLASSIFICATION_DELAY_SECONDS = 30  # Pause between classification batches

# ============== SCHEDULER STATE ==============

class LeadSchedulerState:
    """Persistent scheduler state stored in MongoDB"""
    
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
                "last_error": self.last_error
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
            self.current_day = current_day
            self.save_state()
    
    def log_activity(self, activity_type: str, details: dict):
        """Log scheduler activity"""
        scheduler_logs_collection.insert_one({
            "timestamp": datetime.utcnow(),
            "type": activity_type,
            "details": details
        })


# Global state instance
scheduler_state = LeadSchedulerState()
stop_event = Event()
scheduler_thread: Optional[Thread] = None


# ============== SEARCH QUERY GENERATOR ==============

# Industry modifiers for query variety
INDUSTRIES = [
    "Technology", "Software", "SaaS", "IT", "Finance", "Banking", "FinTech",
    "Healthcare", "HealthTech", "Biotech", "Pharmaceuticals", "Manufacturing",
    "Retail", "E-commerce", "Marketing", "Digital Marketing", "Advertising",
    "Consulting", "Management Consulting", "Telecommunications", "Insurance",
    "Real Estate", "PropTech", "Automotive", "Energy", "CleanTech", "Education",
    "EdTech", "Media", "Entertainment", "Logistics", "Supply Chain", "FMCG",
    "Consumer Goods", "B2B", "Enterprise", "Startup", "Venture Capital",
    "Private Equity", "Investment Banking", "Wealth Management", "HR", "HRTech",
    "Legal", "LegalTech", "Construction", "Architecture", "Design", "Gaming",
    "Cybersecurity", "Cloud", "AI", "Machine Learning", "Data Science",
    "Analytics", "IoT", "Blockchain", "Crypto", "Web3"
]

# Seniority variations for different queries
SENIORITY_KEYWORDS = {
    "Owner": ["Owner", "Business Owner", "Proprietor"],
    "Founder": ["Founder", "Co-Founder", "Founding Partner"],
    "CXO": ["CEO", "CTO", "CFO", "COO", "CMO", "CRO", "CIO", "CHRO", "CPO"],
    "VP": ["VP", "Vice President", "SVP", "EVP"],
    "Director": ["Director", "Head of", "Managing Director"],
    "Manager": ["Manager", "Team Lead", "General Manager"],
    "Senior": ["Senior", "Lead", "Principal", "Staff"]
}

# Regions/Countries for geo-targeting
REGIONS = [
    "United States", "USA", "California", "New York", "Texas", "Florida",
    "United Kingdom", "UK", "London", "Germany", "France", "Netherlands",
    "Canada", "Toronto", "Vancouver", "Australia", "Sydney", "Melbourne",
    "Singapore", "Hong Kong", "Dubai", "UAE", "India", "Bangalore", "Mumbai",
    "Japan", "Tokyo", "South Korea", "Seoul", "Brazil", "Sao Paulo"
]


def generate_search_queries(config: dict, count: int = 10) -> List[str]:
    """
    Generate diverse search queries based on configuration.
    
    Args:
        config: Search configuration with designations, countries, seniorities
        count: Number of queries to generate
        
    Returns:
        List of search query strings
    """
    queries = []
    
    designations = config.get("designations", [])
    countries = config.get("countries", [])
    seniorities = config.get("seniorities", [])
    custom_query = config.get("custom_query", "")
    
    # If no config provided, use defaults
    if not designations and not seniorities:
        designations = ["CEO", "CTO", "Founder", "VP", "Director", "Manager"]
    
    if not countries:
        countries = random.sample(REGIONS, min(5, len(REGIONS)))
    
    # Generate query combinations
    for _ in range(count):
        parts = []
        
        # Random designation
        if designations:
            designation = random.choice(designations)
            parts.append(f'"{designation}"')
        elif seniorities:
            seniority = random.choice(seniorities)
            keywords = SENIORITY_KEYWORDS.get(seniority, [seniority])
            parts.append(f'"{random.choice(keywords)}"')
        
        # Random industry
        if random.random() > 0.3:  # 70% chance to add industry
            parts.append(random.choice(INDUSTRIES))
        
        # Random country/region
        if countries:
            parts.append(random.choice(countries))
        
        # Custom query addition
        if custom_query:
            parts.append(custom_query)
        
        if parts:
            queries.append(" ".join(parts))
    
    # Deduplicate and shuffle
    queries = list(set(queries))
    random.shuffle(queries)
    
    return queries[:count]


# ============== MAIN SCHEDULER LOOP ==============

async def run_search_batch(queries: List[str], state: LeadSchedulerState) -> int:
    """
    Run a batch of search queries and import leads.
    
    Returns:
        Number of new leads imported
    """
    from .ingestion import search_linkedin_leads
    from .service import import_leads
    from .models import LeadInput
    
    total_imported = 0
    seen_urls = set()
    
    for query in queries:
        if stop_event.is_set():
            break
        
        # Check if we've hit hourly/daily limits
        state.reset_hourly_if_needed()
        state.reset_daily_if_needed()
        
        if state.leads_this_hour >= HOURLY_TARGET:
            print(f"[Scheduler] Hourly target reached ({HOURLY_TARGET}), waiting...")
            return total_imported
        
        if state.leads_today >= DAILY_TARGET:
            print(f"[Scheduler] Daily target reached ({DAILY_TARGET}), pausing until tomorrow...")
            return total_imported
        
        try:
            # Search with pagination
            leads_found = []
            for start_index in range(1, 91, 10):  # Up to 100 results (CSE limit)
                if stop_event.is_set():
                    break
                
                results = await search_linkedin_leads(
                    query=query,
                    num_results=RESULTS_PER_QUERY,
                    start=start_index
                )
                
                if not results:
                    break
                
                # Deduplicate
                for lead in results:
                    url = lead.get("linkedin_url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        leads_found.append(lead)
                
                # Delay between pagination requests
                await asyncio.sleep(1)
            
            if leads_found:
                # Import leads
                lead_inputs = [LeadInput(**lead) for lead in leads_found]
                result = import_leads(lead_inputs)
                
                imported = result.imported
                total_imported += imported
                
                # Update state counters
                state.leads_today += imported
                state.leads_this_hour += imported
                state.queries_today += 1
                state.last_run_at = datetime.utcnow()
                state.save_state()
                
                state.log_activity("search_batch", {
                    "query": query,
                    "found": len(leads_found),
                    "imported": imported,
                    "duplicates": result.duplicates
                })
                
                print(f"[Scheduler] Query '{query[:50]}...' - Found: {len(leads_found)}, Imported: {imported}")
            
            # Rate limit delay between queries
            await asyncio.sleep(QUERY_DELAY_SECONDS)
            
        except Exception as e:
            state.error_count += 1
            state.last_error = str(e)
            state.save_state()
            
            state.log_activity("search_error", {
                "query": query,
                "error": str(e)
            })
            
            print(f"[Scheduler] Error in query '{query[:30]}...': {e}")
            
            # Back off on errors
            if "quota" in str(e).lower() or "limit" in str(e).lower():
                print("[Scheduler] Rate limit hit, backing off for 5 minutes...")
                await asyncio.sleep(300)
            else:
                await asyncio.sleep(10)
    
    return total_imported


async def run_classification_batch(state: LeadSchedulerState) -> tuple:
    """
    Classify pending leads in batch.
    
    Returns:
        (success_count, failure_count)
    """
    from .service import classify_pending_leads
    
    try:
        success, failure = classify_pending_leads(CLASSIFICATION_BATCH_SIZE)
        
        state.log_activity("classification_batch", {
            "success": success,
            "failure": failure
        })
        
        print(f"[Scheduler] Classified {success} leads, {failure} failures")
        
        return success, failure
    
    except Exception as e:
        state.error_count += 1
        state.last_error = str(e)
        state.save_state()
        
        print(f"[Scheduler] Classification error: {e}")
        return 0, 0


async def scheduler_loop():
    """
    Main scheduler loop - runs continuously until stopped.
    Alternates between search and classification.
    """
    global scheduler_state
    
    print("[Scheduler] Starting lead ingestion scheduler...")
    print(f"[Scheduler] Targets: {HOURLY_TARGET}/hour, {DAILY_TARGET}/day")
    
    scheduler_state.is_running = True
    scheduler_state.started_at = datetime.utcnow()
    scheduler_state.save_state()
    
    cycle_count = 0
    
    while not stop_event.is_set():
        try:
            scheduler_state.reset_hourly_if_needed()
            scheduler_state.reset_daily_if_needed()
            
            # Check if we've reached daily target
            if scheduler_state.leads_today >= DAILY_TARGET:
                print(f"[Scheduler] Daily target reached. Waiting until midnight...")
                # Calculate time until midnight UTC
                now = datetime.utcnow()
                tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                wait_seconds = (tomorrow - now).total_seconds()
                
                # Wait in chunks to allow stopping
                while wait_seconds > 0 and not stop_event.is_set():
                    await asyncio.sleep(min(60, wait_seconds))
                    wait_seconds -= 60
                continue
            
            # Check if we've reached hourly target
            if scheduler_state.leads_this_hour >= HOURLY_TARGET:
                print(f"[Scheduler] Hourly target reached. Waiting for next hour...")
                # Wait until next hour
                now = datetime.utcnow()
                next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                wait_seconds = (next_hour - now).total_seconds()
                
                while wait_seconds > 0 and not stop_event.is_set():
                    await asyncio.sleep(min(60, wait_seconds))
                    wait_seconds -= 60
                continue
            
            cycle_count += 1
            print(f"\n[Scheduler] === Cycle {cycle_count} ===")
            print(f"[Scheduler] Today: {scheduler_state.leads_today}/{DAILY_TARGET}, This hour: {scheduler_state.leads_this_hour}/{HOURLY_TARGET}")
            
            # Phase 1: Search for new leads
            queries = generate_search_queries(scheduler_state.search_config, QUERIES_PER_BATCH)
            imported = await run_search_batch(queries, scheduler_state)
            
            if stop_event.is_set():
                break
            
            # Phase 2: Classify pending leads
            await run_classification_batch(scheduler_state)
            
            if stop_event.is_set():
                break
            
            # Pause between cycles
            print(f"[Scheduler] Cycle complete. Pausing for {BATCH_DELAY_SECONDS}s...")
            await asyncio.sleep(BATCH_DELAY_SECONDS)
            
        except Exception as e:
            print(f"[Scheduler] Loop error: {e}")
            scheduler_state.error_count += 1
            scheduler_state.last_error = str(e)
            scheduler_state.save_state()
            await asyncio.sleep(30)  # Back off on errors
    
    scheduler_state.is_running = False
    scheduler_state.save_state()
    print("[Scheduler] Scheduler stopped.")


def _run_async_loop():
    """Run the async scheduler in a separate thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(scheduler_loop())
    finally:
        loop.close()


# ============== PUBLIC API ==============

def start_scheduler(config: Optional[dict] = None) -> dict:
    """
    Start the lead scheduler.
    
    Args:
        config: Optional search configuration
            - designations: List of job titles to search
            - countries: List of countries/regions
            - seniorities: List of seniority levels
            - custom_query: Additional search terms
            
    Returns:
        Status dict
    """
    global scheduler_thread, scheduler_state, stop_event
    
    if scheduler_state.is_running:
        return {
            "success": False,
            "message": "Scheduler is already running",
            "status": get_scheduler_status()
        }
    
    # Reset stop event
    stop_event.clear()
    
    # Update config if provided
    if config:
        scheduler_state.search_config = config
        scheduler_state.save_state()
    
    # Start scheduler in background thread
    scheduler_thread = Thread(target=_run_async_loop, daemon=True)
    scheduler_thread.start()
    
    return {
        "success": True,
        "message": "Scheduler started",
        "targets": {
            "hourly": HOURLY_TARGET,
            "daily": DAILY_TARGET
        }
    }


def stop_scheduler() -> dict:
    """
    Stop the lead scheduler.
    
    Returns:
        Status dict
    """
    global stop_event, scheduler_state
    
    if not scheduler_state.is_running:
        return {
            "success": False,
            "message": "Scheduler is not running"
        }
    
    stop_event.set()
    
    # Give it a moment to stop gracefully
    if scheduler_thread:
        scheduler_thread.join(timeout=5)
    
    scheduler_state.is_running = False
    scheduler_state.save_state()
    
    return {
        "success": True,
        "message": "Scheduler stopped",
        "status": get_scheduler_status()
    }


def get_scheduler_status() -> dict:
    """
    Get current scheduler status.
    
    Returns:
        Status dict with all metrics
    """
    scheduler_state.load_state()  # Refresh from DB
    
    return {
        "is_running": scheduler_state.is_running,
        "started_at": scheduler_state.started_at.isoformat() if scheduler_state.started_at else None,
        "last_run_at": scheduler_state.last_run_at.isoformat() if scheduler_state.last_run_at else None,
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
        "search_config": scheduler_state.search_config,
        "error_count": scheduler_state.error_count,
        "last_error": scheduler_state.last_error
    }


def get_scheduler_logs(limit: int = 100) -> List[dict]:
    """
    Get recent scheduler logs.
    
    Args:
        limit: Max number of logs to return
        
    Returns:
        List of log entries
    """
    logs = list(scheduler_logs_collection.find()
                .sort("timestamp", -1)
                .limit(limit))
    
    for log in logs:
        log["_id"] = str(log["_id"])
        if log.get("timestamp"):
            log["timestamp"] = log["timestamp"].isoformat()
    
    return logs


def update_scheduler_config(config: dict) -> dict:
    """
    Update scheduler search configuration.
    
    Args:
        config: New search configuration
        
    Returns:
        Status dict
    """
    global scheduler_state
    
    scheduler_state.search_config = config
    scheduler_state.save_state()
    
    return {
        "success": True,
        "message": "Configuration updated",
        "config": config
    }
