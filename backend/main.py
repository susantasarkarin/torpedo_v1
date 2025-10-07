import os
import traceback
import re
from fastapi import FastAPI, HTTPException, Body, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, RedirectResponse
from dotenv import load_dotenv
from pymongo import MongoClient
from mailersend import MailerSendClient, EmailBuilder
from typing import List, Dict, Any
from bson import ObjectId
from datetime import datetime
from fastapi import Path
# ----------------------------
# Load environment variables
# ----------------------------
load_dotenv()

API_KEY = os.getenv("MAILERSEND_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
MONGO_URI = os.getenv("MONGO_URI")

if not API_KEY or not SENDER_EMAIL or not MONGO_URI:
    raise RuntimeError(
        "❌ Missing MAILERSEND_API_KEY, SENDER_EMAIL, or MONGO_URI in .env"
    )

# ----------------------------
# MongoDB connection
# ----------------------------
client = MongoClient(MONGO_URI)
db = client["email_automation"]
contacts_collection = db["contacts"]
lists_collection = db["lists"]
templates_collection = db["templates"]
reports_collection = db["reports"]

# ----------------------------
# FastAPI app
# ----------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# MailerSend client
# ----------------------------
mailer = MailerSendClient(api_key=API_KEY)

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
        lambda m: f'href=\"http://localhost:8000/track/click?c={campaign_id}&e={email}&url={m.group(1)}\"',
        html_body
    )

# ----------------------------
# Helper: inject open tracking pixel
# ----------------------------
def inject_open_tracking(html_body: str, campaign_id: str, email: str):
    pixel = f'<img src="http://localhost:8000/track/open?c={campaign_id}&e={email}" width="1" height="1" style="display:none;" />'
    return html_body + pixel

# ----------------------------
# List Endpoints
# ----------------------------
@app.post("/create-list/")
async def create_list(list_data: Dict[str, Any] = Body(...)):
    try:
        result = lists_collection.insert_one(list_data)
        list_data["_id"] = str(result.inserted_id)
        return {"message": "List created successfully", "list": list_data}
    except Exception as e:
        print(f"❌ List creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"List creation error: {str(e)}")

@app.get("/lists/")
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


@app.get("/templates/")
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
@app.get("/reports/")
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

        return {"message": "Login successful", "username": username}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login error: {str(e)}")

