"""
Cold Outreach Router
====================

Campaign management API for 3-business cold outreach system.

Baskets:
  A → Survey Fieldwork   (indira@surveyfieldwork.com)
  B → Cogentix Research  (meera@cogentixresearch.com)
  C → BIMwave            (susanta@bimwaveconsultants.com)
  D → Dual Fit           (all 3 businesses, score-ordered, 21-day gap between each)
  E → Nurture            (excluded — no outreach)

Collections used:
  outreach_campaigns_v2        — campaign definitions + step templates
  outreach_mailboxes           — SMTP mailbox records
  outreach_leads_v2            — enrolled leads + workflow state
  outreach_sends_v2            — per-send records (stats)
  outreach_bounce_suppression  — global bounce suppression list
  leads_enriched               — source of truth for leads to enroll
"""

import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, EmailStr
from pymongo import MongoClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cold-outreach", tags=["Cold Outreach"])

SEQUENCE_STEPS = [0, 3, 6, 11]   # Day offsets: Day 1, 4, 7, 12 (0-indexed)
DUAL_FIT_GAP_DAYS = 21           # Gap between sequences for Dual Fit leads
SEQUENCE_DURATION_DAYS = 12      # Last step offset → total sequence window

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


# ── DB connection ─────────────────────────────────────────────────────────────

def get_db():
    uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/"
    db_name = os.getenv("MONGO_DB_NAME") or "torpedo"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client[db_name]


def get_leads_db():
    """Return the email_automation database that holds leads_enriched."""
    uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client["email_automation"]


def _get_gmail_db():
    """Return the torpedo_gmail database that holds workspace_mailboxes."""
    try:
        uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/"
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        return client["torpedo_gmail"]
    except Exception:
        return None


# ── Request/response models ────────────────────────────────────────────────────

class StepTemplate(BaseModel):
    step_number: int          # 1–4
    day_offset: int           # 0, 3, 6, 11
    subject: str
    body_html: str
    body_text: str = ""


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _oid(doc) -> str:
    return str(doc.get("_id", ""))


def _clean(doc: dict) -> dict:
    """Convert ObjectId → str for JSON serialisation."""
    doc["id"] = str(doc.pop("_id", ""))
    return doc


