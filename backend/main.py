import os
import traceback
import re
from fastapi import FastAPI, HTTPException, Body, Path, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response, RedirectResponse
from dotenv import load_dotenv
from pymongo import MongoClient
from typing import List, Dict, Any, Optional
from bson import ObjectId
from datetime import datetime, timedelta
from fastapi import Path
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, Depends, APIRouter
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Auth utilities for password hashing
try:
    from .auth import hash_password, verify_password, needs_rehash, migrate_user_password
except ImportError:
    from auth import hash_password, verify_password, needs_rehash, migrate_user_password

# URL validation utility
try:
    from .utils import validate_redirect_url
except ImportError:
    from utils import validate_redirect_url

# Session store for Redis-backed sessions
try:
    from .session_store import get_session_store, SessionStore, SESSION_TTL_SECONDS as REDIS_SESSION_TTL
except ImportError:
    from session_store import get_session_store, SessionStore, SESSION_TTL_SECONDS as REDIS_SESSION_TTL
try:
    # Prefer relative import when running as a package (python -m uvicorn backend.main)
    from .routers import traffic as traffic_router
    from .app.routers import cpx as cpx_router
    from .routers import finance as finance_router
    from .routers import settings as settings_router
    from .routers import gmail as gmail_router
    from .app.routers import gmail_router as gmail_api_router
    from .routers import rfq as rfq_router
    from .routers import operations as operations_router
    from .routers import health as health_router
    from .routers import users as users_router
    from .routers import roles as roles_router
    from .routers import approvals as approvals_router
    from .app.services.cpx_service import CPXService
    from .app.routers import survey_allocation as survey_allocation_router
    from .app.routers import cint as cint_router
    from .app.integrations.cint_integration import CintIntegration
    from .leads import router as leads_router
    from .routers import panel as panel_router
except Exception:
    # Fallback to absolute import for other runtimes
    from routers import traffic as traffic_router
    from app.routers import cpx as cpx_router
    from routers import finance as finance_router
    from routers import settings as settings_router
    from routers import gmail as gmail_router
    from app.routers import gmail_router as gmail_api_router
    from routers import rfq as rfq_router
    from routers import operations as operations_router
    from routers import health as health_router
    from routers import users as users_router
    from routers import roles as roles_router
    from routers import approvals as approvals_router
    from app.services.cpx_service import CPXService
    from app.routers import survey_allocation as survey_allocation_router
    from routers import panel as panel_router
    from app.routers import cint as cint_router
    from app.integrations.cint_integration import CintIntegration
    from leads import router as leads_router

# Ensure stdout/stderr use UTF-8 on Windows consoles to avoid UnicodeEncodeError
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    # If reconfigure not available or fails, continue without raising
    pass
# ----------------------------
# Load environment variables
# ----------------------------
load_dotenv()

# ----------------------------
# Config
# ----------------------------
#changes 4
API_BASE = os.getenv("API_BASE", "http://139.59.32.72:8000")
# CINT webhook callback URL (must be publicly accessible for CINT servers)
CINT_WEBHOOK_CALLBACK_URL = os.getenv("CINT_WEBHOOK_CALLBACK_URL", "http://139.59.32.72:8000/api/cint/webhooks/opportunities") 

# MONGO_URI can be set via .env or configured via Settings UI (profile > settings)
# Default to localhost if not provided
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

# CORS Origins - comma-separated list
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS", 
    "*"
)

# Handle wildcard or list of origins
if CORS_ORIGINS == "*":
    CORS_ORIGINS = ["*"]
else:
    CORS_ORIGINS = CORS_ORIGINS.split(",")

# ----------------------------
# MongoDB connection
# ----------------------------
client = MongoClient(MONGO_URI)
db = client["email_automation"]

# Traffic flow database (from app.py)
try:
    traffic_db = client["traffic_flow_db"]
    url_parameters_collection = traffic_db["url_parameters"]
    # Test connection
    client.admin.command('ping')
    print("✅ MongoDB connected successfully (including traffic_flow_db)!")
except Exception as e:
    url_parameters_collection = None
    print(f"⚠️ MongoDB traffic_flow_db connection issue: {e}")
    print("   Traffic flow endpoints will have limited functionality")

contacts_collection = db["contacts"]
lists_collection = db["lists"]
templates_collection = db["templates"]
reports_collection = db["reports"]
projects_collection = db["projects"]
vendors_collection = db["vendors"]  # Vendors collection for CPX callback handling

# CPX Research collections
try:
    cpx_db = client["cpx_research"]
    cpx_surveys_collection = cpx_db["cpx_surveys"]
    cpx_filters_collection = cpx_db["cpx_filters"]
    print("✅ CPX Research database collections initialized")
except Exception as e:
    cpx_surveys_collection = None
    cpx_filters_collection = None
    print(f"⚠️ CPX Research database initialization issue: {e}")

# Settings database for app configuration (profile > settings)
try:
    settings_db = client["torpedo_settings"]
    app_settings_collection = settings_db["app_settings"]
except Exception as e:
    app_settings_collection = None
    print(f"⚠️ Settings database initialization issue: {e}")


def get_cpx_config() -> Dict[str, Any]:
    """
    Get CPX configuration from settings database with env vars as fallback.
    This allows CPX credentials to be configured via profile > settings UI.
    """
    config = {
        "cpx_app_id": os.getenv("CPX_APP_ID", ""),
        "cpx_ext_user_id": os.getenv("CPX_EXT_USER_ID", ""),
        "cpx_secure_hash_key": os.getenv("CPX_SECURE_HASH_KEY", ""),
        "cpx_api_timeout": int(os.getenv("CPX_API_TIMEOUT", "30")),
        "cpx_fetch_limit": int(os.getenv("CPX_FETCH_LIMIT", "1000")),
    }
    
    # Try to get config from settings database
    if app_settings_collection is not None:
        try:
            stored = app_settings_collection.find_one({"_id": "app_config"})
            if stored:
                # Override with stored values if they exist and are not empty
                if stored.get("cpx_app_id"):
                    config["cpx_app_id"] = stored["cpx_app_id"]
                if stored.get("cpx_ext_user_id"):
                    config["cpx_ext_user_id"] = stored["cpx_ext_user_id"]
                if stored.get("cpx_secure_hash_key"):
                    config["cpx_secure_hash_key"] = stored["cpx_secure_hash_key"]
                if stored.get("cpx_api_timeout"):
                    config["cpx_api_timeout"] = int(stored["cpx_api_timeout"])
        except Exception as e:
            print(f"⚠️ Could not read CPX config from settings: {e}")
    
    return config


def get_survey_filter_settings() -> Dict[str, Any]:
    """
    Get survey filter settings from settings database.
    Used for CPX filtering, cleanup, and refresh scheduling.
    """
    defaults = {
        "max_loi": 30,  # Increased from 20 to show more surveys
        "min_cpi": 0.3,  # Lowered from 1.0 to show more surveys
        "min_incidence": 10,  # Lowered from 60 to show more surveys
        "deletion_period_days": 7,
        "auto_refresh_enabled": True,
        "refresh_interval_seconds": 60,  # 1 minute
    }
    
    if app_settings_collection is not None:
        try:
            stored = app_settings_collection.find_one({"_id": "survey_filters"})
            if stored:
                return {
                    "max_loi": stored.get("max_loi", defaults["max_loi"]),
                    "min_cpi": stored.get("min_cpi", defaults["min_cpi"]),
                    "min_incidence": stored.get("min_incidence", defaults["min_incidence"]),
                    "deletion_period_days": stored.get("deletion_period_days", defaults["deletion_period_days"]),
                    "auto_refresh_enabled": stored.get("auto_refresh_enabled", defaults["auto_refresh_enabled"]),
                    "refresh_interval_seconds": stored.get("refresh_interval_seconds", defaults["refresh_interval_seconds"]),
                }
        except Exception as e:
            print(f"\u26a0\ufe0f Could not read survey filter settings: {e}")
    
    return defaults


# ----------------------------
# Session Management
# ----------------------------
SECRET_KEY = os.getenv("SESSION_SECRET", "supersecretkey")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", 60 * 60 * 24))  # default 24h
serializer = URLSafeTimedSerializer(SECRET_KEY)

# In-memory sessions dict for backward compatibility during Redis initialization
# Will be replaced by Redis store calls once initialized
sessions = {}  # fallback in-memory store (deprecated - use Redis)

# Global session store reference (initialized on first use)
_session_store = None

async def get_session_store_instance():
    """Get or initialize the session store singleton."""
    global _session_store
    if _session_store is None:
        _session_store = await get_session_store()
    return _session_store

async def verify_session(request: Request):
    """
    Verify session token from Authorization header.
    Uses Redis store for session persistence, with fallback to in-memory.
    """
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing session token")
    
    # Strip any whitespace (headers can sometimes have trailing spaces)
    session_id = session_id.strip()

    try:
        # Deserialize and validate token (already checks expiration via max_age)
        # If this succeeds, the token is valid and not expired
        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)
        
        # Try Redis store first
        store = await get_session_store_instance()
        session_data = await store.get(session_id)
        
        if session_data:
            # Session exists in Redis, extend TTL on activity
            await store.extend(session_id, SESSION_TTL_SECONDS)
        else:
            # Session not in Redis (e.g., after Redis restart or new session)
            # But token is valid (deserialized successfully), so allow access
            # Create session in Redis for tracking
            await store.create(
                session_id,
                {"username": username},
                SESSION_TTL_SECONDS
            )
            print(f"Session created/recreated in store for user: {username}")
        
        # Also update in-memory cache for backward compatibility
        sessions[session_id] = {
            "username": username,
            "expires_at": datetime.utcnow() + timedelta(seconds=SESSION_TTL_SECONDS)
        }

        return username
    except SignatureExpired:
        print(f"Token expired: {session_id[:20]}...")
        raise HTTPException(status_code=401, detail="Session expired - please login again")
    except BadSignature:
        print(f"Invalid token signature: {session_id[:20]}...")
        raise HTTPException(status_code=401, detail="Invalid session token - please login again")
    except Exception as e:
        print(f"Session verification error: {type(e).__name__}: {str(e)}")
        print(f"   Token (first 30 chars): {session_id[:30]}...")
        raise HTTPException(status_code=401, detail=f"Session verification failed: {str(e)}")


# ----------------------------
# FastAPI app
# ----------------------------
APP_VERSION = "1.0.0"
APP_NAME = "Campaign Platform API"

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Campaign Platform Backend API - Leads, Traffic, Finance, CPX Integration"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip compression for responses > 500 bytes (speeds up large JSON payloads)
app.add_middleware(GZipMiddleware, minimum_size=500)


# ----------------------------
# Performance Timing Middleware
# ----------------------------
import time as perf_time
from starlette.middleware.base import BaseHTTPMiddleware

class TimingMiddleware(BaseHTTPMiddleware):
    """Track request timing and add X-Response-Time header"""
    
    async def dispatch(self, request, call_next):
        start_time = perf_time.perf_counter()
        response = await call_next(request)
        process_time = (perf_time.perf_counter() - start_time) * 1000
        response.headers["X-Response-Time"] = f"{process_time:.2f}ms"
        
        # Log slow requests (>1 second)
        if process_time > 1000:
            print(f"⚠️ SLOW REQUEST: {request.method} {request.url.path} - {process_time:.0f}ms")
        
        return response

