"""
Cold Outreach Router
====================

Campaign management API for 3-business cold outreach system.

Baskets:
  A â†’ Survey Fieldwork   (indira@surveyfieldwork.com)
  B â†’ Cogentix Research  (meera@cogentixresearch.com)
  C â†’ BIMwave            (susanta@bimwaveconsultants.com)
  D â†’ Dual Fit           (all 3 businesses, score-ordered, 21-day gap between each)
  E â†’ Nurture            (excluded â€” no outreach)

Collections used:
  outreach_campaigns_v2        â€” campaign definitions + step templates
  outreach_mailboxes           â€” SMTP mailbox records
  outreach_leads_v2            â€” enrolled leads + workflow state
  outreach_sends_v2            â€” per-send records (stats)
  outreach_bounce_suppression  â€” global bounce suppression list
  leads_enriched               â€” source of truth for leads to enroll
"""

import base64 as _b64_module
import logging
import os
import re as _re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote as _url_quote, unquote as _url_unquote

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, EmailStr
from pymongo import MongoClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cold-outreach", tags=["Cold Outreach"])

SEQUENCE_STEPS = [0, 3, 6, 11]   # Day offsets: Day 1, 4, 7, 12 (0-indexed)
DUAL_FIT_GAP_DAYS = 21           # Gap between sequences for Dual Fit leads
SEQUENCE_DURATION_DAYS = 12      # Last step offset â†’ total sequence window

BASKET_BUSINESS = {
    "A": "sfw",
    "B": "cogentix",
    "C": "bimwave",
}

BUSINESS_LABEL = {
    "sfw": "Survey Fieldwork",
    "cogentix": "Cogentix Research",
    "bimwave": "BIMwave",
}

BUSINESS_BASKET = {v: k for k, v in BASKET_BUSINESS.items()}