def _score_basket_for_lead(lead: dict, basket: str) -> float:
    """
    Return a rough affinity score (0–1) for a given basket using the lead's
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


# ══════════════════════════════════════════════════════════════════════════════
#  MAILBOX ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
#  CAMPAIGN ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

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
            "No business context saved yet — fill in the AI Context tab first so the AI knows what to write."
        )

    # Use pipeline 1 (outreach) for email drafting — keys 1, 2, 3
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
        "direct":       "direct and concise — no fluff",
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
  {{{{first_name}}}}   — recipient's first name
  {{{{company}}}}      — recipient's company name
  {{{{title}}}}        — recipient's job title
  {{{{industry}}}}     — recipient's industry

Use at least {{{{first_name}}}} and {{{{company}}}} in the body.
Do not invent specific company facts — keep it general enough to apply to any recipient.
Do not write a signature block — the system appends one automatically.
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
        raise HTTPException(400, "Step has no content yet — save the template first")

    # ── Find a mailbox to send from ──────────────────────────────────────────
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
            "No mailbox found — connect a Gmail account via the Mailboxes tab "
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
    body_text = body_html.replace("<br>", "\n").replace("<br/>", "\n")
    body_text = re.sub(r"<[^>]+>", "", body_text)

    # Build test banner
    test_banner = (
        f'<div style="background:#fef9c3;border:1px solid #fbbf24;padding:10px 14px;'
        f'border-radius:6px;margin-bottom:16px;font-family:sans-serif;font-size:13px;">'
        f'<strong>⚠️ TEST EMAIL</strong> — Step {step_number} of campaign '
        f'<em>{campaign.get("name", campaign_id)}</em>. '
        f'Tokens replaced with sample data.</div>'
    )

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = req.recipient_email
    msg["Subject"] = f"[TEST] {subject}"
    msg.attach(MIMEText(f"TEST EMAIL\n{body_text}", "plain"))
    msg.attach(MIMEText(test_banner + body_html, "html"))

    # ── Send via Gmail API or SMTP ───────────────────────────────────────────
    if gmail_mailbox:
        try:
            from app.services.gmail_workspace_service import GmailWorkspaceService
        except ImportError:
            from backend.app.services.gmail_workspace_service import GmailWorkspaceService

        mongo_uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/"
        ws = GmailWorkspaceService(mongo_uri=mongo_uri)
        ws.load_service_account()

        if not ws.is_configured():
            raise HTTPException(500, "Gmail service account not configured on server")

        try:
            service = ws._get_service(sender_email)
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


# ══════════════════════════════════════════════════════════════════════════════
#  ENROLLMENT LOGIC
# ══════════════════════════════════════════════════════════════════════════════

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

        query = {"classification_basket": basket, "email": {"$exists": True, "$ne": ""}}
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
            logger.warning("No active campaigns found for any business — skipping Dual Fit enrollment")
            return

        cursor = leads_enriched.find(
            {"classification_basket": "D", "email": {"$exists": True, "$ne": ""}}
        )

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


# ══════════════════════════════════════════════════════════════════════════════
#  SUPPRESSION LIST ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
#  DUAL FIT — manual trigger for enrollment
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
#  AWS SES — SNS BOUNCE / COMPLAINT WEBHOOK
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/ses/sns-webhook")
async def ses_sns_webhook(request: Request):
    """
    Receives bounce and complaint notifications from AWS SNS.

    Setup in AWS:
      1. SES → Configuration Set → Event Destinations → SNS topic
      2. SNS → Subscriptions → HTTP(S) endpoint:
         https://yourdomain.com/api/cold-outreach/ses/sns-webhook
      3. Confirm the subscription (AWS sends a SubscribeURL — we auto-confirm below)

    Events handled:
      - Bounce (Permanent)  → add to global suppression list
      - Bounce (Transient)  → log only (don't suppress)
      - Complaint           → add to global suppression list
    """
    import json as _json
    import urllib.request

    body = await request.body()
    try:
        payload = _json.loads(body)
    except Exception:
        logger.warning("SNS webhook: could not parse body")
        return {"ok": False}

    msg_type = payload.get("Type") or request.headers.get("x-amz-sns-message-type", "")

    # ── SNS subscription confirmation ─────────────────────────────────────────
    if msg_type == "SubscriptionConfirmation":
        confirm_url = payload.get("SubscribeURL")
        if confirm_url:
            try:
                urllib.request.urlopen(confirm_url, timeout=5)
                logger.info(f"SNS subscription confirmed: {confirm_url[:80]}")
            except Exception as e:
                logger.error(f"SNS subscription confirm failed: {e}")
        return {"ok": True, "confirmed": True}

    # ── Notification ──────────────────────────────────────────────────────────
    if msg_type == "Notification":
        try:
            message = _json.loads(payload.get("Message", "{}"))
        except Exception:
            return {"ok": False}

        notification_type = message.get("notificationType")
        db = get_db()
        suppression = db["outreach_bounce_suppression"]
        leads_enriched = get_leads_db()["leads_enriched"]
        now = datetime.utcnow()

        def _suppress(email: str, reason: str):
            email = email.lower().strip()
            try:
                suppression.update_one(
                    {"email": email},
                    {"$setOnInsert": {
                        "email": email,
                        "bounced_at": now,
                        "reason": reason,
                        "source": "ses_sns",
                        "created_at": now,
                    }},
                    upsert=True,
                )
                leads_enriched.update_many(
                    {"email": email},
                    {"$set": {"email_status": reason, "bounce_suppressed": True, "bounced_at": now}},
                )
                logger.info(f"SNS suppressed: {email} ({reason})")
            except Exception as e:
                logger.warning(f"SNS suppression write failed for {email}: {e}")

        if notification_type == "Bounce":
            bounce = message.get("bounce", {})
            bounce_type = bounce.get("bounceType", "")
            if bounce_type == "Permanent":
                for r in bounce.get("bouncedRecipients", []):
                    _suppress(r.get("emailAddress", ""), "bounced")
            else:
                # Transient bounce — log but don't suppress
                for r in bounce.get("bouncedRecipients", []):
                    logger.warning(f"Transient bounce (not suppressed): {r.get('emailAddress')}")

        elif notification_type == "Complaint":
            complaint = message.get("complaint", {})
            for r in complaint.get("complainedRecipients", []):
                _suppress(r.get("emailAddress", ""), "complaint")

        elif notification_type == "Delivery":
            # Optional: mark as delivered in outreach_sends_v2 if needed
            pass

    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  OUTREACH SEND PROCESSOR — background job + manual trigger endpoint
# ══════════════════════════════════════════════════════════════════════════════

# Set to an email address to redirect ALL outgoing outreach mail (test mode).
# Set to None to send to actual recipient.
_OUTREACH_TEST_OVERRIDE_EMAIL: Optional[str] = "susantasarkar7447@gmail.com"

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

# Gemini 429 cooldown — skip outreach sends entirely until this time
_gemini_quota_cooldown_until: Optional[datetime] = None
_GEMINI_COOLDOWN_MINUTES = 10  # backoff when all keys exhausted

# Daily send cap per sender email (AWS SES mailboxes are exempt)
_DAILY_SEND_LIMIT_PER_MAILBOX = 2000


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

    mongo_uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/"
    svc = GmailWorkspaceService(mongo_uri=mongo_uri, db_name="torpedo_gmail")
    svc.load_service_account()
    return svc


# ── Gmail signature cache (keyed by from_email, refreshed every 6 hours) ──
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
    Call OpenAI to produce a unique (subject, body_html) for this specific lead.
    Returns (subject, body_html). Raises on failure.
    """
    import openai as _openai
    from leads.openai_rotator import get_pipeline_rotator

    rotator = get_pipeline_rotator("outreach")
    key_index, api_key = rotator.get_available_key()

    tone_map = {
        "professional": "formal and professional",
        "friendly": "warm, friendly, and approachable",
        "direct": "direct and concise — no fluff",
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
<the email body — plain paragraphs, no HTML tags, no signature block>

Rules:
- Address the recipient by their first name: {first_name}
- Reference their company or industry naturally (do NOT invent facts)
- Do NOT include a signature — the system appends one
- Do NOT use markdown, bullet points, or HTML tags
- Keep the tone {tone}
"""

    client = _openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a B2B cold email copywriter specialising in market research and data services. Follow instructions precisely."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=500,
        temperature=0.8,
    )
    tokens = response.usage.total_tokens if response.usage else 0
    rotator.log_request(key_index, tokens, "outreach_email_gen", success=True)

    raw = response.choices[0].message.content.strip()
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
) -> str:
    """
    Send one email via GmailWorkspaceService (service account / domain-wide delegation).
    Returns the Gmail message_id. Raises on failure.
    """
    actual_to = to_email
    if _OUTREACH_TEST_OVERRIDE_EMAIL:
        logger.info(
            f"[OUTREACH TEST MODE] Redirecting {to_email} → {_OUTREACH_TEST_OVERRIDE_EMAIL}"
        )
        actual_to = _OUTREACH_TEST_OVERRIDE_EMAIL

    svc = _get_gmail_workspace_service()
    signature_html = _get_gmail_signature(from_email)
    result = svc.send_email(
        from_email=from_email,
        to=[actual_to],
        subject=subject,
        body_html=body_html,
        signature_html=signature_html,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Gmail API send failed")
    return result.get("message_id") or ""


def _process_one_outreach_lead(db, lead_record: dict) -> bool:
    """
    For one outreach_leads_v2 record:
      1. Verify campaign is active
      2. Check suppression
      3. Generate a personalized email with Gemini
      4. Send via Gmail API (service account / domain-wide delegation)
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

        # Check that this step exists in the sequence (we have 4 steps: 1–4)
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

        business = campaign.get("business", "sfw")
        from_email = _BUSINESS_SENDER.get(business, "indira@surveyfieldwork.com")
        display_name = _BUSINESS_DISPLAY_NAME.get(business, "Indira Das")
        business_label = BUSINESS_LABEL.get(business, business)
        campaign_ctx = campaign.get("business_context") or {}

        # Daily send cap per mailbox (SES exempt)
        if _sender_at_daily_limit(db, from_email):
            tomorrow = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {"next_send_at": tomorrow, "updated_at": datetime.utcnow()}}
            )
            logger.info(f"[Outreach] Daily limit reached for {from_email} — rescheduling {email} to tomorrow")
            return False

        # Generate personalized email for this specific lead
        try:
            subject, body_html = _generate_personalized_email(
                lead=lead_record,
                step_number=next_step_number,
                business=business,
                business_label=business_label,
                campaign_ctx=campaign_ctx,
                sender_name=display_name,
            )
        except Exception as gen_err:
            err_str = str(gen_err)
            # Re-raise quota errors so the outer cycle loop can abort early
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                raise
            logger.warning(
                f"[Outreach] Gemini generation failed for {email} step {next_step_number}: {gen_err}"
            )
            db["outreach_leads_v2"].update_one(
                {"_id": lead_record["_id"]},
                {"$set": {
                    "last_send_error": f"AI generation failed: {gen_err}"[:300],
                    "last_send_error_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }}
            )
            return False

        # Send via Gmail API
        gmail_message_id = _send_via_gmail_api(from_email, email, subject, body_html, display_name)

        now = datetime.utcnow()

        # Record send
        db["outreach_sends_v2"].insert_one({
            "send_id": str(uuid.uuid4()),
            "lead_id": lead_record.get("lead_id"),
            "campaign_id": lead_record["campaign_id"],
            "outreach_lead_id": str(lead_record["_id"]),
            "email": email,
            "from_email": from_email,
            "workflow_step": steps_sent,   # 0-indexed for stats aggregation
            "subject": subject,
            "gmail_message_id": gmail_message_id,
            "status": "sent",
            "reply_received": False,
            "open_count": 0,
            "unsubscribed": False,
            "sent_at": now,
            "created_at": now,
        })

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
        # Re-raise quota errors so the scheduler cycle aborts early
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            raise
        logger.error(
            f"[Outreach] Failed to process {lead_record.get('email')}: {e}",
            exc_info=True
        )
        db["outreach_leads_v2"].update_one(
            {"_id": lead_record["_id"]},
            {"$set": {
                "last_send_error": str(e)[:300],
                "last_send_error_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }}
        )
        return False


def process_due_outreach_sends() -> dict:
    """
    Called by APScheduler every 60 seconds.
    Picks up to 5 outreach_leads_v2 records that are due and sends their next step.
    Stops early if a Gemini 429 quota error is detected and sets a cooldown.
    Returns a summary dict.
    """
    global _gemini_quota_cooldown_until
    try:
        now = datetime.utcnow()

        # Check cooldown — skip entirely if Gemini keys are known-exhausted
        if _gemini_quota_cooldown_until and now < _gemini_quota_cooldown_until:
            return {"processed": 0, "sent": 0, "skipped": 0, "cooldown_until": str(_gemini_quota_cooldown_until)}

        db = get_db()

        due = list(db["outreach_leads_v2"].find({
            "workflow_status": {"$in": ["not_started", "pending_scheduled", "in_sequence"]},
            "next_send_at": {"$lte": now},
        }).limit(5))

        if not due:
            return {"processed": 0, "sent": 0, "skipped": 0}

        sent = 0
        skipped = 0
        quota_abort = False
        for record in due:
            try:
                ok = _process_one_outreach_lead(db, record)
                if ok:
                    sent += 1
                else:
                    skipped += 1
            except Exception as loop_err:
                err_str = str(loop_err)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    logger.warning(
                        f"[Outreach] Gemini quota hit — setting {_GEMINI_COOLDOWN_MINUTES}m cooldown"
                    )
                    _gemini_quota_cooldown_until = now + timedelta(minutes=_GEMINI_COOLDOWN_MINUTES)
                    quota_abort = True
                    break
                skipped += 1

        if sent > 0 or skipped > 0 or quota_abort:
            logger.info(f"[Outreach] Cycle complete: sent={sent} skipped={skipped} quota_abort={quota_abort}")

        # Clear cooldown if we successfully sent at least one
        if sent > 0:
            _gemini_quota_cooldown_until = None

        return {"processed": len(due), "sent": sent, "skipped": skipped, "quota_abort": quota_abort}

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
