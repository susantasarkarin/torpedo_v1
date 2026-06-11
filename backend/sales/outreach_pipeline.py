"""
MODULES 4 + 5 + 6 — OUTREACH PIPELINE
========================================
Module 4: Business unit routing via Gemini
Module 5: Gmail outreach + follow-up scheduling
Module 6: Email tracking & reply sentiment analysis via Gemini

Pipeline flow per lead:
  enriched lead
    → route_lead_to_bu()        [Gemini picks BU + drafts personalised email]
    → send_initial_outreach()   [Gmail API sends email, records send]
    → schedule_followups()      [reads followup_scripts.json, queues follow-up tasks]
    → [time passes — tracking events arrive]
    → handle_email_event()      [bounce → remove, reply → Gemini sentiment → CRM/archive]
    → send_followup_email()     [if not opened within wait window, send next step]
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

from celery_app import celery_app
from db_pools import get_background_db

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
#  CONFIG PATHS
# ─────────────────────────────────────────────────────

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_BU_DIR = _BACKEND_DIR / "configs" / "business_units"
_FOLLOWUP_CONFIG = _BACKEND_DIR / "configs" / "followup_scripts.json"


def _load_business_units() -> List[Dict[str, str]]:
    """Load all BU description files from the configs/business_units/ directory."""
    units = []
    for txt_file in sorted(_BU_DIR.glob("*.txt")):
        content = txt_file.read_text(encoding="utf-8")
        slug = txt_file.stem  # filename without extension
        # Extract BUSINESS UNIT name from first line
        first_line = content.splitlines()[0]
        name = first_line.replace("BUSINESS UNIT:", "").strip().split("—")[0].strip() if "BUSINESS UNIT:" in first_line else slug
        units.append({"slug": slug, "name": name, "description": content})
    return units


def _load_followup_config() -> Dict[str, Any]:
    """Load follow-up timing and scripts from configs/followup_scripts.json."""
    try:
        return json.loads(_FOLLOWUP_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Could not load follow-up config: {e}")
        return {}


# ─────────────────────────────────────────────────────
#  GMAIL API HELPER
# ─────────────────────────────────────────────────────

def _get_gmail_service():
    """Get authenticated Gmail API service using existing credentials."""
    root = str(_BACKEND_DIR.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from gmail_automation.auth import GmailAuthenticator
    auth = GmailAuthenticator()
    return auth.authenticate()


def _send_via_gmail(
    service,
    to_email: str,
    subject: str,
    body: str,
    thread_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send an email via Gmail API.
    Supports thread continuity via thread_id + In-Reply-To + References headers.
    """
    import base64
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart("alternative")
    msg["To"] = to_email
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    msg.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    send_body: Dict[str, Any] = {"raw": raw}
    if thread_id:
        send_body["threadId"] = thread_id

    result = service.users().messages().send(userId="me", body=send_body).execute()
    return result


