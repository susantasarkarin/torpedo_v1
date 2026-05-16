"""
Legacy Campaign Routes
======================
Lists, contacts (by list), templates, email sending, open/click tracking, and reports.
These are the original routes pre-dating the /api/ prefix convention.
Extracted from main.py to keep the app entry-point lean.
"""

import logging
import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse, Response

try:
    from .session_state import verify_session
except ImportError:
    from session_state import verify_session

try:
    from .database import get_client, get_database
except ImportError:
    from database import get_client, get_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-campaign"])

API_BASE = os.getenv("API_BASE", "http://139.59.32.72:8000")

# SMTP config
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Cogentix Research")

# ---------------------------------------------------------------------------
# Lazy collection accessors
# ---------------------------------------------------------------------------
_db = None


def _get_db():
    global _db
    if _db is None:
        _db = get_database("email_automation")
    return _db


def _lists():
    return _get_db()["lists"]


def _contacts():
    return _get_db()["contacts"]


def _templates():
    return _get_db()["templates"]


def _reports():
    return _get_db()["reports"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rewrite_links_with_tracking(html_body: str, campaign_id: str, email: str) -> str:
    return re.sub(
        r'href="(http[s]?://[^"]+)"',
        lambda m: f'href="{API_BASE}/track/click?c={campaign_id}&e={email}&url={m.group(1)}"',
        html_body,
    )


def inject_open_tracking(html_body: str, campaign_id: str, email: str) -> str:
    pixel = f'<img src="{API_BASE}/track/open?c={campaign_id}&e={email}" width="1" height="1" style="display:none;" />'
    return html_body + pixel


def _send_email_html(to_email: str, subject: str, html_content: str) -> bool:
    if not SMTP_USER or not SMTP_PASSWORD:
        raise Exception("SMTP credentials not configured. Set SMTP_USER and SMTP_PASSWORD environment variables.")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html"))
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [to_email], msg.as_string())
    return True


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

@router.post("/create-list/")
async def create_list(list_data: Dict[str, Any] = Body(...)):
    try:
        result = _lists().insert_one(list_data)
        list_data["_id"] = str(result.inserted_id)
        return {"message": "List created successfully", "list": list_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"List creation error: {str(e)}")


