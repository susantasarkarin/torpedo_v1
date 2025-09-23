import os
import traceback
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
lists_collection = db["lists"]  # Added lists collection for storing list data

# ----------------------------
# FastAPI app
# ----------------------------
app = FastAPI()

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# MailerSend client
# ----------------------------
mailer = MailerSendClient(api_key=API_KEY)

# ----------------------------
# Helper function to send emails
# ----------------------------
def send_email(to_email: str, subject: str, body: str):
    try:
        email_builder = (
            EmailBuilder()
            .from_email(SENDER_EMAIL)
            .subject(subject)
            .text(body)
            .html(f"<p>{body}</p>")
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
        # delete the list itself
        result = lists_collection.delete_one({"_id": ObjectId(list_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="List not found")
        # delete all contacts belonging to that list
        contacts_collection.delete_many({"listId": list_id})
        return {"message": "List deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

# ----------------------------
# Upload Contacts (Database Only)
# ----------------------------
@app.post("/upload-csv/")
async def upload_csv(data: Dict[str, List[Dict[str, Any]]] = Body(...)):
    contacts = data.get("contacts", [])
    inserted_contacts = []

    for contact in contacts:
        email = contact.get("email", "").strip()
        list_name = contact.get("listName")
        list_id = contact.get("listId")  # optional

        if not email:
            continue  # Skip rows without email

        # if neither listName nor listId provided skip
        if not list_name and not list_id:
            print(f"❌ Skipping contact {email}: listName and listId missing")
            continue

        try:
            # check duplicate by email + listId if available else email + listName
            query = {"email": email}
            if list_id:
                query["listId"] = list_id
            else:
                query["listName"] = list_name

            existing_contact = contacts_collection.find_one(query)

            if existing_contact:
                print(f"⚠️ Contact {email} already exists in list, skipping")
                continue

            # insert, also ensure listName and listId fields stored
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
# Get contacts by listId (ObjectId string) or fallback by plain id string
# ----------------------------
@app.get("/contacts/{list_id}")
async def get_contacts(list_id: str = Path(...)):
    try:
        contacts = list(contacts_collection.find({"listId": list_id}))
        # if none and list_id looks like a name, also try listName
        if len(contacts) == 0:
            contacts = list(contacts_collection.find({"listName": list_id}))
        for c in contacts:
            c["_id"] = str(c["_id"])
        return {"contacts": contacts}
    except Exception as e:
        print(f"❌ Failed to fetch contacts for list {list_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Fetch contacts error: {str(e)}")

# fallback: get by name route (optional)
@app.get("/contacts-by-name/{list_name}")
async def get_contacts_by_name(list_name: str = Path(...)):
    try:
        contacts = list(contacts_collection.find({"listName": list_name}))
        for c in contacts:
            c["_id"] = str(c["_id"])
        return {"contacts": contacts}
    except Exception as e:
        print(f"❌ Failed to fetch contacts for list name {list_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Fetch contacts error: {str(e)}")

# ----------------------------
# Contact count endpoint (used by frontend)
# ----------------------------
@app.get("/contact-count")
async def contact_count(listId: str = Query(None), listName: str = Query(None)):
    try:
        q = {}
        if listId:
            q["listId"] = listId
        elif listName:
            q["listName"] = listName
        else:
            raise HTTPException(status_code=400, detail="Provide listId or listName")

        count = contacts_collection.count_documents(q)
        return {"count": count}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ contact-count failed: {e}")
        raise HTTPException(status_code=500, detail=f"Contact count error: {str(e)}")

# ----------------------------
# Send Emails (Separate Endpoint)
# ----------------------------
@app.post("/send-emails/")
async def send_emails(data: Dict[str, Any] = Body(...)):
    contacts = data.get("contacts", [])
    send_welcome = data.get("sendWelcome", False)
    validate_emails = data.get("validateEmails", False)

    if not contacts:
        raise HTTPException(status_code=400, detail="No contacts provided")

    sent_emails = []
    failed_emails = []

    for contact in contacts:
        email = contact.get("email", "").strip()
        if not email:
            continue

        try:
            subject = "Welcome from CRM" if send_welcome else "Greetings from CRM"
            body = f"Greetings {contact.get('firstName') or contact.get('name') or 'there'},\nHope you are doing well,This is a new message from our CRM system!"

            send_email(
                to_email=email,
                subject=subject,
                body=body
            )
            sent_emails.append(email)
        except Exception as e:
            print(f"MailerSend failed for {email}: {e}")
            failed_emails.append({"email": email, "error": str(e)})

    return {
        "message": f"Emails sent to {len(sent_emails)} contacts!",
        "sent": sent_emails,
        "failed": failed_emails
    }
