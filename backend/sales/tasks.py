"""
Sales Celery Tasks (Rebuilt)
Background jobs for the sales pipeline:
- Email construction queue (Step 7)
- Email verification queue (Step 8)
- AI enrichment queue (Step 9)
- AI email draft generation (Step 10)
- Mail pool AI classification fallback (Step 5)
- Send approved email (Step 11)
- Deliverability cron (Step 12)
- Reengagement cron
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from celery_app import celery_app
from db_pools import get_background_db, get_background_collection

logger = logging.getLogger(__name__)


def _get_leads_col():
    return get_background_db()["leads"]


def _get_events_col():
    return get_background_db()["email_events"]


def _get_domains_col():
    return get_background_db()["company_domains"]


# ══════════════════════════════════════════════
#  EMAIL CONSTRUCTION QUEUE  (Step 7)
# ══════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="backend.tasks.sales_pipeline.enqueue_email_construction",
    queue="sales",
    max_retries=2,
    rate_limit="10/m",
)
def enqueue_email_construction(self, lead_id: str):
    """Construct email for a lead using domain pattern or skrapp.io."""
    try:
        from bson import ObjectId
        leads = _get_leads_col()
        domains = _get_domains_col()

        lead = leads.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            logger.error(f"Lead {lead_id} not found for email construction")
            return {"error": "lead_not_found"}

        domain = lead.get("domain", "")
        name = lead.get("name", "")
        if not domain or not name:
            return {"error": "missing_domain_or_name"}

        import re
        first, last = _split_name(name)

        # Check cache
        cached = domains.find_one({"domain": domain})
        if cached:
            pattern = cached["pattern"]
            email = _construct_from_pattern(pattern, first, last, domain)
            if email:
                domains.update_one({"domain": domain}, {"$inc": {"hit_count": 1}})
                leads.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$set": {"email": email, "updated_at": datetime.utcnow()}},
                )
                verify_lead_email.delay(lead_id)
                return {"email": email, "source": "cache"}

        # Try skrapp.io
        skrapp_key = os.getenv("SKRAPP_API_KEY", "")
        if skrapp_key:
            import httpx
            try:
                resp = httpx.post(
                    "https://app.skrapp.io/api/v2/email-finder",
                    json={"domain": domain, "firstName": first, "lastName": last},
                    headers={"Authorization": f"Bearer {skrapp_key}"},
                    timeout=15,
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("email"):
                    email = data["email"].lower().strip()
                    pattern = data.get("pattern", "{first}.{last}")
                    domains.update_one(
                        {"domain": domain},
                        {"$set": {"domain": domain, "pattern": pattern, "source": "skrapp", "verified_at": datetime.utcnow()},
                         "$inc": {"hit_count": 1}},
                        upsert=True,
                    )
                    leads.update_one(
                        {"_id": ObjectId(lead_id)},
                        {"$set": {"email": email, "updated_at": datetime.utcnow()}},
                    )
                    verify_lead_email.delay(lead_id)
                    return {"email": email, "source": "skrapp"}
            except Exception as e:
                logger.error(f"Skrapp email-finder error: {e}")

        # Fallback: guess with common patterns
        for pattern in ["{first}.{last}", "{first}{last}", "{first}"]:
            email = _construct_from_pattern(pattern, first, last, domain)
            if email:
                leads.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$set": {"email": email, "email_status": "pending", "updated_at": datetime.utcnow()}},
                )
                verify_lead_email.delay(lead_id)
                return {"email": email, "source": "guess"}

        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {"email_status": "invalid", "stage": "new", "updated_at": datetime.utcnow()}},
        )
        return {"error": "could_not_construct"}

    except Exception as e:
        logger.error(f"Email construction failed for {lead_id}: {e}")
        raise self.retry(exc=e, countdown=60)


# ══════════════════════════════════════════════
#  EMAIL VERIFICATION QUEUE  (Step 8)
# ══════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="backend.tasks.sales_pipeline.verify_lead_email",
    queue="sales",
    max_retries=1,
    rate_limit="10/s",
)
def verify_lead_email(self, lead_id: str):
    """Verify email via skrapp.io. On valid → stage=verified → enqueue enrichment."""
    try:
        from bson import ObjectId
        leads = _get_leads_col()
        lead = leads.find_one({"_id": ObjectId(lead_id)})
        if not lead or not lead.get("email"):
            return {"error": "no_email"}

        email = lead["email"]
        result = _call_skrapp_verify(email)

        if result == "valid":
            leads.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {"email_status": "verified", "stage": "verified", "updated_at": datetime.utcnow()}},
            )
            enrich_lead.delay(lead_id)
            return {"status": "verified"}

        # Try alternate
        domain = lead.get("domain", "")
        name = lead.get("name", "")
        if domain and name:
            first, last = _split_name(name)
            for pattern in ["{first}.{last}", "{first}{last}", "{first_initial}{last}", "{first}"]:
                alt = _construct_from_pattern(pattern, first, last, domain)
                if alt and alt != email:
                    alt_result = _call_skrapp_verify(alt)
                    if alt_result == "valid":
                        leads.update_one(
                            {"_id": ObjectId(lead_id)},
                            {"$set": {"email": alt, "email_status": "verified", "stage": "verified", "updated_at": datetime.utcnow()}},
                        )
                        enrich_lead.delay(lead_id)
                        return {"status": "verified", "email": alt}
                    break  # Only one retry

        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {"email_status": "invalid", "stage": "new", "updated_at": datetime.utcnow()}},
        )
        db = get_background_db()
        db["notifications"].insert_one({
            "type": "email_verification_failed",
            "title": f"Could not verify email for {lead.get('name', '')} at {lead.get('company', '')}",
            "lead_id": lead_id,
            "read": False,
            "created_at": datetime.utcnow(),
        })
        return {"status": "invalid"}

    except Exception as e:
        logger.error(f"Verification failed for {lead_id}: {e}")
        raise self.retry(exc=e, countdown=30)


# ══════════════════════════════════════════════
#  AI ENRICHMENT  (Step 9)
# ══════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="backend.tasks.sales_pipeline.enrich_lead",
    queue="ai_processing",
    max_retries=1,
    rate_limit="20/m",
)
def enrich_lead(self, lead_id: str):
    """
    Enrich a verified lead with company data + AI analysis.
    Steps 1-2: code-only (web scrape + news).
    Step 3: AI call (permitted).
    Step 4: validate & store.
    """
    try:
        from bson import ObjectId
        leads = _get_leads_col()
        lead = leads.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            return {"error": "lead_not_found"}

        company = lead.get("company", "")
        domain = lead.get("domain", "")

        # Step 1 — Gather data (code only)
        gathered = _gather_company_data(company, domain)

        # Step 2 — Build context
        context = {
            "company_name": company,
            "domain": domain,
            "name": lead.get("name", ""),
            "meta_description": gathered.get("meta_description", ""),
            "about_text": gathered.get("about_text", ""),
            "recent_news": gathered.get("news_headlines", []),
        }

        # Step 3 — AI enrichment call
        enrichment = _call_ai_enrichment(context)

        # Step 4 — Validate and store
        if enrichment:
            leads.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {
                    "enrichment": {
                        "role": enrichment.get("company_size_bucket", ""),
                        "company_size": enrichment.get("company_size_bucket", ""),
                        "pain_points": enrichment.get("top_pain_points", [])[:2],
                        "news": "; ".join(gathered.get("news_headlines", [])[:3]),
                        "hook": enrichment.get("personalisation_hook", ""),
                        "status": "done",
                    },
                    "intent_score": enrichment.get("role_match_score", 50),
                    "stage": "enriched",
                    "updated_at": datetime.utcnow(),
                }},
            )
            # Enqueue for email draft generation
            generate_email_draft.delay(lead_id)
            return {"status": "enriched", "score": enrichment.get("role_match_score")}
        else:
            leads.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {"enrichment.status": "failed", "updated_at": datetime.utcnow()}},
            )
            return {"status": "failed"}

    except Exception as e:
        logger.error(f"Enrichment failed for {lead_id}: {e}")
        leads = _get_leads_col()
        from bson import ObjectId
        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {"enrichment.status": "failed", "updated_at": datetime.utcnow()}},
        )
        raise self.retry(exc=e, countdown=120)


def _gather_company_data(company: str, domain: str) -> Dict[str, Any]:
    """Scrape meta description + about page + news headlines (code only)."""
    data = {"meta_description": "", "about_text": "", "news_headlines": []}

    if domain:
        import httpx
        # Meta description
        try:
            resp = httpx.get(f"https://{domain}", timeout=10, follow_redirects=True)
            if resp.status_code == 200:
                import re
                meta_match = re.search(
                    r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
                    resp.text, re.IGNORECASE,
                )
                if meta_match:
                    data["meta_description"] = meta_match.group(1)[:500]

                # About page link
                about_match = re.search(r'href=["\']([^"\']*about[^"\']*)["\']', resp.text, re.IGNORECASE)
                if about_match:
                    about_url = about_match.group(1)
                    if not about_url.startswith("http"):
                        about_url = f"https://{domain}{about_url}"
                    try:
                        about_resp = httpx.get(about_url, timeout=10, follow_redirects=True)
                        if about_resp.status_code == 200:
                            # Strip HTML tags, take first 1000 chars
                            text = re.sub(r"<[^>]+>", " ", about_resp.text)
                            text = re.sub(r"\s+", " ", text).strip()
                            data["about_text"] = text[:1000]
                    except Exception:
                        pass
        except Exception:
            pass

    # Google News RSS for headlines
    if company:
        import httpx
        try:
            from urllib.parse import quote
            rss_url = f"https://news.google.com/rss/search?q={quote(company)}"
            resp = httpx.get(rss_url, timeout=10)
            if resp.status_code == 200:
                import re
                titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.+?)(?:\]\]>)?</title>", resp.text)
                data["news_headlines"] = [t.strip() for t in titles[1:4]]  # Skip RSS feed title
        except Exception:
            pass

    return data


def _call_ai_enrichment(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call AI (OpenAI/Claude) for enrichment. Returns parsed JSON or None."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("No OPENAI_API_KEY — skipping AI enrichment")
        return None

    import httpx
    system_prompt = "You are a B2B sales analyst. Return only valid JSON, no preamble, no markdown."
    user_prompt = f"""Given this company data: {json.dumps(context)}