# â”€â”€ DB connection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_db():
    uri = os.getenv("MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
    db_name = os.getenv("MONGO_DB_NAME") or "torpedo"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client[db_name]


def get_leads_db():
    """Return the email_automation database that holds leads_enriched."""
    uri = os.getenv("MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client["email_automation"]


def _get_gmail_db():
    """Return the torpedo_gmail database that holds workspace_mailboxes."""
    try:
        uri = os.getenv("MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        return client["torpedo_gmail"]
    except Exception:
        return None


# â”€â”€ Request/response models â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class StepTemplate(BaseModel):
    step_number: int          # 1â€“4
    day_offset: int           # 0, 3, 6, 11
    subject: str
    body_html: str
    body_text: str = ""
    attachments: List[Dict[str, Any]] = []  # [{filename, content_b64, mime_type}]


class CreateCampaignRequest(BaseModel):
    business: str             # "sfw" | "cogentix" | "bimwave"
    name: Optional[str] = None
    mailbox_ids: List[str] = []
    steps: List[StepTemplate] = []


class UpdateStepRequest(BaseModel):
    subject: str
    body_html: str
    body_text: str = ""


class AddMailboxRequest(BaseModel):
    business: str             # "sfw" | "cogentix" | "bimwave"
    provider: str = "smtp"   # "smtp" | "ses"
    email: str
    display_name: str
    daily_limit: int = 400
    hourly_limit: int = 60
    # SMTP fields (required when provider=smtp)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    use_tls: bool = True
    # SES fields (required when provider=ses)
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""      # leave blank to use env / IAM role on VM
    aws_secret_access_key: str = ""


class ManualSuppressionRequest(BaseModel):
    email: str
    reason: Optional[str] = "manual"


class BusinessContextRequest(BaseModel):
    description: str = ""
    value_proposition: str = ""
    target_customer: str = ""
    tone: str = "professional"       # professional | friendly | direct
    sender_name: str = ""
    sender_title: str = ""


class SendTestEmailRequest(BaseModel):
    recipient_email: str
    step_number: int = 1


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _oid(doc) -> str:
    return str(doc.get("_id", ""))


def _clean(doc: dict) -> dict:
    """Convert ObjectId â†’ str for JSON serialisation."""
    doc["id"] = str(doc.pop("_id", ""))
    return doc


def _score_basket_for_lead(lead: dict, basket: str) -> float:
    """
    Return a rough affinity score (0â€“1) for a given basket using the lead's
    icp_tags and classification data already stored in leads_enriched.
    Used to order Dual Fit sequences.
    """
    tags = [t.lower() for t in (lead.get("icp_tags") or [])]
    basket_keywords = {
        "A": ["survey_fieldwork", "fieldwork", "data_services", "survey", "data"],
        "B": ["cogentix", "consumer_insights", "insights", "market_research"],
        "C": ["bimwave", "bim", "architecture", "construction", "aec"],
    }
    kws = basket_keywords.get(basket, [])
    hits = sum(1 for t in tags if any(k in t for k in kws))
    return hits / max(len(kws), 1)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  MAILBOX ENDPOINTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@router.get("/mailboxes")
def list_mailboxes():
    db = get_db()
    mailboxes = list(db["outreach_mailboxes"].find({}, {"smtp_password": 0, "aws_secret_access_key": 0}))
    for m in mailboxes:
        m["id"] = str(m.pop("_id"))
    return {"mailboxes": mailboxes}


@router.post("/mailboxes", status_code=201)
def add_mailbox(req: AddMailboxRequest):
    db = get_db()
    if req.business not in BUSINESS_LABEL:
        raise HTTPException(400, f"Unknown business '{req.business}'. Use: sfw, cogentix, bimwave")

    existing = db["outreach_mailboxes"].find_one({"email_address": req.email})
    if existing:
        raise HTTPException(409, f"Mailbox {req.email} already exists")

    if req.provider not in ("smtp", "ses"):
        raise HTTPException(400, "provider must be 'smtp' or 'ses'")

    if req.provider == "smtp" and not req.smtp_host:
        raise HTTPException(400, "smtp_host is required for SMTP provider")

    doc: Dict[str, Any] = {
        "mailbox_id": str(uuid.uuid4()),
        "business": req.business,
        "email_address": req.email,
        "display_name": req.display_name,
        "provider": req.provider,
        "daily_limit": req.daily_limit,
        "hourly_limit": req.hourly_limit,
        "is_active": True,
        "health_status": "healthy",
        "daily_sent_count": 0,
        "hourly_sent_count": 0,
        "last_send_at": None,
        "created_at": datetime.utcnow(),
    }

    if req.provider == "smtp":
        doc.update({
            "smtp_host": req.smtp_host,
            "smtp_port": req.smtp_port,
            "smtp_username": req.smtp_username,
            "smtp_password": req.smtp_password,
            "use_tls": req.use_tls,
        })
    else:  # ses
        doc.update({
            "aws_region": req.aws_region,
            "aws_access_key_id": req.aws_access_key_id or "",
            "aws_secret_access_key": req.aws_secret_access_key or "",
        })
    db["outreach_mailboxes"].insert_one(doc)
    doc["id"] = str(doc.pop("_id"))
    doc.pop("smtp_password", None)
    return {"mailbox": doc}


@router.delete("/mailboxes/{mailbox_id}")
def remove_mailbox(mailbox_id: str):
    db = get_db()
    res = db["outreach_mailboxes"].delete_one({"mailbox_id": mailbox_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Mailbox not found")
    return {"ok": True}


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  CAMPAIGN ENDPOINTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@router.get("/campaigns")
def list_campaigns():
    db = get_db()
    leads_db = get_leads_db()
    leads_enriched = leads_db["leads_enriched"]
    campaigns = list(db["outreach_campaigns_v2"].find())
    # Attach live stats to each
    sends_col = db["outreach_sends_v2"]
    for c in campaigns:
        cid = c.get("campaign_id", "")
        c["id"] = str(c.pop("_id"))
        pipeline = [
            {"$match": {"campaign_id": cid}},
            {"$group": {
                "_id": None,
                "sent": {"$sum": 1},
                "opened": {"$sum": {"$cond": [{"$gt": ["$open_count", 0]}, 1, 0]}},
                "replied": {"$sum": {"$cond": [{"$eq": ["$reply_received", True]}, 1, 0]}},
                "bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}},
            }}
        ]
        agg = list(sends_col.aggregate(pipeline))
        if agg:
            c["stats"] = agg[0]
            c["stats"].pop("_id", None)
        else:
            c["stats"] = {"sent": 0, "opened": 0, "replied": 0, "bounced": 0}

        enrolled = db["outreach_leads_v2"].count_documents({"campaign_id": cid})
        c["stats"]["enrolled"] = enrolled

    # Basket lead counts from leads_enriched (source of truth)
    basket_pipeline = [
        {"$match": {"email": {"$exists": True, "$ne": ""}}},
        {"$group": {"_id": "$classification_basket", "count": {"$sum": 1}}},
    ]
    basket_counts = {
        row["_id"]: row["count"]
        for row in leads_enriched.aggregate(basket_pipeline)
        if row["_id"]
    }
    total_leads = leads_enriched.count_documents({})
    total_with_email = leads_enriched.count_documents({"email": {"$exists": True, "$ne": ""}})
    no_basket = leads_enriched.count_documents({
        "email": {"$exists": True, "$ne": ""},
        "$or": [
            {"classification_basket": {"$exists": False}},
            {"classification_basket": None},
            {"classification_basket": ""},
        ]
    })

    return {
        "campaigns": campaigns,
        "basket_counts": basket_counts,
        "total_leads": total_leads,
        "total_with_email": total_with_email,
        "no_basket": no_basket,
    }


@router.post("/campaigns", status_code=201)
def create_campaign(req: CreateCampaignRequest):
    db = get_db()
    if req.business not in BUSINESS_LABEL:
        raise HTTPException(400, f"Unknown business '{req.business}'. Use: sfw, cogentix, bimwave")

    basket = BUSINESS_BASKET[req.business]
    campaign_id = str(uuid.uuid4())
    default_steps = []
    for i, day_offset in enumerate(SEQUENCE_STEPS):
        default_steps.append({
            "step_number": i + 1,
            "day_offset": day_offset,
            "subject": "",
            "body_html": "",
            "body_text": "",
        })

    # Merge provided steps
    steps_map = {s.step_number: s.dict() for s in req.steps}
    final_steps = []
    for ds in default_steps:
        if ds["step_number"] in steps_map:
            final_steps.append(steps_map[ds["step_number"]])
        else:
            final_steps.append(ds)

    doc = {
        "campaign_id": campaign_id,
        "business": req.business,
        "business_label": BUSINESS_LABEL[req.business],
        "basket": basket,
        "name": req.name or f"{BUSINESS_LABEL[req.business]} Cold Outreach",
        "mailbox_ids": req.mailbox_ids,
        "steps": final_steps,
        "is_active": False,
        "tags": [req.business],
        "campaign_type": "cold_outreach",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    db["outreach_campaigns_v2"].insert_one(doc)
    doc["id"] = str(doc.pop("_id"))
    return {"campaign": doc}


@router.put("/campaigns/{campaign_id}/steps/{step_number}")
def update_step_template(campaign_id: str, step_number: int, req: UpdateStepRequest):
    db = get_db()
    campaign = db["outreach_campaigns_v2"].find_one({"campaign_id": campaign_id})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    steps = campaign.get("steps", [])
    found = False
    for s in steps:
        if s["step_number"] == step_number:
            s["subject"] = req.subject
            s["body_html"] = req.body_html
            s["body_text"] = req.body_text
            found = True
            break

    if not found:
        raise HTTPException(404, f"Step {step_number} not found in campaign")

    db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id},
        {"$set": {"steps": steps, "updated_at": datetime.utcnow()}},
    )
    return {"ok": True, "steps": steps}


@router.put("/campaigns/{campaign_id}/context")
def update_business_context(campaign_id: str, req: BusinessContextRequest):
    """Save AI business context for a campaign. Used to personalise icebreakers."""
    db = get_db()
    campaign = db["outreach_campaigns_v2"].find_one({"campaign_id": campaign_id})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id},
        {"$set": {
            "business_context": req.dict(),
            "updated_at": datetime.utcnow(),
        }},
    )
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/steps/{step_number}/generate")
def generate_step_email(campaign_id: str, step_number: int):
    """
    Use OpenAI to generate a full cold email (subject + body) for a given step.

    The email will contain live placeholder tokens ({{first_name}}, {{company}}, etc.)
    so each recipient gets a personalised version at send time.

    Requires business_context to be saved on the campaign first (via the AI Context tab).
    """
    import openai as _openai
    from leads.openai_rotator import get_pipeline_rotator as _get_pipeline_rotator

    db = get_db()
    campaign = db["outreach_campaigns_v2"].find_one({"campaign_id": campaign_id})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    ctx = campaign.get("business_context") or {}
    if not ctx.get("description") and not ctx.get("value_proposition"):
        raise HTTPException(
            400,
            "No business context saved yet â€” fill in the AI Context tab first so the AI knows what to write."
        )

    # Use pipeline 1 (outreach) for email drafting â€” keys 1, 2, 3
    try:
        _rotator = _get_pipeline_rotator("outreach")
        key_index, api_key = _rotator.get_available_key()
    except Exception as e:
        raise HTTPException(500, f"OpenAI key unavailable: {e}")

    # Step metadata
    day_labels = {1: "Day 1 (initial outreach)", 2: "Day 4 (first follow-up)",
                  3: "Day 7 (second follow-up)", 4: "Day 12 (final bump)"}
    step_label = day_labels.get(step_number, f"Step {step_number}")

    step_instructions = {
        1: (
            "This is the FIRST cold email. It should introduce the sender, explain the value briefly, "
            "and end with a soft call-to-action (e.g. open to a quick call / happy to share more). "
            "Do not be pushy. Keep it under 150 words."
        ),
        2: (
            "This is the FIRST follow-up. The prospect has not replied. "
            "Reference the previous email briefly, add a new angle or stat, keep it under 100 words. "
            "Soft CTA only."
        ),
        3: (
            "This is the SECOND follow-up. Keep it very short (under 75 words). "
            "Add a different hook or a brief case study reference. Stay low-pressure."
        ),
        4: (
            "This is the FINAL follow-up (break-up email). Under 60 words. "
            "Acknowledge it may not be the right time, leave the door open, no hard sell."
        ),
    }

    tone_map = {
        "professional": "formal and professional",
        "friendly":     "warm, friendly, and approachable",
        "direct":       "direct and concise â€” no fluff",
        "conversational": "conversational, as if from one human to another",
    }

    prompt = f"""You are an expert B2B cold email copywriter.

Write a complete cold outreach email for Step {step_number} ({step_label}).

--- ABOUT OUR BUSINESS ---
Business: {campaign.get("business_label", campaign.get("business", ""))}
Description: {ctx.get("description", "")}
Value proposition: {ctx.get("value_proposition", "")}
Ideal customer: {ctx.get("target_customer", "")}
Sender name: {ctx.get("sender_name", "{{sender_name}}")}
Sender title: {ctx.get("sender_title", "")}
Tone: {tone_map.get(ctx.get("tone", "professional"), "professional")}

--- STEP INSTRUCTIONS ---
{step_instructions.get(step_number, "Write a relevant follow-up email.")}

--- OUTPUT FORMAT ---
Write ONLY the following two sections, exactly as shown:

SUBJECT: <the subject line>

BODY:
<the email body>

--- PLACEHOLDER TOKENS ---
You MUST use these tokens exactly (they are replaced per recipient at send time):
  {{{{first_name}}}}   â€” recipient's first name
  {{{{company}}}}      â€” recipient's company name
  {{{{title}}}}        â€” recipient's job title
  {{{{industry}}}}     â€” recipient's industry

Use at least {{{{first_name}}}} and {{{{company}}}} in the body.
Do not invent specific company facts â€” keep it general enough to apply to any recipient.
Do not write a signature block â€” the system appends one automatically.
"""

    try:
        _client = _openai.OpenAI(api_key=api_key)
        _response = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional B2B cold email copywriter. Follow instructions precisely."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600,
            temperature=0.72,
        )
        raw = _response.choices[0].message.content.strip()
        tokens_used = _response.usage.total_tokens if _response.usage else 0
        _rotator.log_request(key_index, tokens_used, "email_generation", success=True)
    except Exception as e:
        logger.error(f"OpenAI generate_step_email failed: {e}")
        raise HTTPException(500, f"AI generation failed: {e}")

    # Parse subject and body from output
    subject = ""
    body = ""
    if "SUBJECT:" in raw:
        parts = raw.split("BODY:", 1)
        subject_part = parts[0].replace("SUBJECT:", "").strip()
        subject = subject_part.strip()
        body = parts[1].strip() if len(parts) > 1 else ""
    else:
        # Fallback: first line as subject, rest as body
        lines = raw.splitlines()
        subject = lines[0].strip()
        body = "\n".join(lines[1:]).strip()

    logger.info(
        f"AI generated step {step_number} for campaign {campaign_id} "
        f"({tokens_used} tokens)"
    )

    return {
        "ok": True,
        "step_number": step_number,
        "subject": subject,
        "body_html": body,
        "tokens_used": tokens_used,
    }


@router.post("/campaigns/{campaign_id}/steps/{step_number}/test")
def send_test_email(campaign_id: str, step_number: int, req: SendTestEmailRequest):
    """
    Send a test version of one step to a given address.
    Tokens are replaced with sample placeholder values.
    Uses Gmail API via the workspace service (service account delegation).
    Falls back to SMTP if no Gmail mailbox is found.
    """
    import base64
    import re
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    db = get_db()
    campaign = db["outreach_campaigns_v2"].find_one({"campaign_id": campaign_id})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    step = next((s for s in campaign.get("steps", []) if s["step_number"] == step_number), None)
    if not step:
        raise HTTPException(404, f"Step {step_number} not found")

    if not step.get("subject") and not step.get("body_html"):
        raise HTTPException(400, "Step has no content yet â€” save the template first")

    # â”€â”€ Find a mailbox to send from â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Priority 1: Gmail API via workspace_mailboxes (torpedo_gmail DB)
    gmail_db = _get_gmail_db()
    gmail_mailbox = None
    if gmail_db is not None:
        gmail_mailbox = gmail_db["workspace_mailboxes"].find_one(
            {"is_active": True},
            sort=[("email", 1)],
        )

    # Priority 2: SMTP mailbox from outreach_mailboxes (torpedo DB)
    smtp_mailbox = db["outreach_mailboxes"].find_one(
        {"business": campaign["business"], "is_active": True}
    )

    if not gmail_mailbox and not smtp_mailbox:
        raise HTTPException(
            400,
            "No mailbox found â€” connect a Gmail account via the Mailboxes tab "
            "or add SMTP credentials"
        )

    sender_email = (gmail_mailbox or smtp_mailbox).get("email") or (smtp_mailbox or {}).get("email_address", "")
    sender_name = (gmail_mailbox or smtp_mailbox).get("display_name", "Team")

    # Replace tokens with sample data
    sample = {
        "{{first_name}}": "Alex",
        "{{last_name}}": "Johnson",
        "{{company}}": "Acme Corp",
        "{{title}}": "Head of Research",
        "{{industry}}": "Market Research",
        "{{sender_name}}": sender_name,
    }

    def _replace(text: str) -> str:
        for token, val in sample.items():
            text = text.replace(token, val)
        return text

    subject = _replace(step.get("subject", "(no subject)"))
    body_html = _replace(step.get("body_html", ""))
    # â”€â”€ Fetch sender signature via Gmail API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    signature_html = ""
    if gmail_mailbox:
        try:
            from app.services.gmail_workspace_service import GmailWorkspaceService as _GWS
        except ImportError:
            from backend.app.services.gmail_workspace_service import GmailWorkspaceService as _GWS
        _mongo = os.getenv("MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        _ws = _GWS(mongo_uri=_mongo)
        _ws.load_service_account()
        if _ws.is_configured():
            signature_html = _ws.get_signature(sender_email) or ""

    # Build final body with signature
    if signature_html:
        full_body_html = body_html + "<br><br>" + signature_html
    else:
        full_body_html = body_html

    body_text = full_body_html.replace("<br>", "\n").replace("<br/>", "\n")
    body_text = re.sub(r"<[^>]+>", "", body_text)

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = req.recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(full_body_html, "html"))

    # â”€â”€ Send via Gmail API or SMTP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if gmail_mailbox:
        # Reuse the workspace service created for signature fetch, or create one
        if not signature_html:
            try:
                from app.services.gmail_workspace_service import GmailWorkspaceService as _GWS2
            except ImportError:
                from backend.app.services.gmail_workspace_service import GmailWorkspaceService as _GWS2
            _mongo = os.getenv("MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
            _ws = _GWS2(mongo_uri=_mongo)
            _ws.load_service_account()

        if not _ws.is_configured():
            raise HTTPException(500, "Gmail service account not configured on server")

        try:
            service = _ws._get_service(sender_email)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            result = service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
        except Exception as e:
            logger.error(f"Gmail API test send failed: {e}")
            raise HTTPException(500, f"Gmail API error: {e}")
    else:
        # Fallback: SMTP
        import smtplib
        try:
            with smtplib.SMTP(smtp_mailbox["smtp_host"], smtp_mailbox["smtp_port"], timeout=30) as server:
                server.starttls()
                server.login(smtp_mailbox["smtp_username"], smtp_mailbox["smtp_password"])
                server.send_message(msg)
        except Exception as e:
            logger.error(f"SMTP test send failed: {e}")
            raise HTTPException(500, f"SMTP error: {e}")

    logger.info(f"Test email for step {step_number} sent to {req.recipient_email} via {sender_email}")
    return {"ok": True, "sent_to": req.recipient_email, "from": sender_email}


# â”€â”€ CSV / File attachment upload for campaign steps â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/campaigns/{campaign_id}/steps/{step_number}/attachments")
async def upload_step_attachment(campaign_id: str, step_number: int, file: UploadFile = File(...)):
    """
    Upload a file attachment (CSV, PDF, etc.) for a specific campaign step.
    The file is stored as base64 in the step's attachments array in MongoDB.
    """
    import base64 as _b64

    db = get_db()
    campaign = db["outreach_campaigns_v2"].find_one({"campaign_id": campaign_id})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # Read file content
    content_bytes = await file.read()
    max_size = 10 * 1024 * 1024  # 10 MB limit
    if len(content_bytes) > max_size:
        raise HTTPException(400, f"File too large. Maximum size is {max_size // (1024*1024)} MB.")

    content_b64 = _b64.b64encode(content_bytes).decode("utf-8")
    mime_type = file.content_type or "application/octet-stream"
    filename = file.filename or "attachment"

    attachment_doc = {
        "filename": filename,
        "content_b64": content_b64,
        "mime_type": mime_type,
        "size_bytes": len(content_bytes),
        "uploaded_at": datetime.utcnow().isoformat(),
    }

    # Upsert into the step's attachments array
    # steps is an array â€” find the matching step and push attachment
    result = db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id, "steps.step_number": step_number},
        {"$push": {
            "steps.$.attachments": attachment_doc,
        }},
    )
    if result.matched_count == 0:
        raise HTTPException(404, f"Step {step_number} not found in campaign")

    logger.info(f"Attachment '{filename}' ({mime_type}, {len(content_bytes)} bytes) uploaded to campaign {campaign_id} step {step_number}")
    return {"ok": True, "filename": filename, "size_bytes": len(content_bytes)}


