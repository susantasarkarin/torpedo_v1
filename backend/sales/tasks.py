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
from datetime import datetime
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
    """
    Pre-enrichment step: apply a known domain email pattern from cache if available,
    then hand off to enrich_lead where Gemini will predict the email if still missing.
    Skrapp.io has been removed — email prediction is handled by Gemini enrichment.
    """
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

        first, last = _split_name(name)

        # Apply known domain pattern from cache (fast path)
        cached = domains.find_one({"domain": domain})
        if cached:
            pattern = cached["pattern"]
            email = _construct_from_pattern(pattern, first, last, domain)
            if email:
                domains.update_one({"domain": domain}, {"$inc": {"hit_count": 1}})
                leads.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$set": {"email": email, "email_status": "pattern_match", "updated_at": datetime.utcnow()}},
                )
                logger.info(f"Email pattern cache hit for {lead_id}: {email}")

        # Always proceed to enrichment — Gemini will predict email if still missing
        enrich_lead.delay(lead_id)
        return {"status": "queued_for_enrichment", "cache_hit": bool(cached)}

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
    """
    Legacy step — Skrapp.io verification removed.
    Email prediction is now handled by Gemini inside enrich_lead.
    This task is kept to safely drain any previously queued messages.
    """
    try:
        enrich_lead.delay(lead_id)
        return {"status": "forwarded_to_enrichment"}
    except Exception as e:
        logger.error(f"verify_lead_email forward failed for {lead_id}: {e}")
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
            update_fields = {
                "enrichment": {
                    "role": enrichment.get("seniority_hint", ""),
                    "company_size": enrichment.get("company_size_bucket", ""),
                    "pain_points": enrichment.get("top_pain_points", [])[:2],
                    "news": "; ".join(gathered.get("news_headlines", [])[:3]),
                    "hook": enrichment.get("personalisation_hook", ""),
                    "status": "done",
                },
                "intent_score": enrichment.get("role_match_score", 50),
                "stage": "enriched",
                "updated_at": datetime.utcnow(),
            }

            # Store Gemini-predicted email if lead doesn't already have a confirmed one
            predicted_email = enrichment.get("email_address", "")
            email_confidence = enrichment.get("email_confidence", 0)
            existing_email = lead.get("email", "")
            existing_status = lead.get("email_status", "")
            if predicted_email and "@" in predicted_email and not existing_email:
                update_fields["email"] = predicted_email.lower().strip()
                update_fields["email_status"] = "gemini_inferred"
                update_fields["email_confidence_score"] = email_confidence
                logger.info(
                    f"Gemini predicted email for {lead_id}: {predicted_email} "
                    f"(confidence={email_confidence})"
                )
            elif predicted_email and "@" in predicted_email and existing_status == "pattern_match":
                # Gemini may have found a better match from website scrape — prefer it if confidence is high
                if email_confidence >= 70:
                    update_fields["email"] = predicted_email.lower().strip()
                    update_fields["email_status"] = "gemini_inferred"
                    update_fields["email_confidence_score"] = email_confidence

            leads.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": update_fields},
            )
            # Auto-assign ICP tags based on enrichment results
            _assign_icp_tags(lead_id, lead, enrichment, gathered)
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


