import os
import traceback
import re
from fastapi import FastAPI, HTTPException, Body, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pymongo import MongoClient
from mailersend import MailerSendClient, EmailBuilder
from typing import List, Dict, Any
from bson import ObjectId

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
lists_collection = db["lists"]  # lists collection for storing list data
templates_collection = db["templates"]

# ----------------------------
# FastAPI app
# ----------------------------
app = FastAPI()

# Enable CORS for React frontend (add other origins if your dev server runs on a different port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # add ports you use
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# MailerSend client
# ----------------------------
mailer = MailerSendClient(api_key=API_KEY)

# ----------------------------
# Helper function to send HTML emails
# ----------------------------
def send_email_html(to_email: str, subject: str, html_content: str, text_content: str = None):
    try:
        email_builder = (
            EmailBuilder()
            .from_email(SENDER_EMAIL)
            .subject(subject)
            .text(text_content or "This is an HTML email. Please enable HTML view.")
            .html(html_content)  # ✅ full HTML with images and placeholders
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
# Endpoint to create and store lists
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

# ----------------------------
# Endpoint to get all lists
# ----------------------------
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

# ----------------------------
# Endpoint to delete list (and its contacts)
# ----------------------------
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

        if resolved_list_id and list_name:
            query = {"email": email, "$or": [{"listId": resolved_list_id}, {"listName": list_name}]}
        elif resolved_list_id:
            query = {"email": email, "listId": resolved_list_id}
        elif list_name:
            query = {"email": email, "listName": list_name}
        else:
            query = {"email": email}

        if contacts_collection.find_one(query):
            print(f"⚠️ Contact {email} already exists in list, skipping")
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

    return {
        "message": f"Successfully uploaded {len(inserted_contacts)} contacts to database!",
        "contacts": inserted_contacts
    }

# ----------------------------
# Fetch contacts
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

        if len(contacts) == 0 and ObjectId.is_valid(list_identifier):
            try:
                list_doc = lists_collection.find_one({"_id": ObjectId(list_identifier)})
                if list_doc:
                    resolved_id = str(list_doc["_id"])
                    name = list_doc.get("name")
                    contacts = list(
                        contacts_collection.find(
                            {"$or": [{"listId": resolved_id}, {"listName": name}]}, {"_id": 0}
                        )
                    )
            except Exception as e:
                print(f"[API] Error looking up list by ObjectId: {e}")

        return {"contacts": contacts}
    except Exception as e:
        print(f"❌ Failed to fetch contacts: {e}")
        raise HTTPException(status_code=500, detail=f"Fetch contacts error: {str(e)}")

# ----------------------------
# Contact count endpoint
# ----------------------------
@app.get("/contact-count")
async def contact_count(listId: str = Query(None), listName: str = Query(None)):
    try:
        q = {}
        if listId:
            q["$or"] = [{"listId": listId}, {"listName": listId}]
        elif listName:
            q["$or"] = [{"listName": listName}, {"listId": listName}]
        else:
            raise HTTPException(status_code=400, detail="Provide listId or listName")

        count = contacts_collection.count_documents(q)
        return {"count": count}
    except Exception as e:
        print(f"❌ contact-count failed: {e}")
        raise HTTPException(status_code=500, detail=f"Contact count error: {str(e)}")

# ----------------------------
# Template endpoints
# ----------------------------
@app.post("/templates/")
async def save_template(template: Dict[str, Any] = Body(...)):
    try:
        result = templates_collection.insert_one(template)
        template["_id"] = str(result.inserted_id)
        return {"message": "Template saved successfully", "template": template}
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
# Send Emails with Template Personalization
# ----------------------------
@app.post("/send-emails/")
async def send_emails(data: Dict[str, Any] = Body(...)):
    contacts = data.get("contacts", [])
    template = data.get("template")

    if not contacts or not template:
        raise HTTPException(status_code=400, detail="Missing contacts or template")

    sent_emails = []
    failed_emails = []

    for contact in contacts:
        email = (contact.get("email") or "").strip()
        if not email:
            continue

        try:
            subject = template.get("subject", "No Subject")
            html_body = template.get("htmlContent", "")

            # Replace placeholders
            html_body = re.sub(r"{{\s*contact.name\s*}}", contact.get("name") or contact.get("firstName") or "there", html_body)
            html_body = re.sub(r"{{\s*sender.companyName\s*}}", "Cogentix Research", html_body)
            html_body = re.sub(r"{{\s*sender.name\s*}}", "CRM System", html_body)
            html_body = re.sub(r"{{\s*sender.title\s*}}", "Team", html_body)
            html_body = re.sub(r"{{\s*sender.email\s*}}", SENDER_EMAIL, html_body)
            html_body = re.sub(r"{{\s*sender.website\s*}}", "https://example.com", html_body)
            html_body = re.sub(r"{{\s*sender.address\s*}}", "123 Main Street", html_body)

            send_email_html(
                to_email=email,
                subject=subject,
                html_content=html_body
            )
            sent_emails.append(email)
        except Exception as e:
            print(f"❌ MailerSend failed for {email}: {e}")
            failed_emails.append({"email": email, "error": str(e)})

    return {
        "message": f"Emails sent to {len(sent_emails)} contacts!",
        "sent": sent_emails,
        "failed": failed_emails
    }