@router.delete("/campaigns/{campaign_id}/steps/{step_number}/attachments/{filename}")
def remove_step_attachment(campaign_id: str, step_number: int, filename: str):
    """Remove a specific attachment from a campaign step by filename."""
    db = get_db()
    result = db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id, "steps.step_number": step_number},
        {"$pull": {"steps.$.attachments": {"filename": filename}}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Campaign or step not found")
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/launch")
def launch_campaign(campaign_id: str, background_tasks: BackgroundTasks):
    db = get_db()
    campaign = db["outreach_campaigns_v2"].find_one({"campaign_id": campaign_id})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id},
        {"$set": {"is_active": True, "launched_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )

    # Enroll leads in background so the response is fast
    background_tasks.add_task(_enroll_basket_leads, campaign_id, campaign["basket"])

    return {"ok": True, "message": "Campaign launched. Enrollment running in background."}


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str):
    db = get_db()
    res = db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id},
        {"$set": {"is_active": False, "paused_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Campaign not found")
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/resume")
def resume_campaign(campaign_id: str):
    db = get_db()
    res = db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id},
        {"$set": {"is_active": True, "resumed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Campaign not found")
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/stats")
def campaign_stats(campaign_id: str):
    db = get_db()
    campaign = db["outreach_campaigns_v2"].find_one({"campaign_id": campaign_id})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    sends = db["outreach_sends_v2"]
    enrolled = db["outreach_leads_v2"].count_documents({"campaign_id": campaign_id})

    # Overall stats
    overall_pipeline = [
        {"$match": {"campaign_id": campaign_id}},
        {"$group": {
            "_id": None,
            "total_sent": {"$sum": 1},
            "total_opened": {"$sum": {"$cond": [{"$gt": ["$open_count", 0]}, 1, 0]}},
            "total_replied": {"$sum": {"$cond": [{"$eq": ["$reply_received", True]}, 1, 0]}},
            "total_bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}},
            "total_unsubscribed": {"$sum": {"$cond": [{"$eq": ["$unsubscribed", True]}, 1, 0]}},
        }},
    ]
    overall = list(sends.aggregate(overall_pipeline))
    overall_stats = overall[0] if overall else {
        "total_sent": 0, "total_opened": 0, "total_replied": 0,
        "total_bounced": 0, "total_unsubscribed": 0,
    }
    overall_stats.pop("_id", None)
    overall_stats["enrolled"] = enrolled

    # Per-step breakdown
    step_pipeline = [
        {"$match": {"campaign_id": campaign_id}},
        {"$group": {
            "_id": "$workflow_step",
            "sent": {"$sum": 1},
            "opened": {"$sum": {"$cond": [{"$gt": ["$open_count", 0]}, 1, 0]}},
            "replied": {"$sum": {"$cond": [{"$eq": ["$reply_received", True]}, 1, 0]}},
            "bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    step_stats = []
    for row in sends.aggregate(step_pipeline):
        step_num = row.pop("_id")
        day_offset = SEQUENCE_STEPS[step_num] if step_num < len(SEQUENCE_STEPS) else step_num
        row["step_number"] = step_num + 1
        row["day_offset"] = day_offset
        row["open_rate"] = round(row["opened"] / max(row["sent"], 1) * 100, 1)
        row["reply_rate"] = round(row["replied"] / max(row["sent"], 1) * 100, 1)
        step_stats.append(row)

    # Rates
    sent = overall_stats.get("total_sent", 0)
    overall_stats["open_rate"] = round(overall_stats.get("total_opened", 0) / max(sent, 1) * 100, 1)
    overall_stats["reply_rate"] = round(overall_stats.get("total_replied", 0) / max(sent, 1) * 100, 1)
    overall_stats["bounce_rate"] = round(overall_stats.get("total_bounced", 0) / max(sent, 1) * 100, 1)

    return {"campaign_id": campaign_id, "overall": overall_stats, "by_step": step_stats}


@router.get("/reports/divisions-over-time")
def reports_divisions_over_time(
    days: int = Query(30, ge=7, le=365, description="Number of trailing days to include"),
):
    """
    Aggregate time-series stats for all divisions.

    Returns:
      - daily trend rows: leads generated, sent, opened, replied, bounced
      - lead-source breakdown over the selected period
      - per-division mail performance totals for the selected period
    """
    db = get_db()
    leads_db = get_leads_db()

    now = datetime.utcnow()
    start_dt = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    day_keys = [
        (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(days)
    ]

    daily = {
        d: {
            "date": d,
            "leads_generated": 0,
            "mails_sent": 0,
            "opened": 0,
            "replied": 0,
            "bounced": 0,
            "lead_sources": {},
            "divisions": {
                "sfw": {"mails_sent": 0, "opened": 0, "replied": 0, "bounced": 0},
                "cogentix": {"mails_sent": 0, "opened": 0, "replied": 0, "bounced": 0},
                "bimwave": {"mails_sent": 0, "opened": 0, "replied": 0, "bounced": 0},
                "unknown": {"mails_sent": 0, "opened": 0, "replied": 0, "bounced": 0},
            },
        }
        for d in day_keys
    }

    lead_source_totals: Dict[str, int] = {}
    division_totals = {
        "sfw": {"mails_sent": 0, "opened": 0, "replied": 0, "bounced": 0},
        "cogentix": {"mails_sent": 0, "opened": 0, "replied": 0, "bounced": 0},
        "bimwave": {"mails_sent": 0, "opened": 0, "replied": 0, "bounced": 0},
        "unknown": {"mails_sent": 0, "opened": 0, "replied": 0, "bounced": 0},
    }

    # 1) Leads generated by source over time
    leads_pipeline = [
        {"$match": {"created_at": {"$gte": start_dt}}},
        {"$project": {
            "day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
            "source": {"$ifNull": ["$source", "unknown"]},
        }},
        {"$group": {
            "_id": {"day": "$day", "source": "$source"},
            "count": {"$sum": 1},
        }},
    ]

    for row in leads_db["leads_enriched"].aggregate(leads_pipeline):
        day = row["_id"]["day"]
        source = (row["_id"].get("source") or "unknown").lower().strip()
        count = int(row.get("count", 0))
        if day not in daily:
            continue
        daily[day]["leads_generated"] += count
        daily[day]["lead_sources"][source] = daily[day]["lead_sources"].get(source, 0) + count
        lead_source_totals[source] = lead_source_totals.get(source, 0) + count

    # 2) Send/open/reply/bounce over time split by division
    sends_pipeline = [
        {"$match": {"sent_at": {"$gte": start_dt}}},
        {"$lookup": {
            "from": "outreach_campaigns_v2",
            "localField": "campaign_id",
            "foreignField": "campaign_id",
            "as": "campaign",
        }},
        {"$addFields": {
            "business": {
                "$ifNull": [
                    {"$arrayElemAt": ["$campaign.business", 0]},
                    "unknown",
                ]
            }
        }},
        {"$project": {
            "day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$sent_at"}},
            "business": "$business",
            "opened": {"$cond": [{"$gt": ["$open_count", 0]}, 1, 0]},
            "replied": {"$cond": [{"$eq": ["$reply_received", True]}, 1, 0]},
            "bounced": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]},
        }},
        {"$group": {
            "_id": {"day": "$day", "business": "$business"},
            "mails_sent": {"$sum": 1},
            "opened": {"$sum": "$opened"},
            "replied": {"$sum": "$replied"},
            "bounced": {"$sum": "$bounced"},
        }},
    ]

    for row in db["outreach_sends_v2"].aggregate(sends_pipeline):
        day = row["_id"]["day"]
        biz = (row["_id"].get("business") or "unknown").lower().strip()
        if biz not in ("sfw", "cogentix", "bimwave"):
            biz = "unknown"

        if day not in daily:
            continue

        sent = int(row.get("mails_sent", 0))
        opened = int(row.get("opened", 0))
        replied = int(row.get("replied", 0))
        bounced = int(row.get("bounced", 0))

        daily[day]["mails_sent"] += sent
        daily[day]["opened"] += opened
        daily[day]["replied"] += replied
        daily[day]["bounced"] += bounced

        daily[day]["divisions"][biz]["mails_sent"] += sent
        daily[day]["divisions"][biz]["opened"] += opened
        daily[day]["divisions"][biz]["replied"] += replied
        daily[day]["divisions"][biz]["bounced"] += bounced

        division_totals[biz]["mails_sent"] += sent
        division_totals[biz]["opened"] += opened
        division_totals[biz]["replied"] += replied
        division_totals[biz]["bounced"] += bounced

    daily_rows = [daily[d] for d in day_keys]

    totals = {
        "leads_generated": sum(r["leads_generated"] for r in daily_rows),
        "mails_sent": sum(r["mails_sent"] for r in daily_rows),
        "opened": sum(r["opened"] for r in daily_rows),
        "replied": sum(r["replied"] for r in daily_rows),
        "bounced": sum(r["bounced"] for r in daily_rows),
    }

    sent_total = max(totals["mails_sent"], 1)
    totals["open_rate"] = round(totals["opened"] / sent_total * 100, 1)
    totals["reply_rate"] = round(totals["replied"] / sent_total * 100, 1)
    totals["bounce_rate"] = round(totals["bounced"] / sent_total * 100, 1)

    for biz, vals in division_totals.items():
        s = max(vals["mails_sent"], 1)
        vals["open_rate"] = round(vals["opened"] / s * 100, 1)
        vals["reply_rate"] = round(vals["replied"] / s * 100, 1)
        vals["bounce_rate"] = round(vals["bounced"] / s * 100, 1)

    return {
        "days": days,
        "start_date": day_keys[0] if day_keys else None,
        "end_date": day_keys[-1] if day_keys else None,
        "totals": totals,
        "lead_source_totals": lead_source_totals,
        "division_totals": division_totals,
        "daily": daily_rows,
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  ENROLLMENT LOGIC
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

_BASKET_SEGMENT_FALLBACK: Dict[str, List[str]] = {
    "A": ["survey_fieldwork", "sfw"],
    "B": ["cogentix"],
    "C": ["bimwave"],
    "D": ["dual_fit"],
}

_BASKET_TAG_FALLBACK: Dict[str, List[str]] = {
    "A": ["survey_fieldwork"],
    "B": ["cogentix"],
    "C": ["bimwave"],
    "D": ["survey_fieldwork", "cogentix"],
}


def _build_basket_enrollment_query(basket: str) -> Dict[str, Any]:
    """
    Build a leads_enriched query for enrollment.
    Uses classification_basket primarily, with icp_segment/icp_tags fallback
    so legacy leads are not silently excluded.
    """
    clauses: List[Dict[str, Any]] = [{"classification_basket": basket}]

    segments = _BASKET_SEGMENT_FALLBACK.get(basket, [])
    if segments:
        clauses.append({"icp_segment": {"$in": segments}})

    tags = _BASKET_TAG_FALLBACK.get(basket, [])
    if tags:
        if basket == "D":
            clauses.append({"icp_tags": {"$all": tags}})
        else:
            clauses.append({"icp_tags": {"$in": tags}})

    return {
        "email": {"$exists": True, "$ne": ""},
        "$or": clauses,
    }


def _sync_active_campaign_enrollment(db):
    """
    Catch-up enrollment for all active campaigns.
    This keeps outreach enrollment aligned with newly added AI leads.
    """
    campaigns = list(
        db["outreach_campaigns_v2"].find(
            {"is_active": True},
            {"campaign_id": 1, "basket": 1, "business": 1},
        )
    )
    synced_baskets = set()
    has_active_business_campaign = False
    for camp in campaigns:
        cid = camp.get("campaign_id")
        basket = camp.get("basket")
        if not basket:
            basket = BUSINESS_BASKET.get((camp.get("business") or "").lower())
        if cid and basket:
            _enroll_basket_leads(cid, basket)
            synced_baskets.add(basket)
        if camp.get("business") in {"sfw", "cogentix", "bimwave"}:
            has_active_business_campaign = True

    # Dual-fit leads are basket D and should still be enrolled whenever any
    # business campaign is active, even if no explicit basket-D campaign exists.
    if has_active_business_campaign and "D" not in synced_baskets and campaigns:
        first_cid = campaigns[0].get("campaign_id")
        if first_cid:
            _enroll_basket_leads(first_cid, "D")

def _enroll_basket_leads(campaign_id: str, basket: str):
    """
    Background task: pull leads from leads_enriched matching the basket,
    filter out bounced/already-enrolled, and create outreach_leads_v2 records.
    For Dual Fit (basket D), all 3 business sequences are queued with staggered starts.
    """
    try:
        db = get_db()
        leads_db = get_leads_db()   # email_automation DB
        suppression = db["outreach_bounce_suppression"]
        outreach_leads = db["outreach_leads_v2"]
        leads_enriched = leads_db["leads_enriched"]
        campaigns_col = db["outreach_campaigns_v2"]

        # Get all suppressed emails in a set for fast lookup
        suppressed_emails = {
            doc["email"] for doc in suppression.find({}, {"email": 1, "_id": 0})
        }

        if basket == "D":
            # Dual Fit: enroll into all 3 business campaigns in score order
            _enroll_dual_fit_leads(db, leads_db, suppressed_emails)
            return

        # Regular basket: single campaign enrollment
        campaign = campaigns_col.find_one({"campaign_id": campaign_id})
        if not campaign:
            logger.error(f"Campaign {campaign_id} not found during enrollment")
            return

        # Already enrolled emails for this campaign
        enrolled_emails = {
            doc["email"] for doc in outreach_leads.find(
                {"campaign_id": campaign_id}, {"email": 1, "_id": 0}
            )
        }

        query = _build_basket_enrollment_query(basket)
        cursor = leads_enriched.find(query)

        enrolled_count = 0
        skipped_suppressed = 0
        skipped_duplicate = 0

        for lead in cursor:
            email = (lead.get("email") or "").lower().strip()
            if not email:
                continue
            if email in suppressed_emails:
                skipped_suppressed += 1
                continue
            if email in enrolled_emails:
                skipped_duplicate += 1
                continue

            lead_id = str(lead.get("_id"))
            now = datetime.utcnow()
            outreach_lead_doc = {
                "lead_id": lead_id,
                "campaign_id": campaign_id,
                "email": email,
                "name": lead.get("name", ""),
                "first_name": lead.get("first_name") or (lead.get("name") or "").split()[0],
                "company_name": lead.get("company_name", ""),
                "title": lead.get("title", ""),
                "company_industry": lead.get("company_industry", ""),
                "seniority_level": lead.get("seniority_level", ""),
                "classification_basket": basket,
                "lead_service_type": {
                    "A": "data_services",
                    "B": "consumer_insights",
                    "C": "bimwave",
                }.get(basket, "data_services"),
                "personalization_level": "medium",
                "workflow_status": "not_started",
                "current_step": 0,
                "next_send_at": now,
                "enrolled_at": now,
                "created_at": now,
                "updated_at": now,
                # Carry forward so the pre-send bounce-risk guard can identify
                # pattern-derived emails and check domain risk before sending.
                "email_source": lead.get("email_source"),
            }
            try:
                outreach_leads.insert_one(outreach_lead_doc)
                enrolled_emails.add(email)
                enrolled_count += 1
            except Exception as e:
                logger.warning(f"Could not enroll {email}: {e}")

        logger.info(
            f"Enrollment complete for campaign {campaign_id} (basket {basket}): "
            f"enrolled={enrolled_count}, skipped_suppressed={skipped_suppressed}, "
            f"skipped_duplicate={skipped_duplicate}"
        )
    except Exception as e:
        logger.error(f"Enrollment background task failed for campaign {campaign_id}: {e}", exc_info=True)


def _enroll_dual_fit_leads(db, leads_db, suppressed_emails: set):
    """
    Enroll Dual Fit (basket D) leads into all 3 business campaigns,
    with staggered start dates ordered by ICP affinity score.
    Gap between sequences: SEQUENCE_DURATION_DAYS + DUAL_FIT_GAP_DAYS
    """
    try:
        campaigns_col = db["outreach_campaigns_v2"]
        outreach_leads = db["outreach_leads_v2"]
        leads_enriched = leads_db["leads_enriched"]

        # Find active campaigns for all 3 businesses
        business_campaigns: Dict[str, Any] = {}
        for biz in ["sfw", "cogentix", "bimwave"]:
            c = campaigns_col.find_one({"business": biz, "is_active": True})
            if c:
                business_campaigns[biz] = c

        if not business_campaigns:
            logger.warning("No active campaigns found for any business â€” skipping Dual Fit enrollment")
            return

        cursor = leads_enriched.find(_build_basket_enrollment_query("D"))

        enrolled_count = 0
        now = datetime.utcnow()
        sequence_window = SEQUENCE_DURATION_DAYS + DUAL_FIT_GAP_DAYS  # days before next sequence starts

        for lead in cursor:
            email = (lead.get("email") or "").lower().strip()
            if not email or email in suppressed_emails:
                continue

            lead_id = str(lead.get("_id"))

            # Score lead against each basket to determine send order
            scored = []
            for biz, campaign in business_campaigns.items():
                basket = BUSINESS_BASKET.get(biz, "A")
                score = _score_basket_for_lead(lead, basket)
                scored.append((score, biz, campaign))

            # Sort descending: highest affinity goes first
            scored.sort(key=lambda x: x[0], reverse=True)

            dual_fit_queue = []
            for seq_index, (score, biz, campaign) in enumerate(scored):
                cid = campaign["campaign_id"]

                # Check if already enrolled in this campaign
                existing = outreach_leads.find_one({"lead_id": lead_id, "campaign_id": cid})
                if existing:
                    continue

                start_date = now + timedelta(days=seq_index * sequence_window)
                outreach_lead_doc = {
                    "lead_id": lead_id,
                    "campaign_id": cid,
                    "email": email,
                    "name": lead.get("name", ""),
                    "first_name": lead.get("first_name") or (lead.get("name") or "").split()[0],
                    "company_name": lead.get("company_name", ""),
                    "title": lead.get("title", ""),
                    "company_industry": lead.get("company_industry", ""),
                    "seniority_level": lead.get("seniority_level", ""),
                    "classification_basket": "D",
                    "dual_fit": True,
                    "dual_fit_sequence_index": seq_index + 1,
                    "lead_service_type": {"sfw": "data_services", "cogentix": "consumer_insights", "bimwave": "bimwave"}.get(biz),
                    "personalization_level": "medium",
                    "workflow_status": "not_started" if seq_index == 0 else "pending_scheduled",
                    "current_step": 0,
                    "next_send_at": start_date,
                    "enrolled_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
                try:
                    outreach_leads.insert_one(outreach_lead_doc)
                    dual_fit_queue.append({
                        "campaign_id": cid,
                        "business": biz,
                        "sequence_index": seq_index + 1,
                        "scheduled_start": start_date,
                    })
                    enrolled_count += 1
                except Exception as e:
                    logger.warning(f"Could not enroll dual-fit lead {email} into {biz}: {e}")

        logger.info(f"Dual Fit enrollment complete: {enrolled_count} lead-campaign records created")
    except Exception as e:
        logger.error(f"Dual Fit enrollment failed: {e}", exc_info=True)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  SUPPRESSION LIST ENDPOINTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@router.get("/suppression")
def list_suppression(page: int = 1, limit: int = 100, search: str = ""):
    db = get_db()
    query: Dict[str, Any] = {}
    if search:
        query["email"] = {"$regex": search, "$options": "i"}

    total = db["outreach_bounce_suppression"].count_documents(query)
    docs = list(
        db["outreach_bounce_suppression"]
        .find(query)
        .sort("created_at", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"total": total, "page": page, "suppressed": docs}


@router.get("/suppression/stats")
def suppression_stats():
    db = get_db()
    total = db["outreach_bounce_suppression"].count_documents({})
    return {"total_suppressed": total}


@router.post("/suppression/manual", status_code=201)
def manual_suppress(req: ManualSuppressionRequest):
    db = get_db()
    email = req.email.lower().strip()
    now = datetime.utcnow()
    try:
        db["outreach_bounce_suppression"].update_one(
            {"email": email},
            {"$setOnInsert": {
                "email": email,
                "bounced_at": now,
                "reason": req.reason,
                "manual": True,
                "created_at": now,
            }},
            upsert=True,
        )
    except Exception as e:
        raise HTTPException(500, f"Could not add suppression: {e}")

    # Also mark in leads_enriched
    get_leads_db()["leads_enriched"].update_many(
        {"email": email},
        {"$set": {"email_status": "bounced", "bounce_suppressed": True, "bounced_at": now}},
    )
    return {"ok": True, "email": email}


@router.delete("/suppression/{email}")
def remove_suppression(email: str):
    """Remove an email from suppression list (use only if added by mistake)."""
    db = get_db()
    email = email.lower().strip()
    res = db["outreach_bounce_suppression"].delete_one({"email": email})
    if res.deleted_count == 0:
        raise HTTPException(404, "Email not found in suppression list")

    # Unmark in leads_enriched
    get_leads_db()["leads_enriched"].update_many(
        {"email": email},
        {"$unset": {"bounce_suppressed": ""}, "$set": {"email_status": "unknown"}},
    )
    return {"ok": True, "email": email}


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  DUAL FIT â€” manual trigger for enrollment
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@router.post("/dual-fit/enroll")
def enroll_dual_fit(background_tasks: BackgroundTasks):
    """Manually trigger Dual Fit enrollment across all active campaigns."""
    db = get_db()
    leads_db = get_leads_db()
    suppressed = {
        doc["email"] for doc in db["outreach_bounce_suppression"].find({}, {"email": 1, "_id": 0})
    }
    background_tasks.add_task(_enroll_dual_fit_leads, db, leads_db, suppressed)
    return {"ok": True, "message": "Dual Fit enrollment started in background"}


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  OPEN / CLICK TRACKING  (self-hosted â€” works with Gmail API sends)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

# Env var: public-facing backend URL, e.g. https://api.mydomain.com
# If unset, tracking pixel + link rewriting are silently skipped (dev safety).
TRACKING_BASE_URL: str = os.getenv("TRACKING_BASE_URL", "").rstrip("/")

# 1Ã—1 transparent PNG (68 bytes)
_TRANSPARENT_PIXEL = _b64_module.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAB"
    "Nl7BcQAAAABJRU5ErkJggg=="
)


@router.get("/track/open/{send_id}")
async def track_open(send_id: str):
    """
    Records an email-open event and returns a 1Ã—1 transparent PNG.
    The tracking pixel is injected into outgoing emails by _inject_open_tracking().
    """
    try:
        db = get_db()
        db["outreach_sends_v2"].update_one(
            {"send_id": send_id},
            {"$inc": {"open_count": 1}, "$set": {"last_opened_at": datetime.utcnow()}},
        )
    except Exception as exc:
        logger.error(f"Open-track write failed for send_id={send_id}: {exc}")

    return Response(
        content=_TRANSPARENT_PIXEL,
        media_type="image/png",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/track/click/{send_id}")
async def track_click(send_id: str, url: str = Query(...)):
    """
    Records a click event and 302-redirects to the original URL.
    Links in outgoing emails are rewritten by _rewrite_links_for_click_tracking().
    """
    decoded_url = _url_unquote(url)

    # Basic URL validation â€” only allow http(s) redirects
    if not decoded_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid redirect URL")

    try:
        db = get_db()
        now = datetime.utcnow()
        db["outreach_sends_v2"].update_one(
            {"send_id": send_id},
            {
                "$inc": {"click_count": 1},
                "$set": {"last_clicked_at": now},
                "$push": {"clicks": {"url": decoded_url, "at": now}},
            },
        )
    except Exception as exc:
        logger.error(f"Click-track write failed for send_id={send_id}: {exc}")

    return RedirectResponse(url=decoded_url, status_code=302)


# â”€â”€ Helpers: inject pixel & rewrite links in outgoing HTML â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _inject_open_tracking(html_body: str, send_id: str, base_url: str) -> str:
    """Insert a 1Ã—1 open-tracking pixel before </body> (or append)."""
    pixel = (
        f'<img src="{base_url}/api/cold-outreach/track/open/{send_id}" '
        f'width="1" height="1" style="display:none" alt="">'
    )
    if "</body>" in html_body.lower():
        return _re.sub(r"(</body>)", f"{pixel}\\1", html_body, flags=_re.IGNORECASE)
    return html_body + pixel


def _rewrite_links_for_click_tracking(html_body: str, send_id: str, base_url: str) -> str:
    """Rewrite href links to route through the click-tracking redirect. Skip mailto: and unsubscribe links."""
    def _replace(match):
        original = match.group(1)
        if original.lower().startswith("mailto:"):
            return match.group(0)
        if "unsubscribe" in original.lower():
            return match.group(0)
        # Don't rewrite our own tracking URLs
        if "/track/" in original:
            return match.group(0)
        encoded = _url_quote(original, safe="")
        return f'href="{base_url}/api/cold-outreach/track/click/{send_id}?url={encoded}"'

    return _re.sub(r'href="([^"]+)"', _replace, html_body)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  OUTREACH SEND PROCESSOR â€” background job + manual trigger endpoint
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

# Set to an email address to redirect ALL outgoing outreach mail (test mode).
# Set to None to send to actual recipient.
_OUTREACH_TEST_OVERRIDE_EMAIL: Optional[str] = None

# Sender mailbox for each business (must exist in torpedo_gmail.workspace_mailboxes)
_BUSINESS_SENDER: Dict[str, str] = {
    "sfw": "indira@surveyfieldwork.com",
    "cogentix": "meera@cogentixresearch.com",
    "bimwave": "susanta@cogentixresearch.com",   # update when bimwave mailbox added
}

_BUSINESS_DISPLAY_NAME: Dict[str, str] = {
    "sfw": "Indira Das",
    "cogentix": "Meera Rathi",
    "bimwave": "Susanta Sarkar",
}

# Daily send cap per sender email (AWS SES mailboxes are exempt)
_DAILY_SEND_LIMIT_PER_MAILBOX = 2000

# â”€â”€ Per-mailbox 429 cooldown tracking â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# {sender_email: datetime_when_cooldown_expires}  â€” in-memory, resets on restart
_MAILBOX_COOLDOWN: Dict[str, datetime] = {}
_COOLDOWN_SECONDS = 900  # 15 minutes after a 429 error

# Periodic catch-up enrollment interval for active campaigns.
_LAST_ENROLL_SYNC_AT: Optional[datetime] = None
_ENROLL_SYNC_INTERVAL_SECONDS = int(
    os.getenv("OUTREACH_ENROLL_SYNC_INTERVAL_SECONDS", "300")
)


def _resolve_sender_for_campaign(db, campaign: dict) -> Optional[Dict[str, Any]]:
    """
    Resolve the sender for a campaign with this priority:
      1) campaign mailbox_ids in outreach_mailboxes
      2) active outreach_mailboxes for campaign business
      3) static business sender (if active workspace mailbox exists)

    Returns:
      {
        "from_email": str,
        "display_name": str,
        "transport": "gmail"|"smtp",
        "mailbox_doc": dict | None,
      }
    """
    business = campaign.get("business", "sfw")
    default_display = _BUSINESS_DISPLAY_NAME.get(business, "Team")

    candidates: List[Dict[str, Any]] = []
    for mailbox_id in (campaign.get("mailbox_ids") or []):
        if not mailbox_id:
            continue
        doc = db["outreach_mailboxes"].find_one(
            {"mailbox_id": mailbox_id, "is_active": True}
        )
        if doc:
            candidates.append(doc)

    if not candidates:
        candidates = list(
            db["outreach_mailboxes"]
            .find({"business": business, "is_active": True})
            .sort("created_at", 1)
        )

    gmail_db = _get_gmail_db()
    workspace_col = gmail_db["workspace_mailboxes"] if gmail_db is not None else None

    # Prefer Gmail when this sender mailbox is actively connected.
    for cand in candidates:
        from_email = ((cand.get("email_address") or cand.get("email") or "").strip().lower())
        if not from_email or workspace_col is None:
            continue
        ws_doc = workspace_col.find_one({"email": from_email, "is_active": True})
        if ws_doc:
            return {
                "from_email": from_email,
                "display_name": ws_doc.get("display_name") or cand.get("display_name") or default_display,
                "transport": "gmail",
                "mailbox_doc": cand,
            }

    # Fallback to SMTP mailbox for this business.
    for cand in candidates:
        if cand.get("provider") != "smtp":
            continue
        from_email = ((cand.get("email_address") or cand.get("email") or "").strip().lower())
        if not from_email:
            continue
        if cand.get("smtp_host") and cand.get("smtp_port") and cand.get("smtp_username") and cand.get("smtp_password"):
            return {
                "from_email": from_email,
                "display_name": cand.get("display_name") or default_display,
                "transport": "smtp",
                "mailbox_doc": cand,
            }

    # Static fallback sender if that workspace mailbox exists.
    fallback_email = _BUSINESS_SENDER.get(business, "indira@surveyfieldwork.com").lower()
    if workspace_col is not None:
        ws_doc = workspace_col.find_one({"email": fallback_email, "is_active": True})
        if ws_doc:
            return {
                "from_email": fallback_email,
                "display_name": ws_doc.get("display_name") or default_display,
                "transport": "gmail",
                "mailbox_doc": None,
            }

    return None


def _is_mailbox_in_cooldown(sender_email: str) -> bool:
    """Return True if this mailbox recently hit a Gmail 429."""
    expires = _MAILBOX_COOLDOWN.get(sender_email)
    if expires and datetime.utcnow() < expires:
        return True
    return False


def _set_mailbox_cooldown(sender_email: str, retry_after_str: str = ""):
    """Set a 429 cooldown for this mailbox. Parses 'Retry after' from error if available."""
    cooldown_until = datetime.utcnow() + timedelta(seconds=_COOLDOWN_SECONDS)
    # Try to parse the actual retry-after timestamp from Gmail error
    if retry_after_str:
        try:
            # Format: "2026-04-10T13:14:10.001Z"
            import re as _re_cd
            match = _re_cd.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', retry_after_str)
            if match:
                parsed = datetime.strptime(match.group(1), '%Y-%m-%dT%H:%M:%S')
                if parsed > datetime.utcnow():
                    cooldown_until = parsed + timedelta(seconds=60)  # +1 min buffer
        except Exception:
            pass
    _MAILBOX_COOLDOWN[sender_email] = cooldown_until
    logger.warning(f"[Outreach] Mailbox {sender_email} in cooldown until {cooldown_until.isoformat()}")


def _sender_at_daily_limit(db, from_email: str) -> bool:
    """Return True if this sender has hit the daily send cap.
    AWS SES mailboxes are exempt (no limit)."""
    mailbox = db["outreach_mailboxes"].find_one({"email_address": from_email})
    if mailbox and mailbox.get("provider") == "ses":
        return False
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = db["outreach_sends_v2"].count_documents({
        "from_email": from_email,
        "sent_at": {"$gte": today_start},
    })
    return sent_today >= _DAILY_SEND_LIMIT_PER_MAILBOX


# Per-business step context for AI generation
_STEP_INSTRUCTIONS: Dict[int, str] = {
    1: (
        "This is the FIRST cold email. Introduce yourself briefly, state the value for "
        "their specific role/company, and end with a soft CTA (open to a quick call / "
        "happy to share more). Keep it under 120 words."
    ),
    2: (
        "This is the FIRST follow-up. The prospect has not replied. Reference the previous "
        "email briefly, add a new angle or a concrete benefit for their industry. "
        "Under 90 words. Soft CTA only."
    ),
    3: (
        "This is the SECOND follow-up. Very short (under 70 words). Add a different hook "
        "or a quick case-study reference relevant to their vertical. Stay low-pressure."
    ),
    4: (
        "This is the FINAL follow-up (break-up email). Under 55 words. "
        "Acknowledge it may not be the right time, leave the door open, no hard sell."
    ),
}


def _get_gmail_workspace_service():
    """Return a ready GmailWorkspaceService instance loaded from DB credentials."""
    try:
        from app.services.gmail_workspace_service import GmailWorkspaceService
    except ImportError:
        from backend.app.services.gmail_workspace_service import GmailWorkspaceService

    mongo_uri = os.getenv("MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
    svc = GmailWorkspaceService(mongo_uri=mongo_uri, db_name="torpedo_gmail")
    svc.load_service_account()
    return svc


# â”€â”€ Gmail signature cache (keyed by from_email, refreshed every 6 hours) â”€â”€
_signature_cache: dict[str, tuple[str | None, float]] = {}
_SIGNATURE_TTL = 6 * 3600  # 6 hours in seconds


def _get_gmail_signature(from_email: str) -> str | None:
    """Return the Gmail signature HTML for *from_email* (cached)."""
    import time
    now = time.time()
    cached = _signature_cache.get(from_email)
    if cached and (now - cached[1]) < _SIGNATURE_TTL:
        return cached[0]

    svc = _get_gmail_workspace_service()
    sig = svc.get_signature(from_email)
    _signature_cache[from_email] = (sig, now)
    return sig


def _generate_personalized_email(
    lead: dict,
    step_number: int,
    business: str,
    business_label: str,
    campaign_ctx: dict,
    sender_name: str,
) -> tuple[str, str]:
    """
    Call Gemini to produce a unique (subject, body_html) for this specific lead.
    Uses the Gemini key rotator (7 free-tier keys).
    Returns (subject, body_html). Raises on failure.
    """
    import google.generativeai as genai
    from leads.gemini_rotator import get_pipeline_rotator as get_gemini_pipeline_rotator

    rotator = get_gemini_pipeline_rotator("outreach")
    key_index, api_key = rotator.get_available_key()

    tone_map = {
        "professional": "formal and professional",
        "friendly": "warm, friendly, and approachable",
        "direct": "direct and concise â€” no fluff",
        "conversational": "conversational, as if from one human to another",
    }
    tone = tone_map.get(campaign_ctx.get("tone", "professional"), "professional and warm")

    first_name = (
        lead.get("first_name")
        or (lead.get("name") or "").split()[0]
        or "there"
    )

    prompt = f"""You are a B2B cold email copywriter specialising in market research and data services.

Write a UNIQUE, PERSONALISED cold email for Step {step_number}.

--- ABOUT OUR BUSINESS ---
Company: {business_label}
Value proposition: {campaign_ctx.get("value_proposition", "")}
Ideal customer: {campaign_ctx.get("target_customer", "")}
Sender: {sender_name} ({campaign_ctx.get("sender_title", "")})
Tone: {tone}

--- ABOUT THIS SPECIFIC LEAD ---
Name: {lead.get("name") or first_name}
First name: {first_name}
Title: {lead.get("title") or ""}
Company: {lead.get("company_name") or ""}
Industry: {lead.get("company_industry") or ""}
Seniority: {lead.get("seniority_level") or ""}
Location: {lead.get("location") or ""}

--- STEP INSTRUCTIONS ---
{_STEP_INSTRUCTIONS.get(step_number, _STEP_INSTRUCTIONS[1])}

--- OUTPUT FORMAT (strictly follow this, nothing else) ---
SUBJECT: <the subject line>

BODY:
<the email body â€” plain paragraphs, no HTML tags, no signature block>

Rules:
- Address the recipient by their first name: {first_name}
- Reference their company or industry naturally (do NOT invent facts)
- Do NOT include a signature â€” the system appends one
- Do NOT use markdown, bullet points, or HTML tags
- Keep the tone {tone}
"""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(prompt)
    rotator.log_request(key_index, 0, "outreach_email_gen", success=True)

    raw = response.text.strip()
    subject = ""
    body = ""
    if "SUBJECT:" in raw:
        parts = raw.split("BODY:", 1)
        subject = parts[0].replace("SUBJECT:", "").strip()
        body = parts[1].strip() if len(parts) > 1 else raw
    else:
        lines = raw.splitlines()
        subject = lines[0].strip()
        body = "\n".join(lines[1:]).strip()

    # Convert plain text body to safe HTML (preserve paragraphs)
    import html as _html
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    body_html = "".join(f"<p>{_html.escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs)

    return subject, body_html


def _send_via_gmail_api(
    from_email: str,
    to_email: str,
    subject: str,
    body_html: str,
    display_name: str,
    attachments: Optional[List[Dict]] = None,
) -> dict:
    """
    Send one email via GmailWorkspaceService (service account / domain-wide delegation).
    Returns dict with 'message_id' and 'thread_id'. Raises on failure.
    """
    actual_to = to_email
    if _OUTREACH_TEST_OVERRIDE_EMAIL:
        logger.info(
            f"[OUTREACH TEST MODE] Redirecting {to_email} â†’ {_OUTREACH_TEST_OVERRIDE_EMAIL}"
        )
        actual_to = _OUTREACH_TEST_OVERRIDE_EMAIL

    svc = _get_gmail_workspace_service()
    signature_html = _get_gmail_signature(from_email)

    # Convert stored attachment docs to the format send_email expects
    gmail_attachments = None
    if attachments:
        import base64 as _b64
        gmail_attachments = []
        for att in attachments:
            content_b64 = att.get("content_b64")
            if not content_b64:
                continue
            gmail_attachments.append({
                "filename": att.get("filename", "attachment"),
                "content": content_b64,  # already base64
                "mime_type": att.get("mime_type", "application/octet-stream"),
            })

    result = svc.send_email(
        from_email=from_email,
        to=[actual_to],
        subject=subject,
        body_html=body_html,
        signature_html=signature_html,
        attachments=gmail_attachments if gmail_attachments else None,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Gmail API send failed")
    return {
        "message_id": result.get("message_id") or "",
        "thread_id": result.get("thread_id") or "",
    }


def _send_via_smtp(
    smtp_mailbox: Dict[str, Any],
    to_email: str,
    subject: str,
    body_html: str,
    display_name: str,
    attachments: Optional[List[Dict]] = None,
) -> dict:
    """Send one email via SMTP mailbox configuration from outreach_mailboxes."""
    import base64 as _b64
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formataddr

    actual_to = to_email
    if _OUTREACH_TEST_OVERRIDE_EMAIL:
        logger.info(
            f"[OUTREACH TEST MODE] Redirecting {to_email} â†’ {_OUTREACH_TEST_OVERRIDE_EMAIL}"
        )
        actual_to = _OUTREACH_TEST_OVERRIDE_EMAIL

    host = smtp_mailbox.get("smtp_host")
    port = int(smtp_mailbox.get("smtp_port") or 587)
    username = smtp_mailbox.get("smtp_username")
    password = smtp_mailbox.get("smtp_password")
    from_email = (
        smtp_mailbox.get("email_address")
        or smtp_mailbox.get("email")
        or username
    )

    if not host or not username or not password or not from_email:
        raise RuntimeError("SMTP mailbox configuration is incomplete")

    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr((display_name, from_email))
    msg["To"] = actual_to
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    plain_body = _re.sub(r"<[^>]+>", "", body_html or "")
    alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    alt.attach(MIMEText(body_html or "", "html", "utf-8"))
    msg.attach(alt)

    for att in attachments or []:
        content_b64 = att.get("content_b64")
        if not content_b64:
            continue
        try:
            payload = _b64.b64decode(content_b64)
        except Exception:
            continue
        part = MIMEApplication(payload)
        filename = att.get("filename") or "attachment"
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    with smtplib.SMTP(host, port, timeout=30) as server:
        use_tls_raw = smtp_mailbox.get("smtp_use_tls", True)
        if isinstance(use_tls_raw, str):
            use_tls = use_tls_raw.strip().lower() in {"1", "true", "yes", "on"}
        else:
            use_tls = bool(use_tls_raw)
        if use_tls:
            server.starttls()
        server.login(username, password)
        server.sendmail(from_email, [actual_to], msg.as_string())

    return {"message_id": "", "thread_id": ""}


def _process_one_outreach_lead(db, lead_record: dict) -> bool:
    """
    For one outreach_leads_v2 record:
      1. Verify campaign is active
      2. Check suppression
      3. Use the pre-written step template and replace placeholders with lead data
        4. Send via resolved mailbox transport (Gmail API or SMTP)
      5. Record the send and advance workflow state
    Returns True on success, False on any error (does not raise).
    """
    try:
        campaign = db["outreach_campaigns_v2"].find_one(
            {"campaign_id": lead_record["campaign_id"]}
        )
        if not campaign or not campaign.get("is_active"):
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {"workflow_status": "paused", "updated_at": datetime.utcnow()}}
            )
            return False

        steps_sent = lead_record.get("current_step", 0)
        next_step_number = steps_sent + 1  # 1-indexed

        # Check that this step exists in the sequence (we have 4 steps: 1â€“4)
        if next_step_number > len(SEQUENCE_STEPS):
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {"workflow_status": "completed", "updated_at": datetime.utcnow()}}
            )
            return True

        # Check suppression
        email = (lead_record.get("email") or "").lower().strip()
        if not email or db["outreach_bounce_suppression"].find_one({"email": email}):
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {"workflow_status": "suppressed", "updated_at": datetime.utcnow()}}
            )
            return False

        # Reject emails that are not RFC-valid (non-ASCII, apostrophes in domain, etc.)
        import re as _re
        _EMAIL_RE = _re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
        _is_ascii = True
        try:
            email.encode("ascii")
        except UnicodeEncodeError:
            _is_ascii = False
        if not _is_ascii or not _EMAIL_RE.match(email):
            logger.warning(f"[Outreach] Skipping invalid email address: {email}")
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {
                    "workflow_status": "bounced",
                    "last_send_error": "Invalid email address format",
                    "last_send_error_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }}
            )
            return False

        business = campaign.get("business", "sfw")
        sender_config = _resolve_sender_for_campaign(db, campaign)
        if not sender_config:
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {
                    "workflow_status": "error",
                    "last_send_error": f"No active mailbox available for business '{business}'",
                    "last_send_error_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }}
            )
            return False

        from_email = sender_config["from_email"]
        display_name = sender_config["display_name"]
        sender_transport = sender_config["transport"]
        smtp_mailbox = sender_config.get("mailbox_doc") or {}
        business_label = BUSINESS_LABEL.get(business, business)
        campaign_ctx = campaign.get("business_context") or {}

        # Daily send cap per mailbox (SES exempt)
        if _sender_at_daily_limit(db, from_email):
            tomorrow = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {"next_send_at": tomorrow, "updated_at": datetime.utcnow()}}
            )
            logger.info(f"[Outreach] Daily limit reached for {from_email} â€” rescheduling {email} to tomorrow")
            return False

        # â”€â”€ Pre-send bounce-risk guard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # For pattern-derived / guessed emails, check the domain's bounce history.
        # Blacklisted domains are skipped entirely; high-risk domains require a
        # minimum confidence of 0.55 before we proceed.
        email_source_flag = lead_record.get("email_source", "")
        if not email_source_flag and lead_record.get("lead_id"):
            # Backward compatibility: older outreach_leads_v2 rows may not carry
            # email_source yet, so pull it from the canonical leads collection.
            try:
                canonical = get_leads_db()["leads_enriched"].find_one(
                    {"_id": ObjectId(lead_record.get("lead_id"))},
                    {"email_source": 1},
                )
                email_source_flag = (canonical or {}).get("email_source", "")
            except Exception:
                email_source_flag = ""
        if email_source_flag in ("pattern_derived", "pattern_applied", "guessed", "pattern_guess"):
            try:
                from leads.email_pattern_system import get_pattern_system as _get_ps
                _send_domain = email.split("@")[1] if "@" in email else ""
                if _send_domain:
                    _risk = _get_ps().get_domain_risk(_send_domain)
                    if _risk.get("pattern_blacklisted"):
                        skip_reason = (
                            f"Domain '{_send_domain}' is blacklisted (bounce rate "
                            f"{_risk['bounce_rate']:.0%} > 60%). "
                            "No more pattern-derived emails for this domain."
                        )
                        logger.warning(f"[Outreach] Skipping {email}: {skip_reason}")
                        db["outreach_leads_v2"].update_one(
                            {"_id": lead_record["_id"]},
                            {"$set": {
                                "workflow_status": "skipped_high_bounce_risk",
                                "last_send_error": skip_reason[:300],
                                "last_send_error_at": datetime.utcnow(),
                                "updated_at": datetime.utcnow(),
                            }},
                        )
                        return False
                    if _risk.get("high_bounce_risk") and _risk.get("confidence", 1.0) < 0.55:
                        skip_reason = (
                            f"Domain '{_send_domain}' has high bounce risk "
                            f"(rate {_risk['bounce_rate']:.0%}, confidence {_risk['confidence']:.2f}). "
                            "Skipping until pattern is reinforced by a successful send."
                        )
                        logger.warning(f"[Outreach] Skipping {email}: {skip_reason}")
                        db["outreach_leads_v2"].update_one(
                            {"_id": lead_record["_id"]},
                            {"$set": {
                                "workflow_status": "skipped_high_bounce_risk",
                                "last_send_error": skip_reason[:300],
                                "last_send_error_at": datetime.utcnow(),
                                "updated_at": datetime.utcnow(),
                            }},
                        )
                        return False
            except Exception as _guard_err:
                logger.debug(f"[Outreach] bounce-risk guard skipped: {_guard_err}")

        # Use the pre-written step template and replace placeholders with lead data
        step_template = next(
            (s for s in campaign.get("steps", []) if s.get("step_number") == next_step_number),
            None,
        )
        if not step_template or (not step_template.get("subject") and not step_template.get("body_html")):
            logger.warning(
                f"[Outreach] No template content for step {next_step_number} "
                f"in campaign {campaign['campaign_id']} â€” skipping {email}"
            )
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {
                    "workflow_status": "error",
                    "last_send_error": f"Step {next_step_number} has no template content",
                    "last_send_error_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }}
            )
            return False

        first_name = (
            lead_record.get("first_name")
            or (lead_record.get("name") or "").split()[0]
            or "there"
        )
        placeholders = {
            "{{first_name}}": first_name,
            "{{last_name}}": lead_record.get("last_name") or "",
            "{{name}}": lead_record.get("name") or first_name,
            "{{company}}": lead_record.get("company_name") or "",
            "{{title}}": lead_record.get("title") or "",
            "{{industry}}": lead_record.get("company_industry") or "",
            "{{sender_name}}": display_name,
        }

        def _replace_tokens(text: str) -> str:
            for token, val in placeholders.items():
                text = text.replace(token, val)
            return text

        subject = _replace_tokens(step_template.get("subject", "(no subject)"))
        body_html = _replace_tokens(step_template.get("body_html", ""))

        # Collect step attachments (CSV files, etc.) if any
        step_attachments = step_template.get("attachments") or []

        # Generate send_id BEFORE sending so the tracking pixel can embed it
        send_id = str(uuid.uuid4())

        # Inject open-tracking pixel + rewrite links for click tracking
        if TRACKING_BASE_URL:
            body_html = _inject_open_tracking(body_html, send_id, TRACKING_BASE_URL)
            body_html = _rewrite_links_for_click_tracking(body_html, send_id, TRACKING_BASE_URL)

        if sender_transport == "gmail":
            send_result = _send_via_gmail_api(
                from_email, email, subject, body_html, display_name,
                attachments=step_attachments if step_attachments else None,
            )
        elif sender_transport == "smtp":
            send_result = _send_via_smtp(
                smtp_mailbox,
                email,
                subject,
                body_html,
                display_name,
                attachments=step_attachments if step_attachments else None,
            )
        else:
            raise RuntimeError(f"Unsupported sender transport: {sender_transport}")
        gmail_message_id = send_result["message_id"]
        gmail_thread_id = send_result["thread_id"]

        now = datetime.utcnow()

        # Record send
        db["outreach_sends_v2"].insert_one({
            "send_id": send_id,
            "lead_id": lead_record.get("lead_id"),
            "campaign_id": lead_record["campaign_id"],
            "outreach_lead_id": str(lead_record["_id"]),
            "email": email,
            "from_email": from_email,
            "workflow_step": steps_sent,   # 0-indexed for stats aggregation
            "subject": subject,
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": gmail_thread_id,
            "status": "sent",
            "reply_received": False,
            "open_count": 0,
            "click_count": 0,
            "clicks": [],
            "unsubscribed": False,
            "sent_at": now,
            "created_at": now,
        })

        # Feedback loop: reinforce email pattern confidence for this domain
        # Only meaningful for pattern-derived emails; harmless for others.
        try:
            from leads.email_pattern_system import get_pattern_system as _get_ps
            _domain = email.split("@")[1] if "@" in email else ""
            if _domain:
                _get_ps().record_send_success(
                    domain=_domain,
                    email=email,
                    first_name=lead_record.get("first_name", ""),
                    last_name=lead_record.get("last_name", ""),
                )
        except Exception as _ps_err:
            logger.debug(f"[PatternFeedback] send_success hook failed: {_ps_err}")

        # Advance workflow: compute next send date from SEQUENCE_STEPS offsets
        if next_step_number < len(SEQUENCE_STEPS):
            days_to_next = SEQUENCE_STEPS[next_step_number] - SEQUENCE_STEPS[next_step_number - 1]
            next_send_at = now + timedelta(days=max(days_to_next, 1))
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {
                    "current_step": next_step_number,
                    "workflow_status": "in_sequence",
                    "next_send_at": next_send_at,
                    "last_sent_at": now,
                    "updated_at": now,
                }}
            )
        else:
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {
                    "current_step": next_step_number,
                    "workflow_status": "completed",
                    "last_sent_at": now,
                    "updated_at": now,
                }}
            )

        logger.info(
            f"[Outreach] Sent step {next_step_number} to {email} "
            f"from {from_email} (campaign {campaign['campaign_id']})"
        )
        return True

    except Exception as e:
        err_str = str(e)
        logger.error(
            f"[Outreach] Failed to process {lead_record.get('email')}: {e}",
            exc_info=True
        )
        _from = locals().get("from_email", "")
        # On Gmail 429, set mailbox cooldown, push lead out, and RE-RAISE
        # so the outer loop can skip remaining leads for this sender
        if '429' in err_str and 'rate' in err_str.lower():
            if _from:
                _set_mailbox_cooldown(_from, err_str)
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {
                    "next_send_at": datetime.utcnow() + timedelta(seconds=_COOLDOWN_SECONDS),
                    "last_send_error": err_str[:300],
                    "last_send_error_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }}
            )
            raise  # Re-raise so outer send loop can track failed senders
        else:
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {
                    "last_send_error": err_str[:300],
                    "last_send_error_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }}
            )
        return False