def _assign_icp_tags(
    lead_id: str,
    lead: Dict[str, Any],
    enrichment: Dict[str, Any],
    gathered: Dict[str, Any],
) -> None:
    """
    5-basket ICP classification engine run after every enrichment.

    Basket A  — Survey Fieldwork (SFW): sampling & fieldwork buyers
    Basket B  — Cogentix Research: brand & consumer insights buyers
    Basket C  — BIMwave: AEC & built-environment buyers
    Basket D  — Dual Fit: qualifies for both A and B
    Basket E  — Nurture / Unqualified: no basket match or low-quality signal

    Writes to lead:
        icp_tags, classification_basket (code A-E),
        classification_basket_name, fit_tier (1-3), fit_tier_label,
        persona_label, classification_confidence, classified_at
    """
    import re as _re
    try:
        from bson import ObjectId
        leads = _get_leads_col()

        # ── Normalise all fields to lowercase strings ─────────────────────
        def _n(v): return (v or "").lower().strip()

        title        = _n(lead.get("title", ""))
        dept         = _n(lead.get("department", ""))
        seniority    = _n(lead.get("seniority_level", ""))
        buying_role  = _n(lead.get("buying_role", "") or lead.get("persona", ""))
        industry     = _n(
            lead.get("company_industry", "") or
            enrichment.get("industry", "")
        )
        co_size_raw  = _n(
            lead.get("company_employee_count_range", "") or
            enrichment.get("company_size", "") or
            lead.get("company_size", "")
        )
        revenue_raw  = _n(lead.get("company_revenue_range", "") or "")
        location     = _n(lead.get("location", "") or lead.get("company_headquarters", ""))
        email_status = _n(lead.get("email_status", ""))
        confidence   = int(lead.get("confidence_score") or lead.get("intent_score") or 0)
        full_text    = " ".join([
            title, dept, industry,
            _n(lead.get("company", "")),
            _n(enrichment.get("hook", "")),
            _n(gathered.get("meta_description", "")),
            _n(gathered.get("about_text", "")),
            " ".join(enrichment.get("pain_points", [])),
        ])

        # ── Revenue helper ────────────────────────────────────────────────
        def _revenue_gte(rev, min_m):
            nums = _re.findall(r"\d+", rev.replace(",", ""))
            if not nums: return False
            low = int(nums[0])
            if "billion" in rev or (len(nums) == 1 and "b" in rev): low *= 1000
            return low >= min_m

        # ── Seniority helpers ─────────────────────────────────────────────
        HIGH_TITLES = {
            "vp", "vice president", "c-suite", "ceo", "cto", "cfo", "coo",
            "cmo", "cro", "chro", "cio", "cpo", "director", "svp", "evp",
            "president", "owner", "founder", "co-founder", "partner",
            "managing director", "md",
        }
        MID_TITLES = {"manager", "head of", "senior", "principal", "lead"}

        def _is_high():
            combined = title + " " + seniority
            return any(t in combined for t in HIGH_TITLES)

        def _is_mid():
            combined = title + " " + seniority
            return any(t in combined for t in MID_TITLES)

        def _is_dm():
            return any(k in buying_role for k in ("decision maker", "decision", "influencer", "champion"))

        # ── Basket keyword / industry sets ────────────────────────────────
        MR_IND  = ["market research", "research agency", "consumer insights",
                   "data collection", "panel services", "mr technology", "fieldwork"]
        MR_DEPT = ["research operations", "insights", "data", "field services", "sampling", "research"]
        MR_KW   = ["panel", "fieldwork", "survey", "cati", "cawi", "tracker",
                   "quantitative", "sample", "incidence rate", "ir rate", "respondent", "omnibus"]

        BRAND_IND  = ["fmcg", "consumer goods", "retail", "healthcare", "pharma",
                      "media", "fintech", "financial services", "advertising agency",
                      "brand consulting", "cpg", "insurance", "telecom"]
        BRAND_DEPT = ["marketing", "brand", "consumer insights", "strategy",
                      "product", "growth", "communications"]
        BRAND_KW   = ["brand health", "ad effectiveness", "concept testing", "nps",
                      "satisfaction", "brand tracking", "customer experience",
                      "brand equity", "awareness", "consideration", "purchase intent"]

        AEC_IND  = ["architecture", "construction", "engineering", "real estate develop",
                    "interior design", "mep", "infrastructure", "bim services"]
        AEC_DEPT = ["architecture", "engineering", "project management",
                    "construction", "design", "bim"]
        AEC_KW   = ["revit", "bim", "ifc", "aec", "autocad", "navisworks", "archicad",
                    "civil engineering", "structural", "mechanical engineering"]
        AEC_GEO  = ["united states", " us,", "united kingdom", " uk,", "australia",
                    "canada", "middle east", "uae", "dubai", "saudi", "qatar"]

        # ── Scoring functions (higher = stronger signal) ──────────────────
        def _score_sfw():
            s = 0
            if any(i in industry for i in MR_IND):   s += 4
            if any(k in full_text for k in MR_KW):   s += 2
            if any(d in dept for d in MR_DEPT):      s += 3
            if _is_high():                            s += 2
            if _is_dm():                              s += 2
            if "mid-market" in co_size_raw or "enterprise" in co_size_raw: s += 2
            if _revenue_gte(revenue_raw, 10):         s += 2
            return s

        def _score_brand():
            s = 0
            if any(i in industry for i in BRAND_IND):  s += 4
            if any(k in full_text for k in BRAND_KW):  s += 2
            if any(d in dept for d in BRAND_DEPT):     s += 3
            if _is_high():                              s += 2
            if _is_dm():                                s += 2
            if _revenue_gte(revenue_raw, 10):           s += 2
            return s

        def _score_aec():
            s = 0
            if any(i in industry for i in AEC_IND):   s += 4
            if any(k in full_text for k in AEC_KW):   s += 2
            if any(d in dept for d in AEC_DEPT):      s += 3
            if any(g in location for g in AEC_GEO):   s += 2
            return s

        sfw_s   = _score_sfw()
        brand_s = _score_brand()
        aec_s   = _score_aec()
        THRESHOLD = 4  # minimum score to qualify for a basket

        q_sfw   = sfw_s   >= THRESHOLD
        q_brand = brand_s >= THRESHOLD
        q_aec   = aec_s   >= THRESHOLD

        # Disqualify low-quality email signals
        exclude = email_status == "predicted" and confidence < 50

        # ── Assign basket (A-E) ───────────────────────────────────────────
        if exclude or (not q_sfw and not q_brand and not q_aec):
            basket_code, basket_name = "E", "Nurture / Unqualified"
            icp_tags = ["nurture"]
        elif q_sfw and q_brand:
            basket_code, basket_name = "D", "Dual Fit: SFW + Cogentix"
            icp_tags = ["survey_fieldwork", "cogentix"]
        elif q_aec:
            basket_code, basket_name = "C", "BIMwave"
            icp_tags = ["bimwave"]
        elif q_sfw:
            basket_code, basket_name = "A", "Survey Fieldwork"
            icp_tags = ["survey_fieldwork"]
        else:
            basket_code, basket_name = "B", "Cogentix Research"
            icp_tags = ["cogentix"]

        # ── Fit tier ──────────────────────────────────────────────────────
        top = max(sfw_s, brand_s, aec_s)
        if top >= 8 and _is_high() and (
            "decision maker" in buying_role or _revenue_gte(revenue_raw, 50)
        ):
            fit_tier, fit_label = 1, "Hot"
        elif top >= 4 and (_is_high() or _is_mid()) and (
            _is_dm() or _revenue_gte(revenue_raw, 10)
        ):
            fit_tier, fit_label = 2, "Warm"
        else:
            fit_tier, fit_label = 3, "Cold"

        # ── Persona label ─────────────────────────────────────────────────
        ctx = title + " " + dept + " " + seniority
        if any(k in ctx for k in ("ceo", "cto", "cfo", "coo", "cmo", "cro",
                                   "svp", "evp", "president", "c-suite")):
            persona_label = "Executive Sponsor"
        elif any(d in dept for d in MR_DEPT):
            persona_label = "Research Buyer"
        elif any(d in dept for d in BRAND_DEPT):
            persona_label = "Brand Strategist"
        elif any(d in dept for d in AEC_DEPT):
            persona_label = "AEC Operator"
        elif any(k in buying_role for k in ("influencer", "champion", "recommender")):
            persona_label = "Influencer / Recommender"
        elif _is_high():
            persona_label = "Executive Sponsor"
        else:
            persona_label = "Influencer / Recommender"

        # ── Classification confidence ─────────────────────────────────────
        conf = "High" if top >= 10 else "Medium" if top >= 5 else "Low"

        # ── Persist to lead doc ───────────────────────────────────────────
        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {
                "$set": {
                    "icp_tags": icp_tags,
                    "classification_basket": basket_code,
                    "classification_basket_name": basket_name,
                    "fit_tier": fit_tier,
                    "fit_tier_label": fit_label,
                    "persona_label": persona_label,
                    "classification_confidence": conf,
                    "classified_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                },
            },
        )
        logger.info(
            f"Classified lead {lead_id}: Basket {basket_code} ({basket_name}), "
            f"Tier {fit_tier} ({fit_label}), Persona: {persona_label}, Conf: {conf}"
        )
    except Exception as e:
        logger.warning(f"ICP classification failed for {lead_id}: {e}")


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
                    except Exception as e:
                        logger.warning(f"About page scrape failed for {domain}: {e}")
        except Exception as e:
            logger.warning(f"Domain fetch failed for {domain}: {e}")

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
        except Exception as e:
            logger.warning(f"News RSS fetch failed for {company}: {e}")

    return data