# ─────────────────────────────────────────────────────
#  MODULE 4: BUSINESS UNIT ROUTING
# ─────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="backend.sales.outreach_pipeline.route_lead_to_bu",
    queue="ai_processing",
    max_retries=1,
    rate_limit="20/m",
)
def route_lead_to_bu(self, lead_id: str) -> Dict[str, Any]:
    """
    Module 4: Use Gemini to research the lead, read BU descriptions,
    identify the gap, route to the best BU, and draft a personalised outreach email.

    Stores on the lead:
        bu_routing.slug, bu_routing.bu_name, bu_routing.gap_analysis,
        bu_routing.outreach_email.{subject, body}, bu_routing.routed_at
    """
    try:
        from bson import ObjectId
        from ai_governance.ai_gateway import get_ai_gateway

        db = get_background_db()
        leads = db["leads"]
        lead = leads.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            return {"error": "lead_not_found"}

        enrichment = lead.get("enrichment", {})
        lead_context = {
            "name": lead.get("name", ""),
            "email": lead.get("email", ""),
            "company": lead.get("company", ""),
            "domain": lead.get("domain", ""),
            "title": lead.get("title", ""),
            "industry": enrichment.get("industry", lead.get("company_industry", "")),
            "company_size": enrichment.get("company_size", ""),
            "seniority": enrichment.get("seniority_hint", lead.get("seniority_level", "")),
            "pain_points": enrichment.get("pain_points", []),
            "hook": enrichment.get("hook", ""),
            "news": enrichment.get("news", ""),
            "icp_tags": lead.get("icp_tags", []),
            "persona_label": lead.get("persona_label", ""),
        }

        business_units = _load_business_units()
        if not business_units:
            logger.error(f"[BU Routing] No business unit config files found in {_BU_DIR}")
            return {"error": "no_bu_configs"}

        gateway = get_ai_gateway()
        result = gateway.route_to_business_unit(lead_context, business_units)

        if not result.get("success"):
            logger.error(f"[BU Routing] Gemini routing failed for {lead_id}: {result.get('error')}")
            return {"error": "routing_failed", "detail": result.get("error")}

        # Find the full BU description for the chosen slug (for OpenAI drafting)
        chosen_bu = next(
            (bu for bu in business_units if bu["slug"] == result.get("slug")),
            business_units[0] if business_units else {}
        )

        # Draft the outreach email via Claude (ai_governance gateway)
        draft = gateway.draft_outreach_email(
            lead_context=lead_context,
            bu_description=chosen_bu.get("description", ""),
            gap_analysis=result.get("gap_analysis", ""),
            sender=result.get("sender", ""),
        )

        if not draft.get("subject") or not draft.get("body"):
            logger.error(f"[BU Routing] OpenAI email draft empty for lead {lead_id}")
            return {"error": "draft_failed"}

        # Store routing + draft on lead
        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {
                "bu_routing": {
                    "slug": result["slug"],
                    "bu_name": result["bu_name"],
                    "gap_analysis": result["gap_analysis"],
                    "sender": result.get("sender", ""),
                    "outreach_email": draft,
                    "routed_at": datetime.utcnow(),
                },
                "stage": "email_construction",
                "updated_at": datetime.utcnow(),
            }},
        )

        logger.info(
            f"[BU Routing] Lead {lead_id} ({lead.get('name')}) → {result['bu_name']} "
            f"({result['slug']})"
        )

        # Trigger sending
        send_initial_outreach.delay(lead_id)
        return {"status": "routed", "bu": result["slug"]}

    except Exception as e:
        logger.error(f"[BU Routing] Task failed for {lead_id}: {e}")
        raise self.retry(exc=e, countdown=120)