def process_due_outreach_sends() -> dict:
    """
    Called by APScheduler every 60 seconds.
    Round-robins across active campaigns, picking up to 2 leads per campaign
    per cycle (max 6 total). Respects per-mailbox 429 cooldowns.
    Uses the pre-written step templates (no AI generation).
    Returns a summary dict.
    """
    try:
        global _LAST_ENROLL_SYNC_AT
        now = datetime.utcnow()
        db = get_db()

        # Periodic catch-up enrollment keeps active campaigns synced with new AI leads.
        if (
            _LAST_ENROLL_SYNC_AT is None
            or (now - _LAST_ENROLL_SYNC_AT).total_seconds() >= _ENROLL_SYNC_INTERVAL_SECONDS
        ):
            try:
                _sync_active_campaign_enrollment(db)
                _LAST_ENROLL_SYNC_AT = now
            except Exception as enroll_sync_err:
                logger.error(f"[Outreach] Enrollment catch-up sync failed: {enroll_sync_err}")

        # Get active campaigns (campaigns use is_active flag, not status)
        active_campaigns = list(db["outreach_campaigns_v2"].find(
            {"is_active": True},
            {"campaign_id": 1, "business": 1, "mailbox_ids": 1}
        ))

        if not active_campaigns:
            return {"processed": 0, "sent": 0, "skipped": 0}

        # Build list of leads round-robin: up to 2 per campaign
        due = []
        cooldown_skipped = []
        for camp in active_campaigns:
            cid = camp.get("campaign_id")
            business = camp.get("business", "sfw")
            sender_cfg = _resolve_sender_for_campaign(db, camp)
            if not sender_cfg:
                # Determine why sender resolution failed to surface a helpful error
                fallback_email = _BUSINESS_SENDER.get(business, "")
                gmail_db = _get_gmail_db()
                ws_active = False
                if gmail_db is not None and fallback_email:
                    ws_active = bool(gmail_db["workspace_mailboxes"].find_one(
                        {"email": fallback_email, "is_active": True}
                    ))
                outreach_mb_count = db["outreach_mailboxes"].count_documents(
                    {"business": business, "is_active": True}
                )
                reason = (
                    f"No active mailbox for campaign {cid} (business={business}). "
                    f"outreach_mailboxes active={outreach_mb_count}, "
                    f"workspace_mailbox '{fallback_email}' active={ws_active}. "
                    "Configure an active mailbox in Settings > Mailboxes."
                )
                logger.warning(f"[Outreach] {reason}")
                # Stamp due leads with this error so it surfaces in the UI
                db["outreach_leads_v2"].update_many(
                    {
                        "campaign_id": cid,
                        "workflow_status": {"$in": ["not_started", "pending_scheduled", "in_sequence"]},
                        "next_send_at": {"$lte": now},
                    },
                    {"$set": {
                        "last_send_error": reason,
                        "last_send_attempt_at": now,
                    }},
                )
                continue
            sender = sender_cfg.get("from_email") if sender_cfg else ""

            # Skip campaigns whose mailbox is in 429 cooldown
            if sender and _is_mailbox_in_cooldown(sender):
                cooldown_skipped.append(camp.get("business", "sfw"))
                continue

            camp_due = list(db["outreach_leads_v2"].find({
                "campaign_id": cid,
                "workflow_status": {"$in": ["not_started", "pending_scheduled", "in_sequence"]},
                "next_send_at": {"$lte": now},
            }).limit(2))
            due.extend(camp_due)

        if cooldown_skipped:
            logger.info(f"[Outreach] Skipped campaigns in 429 cooldown: {cooldown_skipped}")

        if not due:
            return {"processed": 0, "sent": 0, "skipped": 0}

        sent = 0
        skipped = 0
        failed_senders = set()  # Track senders that fail in this cycle
        for record in due:
            # If this record's business sender already failed this cycle, skip it
            camp = db["outreach_campaigns_v2"].find_one(
                {"campaign_id": record.get("campaign_id")},
                {"business": 1, "mailbox_ids": 1}
            )
            sender = ""
            if camp:
                sender_cfg = _resolve_sender_for_campaign(db, camp)
                sender = sender_cfg.get("from_email") if sender_cfg else ""
                if sender in failed_senders:
                    skipped += 1
                    continue

            try:
                ok = _process_one_outreach_lead(db, record)
                if ok:
                    sent += 1
                else:
                    skipped += 1
            except Exception as loop_err:
                logger.error(f"[Outreach] Error processing lead {record.get('email')}: {loop_err}")
                skipped += 1
                # If 429, mark this sender as failed for the rest of the cycle
                if '429' in str(loop_err):
                    if sender:
                        failed_senders.add(sender)

        if sent > 0 or skipped > 0:
            logger.info(f"[Outreach] Cycle complete: sent={sent} skipped={skipped}")

        return {"processed": len(due), "sent": sent, "skipped": skipped}

    except Exception as e:
        logger.error(f"[Outreach] process_due_outreach_sends error: {e}", exc_info=True)
        return {"processed": 0, "sent": 0, "skipped": 0, "error": str(e)}


