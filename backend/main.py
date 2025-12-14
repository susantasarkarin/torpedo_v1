import os
import traceback
import re
from fastapi import FastAPI, HTTPException, Body, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, RedirectResponse
from dotenv import load_dotenv
from pymongo import MongoClient
from mailersend import MailerSendClient, EmailBuilder
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
    from .app.services.cpx_service import CPXService
except Exception:
    # Fallback to absolute import for other runtimes
    from routers import traffic as traffic_router
    from app.routers import cpx as cpx_router
    from routers import finance as finance_router
    from routers import settings as settings_router
    from app.services.cpx_service import CPXService

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

API_KEY = os.getenv("MAILERSEND_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
MONGO_URI = os.getenv("MONGO_URI")

# CPX Research Configuration
CPX_APP_ID = os.getenv("CPX_APP_ID")
CPX_EXT_USER_ID = os.getenv("CPX_EXT_USER_ID")
CPX_SECURE_HASH_KEY = os.getenv("CPX_SECURE_HASH_KEY")
CPX_API_TIMEOUT = int(os.getenv("CPX_API_TIMEOUT", "30"))
CPX_FETCH_LIMIT = int(os.getenv("CPX_FETCH_LIMIT", "1000"))

# CORS Origins - comma-separated list
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS", 
    "http://localhost:5173,http://localhost:3000,http://localhost:9945,http://34.14.202.129"
).split(",")

if not API_KEY or not SENDER_EMAIL or not MONGO_URI:
    raise RuntimeError(
        "❌ Missing MAILERSEND_API_KEY, SENDER_EMAIL, or MONGO_URI in .env"
    )

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
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

app.include_router(traffic_router.router)

# Finance router for CRUD endpoints used by the frontend
try:
    app.include_router(finance_router.router)
    print("✅ Finance router included")
except Exception as e:
    print(f"⚠️ Finance router not included: {e}")

# CPX Research router
if cpx_surveys_collection is not None and cpx_filters_collection is not None:
    # Initialize CPX service with database collections
    cpx_service = CPXService(
        app_id=CPX_APP_ID,
        ext_user_id=CPX_EXT_USER_ID,
        secure_hash_key=CPX_SECURE_HASH_KEY,
        api_timeout=CPX_API_TIMEOUT,
        fetch_limit=CPX_FETCH_LIMIT,
        surveys_collection=cpx_surveys_collection,
        filters_collection=cpx_filters_collection,
    )
    cpx_router.set_cpx_service(cpx_service)
    app.include_router(cpx_router.router)
    print("✅ CPX Research router initialized")
else:
    print("⚠️ CPX Research router not initialized due to database connection issue")

# Settings router
try:
    app.include_router(settings_router.router)
    print("✅ Settings router included")
except Exception as e:
    print(f"⚠️ Settings router not included: {e}")