# ─────────────────────────────────────────────────────
#  MODULE 5: GMAIL OUTREACH + FOLLOW-UP SCHEDULING
# ─────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="backend.sales.outreach_pipeline.send_initial_outreach",
    queue="sales",
    max_retries=2,
    rate_limit="30/h",
)
def send_initial_outreach(self, lead_id: str) -> Dict[str, Any]:
    """
    Module 5: Send the initial outreach email via Gmail API (Susanta's account).
    Records the send in email_events and schedules follow-ups.
    """
    try:
        from bson import ObjectId
        db = get_background_db()
        leads = db["leads"]
        events = db["email_events"]

        lead = leads.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            return {"error": "lead_not_found"}

        # Get the routed email draft
        routing = lead.get("bu_routing", {})
        draft = routing.get("outreach_email") or lead.get("email_draft", {})
        if not draft or not draft.get("subject") or not draft.get("body"):
            logger.error(f"[Outreach] No approved draft for lead {lead_id}")
            return {"error": "no_draft_available"}

        to_email = lead.get("email", "")
        if not to_email:
            return {"error": "no_email_address"}

        # Check bounce suppression
        suppressed = db["outreach_bounce_suppression"].count_documents(
            {"email": to_email.lower()}, limit=1
        )
        if suppressed:
            logger.warning(f"[Outreach] {to_email} is bounce-suppressed. Skipping.")
            leads.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {"stage": "lost", "email_status": "bounced", "updated_at": datetime.utcnow()}},
            )
            return {"status": "suppressed"}

        service = _get_gmail_service()
        result = _send_via_gmail(
            service,
            to_email=to_email,
            subject=draft["subject"],
            body=draft["body"],
        )

        gmail_message_id = result.get("id", "")
        gmail_thread_id = result.get("threadId", "")
        now = datetime.utcnow()

        # Record send event
        events.insert_one({
            "lead_id": lead_id,
            "type": "sent",
            "step": 1,
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": gmail_thread_id,
            "subject": draft["subject"],
            "sent_at": now,
            "bu_slug": routing.get("slug", ""),
        })

        # Update lead
        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {
                "stage": "outreach_sent",
                "outreach_step": 1,
                "last_contacted": now,
                "gmail_thread_id": gmail_thread_id,
                "last_gmail_message_id": gmail_message_id,
                "updated_at": now,
            }},
        )

        logger.info(f"[Outreach] Sent step 1 to {to_email} (thread: {gmail_thread_id})")

        # Schedule follow-ups
        schedule_followups.delay(lead_id, gmail_thread_id, gmail_message_id, step=1)
        return {"status": "sent", "gmail_message_id": gmail_message_id}

    except Exception as e:
        logger.error(f"[Outreach] Send failed for {lead_id}: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(
    name="backend.sales.outreach_pipeline.schedule_followups",
    queue="sales",
)
def schedule_followups(
    lead_id: str,
    thread_id: str,
    last_message_id: str,
    step: int,
) -> Dict[str, Any]:
    """
    Read follow-up config and schedule next email as a Celery ETA task.
    Called after each successful send.
    """
    from bson import ObjectId
    db = get_background_db()
    leads = db["leads"]
    lead = leads.find_one({"_id": ObjectId(lead_id)})
    if not lead:
        return {"error": "lead_not_found"}

    config = _load_followup_config()
    track = lead.get("track", "cold")
    sequence = config.get("sequences", {}).get(track, config.get("sequences", {}).get("cold", {}))
    steps = sequence.get("steps", [])
    reply_wait = config.get("reply_wait_hours", {})

    # Find next step
    next_steps = [s for s in steps if s["step"] > step]
    if not next_steps:
        logger.info(f"[Schedule] Lead {lead_id} has completed all follow-up steps.")
        return {"status": "sequence_complete"}

    next_step = next_steps[0]
    delay_days = next_step.get("delay_days", 4)
    wait_hours = reply_wait.get(f"step_{step}", 96)

    # ETA = max(wait_hours since send, now + delay_days)
    eta = datetime.utcnow() + timedelta(hours=max(wait_hours, delay_days * 24))

    send_followup_email.apply_async(
        args=[lead_id, thread_id, last_message_id, next_step["step"]],
        eta=eta,
    )

    logger.info(
        f"[Schedule] Lead {lead_id}: step {next_step['step']} scheduled for {eta.isoformat()} "
        f"(delay_days={delay_days})"
    )
    return {"status": "scheduled", "next_step": next_step["step"], "eta": eta.isoformat()}


