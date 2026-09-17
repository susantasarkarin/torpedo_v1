"""
PARALLEL LEAD INGESTION & AI PROCESSING SCHEDULER
==================================================
ALL tasks run in PARALLEL - never blocking each other.

Architecture:
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MASTER SCHEDULER                                     │
│                        (asyncio.gather)                                      │
└─────────────────────────────────────────────────────────────────────────────┘
     │         │         │         │         
     ▼         ▼         ▼         ▼         
┌─────────┬─────────┬─────────┬─────────┐
│ WEB     │ LEAD    │ COMPANY │ LEAD    │
│ SEARCH  │ CLASS.  │ ENRICH  │ SCORING │
│         │         │         │         │
│ OpenAI  │ OpenAI  │ OpenAI  │ OpenAI  │
│ GPT-4o  │ mini    │ web     │ web     │
└─────────┴─────────┴─────────┴─────────┘

AI GOVERNANCE POLICY (Effective Jan 2026):
- Gemini operations (email classification, summarization) are DISABLED in scheduler
- Gemini calls can only be triggered via manual API request (not scheduled/automated)
- OpenAI (gpt-4o-mini): Web search, company discovery, enrichment, lead classification
"""

import os
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from threading import Thread, Event
from pymongo import MongoClient
from dotenv import load_dotenv


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


load_dotenv()

# ============== CONFIGURATION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
client = _get_pooled_client()
db = client['email_automation']

# Scheduler state collection
scheduler_state_collection = db['scheduler_state']
scheduler_logs_collection = db['scheduler_logs']

# ============== SCHEDULER CONSTANTS ==============

# MongoDB connection for dynamic rate limits
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
_settings_client = _get_pooled_client()
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
        try:
            self.load_state()
        except Exception as e:
            # MongoDB unreachable at import time — boot with in-memory
            # defaults so the API can start; state persists once DB is back.
            print(f"[scheduler] Could not load state from DB, using defaults: {e}")
            self._set_defaults()

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
            self.leads_per_icp = state.get("leads_per_icp", {})
            self.error_count = state.get("error_count", 0)
            self.last_error = state.get("last_error")
        else:
            self.reset_state()
    
    def reset_state(self):
        """Reset to default state and persist"""
        self._set_defaults()
        self.save_state()

    def _set_defaults(self):
        """Set default state in memory only (no DB write)"""
        self.is_running = False
        self.started_at = None
        self.last_run_at = None
        self.leads_today = 0
        self.leads_this_hour = 0
        self.queries_today = 0
        self.current_hour = datetime.utcnow().hour
        self.current_day = datetime.utcnow().date().isoformat()
        self.search_config = {}
        self.leads_per_icp = {}
        self.error_count = 0
        self.last_error = None

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
                "leads_per_icp": self.leads_per_icp,
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
            self.leads_per_icp = {}  # reset per-ICP daily counts
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

