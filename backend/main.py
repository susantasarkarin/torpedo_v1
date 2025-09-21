import os
import csv
import traceback
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pymongo import MongoClient
from mailersend import MailerSendClient, EmailBuilder

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

# --------------------------
# CSV Upload Endpoint
# --------------------------
@app.post("/upload-csv/")
async def upload_csv(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")

    contents = await file.read()
    decoded = contents.decode("utf-8").splitlines()
    reader = csv.DictReader(decoded)

    contacts = []

    for row in reader:
        # Strip spaces to prevent invalid emails
        email = (row.get("email") or row.get("Email") or "").strip()
        name = (row.get("name") or row.get("Name") or "").strip()

        if not email:
            continue  # Skip rows without email

        contact = {"email": email, "name": name}

        # Insert into MongoDB
        try:
            result = contacts_collection.insert_one(contact)
            contact["_id"] = str(result.inserted_id)  # Convert ObjectId to string
        except Exception as e:
            print(f"MongoDB insert failed for {email}: {e}")
            continue

        # Send email
        try:
            send_email(
                to_email=email,
                subject="Welcome from CRM",
                body=f"Hello {name or 'there'},\nThis is a test email from our CRM automation!"
            )
        except Exception as e:
            print(f"MailerSend failed for {email}: {e}")

        contacts.append(contact)

    return {"message": "CSV uploaded and emails processed!", "contacts": contacts}
