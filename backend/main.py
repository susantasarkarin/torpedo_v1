import os
import traceback
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pymongo import MongoClient
from mailersend import MailerSendClient, EmailBuilder
from typing import List, Dict, Any

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
# Upload Contacts (Database Only)
# ----------------------------
@app.post("/upload-csv/")
async def upload_csv(data: Dict[str, List[Dict[str, Any]]] = Body(...)):
    contacts = data.get("contacts", [])
    inserted_contacts = []

    for contact in contacts:
        email = contact.get("email", "").strip()
        if not email:
            continue  # Skip rows without email

        try:
            result = contacts_collection.insert_one(contact)
            contact["_id"] = str(result.inserted_id)
            inserted_contacts.append(contact)
        except Exception as e:
            print(f"MongoDB insert failed for {email}: {e}")
            continue

    return {"message": f"Successfully uploaded {len(inserted_contacts)} contacts to database!", "contacts": inserted_contacts}

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