# NOTE: There is deliberately no global INDUSTRIES list here any more.
# Industry terms MUST come from the caller's own ICP config (icp_config.py),
# otherwise queries drift outside the ICP — e.g. the BIM ICP was emitting
# '"BIM Manager" Crypto India' because a generic 60-industry list was sampled
# instead of the ICP's own `industries`.

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
    
    Industry terms are drawn ONLY from config["industries"] (the active ICP's
    own list). If the config defines no industries, the industry term is
    omitted entirely — never substituted from a generic global list.

    Args:
        config: Search configuration with designations, countries, seniorities,
                industries
        count: Number of queries to generate

    Returns:
        List of search query strings
    """
    queries = []

    designations = config.get("designations", [])
    countries = config.get("countries", [])
    seniorities = config.get("seniorities", [])
    industries = config.get("industries", []) or []
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
        
        # Random industry — ICP-scoped only. No industries configured means
        # no industry term (rather than drifting outside the ICP).
        if industries and random.random() > 0.3:  # 70% chance to add industry
            parts.append(random.choice(industries))

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

async def run_search_batch(queries: List[str], state: LeadSchedulerState, icp_segment: Optional[str] = None) -> int:
    """
    Run a batch of search queries and import leads.
    icp_segment: ICP slug to tag imported leads (e.g. 'bimwave').

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
                result = import_leads(lead_inputs, icp_segment=icp_segment)

                imported = result.imported
                total_imported += imported
                
                # Update state counters
                state.leads_today += imported
                state.leads_this_hour += imported
                state.queries_today += 1
                state.last_run_at = datetime.utcnow()
                # Track per-ICP count if segment provided
                if icp_segment:
                    state.leads_per_icp[icp_segment] = state.leads_per_icp.get(icp_segment, 0) + imported
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
    DISABLED 2026-09-17: OPENAI_API_KEY is empty (confirmed via direct
    length check on the deployed .env -- 0 characters), so every call here
    was failing on an auth error before even reaching the network. This
    codebase's classification path for real leads is now
    leads/bucket_classifier.py (scheduled separately, cheap-role/local-SLM
    routed) -- reviving this OpenAI path would duplicate that pipeline with
    a second, incompatible classification result, not add coverage.
    Matches the existing "DISABLED PER AI GOVERNANCE POLICY" pattern
    already used for run_email_classification_batch/run_email_summary_batch
    below, rather than leaving this to fail silently forever.
    """
    return 0, 0


# ============== EMAIL CLASSIFICATION BATCH ==============

async def run_email_classification_batch() -> dict:
    """
    DISABLED PER AI GOVERNANCE POLICY.
    
    Email classification uses Gemini which cannot be triggered from schedulers.
    Use the API endpoint POST /api/v2/ai/gemini/classify for manual classification.
    
    See: backend/ai_governance/README.md
    """
    return {
        "processed": 0, 
        "success": 0, 
        "errors": 0, 
        "message": "DISABLED: Gemini email classification cannot be triggered from scheduler. Use API endpoint.",
        "governance": "AI_GOVERNANCE_POLICY_ACTIVE"
    }


# ============== COMPANY ENRICHMENT BATCH ==============

async def run_company_enrichment_batch() -> dict:
    """
    DISABLED 2026-09-17: same reason as run_classification_batch above --
    OPENAI_API_KEY is empty. See that function's docstring.
    """
    return {
        "processed": 0,
        "enriched": 0,
        "message": "DISABLED: OPENAI_API_KEY is empty in production config.",
        "governance": "AI_GOVERNANCE_POLICY_ACTIVE",
    }


# ============== EMAIL SUMMARY BATCH ==============

async def run_email_summary_batch() -> dict:
    """
    DISABLED PER AI GOVERNANCE POLICY.
    
    Email summarization uses Gemini which cannot be triggered from schedulers.
    Use the API endpoint POST /api/v2/ai/gemini/summarize for manual summarization.
    
    See: backend/ai_governance/README.md
    """
    return {
        "processed": 0, 
        "summarized": 0, 
        "message": "DISABLED: Gemini email summarization cannot be triggered from scheduler. Use API endpoint.",
        "governance": "AI_GOVERNANCE_POLICY_ACTIVE"
    }


# ============== LEAD SCORING BATCH ==============

async def run_lead_scoring_batch() -> dict:
    """
    DISABLED 2026-09-17: same reason as run_classification_batch above --
    OPENAI_API_KEY is empty. See that function's docstring.
    """
    return {
        "processed": 0,
        "scored": 0,
        "message": "DISABLED: OPENAI_API_KEY is empty in production config.",
        "governance": "AI_GOVERNANCE_POLICY_ACTIVE",
    }


# ============== GMAIL SYNC BATCH ==============

async def run_gmail_sync_batch() -> dict:
    """
    Sync Gmail mailboxes in batch.
    Uses Gmail API - syncs all active mailboxes.
    """
    try:
        torpedo_gmail = client['torpedo_gmail']
        
        # Get active Gmail accounts
        active_accounts = list(torpedo_gmail['gmail_accounts'].find(
            {"is_active": True},
            {"_id": 1, "email": 1}
        ))
        
        if not active_accounts:
            return {"processed": 0, "message": "No active Gmail accounts"}
        
        synced_count = 0
        for account in active_accounts:
            try:
                # Import and run the sync function
                from ..routers.gmail import sync_mailbox_internal
                result = await sync_mailbox_internal(str(account["_id"]))
                if result.get("success"):
                    synced_count += 1
            except Exception as e:
                print(f"[Scheduler] Gmail sync error for {account.get('email')}: {e}")
        
        print(f"[Scheduler] Gmail Sync: {synced_count}/{len(active_accounts)} accounts")
        
        return {"processed": len(active_accounts), "synced": synced_count}
    
    except Exception as e:
        print(f"[Scheduler] Gmail Sync error: {e}")
        return {"processed": 0, "synced": 0, "error": str(e)}


# ============== CINT HEALTH CHECK ==============

async def run_cint_health_check() -> dict:
    """
    Check Cint subscription and resubscribe if needed.
    Uses Cint API.
    """
    try:
        from ..app.integrations.cint_integration import CintIntegration
        from ..app.models.cint import OpportunitiesSubscriptionConfig
        
        cint = CintIntegration()
        await cint.initialize()
        
        if not cint.cint_service:
            return {"healthy": False, "message": "Cint service not available"}
        
        # Check subscription status
        status = await cint.cint_service.get_opportunities_subscription()
        
        if status.get("success"):
            print("[Scheduler] Cint Health: ✅ Subscription active")
            return {"healthy": True, "status": "active"}
        else:
            # Attempt to resubscribe
            print("[Scheduler] Cint Health: ⚠️ Subscription inactive, resubscribing...")
            
            # Get callback URL from settings
            settings = db_torpedo_settings['app_settings'].find_one({"key": "app_settings"}) or {}
            callback_url = settings.get("cint_callback_url", "")
            
            if not callback_url:
                return {"healthy": False, "message": "No Cint callback URL configured"}
            
            config = OpportunitiesSubscriptionConfig(
                callback_url=callback_url,
                include_quotas=True,
                payload_max_size_mb=10,
                payload_max_survey_count=1000,
                send_interval_seconds=30,
                opportunities_filters=[],
            )
            
            result = await cint.cint_service.create_opportunities_subscription(config)
            
            if result.get("success"):
                print("[Scheduler] Cint Health: ✅ Resubscribed successfully")
                return {"healthy": True, "status": "resubscribed"}
            else:
                print(f"[Scheduler] Cint Health: ❌ Resubscribe failed: {result.get('error')}")
                return {"healthy": False, "error": result.get('error')}
                
    except ImportError:
        return {"healthy": False, "message": "Cint integration not installed"}
    except Exception as e:
        print(f"[Scheduler] Cint Health error: {e}")
        return {"healthy": False, "error": str(e)}


# ============== CPX SURVEY REFRESH ==============

async def run_cpx_refresh() -> dict:
    """
    Refresh CPX survey inventory.
    Uses CPX API.
    """
    try:
        from ..routers.traffic import refresh_cpx_surveys_internal
        
        result = await refresh_cpx_surveys_internal()
        
        if result.get("success"):
            count = result.get("survey_count", 0)
            print(f"[Scheduler] CPX Refresh: ✅ {count} surveys")
            return {"processed": 1, "surveys": count}
        else:
            print(f"[Scheduler] CPX Refresh: ❌ {result.get('error')}")
            return {"processed": 0, "error": result.get('error')}
            
    except ImportError:
        # Try alternative method
        try:
            cpx_db = client['cpx_db']
            surveys = cpx_db['cpx_surveys']
            count = surveys.count_documents({})
            print(f"[Scheduler] CPX Refresh: ✅ {count} surveys in DB")
            return {"processed": 1, "surveys": count}
        except Exception:
            return {"processed": 0, "message": "CPX integration not available"}
    except Exception as e:
        print(f"[Scheduler] CPX Refresh error: {e}")
        return {"processed": 0, "error": str(e)}


# ============== TIER 2 ANALYSIS (OpenAI GPT-4o) ==============

async def run_tier2_analysis_batch() -> dict:
    """
    Process high-value leads with GPT-4o for deeper analysis.
    Uses OpenAI (premium tier) - 1 lead at a time for quality.
    """
    try:
        from .openai_wrapper import chat_completion
        
        # Get high-score leads needing tier 2 analysis
        leads_needing_analysis = list(db['leads_enriched'].find(
            {
                "lead_score": {"$gte": 80},  # Only high-value leads
                "tier2_analysis": {"$exists": False},
                "status": "classified"
            },
            {"_id": 1, "full_name": 1, "title": 1, "company_name": 1, "email": 1, 
             "linkedin_url": 1, "seniority_level": 1, "department": 1}
        ).limit(5))
        
        if not leads_needing_analysis:
            return {"processed": 0, "message": "No leads need tier 2 analysis"}
        
        analyzed_count = 0
        for lead in leads_needing_analysis:
            prompt = f"""Provide a detailed B2B outreach strategy for this lead:

