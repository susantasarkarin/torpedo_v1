import os
import traceback
import re
import logging
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
# itsdangerous is now used inside session_state.py
from fastapi import Request, Depends, APIRouter
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# Configure logging
logger = logging.getLogger(__name__)

# Set up basic logging configuration if not already configured
if not logging.getLogger().hasHandlers():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

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
    from .routers import cpx_api as cpx_api_router
    from .routers import cpx_app as cpx_router
    from .routers import finance as finance_router
    from .routers import settings as settings_router
    from .routers import gmail as gmail_router
    from .routers import gmail_app_router as gmail_api_router
    from .routers import rfq as rfq_router
    from .routers import operations as operations_router
    from .routers import health as health_router
    from .routers import users as users_router
    from .routers import roles as roles_router
    from .routers import approvals as approvals_router
    from .app.services.cpx_service import CPXService
    from .routers import survey_allocation as survey_allocation_router
    from .routers import cint as cint_router
    from .app.integrations.cint_integration import CintIntegration
    from .leads import router as leads_router
    from .routers import panel as panel_router
    from .routers import mail_operations as mail_operations_router
    from .routers import prompt_management as prompt_management_router
    from .routers import automation as automation_router
except Exception:
    # Fallback to absolute import for other runtimes
    from routers import traffic as traffic_router
    from routers import cpx_api as cpx_api_router
    from routers import cpx_app as cpx_router
    from routers import finance as finance_router
    from routers import settings as settings_router
    from routers import gmail as gmail_router
    from routers import gmail_app_router as gmail_api_router
    from routers import rfq as rfq_router
    from routers import operations as operations_router
    from routers import health as health_router
    from routers import users as users_router
    from routers import roles as roles_router
    from routers import approvals as approvals_router
    from app.services.cpx_service import CPXService
    from routers import survey_allocation as survey_allocation_router
    from routers import panel as panel_router
    from routers import cint as cint_router
    from app.integrations.cint_integration import CintIntegration
    from leads import router as leads_router
    from routers import mail_operations as mail_operations_router
    from routers import prompt_management as prompt_management_router
    from routers import automation as automation_router

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
# MongoDB connection (pooled singleton â€” shared across all modules)
# ----------------------------
try:
    from .database import get_client, get_database
except ImportError:
    from database import get_client, get_database

client = get_client()
db = get_database("email_automation")

# Traffic flow database (from app.py)
try:
    traffic_db = client["traffic_flow_db"]
    url_parameters_collection = traffic_db["url_parameters"]
    # Test connection
    client.admin.command('ping')
    print("âœ… MongoDB connected successfully (including traffic_flow_db)!")
except Exception as e:
    url_parameters_collection = None
    print(f"âš ï¸ MongoDB traffic_flow_db connection issue: {e}")
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
    print("âœ… CPX Research database collections initialized")
except Exception as e:
    cpx_surveys_collection = None
    cpx_filters_collection = None
    print(f"âš ï¸ CPX Research database initialization issue: {e}")

# Settings database for app configuration (profile > settings)
try:
    settings_db = client["torpedo_settings"]
    app_settings_collection = settings_db["app_settings"]
except Exception as e:
    app_settings_collection = None
    print(f"âš ï¸ Settings database initialization issue: {e}")


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
            print(f"âš ï¸ Could not read CPX config from settings: {e}")
    
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
# Session Management  (extracted to session_state.py)
# ----------------------------
from session_state import (
    SECRET_KEY, SESSION_TTL_SECONDS, serializer,
    BoundedSessionCache, sessions,
    get_session_store_instance, verify_session,
)


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
# Global Exception Handler - Ensures all errors return JSON
# ----------------------------
from starlette.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    """Convert all HTTP exceptions to JSON responses"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "path": str(request.url.path)
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Convert all unhandled exceptions to JSON responses"""
    print(f"âŒ Unhandled exception: {type(exc).__name__}: {str(exc)}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "error": f"Internal server error: {type(exc).__name__}",
            "status_code": 500,
            "path": str(request.url.path),
            "detail": str(exc)[:200]  # Limit error message length
        }
    )

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
            print(f"âš ï¸ SLOW REQUEST: {request.method} {request.url.path} - {process_time:.0f}ms")
        
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

    # Initialize lead collections
    leads_raw_collection = gmail_db.get_collection('leads_raw')
    leads_enriched_collection = gmail_db.get_collection('leads_enriched')

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
    
    # Check 8: Gmail â†’ Lead Pipeline Health (CRITICAL)
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
            health["warnings"].append(f"Low conversion: {inbound_emails_24h} emails â†’ {gmail_leads_24h} leads")
        
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
            print("âœ… Traffic service initialized")
        except Exception as e:
            print(f"âš ï¸ Traffic service initialization issue: {e}")
    
    # Inject Survey Allocation Service into traffic router
    try:
        from app.services.survey_allocation_service import get_survey_allocation_service
        survey_allocation_service_instance = get_survey_allocation_service()
        traffic_router.set_survey_allocation_service(survey_allocation_service_instance)
        print("âœ… Survey allocation service injected into traffic router")
    except Exception as e:
        print(f"âš ï¸ Survey allocation service injection issue: {e}")

# ============================================
# CPX Callback/Postback Collections (MUST be before router inclusion)
# ============================================
# Inject vendors collection into traffic router for CPX callback handling
try:
    traffic_router.set_vendors_collection(vendors_collection)
    print("âœ… Vendors collection injected into traffic router")