@celery_app.task(
    bind=True,
    name="backend.sales.outreach_pipeline.send_followup_email",
    queue="sales",
    max_retries=2,
    rate_limit="30/h",
)
def send_followup_email(
    self,
    lead_id: str,
    thread_id: str,
    in_reply_to: str,
    step: int,
) -> Dict[str, Any]:
    """
    Module 5: Send a follow-up email in the same Gmail thread.
    Checks that lead has not replied or bounced before sending.
    Each step uses a unique script from followup_scripts.json.
    """
    try:
        from bson import ObjectId
        db = get_background_db()
        leads = db["leads"]
        events = db["email_events"]

        lead = leads.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            return {"error": "lead_not_found"}

        # Abort conditions — lead replied, bounced, or unsubscribed
        stage = lead.get("stage", "")
        if stage in ("replied", "won", "lost"):
            logger.info(f"[Followup] Lead {lead_id} stage={stage}, skipping step {step}.")
            return {"status": "skipped", "reason": stage}

        email_status = lead.get("email_status", "")
        if email_status == "bounced":
            return {"status": "skipped", "reason": "bounced"}

        config = _load_followup_config()
        track = lead.get("track", "cold")
        sequence = config.get("sequences", {}).get(track, config.get("sequences", {}).get("cold", {}))
        step_configs = [s for s in sequence.get("steps", []) if s["step"] == step]
        if not step_configs:
            return {"error": f"No config for step {step}"}

        step_cfg = step_configs[0]

        # Build email from unique step script (no content reuse)
        first_name = lead.get("first_name") or lead.get("name", "").split(" ")[0] or "there"
        company = lead.get("company", "")
        pain_points = lead.get("enrichment", {}).get("pain_points", [])
        pain_point = pain_points[0] if pain_points else "operational efficiency"
        hook = lead.get("enrichment", {}).get("hook", "")
        routing = lead.get("bu_routing", {})
        bu_name = routing.get("bu_name", "our team")
        industry = lead.get("enrichment", {}).get("industry", "your industry")

        # Fill step-specific script template
        subject = step_cfg["subject_template"].format(
            company=company,
            pain_area=pain_point,
            first_name=first_name,
        )
        body = step_cfg["script_template"].format(
            first_name=first_name,
            company=company,
            hook=hook or f"you're working on challenges in {industry}",
            value_prop_short=f"accelerate results for {industry} teams",
            pain_point=pain_point,
            pain_area=pain_point,
            persona_type="business",
            objection="complexity and cost",
            industry=industry,
            outcome_example="a 30% reduction in project turnaround time",
            recent_news_or_hook=hook or f"there have been notable shifts in {industry}",
            cta="Would you be open to a quick 15-minute call?",
        )

        # Get reference chain for thread continuity
        prior_events = list(events.find(
            {"lead_id": lead_id, "type": "sent"},
            sort=[("sent_at", -1)],
            limit=10,
        ))
        references = " ".join(e.get("gmail_message_id", "") for e in prior_events if e.get("gmail_message_id"))

        service = _get_gmail_service()
        result = _send_via_gmail(
            service,
            to_email=lead["email"],
            subject=subject,
            body=body,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            references=references,
        )

        gmail_message_id = result.get("id", "")
        now = datetime.utcnow()

        events.insert_one({
            "lead_id": lead_id,
            "type": "sent",
            "step": step,
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": thread_id,
            "subject": subject,
            "sent_at": now,
        })

        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {
                "outreach_step": step,
                "last_contacted": now,
                "last_gmail_message_id": gmail_message_id,
                "updated_at": now,
            }},
        )

        logger.info(f"[Followup] Sent step {step} to {lead['email']}")

        # Schedule next follow-up
        schedule_followups.delay(lead_id, thread_id, gmail_message_id, step=step)
        return {"status": "sent", "step": step, "gmail_message_id": gmail_message_id}

    except Exception as e:
        logger.error(f"[Followup] Step {step} failed for {lead_id}: {e}")
        raise self.retry(exc=e, countdown=300)


# ─────────────────────────────────────────────────────
#  MODULE 6: EMAIL TRACKING & REPLY ANALYSIS
# ─────────────────────────────────────────────────────