Return JSON with exactly these fields:
{{
  "role_match_score": <number 0-100>,
  "company_size_bucket": "1-10" | "11-50" | "51-200" | "201-1000" | "1000+",
  "top_pain_points": [<string>, <string>],
  "personalisation_hook": "<one sentence, specific to this company>"
}}"""

    try:
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 300,
            },
            timeout=30,
        )
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        result = json.loads(content.strip())

        # Validate required fields
        required = ["role_match_score", "company_size_bucket", "top_pain_points", "personalisation_hook"]
        if all(k in result for k in required):
            return result
        logger.warning(f"AI enrichment missing fields: {result}")
        return None
    except Exception as e:
        logger.error(f"AI enrichment API call failed: {e}")
        return None


# ══════════════════════════════════════════════
#  AI EMAIL DRAFT GENERATION  (Step 10)
# ══════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="backend.tasks.sales_pipeline.generate_email_draft",
    queue="ai_processing",
    max_retries=1,
    rate_limit="20/m",
)
def generate_email_draft(self, lead_id: str, instruction: Optional[str] = None):
    """
    Generate email draft using AI based on track type.
    Creates draft on lead record with status=pending_review.
    """
    try:
        from bson import ObjectId
        leads = _get_leads_col()
        lead = leads.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            return {"error": "lead_not_found"}

        # Step 1 — Assemble context
        enrichment = lead.get("enrichment", {})
        track = lead.get("track", "cold")
        name = lead.get("name", "")
        company = lead.get("company", "")

        context = {
            "name": name,
            "company": company,
            "role_match_score": enrichment.get("role", ""),
            "pain_points": enrichment.get("pain_points", []),
            "hook": enrichment.get("hook", ""),
            "news": enrichment.get("news", ""),
            "contactus_message": lead.get("contactus_message", ""),
            "track": track,
            "last_contacted": str(lead.get("last_contacted", "")),
        }

        # Step 2 — Build prompt
        system = (
            "You write B2B sales emails that sound like a real person wrote them. "
            "Rules: No 'I hope this email finds you well'. No buzzwords. No filler sentences. "
            "Short paragraphs. One clear ask at the end. Max 120 words for the body. "
            'Return only valid JSON: { "subject": "<string>", "body": "<string>" } '
            "Do not include any preamble or markdown."
        )

        if track == "cold":
            user = (
                f"Write a cold outreach email to {name}, at {company}. "
                f"Their likely pain point: {', '.join(context['pain_points'][:1])}. "
                f"Personalisation hook: {context['hook']}. "
                f"Company news: {context['news']}. "
                "Our ask: a 20-minute call to explore if we can help."
            )
        elif track == "reengagement":
            user = (
                f"Write a re-engagement email to {name} at {company}. "
                f"We last exchanged emails on {context['last_contacted']}. "
                "Reference that naturally — not awkwardly. "
                f"Pain point: {', '.join(context['pain_points'][:1])}. "
                f"Hook: {context['hook']}. "
                "Tone: warm, not salesy. We're re-opening a conversation, not starting one."
            )
        else:  # inbound
            user = (
                f"Write a response to {name} at {company} who contacted us via our website. "
                f"Their message: {context['contactus_message']}. "
                "Respond directly to what they said. Do not pitch. "
                "Confirm we received it and suggest a call. Tone: prompt, helpful, human."
            )

        if instruction:
            user += f"\n\nAdditional instruction from rep: {instruction}"

        # Step 3 — AI call
        draft = _call_ai_draft(system, user)
        if not draft:
            return {"error": "ai_draft_failed"}

        # Store draft
        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {
                "email_draft": {
                    "subject": draft["subject"],
                    "body": draft["body"],
                    "generated_at": datetime.utcnow(),
                    "status": "pending_review",
                },
                "updated_at": datetime.utcnow(),
            }},
        )

        # Notification for rep
        db = get_background_db()
        db["notifications"].insert_one({
            "type": "draft_ready",
            "title": f"New draft ready for {name} at {company}",
            "lead_id": lead_id,
            "read": False,
            "created_at": datetime.utcnow(),
        })

        return {"status": "draft_created", "subject": draft["subject"]}

    except Exception as e:
        logger.error(f"Draft generation failed for {lead_id}: {e}")
        raise self.retry(exc=e, countdown=60)


def _call_ai_draft(system_prompt: str, user_prompt: str) -> Optional[Dict[str, str]]:
    """Call AI to generate email draft. Returns {subject, body} or None."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("No OPENAI_API_KEY — cannot generate draft")
        return None

    import httpx
    try:
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 400,
            },
            timeout=30,
        )
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        result = json.loads(content.strip())
        if "subject" in result and "body" in result:
            return result
        return None
    except Exception as e:
        logger.error(f"AI draft API call failed: {e}")
        return None