@router.get("/lists/", dependencies=[Depends(verify_session)])
async def get_lists(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
):
    try:
        col = _lists()
        total = col.count_documents({})
        lists = list(col.find().skip(skip).limit(limit))
        for item in lists:
            item["_id"] = str(item["_id"])
        return {"lists": lists, "total": total, "skip": skip, "limit": limit, "has_more": (skip + len(lists)) < total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch lists error: {str(e)}")


@router.delete("/delete-list/{list_id}")
async def delete_list(list_id: str):
    try:
        result = _lists().delete_one({"_id": ObjectId(list_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="List not found")
        _contacts().delete_many({"listId": list_id})
        return {"message": "List deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


# ---------------------------------------------------------------------------
# Upload contacts
# ---------------------------------------------------------------------------

@router.post("/upload-csv/")
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
                found = _lists().find_one({"name": incoming_list_id})
                resolved_list_id = str(found["_id"]) if found else incoming_list_id
            elif list_name:
                found = _lists().find_one({"name": list_name})
                resolved_list_id = str(found["_id"]) if found else None
        except Exception as e:
            logger.warning("upload-csv: error resolving list id/name: %s", e)

        query: Dict[str, Any] = {"email": email}
        if resolved_list_id:
            query["listId"] = resolved_list_id
        elif list_name:
            query["listName"] = list_name

        if _contacts().find_one(query):
            continue

        if list_name:
            contact["listName"] = list_name
        if resolved_list_id:
            contact["listId"] = resolved_list_id

        try:
            result = _contacts().insert_one(contact)
            contact["_id"] = str(result.inserted_id)
            inserted_contacts.append(contact)
        except Exception as e:
            logger.error("MongoDB insert failed for %s: %s", email, e)
            continue

    return {"message": f"Uploaded {len(inserted_contacts)} contacts!", "contacts": inserted_contacts}


# ---------------------------------------------------------------------------
# Contacts by list
# ---------------------------------------------------------------------------

@router.get("/contacts/{list_identifier}")
async def get_contacts_by_list(
    list_identifier: str = Path(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
):
    try:
        query = {
            "$or": [
                {"listId": list_identifier},
                {"listName": list_identifier},
                {"listName": {"$regex": f"^{re.escape(list_identifier)}$", "$options": "i"}},
            ]
        }
        col = _contacts()
        total = col.count_documents(query)
        contacts = list(col.find(query, {"_id": 0}).skip(skip).limit(limit))
        return {"contacts": contacts, "total": total, "skip": skip, "limit": limit, "has_more": (skip + len(contacts)) < total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch contacts error: {str(e)}")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@router.post("/templates/")
async def save_template(template: Dict[str, Any] = Body(...)):
    try:
        data = {k: v for k, v in template.items() if k != "_id"}
        result = _templates().insert_one(data)
        saved = _templates().find_one({"_id": result.inserted_id})
        saved["_id"] = str(saved["_id"])
        return {"message": "Template saved successfully", "template": saved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Template save error: {str(e)}")


@router.get("/templates/", dependencies=[Depends(verify_session)])
async def get_templates(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
):
    try:
        col = _templates()
        total = col.count_documents({})
        templates = list(col.find().skip(skip).limit(limit))
        for t in templates:
            t["_id"] = str(t["_id"])
        return {"templates": templates, "total": total, "skip": skip, "limit": limit, "has_more": (skip + len(templates)) < total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Template fetch error: {str(e)}")


@router.get("/templates", dependencies=[Depends(verify_session)])
async def get_templates_no_slash(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
):
    return await get_templates(skip=skip, limit=limit)


@router.post("/templates")
async def save_template_no_slash(template: Dict[str, Any] = Body(...)):
    return await save_template(template=template)


@router.put("/templates/{template_id}")
async def update_template(template_id: str, template_data: Dict[str, Any] = Body(...)):
    try:
        template_data = {k: v for k, v in template_data.items() if k != "_id"}
        matched = 0
        if ObjectId.is_valid(template_id):
            result = _templates().update_one({"_id": ObjectId(template_id)}, {"$set": template_data})
            matched = result.matched_count
        if matched == 0:
            result = _templates().update_one({"_id": template_id}, {"$set": template_data})
            matched = result.matched_count
        if matched == 0:
            raise HTTPException(status_code=404, detail="Template not found")
        return {"message": "Template updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Template update error: {str(e)}")


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str = Path(...)):
    try:
        if ObjectId.is_valid(template_id):
            result = _templates().delete_one({"_id": ObjectId(template_id)})
            if result.deleted_count == 0:
                result = _templates().delete_one({"_id": template_id})
        else:
            result = _templates().delete_one({"_id": template_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Template not found")
        return {"message": "Template deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Template delete error: {str(e)}")


# ---------------------------------------------------------------------------
# Send emails
# ---------------------------------------------------------------------------

@router.post("/send-emails/")
async def send_emails(data: Dict[str, Any] = Body(...)):
    contacts = data.get("contacts", [])
    template = data.get("template")
    if not contacts or not template:
        raise HTTPException(status_code=400, detail="Missing contacts or template")

    subject = template.get("subject", "No Subject")
    html_content = template.get("htmlContent", "")
    campaign_id = str(ObjectId())

    _reports().insert_one({
        "campaignId": campaign_id,
        "subject": subject,
        "sent": [],
        "opens": [],
        "clicks": [],
        "createdAt": datetime.utcnow(),
    })

    sent_emails: List[str] = []
    failed_emails: List[Dict[str, str]] = []

    for contact in contacts:
        email = (contact.get("email") or "").strip()
        if not email:
            continue
        try:
            personalized_html = re.sub(r"{{\s*contact.name\s*}}", contact.get("name") or "there", html_content)
            personalized_html = re.sub(r"{{\s*sender.companyName\s*}}", "Cogentix Research", personalized_html)
            personalized_html = rewrite_links_with_tracking(personalized_html, campaign_id, email)
            personalized_html = inject_open_tracking(personalized_html, campaign_id, email)
            _send_email_html(email, subject, personalized_html)
            sent_emails.append(email)
            _reports().update_one(
                {"campaignId": campaign_id},
                {"$push": {"sent": {"email": email, "time": datetime.utcnow()}}},
            )
        except Exception as e:
            failed_emails.append({"email": email, "error": str(e)})

    return {"message": f"Sent {len(sent_emails)} emails!", "sent": sent_emails, "failed": failed_emails}


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------

@router.get("/track/open")
async def track_open(c: str, e: str):
    _reports().update_one(
        {"campaignId": c},
        {"$push": {"opens": {"email": e, "time": datetime.utcnow()}}},
        upsert=True,
    )
    transparent_pixel = (
        b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80"
        b"\xff\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04"
        b"\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01"
        b"\x00\x01\x00\x00\x02\x02\x4c\x01\x00\x3b"
    )
    return Response(content=transparent_pixel, media_type="image/gif")


@router.get("/track/click")
async def track_click(c: str, e: str, url: str):
    _reports().update_one(
        {"campaignId": c},
        {"$push": {"clicks": {"email": e, "url": url, "time": datetime.utcnow()}}},
        upsert=True,
    )
    return RedirectResponse(url)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@router.get("/reports/", dependencies=[Depends(verify_session)])
async def get_reports():
    try:
        campaigns = list(_reports().find({}, {"_id": 0}))
        return {"campaigns": campaigns}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reports fetch error: {str(e)}")