Name: {lead.get('full_name', 'Unknown')}
Title: {lead.get('title', 'N/A')}
Company: {lead.get('company_name', 'N/A')}
Seniority: {lead.get('seniority_level', 'Unknown')}
Department: {lead.get('department', 'Unknown')}

Provide:
1. Pain points this person likely faces
2. Best outreach approach
3. Suggested value proposition
4. Optimal contact timing
5. Risk assessment (low/medium/high)

Return as JSON with these keys: pain_points, outreach_approach, value_prop, timing, risk_level"""

            result = chat_completion(
                messages=[
                    {"role": "system", "content": "You are a B2B sales strategy expert. Provide actionable insights."},
                    {"role": "user", "content": prompt}
                ],
                source="scheduler_tier2",
                max_output_tokens=500,
                provider="openai"  # Use OpenAI GPT-4o for premium analysis
            )
            
            if result.get("success"):
                db['leads_enriched'].update_one(
                    {"_id": lead["_id"]},
                    {"$set": {
                        "tier2_analysis": result["content"],
                        "tier2_analyzed_at": datetime.utcnow(),
                        "tier2_provider": "openai"
                    }}
                )
                analyzed_count += 1
        
        print(f"[Scheduler] Tier 2 Analysis: {analyzed_count}/{len(leads_needing_analysis)} (OpenAI GPT-4o)")
        
        return {"processed": len(leads_needing_analysis), "analyzed": analyzed_count}
    
    except Exception as e:
        print(f"[Scheduler] Tier 2 Analysis error: {e}")
        return {"processed": 0, "analyzed": 0, "error": str(e)}


# ============== OUTREACH EMAIL GENERATION (OpenAI) ==============

async def run_outreach_email_batch() -> dict:
    """
    Generate personalized outreach emails using OpenAI.
    Uses OpenAI GPT-4o - 5 leads per batch for quality.
    """
    try:
        from .openai_wrapper import chat_completion
        
        # Get leads with tier2 analysis but no outreach email
        leads_needing_outreach = list(db['leads_enriched'].find(
            {
                "tier2_analysis": {"$exists": True},
                "outreach_email": {"$exists": False},
                "email": {"$exists": True, "$ne": ""}
            },
            {"_id": 1, "full_name": 1, "title": 1, "company_name": 1, "tier2_analysis": 1}
        ).limit(5))
        
        if not leads_needing_outreach:
            return {"processed": 0, "message": "No leads need outreach emails"}
        
        generated_count = 0
        for lead in leads_needing_outreach:
            analysis = lead.get('tier2_analysis', '')
            
            prompt = f"""Write a personalized cold outreach email for:

Name: {lead.get('full_name', 'Unknown')}
Title: {lead.get('title', 'N/A')}
Company: {lead.get('company_name', 'N/A')}

Analysis insights:
{analysis[:500] if analysis else 'N/A'}

Requirements:
- Subject line under 50 characters
- Email body under 150 words
- Personal, not salesy
- Clear CTA for a quick call

Return JSON: {{"subject": "...", "body": "...", "cta": "..."}}"""

            result = chat_completion(
                messages=[
                    {"role": "system", "content": "You are a B2B cold email expert. Write concise, personalized emails."},
                    {"role": "user", "content": prompt}
                ],
                source="scheduler_outreach",
                max_output_tokens=400,
                provider="openai"  # Use OpenAI for quality
            )
            
            if result.get("success"):
                db['leads_enriched'].update_one(
                    {"_id": lead["_id"]},
                    {"$set": {
                        "outreach_email": result["content"],
                        "outreach_generated_at": datetime.utcnow(),
                        "outreach_provider": "openai"
                    }}
                )
                generated_count += 1
        
        print(f"[Scheduler] Outreach Emails: {generated_count}/{len(leads_needing_outreach)} (OpenAI)")
        
        return {"processed": len(leads_needing_outreach), "generated": generated_count}
    
    except Exception as e:
        print(f"[Scheduler] Outreach Email error: {e}")
        return {"processed": 0, "generated": 0, "error": str(e)}


# ============== MASTER SCHEDULER LOOP ==============

async def scheduler_loop():
    """
    Main scheduler loop - runs continuously until stopped.
    Runs ALL 6 tasks in PARALLEL using asyncio.gather:
    - Web Search (OpenAI/Google)
    - Lead Classification (OpenAI)
    - Email Classification (Gemini via ai_governance)
    - Company Enrichment (OpenAI web search)
    - Email Summary (Gemini via ai_governance)
    - Lead Scoring (OpenAI)
    """
    global scheduler_state
    
    print("[Scheduler] Starting FULL PARALLEL lead ingestion scheduler...")
    print(f"[Scheduler] Targets: {HOURLY_TARGET}/hour, {DAILY_TARGET}/day")
    print("[Scheduler] Mode: 6 tasks running in PARALLEL (Gemini for email, OpenAI for web)")
    
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
                now = datetime.utcnow()
                tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                wait_seconds = (tomorrow - now).total_seconds()
                
                while wait_seconds > 0 and not stop_event.is_set():
                    await asyncio.sleep(min(60, wait_seconds))
                    wait_seconds -= 60
                continue
            
            # Check if we've reached hourly target
            if scheduler_state.leads_this_hour >= HOURLY_TARGET:
                print(f"[Scheduler] Hourly target reached. Waiting for next hour...")
                now = datetime.utcnow()
                next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                wait_seconds = (next_hour - now).total_seconds()
                
                while wait_seconds > 0 and not stop_event.is_set():
                    await asyncio.sleep(min(60, wait_seconds))
                    wait_seconds -= 60
                continue
            
            cycle_count += 1
            print(f"\n[Scheduler] === PARALLEL Cycle {cycle_count} ===")
            print(f"[Scheduler] Today: {scheduler_state.leads_today}/{DAILY_TARGET}, This hour: {scheduler_state.leads_this_hour}/{HOURLY_TARGET}")
            
            # Generate search queries for this batch — ICP round-robin if ICPs are configured
            try:
                from .icp_config import get_active_icps
                active_icps = get_active_icps()
            except Exception:
                active_icps = []

            if active_icps:
                # Round-robin over ICPs to generate queries and run searches.
                # Names are collected alongside tasks so result labels can never
                # drift out of alignment with the gather() results.
                icp_search_tasks = []
                icp_names = []
                for icp in active_icps:
                    icp_slug = icp["slug"]
                    icp_budget = icp.get("daily_budget", DAILY_TARGET // max(len(active_icps), 1))
                    already_today = scheduler_state.leads_per_icp.get(icp_slug, 0)
                    if already_today >= icp_budget:
                        print(f"[Scheduler] ICP '{icp_slug}' budget reached ({already_today}/{icp_budget}), skipping")
                        continue
                    # AI-generated queries via Bedrock, with automatic fallback
                    # to the template builder. Budget is enforced inside.
                    from .icp_query_ai import generate_icp_queries
                    queries = generate_icp_queries(
                        icp,
                        QUERIES_PER_BATCH,
                        leads_per_icp=scheduler_state.leads_per_icp,
                    )
                    if not queries:
                        continue
                    icp_search_tasks.append(
                        run_search_batch(queries, scheduler_state, icp_segment=icp_slug)
                    )
                    icp_names.append(f"Search[{icp_slug}]")

                if not icp_search_tasks:
                    # All ICPs hit their daily budget — fall through to generic search for remaining budget
                    queries = generate_search_queries(scheduler_state.search_config, QUERIES_PER_BATCH)
                    icp_search_tasks = [run_search_batch(queries, scheduler_state)]
                    icp_names = ["Search"]
            else:
                # No ICPs configured — use generic query generation (backwards-compatible)
                queries = generate_search_queries(scheduler_state.search_config, QUERIES_PER_BATCH)
                icp_search_tasks = [run_search_batch(queries, scheduler_state)]
                icp_names = ["Search"]
            
            # ================================================================
            # RUN ALL 6 TASKS IN PARALLEL using asyncio.gather
            # ================================================================
            print("[Scheduler] 🚀 Starting FULL parallel execution: 6 concurrent tasks")
            print("[Scheduler] Tasks: Search | Lead Class | Email Class | Company Enrich | Email Summary | Lead Scoring")
            
            results = await asyncio.gather(
                # Task 1: Web Search for new leads (Google CSE) — ICP round-robin or generic
                *icp_search_tasks,
                # Task 2: Classify pending leads (OpenAI, 20/batch)
                run_classification_batch(scheduler_state),
                # Task 3: Classify emails (Gemini via ai_governance, 10/batch)
                run_email_classification_batch(),
                # Task 4: Enrich company data (OpenAI web search, 10/batch)
                run_company_enrichment_batch(),
                # Task 5: Summarize emails (Gemini via ai_governance, 5/batch)
                run_email_summary_batch(),
                # Task 6: Score leads (OpenAI, 50/batch)
                run_lead_scoring_batch(),
                # Return exceptions instead of raising them
                return_exceptions=True
            )

            # icp_names was built alongside icp_search_tasks above, so the two
            # stay aligned by construction (previously they were derived
            # independently and could silently mislabel results).

            # ================================================================
            # PROCESS ALL RESULTS (ICP search tasks + 5 fixed tasks)
            # ================================================================
            task_names = icp_names + ["Lead Classification", "Email Classification",
                                      "Company Enrichment", "Email Summary", "Lead Scoring"]

            for i, (name, result) in enumerate(zip(task_names, results)):
                if isinstance(result, Exception):
                    print(f"[Scheduler] ⚠️ {name} error: {result}")
                elif isinstance(result, dict):
                    # Handle dict results from batch functions
                    if result.get("error"):
                        print(f"[Scheduler] ⚠️ {name}: {result.get('error')}")
                    else:
                        processed = result.get("processed", result.get("found", 0))
                        success_key = next((k for k in ["classified", "enriched", "summarized", "scored", "success"] if k in result), None)
                        success_val = result.get(success_key, processed) if success_key else processed
                        print(f"[Scheduler] ✅ {name}: {success_val}/{processed}")
                elif isinstance(result, tuple):
                    # Handle tuple results (success, failure)
                    success, failure = result
                    print(f"[Scheduler] ✅ {name}: {success} success, {failure} failed")
                elif isinstance(result, int):
                    print(f"[Scheduler] ✅ {name}: {result} leads")
            
            if stop_event.is_set():
                break
            
            # Pause between cycles
            print(f"[Scheduler] Parallel cycle complete. Pausing for {BATCH_DELAY_SECONDS}s...")
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