@router.post("/process-due")
def trigger_process_due():
    """
    Manually trigger one cycle of the outreach send processor.
    Normally runs automatically every 60 seconds via APScheduler.
    """
    result = process_due_outreach_sends()
    return {"ok": True, **result}


@router.get("/sender-status")
def get_sender_status():
    """
    GET /cold-outreach/sender-status
    Diagnostic endpoint: for each active campaign, shows whether a sender
    mailbox can be resolved and WHY it fails if not.
    """
    db = get_db()
    gmail_db = _get_gmail_db()

    campaigns = list(db["outreach_campaigns_v2"].find(
        {},
        {"campaign_id": 1, "business": 1, "mailbox_ids": 1, "is_active": 1, "name": 1}
    ))

    results = []
    for camp in campaigns:
        cid = camp.get("campaign_id")
        business = camp.get("business", "sfw")
        fallback_email = _BUSINESS_SENDER.get(business, "")

        sender_cfg = _resolve_sender_for_campaign(db, camp)

        # Gather diagnostic details
        outreach_mbs = list(db["outreach_mailboxes"].find(
            {"business": business},
            {"email_address": 1, "is_active": 1, "provider": 1, "_id": 0}
        ))
        ws_mailboxes = []
        if gmail_db is not None and fallback_email:
            ws_doc = gmail_db["workspace_mailboxes"].find_one(
                {"email": fallback_email},
                {"email": 1, "is_active": 1, "display_name": 1, "_id": 0}
            )
            if ws_doc:
                ws_mailboxes.append(ws_doc)

        due_count = db["outreach_leads_v2"].count_documents({
            "campaign_id": cid,
            "workflow_status": {"$in": ["not_started", "pending_scheduled", "in_sequence"]},
        })
        error_count = db["outreach_leads_v2"].count_documents({
            "campaign_id": cid,
            "workflow_status": "error",
        })

        results.append({
            "campaign_id": cid,
            "campaign_name": camp.get("name", cid),
            "business": business,
            "is_active": camp.get("is_active", False),
            "sender_resolved": sender_cfg is not None,
            "resolved_sender": sender_cfg.get("from_email") if sender_cfg else None,
            "transport": sender_cfg.get("transport") if sender_cfg else None,
            "outreach_mailboxes": outreach_mbs,
            "workspace_mailboxes_checked": ws_mailboxes,
            "fallback_email": fallback_email,
            "cooldown_active": _is_mailbox_in_cooldown(sender_cfg.get("from_email", "")) if sender_cfg else False,
            "due_leads": due_count,
            "error_leads": error_count,
            "diagnosis": (
                "OK â€” sender resolved" if sender_cfg
                else (
                    f"FAIL â€” no active outreach_mailboxes for business='{business}' "
                    f"and workspace_mailbox '{fallback_email}' "
                    f"{'exists but is_active=False' if ws_mailboxes else 'NOT FOUND in workspace_mailboxes'}. "
                    "Fix: add an active mailbox in Settings > Mailboxes, or "
                    f"ensure {fallback_email} is active in workspace_mailboxes."
                )
            ),
        })

    return {
        "campaigns": results,
        "workspace_mailboxes_total": (
            gmail_db["workspace_mailboxes"].count_documents({}) if gmail_db is not None else 0
        ),
        "outreach_mailboxes_total": db["outreach_mailboxes"].count_documents({}),
        "businesses_configured": list(_BUSINESS_SENDER.keys()),
    }