def _call_ai_enrichment(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Enrich a lead using OpenAI."""
    try:
        from ai_governance.ai_gateway import get_ai_gateway
        return get_ai_gateway().enrich_lead_data(context)
    except Exception as e:
        logger.error(f"AI enrichment failed: {e}")
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
def generate_email_draft(self, lead_id: str, instruction: Optional[str] = None, icp_slug: Optional[str] = None):
    """
    Generate email draft using AI based on track type and ICP-specific outreach config.
    icp_slug: if provided, use that ICP's config. Otherwise, pick the first tag on the lead.
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

        # Resolve ICP outreach config (per-ICP personalisation)
        icp_tags = lead.get("icp_tags", [])
        active_slug = icp_slug or (icp_tags[0] if icp_tags else None)
        icp_config = _get_icp_outreach_config(active_slug)

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

        # Merge ICP pain points (prefer enriched, fall back to ICP template)
        pain_points = context["pain_points"] or icp_config.get("pain_points", [])
        service_name = icp_config.get("service_name", "our company")
        value_prop = icp_config.get("value_proposition", "")
        cta = icp_config.get("call_to_action", "Would you be open to a quick 20-minute call?")
        sender_title = icp_config.get("sender_title", "")

        # Step 2 — Build ICP-aware prompt
        system = (
            "You write B2B sales emails that sound like a real person wrote them. "
            "Rules: No 'I hope this email finds you well'. No buzzwords. No filler sentences. "
            "Short paragraphs. One clear ask at the end. Max 120 words for the body. "
            'Return only valid JSON: { "subject": "<string>", "body": "<string>" } '
            "Do not include any preamble or markdown."
        )

        if track == "cold":
            user = (
                f"Write a cold outreach email to {name} at {company}.\n"
                f"We are reaching out on behalf of {service_name}.\n"
                f"Our value proposition: {value_prop}\n"
                f"Their likely pain point: {', '.join(pain_points[:1]) if pain_points else 'operational inefficiency'}.\n"
                f"Personalisation hook (use if relevant): {context['hook']}.\n"
                f"Recent company news (mention only if specific and relevant): {context['news']}.\n"
                f"End with this ask: {cta}"
            )
        elif track == "reengagement":
            user = (
                f"Write a re-engagement email to {name} at {company} on behalf of {service_name}.\n"
                f"We last exchanged emails on {context['last_contacted']}. Reference that naturally — not awkwardly.\n"
                f"Pain point to address: {', '.join(pain_points[:1]) if pain_points else 'operational efficiency'}.\n"
                f"Hook: {context['hook']}.\n"
                f"Tone: warm, not salesy. We're re-opening a conversation, not starting one.\n"
                f"End with: {cta}"
            )
        else:  # inbound
            user = (
                f"Write a response to {name} at {company} who contacted {service_name} via our website.\n"
                f"Their message: {context['contactus_message']}.\n"
                "Respond directly to what they said. Do not pitch. "
                "Confirm we received it and suggest a call. Tone: prompt, helpful, human."
            )

        if instruction:
            user += f"\n\nAdditional instruction from rep: {instruction}"

        # Step 3 — AI call
        draft = _call_ai_draft(system, user)
        if not draft:
            return {"error": "ai_draft_failed"}

        # Store draft (include which ICP was used for reference)
        leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {
                "email_draft": {
                    "subject": draft["subject"],
                    "body": draft["body"],
                    "generated_at": datetime.utcnow(),
                    "status": "pending_review",
                    "icp_slug": active_slug,
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


def _get_icp_outreach_config(slug: Optional[str]) -> Dict[str, Any]:
    """
    Fetch the outreach_config for a given ICP slug from the icp_segments collection.
    Falls back to a generic config if the slug is None or not found.
    """
    if not slug:
        return {}
    try:
        db = get_background_db()
        seg = db["icp_segments"].find_one({"slug": slug}, {"outreach_config": 1, "_id": 0})
        if seg and seg.get("outreach_config"):
            return seg["outreach_config"]
    except Exception as e:
        logger.warning(f"Could not fetch ICP outreach config for {slug}: {e}")
    return {}


def _call_ai_draft(system_prompt: str, user_prompt: str) -> Optional[Dict[str, str]]:
    """Generate email draft using OpenAI."""
    try:
        from ai_governance.ai_gateway import get_ai_gateway
        return get_ai_gateway().generate_email_draft(system_prompt, user_prompt)
    except Exception as e:
        logger.error(f"AI draft generation failed: {e}")
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
        # Build classification context for Gemini
        sender_summaries = []
        for s in sender_batch[:50]:
            sender_summaries.append({
                "email": s["email"],
                "name": s.get("name", ""),
                "domain": s.get("domain", ""),
                "subjects": s.get("subjects", "")[:200],
            })

        from ai_governance.ai_gateway import get_ai_gateway
        classifications = get_ai_gateway().classify_senders(sender_summaries) or []

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
