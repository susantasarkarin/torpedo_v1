import os
import traceback
import re
from fastapi import FastAPI, HTTPException, Body, Path, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
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
try:
    # Prefer relative import when running as a package (python -m uvicorn backend.main)
    from .routers import traffic as traffic_router
    from .app.routers import cpx as cpx_router
    from .routers import finance as finance_router
    from .routers import settings as settings_router
    from .routers import gmail as gmail_router
    from .app.services.cpx_service import CPXService
    from .app.routers import survey_allocation as survey_allocation_router
    from .leads import router as leads_router
except Exception:
    # Fallback to absolute import for other runtimes
    from routers import traffic as traffic_router
    from app.routers import cpx as cpx_router
    from routers import finance as finance_router
    from routers import settings as settings_router
    from routers import gmail as gmail_router
    from app.services.cpx_service import CPXService
    from app.routers import survey_allocation as survey_allocation_router
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
API_BASE = os.getenv("API_BASE", "http://34.14.202.129:8000") 

# MONGO_URI can be set via .env or configured via Settings UI (profile > settings)
# Default to localhost if not provided
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

# CORS Origins - comma-separated list
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS", 
    "http://localhost:5173,http://localhost:3000,http://localhost:9945,http://34.14.202.129,https://www.surveyieldwork.com,https://surveyieldwork.com"
).split(",")

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
        "max_loi": 20,
        "min_cpi": 1.0,
        "deletion_period_days": 7,
        "auto_refresh_enabled": True,
        "refresh_interval_seconds": 60,
    }
    
    if app_settings_collection is not None:
        try:
            stored = app_settings_collection.find_one({"_id": "survey_filters"})
            if stored:
                return {
                    "max_loi": stored.get("max_loi", defaults["max_loi"]),
                    "min_cpi": stored.get("min_cpi", defaults["min_cpi"]),
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
sessions = {}  # store active sessions (use Redis for production)

def verify_session(request: Request):
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing session token")
    
    # Strip any whitespace (headers can sometimes have trailing spaces)
    session_id = session_id.strip()

    try:
        # Deserialize and validate token (already checks expiration via max_age)
        # If this succeeds, the token is valid and not expired
        username = serializer.loads(session_id, max_age=SESSION_TTL_SECONDS)
        
        # Optional: Check if session exists in memory for additional tracking
        # If server restarted, session won't be in memory, but token is still valid
        session_data = sessions.get(session_id)
        
        if session_data:
            # Session exists in memory, check explicit expiration
            if datetime.utcnow() > session_data["expires_at"]:
                del sessions[session_id]
                print(f"Session expired for user: {username}")
                raise HTTPException(status_code=401, detail="Session expired or invalid")
        else:
            # Session not in memory (e.g., after server restart)
            # But token is valid (deserialized successfully), so allow access
            # Recreate session in memory for tracking (optional)
            sessions[session_id] = {
                "username": username,
                "expires_at": datetime.utcnow() + timedelta(seconds=SESSION_TTL_SECONDS)
            }
            print(f"Session recreated for user: {username} (server restart scenario)")

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
    )
    cpx_router.set_cpx_service(cpx_service)
    traffic_router.set_cpx_service(cpx_service)  # Inject CPX service into traffic router for survey allocation
    app.include_router(cpx_router.router)
    print("✅ CPX Research router initialized")
    print("✅ CPX service injected into traffic router")
else:
    print("⚠️ CPX Research router not initialized due to database connection issue")

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

# Gmail router for Gmail API integration
try:
    app.include_router(gmail_router.router)
    print("✅ Gmail router included")
except Exception as e:
    print(f"⚠️ Gmail router not included: {e}")

# Survey Allocation & Quality Control Engine router
try:
    app.include_router(survey_allocation_router.router)
    print("✅ Survey Allocation router included")
except Exception as e:
    print(f"⚠️ Survey Allocation router not included: {e}")

# Leads AI Classification router
try:
    app.include_router(leads_router.router)
    print("✅ Leads AI Classification router included")
except Exception as e:
    print(f"⚠️ Leads router not included: {e}")

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