except Exception as e:
    print(f"âš ï¸ Vendors collection injection issue: {e}")

# Initialize CPX callback logs collection and inject into traffic router
try:
    cpx_callback_logs_collection = traffic_db["cpx_callback_logs"]
    traffic_router.set_cpx_callback_logs_collection(cpx_callback_logs_collection)
    print("âœ… CPX callback logs collection initialized")
except Exception as e:
    print(f"âš ï¸ CPX callback logs collection issue: {e}")

# Initialize CPX S2S postback logs collection for redirect verification
try:
    cpx_postback_logs_for_traffic = traffic_db["cpx_postback_logs"]
    traffic_router.set_cpx_postback_logs_collection(cpx_postback_logs_for_traffic)
    print("âœ… CPX postback logs injected into traffic router for S2S verification")
except Exception as e:
    print(f"âš ï¸ CPX postback logs injection issue: {e}")

app.include_router(traffic_router.router)

# All remaining routers are registered via router_registry.register_simple_routers(app)
# which is called after the complex service-injected routers below.

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
    print("âœ… CPX Research router initialized")
    print("âœ… CPX service injected into traffic router")
else:
    print("âš ï¸ CPX Research router not initialized due to database connection issue")

# Cint Integration Setup
try:
    from database_setup_cint import setup_cint_database
    # Initialize Cint database collections
    setup_cint_database(mongo_uri=MONGO_URI)
    print("âœ… Cint database collections initialized")
    
    # Initialize CintIntegration with environment variables or defaults
    cint_integration = CintIntegration.load_from_env()
    cint_integration.initialize()
    
    # Wire up services to router for dependency injection
    cint_router.set_cint_service(cint_integration.cint_service)
    cint_router.set_cint_allocation_ext(cint_integration.allocation_extension)
    traffic_router.set_cint_service(cint_integration.cint_service)  # Inject CINT service into traffic router for survey allocation
    
    # Register Cint router
    app.include_router(cint_router.router, prefix="/api/cint", tags=["Cint Research"])
    print("âœ… Cint Research router initialized")
    print(f"âœ… Cint integration active (Supplier Code: {cint_integration.supplier_code})")
except Exception as e:
    print(f"âš ï¸ Cint Research setup failed: {e}")
    import traceback
    traceback.print_exc()


# ============================================
#CPX API Router (trans_id based flow - no message_id)
# ============================================
try:
    # Initialize survey_transactions collection for the new CPX API flow
    survey_transactions_collection = traffic_db["survey_transactions"]
    cpx_postback_logs_collection = traffic_db["cpx_postback_logs"]
    
    # ============================================
    # CPX ENTRY GUARD COLLECTION (TASK 3 - Single-Use ext_user_id)
    # ============================================
    # This collection prevents ext_user_id reuse which causes CPX to reject traffic
    # with errors like: already_clicked, already_do_internal, api_standart_screen_out
    cpx_entry_guards_collection = traffic_db["cpx_entry_guards"]
    
    # Create indexes for CPX entry guards
    try:
        # Unique index on ext_user_id to prevent reuse
        cpx_entry_guards_collection.create_index("ext_user_id", unique=True, background=True)
        cpx_entry_guards_collection.create_index("status", background=True)
        cpx_entry_guards_collection.create_index("created_at", background=True)
        # TTL index to auto-expire old entries after 7 days
        cpx_entry_guards_collection.create_index("created_at", expireAfterSeconds=604800, background=True)
        print("âœ… CPX entry guards collection initialized with unique ext_user_id index")
    except Exception as idx_err:
        print(f"âš ï¸ CPX entry guards index may already exist: {idx_err}")
    
    # Inject into traffic router
    traffic_router.set_cpx_entry_guards_collection(cpx_entry_guards_collection)
    
    # Create unique index on trans_id to prevent duplicate transactions
    # This is CRITICAL for idempotency and fraud prevention
    try:
        survey_transactions_collection.create_index("trans_id", unique=True, background=True)
        print("âœ… Unique index on trans_id created/verified")
    except Exception as idx_err:
        print(f"âš ï¸ trans_id index may already exist or error: {idx_err}")
    
    # Create index on subid for faster lookups by SFWID
    try:
        survey_transactions_collection.create_index("subid", background=True)
        survey_transactions_collection.create_index("status", background=True)
        survey_transactions_collection.create_index("created_at", background=True)
        print("âœ… Additional indexes on survey_transactions created/verified")
    except Exception as idx_err:
        print(f"âš ï¸ Additional indexes warning: {idx_err}")
    
    # Inject collections into cpx_api_router
    cpx_api_router.set_survey_transactions_collection(survey_transactions_collection)
    cpx_api_router.set_cpx_postback_logs_collection(cpx_postback_logs_collection)
    cpx_api_router.set_url_parameters_collection(url_parameters_collection)  # Traffic records
    cpx_api_router.set_vendors_collection(vendors_collection)  # Vendors for postback forwarding
    
    # Include the CPX API router (trans_id based flow)
    app.include_router(cpx_api_router.router)
    print("âœ… CPX API router initialized (trans_id flow)")
    print("âœ… Survey transactions collection initialized")
    print("âœ… CPX vendor postback forwarding enabled")
except Exception as e:
    print(f"âš ï¸ CPX API router not initialized: {e}")
    import traceback
    traceback.print_exc()