import re as _re

_BOUNCE_FROM_PATTERN = _re.compile(
    r"mailer-daemon|postmaster|mail[\s_-]?delivery|bounce",
    _re.IGNORECASE,
)
_BOUNCE_SUBJECT_PATTERN = _re.compile(
    r"undeliverable|delivery.*(?:fail|status|notification)|returned.*mail|"
    r"mail.*(?:delivery|undeliverable)|permanent.*failure|"
    r"undelivered\s+mail",
    _re.IGNORECASE,
)
_OOO_SUBJECT_PATTERN = _re.compile(
    r"out\s+of\s+(?:the\s+)?office|automatic\s+reply|auto[\s-]?reply|"
    r"away\s+from\s+(?:the\s+)?office|on\s+(?:annual\s+)?leave|"
    r"(?:i\s+am|i'm)\s+(?:currently\s+)?(?:out|away|on\s+vacation)",
    _re.IGNORECASE,
)

# Outreach sender emails (used to scope gmail metadata queries)
_OUTREACH_SENDERS = list(_BUSINESS_SENDER.values())


def _extract_bounced_recipient(body_text: str) -> Optional[str]:
    """Try to extract the original recipient email from a bounce-back message body."""
    if not body_text:
        return None
    # Common patterns in DSN bounce messages
    patterns = [
        _re.compile(r"(?:original|final)[\s-]*recipient[:\s]*<?([^\s<>@]+@[^\s<>]+)>?", _re.I),
        _re.compile(r"(?:delivery|message).*?to\s+<?([^\s<>@]+@[^\s<>]+)>?\s+(?:has\s+)?(?:failed|was\s+rejected)", _re.I),
        _re.compile(r"<?([^\s<>@]+@[^\s<>]+)>?\s+(?:was\s+)?(?:not\s+)?(?:delivered|rejected|undeliverable)", _re.I),
        _re.compile(r"address[:\s]*<?([^\s<>@]+@[^\s<>]+)>?", _re.I),
    ]
    for pat in patterns:
        m = pat.search(body_text[:3000])
        if m:
            candidate = m.group(1).lower().strip().rstrip(".")
            # Don't return the sender's own email
            if candidate not in _OUTREACH_SENDERS:
                return candidate
    # Fallback: look for any email address that's in our outreach leads
    emails_found = _re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", body_text[:3000])
    for e in emails_found:
        e_lower = e.lower()
        if e_lower not in _OUTREACH_SENDERS and "mailer-daemon" not in e_lower and "postmaster" not in e_lower:
            return e_lower
    return None