@app.on_event("startup")
async def startup_event():
    """Initialize scheduler and start background jobs"""
    global cpx_refresh_job
    
    # Resume incomplete web search jobs
    try:
        from leads.router import get_incomplete_jobs, run_web_search_job, update_job, JobStatus
        import asyncio
        
        incomplete_jobs = get_incomplete_jobs()
        if incomplete_jobs:
            print(f"🔄 Found {len(incomplete_jobs)} incomplete web search jobs to resume...")
            for job in incomplete_jobs:
                job_id = job["job_id"]
                print(f"   Resuming job {job_id} (status: {job['status']}, imported: {job['total_imported']}/{job['target_count']})")
                # Schedule the job to run
                asyncio.create_task(run_web_search_job(job_id))
            print(f"✅ Resumed {len(incomplete_jobs)} web search jobs")
    except Exception as e:
        print(f"⚠️ Could not resume web search jobs: {e}")
    
    if cpx_service is not None:
        try:
            # Perform immediate initial fetch
            print("🚀 Performing initial CPX survey fetch...")
            refresh_cpx_inventory()
            
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
            else:
                print("⚠️ CPX auto-refresh is disabled in settings")
        except Exception as e:
            print(f"❌ Failed to schedule CPX refresh job: {str(e)}")
            traceback.print_exc()
    
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
    print("")
    print("🔄 BACKGROUND JOBS:")
    if scheduler.running:
        print(f"   • CPX Survey Refresh: Active (every {filter_settings.get('refresh_interval_seconds', 60)}s)")
    else:
        print("   • CPX Survey Refresh: Inactive")
    print("")
    print("🌐 ENDPOINTS:")
    print("   • Health: GET /health")
    print("   • API Docs: GET /docs")
    print("   • OpenAPI: GET /openapi.json")
    print("=" * 60 + "\n")

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown scheduler"""
    if scheduler.running:
        scheduler.shutdown()
        print("✅ Scheduler shutdown complete")




# ----------------------------
# Users (Hardcoded for now)
# ----------------------------
users_collection = db["users"]

# Insert one default user if not exists
if not users_collection.find_one({"username": "admin"}):
    users_collection.insert_one({
        "username": "admin",
        "password": "password123",  # ⚠️ For demo only, store hashed later
        "createdAt": datetime.utcnow()
    })


@app.post("/login/")
async def login(credentials: Dict[str, str] = Body(...)):
    try:
        username = credentials.get("username")
        password = credentials.get("password")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")

        user = users_collection.find_one({"username": username, "password": password})
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        # ✅ If user has no role field, assume admin
        role = user.get("role", "admin")

        # ✅ Create session token
        session_id = serializer.dumps(username)
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login error: {str(e)}")




@app.post("/logout/")
async def logout(request: Request):
    session_id = request.headers.get("Authorization")
    if session_id in sessions:
        del sessions[session_id]
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
        allowed_fields = ["email"]
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
        
        if len(new_password) < 6:
            raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
        
        # Verify current password
        user = users_collection.find_one({"username": username, "password": current_password})
        if not user:
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        
        # Update password
        result = users_collection.update_one(
            {"username": username},
            {"$set": {"password": new_password, "updatedAt": datetime.utcnow()}}
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
async def get_lists():
    try:
        lists = list(lists_collection.find())
        for list_item in lists:
            list_item["_id"] = str(list_item["_id"])
        return {"lists": lists}
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
async def get_contacts(list_identifier: str = Path(...)):
    try:
        or_clauses = [
            {"listId": list_identifier},
            {"listName": list_identifier},
            {"listName": {"$regex": f"^{re.escape(list_identifier)}$", "$options": "i"}}
        ]
        contacts = list(contacts_collection.find({"$or": or_clauses}, {"_id": 0}))
        return {"contacts": contacts}
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
async def get_templates():
    try:
        templates = list(templates_collection.find())
        for t in templates:
            t["_id"] = str(t["_id"])
        return {"templates": templates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Template fetch error: {str(e)}")

# ----------------------------
# Send Emails
# ----------------------------
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

# Get all leads
@app.get("/leads/", dependencies=[Depends(verify_session)])
async def get_leads():
    try:
        leads = list(leads_collection.find())
        for lead in leads:
            lead["_id"] = str(lead["_id"])
            # Convert datetime to string for JSON serialization
            for date_field in ["createdAt", "updatedAt", "addedOn"]:
                if date_field in lead:
                    lead[date_field] = lead[date_field].isoformat() if isinstance(lead[date_field], datetime) else str(lead[date_field])
        return {"leads": leads}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch leads error: {str(e)}")

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


# Import leads from CSV
@app.post("/leads/import/csv")
async def import_leads_csv(file: UploadFile = File(...)):
    """
    Import leads from a CSV file.
    Expected columns: name, firstName, lastName, email, title, linkedin, location,
    companyName, companyDomain, companyWebsite, companyIndustry, companyType, etc.
    """
    import csv
    import io
    
    try:
        content = await file.read()
        decoded = content.decode("utf-8-sig")  # Handle BOM
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported = 0
        skipped = 0
        errors = []
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
            try:
                # Skip empty rows
                if not any(row.values()):
                    skipped += 1
                    continue
                
                # Email is required
                email = row.get("email", "").strip()
                if not email:
                    skipped += 1
                    errors.append(f"Row {row_num}: Missing email")
                    continue
                
                # Build lead data from CSV row
                lead_data = {
                    "name": row.get("name", "").strip() or f"{row.get('firstName', '')} {row.get('lastName', '')}".strip(),
                    "firstName": row.get("firstName", "").strip(),
                    "lastName": row.get("lastName", "").strip(),
                    "email": email,
                    "emailStatus": row.get("emailStatus", "Valid").strip() or "Valid",
                    "title": row.get("title", "").strip(),
                    "linkedin": row.get("linkedin", "").strip(),
                    "location": row.get("location", "").strip(),
                    "companyName": row.get("companyName", "").strip(),
                    "companyDomain": row.get("companyDomain", "").strip(),
                    "companyWebsite": row.get("companyWebsite", "").strip(),
                    "companyEmployeeCount": row.get("companyEmployeeCount", "").strip(),
                    "companyEmployeeCountRange": row.get("companyEmployeeCountRange", "").strip(),
                    "companyFounded": row.get("companyFounded", "").strip(),
                    "companyIndustry": row.get("companyIndustry", "").strip(),
                    "companyType": row.get("companyType", "").strip(),
                    "companyHeadquarters": row.get("companyHeadquarters", "").strip(),
                    "companyRevenueRange": row.get("companyRevenueRange", "").strip(),
                    "companyLinkedinUrl": row.get("companyLinkedinUrl", "").strip(),
                    "companyCrunchbaseUrl": row.get("companyCrunchbaseUrl", "").strip(),
                    "companyFundingRounds": row.get("companyFundingRounds", "").strip(),
                    "companyLastFundingRoundAmount": row.get("companyLastFundingRoundAmount", "").strip(),
                    "companyLogoPrimary": row.get("companyLogoPrimary", "").strip(),
                    "companyLogoSecondary": row.get("companyLogoSecondary", "").strip(),
                    "addedOn": datetime.utcnow(),
                    "createdAt": datetime.utcnow(),
                    "updatedAt": datetime.utcnow(),
                    "source": "csv_import",
                }
                
                # Check for duplicate email
                existing = leads_collection.find_one({"email": email})
                if existing:
                    # Update existing lead
                    lead_data.pop("addedOn", None)
                    lead_data.pop("createdAt", None)
                    leads_collection.update_one(
                        {"_id": existing["_id"]},
                        {"$set": lead_data}
                    )
                else:
                    # Insert new lead
                    leads_collection.insert_one(lead_data)
                
                imported += 1
                
            except Exception as e:
                skipped += 1
                errors.append(f"Row {row_num}: {str(e)}")
        
        return {
            "message": f"Import completed: {imported} leads imported, {skipped} skipped",
            "imported": imported,
            "skipped": skipped,
            "errors": errors[:20],  # Limit error list
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
        result = contacts_collection.insert_one(contact_data)
        contact_data["_id"] = str(result.inserted_id)
        
        # Auto-sync to Customers (finance_db): create/update customer with company info
        if contact_data.get("companyName"):
            # Check if customer already exists for this company
            existing_customer = finance_customers_collection.find_one({"company_name": contact_data["companyName"]})
            
            if existing_customer:
                # Update existing customer with latest company info
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
                finance_customers_collection.insert_one(customer_data)
        
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
        for contact in contacts:
            contact["_id"] = str(contact["_id"])
            # Convert datetime to string for JSON serialization
            for date_field in ["createdAt", "updatedAt", "movedFromLeadAt", "addedOn"]:
                if date_field in contact:
                    contact[date_field] = contact[date_field].isoformat() if isinstance(contact[date_field], datetime) else str(contact[date_field])
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
                # Update existing customer
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
        result = vendors_collection.update_one({"_id": ObjectId(vendor_id)}, {"$set": vendor_data})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return {"message": "Vendor updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vendor update error: {str(e)}")

@app.delete("/vendors/{vendor_id}")
async def delete_vendor(vendor_id: str):
    try:
        result = vendors_collection.delete_one({"_id": ObjectId(vendor_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return {"message": "Vendor deleted successfully"}
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
    try:
        result = projects_collection.delete_one({"_id": ObjectId(project_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"message": "Project deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project delete error: {str(e)}")