app.add_middleware(TimingMiddleware)


# ----------------------------
# Root Health Check
# ----------------------------
@app.get("/", tags=["health"])
async def root():
    """Root endpoint - API info and health check"""
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "status": "running",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint for load balancers and monitoring"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": APP_VERSION
    }


@app.get("/system/health", tags=["health"])
async def system_health():
    """
    Comprehensive system health check for lead ingestion pipeline.
    
    Returns status for all critical components:
    - Gmail mailboxes configured
    - Lead ingestion activity (last 24h)
    - AI classification status
    - Database connectivity
    """
    now = datetime.utcnow()
    twenty_four_hours_ago = now - timedelta(hours=24)
    
    health = {
        "timestamp": now.isoformat(),
        "version": APP_VERSION,
        "status": "healthy",
        "checks": {},
        "warnings": [],
        "errors": []
    }
    
    # Check 1: Gmail Mailboxes Configured
    try:
        gmail_db = client['torpedo_gmail']
        mailboxes_collection = gmail_db['workspace_mailboxes']
        mailbox_count = mailboxes_collection.count_documents({})
        health["checks"]["gmail_mailboxes"] = {
            "count": mailbox_count,
            "status": "ok" if mailbox_count > 0 else "warning"
        }
        if mailbox_count == 0:
            health["warnings"].append("No Gmail mailboxes configured - Gmail lead source inactive")
    except Exception as e:
        health["checks"]["gmail_mailboxes"] = {"status": "error", "error": str(e)}
        health["errors"].append(f"Gmail mailbox check failed: {e}")
    
    # Check 2: Email Sync Activity (last 24h)
    try:
        email_metadata = gmail_db.get_collection('email_metadata')
        recent_emails = email_metadata.count_documents({
            "internal_date": {"$gte": twenty_four_hours_ago}
        })
        health["checks"]["email_sync_24h"] = {
            "count": recent_emails,
            "status": "ok" if recent_emails > 0 else "warning"
        }
        if recent_emails == 0:
            health["warnings"].append("No emails synced in last 24 hours")
    except Exception as e:
        health["checks"]["email_sync_24h"] = {"status": "error", "error": str(e)}
    
    # Check 3: Lead Ingestion Activity (last 24h)
    try:
        leads_today = leads_raw_collection.count_documents({
            "created_at": {"$gte": twenty_four_hours_ago}
        })
        total_leads = leads_raw_collection.count_documents({})
        health["checks"]["lead_ingestion_24h"] = {
            "new_leads": leads_today,
            "total_leads": total_leads,
            "status": "ok" if leads_today > 0 else "warning"
        }
        if leads_today == 0:
            health["warnings"].append("No new leads ingested in last 24 hours")
    except Exception as e:
        health["checks"]["lead_ingestion_24h"] = {"status": "error", "error": str(e)}
        health["errors"].append(f"Lead ingestion check failed: {e}")
    
    # Check 4: AI Classification Status
    try:
        pending_classification = leads_raw_collection.count_documents({
            "classification_status": "pending"
        })
        classified = leads_raw_collection.count_documents({
            "classification_status": {"$in": ["completed", "classified"]}
        })
        health["checks"]["ai_classification"] = {
            "pending": pending_classification,
            "classified": classified,
            "status": "ok" if pending_classification < 100 else "warning"
        }
        if pending_classification > 100:
            health["warnings"].append(f"{pending_classification} leads awaiting classification")
    except Exception as e:
        health["checks"]["ai_classification"] = {"status": "error", "error": str(e)}
    
    # Check 5: Lead Sources Distribution
    try:
        pipeline = [
            {"$group": {"_id": "$source", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        source_dist = list(leads_raw_collection.aggregate(pipeline))
        health["checks"]["lead_sources"] = {
            "distribution": {s["_id"] or "unknown": s["count"] for s in source_dist},
            "status": "ok"
        }
    except Exception as e:
        health["checks"]["lead_sources"] = {"status": "error", "error": str(e)}
    
    # Check 6: Enrichment Status
    try:
        enriched_count = leads_enriched_collection.count_documents({})
        health["checks"]["enrichment"] = {
            "enriched_leads": enriched_count,
            "status": "ok"
        }
    except Exception as e:
        health["checks"]["enrichment"] = {"status": "error", "error": str(e)}
    
    # Check 7: Unique Email Index
    try:
        indexes = leads_raw_collection.index_information()
        has_email_index = any('email' in idx.get('key', [{}])[0] for idx in indexes.values())
        health["checks"]["email_unique_index"] = {
            "exists": has_email_index,
            "status": "ok" if has_email_index else "warning"
        }
        if not has_email_index:
            health["warnings"].append("Email unique index not found - deduplication may be slow")
    except Exception as e:
        health["checks"]["email_unique_index"] = {"status": "error", "error": str(e)}
    
    # Check 8: Gmail → Lead Pipeline Health (CRITICAL)
    try:
        # Get inbound emails in last 24h
        inbound_emails_24h = email_metadata.count_documents({
            "direction": "inbound",
            "internal_date": {"$gte": twenty_four_hours_ago}
        })
        # Get leads from gmail source in last 24h
        gmail_leads_24h = leads_raw_collection.count_documents({
            "source": "gmail",
            "created_at": {"$gte": twenty_four_hours_ago}
        })
        
        pipeline_status = "ok"
        if inbound_emails_24h > 0 and gmail_leads_24h == 0:
            pipeline_status = "critical"
            health["errors"].append(f"CRITICAL: {inbound_emails_24h} inbound emails but 0 leads created - pipeline broken")
        elif inbound_emails_24h > 10 and gmail_leads_24h < (inbound_emails_24h * 0.1):
            pipeline_status = "warning"
            health["warnings"].append(f"Low conversion: {inbound_emails_24h} emails → {gmail_leads_24h} leads")
        
        health["checks"]["gmail_to_lead_pipeline"] = {
            "inbound_emails_24h": inbound_emails_24h,
            "gmail_leads_24h": gmail_leads_24h,
            "conversion_rate": round(gmail_leads_24h / max(inbound_emails_24h, 1) * 100, 1),
            "status": pipeline_status
        }
    except Exception as e:
        health["checks"]["gmail_to_lead_pipeline"] = {"status": "error", "error": str(e)}
    
    # Check 9: Dedup Collision Count (from ingestion logs)
    try:
        ingestion_log = db.get_collection('ingestion_log')
        dedup_collisions_24h = ingestion_log.count_documents({
            "action": {"$in": ["skipped", "updated"]},
            "timestamp": {"$gte": twenty_four_hours_ago}
        })
        health["checks"]["dedup_collisions_24h"] = {
            "count": dedup_collisions_24h,
            "status": "ok"
        }
    except Exception as e:
        health["checks"]["dedup_collisions_24h"] = {"count": 0, "status": "unavailable"}
    
    # Overall status determination (RED conditions)
    if health["errors"]:
        health["status"] = "unhealthy"  # RED
    elif len(health["warnings"]) > 2:
        health["status"] = "degraded"   # YELLOW
    
    return health


# ----------------------------
# Include Routers
# ----------------------------
# Traffic flow router (separate database)
if url_parameters_collection is not None:
    traffic_router.set_url_parameters_collection(url_parameters_collection)
    
    # Initialize Traffic Service if CPX surveys are also available
    if cpx_surveys_collection is not None:
        try:
            from app.services.traffic_service import TrafficService
            traffic_service_instance = TrafficService(
                traffic_collection=url_parameters_collection,
                surveys_collection=cpx_surveys_collection
            )
            traffic_router.set_traffic_service(traffic_service_instance)
            print("✅ Traffic service initialized")
        except Exception as e:
            print(f"⚠️ Traffic service initialization issue: {e}")
    
    # Inject Survey Allocation Service into traffic router
    try:
        from app.services.survey_allocation_service import get_survey_allocation_service
        survey_allocation_service_instance = get_survey_allocation_service()
        traffic_router.set_survey_allocation_service(survey_allocation_service_instance)
        print("✅ Survey allocation service injected into traffic router")
    except Exception as e:
        print(f"⚠️ Survey allocation service injection issue: {e}")

app.include_router(traffic_router.router)

# Finance router for CRUD endpoints used by the frontend
try:
    app.include_router(finance_router.router)
    print("✅ Finance router included")
except Exception as e:
    print(f"⚠️ Finance router not included: {e}")

# CPX Research router
if cpx_surveys_collection is not None and cpx_filters_collection is not None:
    # Get CPX config from settings database (with env vars as fallback)
    cpx_config = get_cpx_config()
    
    # Initialize CPX service with database collections
    cpx_service = CPXService(
        app_id=cpx_config["cpx_app_id"],
        ext_user_id=cpx_config["cpx_ext_user_id"],
        secure_hash_key=cpx_config["cpx_secure_hash_key"],
        api_timeout=cpx_config["cpx_api_timeout"],
        fetch_limit=cpx_config.get("cpx_fetch_limit", 1000),
        surveys_collection=cpx_surveys_collection,
        filters_collection=cpx_filters_collection,
        settings_collection=app_settings_collection,  # Pass settings collection for filter settings
        survey_allocation_service=survey_allocation_service_instance,  # Inject survey allocation service for metrics
    )
    cpx_router.set_cpx_service(cpx_service)
    traffic_router.set_cpx_service(cpx_service)  # Inject CPX service into traffic router for survey allocation
    app.include_router(cpx_router.router)
    print("✅ CPX Research router initialized")
    print("✅ CPX service injected into traffic router")
else:
    print("⚠️ CPX Research router not initialized due to database connection issue")

# Cint Integration Setup
try:
    from database_setup_cint import setup_cint_database
    # Initialize Cint database collections
    setup_cint_database(mongo_uri=MONGO_URI)
    print("✅ Cint database collections initialized")
    
    # Initialize CintIntegration with environment variables or defaults
    cint_integration = CintIntegration.load_from_env()
    cint_integration.initialize()
    
    # Wire up services to router for dependency injection
    cint_router.set_cint_service(cint_integration.cint_service)
    cint_router.set_cint_allocation_ext(cint_integration.allocation_extension)
    
    # Register Cint router
    app.include_router(cint_router.router, prefix="/api/cint", tags=["Cint Research"])
    print("✅ Cint Research router initialized")
    print(f"✅ Cint integration active (Supplier Code: {cint_integration.supplier_code})")
except Exception as e:
    print(f"⚠️ Cint Research setup failed: {e}")
    import traceback
    traceback.print_exc()

# Inject vendors collection into traffic router for CPX callback handling
try:
    traffic_router.set_vendors_collection(vendors_collection)
    print("✅ Vendors collection injected into traffic router")
except Exception as e:
    print(f"⚠️ Vendors collection injection issue: {e}")

# Initialize CPX callback logs collection and inject into traffic router
try:
    cpx_callback_logs_collection = traffic_db["cpx_callback_logs"]
    traffic_router.set_cpx_callback_logs_collection(cpx_callback_logs_collection)
    print("✅ CPX callback logs collection initialized")
except Exception as e:
    print(f"⚠️ CPX callback logs collection issue: {e}")

# Settings router
try:
    app.include_router(settings_router.router)
    print("✅ Settings router included")
except Exception as e:
    print(f"⚠️ Settings router not included: {e}")

# Health router for system monitoring
try:
    app.include_router(health_router.router)
    print("✅ Health router included")
except Exception as e:
    print(f"⚠️ Health router not included: {e}")

# Performance monitoring router
try:
    from routers import performance as performance_router
    app.include_router(performance_router.router)
    print("✅ Performance router included")
except Exception as e:
    print(f"⚠️ Performance router not included: {e}")

# Gmail router for Gmail API integration (legacy - IMAP based)
try:
    app.include_router(gmail_router.router)
    print("✅ Gmail router included (legacy)")
except Exception as e:
    print(f"⚠️ Gmail router not included: {e}")

# New Gmail API router (OAuth + metadata-only storage + AI classification)
try:
    app.include_router(gmail_api_router.router)
    print("✅ Gmail API router included (new)")
except Exception as e:
    print(f"⚠️ Gmail API router not included: {e}")

# Gmail Workspace router (Service Account with Domain-Wide Delegation)
try:
    from routers import gmail_workspace as gmail_workspace_router
    app.include_router(gmail_workspace_router.router)
    print("✅ Gmail Workspace router included (Service Account)")
except Exception as e:
    print(f"⚠️ Gmail Workspace router not included: {e}")

# Survey Allocation & Quality Control Engine router
try:
    app.include_router(survey_allocation_router.router)
    print("✅ Survey Allocation router included")
except Exception as e:
    print(f"⚠️ Survey Allocation router not included: {e}")

# Survey Pool Management router (sync/activate surveys from CPX/CINT)
try:
    from app.routers import survey_pool as survey_pool_router
    app.include_router(survey_pool_router.router)
    print("✅ Survey Pool router included")
except Exception as e:
    print(f"⚠️ Survey Pool router not included: {e}")

# Leads AI Classification router
try:
    app.include_router(leads_router.router)
    print("✅ Leads AI Classification router included")
except Exception as e:
    print(f"⚠️ Leads router not included: {e}")

# Classified Gmail router (Email classification and move to leads)
try:
    try:
        from .routers import classified_gmail as classified_gmail_router
    except ImportError:
        from routers import classified_gmail as classified_gmail_router
    
    app.include_router(classified_gmail_router.router)
    print("✅ Classified Gmail router included")
except Exception as e:
    print(f"⚠️ Classified Gmail router not included: {e}")

# Email Patterns Discovery router
try:
    try:
        from .routers import email_patterns as email_patterns_router
    except ImportError:
        from routers import email_patterns as email_patterns_router
    
    app.include_router(email_patterns_router.router)
    print("✅ Email Patterns router included")
except Exception as e:
    print(f"⚠️ Email Patterns router not included: {e}")

# Company Cache router
try:
    try:
        from .routers import company_cache as company_cache_router
    except ImportError:
        from routers import company_cache as company_cache_router
    
    app.include_router(company_cache_router.router)
    print("✅ Company Cache router included")
except Exception as e:
    print(f"⚠️ Company Cache router not included: {e}")

# Lead Generation Agents router
try:
    from leads.agent_router import router as agent_router
    app.include_router(agent_router)
    print("✅ Lead Generation Agents router included")
except Exception as e:
    print(f"⚠️ Lead Agents router not included: {e}")

# Panel (Survey Panel User Portal) router
try:
    app.include_router(panel_router.router)
    print("✅ Panel (Survey Panel) router included")
except Exception as e:
    print(f"⚠️ Panel router not included: {e}")

# Clay-Level Features router (List building, enrichment, workbooks)
try:
    try:
        from .leads.clay_routes import router as clay_routes
    except ImportError:
        from leads.clay_routes import router as clay_routes
    
    app.include_router(clay_routes)
    print("✅ Clay-Level Features router included")
except Exception as e:
    print(f"⚠️ Clay router not included: {e}")

# RFQ (Request for Quote) router
try:
    app.include_router(rfq_router.router)
    print("✅ RFQ router included")
except Exception as e:
    print(f"⚠️ RFQ router not included: {e}")

# Operations router (Operations-Finance integration)
try:
    app.include_router(operations_router.router)
    print("✅ Operations router included")
except Exception as e:
    print(f"⚠️ Operations router not included: {e}")

# Sales Dashboard router
try:
    try:
        from .routers import sales_dashboard as sales_dashboard_router
    except ImportError:
        from routers import sales_dashboard as sales_dashboard_router
    app.include_router(sales_dashboard_router.router)
    print("✅ Sales Dashboard router included")
except Exception as e:
    print(f"⚠️ Sales Dashboard router not included: {e}")

# Sales Accounts router
try:
    try:
        from .routers import sales_accounts as sales_accounts_router
    except ImportError:
        from routers import sales_accounts as sales_accounts_router
    app.include_router(sales_accounts_router.router)
    print("✅ Sales Accounts router included")
except Exception as e:
    print(f"⚠️ Sales Accounts router not included: {e}")

# Unified Vendors router
try:
    try:
        from .routers import unified_vendors as unified_vendors_router
    except ImportError:
        from routers import unified_vendors as unified_vendors_router
    app.include_router(unified_vendors_router.router)
    print("✅ Unified Vendors router included")
except Exception as e:
    print(f"⚠️ Unified Vendors router not included: {e}")

# Vendor Leads router (for vendor qualification workflow)
try:
    try:
        from .routers import vendor_leads as vendor_leads_router
    except ImportError:
        from routers import vendor_leads as vendor_leads_router
    app.include_router(vendor_leads_router.router)
    print("✅ Vendor Leads router included")
except Exception as e:
    print(f"⚠️ Vendor Leads router not included: {e}")

# Email Sync router
try:
    try:
        from .email_sync.router import router as email_sync_router
    except ImportError:
        from email_sync.router import router as email_sync_router
    app.include_router(email_sync_router, prefix="/api/v1")
    print("✅ Email Sync router included")
except Exception as e:
    print(f"⚠️ Email Sync router not included: {e}")

# Unified Inbox router (aggregated email view)
try:
    try:
        from .routers import unified_inbox as unified_inbox_router
    except ImportError:
        from routers import unified_inbox as unified_inbox_router
    app.include_router(unified_inbox_router.router)
    print("✅ Unified Inbox router included")
except Exception as e:
    print(f"⚠️ Unified Inbox router not included: {e}")

# Campaigns router (cold outreach sequences)
try:
    try:
        from .routers import campaigns as campaigns_router
    except ImportError:
        from routers import campaigns as campaigns_router
    app.include_router(campaigns_router.router)
    print("✅ Campaigns router included")
except Exception as e:
    print(f"⚠️ Campaigns router not included: {e}")

# Email Classification router (AI batch classification)
try:
    try:
        from .routers import classification as classification_router
    except ImportError:
        from routers import classification as classification_router
    app.include_router(classification_router.router)
    print("✅ Email Classification router included")
except Exception as e:
    print(f"⚠️ Email Classification router not included: {e}")

# Gemini router removed - using OpenAI for all AI tasks

# Audit Trail router
try:
    try:
        from .routers import audit as audit_router
    except ImportError:
        from routers import audit as audit_router
    app.include_router(audit_router.router)
    print("✅ Audit Trail router included")
except Exception as e:
    print(f"⚠️ Audit Trail router not included: {e}")

# P1.6: AI Review Queue router
try:
    try:
        from .routers import review_queue as review_queue_router
    except ImportError:
        from routers import review_queue as review_queue_router
    app.include_router(review_queue_router.router)
    print("✅ AI Review Queue router included")
except Exception as e:
    print(f"⚠️ AI Review Queue router not included: {e}")

# --- RBAC Routers ---
try:
    app.include_router(users_router.router)
    print("✅ Users router included")
except Exception as e:
    print(f"⚠️ Users router not included: {e}")

try:
    app.include_router(roles_router.router)
    print("✅ Roles router included")
except Exception as e:
    print(f"⚠️ Roles router not included: {e}")

try:
    app.include_router(approvals_router.router)
    print("✅ Approvals router included")
except Exception as e:
    print(f"⚠️ Approvals router not included: {e}")

# --- MCP Action Router ---
try:
    try:
        from .routers import mcp as mcp_router
    except ImportError:
        from routers import mcp as mcp_router
    app.include_router(mcp_router.router)
    print("✅ MCP Action Router included")
except Exception as e:
    print(f"⚠️ MCP Action Router not included: {e}")

# --- Projects Router ---
try:
    try:
        from .routers import projects as projects_router
    except ImportError:
        from routers import projects as projects_router
    app.include_router(projects_router.router)
    print("✅ Projects router included")
except Exception as e:
    print(f"⚠️ Projects router not included: {e}")

# --- Support/Tickets Router ---
try:
    try:
        from .routers import support as support_router
    except ImportError:
        from routers import support as support_router
    app.include_router(support_router.router)
    print("✅ Support router included")
except Exception as e:
    print(f"⚠️ Support router not included: {e}")

# ----------------------------
# APScheduler for CPX refresh job
# ----------------------------
scheduler = BackgroundScheduler()
cpx_refresh_job: Optional[Any] = None

def refresh_cpx_inventory():
    """Background job to refresh CPX survey inventory"""
    if cpx_service is None:
        print("⚠️ CPX service not initialized, skipping refresh")
        return
    
    try:
        print(f"🔄 [CPX] Starting scheduled refresh at {datetime.utcnow().isoformat()}")
        
        # Get filter settings from database
        filter_settings = get_survey_filter_settings()
        deletion_days = filter_settings.get("deletion_period_days", 7)
        
        # Cleanup surveys older than configured days
        cpx_service.cleanup_old_surveys(days=deletion_days)
        
        # Fetch and upsert new surveys
        surveys = cpx_service.fetch_cpx_surveys()
        count = cpx_service.upsert_surveys(surveys)
        print(f"✅ [CPX] Refresh complete: {len(surveys)} fetched, {count} upserted")
    except Exception as e:
        print(f"❌ [CPX] Refresh failed: {str(e)}")
        traceback.print_exc()


def background_gmail_sync():
    """
    Background job to sync emails for all registered mailboxes.
    Runs every 5 minutes to pull new emails without human intervention.
    Also auto-classifies new emails using OpenAI and extracts leads.
    """
    try:
        print(f"🔄 [Gmail] Starting background sync at {datetime.utcnow().isoformat()}")
        
        # Try Gmail Workspace Service first (Service Account with Domain-Wide Delegation)
        try:
            from app.services.gmail_workspace_service import GmailWorkspaceService
            
            ws_service = GmailWorkspaceService(mongo_uri=MONGO_URI)
            ws_service.load_service_account()
            
            mailboxes = ws_service.list_mailboxes()
            total_synced = 0
            
            for mb in mailboxes:
                try:
                    # Use incremental sync (not full_sync) for background job
                    result = ws_service.sync_mailbox(mb["id"], max_results=1000, full_sync=False)
                    new_count = result.get("new_emails", 0)
                    total_synced += new_count
                    if new_count > 0:
                        print(f"   📧 {mb['email']}: +{new_count} new emails")
                except Exception as e:
                    print(f"   ⚠️ {mb['email']}: sync error - {e}")
            
            print(f"✅ [Gmail] Background sync complete: {total_synced} new emails across {len(mailboxes)} mailboxes")
            
            # Re-enabled: Auto-classification using DeepSeek (cheaper & faster)
            if total_synced > 0:
                try:
                    from leads.email_classifier import classify_all_pending_emails
                    print(f"🤖 [AI] Starting AI auto-classification of {min(total_synced, 100)} emails...")
                    # Use 'background' source for higher rate limits
                    classify_result = classify_all_pending_emails(batch_size=20, max_batches=5, source="background")
                    success_count = classify_result.get('total_success', 0)
                    print(f"✅ [AI] Classified {success_count} emails using AI")
                except ImportError as ie:
                    print(f"⚠️ Could not import classifier: {ie}")
                except Exception as e:
                    print(f"⚠️ Auto-classification failed: {e}")
            #         print(f"⚠️ [AI] Email classifier not available: {ie}")
            #     except Exception as classify_err:
            #         print(f"⚠️ [AI] Classification error: {classify_err}")
                    
        except ImportError:
            print("⚠️ [Gmail] Gmail Workspace Service not available")
        except Exception as e:
            print(f"⚠️ [Gmail] Workspace sync error: {e}")
        
    except Exception as e:
        print(f"❌ [Gmail] Background sync failed: {str(e)}")
        traceback.print_exc()


def cint_health_check():
    """
    Background job to check Cint subscription health and auto-resubscribe if needed.
    Also runs click-based cleanup for unclicked surveys.
    Runs every 30 minutes to ensure webhook is active.
    """
    import asyncio
    
    async def _check_and_resubscribe():
        try:
            print(f"🔄 [Cint] Health check at {datetime.utcnow().isoformat()}")
            
            if not cint_integration or not cint_integration.cint_service:
                print("⚠️ [Cint] Integration not initialized")
                return
            
            # Run click-based cleanup for unclicked surveys (older than 3 days with 0 clicks)
            try:
                deleted_count = cint_integration.cint_service.cleanup_unclicked_surveys(days=3)
                if deleted_count > 0:
                    print(f"🗑️ [Cint] Cleaned up {deleted_count} unclicked surveys")
            except Exception as cleanup_error:
                print(f"⚠️ [Cint] Cleanup error: {cleanup_error}")
            
            # Check current subscription status
            status_result = await cint_integration.cint_service.get_opportunities_subscription()
            
            if status_result.get("success"):
                print("✅ [Cint] Webhook subscription is active")
            else:
                # Subscription not found or expired, re-subscribe
                print("⚠️ [Cint] Subscription inactive, attempting to resubscribe...")
                
                from app.models.cint import OpportunitiesSubscriptionConfig
                
                config = OpportunitiesSubscriptionConfig(
                    callback_url=CINT_WEBHOOK_CALLBACK_URL,
                    include_quotas=True,
                    payload_max_size_mb=10,
                    payload_max_survey_count=1000,
                    send_interval_seconds=30,
                    opportunities_filters=[],
                )
                
                result = await cint_integration.cint_service.create_opportunities_subscription(config)
                
                if result.get("success"):
                    print(f"✅ [Cint] Resubscribed successfully: {CINT_WEBHOOK_CALLBACK_URL}")
                else:
                    print(f"❌ [Cint] Resubscribe failed: {result.get('error')}")
                    
        except Exception as e:
            print(f"❌ [Cint] Health check failed: {str(e)}")
            traceback.print_exc()
    
    # Run the async function
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_check_and_resubscribe())
        else:
            loop.run_until_complete(_check_and_resubscribe())
    except RuntimeError:
        # No event loop, create one
        asyncio.run(_check_and_resubscribe())


def background_historic_email_sync():
    """
    Background job to download historic emails for all mailboxes.
    Uses rate-limited backfill with exponential backoff.
    
    Features:
    - Configurable rate limiting (default: 500 emails/minute)
    - Exponential backoff on rate limit errors (30s → 60s → 120s → 300s)
    - Resumable with cursor persistence for crash recovery
    - Skip AI classification for historic emails (configurable)
    - Auto-starts on service boot
    
    Configuration stored in MongoDB (torpedo_gmail.gmail_config):
    - enabled: bool (default True)
    - max_emails_per_minute: int (default 500)
    - batch_size: int (default 50)
    - batch_delay_seconds: float (default 6.0)
    - skip_classification: bool (default True)
    """
    import threading
    
    def _run_historic_sync():
        try:
            # Import the Gmail Workspace Service
            try:
                import sys
                import os
                parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if parent_dir not in sys.path:
                    sys.path.insert(0, parent_dir)
                
                from gmail_workspace_service_vm import GmailWorkspaceService
            except ImportError:
                try:
                    from app.services.gmail_workspace_service import GmailWorkspaceService
                except ImportError:
                    print("⚠️ [Backfill] Gmail Workspace Service not available")
                    return
            
            # Initialize service
            ws_service = GmailWorkspaceService(mongo_uri=MONGO_URI)
            ws_service.load_service_account()
            
            if not ws_service.is_configured():
                return  # Silent skip if not configured
            
            # Check if backfill is enabled
            if not ws_service.is_backfill_enabled():
                return  # Silent skip if paused
            
            # Run backfill cycle with rate limiting
            result = ws_service.run_backfill_cycle()
            
            if result.get("skipped"):
                return  # Backfill paused, skip silently
            
            processed = result.get("processed", 0)
            total_fetched = result.get("total_fetched", 0)
            duration = result.get("duration_seconds", 0)
            
            if total_fetched > 0:
                print(f"📥 [Backfill] Cycle complete: +{total_fetched} emails from {processed} mailbox(es) in {duration:.1f}s")
            
            # Log individual results if there were errors
            for r in result.get("results", []):
                if r.get("error"):
                    print(f"   ⚠️ [Backfill] {r.get('email')}: {r.get('error')}")
            
        except Exception as e:
            print(f"❌ [Backfill] Historic email sync failed: {str(e)}")
            traceback.print_exc()
    
    # Run in a separate thread to not block the scheduler
    thread = threading.Thread(target=_run_historic_sync, daemon=True)
    thread.start()


@app.on_event("startup")
async def startup_event():
    """Initialize scheduler and start background jobs"""
    global cpx_refresh_job
    
    # Initialize Clay-Level Features
    try:
        try:
            from .leads.clay_init import initialize_clay_features
        except ImportError:
            from leads.clay_init import initialize_clay_features
        
        await initialize_clay_features()
    except Exception as e:
        print(f"⚠️ Clay initialization error: {e}")
        import traceback
        traceback.print_exc()
    
    # Auto-subscribe to Cint webhook on startup
    try:
        from app.models.cint import OpportunitiesSubscriptionConfig, OpportunitiesSubscriptionFilter
        
        # Check if Cint integration is available
        if cint_integration and cint_integration.cint_service:
            # Check current subscription status
            status_result = await cint_integration.cint_service.get_opportunities_subscription()
            
            if status_result.get("success"):
                print("✅ Cint webhook already subscribed")
            else:
                # Create subscription if not already subscribed (404 means no subscription exists)
                print("📡 Subscribing to Cint opportunities webhook...")
                
                # Use public callback URL (CINT servers must be able to reach this)
                callback_url = CINT_WEBHOOK_CALLBACK_URL
                
                # Configure subscription to receive opportunities from major English locales
                config = OpportunitiesSubscriptionConfig(
                    callback_url=callback_url,
                    include_quotas=True,
                    payload_max_size_mb=10,
                    payload_max_survey_count=1000,  # Min required: 1000
                    send_interval_seconds=30,  # Max allowed: 30 seconds
                    opportunities_filters=[],  # Uses default: eng_us, eng_gb, eng_ca, eng_au
                )
                
                result = await cint_integration.cint_service.create_opportunities_subscription(config)
                
                if result.get("success"):
                    print(f"✅ Cint webhook subscription created: {callback_url}")
                else:
                    print(f"⚠️ Cint webhook subscription failed: {result.get('error')}")
    except ImportError:
        print("⚠️ Cint models not available for auto-subscription")
    except Exception as e:
        print(f"⚠️ Cint webhook subscription error: {e}")
        import traceback
        traceback.print_exc()
    
    # Start Email Sync workers (runs in background even when user navigates away)
    try:
        try:
            from .email_sync.router import get_orchestrator
        except ImportError:
            from email_sync.router import get_orchestrator
        
        orchestrator = get_orchestrator()
        if orchestrator and not orchestrator._started:
            orchestrator.start()
            print("✅ Email Sync workers started (background sync enabled)")
    except Exception as e:
        print(f"⚠️ Could not start Email Sync workers: {e}")
    
    # Initialize background job scheduler for continuous lead generation
    # This handles automatic resumption of paused web search jobs, daily limit resets, etc.
    try:
        try:
            from .background_job_scheduler import initialize_scheduler
        except ImportError:
            from background_job_scheduler import initialize_scheduler
        
        initialize_scheduler()
        print("✅ Background job scheduler initialized (auto-resume web search jobs every 5 min)")
    except Exception as e:
        print(f"⚠️ Could not initialize background job scheduler: {e}")
        import traceback
        traceback.print_exc()
    
    # Resume incomplete web search jobs (if auto-resume is enabled)
    try:
        from leads.router import (
            get_incomplete_jobs, run_web_search_job, update_job, JobStatus,
            get_global_search_control
        )
        import asyncio
        
        # Check if auto-resume is disabled or global search is paused
        search_control = get_global_search_control()
        auto_resume_disabled = search_control.get("auto_resume_disabled", False)
        global_paused = search_control.get("paused", False)
        circuit_open = search_control.get("circuit_breaker_open", False)
        
        incomplete_jobs = get_incomplete_jobs()
        
        if auto_resume_disabled:
            print(f"⏸️ Web search auto-resume is DISABLED. {len(incomplete_jobs)} jobs not resumed.")
            print("   Enable with: POST /leads/import/web-search/control/enable-auto-resume")
        elif global_paused:
            print(f"⏸️ Global web search is PAUSED. {len(incomplete_jobs)} jobs not resumed.")
            print(f"   Reason: {search_control.get('paused_reason', 'Unknown')}")
            print("   Resume with: POST /leads/import/web-search/control/resume")
        elif circuit_open:
            print(f"🔴 Circuit breaker OPEN (too many API errors). {len(incomplete_jobs)} jobs not resumed.")
            print("   Reset with: POST /leads/import/web-search/control/resume")
        elif incomplete_jobs:
            print(f"🔄 Found {len(incomplete_jobs)} incomplete web search jobs to resume...")
            for job in incomplete_jobs:
                job_id = job["job_id"]
                print(f"   Resuming job {job_id} (status: {job['status']}, imported: {job['total_imported']}/{job['target_count']})")
                # Schedule the job to run
                asyncio.create_task(run_web_search_job(job_id))
            print(f"✅ Resumed {len(incomplete_jobs)} web search jobs")
        else:
            print("ℹ️ No incomplete web search jobs to resume")
    except Exception as e:
        print(f"⚠️ Could not check/resume web search jobs: {e}")
    
    if cpx_service is not None:
        try:
            # Get refresh settings from database
            filter_settings = get_survey_filter_settings()
            auto_refresh = filter_settings.get("auto_refresh_enabled", True)
            refresh_interval = filter_settings.get("refresh_interval_seconds", 60)
            
            if auto_refresh:
                # Start scheduler for periodic refreshes
                scheduler.start()
                cpx_refresh_job = scheduler.add_job(
                    refresh_cpx_inventory,
                    IntervalTrigger(seconds=refresh_interval),
                    id="cpx_refresh",
                    name="CPX Survey Inventory Refresh",
                    replace_existing=True
                )
                print(f"✅ CPX refresh job scheduled (every {refresh_interval} seconds)")
                # Schedule initial fetch as background task (non-blocking)
                import asyncio
                asyncio.create_task(asyncio.to_thread(refresh_cpx_inventory))
                print("🚀 Initial CPX survey fetch scheduled (running in background)")
            else:
                print("⚠️ CPX auto-refresh is disabled in settings")
        except Exception as e:
            print(f"❌ Failed to schedule CPX refresh job: {str(e)}")
            traceback.print_exc()
    
    # ----------------------------
    # Background Gmail Sync Job (every 5 minutes)
    # ----------------------------
    try:
        # Only add if scheduler is running
        if scheduler.running:
            scheduler.add_job(
                background_gmail_sync,
                IntervalTrigger(seconds=300),  # Every 5 minutes
                id="gmail_sync",
                name="Gmail Background Sync",
                replace_existing=True
            )
            print("✅ Gmail background sync job scheduled (every 5 minutes)")
        else:
            print("⚠️ Scheduler not running, Gmail sync job not scheduled")
    except Exception as e:
        print(f"⚠️ Could not schedule Gmail sync job: {e}")
    
    # ----------------------------
    # Cint Health Check & Auto-Resubscribe (every 30 minutes)
    # ----------------------------
    try:
        if scheduler.running and cint_integration and cint_integration.cint_service:
            scheduler.add_job(
                cint_health_check,
                IntervalTrigger(seconds=1800),  # Every 30 minutes
                id="cint_health_check",
                name="Cint Health Check & Auto-Resubscribe",
                replace_existing=True
            )
            print("✅ Cint health check job scheduled (every 30 minutes)")
    except Exception as e:
        print(f"⚠️ Could not schedule Cint health check job: {e}")
    
    # ----------------------------
    # Historic Email Backfill (every 30 seconds, rate-limited)
    # ----------------------------
    try:
        if scheduler.running:
            scheduler.add_job(
                background_historic_email_sync,
                IntervalTrigger(seconds=30),  # Every 30 seconds for responsive backfill
                id="historic_email_sync",
                name="Historic Email Backfill (Rate-Limited)",
                replace_existing=True
            )
            print("✅ Historic email backfill job scheduled (every 30 seconds, rate-limited)")
    except Exception as e:
        print(f"⚠️ Could not schedule historic email sync job: {e}")
    
    # ----------------------------
    # Email Classification Job (every 2 minutes, batch of 10)
    # Feature flag: EMAIL_CLASSIFICATION_ENABLED=true (default: false for safety)
    # ----------------------------
    try:
        email_classify_enabled = os.getenv("EMAIL_CLASSIFICATION_ENABLED", "false").lower() == "true"
        if scheduler.running and email_classify_enabled:
            def background_email_classification():
                """Classify a batch of unclassified emails using existing classify_batch."""
                try:
                    from leads.email_classifier import classify_batch
                    result = classify_batch(batch_size=50, source="apscheduler")
                    processed = result.get("processed", 0)
                    success = result.get("success", 0)
                    errors = result.get("errors", 0)
                    if processed > 0:
                        print(f"[EmailClassify] Batch complete: {success}/{processed} classified, {errors} errors")
                except Exception as e:
                    print(f"[EmailClassify] Error: {e}")
            
            scheduler.add_job(
                background_email_classification,
                IntervalTrigger(seconds=120),  # Every 2 minutes = 30 batches/hour = 1500 emails/hour max
                id="email_classification",
                name="Email Classification (Rate-Limited)",
                replace_existing=True
            )
            print("✅ Email classification job scheduled (every 2 min, batch=50, ~1500/hour)")
        elif not email_classify_enabled:
            print("ℹ️ Email classification disabled (set EMAIL_CLASSIFICATION_ENABLED=true to enable)")
    except Exception as e:
        print(f"⚠️ Could not schedule email classification job: {e}")
    
    # ============== STARTUP SUMMARY BANNER ==============
    print("\n" + "=" * 60)
    print(f"🚀 {APP_NAME} v{APP_VERSION} STARTED SUCCESSFULLY")
    print("=" * 60)
    print("📋 REGISTERED ROUTERS:")
    print("   • /leads         - Lead management & AI classification")
    print("   • /finance       - Finance module (invoices, vendors)")
    print("   • /settings      - Application settings")
    print("   • /gmail         - Gmail API integration")
    print("   • /cpx           - CPX Research surveys")
    print("   • /survey-allocation - Survey allocation engine")
    print("   • /              - Traffic flow (root level)")
    print("   • /api/v1/email-sync - Email sync (background workers)")
    print("")
    print("🔄 BACKGROUND JOBS:")
    if scheduler.running:
        print(f"   • CPX Survey Refresh: Active (every {filter_settings.get('refresh_interval_seconds', 60)}s)")
        print("   • Gmail Background Sync: Active (every 5 minutes)")
        print("   • Historic Email Backfill: Active (every 30 seconds, rate-limited)")
        if email_classify_enabled:
            print("   • Email Classification: Active (every 2 min, batch=10)")
        else:
            print("   • Email Classification: Disabled (EMAIL_CLASSIFICATION_ENABLED=false)")
    else:
        print("   • CPX Survey Refresh: Inactive")
    # Check email sync workers status
    try:
        try:
            from .email_sync.router import get_orchestrator
        except ImportError:
            from email_sync.router import get_orchestrator
        orchestrator = get_orchestrator()
        if orchestrator and orchestrator._started:
            print("   • Email Sync Workers: Active (runs in background)")
        else:
            print("   • Email Sync Workers: Inactive")
    except:
        print("   • Email Sync Workers: Not available")
    print("")
    print("🌐 ENDPOINTS:")
    print("   • Health: GET /health")
    print("   • API Docs: GET /docs")
    print("   • OpenAPI: GET /openapi.json")
    print("=" * 60 + "\n")

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown scheduler and email sync workers"""
    # Shutdown background job scheduler (handles web search job resumption)
    try:
        try:
            from .background_job_scheduler import shutdown_scheduler
        except ImportError:
            from background_job_scheduler import shutdown_scheduler
        
        shutdown_scheduler()
        print("✅ Background job scheduler shutdown complete")
    except Exception as e:
        print(f"⚠️ Could not shutdown background job scheduler: {e}")
    
    # Shutdown Clay features
    try:
        try:
            from .leads.clay_init import shutdown_clay_features
        except ImportError:
            from leads.clay_init import shutdown_clay_features
        
        await shutdown_clay_features()
    except Exception as e:
        print(f"⚠️ Clay shutdown error: {e}")
    
    if scheduler.running:
        scheduler.shutdown()
        print("✅ Scheduler shutdown complete")
    
    # Stop Email Sync workers
    try:
        try:
            from .email_sync.router import get_orchestrator
        except ImportError:
            from email_sync.router import get_orchestrator
        
        orchestrator = get_orchestrator()
        if orchestrator and orchestrator._started:
            orchestrator.stop()
            print("✅ Email Sync workers shutdown complete")
    except Exception as e:
        print(f"⚠️ Could not stop Email Sync workers: {e}")




# ----------------------------
# Users (Hardcoded for now)
# ----------------------------
users_collection = db["users"]

# Create index for faster login queries
users_collection.create_index("username", unique=True, background=True)

# Insert one default user if not exists (with hashed password)
if not users_collection.find_one({"username": "admin"}):
    users_collection.insert_one({
        "username": "admin",
        "password": hash_password("password123"),  # ✅ Securely hashed
        "createdAt": datetime.utcnow()
    })
    print("✅ Default admin user created with hashed password")


@app.post("/login/")
async def login(credentials: Dict[str, str] = Body(...)):
    try:
        username = credentials.get("username")
        password = credentials.get("password")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")

        # Find user by username only
        user = users_collection.find_one({"username": username})
        if not user:
            print(f"❌ Login failed: User '{username}' not found")
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        # Verify password using secure comparison
        stored_password = user.get("password", "")
        
        # Debug: Log hash type for troubleshooting (don't log actual password)
        if stored_password.startswith('$2'):
            print(f"🔐 User '{username}' has bcrypt hash")
        elif stored_password.startswith('pbkdf2:'):
            print(f"🔐 User '{username}' has PBKDF2 hash")
        else:
            print(f"⚠️ User '{username}' has plaintext/unknown password format")
        
        if not verify_password(password, stored_password):
            print(f"❌ Login failed: Password verification failed for '{username}'")
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        print(f"✅ Password verified for user '{username}'")
        
        # Migrate plaintext password to hash if needed (one-time migration)
        if needs_rehash(stored_password):
            migrate_user_password(users_collection, username, password)

        # ✅ If user has no role field, assume admin
        role = user.get("role", "admin")

        # ✅ Create session token
        session_id = serializer.dumps(username)
        
        # Store session in Redis (with fallback to in-memory)
        store = await get_session_store_instance()
        await store.create(
            session_id,
            {"username": username, "role": role},
            SESSION_TTL_SECONDS
        )
        
        # Also store in memory for backward compatibility
        sessions[session_id] = {
            "username": username,
            "expires_at": datetime.utcnow() + timedelta(seconds=SESSION_TTL_SECONDS)
        }

        return {
            "message": "Login successful",
            "username": username,
            "session_id": session_id,
            "role": role  # ✅ return role to frontend
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login error: {str(e)}")




@app.post("/logout/")
async def logout(request: Request):
    session_id = request.headers.get("Authorization")
    if session_id:
        # Delete from Redis store
        store = await get_session_store_instance()
        await store.delete(session_id)
        
        # Also delete from in-memory cache
        sessions.pop(session_id, None)
    return {"message": "Logged out successfully"}


# ----------------------------
# User Profile Endpoints
# ----------------------------
@app.get("/profile/", dependencies=[Depends(verify_session)])
async def get_profile(request: Request):
    """Get current user's profile information (audit-safe fields only)"""
    try:
        session_id = request.headers.get("Authorization")
        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)
        
        user = users_collection.find_one({"username": username})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Return only audit-safe fields - no passwords or system secrets
        return {
            "username": user.get("username", ""),
            "email": user.get("email", ""),
            "displayName": user.get("displayName", user.get("username", "")),
            "role": user.get("role", "admin"),
            "createdAt": user.get("createdAt", "").isoformat() if user.get("createdAt") else "",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile fetch error: {str(e)}")


@app.put("/profile/update", dependencies=[Depends(verify_session)])
async def update_profile(request: Request, profile_data: Dict[str, Any] = Body(...)):
    """Update user's profile (audit-safe fields only - email)"""
    try:
        session_id = request.headers.get("Authorization")
        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)
        
        # Only allow updating audit-safe fields
        allowed_fields = ["email", "displayName"]
        update_data = {k: v for k, v in profile_data.items() if k in allowed_fields}
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields to update")
        
        update_data["updatedAt"] = datetime.utcnow()
        
        result = users_collection.update_one(
            {"username": username},
            {"$set": update_data}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {"message": "Profile updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile update error: {str(e)}")


@app.put("/profile/change-password", dependencies=[Depends(verify_session)])
async def change_password(request: Request, password_data: Dict[str, str] = Body(...)):
    """Change user's password (requires current password verification)"""
    try:
        session_id = request.headers.get("Authorization")
        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)
        
        current_password = password_data.get("current_password")
        new_password = password_data.get("new_password")
        
        if not current_password or not new_password:
            raise HTTPException(status_code=400, detail="Current and new password are required")
        
        if len(new_password) < 8:
            raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
        
        # Verify current password using secure comparison
        user = users_collection.find_one({"username": username})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        stored_password = user.get("password", "")
        if not verify_password(current_password, stored_password):
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        
        # Update password with secure hash
        hashed_password = hash_password(new_password)
        result = users_collection.update_one(
            {"username": username},
            {"$set": {
                "password": hashed_password,
                "password_updated_at": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            }}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {"message": "Password changed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Password change error: {str(e)}")



# ----------------------------
# Helper: rewrite links with tracking
# ----------------------------
def rewrite_links_with_tracking(html_body: str, campaign_id: str, email: str):
    return re.sub(
        r'href="(http[s]?://[^"]+)"',
        lambda m: f'href=\"{API_BASE}/track/click?c={campaign_id}&e={email}&url={m.group(1)}\"',
        html_body
    )
#changes 5
# def rewrite_links_with_tracking(html_body: str, campaign_id: str, email: str):
#     return re.sub(
#         r'href="(http[s]?://[^"]+)"',
#         lambda m: f'href=\"http://localhost:8000/track/click?c={campaign_id}&e={email}&url={m.group(1)}\"',
#         html_body
#     )

# ----------------------------
# Helper: inject open tracking pixel
# ----------------------------
def inject_open_tracking(html_body: str, campaign_id: str, email: str):
    pixel = f'<img src="{API_BASE}/track/open?c={campaign_id}&e={email}" width="1" height="1" style="display:none;" />'
    return html_body + pixel
#changes 6
# def inject_open_tracking(html_body: str, campaign_id: str, email: str):
#     pixel = f'<img src="http://localhost:8000/track/open?c={campaign_id}&e={email}" width="1" height="1" style="display:none;" />'
#     return html_body + pixel

# ----------------------------
# List Endpoints
# ----------------------------
@app.post("/create-list/",)
async def create_list(list_data: Dict[str, Any] = Body(...)):
    try:
        result = lists_collection.insert_one(list_data)
        list_data["_id"] = str(result.inserted_id)
        return {"message": "List created successfully", "list": list_data}
    except Exception as e:
        print(f"❌ List creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"List creation error: {str(e)}")

@app.get("/lists/",dependencies=[Depends(verify_session)])
async def get_lists(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum records to return")
):
    try:
        # Get total count
        total = lists_collection.count_documents({})
        
        # Get paginated lists
        lists = list(lists_collection.find().skip(skip).limit(limit))
        for list_item in lists:
            list_item["_id"] = str(list_item["_id"])
        
        return {
            "lists": lists,
            "total": total,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + len(lists)) < total
        }
    except Exception as e:
        print(f"❌ Failed to fetch lists: {e}")
        raise HTTPException(status_code=500, detail=f"Fetch lists error: {str(e)}")

@app.delete("/delete-list/{list_id}")
async def delete_list(list_id: str):
    try:
        result = lists_collection.delete_one({"_id": ObjectId(list_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="List not found")
        contacts_collection.delete_many({"listId": list_id})
        return {"message": "List deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

# ----------------------------
# Upload Contacts
# ----------------------------
@app.post("/upload-csv/")
async def upload_csv(data: Dict[str, List[Dict[str, Any]]] = Body(...)):
    contacts = data.get("contacts", [])
    inserted_contacts = []

    for contact in contacts:
        email = (contact.get("email") or "").strip()
        list_name = contact.get("listName")
        incoming_list_id = contact.get("listId")
        if not email:
            continue

        resolved_list_id = None
        try:
            if incoming_list_id and ObjectId.is_valid(str(incoming_list_id)):
                resolved_list_id = str(incoming_list_id)
            elif incoming_list_id:
                found = lists_collection.find_one({"name": incoming_list_id})
                resolved_list_id = str(found["_id"]) if found else incoming_list_id
            elif list_name:
                found = lists_collection.find_one({"name": list_name})
                resolved_list_id = str(found["_id"]) if found else None
        except Exception as e:
            print(f"[upload-csv] Error resolving list id/name: {e}")

        query = {"email": email}
        if resolved_list_id:
            query["listId"] = resolved_list_id
        elif list_name:
            query["listName"] = list_name

        if contacts_collection.find_one(query):
            continue

        if list_name:
            contact["listName"] = list_name
        if resolved_list_id:
            contact["listId"] = resolved_list_id

        try:
            result = contacts_collection.insert_one(contact)
            contact["_id"] = str(result.inserted_id)
            inserted_contacts.append(contact)
        except Exception as e:
            print(f"❌ MongoDB insert failed for {email}: {e}")
            continue

    return {"message": f"Uploaded {len(inserted_contacts)} contacts!", "contacts": inserted_contacts}

# ----------------------------
# Fetch Contacts
# ----------------------------
@app.get("/contacts/{list_identifier}")
async def get_contacts(
    list_identifier: str = Path(...),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum records to return")
):
    try:
        or_clauses = [
            {"listId": list_identifier},
            {"listName": list_identifier},
            {"listName": {"$regex": f"^{re.escape(list_identifier)}$", "$options": "i"}}
        ]
        query = {"$or": or_clauses}
        
        # Get total count
        total = contacts_collection.count_documents(query)
        
        # Get paginated contacts
        contacts = list(contacts_collection.find(query, {"_id": 0}).skip(skip).limit(limit))
        
        return {
            "contacts": contacts,
            "total": total,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + len(contacts)) < total
        }
    except Exception as e:
        print(f"❌ Failed to fetch contacts: {e}")
        raise HTTPException(status_code=500, detail=f"Fetch contacts error: {str(e)}")

# ----------------------------
# Templates
# ----------------------------
@app.post("/templates/")
async def save_template(template: Dict[str, Any] = Body(...)):
    try:
        # strip client-sent _id to avoid string _id pollution
        data = dict(template)
        data.pop("_id", None)

        result = templates_collection.insert_one(data)
        saved = templates_collection.find_one({"_id": result.inserted_id})
        saved["_id"] = str(saved["_id"])
        return {"message": "Template saved successfully", "template": saved}
    except Exception as e:
        print(f"❌ Template save failed: {e}")
        raise HTTPException(status_code=500, detail=f"Template save error: {str(e)}")


@app.get("/templates/",dependencies=[Depends(verify_session)])
async def get_templates(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum records to return")
):
    try:
        # Get total count
        total = templates_collection.count_documents({})
        
        # Get paginated templates
        templates = list(templates_collection.find().skip(skip).limit(limit))
        for t in templates:
            t["_id"] = str(t["_id"])
        
        return {
            "templates": templates,
            "total": total,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + len(templates)) < total
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Template fetch error: {str(e)}")

# ----------------------------
# Send Emails
# ----------------------------
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# SMTP Configuration (can be overridden via environment variables)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Cogentix Research")


def send_email_html(to_email: str, subject: str, html_content: str) -> bool:
    """
    Send an HTML email via SMTP.
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML body of the email
        
    Returns:
        True if email was sent successfully, False otherwise
        
    Raises:
        Exception if SMTP is not configured or sending fails
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        raise Exception("SMTP credentials not configured. Set SMTP_USER and SMTP_PASSWORD environment variables.")
    
    # Create the email message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    
    # Attach HTML content
    msg.attach(MIMEText(html_content, "html"))
    
    # Send the email
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [to_email], msg.as_string())
    
    return True


@app.post("/send-emails/")
async def send_emails(data: Dict[str, Any] = Body(...)):
    contacts = data.get("contacts", [])
    template = data.get("template")
    if not contacts or not template:
        raise HTTPException(status_code=400, detail="Missing contacts or template")

    subject = template.get("subject", "No Subject")
    html_content = template.get("htmlContent", "")
    campaign_id = str(ObjectId())

    reports_collection.insert_one({
        "campaignId": campaign_id,
        "subject": subject,
        "sent": [],
        "opens": [],
        "clicks": [],
        "createdAt": datetime.utcnow()
    })

    sent_emails, failed_emails = [], []

    for contact in contacts:
        email = (contact.get("email") or "").strip()
        if not email:
            continue
        try:
            personalized_html = re.sub(r"{{\s*contact.name\s*}}", contact.get("name") or "there", html_content)
            personalized_html = re.sub(r"{{\s*sender.companyName\s*}}", "Cogentix Research", personalized_html)

            personalized_html = rewrite_links_with_tracking(personalized_html, campaign_id, email)
            personalized_html = inject_open_tracking(personalized_html, campaign_id, email)

            send_email_html(email, subject, personalized_html)
            sent_emails.append(email)

            reports_collection.update_one(
                {"campaignId": campaign_id},
                {"$push": {"sent": {"email": email, "time": datetime.utcnow()}}}
            )
        except Exception as e:
            failed_emails.append({"email": email, "error": str(e)})

    return {"message": f"Sent {len(sent_emails)} emails!", "sent": sent_emails, "failed": failed_emails}

# ----------------------------
# Tracking Endpoints
# ----------------------------
@app.get("/track/open")
async def track_open(c: str, e: str):
    reports_collection.update_one(
        {"campaignId": c},
        {"$push": {"opens": {"email": e, "time": datetime.utcnow()}}},
        upsert=True
    )
    transparent_pixel = (
        b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80"
        b"\xff\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04"
        b"\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01"
        b"\x00\x01\x00\x00\x02\x02\x4c\x01\x00\x3b"
    )
    return Response(content=transparent_pixel, media_type="image/gif")

@app.get("/track/click")
async def track_click(c: str, e: str, url: str):
    reports_collection.update_one(
        {"campaignId": c},
        {"$push": {"clicks": {"email": e, "url": url, "time": datetime.utcnow()}}},
        upsert=True
    )
    return RedirectResponse(url)

# ----------------------------
# Reports
# ----------------------------
@app.get("/reports/",dependencies=[Depends(verify_session)])
async def get_reports():
    try:
        campaigns = list(reports_collection.find({}, {"_id": 0}))
        return {"campaigns": campaigns}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reports fetch error: {str(e)}")
# ----------------------------
# Update Template
# ----------------------------
@app.put("/templates/{template_id}")
async def update_template(template_id: str, template_data: Dict[str, Any] = Body(...)):
    try:
        # Never allow _id to be updated
        template_data = {k: v for k, v in template_data.items() if k != "_id"}

        matched = 0
        if ObjectId.is_valid(template_id):
            result = templates_collection.update_one(
                {"_id": ObjectId(template_id)}, {"$set": template_data}
            )
            matched = result.matched_count

        if matched == 0:
            result = templates_collection.update_one(
                {"_id": template_id}, {"$set": template_data}
            )
            matched = result.matched_count

        if matched == 0:
            raise HTTPException(status_code=404, detail="Template not found")

        return {"message": "Template updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Template update error: {str(e)}")



# ----------------------------
# Delete Template
# ----------------------------
@app.delete("/templates/{template_id}")
async def delete_template(template_id: str = Path(...)):
    try:
        # Try ObjectId FIRST if the string looks like one
        if ObjectId.is_valid(template_id):
            result = templates_collection.delete_one({"_id": ObjectId(template_id)})
            if result.deleted_count == 0:
                # Then try as plain string
                result = templates_collection.delete_one({"_id": template_id})
        else:
            result = templates_collection.delete_one({"_id": template_id})

        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail=f"Template not found")

        return {"message": "Template deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Template delete error: {str(e)}")


# ----------------------------
# Leads Collection
# ----------------------------
leads_collection = db["leads"]

# Create indexes for faster queries
try:
    leads_collection.create_index("createdAt", background=True)
    leads_collection.create_index("email", unique=True, sparse=True, background=True)
except Exception as e:
    print(f"Warning: Could not create leads indexes: {e}")

# Create a lead
@app.post("/leads/")
async def create_lead(lead_data: Dict[str, Any] = Body(...)):
    try:
        # Validate required fields
        if not lead_data.get("email") or not lead_data["email"].strip():
            raise HTTPException(status_code=400, detail="Email is required")

        lead_data["addedOn"] = datetime.utcnow()
        lead_data["createdAt"] = datetime.utcnow()
        lead_data["updatedAt"] = datetime.utcnow()
        result = leads_collection.insert_one(lead_data)
        lead_data["_id"] = str(result.inserted_id)
        return {"message": "Lead created successfully", "lead": lead_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lead creation error: {str(e)}")

# NOTE: /leads GET endpoint is handled by leads/router.py with full filtering support including source filter
# Do not add competing /leads/ routes here as it will conflict with the router's implementation

# Get a single lead by ID
@app.get("/leads/{lead_id}", dependencies=[Depends(verify_session)])
async def get_lead(lead_id: str):
    try:
        lead = leads_collection.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        lead["_id"] = str(lead["_id"])
        # Convert datetime to string for JSON serialization
        for date_field in ["createdAt", "updatedAt", "addedOn"]:
            if date_field in lead:
                lead[date_field] = lead[date_field].isoformat() if isinstance(lead[date_field], datetime) else str(lead[date_field])
        return {"lead": lead}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch lead error: {str(e)}")

# Update a lead
@app.put("/leads/{lead_id}")
async def update_lead(lead_id: str, lead_data: Dict[str, Any] = Body(...)):
    try:
        # Exclude _id from updates
        lead_data = {k: v for k, v in lead_data.items() if k not in ["_id", "createdAt", "addedOn"]}

        # Validate required fields if they are being updated
        if "email" in lead_data and (not lead_data["email"] or not lead_data["email"].strip()):
            raise HTTPException(status_code=400, detail="Email cannot be empty")

        lead_data["updatedAt"] = datetime.utcnow()
        result = leads_collection.update_one(
            {"_id": ObjectId(lead_id)}, {"$set": lead_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Lead not found")
        return {"message": "Lead updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lead update error: {str(e)}")

# Delete a lead
@app.delete("/leads/{lead_id}")
async def delete_lead(lead_id: str):
    try:
        result = leads_collection.delete_one({"_id": ObjectId(lead_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Lead not found")
        return {"message": "Lead deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lead delete error: {str(e)}")

# Bulk delete leads
@app.post("/leads/bulk-delete")
async def bulk_delete_leads(data: Dict[str, Any] = Body(...)):
    """Delete multiple leads by their IDs"""
    try:
        ids = data.get("ids", [])
        if not ids:
            raise HTTPException(status_code=400, detail="No IDs provided")
        
        object_ids = [ObjectId(id) for id in ids]
        result = leads_collection.delete_many({"_id": {"$in": object_ids}})
        
        return {
            "message": f"Successfully deleted {result.deleted_count} leads",
            "deleted_count": result.deleted_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk delete error: {str(e)}")

# Move lead to contacts (RFQ stage)
@app.post("/leads/{lead_id}/move-to-contacts")
async def move_lead_to_contacts(lead_id: str, stage_data: Dict[str, Any] = Body(...)):
    try:
        # Find the lead
        lead = leads_collection.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        # Create contact from lead data
        contact_data = {k: v for k, v in lead.items() if k != "_id"}
        contact_data["stage"] = stage_data.get("stage", "RFQ")
        contact_data["movedFromLeadAt"] = datetime.utcnow()
        contact_data["createdAt"] = lead.get("createdAt", datetime.utcnow())
        contact_data["updatedAt"] = datetime.utcnow()
        
        # Insert into contacts
        result = contacts_collection.insert_one(contact_data)
        contact_data["_id"] = str(result.inserted_id)
        
        # Delete from leads
        leads_collection.delete_one({"_id": ObjectId(lead_id)})
        
        return {"message": "Lead moved to contacts successfully", "contact": contact_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Move lead error: {str(e)}")


# Import leads from CSV - USES CANONICAL INGESTION PIPELINE
@app.post("/leads/import/csv")
async def import_leads_csv(file: UploadFile = File(...)):
    """
    Import leads from a CSV file using CANONICAL INGESTION PIPELINE.
    All leads go through the same pipeline as Gmail and Web Search.
    
    Expected columns: name, firstName, lastName, email, title, linkedin, location,
    companyName, companyDomain, companyWebsite, companyIndustry, companyType, etc.
    """
    import csv
    import io
    from leads.canonical_ingestion import ingest_lead
    
    try:
        content = await file.read()
        decoded = content.decode("utf-8-sig")  # Handle BOM
        reader = csv.DictReader(io.StringIO(decoded))
        
        results = {
            'inserted': 0,
            'updated': 0,
            'skipped': 0,
            'errors': []
        }
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
            try:
                # Skip empty rows
                if not any(row.values()):
                    results['skipped'] += 1
                    continue
                
                # Build canonical payload from CSV row
                payload = {
                    'email': row.get('email', '').strip(),
                    'name': row.get('name', '').strip() or f"{row.get('firstName', '')} {row.get('lastName', '')}".strip(),
                    'first_name': row.get('firstName', '').strip(),
                    'last_name': row.get('lastName', '').strip(),
                    'title': row.get('title', '').strip(),
                    'linkedin_url': row.get('linkedin', '').strip(),
                    'location': row.get('location', '').strip(),
                    'company': row.get('companyName', '').strip(),
                    'company_domain': row.get('companyDomain', '').strip(),
                    'phone': row.get('phone', '').strip(),
                }
                
                # Use CANONICAL ingestion (same as Gmail and Web Search)
                result = ingest_lead(
                    payload=payload,
                    source='csv',
                    source_detail=f'csv_import:{file.filename}',
                    skip_classification=True  # Batch classify after import
                )
                
                if result['success']:
                    if result['action'] == 'inserted':
                        results['inserted'] += 1
                    elif result['action'] == 'updated':
                        results['updated'] += 1
                    else:
                        results['skipped'] += 1
                else:
                    results['skipped'] += 1
                    if result['error']:
                        results['errors'].append(f"Row {row_num}: {result['error']}")
                
            except Exception as e:
                results['skipped'] += 1
                results['errors'].append(f"Row {row_num}: {str(e)}")
        
        return {
            "message": f"Import completed: {results['inserted']} inserted, {results['updated']} updated, {results['skipped']} skipped",
            "inserted": results['inserted'],
            "updated": results['updated'],
            "skipped": results['skipped'],
            "errors": results['errors'][:20],  # Limit error list
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV import error: {str(e)}")


# ----------------------------
# Contacts Collection (Qualified Leads with Stages)
# ----------------------------

# Finance DB for customers (canonical entity for accounts/clients/customers)
finance_db = client["finance_db"]
finance_customers_collection = finance_db["customers"]

# Create a contact
@app.post("/contacts/")
async def create_contact(contact_data: Dict[str, Any] = Body(...)):
    try:
        # Validate required fields
        if not contact_data.get("email") or not contact_data["email"].strip():
            raise HTTPException(status_code=400, detail="Email is required")
        
        contact_data["stage"] = contact_data.get("stage", "RFQ")
        contact_data["createdAt"] = datetime.utcnow()
        contact_data["updatedAt"] = datetime.utcnow()
        
        # Auto-sync to Customers (finance_db): create/update customer with company info
        linked_customer_id = None
        if contact_data.get("companyName"):
            # Check if customer already exists for this company
            existing_customer = finance_customers_collection.find_one({"company_name": contact_data["companyName"]})
            
            if existing_customer:
                # Update existing customer with latest company info
                linked_customer_id = str(existing_customer["_id"])
                update_fields = {"updated_at": datetime.utcnow()}
                if contact_data.get("companyEmail"):
                    update_fields["email"] = contact_data["companyEmail"]
                if contact_data.get("companyHeadquarters"):
                    update_fields["billing_address.line1"] = contact_data["companyHeadquarters"]
                    update_fields["shipping_address.line1"] = contact_data["companyHeadquarters"]
                
                finance_customers_collection.update_one(
                    {"_id": existing_customer["_id"]},
                    {"$set": update_fields}
                )
            else:
                # Create new customer for this company
                customer_data = {
                    "name": contact_data["companyName"],
                    "customer_type": "business",
                    "company_name": contact_data["companyName"],
                    "email": contact_data.get("companyEmail", ""),
                    "phone": "",
                    "gst_treatment": "unregistered",
                    "gstin": "",
                    "pan": "",
                    "billing_address": {
                        "line1": contact_data.get("companyHeadquarters", ""),
                        "line2": "",
                        "city": "",
                        "state": "",
                        "pincode": "",
                        "country": "India",
                    },
                    "shipping_address": {
                        "line1": contact_data.get("companyHeadquarters", ""),
                        "line2": "",
                        "city": "",
                        "state": "",
                        "pincode": "",
                        "country": "India",
                    },
                    "same_as_billing": True,
                    "payment_terms": 30,
                    "credit_limit": 0,
                    "currency": "INR",
                    "opening_balance": 0,
                    "notes": "",
                    "status": "active",
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }
                result_customer = finance_customers_collection.insert_one(customer_data)
                linked_customer_id = str(result_customer.inserted_id)
        
        # Store the linked customer ID in the contact
        contact_data["linked_customer_id"] = linked_customer_id
        result = contacts_collection.insert_one(contact_data)
        contact_data["_id"] = str(result.inserted_id)
        
        return {"message": "Contact created successfully", "contact": contact_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contact creation error: {str(e)}")

# Get all contacts
@app.get("/contacts/", dependencies=[Depends(verify_session)])
async def get_contacts():
    try:
        contacts = list(contacts_collection.find())
        
        # Build a map of all customers for quick lookup
        all_customers = {str(c["_id"]): c for c in finance_customers_collection.find()}
        
        for contact in contacts:
            contact["_id"] = str(contact["_id"])
            # Convert datetime to string for JSON serialization
            for date_field in ["createdAt", "updatedAt", "movedFromLeadAt", "addedOn"]:
                if date_field in contact:
                    contact[date_field] = contact[date_field].isoformat() if isinstance(contact[date_field], datetime) else str(contact[date_field])
            
            # Include linked customer info if available
            linked_customer_id = contact.get("linked_customer_id")
            if linked_customer_id and linked_customer_id in all_customers:
                customer = all_customers[linked_customer_id]
                contact["linked_customer"] = {
                    "_id": str(customer["_id"]),
                    "name": customer.get("name", ""),
                    "company_name": customer.get("company_name", ""),
                    "email": customer.get("email", ""),
                    "status": customer.get("status", "active")
                }
            elif contact.get("companyName"):
                # Try to find by company name if linked_customer_id not set
                for cid, customer in all_customers.items():
                    if customer.get("company_name") == contact["companyName"]:
                        contact["linked_customer_id"] = cid
                        contact["linked_customer"] = {
                            "_id": cid,
                            "name": customer.get("name", ""),
                            "company_name": customer.get("company_name", ""),
                            "email": customer.get("email", ""),
                            "status": customer.get("status", "active")
                        }
                        # Update the contact with the linked_customer_id
                        contacts_collection.update_one(
                            {"_id": ObjectId(contact["_id"])},
                            {"$set": {"linked_customer_id": cid}}
                        )
                        break
        
        return {"contacts": contacts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch contacts error: {str(e)}")

# Update a contact
@app.put("/contacts/{contact_id}")
async def update_contact(contact_id: str, contact_data: Dict[str, Any] = Body(...)):
    try:
        # Exclude _id from updates
        contact_data = {k: v for k, v in contact_data.items() if k not in ["_id", "createdAt", "movedFromLeadAt"]}
        
        # Validate required fields if they are being updated
        if "email" in contact_data and (not contact_data["email"] or not contact_data["email"].strip()):
            raise HTTPException(status_code=400, detail="Email cannot be empty")
        
        contact_data["updatedAt"] = datetime.utcnow()
        result = contacts_collection.update_one(
            {"_id": ObjectId(contact_id)}, {"$set": contact_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Contact not found")
        
        # Auto-sync to Customers (finance_db): update customer with company info
        if contact_data.get("companyName"):
            # Check if customer exists for this company
            existing_customer = finance_customers_collection.find_one({"company_name": contact_data["companyName"]})
            
            if existing_customer:
                # Update existing customer and store the link
                linked_customer_id = str(existing_customer["_id"])
                update_fields = {"updated_at": datetime.utcnow()}
                if contact_data.get("companyEmail"):
                    update_fields["email"] = contact_data["companyEmail"]
                if contact_data.get("companyHeadquarters"):
                    update_fields["billing_address.line1"] = contact_data["companyHeadquarters"]
                    update_fields["shipping_address.line1"] = contact_data["companyHeadquarters"]
                
                finance_customers_collection.update_one(
                    {"_id": existing_customer["_id"]},
                    {"$set": update_fields}
                )
                
                # Update the contact with the linked_customer_id
                contacts_collection.update_one(
                    {"_id": ObjectId(contact_id)},
                    {"$set": {"linked_customer_id": linked_customer_id}}
                )
        
        return {"message": "Contact updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contact update error: {str(e)}")

# Delete a contact
@app.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str):
    try:
        result = contacts_collection.delete_one({"_id": ObjectId(contact_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Contact not found")
        return {"message": "Contact deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contact delete error: {str(e)}")

# Bulk delete contacts
@app.post("/contacts/bulk-delete")
async def bulk_delete_contacts(data: Dict[str, Any] = Body(...)):
    """Delete multiple contacts by their IDs"""
    try:
        ids = data.get("ids", [])
        if not ids:
            raise HTTPException(status_code=400, detail="No IDs provided")
        
        object_ids = [ObjectId(id) for id in ids]
        result = contacts_collection.delete_many({"_id": {"$in": object_ids}})
        
        return {
            "message": f"Successfully deleted {result.deleted_count} contacts",
            "deleted_count": result.deleted_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk delete error: {str(e)}")

def generate_vid():
    while True:
        vid = str(datetime.utcnow().microsecond % 10000).zfill(4)
        if not vendors_collection.find_one({"vid": vid}):
            return vid

@app.post("/vendors/")
async def create_vendor(vendor_data: Dict[str, Any] = Body(...)):
    try:
        # Validate required fields
        if not vendor_data.get("vendorName") or not vendor_data["vendorName"].strip():
            raise HTTPException(status_code=400, detail="Vendor name is required")
        if not vendor_data.get("vendorVariable") or not vendor_data["vendorVariable"].strip():
            raise HTTPException(status_code=400, detail="Vendor Variable is required")
        if not vendor_data.get("vendorType") or not vendor_data["vendorType"].strip():
            raise HTTPException(status_code=400, detail="Vendor Type is required")
        if not vendor_data.get("status") or not vendor_data["status"].strip():
            raise HTTPException(status_code=400, detail="Status is required")

        # Validate redirect URLs if provided
        for url_field in ["completeRD", "terminateRD", "quotaRD"]:
            urls = vendor_data.get(url_field, [])
            if urls:
                # Handle both array and string format
                url_list = urls if isinstance(urls, list) else [urls]
                for url in url_list:
                    if url and url.strip():
                        is_valid, error_msg = validate_redirect_url(url.strip(), require_https=False)
                        if not is_valid:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Invalid {url_field} URL: {error_msg}"
                            )

        vendor_data["vid"] = generate_vid()
        result = vendors_collection.insert_one(vendor_data)
        vendor_data["_id"] = str(result.inserted_id)
        return {"message": "Vendor created successfully", "vendor": vendor_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vendor creation error: {str(e)}")

@app.get("/vendors/",dependencies=[Depends(verify_session)])
async def get_vendors():
    try:
        vendors = list(vendors_collection.find())
        for v in vendors:
            v["_id"] = str(v["_id"])
        return {"vendors": vendors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch vendors error: {str(e)}")

@app.put("/vendors/{vendor_id}")
async def update_vendor(vendor_id: str, vendor_data: Dict[str, Any] = Body(...)):
    try:
        vendor_data = {k: v for k, v in vendor_data.items() if k != "_id" and k != "vid"}
        
        # Validate redirect URLs if provided
        for url_field in ["completeRD", "terminateRD", "quotaRD"]:
            urls = vendor_data.get(url_field, [])
            if urls:
                # Handle both array and string format
                url_list = urls if isinstance(urls, list) else [urls]
                for url in url_list:
                    if url and url.strip():
                        is_valid, error_msg = validate_redirect_url(url.strip(), require_https=False)
                        if not is_valid:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Invalid {url_field} URL: {error_msg}"
                            )
        
        result = vendors_collection.update_one({"_id": ObjectId(vendor_id)}, {"$set": vendor_data})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return {"message": "Vendor updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vendor update error: {str(e)}")

@app.delete("/vendors/{vendor_id}")
async def delete_vendor(vendor_id: str):
    """
    Soft delete a panel vendor with safety checks.
    - Blocks if vendor has traffic records
    - Blocks if vendor is linked to a billing vendor
    """
    try:
        # First check if the vendor exists
        vendor = vendors_collection.find_one({"_id": ObjectId(vendor_id)})
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
        
        # Safety Check 1: Check for traffic records linked to this vendor
        if url_parameters_collection is not None:
            vid = vendor.get("vid")
            if vid:
                traffic_count = url_parameters_collection.count_documents({"vendorId": vid})
                if traffic_count > 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot delete vendor with {traffic_count} traffic records. Archive instead."
                    )
        
        # Safety Check 2: Check if linked to a billing vendor
        linked_billing_id = vendor.get("linked_billing_vendor_id")
        if linked_billing_id:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete vendor linked to billing vendor (ID: {linked_billing_id}). Unlink first."
            )
        
        # Soft delete instead of hard delete
        result = vendors_collection.update_one(
            {"_id": ObjectId(vendor_id)},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "status": "deleted"
                }
            }
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return {"message": "Vendor deleted successfully (soft delete)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vendor delete error: {str(e)}")
    

def generate_survey_no():
    while True:
        survey_no = str(datetime.utcnow().microsecond % 100000).zfill(5)
        if not projects_collection.find_one({"surveyNo": survey_no}):
            return survey_no
        
@app.post("/projects/")
async def create_project(project_data: Dict[str, Any] = Body(...)):
    try:
        # Validate required fields
        if not project_data.get("projectName") or not project_data["projectName"].strip():
            raise HTTPException(status_code=400, detail="Project name is required")
        if not project_data.get("salesPerson") or not project_data["salesPerson"].strip():
            raise HTTPException(status_code=400, detail="Sales person is required")
        if not project_data.get("client") or not project_data["client"].strip():
            raise HTTPException(status_code=400, detail="Client is required")

        project_data["surveyNo"] = generate_survey_no()
        project_data["createdAt"] = datetime.utcnow()
        result = projects_collection.insert_one(project_data)
        project_data["_id"] = str(result.inserted_id)
        return {"message": "Project created successfully", "project": project_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project creation error: {str(e)}")

@app.get("/projects/",dependencies=[Depends(verify_session)])
async def get_projects():
    try:
        projects = list(projects_collection.find())
        for p in projects:
            p["_id"] = str(p["_id"])
        return {"projects": projects}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch projects error: {str(e)}")

@app.put("/projects/{project_id}")
async def update_project(project_id: str, project_data: Dict[str, Any] = Body(...)):
    try:
        project_data = {k: v for k, v in project_data.items() if k not in ["_id", "surveyNo"]}
        result = projects_collection.update_one({"_id": ObjectId(project_id)}, {"$set": project_data})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"message": "Project updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project update error: {str(e)}")

@app.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """
    Soft delete a project with cascade validation.
    Checks for linked invoices, bills, and expenses before deletion.
    P0.13: Project Soft Delete with Cascade Validation
    """
    try:
        # First check if project exists
        project = projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Import finance collections for cascade validation
        finance_db = client["finance_db"]
        invoices_collection = finance_db["invoices"]
        bills_collection = finance_db["bills"]
        expenses_collection = finance_db["expenses"]
        
        # Check for linked invoices (excluding soft-deleted)
        linked_invoices = invoices_collection.count_documents({
            "project_id": project_id,
            "is_deleted": {"$ne": True}
        })
        if linked_invoices > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete project with {linked_invoices} linked invoice(s). Delete or unlink invoices first."
            )
        
        # Check for linked bills (excluding soft-deleted)
        linked_bills = bills_collection.count_documents({
            "project_id": project_id,
            "is_deleted": {"$ne": True}
        })
        if linked_bills > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete project with {linked_bills} linked bill(s). Delete or unlink bills first."
            )
        
        # Check for linked expenses (excluding soft-deleted)
        linked_expenses = expenses_collection.count_documents({
            "project_id": project_id,
            "is_deleted": {"$ne": True}
        })
        if linked_expenses > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete project with {linked_expenses} linked expense(s). Delete or unlink expenses first."
            )
        
        # Soft delete - set is_deleted flag instead of removing
        result = projects_collection.update_one(
            {"_id": ObjectId(project_id)},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "projectStatus": "Deleted"
                }
            }
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Project not found")
        
        return {"message": "Project deleted successfully (soft delete)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project delete error: {str(e)}")