def process_outreach_bounces_and_replies() -> dict:
    """
    Called by APScheduler every 5 minutes.
    Scans gmail email_metadata for bounce-back emails and replies to outreach emails.

    Bounce detection:
      - Matches inbound emails from mailer-daemon/postmaster with bounce subjects
      - Extracts the original recipient from the bounce body
      - Marks the outreach send as bounced, the lead as bounced
      - Adds the email to outreach_bounce_suppression

    Reply detection:
      - Matches inbound emails by gmail_thread_id to outreach sends
      - Updates outreach_sends_v2 with reply_received=True
      - Updates outreach_leads_v2 workflow_status to "replied"

    OOO detection:
      - Detects out-of-office auto-replies by subject pattern
      - Marks sends with ooo_received=True (does not stop sequence)
    """
    try:
        db = get_db()
        gmail_db = _get_gmail_db()
        if gmail_db is None:
            return {"error": "gmail_db not available"}

        # Get outreach mailbox IDs
        outreach_mailboxes = list(gmail_db["workspace_mailboxes"].find(
            {"email": {"$in": _OUTREACH_SENDERS}},
            {"_id": 1, "email": 1}
        ))
        if not outreach_mailboxes:
            return {"error": "no outreach mailboxes found"}

        mailbox_ids = [str(m["_id"]) for m in outreach_mailboxes]
        mailbox_email_map = {str(m["_id"]): m["email"] for m in outreach_mailboxes}

        # Find the last scan timestamp (or default to 6 hours ago)
        scan_state = db["outreach_scan_state"].find_one({"_id": "bounce_reply_scanner"})
        last_scan = (
            scan_state["last_scan_at"]
            if scan_state
            else datetime.utcnow() - timedelta(hours=6)
        )

        # Query inbound emails synced since last scan for outreach mailboxes
        inbound_cursor = gmail_db["email_metadata"].find(
            {
                "mailbox_id": {"$in": mailbox_ids},
                "direction": "inbound",
                "synced_at": {"$gt": last_scan},
            },
            {
                "gmail_message_id": 1,
                "gmail_thread_id": 1,
                "mailbox_id": 1,
                "from_email": 1,
                "to_emails": 1,
                "subject": 1,
                "body_plain": 1,
                "snippet": 1,
                "synced_at": 1,
            }
        ).sort("synced_at", 1).limit(200)

        inbound_emails = list(inbound_cursor)
        if not inbound_emails:
            # Update scan timestamp even if nothing found
            db["outreach_scan_state"].update_one(
                {"_id": "bounce_reply_scanner"},
                {"$set": {"last_scan_at": datetime.utcnow()}},
                upsert=True,
            )
            return {"processed": 0, "bounces": 0, "replies": 0, "ooo": 0}

        bounces = 0
        replies = 0
        ooo_count = 0
        now = datetime.utcnow()

        for email_doc in inbound_emails:
            from_email = (email_doc.get("from_email") or "").lower()
            subject = email_doc.get("subject") or ""
            body_text = email_doc.get("body_plain") or email_doc.get("snippet") or ""
            thread_id = email_doc.get("gmail_thread_id") or ""
            msg_id = email_doc.get("gmail_message_id") or ""

            is_bounce = bool(
                _BOUNCE_FROM_PATTERN.search(from_email)
                or _BOUNCE_SUBJECT_PATTERN.search(subject)
            )
            is_ooo = bool(_OOO_SUBJECT_PATTERN.search(subject)) and not is_bounce

            if is_bounce:
                # Extract the original recipient from the bounce body
                recipient = _extract_bounced_recipient(body_text)
                if not recipient:
                    # Try to find the recipient via gmail_thread_id â†’ outreach_sends_v2
                    if thread_id:
                        send = db["outreach_sends_v2"].find_one(
                            {"gmail_thread_id": thread_id},
                            {"email": 1}
                        )
                        if send:
                            recipient = send["email"]

                if recipient:
                    recipient = recipient.lower().strip()
                    # 1. Add to suppression list
                    db["outreach_bounce_suppression"].update_one(
                        {"email": recipient},
                        {"$set": {
                            "email": recipient,
                            "bounced_at": now,
                            "reason": "gmail_bounce",
                            "source": "bounce_scanner",
                            "bounce_subject": subject[:200],
                            "created_at": now,
                        }},
                        upsert=True,
                    )
                    # Feedback loop: penalise pattern for this domain
                    try:
                        from leads.email_pattern_system import get_pattern_system as _get_ps
                        _bounce_domain = recipient.split("@")[1] if "@" in recipient else ""
                        if _bounce_domain:
                            _get_ps().record_bounce(domain=_bounce_domain, email=recipient)
                    except Exception as _ps_err:
                        logger.debug(f"[PatternFeedback] record_bounce hook failed: {_ps_err}")
                    # 2. Mark all sends to this email as bounced
                    db["outreach_sends_v2"].update_many(
                        {"email": recipient, "status": "sent"},
                        {"$set": {"status": "bounced", "bounced_at": now}},
                    )
                    # 3. Mark the lead as bounced (stop further sends)
                    db["outreach_leads_v2"].update_many(
                        {"email": recipient, "workflow_status": {"$nin": ["bounced", "completed", "replied"]}},
                        {"$set": {
                            "workflow_status": "bounced",
                            "bounced_at": now,
                            "updated_at": now,
                        }},
                    )
                    # 4. Also update leads_enriched for global suppression
                    try:
                        leads_db = get_leads_db()
                        leads_db["leads_enriched"].update_many(
                            {"email": recipient},
                            {"$set": {
                                "email_status": "bounced",
                                "bounce_suppressed": True,
                                "bounced_at": now,
                            }},
                        )
                    except Exception:
                        pass

                    # â”€â”€ Bounce Recovery: attempt to find alternate email â”€â”€
                    # Find the outreach_leads_v2 record for this bounce and
                    # attempt recovery instead of simply suppressing forever.
                    try:
                        bounced_lead = db["outreach_leads_v2"].find_one(
                            {"email": recipient,
                             "workflow_status": "bounced"},
                            {"_id": 1}
                        )
                        if bounced_lead:
                            from leads.bounce_recovery import attempt_recovery as _bounce_recovery
                            recovery_result = _bounce_recovery(
                                str(bounced_lead["_id"]), recipient
                            )
                            if recovery_result.get("action") == "retry":
                                logger.info(
                                    f"[BounceRecovery] Lead {bounced_lead['_id']} â†’ "
                                    f"retry with {recovery_result['email']} "
                                    f"(method={recovery_result.get('method')})"
                                )
                            elif recovery_result.get("action") == "human_intervention":
                                logger.warning(
                                    f"[BounceRecovery] Lead {bounced_lead['_id']} â†’ "
                                    f"needs_human_intervention after all attempts"
                                )
                    except Exception as _br_err:
                        logger.debug(f"[BounceRecovery] Recovery hook failed: {_br_err}")

                    bounces += 1

            elif is_ooo:
                # OOO: match by thread_id to find the original send
                if thread_id:
                    send = db["outreach_sends_v2"].find_one(
                        {"gmail_thread_id": thread_id},
                        {"_id": 1, "email": 1}
                    )
                    if send:
                        db["outreach_sends_v2"].update_one(
                            {"_id": send["_id"]},
                            {"$set": {"ooo_received": True, "ooo_at": now}},
                        )
                        ooo_count += 1

            else:
                # Potential reply â€” match by gmail_thread_id
                if thread_id:
                    send = db["outreach_sends_v2"].find_one(
                        {"gmail_thread_id": thread_id},
                        {"_id": 1, "email": 1, "campaign_id": 1, "outreach_lead_id": 1}
                    )
                    if send:
                        # Mark send as replied
                        db["outreach_sends_v2"].update_one(
                            {"_id": send["_id"]},
                            {"$set": {
                                "reply_received": True,
                                "replied_at": now,
                                "reply_from": from_email,
                                "reply_subject": subject[:200],
                                "reply_snippet": (body_text or "")[:300],
                            }},
                        )
                        # Mark lead as replied (stops further sends in sequence)
                        outreach_lead = db["outreach_leads_v2"].find_one_and_update(
                            {"_id": ObjectId(send["outreach_lead_id"])},
                            {"$set": {
                                "workflow_status": "replied",
                                "replied_at": now,
                                "updated_at": now,
                            }},
                            return_document=True,
                        )

                        # Promote replied lead to the Leads module
                        # (upsert into leads_enriched with source="outreach_reply")
                        if outreach_lead:
                            try:
                                leads_db = get_leads_db()
                                reply_email = (outreach_lead.get("email") or "").lower().strip()
                                if reply_email:
                                    leads_db["leads_enriched"].update_one(
                                        {"email": reply_email},
                                        {"$set": {
                                            "source": "outreach_reply",
                                            "stage": "new",
                                            "outreach_replied_at": now,
                                            "outreach_campaign_id": send.get("campaign_id"),
                                            "reply_subject": subject[:200],
                                            "reply_snippet": (body_text or "")[:300],
                                            "updated_at": now,
                                        }},
                                    )
                            except Exception:
                                pass

                        replies += 1

        # Update scan watermark
        last_synced = max(
            (e.get("synced_at") for e in inbound_emails if e.get("synced_at")),
            default=now,
        )
        db["outreach_scan_state"].update_one(
            {"_id": "bounce_reply_scanner"},
            {"$set": {"last_scan_at": last_synced}},
            upsert=True,
        )

        if bounces > 0 or replies > 0 or ooo_count > 0:
            logger.info(
                f"[Outreach Scanner] Processed {len(inbound_emails)} inbound emails: "
                f"bounces={bounces}, replies={replies}, ooo={ooo_count}"
            )

        # â”€â”€ 7-day delivery confirmation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Emails that were sent â‰¥7 days ago with no bounce are promoted to
        # "Delivered" status in leads_enriched â€” the strongest trust signal for
        # a pattern-derived address.
        try:
            cutoff_7d = datetime.utcnow() - timedelta(days=7)
            delivered_emails = list(db["outreach_sends_v2"].distinct(
                "email",
                {"status": "sent", "sent_at": {"$lt": cutoff_7d}},
            ))
            if delivered_emails:
                leads_db = get_leads_db()
                updated = leads_db["leads_enriched"].update_many(
                    {
                        "email": {"$in": delivered_emails},
                        "email_status": {"$nin": ["bounced", "Delivered"]},
                    },
                    {"$set": {
                        "email_status": "Delivered",
                        "delivery_confirmed_at": datetime.utcnow(),
                    }},
                )
                if updated.modified_count:
                    logger.info(
                        f"[Outreach Scanner] Promoted {updated.modified_count} emails "
                        f"to 'Delivered' status (7-day no-bounce window)"
                    )
        except Exception as _del_err:
            logger.debug(f"[Outreach Scanner] 7-day delivery promotion failed: {_del_err}")

        return {
            "processed": len(inbound_emails),
            "bounces": bounces,
            "replies": replies,
            "ooo": ooo_count,
        }

    except Exception as e:
        logger.error(f"[Outreach Scanner] Error: {e}", exc_info=True)
        return {"error": str(e)}