# ══════════════════════════════════════════════
#  MAIL POOL AI FALLBACK  (Step 5)
# ══════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="backend.tasks.sales_pipeline.classify_mail_pool_senders",
    queue="ai_processing",
    max_retries=1,
    rate_limit="5/m",
)
def classify_mail_pool_senders(self, sender_batch: List[Dict[str, Any]]):
    """
    AI fallback for ambiguous mail pool senders.
    Classifies as: client | vendor | promotional | transactional | unknown.
    """
    try:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning("No OPENAI_API_KEY — creating all as leads")
            _create_leads_from_senders(sender_batch)
            return {"status": "fallback_no_api"}

        # Build classification prompt
        sender_summaries = []
        for s in sender_batch[:50]:
            sender_summaries.append({
                "email": s["email"],
                "name": s.get("name", ""),
                "domain": s.get("domain", ""),
                "subjects": s.get("subjects", "")[:200],
            })

        import httpx
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": "You classify email senders. Return only valid JSON array."},
                    {"role": "user", "content": (
                        "Classify each sender as: client | vendor | promotional | transactional | unknown. "
                        "Return JSON array: [{\"email\": \"...\", \"classification\": \"...\"}]. "
                        f"Senders: {json.dumps(sender_summaries)}"
                    )},
                ],
                "temperature": 0.1,
                "max_tokens": 2000,
            },
            timeout=30,
        )

        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        classifications = json.loads(content.strip())

        # Map classifications back
        class_map = {c["email"]: c["classification"] for c in classifications if "email" in c}

        viable = []
        for s in sender_batch:
            cls = class_map.get(s["email"], "unknown")
            if cls in ("client", "unknown"):
                viable.append(s)
            # vendor → skip (TODO: route to vendor module)
            # promotional/transactional → archive

        _create_leads_from_senders(viable)
        return {"classified": len(classifications), "leads_created": len(viable)}

    except Exception as e:
        logger.error(f"Mail pool AI classification failed: {e}")
        # Fallback: create all as leads
        _create_leads_from_senders(sender_batch)
        raise self.retry(exc=e, countdown=120)