# Settings, health, performance, gmail, survey allocation routers
# are registered by register_simple_routers(app) below.

# Survey Allocation & Quality Control Engine router
try:
    app.include_router(survey_allocation_router.router)
    print("âœ… Survey Allocation router included")
except Exception as e:
    print(f"âš ï¸ Survey Allocation router not included: {e}")

# Survey Pool, Leads, and all remaining routers
try:
    from router_registry import register_simple_routers
    # Include leads router first (has its own import at top level)
    try:
        app.include_router(leads_router.router)
        print("âœ… Leads AI Classification router included")
    except Exception as _leads_err:
        print(f"âš ï¸ Leads router not included: {_leads_err}")
    register_simple_routers(app)
    from routers.auth_handler import router as _auth_router
    app.include_router(_auth_router)
    print("âœ… auth_handler router included")
except Exception as e:
    print(f"âš ï¸ router_registry failed: {e}")
    import traceback; traceback.print_exc()

# ----------------------------
# APScheduler for CPX refresh job
# ----------------------------
scheduler = BackgroundScheduler()
cpx_refresh_job: Optional[Any] = None

def refresh_cpx_inventory():
    """
    â›” DISABLED - CPX CANNOT BE REFRESHED IN BACKGROUND JOBS
    
    CPX Research binds survey hrefs to:
      - ext_user_id (stable vendor ID)
      - IP address (real client IP)  
      - User-Agent (real browser UA)
    
    Background jobs cannot provide real client IP/UA, so any surveys
    fetched here would produce UNUSABLE hrefs that fail on click.
    
    The ONLY valid way to get CPX surveys is via HTTP request:
      cpx_service.fetch_and_allocate_for_respondent(
          vendor_user_id=rid,
          internal_tracking_id=sfwid,
          user_ip=real_client_ip,
          user_agent=real_browser_ua
      )
    
    This job now only performs cleanup of old survey metadata.
    """
    if cpx_service is None:
        print("âš ï¸ CPX service not initialized, skipping cleanup")
        return
    
    try:
        print(f"ðŸ”„ [CPX] Starting scheduled cleanup at {datetime.utcnow().isoformat()}")
        
        # Get filter settings from database
        filter_settings = get_survey_filter_settings()
        deletion_days = filter_settings.get("deletion_period_days", 7)
        
        # Cleanup surveys older than configured days (metadata only)
        cpx_service.cleanup_old_surveys(days=deletion_days)
        
        # â›” DO NOT fetch new surveys - CPX requires real client IP/UA
        # surveys = cpx_service.fetch_cpx_surveys()  # DISABLED
        
        print(f"âœ… [CPX] Cleanup complete. Note: Survey fetch disabled - use HTTP context.")
    except Exception as e:
        print(f"âŒ [CPX] Cleanup failed: {str(e)}")
        traceback.print_exc()


def background_gmail_sync():
    """
    Background job to sync emails for all registered mailboxes.
    Runs every 5 minutes to pull new emails without human intervention.
    Also auto-classifies new emails using OpenAI and extracts leads.
    """
    try:
        print(f"ðŸ”„ [Gmail] Starting background sync at {datetime.utcnow().isoformat()}")
        
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
                        print(f"   ðŸ“§ {mb['email']}: +{new_count} new emails")
                except Exception as e:
                    print(f"   âš ï¸ {mb['email']}: sync error - {e}")
            
            print(f"âœ… [Gmail] Background sync complete: {total_synced} new emails across {len(mailboxes)} mailboxes")
            
            # Auto-classification using Gemini (via ai_governance module)
            if total_synced > 0:
                try:
                    from leads.email_classifier import classify_all_pending_emails
                    print(f"ðŸ¤– [AI] Starting AI auto-classification of {min(total_synced, 100)} emails...")
                    # Use 'background' source for higher rate limits
                    classify_result = classify_all_pending_emails(batch_size=20, max_batches=5, source="background")
                    success_count = classify_result.get('total_success', 0)
                    print(f"âœ… [AI] Classified {success_count} emails using AI")
                except ImportError as ie:
                    print(f"âš ï¸ Could not import classifier: {ie}")
                except Exception as e:
                    print(f"âš ï¸ Auto-classification failed: {e}")
            #         print(f"âš ï¸ [AI] Email classifier not available: {ie}")
            #     except Exception as classify_err:
            #         print(f"âš ï¸ [AI] Classification error: {classify_err}")
                    
        except ImportError:
            print("âš ï¸ [Gmail] Gmail Workspace Service not available")
        except Exception as e:
            print(f"âš ï¸ [Gmail] Workspace sync error: {e}")
        
    except Exception as e:
        print(f"âŒ [Gmail] Background sync failed: {str(e)}")
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
            print(f"ðŸ”„ [Cint] Health check at {datetime.utcnow().isoformat()}")
            
            if not cint_integration or not cint_integration.cint_service:
                print("âš ï¸ [Cint] Integration not initialized")
                return
            
            # Run click-based cleanup for unclicked surveys (older than 3 days with 0 clicks)
            try:
                deleted_count = cint_integration.cint_service.cleanup_unclicked_surveys(days=3)
                if deleted_count > 0:
                    print(f"ðŸ—‘ï¸ [Cint] Cleaned up {deleted_count} unclicked surveys")
            except Exception as cleanup_error:
                print(f"âš ï¸ [Cint] Cleanup error: {cleanup_error}")
            
            # Check current subscription status
            status_result = await cint_integration.cint_service.get_opportunities_subscription()
            
            if status_result.get("success"):
                print("âœ… [Cint] Webhook subscription is active")
            else:
                # Subscription not found or expired, re-subscribe
                print("âš ï¸ [Cint] Subscription inactive, attempting to resubscribe...")
                
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
                    print(f"âœ… [Cint] Resubscribed successfully: {CINT_WEBHOOK_CALLBACK_URL}")
                else:
                    print(f"âŒ [Cint] Resubscribe failed: {result.get('error')}")
                    
        except Exception as e:
            print(f"âŒ [Cint] Health check failed: {str(e)}")
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