@router.post("/scan-bounces-replies")
def trigger_bounce_reply_scan():
    """Manually trigger one cycle of the bounce & reply scanner."""
    result = process_outreach_bounces_and_replies()
    return {"ok": True, **result}


@router.get("/campaigns/{campaign_id}/leads-by-status")
def get_leads_by_status(
    campaign_id: str,
    status: str = Query("all", description="Filter: all|opened|not_opened|bounced|replied|sent"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """
    GET /api/cold-outreach/campaigns/{campaign_id}/leads-by-status
    Returns outreach sends bucketed by email status:
      - sent:       all sent (excluding bounced)
      - opened:     open_count > 0
      - not_opened: open_count == 0 and status != 'bounced'
      - bounced:    status == 'bounced'
      - replied:    reply_received == True
    """
    db = get_db()
    sends_col = db["outreach_sends_v2"]

    query: Dict[str, Any] = {"campaign_id": campaign_id}

    if status == "opened":
        query["open_count"] = {"$gt": 0}
        query["status"] = {"$ne": "bounced"}
    elif status == "not_opened":
        query["$or"] = [{"open_count": 0}, {"open_count": {"$exists": False}}]
        query["status"] = {"$ne": "bounced"}
        query["reply_received"] = {"$ne": True}
    elif status == "bounced":
        query["status"] = "bounced"
    elif status == "replied":
        query["reply_received"] = True
    elif status == "sent":
        query["status"] = {"$ne": "bounced"}
    # else "all" â€” no extra filter

    total = sends_col.count_documents(query)
    skip = (page - 1) * limit
    sends = list(
        sends_col.find(query, {
            "send_id": 1, "email": 1, "from_email": 1,
            "workflow_step": 1, "subject": 1, "status": 1,
            "open_count": 1, "click_count": 1,
            "reply_received": 1, "replied_at": 1,
            "reply_from": 1, "reply_subject": 1, "reply_snippet": 1,
            "last_opened_at": 1, "bounced_at": 1,
            "created_at": 1,
        })
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    for s in sends:
        s["_id"] = str(s["_id"])

    # Quick summary counts for header badges
    summary = {
        "total_sent": sends_col.count_documents({"campaign_id": campaign_id}),
        "opened": sends_col.count_documents({"campaign_id": campaign_id, "open_count": {"$gt": 0}}),
        "bounced": sends_col.count_documents({"campaign_id": campaign_id, "status": "bounced"}),
        "replied": sends_col.count_documents({"campaign_id": campaign_id, "reply_received": True}),
    }
    summary["not_opened"] = summary["total_sent"] - summary["opened"] - summary["bounced"]

    return {
        "sends": sends,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "summary": summary,
    }