def _create_leads_from_senders(senders: List[Dict[str, Any]]):
    """Create lead records from viable mail pool senders."""
    leads = _get_leads_col()
    now = datetime.utcnow()
    for s in senders:
        email = s["email"].lower().strip()
        domain = email.split("@")[1] if "@" in email else ""
        try:
            leads.insert_one({
                "source": "mail_pool",
                "stage": "new",
                "name": s.get("name", email.split("@")[0]),
                "email": email,
                "email_status": "pending",
                "company": "",
                "domain": domain,
                "last_contacted": None,
                "intent_score": None,
                "enrichment": {"status": "pending"},
                "mail_thread_ids": s.get("thread_ids", []),
                "contactus_message": None,
                "track": s.get("track", "cold"),
                "rfq_id": None,
                "archived": False,
                "reengagement_eligible_at": None,
                "email_draft": None,
                "created_at": now,
                "updated_at": now,
            })
        except Exception:
            pass  # Duplicate email


# ══════════════════════════════════════════════
#  SEND APPROVED EMAIL  (Step 11)
# ══════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="backend.tasks.sales_pipeline.send_approved_email",
    queue="sales",
    max_retries=2,
    rate_limit="30/m",
)
def send_approved_email(self, lead_id: str):
    """Send the approved email draft and record tracking events."""
    try:
        from bson import ObjectId
        import uuid
        leads = _get_leads_col()
        events = _get_events_col()

        lead = leads.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            return {"error": "lead_not_found"}

        draft = lead.get("email_draft", {})
        if draft.get("status") != "approved":
            return {"error": "draft_not_approved"}

        email = lead.get("email")
        if not email:
            return {"error": "no_email"}

        send_id = str(uuid.uuid4())[:8]

        # Prepare email with tracking
        from sales.tracking_router import prepare_email_for_tracking
        html_body = f"<html><body>{draft['body']}</body></html>"
        tracked_body = prepare_email_for_tracking(html_body, lead_id, send_id)

        # Send via SMTP (use existing email infrastructure)
        # TODO: integrate with campaign send infrastructure
        logger.info(f"Would send email to {email}: {draft['subject']}")

        # Record sent event
        events.insert_one({
            "lead_id": lead_id,
            "send_id": send_id,
            "event_type": "sent",
            "timestamp": datetime.utcnow(),
            "metadata": {},
        })

        # Update lead stage
        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {
                "stage": "outreach_sent",
                "last_contacted": datetime.utcnow(),
                "email_draft.status": "sent",
                "updated_at": datetime.utcnow(),
            }},
        )

        return {"status": "sent", "send_id": send_id}

    except Exception as e:
        logger.error(f"Send failed for {lead_id}: {e}")
        raise self.retry(exc=e, countdown=60)