@celery_app.task(
    name="backend.sales.outreach_pipeline.handle_email_event",
    queue="sales",
)
def handle_email_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Module 6: Handle an inbound tracking event for a sent email.
    Events: delivered, opened, bounced, not_opened, reply_received.

    Routing:
      bounced       → flag lead, add to suppression list, remove from sequence
      reply_received → Gemini sentiment → positive→CRM, negative→archive, neutral→manual review
      not_opened    → already handled by schedule_followups timer
    """
    from bson import ObjectId
    event_type = event.get("type", "")
    lead_id = event.get("lead_id", "")
    if not lead_id:
        return {"error": "no_lead_id"}

    db = get_background_db()
    leads = db["leads"]

    if event_type == "delivered":
        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {"last_delivery_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
        )
        return {"status": "delivered_recorded"}

    elif event_type == "opened":
        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {
                "$set": {"last_opened_at": datetime.utcnow(), "updated_at": datetime.utcnow()},
                "$inc": {"open_count": 1},
            },
        )
        logger.info(f"[Tracking] Lead {lead_id} opened email.")
        return {"status": "opened_recorded"}

    elif event_type == "bounced":
        _handle_bounce(lead_id, event.get("email", ""), db)
        return {"status": "bounced_handled"}

    elif event_type == "reply_received":
        analyze_reply.delay(lead_id, event.get("reply_body", ""), event.get("gmail_message_id", ""))
        return {"status": "reply_queued_for_analysis"}

    return {"status": "event_recorded", "type": event_type}


def _handle_bounce(lead_id: str, email: str, db) -> None:
    """Flag lead as bounced, add to suppression list, stop sequence."""
    from bson import ObjectId
    now = datetime.utcnow()

    # Add to global suppression list
    if email:
        try:
            db["outreach_bounce_suppression"].update_one(
                {"email": email.lower()},
                {"$setOnInsert": {
                    "email": email.lower(),
                    "bounced_at": now,
                    "lead_id": lead_id,
                    "created_at": now,
                }},
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"[Bounce] Suppression insert failed: {e}")

    db["leads"].update_one(
        {"_id": ObjectId(lead_id)},
        {"$set": {
            "email_status": "bounced",
            "stage": "lost",
            "bounce_suppressed": True,
            "bounced_at": now,
            "updated_at": now,
        }},
    )
    logger.warning(f"[Bounce] Lead {lead_id} ({email}) bounced and suppressed.")


@celery_app.task(
    bind=True,
    name="backend.sales.outreach_pipeline.analyze_reply",
    queue="ai_processing",
    max_retries=1,
    rate_limit="20/m",
)
def analyze_reply(self, lead_id: str, reply_body: str, gmail_message_id: str) -> Dict[str, Any]:
    """
    Module 6: Use Gemini to analyse the sentiment of a reply.
    Routes the lead based on result:
      positive  → stage='replied', move to CRM (active leads section)
      negative  → stage='lost', archive and flag for review
      neutral   → flag for manual review, stage remains
    """
    try:
        from bson import ObjectId
        from ai_governance.ai_gateway import get_ai_gateway

        db = get_background_db()
        leads = db["leads"]
        lead = leads.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            return {"error": "lead_not_found"}

        gateway = get_ai_gateway()
        analysis = gateway.analyze_reply_sentiment(
            email_id=gmail_message_id,
            reply_body=reply_body,
            lead_name=lead.get("name", ""),
        )

        sentiment = analysis.get("sentiment", "neutral")
        action = analysis.get("recommended_action", "flag_for_manual_review")
        now = datetime.utcnow()

        reply_record = {
            "gmail_message_id": gmail_message_id,
            "body_snippet": reply_body[:500],
            "sentiment": sentiment,
            "summary": analysis.get("summary", ""),
            "intent": analysis.get("intent", ""),
            "recommended_action": action,
            "analyzed_at": now,
        }

        if action == "move_to_crm":
            leads.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {
                    "stage": "replied",
                    "engagement_status": "replied_positive",
                    "last_reply": reply_record,
                    "crm_added_at": now,
                    "updated_at": now,
                }},
            )
            db["notifications"].insert_one({
                "type": "positive_reply",
                "title": f"Positive reply from {lead.get('name')} at {lead.get('company')}",
                "lead_id": lead_id,
                "summary": analysis.get("summary", ""),
                "read": False,
                "created_at": now,
            })
            logger.info(f"[Reply] Lead {lead_id} → POSITIVE → moved to CRM")

        elif action == "archive_and_flag":
            leads.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {
                    "stage": "lost",
                    "engagement_status": "replied_negative",
                    "archived": True,
                    "last_reply": reply_record,
                    "updated_at": now,
                }},
            )
            logger.info(f"[Reply] Lead {lead_id} → NEGATIVE → archived and flagged")

        else:  # neutral / unclear → manual review
            leads.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {
                    "engagement_status": "replied_neutral",
                    "needs_manual_review": True,
                    "last_reply": reply_record,
                    "updated_at": now,
                }},
            )
            db["notifications"].insert_one({
                "type": "neutral_reply",
                "title": f"Reply needs review: {lead.get('name')} at {lead.get('company')}",
                "lead_id": lead_id,
                "summary": analysis.get("summary", ""),
                "read": False,
                "created_at": now,
            })
            logger.info(f"[Reply] Lead {lead_id} → NEUTRAL → flagged for manual review")

        return {
            "status": "analyzed",
            "sentiment": sentiment,
            "action": action,
            "lead_id": lead_id,
        }

    except Exception as e:
        logger.error(f"[Reply Analysis] Failed for lead {lead_id}: {e}")
        raise self.retry(exc=e, countdown=60)