def refresh_cint_inventory():
    """
    Background job to refresh CINT survey inventory from offerwall API.
    
    This is a FALLBACK mechanism in case webhooks are not working.
    Polls the legacy Fulcrum AllOfferwall API and syncs surveys to MongoDB.
    
    Runs every 5 minutes (configurable) to ensure fresh survey inventory.
    """
    import asyncio
    
    async def _fetch_and_sync():
        try:
            print(f"ðŸ”„ [Cint] Starting survey inventory refresh at {datetime.utcnow().isoformat()}")
            
            if not cint_integration or not cint_integration.cint_service:
                print("âš ï¸ [Cint] Integration not initialized, skipping refresh")
                return
            
            # Fetch and sync surveys from offerwall API
            result = await cint_integration.cint_service.sync_surveys_from_offerwall(apply_filters=False)
            
            if result.get("success"):
                fetched = result.get("stats", {}).get("fetched", 0)
                stored = result.get("stats", {}).get("stored", 0)
                print(f"âœ… [Cint] Refresh complete: {fetched} fetched, {stored} stored/updated")
            else:
                print(f"âš ï¸ [Cint] Refresh returned no success: {result}")
                
        except Exception as e:
            print(f"âŒ [Cint] Inventory refresh failed: {str(e)}")
            traceback.print_exc()
    
    # Run the async function
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_fetch_and_sync())
        else:
            loop.run_until_complete(_fetch_and_sync())
    except RuntimeError:
        # No event loop, create one
        asyncio.run(_fetch_and_sync())


def background_survey_sync():
    """
    Background job to sync and activate surveys from CPX/CINT pools.
    
    This job evaluates surveys against filter criteria and marks eligible
    surveys as is_active_in_pool=True, making them available for traffic allocation.
    
    Runs every 10 minutes to ensure surveys are properly activated.
    """
    try:
        print(f"ðŸ”„ [Survey Pool] Starting sync at {datetime.utcnow().isoformat()}")
        
        from app.services.activation_service import get_activation_service
        
        service = get_activation_service()
        stats = service.sync_and_activate_surveys()
        
        cpx_activated = stats.get("cpx_activated", 0)
        cint_activated = stats.get("cint_activated", 0)
        total_activated = cpx_activated + cint_activated
        
        if total_activated > 0:
            print(f"âœ… [Survey Pool] Sync complete: {total_activated} surveys activated (CPX: {cpx_activated}, CINT: {cint_activated})")
        else:
            print(f"â„¹ï¸ [Survey Pool] Sync complete: No new surveys to activate")
            
    except Exception as e:
        print(f"âŒ [Survey Pool] Sync failed: {str(e)}")
        traceback.print_exc()