# ----------------------------
# MailerSend client
# ----------------------------
mailer = MailerSendClient(api_key=API_KEY)

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
        
        # Cleanup surveys older than 7 days
        cpx_service.cleanup_old_surveys(days=7)
        
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
    
    if cpx_service is not None:
        try:
            # Perform immediate initial fetch
            print("🚀 Performing initial CPX survey fetch...")
            refresh_cpx_inventory()
            
            # Start scheduler for periodic refreshes
            scheduler.start()
            cpx_refresh_job = scheduler.add_job(
                refresh_cpx_inventory,
                IntervalTrigger(seconds=60),
                id="cpx_refresh",
                name="CPX Survey Inventory Refresh",
                replace_existing=True
            )
            print("✅ CPX refresh job scheduled (every 60 seconds)")
        except Exception as e:
            print(f"❌ Failed to schedule CPX refresh job: {str(e)}")
            traceback.print_exc()

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
# Helper: send HTML emails
# ----------------------------
def send_email_html(to_email: str, subject: str, html_content: str, text_content: str = None):
    try:
        email_builder = (
            EmailBuilder()
            .from_email(SENDER_EMAIL)
            .subject(subject)
            .text(text_content or "This is an HTML email. Please enable HTML view.")
            .html(html_content)
            .to(to_email)
        )
        email = email_builder.build()
        response = mailer.emails.send(email)
        return response
    except Exception as e:
        print(f"❌ MailerSend failed for {to_email}: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"MailerSend error: {str(e)}")

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
# Clients Collection
# ----------------------------
clients_collection = db["clients"]

def generate_client_no():
    """Generate a unique 7-digit client number"""
    while True:
        client_no = str(datetime.utcnow().microsecond % 10000000).zfill(7)
        if not clients_collection.find_one({"clientNo": client_no}):
            return client_no

# Create a client
@app.post("/clients/")
async def create_client(client_data: Dict[str, Any] = Body(...)):
    try:
        # Validate required fields
        if not client_data.get("name") or not client_data["name"].strip():
            raise HTTPException(status_code=400, detail="Client name is required")
        if not client_data.get("email") or not client_data["email"].strip():
            raise HTTPException(status_code=400, detail="Email address is required")
        if not client_data.get("contactPerson") or not client_data["contactPerson"].strip():
            raise HTTPException(status_code=400, detail="Phone number is required")

        client_data["clientNo"] = generate_client_no()
        result = clients_collection.insert_one(client_data)
        client_data["_id"] = str(result.inserted_id)
        return {"message": "Client created successfully", "client": client_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Client creation error: {str(e)}")

# Get all clients
@app.get("/clients/",dependencies=[Depends(verify_session)])
async def get_clients():
    try:
        clients = list(clients_collection.find())
        for c in clients:
            c["_id"] = str(c["_id"])
        return {"clients": clients}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch clients error: {str(e)}")

# Update a client
@app.put("/clients/{client_id}")
async def update_client(client_id: str, client_data: Dict[str, Any] = Body(...)):
    try:
        # Exclude _id and clientNo from updates (clientNo is system-generated)
        client_data = {k: v for k, v in client_data.items() if k not in ["_id", "clientNo"]}

        # Validate required fields if they are being updated
        if "name" in client_data and (not client_data["name"] or not client_data["name"].strip()):
            raise HTTPException(status_code=400, detail="Client name cannot be empty")
        if "email" in client_data and (not client_data["email"] or not client_data["email"].strip()):
            raise HTTPException(status_code=400, detail="Email address cannot be empty")
        if "contactPerson" in client_data and (not client_data["contactPerson"] or not client_data["contactPerson"].strip()):
            raise HTTPException(status_code=400, detail="Phone number cannot be empty")

        result = clients_collection.update_one(
            {"_id": ObjectId(client_id)}, {"$set": client_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Client not found")
        return {"message": "Client updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Client update error: {str(e)}")

# Delete a client
@app.delete("/clients/{client_id}")
async def delete_client(client_id: str):
    try:
        result = clients_collection.delete_one({"_id": ObjectId(client_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Client not found")
        return {"message": "Client deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Client delete error: {str(e)}")

vendors_collection = db["vendors"]

def generate_vendor_no():
    while True:
        vendor_no = str(datetime.utcnow().microsecond % 10000).zfill(4)
        if not vendors_collection.find_one({"vendorNo": vendor_no}):
            return vendor_no

@app.post("/vendors/")
async def create_vendor(vendor_data: Dict[str, Any] = Body(...)):
    try:
        # Validate required fields
        if not vendor_data.get("vendorName") or not vendor_data["vendorName"].strip():
            raise HTTPException(status_code=400, detail="Vendor name is required")
        if not vendor_data.get("vendorEmail") or not vendor_data["vendorEmail"].strip():
            raise HTTPException(status_code=400, detail="Email address is required")

        vendor_data["vendorNo"] = generate_vendor_no()
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
        vendor_data = {k: v for k, v in vendor_data.items() if k != "_id" and k != "vendorNo"}
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