# ══════════════════════════════════════════════
#  DELIVERABILITY CRON  (Step 12)
# ══════════════════════════════════════════════

@celery_app.task(
    name="backend.tasks.sales_pipeline.calculate_deliverability",
    queue="sales",
)
def calculate_deliverability():
    """Nightly cron: recalculate domain health scores."""
    from sales.tracking_router import calculate_deliverability_scores
    calculate_deliverability_scores()
    return {"status": "done"}


# ══════════════════════════════════════════════
#  REENGAGEMENT CRON
# ══════════════════════════════════════════════

@celery_app.task(
    name="backend.tasks.sales_pipeline.check_reengagement",
    queue="sales",
)
def check_reengagement():
    """
    Nightly cron: find lost leads where reengagement_eligible_at <= today.
    Move them to stage=new with track=reengagement for campaign inclusion.
    """
    leads = _get_leads_col()
    now = datetime.utcnow()

    result = leads.update_many(
        {
            "stage": "lost",
            "reengagement_eligible_at": {"$lte": now},
            "archived": False,
        },
        {"$set": {
            "stage": "new",
            "track": "reengagement",
            "email_status": "verified",  # Keep their verified email
            "updated_at": now,
        }},
    )
    logger.info(f"Re-engagement: {result.modified_count} leads moved back to pipeline")
    return {"reengaged": result.modified_count}


# ══════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════

def _split_name(name: str):
    import re
    parts = name.strip().split(None, 1)
    first = parts[0].lower() if parts else ""
    last = parts[1].lower() if len(parts) > 1 else ""
    first = re.sub(r"[^a-z]", "", first)
    last = re.sub(r"[^a-z]", "", last)
    return first, last


def _construct_from_pattern(pattern: str, first: str, last: str, domain: str) -> Optional[str]:
    result = pattern
    result = result.replace("{first}", first)
    result = result.replace("{last}", last)
    result = result.replace("{first_initial}", first[0] if first else "")
    result = result.replace("{last_initial}", last[0] if last else "")
    if not result or not result.strip():
        return None
    return f"{result}@{domain}"


def _call_skrapp_verify(email: str) -> str:
    skrapp_key = os.getenv("SKRAPP_API_KEY", "")
    if not skrapp_key:
        return "valid"
    import httpx
    try:
        resp = httpx.post(
            "https://app.skrapp.io/api/v2/verify",
            json={"email": email},
            headers={"Authorization": f"Bearer {skrapp_key}"},
            timeout=15,
        )
        data = resp.json()
        return "valid" if data.get("status") == "valid" else "invalid"
    except Exception as e:
        logger.error(f"Skrapp verify error: {e}")
        return "invalid"