def background_historic_email_sync():
    """
    Background job to download historic emails for all mailboxes.
    Uses rate-limited backfill with exponential backoff.
    
    Features:
    - Configurable rate limiting (default: 500 emails/minute)
    - Exponential backoff on rate limit errors (30s â†’ 60s â†’ 120s â†’ 300s)
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
                    print("âš ï¸ [Backfill] Gmail Workspace Service not available")
                    return
            
            # Initialize service
            ws_service = GmailWorkspaceService(mongo_uri=MONGO_URI)
            ws_service.load_service_account()
            
            if not ws_service.is_configured():
                return  # Silent skip if not configured
            
            # Check if backfill is enabled (method may not exist in all versions)
            is_enabled_fn = getattr(ws_service, 'is_backfill_enabled', None)
            if is_enabled_fn and not is_enabled_fn():
                return  # Silent skip if paused
            
            # Run backfill cycle with rate limiting
            run_backfill_fn = getattr(ws_service, 'run_backfill_cycle', None)
            if not run_backfill_fn:
                return  # Method not available in this version
            result = run_backfill_fn()
            
            if result.get("skipped"):
                return  # Backfill paused, skip silently
            
            processed = result.get("processed", 0)
            total_fetched = result.get("total_fetched", 0)
            duration = result.get("duration_seconds", 0)
            
            if total_fetched > 0:
                print(f"ðŸ“¥ [Backfill] Cycle complete: +{total_fetched} emails from {processed} mailbox(es) in {duration:.1f}s")
            
            # Log individual results if there were errors
            for r in result.get("results", []):
                if r.get("error"):
                    print(f"   âš ï¸ [Backfill] {r.get('email')}: {r.get('error')}")
            
        except Exception as e:
            print(f"âŒ [Backfill] Historic email sync failed: {str(e)}")
            traceback.print_exc()
    
    # Run in a separate thread to not block the scheduler
    thread = threading.Thread(target=_run_historic_sync, daemon=True)
    thread.start()


def weekly_panel_mail_integration_job():
    """
    Weekly panel mailing automation.

    Flow:
    1) Fetch panelist data from configured SFW export/API link (CSV/JSON)
    2) Upsert new panelists into campaign_platform.panelists
    3) Send panel invitation/weekly mail batch via existing panel email service
    """
    enabled = os.getenv("PANEL_WEEKLY_MAIL_ENABLED", "false").lower() == "true"
    if not enabled:
        print("â„¹ï¸ [PanelWeekly] Job skipped (PANEL_WEEKLY_MAIL_ENABLED=false)")
        return

    source_url = (os.getenv("SFW_PANEL_EXPORT_URL", "") or "").strip()
    if not source_url:
        print("âš ï¸ [PanelWeekly] SFW_PANEL_EXPORT_URL is missing; cannot run weekly integration")
        return

    data_format = (os.getenv("SFW_PANEL_EXPORT_FORMAT", "auto") or "auto").strip().lower()
    root_key = (os.getenv("SFW_PANEL_EXPORT_ROOT_KEY", "") or "").strip()
    country = (os.getenv("PANEL_WEEKLY_MAIL_COUNTRY", "") or "").strip() or None
    force_resend = os.getenv("PANEL_WEEKLY_FORCE_RESEND", "true").lower() == "true"

    try:
        headers = {}
        headers_json = (os.getenv("SFW_PANEL_EXPORT_HEADERS_JSON", "") or "").strip()
        if headers_json:
            import json
            parsed = json.loads(headers_json)
            if isinstance(parsed, dict):
                headers = {str(k): str(v) for k, v in parsed.items()}

        try:
            from .routers.panel_admin import (
                _fetch_link_data,
                _parse_csv_text,
                _extract_first_list_payload,
                _upsert_panelists,
            )
            from .services.panel_email_service import send_bulk_invitations
        except ImportError:
            from routers.panel_admin import (
                _fetch_link_data,
                _parse_csv_text,
                _extract_first_list_payload,
                _upsert_panelists,
            )
            from services.panel_email_service import send_bulk_invitations

        fetched = _fetch_link_data(source_url, request_headers=headers)
        text = fetched["text"]
        content_type = fetched["content_type"]

        detected_format = data_format
        if detected_format == "auto":
            if "json" in content_type:
                detected_format = "json"
            elif "csv" in content_type:
                detected_format = "csv"
            else:
                stripped = text.lstrip()
                detected_format = "json" if stripped.startswith("[") or stripped.startswith("{") else "csv"

        rows = []
        if detected_format == "csv":
            rows = _parse_csv_text(text)
        else:
            import json
            payload = json.loads(text)
            if root_key and isinstance(payload, dict) and isinstance(payload.get(root_key), list):
                rows = [item for item in payload[root_key] if isinstance(item, dict)]
            else:
                rows = _extract_first_list_payload(payload)

        if not rows:
            print("âš ï¸ [PanelWeekly] No rows found in SFW payload; skipping send")
            return

        upsert_result = _upsert_panelists(rows, source="weekly_link_import")
        send_result = send_bulk_invitations(country=country, force_resend=force_resend)

        print(
            "âœ… [PanelWeekly] Completed | "
            f"fetched={len(rows)} inserted={upsert_result.get('inserted', 0)} "
            f"skipped={upsert_result.get('skipped', 0)} sent={send_result.get('sent', 0)} "
            f"send_skipped={send_result.get('skipped', 0)} failed={send_result.get('failed', 0)}"
        )
    except Exception as e:
        print(f"âŒ [PanelWeekly] Weekly integration failed: {e}")
        traceback.print_exc()


@app.on_event("startup")
async def startup_event():
    """Initialize scheduler and start background jobs"""
    global cpx_refresh_job

    # NOTE: setup_indexes() is intentionally NOT called on every startup.
    # On MongoDB 4.2+ the background=True flag is ignored, so 130+ foreground
    # index builds would lock collections for minutes on large datasets.
    # Run `python indexes.py` manually on first deploy or after schema changes.

    # Initialize Clay-Level Features
    try:
        try:
            from .leads.clay_init import initialize_clay_features
        except ImportError:
            from leads.clay_init import initialize_clay_features
        
        await initialize_clay_features()
    except Exception as e:
        print(f"âš ï¸ Clay initialization error: {e}")
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
                print("âœ… Cint webhook already subscribed")
            else:
                # Create subscription if not already subscribed (404 means no subscription exists)
                print("ðŸ“¡ Subscribing to Cint opportunities webhook...")
                
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
                    print(f"âœ… Cint webhook subscription created: {callback_url}")
                else:
                    print(f"âš ï¸ Cint webhook subscription failed: {result.get('error')}")
    except ImportError:
        print("âš ï¸ Cint models not available for auto-subscription")
    except Exception as e:
        print(f"âš ï¸ Cint webhook subscription error: {e}")
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
            print("âœ… Email Sync workers started (background sync enabled)")
    except Exception as e:
        print(f"âš ï¸ Could not start Email Sync workers: {e}")
    
    # Initialize background job scheduler for continuous lead generation
    # This handles automatic resumption of paused web search jobs, daily limit resets, etc.
    try:
        try:
            from .background_job_scheduler import initialize_scheduler
        except ImportError:
            from background_job_scheduler import initialize_scheduler
        
        initialize_scheduler()
        print("âœ… Background job scheduler initialized (auto-resume web search jobs every 5 min)")
    except Exception as e:
        print(f"âš ï¸ Could not initialize background job scheduler: {e}")
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
            print(f"â¸ï¸ Web search auto-resume is DISABLED. {len(incomplete_jobs)} jobs not resumed.")
            print("   Enable with: POST /leads/import/web-search/control/enable-auto-resume")
        elif global_paused:
            print(f"â¸ï¸ Global web search is PAUSED. {len(incomplete_jobs)} jobs not resumed.")
            print(f"   Reason: {search_control.get('paused_reason', 'Unknown')}")
            print("   Resume with: POST /leads/import/web-search/control/resume")
        elif circuit_open:
            print(f"ðŸ”´ Circuit breaker OPEN (too many API errors). {len(incomplete_jobs)} jobs not resumed.")
            print("   Reset with: POST /leads/import/web-search/control/resume")
        elif incomplete_jobs:
            print(f"ðŸ”„ Found {len(incomplete_jobs)} incomplete web search jobs to resume...")
            for job in incomplete_jobs:
                job_id = job["job_id"]
                print(f"   Resuming job {job_id} (status: {job['status']}, imported: {job['total_imported']}/{job['target_count']})")
                # Schedule the job to run
                asyncio.create_task(run_web_search_job(job_id))
            print(f"âœ… Resumed {len(incomplete_jobs)} web search jobs")
        else:
            print("â„¹ï¸ No incomplete web search jobs to resume")
    except Exception as e:
        print(f"âš ï¸ Could not check/resume web search jobs: {e}")
    
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
                print(f"âœ… CPX refresh job scheduled (every {refresh_interval} seconds)")
                # Schedule initial fetch as background task (non-blocking)
                import asyncio
                asyncio.create_task(asyncio.to_thread(refresh_cpx_inventory))
                print("ðŸš€ Initial CPX survey fetch scheduled (running in background)")
            else:
                print("âš ï¸ CPX auto-refresh is disabled in settings")
        except Exception as e:
            print(f"âŒ Failed to schedule CPX refresh job: {str(e)}")
            traceback.print_exc()

    # Ensure the APScheduler is running even when CPX auto-refresh is disabled,
    # so that Gmail sync, Cint health check, outreach send processor, etc. can register.
    try:
        if not scheduler.running:
            scheduler.start()
            print("âœ… APScheduler started (CPX auto-refresh disabled, starting for other jobs)")
    except Exception as e:
        print(f"âš ï¸ Could not start APScheduler: {e}")

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
            print("âœ… Gmail background sync job scheduled (every 5 minutes)")
        else:
            print("âš ï¸ Scheduler not running, Gmail sync job not scheduled")
    except Exception as e:
        print(f"âš ï¸ Could not schedule Gmail sync job: {e}")
    
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
            print("âœ… Cint health check job scheduled (every 30 minutes)")
    except Exception as e:
        print(f"âš ï¸ Could not schedule Cint health check job: {e}")
    
    # ----------------------------
    # Cint Survey Inventory Refresh (every 5 minutes - fallback for webhooks)
    # ----------------------------
    try:
        if scheduler.running and cint_integration and cint_integration.cint_service:
            scheduler.add_job(
                refresh_cint_inventory,
                IntervalTrigger(seconds=300),  # Every 5 minutes
                id="cint_inventory_refresh",
                name="Cint Survey Inventory Refresh",
                replace_existing=True
            )
            print("âœ… Cint inventory refresh job scheduled (every 5 minutes)")
            
            # Schedule initial fetch as background task (non-blocking)
            import asyncio
            asyncio.create_task(asyncio.to_thread(refresh_cint_inventory))
            print("ðŸš€ Initial Cint survey fetch scheduled (running in background)")
    except Exception as e:
        print(f"âš ï¸ Could not schedule Cint inventory refresh job: {e}")
    
    # ----------------------------
    # Survey Pool Sync & Activation (every 10 minutes)
    # ----------------------------
    try:
        if scheduler.running:
            scheduler.add_job(
                background_survey_sync,
                IntervalTrigger(seconds=600),  # Every 10 minutes
                id="survey_pool_sync",
                name="Survey Pool Sync & Activation",
                replace_existing=True
            )
            print("âœ… Survey pool sync job scheduled (every 10 minutes)")
            
            # Run initial sync on startup (non-blocking)
            import threading
            threading.Thread(target=background_survey_sync, daemon=True).start()
            print("ðŸš€ Initial survey pool sync scheduled (running in background)")
    except Exception as e:
        print(f"âš ï¸ Could not schedule survey pool sync job: {e}")
    
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
            print("âœ… Historic email backfill job scheduled (every 30 seconds, rate-limited)")
    except Exception as e:
        print(f"âš ï¸ Could not schedule historic email sync job: {e}")

    # ----------------------------
    # Cold Outreach Send Processor (every 60 seconds)
    # ----------------------------
    try:
        if scheduler.running:
            def _outreach_send_job():
                try:
                    try:
                        from .routers.cold_outreach_router import process_due_outreach_sends
                    except ImportError:
                        from routers.cold_outreach_router import process_due_outreach_sends
                    process_due_outreach_sends()
                except Exception as e:
                    print(f"[OutreachSend] Error: {e}")

            scheduler.add_job(
                _outreach_send_job,
                IntervalTrigger(seconds=60),
                id="outreach_send_processor",
                name="Cold Outreach Send Processor",
                replace_existing=True
            )
            print("âœ… Cold outreach send processor scheduled (every 60 seconds)")
    except Exception as e:
        print(f"âš ï¸ Could not schedule outreach send processor: {e}")

    # ----------------------------
    # Cold Outreach Bounce & Reply Scanner (every 5 minutes)
    # Also runs a backfill of all historical replied leads on each cycle.
    # ----------------------------
    try:
        if scheduler.running:
            def _outreach_bounce_reply_job():
                try:
                    try:
                        from .routers.cold_outreach_router import (
                            process_outreach_bounces_and_replies,
                            sync_outreach_replies_to_leads,
                        )
                    except ImportError:
                        from routers.cold_outreach_router import (
                            process_outreach_bounces_and_replies,
                            sync_outreach_replies_to_leads,
                        )
                    process_outreach_bounces_and_replies()
                    # Backfill any replied leads not yet in the leads collection
                    sync_outreach_replies_to_leads()
                except Exception as e:
                    print(f"[OutreachScanner] Error: {e}")

            scheduler.add_job(
                _outreach_bounce_reply_job,
                IntervalTrigger(seconds=300),
                id="outreach_bounce_reply_scanner",
                name="Cold Outreach Bounce & Reply Scanner",
                replace_existing=True
            )
            print("âœ… Cold outreach bounce & reply scanner scheduled (every 5 minutes)")

            # Run backfill immediately at startup so existing replied leads appear right away
            try:
                try:
                    from .routers.cold_outreach_router import sync_outreach_replies_to_leads as _sync_now
                except ImportError:
                    from routers.cold_outreach_router import sync_outreach_replies_to_leads as _sync_now
                result = _sync_now()
                print(f"âœ… Startup reply backfill: {result.get('promoted', 0)} promoted, {result.get('skipped', 0)} already present")
            except Exception as _e:
                print(f"âš ï¸ Startup reply backfill failed: {_e}")
    except Exception as e:
        print(f"âš ï¸ Could not schedule outreach bounce & reply scanner: {e}")
    
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
            print("âœ… Email classification job scheduled (every 2 min, batch=50, ~1500/hour)")
        elif not email_classify_enabled:
            print("â„¹ï¸ Email classification disabled (set EMAIL_CLASSIFICATION_ENABLED=true to enable)")
    except Exception as e:
        print(f"âš ï¸ Could not schedule email classification job: {e}")

    # ----------------------------
    # Mail Segregation Job (every 10 minutes)
    # ----------------------------
    try:
        if scheduler.running:
            def background_mail_segregation_wrapper():
                """Run rule-based mail segregation (sync, no AI)"""
                from backend.agents.mail_segregation_agent import get_mail_segregation_agent, SegmentationStrategy
                try:
                    agent = get_mail_segregation_agent()
                    result = agent.segregate_all_emails(
                        strategy=SegmentationStrategy.CATEGORY,
                        batch_size=50,
                        force_rescan=False
                    )
                    if result.get("processed", 0) > 0:
                        print(f"[MailSegregation] Processed {result.get('processed')} emails")
                except Exception as e:
                    print(f"[MailSegregation] Error: {e}")

            scheduler.add_job(
                background_mail_segregation_wrapper,
                IntervalTrigger(seconds=600),
                id="mail_segregation",
                name="Mail Segregation (Auto)",
                replace_existing=True
            )
            print("âœ… Mail segregation job scheduled (every 10 minutes)")
    except Exception as e:
        print(f"âš ï¸ Could not schedule mail segregation job: {e}")

    # ----------------------------
    # Weekly Panel Mail Integration (SFW -> Campaign)
    # ----------------------------
    try:
        weekly_enabled = os.getenv("PANEL_WEEKLY_MAIL_ENABLED", "false").lower() == "true"
        if scheduler.running and weekly_enabled:
            weekly_day = (os.getenv("PANEL_WEEKLY_DAY", "mon") or "mon").strip().lower()
            weekly_hour = int(os.getenv("PANEL_WEEKLY_HOUR_UTC", "9"))
            weekly_minute = int(os.getenv("PANEL_WEEKLY_MINUTE_UTC", "0"))

            scheduler.add_job(
                weekly_panel_mail_integration_job,
                CronTrigger(day_of_week=weekly_day, hour=weekly_hour, minute=weekly_minute, timezone="UTC"),
                id="panel_weekly_mail_integration",
                name="Panel Weekly Mail Integration",
                replace_existing=True,
            )
            print(f"âœ… Weekly panel mail integration scheduled ({weekly_day} {weekly_hour:02d}:{weekly_minute:02d} UTC)")
        elif not weekly_enabled:
            print("â„¹ï¸ Weekly panel mail integration disabled (set PANEL_WEEKLY_MAIL_ENABLED=true to enable)")
    except Exception as e:
        print(f"âš ï¸ Could not schedule weekly panel mail integration: {e}")

    # Pre-warm mail pool stats cache after a 90s delay (lets server stabilize before heavy MongoDB I/O)
    try:
        import threading
        from routers.gmail import _compute_and_persist_mail_pool_stats
        def _delayed_prewarm():
            import time as _t
            _t.sleep(90)
            _compute_and_persist_mail_pool_stats()
        threading.Thread(target=_delayed_prewarm, daemon=True).start()
        print("ðŸ”„ Mail pool stats pre-warm scheduled (90s delay)")
    except Exception as e:
        print(f"âš ï¸ Could not pre-warm mail pool stats: {e}")

    # ============== STARTUP SUMMARY BANNER ==============
    print("\n" + "=" * 60)
    print(f"ðŸš€ {APP_NAME} v{APP_VERSION} STARTED SUCCESSFULLY")
    print("=" * 60)
    print("ðŸ“‹ REGISTERED ROUTERS:")
    print("   â€¢ /leads         - Lead management & AI classification")
    print("   â€¢ /finance       - Finance module (invoices, vendors)")
    print("   â€¢ /settings      - Application settings")
    print("   â€¢ /gmail         - Gmail API integration")
    print("   â€¢ /cpx           - CPX Research surveys")
    print("   â€¢ /survey-allocation - Survey allocation engine")
    print("   â€¢ /              - Traffic flow (root level)")
    print("   â€¢ /api/v1/email-sync - Email sync (background workers)")
    print("")
    print("ðŸ”„ BACKGROUND JOBS:")
    if scheduler.running:
        print(f"   â€¢ CPX Survey Refresh: Active (every {filter_settings.get('refresh_interval_seconds', 60)}s)")
        print("   â€¢ Cint Survey Refresh: Active (every 5 minutes)")
        print("   â€¢ Gmail Background Sync: Active (every 5 minutes)")
        print("   â€¢ Historic Email Backfill: Active (every 30 seconds, rate-limited)")
        if os.getenv("PANEL_WEEKLY_MAIL_ENABLED", "false").lower() == "true":
            print("   â€¢ Panel Weekly Mail Integration: Active (weekly, UTC cron)")
        if email_classify_enabled:
            print("   â€¢ Email Classification: Active (every 2 min, batch=10)")
        else:
            print("   â€¢ Email Classification: Disabled (EMAIL_CLASSIFICATION_ENABLED=false)")
    else:
        print("   â€¢ CPX Survey Refresh: Inactive")
        print("   â€¢ Cint Survey Refresh: Inactive")
    # Check email sync workers status
    try:
        try:
            from .email_sync.router import get_orchestrator
        except ImportError:
            from email_sync.router import get_orchestrator
        orchestrator = get_orchestrator()
        if orchestrator and orchestrator._started:
            print("   â€¢ Email Sync Workers: Active (runs in background)")
        else:
            print("   â€¢ Email Sync Workers: Inactive")
    except:
        print("   â€¢ Email Sync Workers: Not available")
    print("")
    print("ðŸŒ ENDPOINTS:")
    print("   â€¢ Health: GET /health")
    print("   â€¢ API Docs: GET /docs")
    print("   â€¢ OpenAPI: GET /openapi.json")
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
        print("âœ… Background job scheduler shutdown complete")
    except Exception as e:
        print(f"âš ï¸ Could not shutdown background job scheduler: {e}")
    
    # Shutdown Clay features
    try:
        try:
            from .leads.clay_init import shutdown_clay_features
        except ImportError:
            from leads.clay_init import shutdown_clay_features
        
        await shutdown_clay_features()
    except Exception as e:
        print(f"âš ï¸ Clay shutdown error: {e}")
    
    if scheduler.running:
        scheduler.shutdown()
        print("âœ… Scheduler shutdown complete")
    
    # Stop Email Sync workers
    try:
        try:
            from .email_sync.router import get_orchestrator
        except ImportError:
            from email_sync.router import get_orchestrator
        
        orchestrator = get_orchestrator()
        if orchestrator and orchestrator._started:
            orchestrator.stop()
            print("âœ… Email Sync workers shutdown complete")
    except Exception as e:
        print(f"âš ï¸ Could not stop Email Sync workers: {e}")




# ----------------------------
# Users - Default Admin Configuration
# ----------------------------
users_collection = db["users"]

# Create index for faster login queries
users_collection.create_index("username", unique=True, background=True)

# Get default admin credentials from environment variables
# This allows customization without hardcoding credentials in source code
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "password123")

# Insert one default user if not exists (with hashed password)
# Only creates the default admin if no admin user exists in the database
if not users_collection.find_one({"username": DEFAULT_ADMIN_USERNAME}):
    users_collection.insert_one({
        "username": DEFAULT_ADMIN_USERNAME,
        "password": hash_password(DEFAULT_ADMIN_PASSWORD),  # âœ… Securely hashed
        "createdAt": datetime.utcnow()
    })
    print(f"âœ… Default admin user '{DEFAULT_ADMIN_USERNAME}' created with hashed password")
    
    # Use ERROR level for security-critical warnings to ensure visibility
    logger.error(
        "SECURITY CRITICAL: Default admin credentials are being used! "
        "This is a security risk in production environments. "
        "Action required: "
        "1. Change password immediately via Profile > Change Password, or "
        "2. Configure DEFAULT_ADMIN_USERNAME and DEFAULT_ADMIN_PASSWORD in .env file"
    )


# Auth routes (login, logout, profile) are in routers/auth_handler.py




# ----------------------------
# Routes extracted to dedicated routers (Phase 8)
# ----------------------------
# Admin user management  → routers/admin_handler.py
# Lists / templates / email tracking / reports → routers/legacy_campaign.py
# Leads CRUD → routers/legacy_leads.py
# Contacts CRUD → routers/legacy_contacts.py
# Vendors / Projects → routers/legacy_vendors_projects.py
