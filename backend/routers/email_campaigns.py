"""
Email Campaign Router
Handles bulk email sending with template rendering and signature injection
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import os
from pymongo import MongoClient
from bson import ObjectId
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Template

router = APIRouter(prefix="/email-campaigns", tags=["Email Campaigns"])

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["email_automation"]

class BulkEmailRequest(BaseModel):
    lead_ids: List[str] = Field(..., description="List of lead IDs to send emails to")
    template_id: str = Field(..., description="Template ID to use")
    subject: Optional[str] = Field(None, description="Optional custom subject line")

class EmailResponse(BaseModel):
    success: bool
    message: str
    sent_count: int = 0
    failed_count: int = 0

def render_template(template_html: str, contact: dict, sender: dict) -> str:
    """Render Jinja2 template with contact and sender data"""
    try:
        template = Template(template_html)
        return template.render(contact=contact, sender=sender)
    except Exception as e:
        print(f"❌ Template rendering error: {e}")
        return template_html

def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send email via SMTP (or simulate if credentials not configured)"""
    
    # Check if SMTP is configured
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    
    if not all([smtp_host, smtp_user, smtp_password]):
        print(f"📧 SIMULATED EMAIL TO: {to_email}")
        print(f"   SUBJECT: {subject}")
        print(f"   (SMTP not configured - set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env)")
        return True  # Simulate success
    
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Attach HTML body
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        
        # Send via SMTP
        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        print(f"✅ Email sent to {to_email}")
        return True
        
    except Exception as e:
        print(f"❌ Email send failed to {to_email}: {e}")
        return False

@router.post("/send-bulk", response_model=EmailResponse)
async def send_bulk_emails(request: BulkEmailRequest):
    """
    Send emails to multiple leads using a template
    Fetches digital signature from user profile and injects into template
    """
    
    try:
        # Get template
        template = db.templates.find_one({"_id": ObjectId(request.template_id)})
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        # Get user profile (assuming single admin user for now)
        user = db.users.find_one({"email": {"$exists": True}})
        if not user:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        # Extract signature
        signature = user.get("email_signature", "")
        sender_name = user.get("first_name", "") + " " + user.get("last_name", "")
        sender_email = user.get("email", "")
        
        sender_data = {
            "name": sender_name,
            "email": sender_email,
            "signature": signature,
            "company": user.get("company_name", ""),
            "title": user.get("job_title", "")
        }
        
        # Get leads
        lead_object_ids = [ObjectId(lid) for lid in request.lead_ids]
        leads = list(db.leads_enriched.find({"_id": {"$in": lead_object_ids}}))
        
        if not leads:
            raise HTTPException(status_code=404, detail="No leads found")
        
        # Send emails
        sent_count = 0
        failed_count = 0
        
        for lead in leads:
            try:
                # Prepare contact data
                contact_data = {
                    "name": lead.get("name", ""),
                    "email": lead.get("email", ""),
                    "title": lead.get("title", ""),
                    "company": lead.get("company_name", ""),
                    "first_name": lead.get("name", "").split()[0] if lead.get("name") else ""
                }
                
                # Render template
                email_body = render_template(template["body"], contact_data, sender_data)
                
                # Append signature if not already in template
                if signature and signature not in email_body:
                    email_body += f"\n\n{signature}"
                
                # Use custom subject or template subject
                subject = request.subject or template.get("subject", "No Subject")
                
                # Send email
                success = send_email(
                    to_email=lead.get("email", ""),
                    subject=subject,
                    html_body=email_body
                )
                
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
                    
            except Exception as e:
                print(f"❌ Failed to send to {lead.get('email')}: {e}")
                failed_count += 1
        
        # Save campaign record
        campaign_record = {
            "template_id": request.template_id,
            "template_name": template.get("name", ""),
            "lead_ids": request.lead_ids,
            "sent_count": sent_count,
            "failed_count": failed_count,
            "created_at": datetime.utcnow(),
            "status": "completed"
        }
        db.email_campaigns.insert_one(campaign_record)
        
        return EmailResponse(
            success=True,
            message=f"Campaign sent! {sent_count} successful, {failed_count} failed",
            sent_count=sent_count,
            failed_count=failed_count
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Bulk email error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/templates")
async def get_templates():
    """Get all available email templates"""
    try:
        templates = list(db.templates.find())
        for t in templates:
            t["_id"] = str(t["_id"])
        return {"templates": templates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/signature")
async def get_user_signature():
    """Get current user's email signature"""
    try:
        user = db.users.find_one({"email": {"$exists": True}})
        if not user:
            return {"signature": ""}
        
        return {
            "signature": user.get("email_signature", ""),
            "name": f"{user.get('first_name', '')} {user.get('last_name', '')}",
            "email": user.get("email", ""),
            "title": user.get("job_title", ""),
            "company": user.get("company_name", "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
async def get_campaign_history():
    """Get email campaign history"""
    try:
        campaigns = list(db.email_campaigns.find().sort("created_at", -1).limit(50))
        for c in campaigns:
            c["_id"] = str(c["_id"])
            c["created_at"] = c["created_at"].isoformat() if isinstance(c["created_at"], datetime) else str(c["created_at"])
        return {"campaigns": campaigns}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
