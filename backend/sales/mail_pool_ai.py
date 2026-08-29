"""
MAIL POOL AI PROCESSING
=======================
AI layer over the Gmail mail pool (torpedo_gmail.email_metadata). For each
email (or sender), ONE combined model call — via AWS Bedrock through the
governed bedrock_client (Converse API) — produces:

  - summary + key points + sentiment
  - category / priority / action-required classification
  - extracted contacts (signature/body) -> routed through canonical ingestion
  - RFQ detection -> logged on the CRM spine (opportunity + project via
    crm_service.create_rfq) AND a draft estimate in finance_db.estimates
  - follow-up flag -> AI-drafted reply stored in mail_followup_drafts

Model routing (roles, never model IDs — the concrete models resolve inside
leads/bedrock_client.py and are swappable by env):
  - role="cheap": the per-email / per-sender analysis call (summary, sentiment,
    category, contact + RFQ detection). High volume, cheap, good enough for
    triage.
  - role="smart": only the two outputs a human or client actually reads —
    (a) follow-up reply drafts, and (b) parsing RFQ line items for the draft
    finance estimate.

Results are stored on the email doc under `ai_analysis` (idempotency marker)
so each email is processed once; `ai_analysis.meta` carries the model ID and
token usage for cost auditing. All downstream actions are best-effort and
non-fatal: a failed RFQ mirror never loses the summary.

RFQ detection lives ONLY in this AI layer, by design. The rule-based
MailSegregationAgent deliberately has no keyword RFQ rules — semantic intent
("are they asking us to quote research work?") is not reliably captured by
keywords, and two competing RFQ definitions would silently disagree. Do not
add RFQ keyword rules to the rule layer.

The regex-only extractor (sales/mail_pool_extractor.py) remains the fallback
when AI is unavailable.
"""

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Cheap trigger, not a classifier: "does anything about this sender's mail
# look worth a deep RFQ scan" (see process_sender()). The AI still decides
# what's actually an RFQ — this only decides whether to look at all.
_RFQ_SIGNAL_REGEX = re.compile(
    r"\b(rfq|rfp|request\s+for\s+(quote|quotation|proposal)|"
    r"quot(e|ation)|pricing\s+(request|proposal)|tender)\b",
    re.IGNORECASE,
)

MAIL_DB = "torpedo_gmail"
MAIL_COLLECTION = "email_metadata"
FOLLOWUP_COLLECTION = "mail_followup_drafts"  # stored in email_automation

# --- Bedrock role routing (roles resolve to models inside bedrock_client) ---
MAIL_AI_ANALYSIS_ROLE = os.getenv("MAIL_AI_ANALYSIS_ROLE", "cheap")   # summary/category/RFQ-detect
MAIL_AI_WRITER_ROLE = os.getenv("MAIL_AI_WRITER_ROLE", "smart")       # follow-up drafts, RFQ line items
MAIL_AI_ANALYSIS_MAX_TOKENS = int(os.getenv("MAIL_AI_ANALYSIS_MAX_TOKENS", "4000"))
MAIL_AI_SCAN_MAX_TOKENS = int(os.getenv("MAIL_AI_SCAN_MAX_TOKENS", "8000"))
# Per-run cap on how many emails/senders one beat processes.
MAIL_AI_MAX_PER_RUN = int(os.getenv("MAIL_AI_MAX_PER_RUN", "200"))


class MailAIThrottled(Exception):
    """Bedrock throttling / outage — the run should stop and leave the email
    UNMARKED so the next beat retries it. Never results in a partial
    ai_analysis or a burned failed-attempt."""

# --- Stage-1 rule prefilter (cost control) ---
# Rules run first (free). Only these rule segments are worth a paid Bedrock
# call; Bank/Promotion/Transactional noise is skipped when the rule is
# confident. This is the single biggest cost lever — the noise never pays for
# a model call.
MAIL_AI_PREFILTER_ENABLED = os.getenv(
    "MAIL_AI_PREFILTER_ENABLED", "true").lower() in ("1", "true", "yes")
MAIL_AI_PREFILTER_MIN_CONFIDENCE = float(
    os.getenv("MAIL_AI_PREFILTER_MIN_CONFIDENCE", "0.5"))
# Rule segments that get skipped (never reach Bedrock) when confident enough.
PREFILTER_SKIP_SEGMENTS = frozenset({"bank", "promotion", "transactional"})
# Rule segments that always proceed to the AI mail-desk.
PREFILTER_PROCEED_SEGMENTS = frozenset(
    {"internal", "client", "vendor", "gst_it_govt", "others"})
# Nightly safety net: how many prefiltered-out emails to re-check with the
# cheap model, to catch the rule filter silently eating real client mail.
MAIL_AI_PREFILTER_AUDIT_SAMPLE = int(os.getenv("MAIL_AI_PREFILTER_AUDIT_SAMPLE", "20"))
PREFILTER_AUDIT_COLLECTION = "mail_ai_prefilter_audit"   # in email_automation
# AI categories that, if seen on a prefiltered-out email, mean the rules were
# wrong to skip it — real correspondence, not noise.
_MEANINGFUL_AI_CATEGORIES = frozenset({"rfq", "client_inquiry", "reply", "vendor"})


# --- AI category -> UI segment mapping (single source of truth) ---
# The `segment` field the MailPool UI reads is derived from the AI category
# once Stage 2 runs. An AI category of "other" (or anything unmapped) keeps
# the rule segment.
AI_CATEGORY_TO_SEGMENT = {
    "rfq": "Client",
    "client_inquiry": "Client",
    "reply": "Client",
    "vendor": "Vendor",
    "promotional": "Promotion",
    "transactional": "Transactional",
    # Labels match mail_segregation_agent.py's rule-derived display strings
    # for the same concepts (_result("internal", "Internal", ...) etc.) so
    # the AI-detected and rule-detected paths agree on what the UI shows.
    "internal": "Internal",
    "bank": "Bank",
    "gov_tax": "GST/IT/Govt",
}
# Rule segments that always win over the AI category (domain-based, reliable)
# — IN THEORY. In practice, process_sender() (the only scheduled path) always
# calls derive_segment(category, None), so rule_result is never populated
# here and this override never fires on live traffic (confirmed: prod
# segment_source is ~447K "ai" vs. only ~284 "rules"). The AI's own
# internal/bank/gov_tax categories above are today's only real signal for
# these buckets on the sender path — rewiring the rule engine into
# process_sender() is a separate, bigger change.
RULE_AUTHORITATIVE_SEGMENTS = frozenset({"internal", "bank", "gst_it_govt"})


def derive_segment(ai_category: Optional[str],
                   rule_result: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """
    Map (ai_category, rule_result) -> (segment, segment_source).

    - Rule segment in {internal, bank, gst_it_govt}  -> rule display wins ("rules")
    - AI category in AI_CATEGORY_TO_SEGMENT           -> mapped segment ("ai")
    - "other"/unknown AI category                    -> rule display ("rules")
    """
    rule = rule_result or {}
    rule_seg = str(rule.get("segment") or "").lower()
    rule_display = rule.get("category") or "Others"

    if rule_seg in RULE_AUTHORITATIVE_SEGMENTS:
        return rule_display, "rules"
    mapped = AI_CATEGORY_TO_SEGMENT.get(str(ai_category or "").lower())
    if mapped:
        return mapped, "ai"
    return rule_display, "rules"


def _rule_agent():
    try:
        from agents.mail_segregation_agent import get_mail_segregation_agent
    except ImportError:
        from backend.agents.mail_segregation_agent import get_mail_segregation_agent
    return get_mail_segregation_agent()


def prefilter_decision(email_doc: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Stage 1: run the free rule classifier and decide whether this email is
    worth a paid Bedrock call.

    Returns (decision, rule_result) where decision is:
      "proceed" -> send to the AI mail-desk (Stage 2)
      "skip"    -> noise (Bank/Promotion/Transactional, confident); no model call
    When the prefilter is disabled every email proceeds.
    """
    try:
        rule_result = _rule_agent().classify(email_doc)
    except Exception as e:
        logger.warning("[mail-ai] rule prefilter failed, proceeding to AI: %s", e)
        return "proceed", {}

    if not MAIL_AI_PREFILTER_ENABLED:
        return "proceed", rule_result

    segment = (rule_result.get("segment") or "").lower()
    confidence = float(rule_result.get("confidence") or 0.0)
    if segment in PREFILTER_SKIP_SEGMENTS and confidence >= MAIL_AI_PREFILTER_MIN_CONFIDENCE:
        return "skip", rule_result
    return "proceed", rule_result

_MAIL_AI_SYSTEM = ("You are the mail-desk analyst for a market-research company "
                   "(surveys, panels, fieldwork). You return only valid JSON — "
                   "no markdown fences, no preamble, no commentary. Use JSON null "
                   "for missing values, never the string \"null\".")


def _bedrock():
    try:
        from leads import bedrock_client as bc
    except ImportError:
        from backend.leads import bedrock_client as bc
    return bc


def _analysis_json(prompt: str, max_tokens: int,
                   caller: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Run one cheap-model analysis call and return (parsed_dict_or_None, meta).
    Never raises — a Bedrock/JSON failure returns (None, meta_with_error) so
    the caller leaves the email unmarked for the next beat to retry.
    """
    bc = _bedrock()
    try:
        result, meta = bc.converse_json_meta(
            role=MAIL_AI_ANALYSIS_ROLE, system=_MAIL_AI_SYSTEM, user=prompt,
            max_tokens=max_tokens, temperature=0.0)
    except bc.BedrockError as e:
        # Transport/throttle/outage (retries already exhausted in bedrock_client)
        # -> systemic. Do NOT mark the email; the next beat retries it.
        raise MailAIThrottled(f"{caller}: {e}")
    except Exception as e:
        # Content/JSON failure -> this specific email is the problem.
        logger.warning("[mail-ai] %s analysis unparseable: %s", caller, e)
        return None, {"error": str(e), "role": MAIL_AI_ANALYSIS_ROLE}
    # Shared by analyze_email() (flat shape, top-level "summary") and
    # analyze_sender() (nested {emails, sender} shape, summary lives under
    # "sender") — only isinstance is checkable here; each caller validates
    # its own shape further.
    if not isinstance(result, dict):
        return None, meta
    return result, meta

_ANALYSIS_PROMPT = """You are the mail-desk analyst for a market-research company (surveys, panels, fieldwork).
Analyze this email and return ONLY valid JSON, no markdown.

From: {from_line}
Subject: {subject}
Body:
{body}

Return exactly this JSON shape:
{{
  "summary": "<2-3 sentence summary>",
  "key_points": ["<point>", "..."],
  "sentiment": "positive|neutral|negative",
  "category": "rfq|client_inquiry|vendor|reply|promotional|transactional|other",
  "priority": "high|medium|low",
  "action_required": true/false,
  "follow_up_needed": true/false,
  "contacts": [
    {{"name": "<full name or null>", "email": "<email>", "phone": "<or null>",
      "company": "<or null>", "title": "<or null>"}}
  ],
  "rfq": {{
    "is_rfq": true/false,
    "title": "<short title for the request, or null>",
    "description": "<what is being requested, or null>",
    "budget": <number or null>,
    "currency": "<ISO 4217 code (USD, INR, EUR, GBP...) or null>",
    "items": [{{"description": "<line item>", "quantity": <number>, "rate": <number or 0>}}],
    "deadline": "<ISO date or null>",
    "methodology": "<CATI|CAWI|F2F|CAPI|Online Panel|IDI|Focus Group|... or null>",
    "loi": <length of interview in minutes, integer, or null>,
    "ir": <incidence rate as a percentage number (e.g. 25 for 25%), or null>,
    "sample_size": <number of completes/respondents requested, integer, or null>,
    "country": "<target country/market, or null>",
    "study_type": "<B2B|B2C|Healthcare|IT|Consumer|Other, or null>"
  }}
}}

Rules:
- "rfq" means the sender is requesting a quotation/proposal/pricing for research
  work (sample, surveys, panel, fieldwork, translations etc.). A promotional
  email SELLING something is never an RFQ.
- contacts: only real external people evident in the email; [] if none.
- follow_up_needed: true when a reply from us is clearly expected.
- budget/currency: only fill from an explicit number/currency in the email; a
  request that merely asks for pricing (no figure given yet) is budget: null.
- loi/ir/sample_size/country/methodology/study_type: extract only what the
  email actually states; leave null rather than guessing."""


def _get_db(name: str):
    try:
        from db_pools import get_db
    except ImportError:
        from backend.db_pools import get_db
    return get_db(name)


def analyze_email(email_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run the combined AI analysis for one mail-pool email doc (cheap role)."""
    subject = email_doc.get("subject") or "(no subject)"
    from_name = email_doc.get("from_name") or ""
    from_email = email_doc.get("from_email") or email_doc.get("from") or ""
    body = (email_doc.get("body_plain") or email_doc.get("body")
            or email_doc.get("snippet") or "")
    prompt = _ANALYSIS_PROMPT.format(
        from_line=f"{from_name} <{from_email}>".strip(),
        subject=subject,
        body=str(body)[:4000],
    )
    result, meta = _analysis_json(
        prompt, MAIL_AI_ANALYSIS_MAX_TOKENS, caller="analyze_email")
    if result is None:
        return None
    result["analyzed_at"] = datetime.utcnow().isoformat()
    result["model_source"] = "bedrock"
    result["meta"] = meta            # model_id + token usage for cost auditing
    return result


WARM_QUEUE_COLLECTION = "warm_outreach_queue"   # in email_automation


def _has_emailed_us(email: str) -> bool:
    """True when this address appears as a sender anywhere in the mail pool —
    i.e. they have emailed us, so they are an inbound correspondent."""
    email = (email or "").strip().lower()
    if not email:
        return False
    try:
        return _get_db(MAIL_DB)[MAIL_COLLECTION].count_documents(
            {"from_email": email}, limit=1) > 0
    except Exception:
        return False


def _run_icp_and_route(lead_id: str, email: str, is_inbound: bool,
                       source_email_id: Any) -> Optional[str]:
    """
    Hand a freshly-ingested mail lead to the ICP pipeline:
      1. bucket_classifier (cheap first pass, smart escalation) -> bucket
      2. route:
         - inbound correspondent -> WARM queue, never cold outreach
         - otherwise -> standard cold-outreach qualification gates
    Returns the route ("warm" | "cold" | "not_qualified" | None). Never raises.
    """
    try:
        try:
            from leads.bucket_classifier import classify_lead, persist, leads_raw
            from leads.outreach_qualification import qualify
        except ImportError:
            from backend.leads.bucket_classifier import classify_lead, persist, leads_raw
            from backend.leads.outreach_qualification import qualify
        from bson import ObjectId

        try:
            oid = ObjectId(lead_id)
        except Exception:
            oid = lead_id
        lead = leads_raw.find_one({"_id": oid})
        if not lead:
            return None

        # ICP bucket classification (SFW / Cogentix / BIM / REJECT / REVIEW).
        result = classify_lead(lead)
        persist(lead, result)
        lead = leads_raw.find_one({"_id": oid}) or lead

        now = datetime.utcnow()
        if is_inbound:
            # Never cold-outreach an existing correspondent. Block cold
            # enrollment and route to the warm queue for a human.
            leads_raw.update_one({"_id": oid}, {"$set": {
                "cold_outreach_blocked": True,
                "cold_block_reason": "inbound_correspondent",
                "outreach_route": "warm",
                "warm_flagged_at": now,
            }})
            _get_db("email_automation")[WARM_QUEUE_COLLECTION].update_one(
                {"email": email},
                {"$set": {"email": email, "lead_id": str(oid),
                          "outreach_bucket": result.get("bucket"),
                          "reason": "inbound_correspondent",
                          "source_email_id": str(source_email_id),
                          "status": "pending_human_followup",
                          "flagged_at": now}},
                upsert=True)
            logger.info("[mail-ai] lead %s -> WARM queue (inbound correspondent)", oid)
            return "warm"

        # Outbound-eligible: apply the standard cold-outreach gates.
        q = qualify(lead)
        leads_raw.update_one({"_id": oid}, {"$set": {
            "outreach_route": "cold" if q.qualified else "not_qualified",
            "outreach_qualification_reason": q.reason,
        }})
        return "cold" if q.qualified else "not_qualified"
    except Exception as e:
        logger.warning("[mail-ai] ICP routing failed for lead %s: %s", lead_id, e)
        return None


# AI category -> destination. "vendor" contacts go to the standalone Vendor
# Leads collection (email_automation.vendor_leads, the Vendor > Leads page);
# everything else (rfq/client_inquiry/reply/promotional/transactional/other)
# keeps going through canonical ingestion into the Sales > Leads pipeline —
# unchanged from before, this only carves vendor out of that shared path.
VENDOR_LEADS_COLLECTION = "vendor_leads"   # in email_automation


def _ingest_vendor_contact(contact: Dict[str, Any], analysis: Dict[str, Any],
                           email_doc: Dict[str, Any]) -> bool:
    """Insert one AI-extracted vendor contact into vendor_leads, deduped by
    email (same convention as routers/vendor_leads.py's transfer endpoints).
    Returns True if a new row was inserted."""
    email = (contact.get("email") or "").strip().lower()
    if not email:
        return False
    col = _get_db("email_automation")[VENDOR_LEADS_COLLECTION]
    if col.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}):
        return False
    now = datetime.utcnow()
    name = (contact.get("name") or "").strip()
    col.insert_one({
        "name": name or "Unknown",
        "first_name": name.split()[0] if name else "",
        "last_name": name.split()[-1] if name and " " in name else "",
        "email": email,
        "title": (contact.get("title") or "").strip(),
        "company": (contact.get("company") or "").strip(),
        "phone": (contact.get("phone") or "").strip(),
        "status": "new",
        "notes": f"Auto-extracted from mail pool ({email_doc.get('subject') or 'email'}). "
                 f"AI summary: {analysis.get('summary', '')}",
        "source": "mail_pool_ai",
        "source_email_id": str(email_doc.get("_id")),
        "created_at": now, "updated_at": now,
    })
    return True


def _ingest_contacts(analysis: Dict[str, Any], email_doc: Dict[str, Any]) -> int:
    """
    Route AI-extracted contacts to their destination by AI category:
      - "vendor"                       -> vendor_leads (Vendor > Leads)
      - everything else (rfq/client_inquiry/reply/promotional/transactional/
        other) -> canonical ingestion -> leads_raw/leads_enriched
        (Sales > Leads), then ICP bucket classification + outreach routing.
    The email's own sender is always an inbound correspondent (warm, never
    cold) on the sales path; other extracted contacts are checked against
    the pool.
    """
    ingested = 0
    contacts = analysis.get("contacts") or []
    if not contacts:
        return 0

    if (analysis.get("category") or "").strip().lower() == "vendor":
        for c in contacts:
            try:
                if _ingest_vendor_contact(c, analysis, email_doc):
                    ingested += 1
            except Exception as ce:
                logger.debug(f"[mail-ai] vendor contact ingest skipped: {ce}")
        return ingested

    sender_email = (email_doc.get("from_email") or email_doc.get("from") or "").strip().lower()
    try:
        try:
            from leads.canonical_ingestion import ingest_lead
        except ImportError:
            from backend.leads.canonical_ingestion import ingest_lead
        for c in contacts:
            contact_email = (c.get("email") or "").strip().lower()
            if not contact_email:
                continue
            try:
                r = ingest_lead({
                    "email": contact_email,
                    "name": c.get("name"),
                    "company": c.get("company"),
                    "title": c.get("title"),
                    "phone": c.get("phone"),
                    "subject": email_doc.get("subject"),
                    "notes": analysis.get("summary"),
                }, source="gmail", source_detail="mail_pool_ai") or {}
                if not r.get("success"):
                    continue
                ingested += 1
                lead_id = r.get("lead_id")
                if lead_id:
                    is_inbound = (contact_email == sender_email) or _has_emailed_us(contact_email)
                    _run_icp_and_route(lead_id, contact_email, is_inbound,
                                       email_doc.get("_id"))
            except Exception as ce:
                logger.debug(f"[mail-ai] contact ingest/route skipped: {ce}")
    except Exception as e:
        logger.warning(f"[mail-ai] contact ingestion unavailable: {e}")
    return ingested


_RFQ_ITEMS_SYSTEM = (
    "You convert a research-services request into clean quotation line items. "
    "Return ONLY JSON: {\"items\": [{\"description\": str, \"quantity\": number, "
    "\"rate\": number}]}. Use the buyer's stated numbers; never invent prices — "
    "use rate 0 when the price is unknown. Keep descriptions short and concrete "
    "(e.g. 'CATI interviews, urban India, n=500').")


def _smart_parse_rfq_items(rfq: Dict[str, Any],
                           email_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse RFQ line items with the SMART model (a human reads the resulting
    estimate). Falls back to the cheap analysis's own `items` on any failure.
    """
    cheap_items = [
        {"description": it["description"],
         "quantity": float(it.get("quantity") or 1),
         "rate": float(it.get("rate") or 0), "tax_amount": 0}
        for it in (rfq.get("items") or []) if it.get("description")
    ]
    try:
        bc = _bedrock()
        body = (email_doc.get("body_plain") or email_doc.get("body")
                or email_doc.get("snippet") or "")
        result = bc.converse_json_object(
            role=MAIL_AI_WRITER_ROLE, system=_RFQ_ITEMS_SYSTEM,
            user=(f"Request title: {rfq.get('title') or ''}\n"
                  f"Request description: {rfq.get('description') or ''}\n"
                  f"Currency: {rfq.get('currency') or 'unknown'}\n"
                  f"Original email:\n{str(body)[:3000]}\n\n"
                  f"Extract the quotation line items."),
            max_tokens=1500, temperature=0.0)
        parsed = [
            {"description": str(it["description"]).strip(),
             "quantity": float(it.get("quantity") or 1),
             "rate": float(it.get("rate") or 0), "tax_amount": 0}
            for it in ((result or {}).get("items") or [])
            if isinstance(it, dict) and it.get("description")
        ]
        if parsed:
            return parsed
    except Exception as e:
        logger.warning(f"[mail-ai] smart RFQ item parse failed, using cheap: {e}")
    return cheap_items


def _log_rfq_and_estimate(analysis: Dict[str, Any],
                          email_doc: Dict[str, Any]) -> Dict[str, Any]:
    """RFQ email -> spine opportunity+project AND a draft finance estimate."""
    out: Dict[str, Any] = {}
    rfq = analysis.get("rfq") or {}
    if not rfq.get("is_rfq"):
        return out

    from_email = (email_doc.get("from_email") or email_doc.get("from") or "").strip().lower()
    sender_company = None
    for c in (analysis.get("contacts") or []):
        if c.get("company"):
            sender_company = c["company"]
            break
    title = rfq.get("title") or f"RFQ: {email_doc.get('subject', 'email request')}"
    budget = rfq.get("budget") or 0

    # --- CRM spine: account/contact + opportunity + project ----------------
    try:
        try:
            from app.services import crm_service
        except ImportError:
            from backend.app.services import crm_service

        account_id = None
        if sender_company:
            account, _ = crm_service.get_or_create_account(
                sender_company, defaults={"account_type": "client",
                                          "metadata": {"source": "mail_pool_ai"}})
            account_id = account["_id"]
        contact_id = None
        if from_email:
            contact, _ = crm_service.get_or_create_contact(
                from_email, defaults={"name": email_doc.get("from_name"),
                                      "account_id": account_id,
                                      "metadata": {"source": "mail_pool_ai"}})
            contact_id = contact["_id"]

        rfq_result = crm_service.create_rfq({
            "title": title,
            "account_id": account_id,
            "contact_id": contact_id,
            "budget": budget,
            # AI-extracted currency was parsed but never carried past this
            # point, so every RFQ silently fell back to the spine's INR
            # default regardless of what the buyer actually asked in.
            "currency": rfq.get("currency"),
            "description": rfq.get("description"),
            "deadline": rfq.get("deadline"),
            "source_email_id": str(email_doc.get("_id")),
            # Research-brief fields the RFQ page's LOI/IR/N/Country columns
            # read from metadata.rfq — previously never extracted at all.
            "methodology": rfq.get("methodology"),
            "loi": rfq.get("loi"),
            "ir": rfq.get("ir"),
            "sample_size": rfq.get("sample_size"),
            "country": rfq.get("country"),
            "study_type": rfq.get("study_type"),
        })
        out["opportunity_id"] = rfq_result["opportunity"]["_id"]
        out["project_id"] = rfq_result["project"]["_id"]
    except Exception as e:
        logger.warning(f"[mail-ai] RFQ spine logging failed (non-fatal): {e}")

    # --- Finance: draft estimate for human review --------------------------
    try:
        finance_db = _get_db("finance_db")
        customers = finance_db["customers"]
        estimates = finance_db["estimates"]
        now = datetime.utcnow()

        customer_name = sender_company or email_doc.get("from_name") or from_email
        customer = customers.find_one({"name": customer_name})
        if not customer:
            ins = customers.insert_one({
                "name": customer_name,
                "customer_type": "business",
                "email": from_email,
                "status": "active",
                "source": "mail_pool_ai",
                "total_receivables": 0, "total_paid": 0,
                "created_at": now, "updated_at": now,
            })
            customer_id = str(ins.inserted_id)
        else:
            customer_id = str(customer["_id"])

        # Line items are parsed by the SMART model (a human reads the estimate);
        # falls back to the cheap analysis items, then to a single summary line.
        items = _smart_parse_rfq_items(rfq, email_doc)
        if not items:
            items = [{"description": rfq.get("description") or title,
                      "quantity": 1, "rate": float(budget or 0),
                      "tax_amount": 0}]
        subtotal = sum(i["quantity"] * i["rate"] for i in items)

        count = estimates.estimated_document_count() + 1
        estimate_doc = {
            "estimate_number": f"EST-{now.strftime('%Y%m')}-{str(count).zfill(4)}",
            "customer_id": customer_id,
            # Cross-link to the spine opportunity created above, so estimate
            # status changes can move the deal through the pipeline.
            "opportunity_id": out.get("opportunity_id"),
            "status": "draft",
            "items": items,
            "subtotal": subtotal,
            "tax_total": 0,
            "total_amount": subtotal,
            "currency_code": rfq.get("currency") or "INR",
            "notes": (f"Auto-drafted from RFQ email "
                      f"'{email_doc.get('subject', '')}'. "
                      f"AI summary: {analysis.get('summary', '')}"),
            "source": "mail_pool_ai",
            "source_email_id": str(email_doc.get("_id")),
            "created_at": now, "updated_at": now,
        }
        ins = estimates.insert_one(estimate_doc)
        out["estimate_id"] = str(ins.inserted_id)
        out["estimate_number"] = estimate_doc["estimate_number"]
    except Exception as e:
        logger.warning(f"[mail-ai] estimate draft failed (non-fatal): {e}")

    # Surface the RFQ in CRM notifications (best-effort)
    try:
        try:
            from app.services import crm_service
        except ImportError:
            from backend.app.services import crm_service
        crm_service.notify(
            "rfq_received",
            f"RFQ detected in mail pool: {title}"
            + (f" (est. {rfq.get('currency') or ''} {budget})" if budget else ""),
            link_object_type="opportunity",
            link_object_id=out.get("opportunity_id"),
            dedupe_key=f"rfq_email_{email_doc.get('_id')}")
    except Exception:
        pass

    return out


# A human/client reads these two outputs, so they use the SMART role.
_FOLLOWUP_SYSTEM = (
    "You draft concise, professional replies for a market-research company. "
    "Return ONLY JSON: {\"subject\": \"...\", \"body\": \"...\"}. Reply in the "
    "sender's language. Do not invent prices or commitments; propose a call or "
    "ask clarifying questions when specifics are missing.")


def _draft_follow_up(analysis: Dict[str, Any],
                     email_doc: Dict[str, Any]) -> Optional[str]:
    """Smart-model reply draft for follow_up_needed emails; stored for review."""
    if not analysis.get("follow_up_needed"):
        return None
    try:
        bc = _bedrock()
        try:
            draft = bc.converse_json_object(
                role=MAIL_AI_WRITER_ROLE, system=_FOLLOWUP_SYSTEM,
                user=(f"Original email from {email_doc.get('from_email', '')}:\n"
                      f"Subject: {email_doc.get('subject', '')}\n"
                      f"Summary: {analysis.get('summary', '')}\n"
                      f"Key points: {', '.join(analysis.get('key_points') or [])}\n\n"
                      f"Draft our reply."),
                max_tokens=1200, temperature=0.4)
        except Exception as e:
            logger.warning(f"[mail-ai] follow-up model call failed: {e}")
            return None
        if not draft or not draft.get("subject") or not draft.get("body"):
            return None
        col = _get_db("email_automation")[FOLLOWUP_COLLECTION]
        ins = col.insert_one({
            "source_email_id": str(email_doc.get("_id")),
            "to_email": email_doc.get("from_email") or email_doc.get("from"),
            "subject": draft.get("subject"),
            "body": draft.get("body"),
            "status": "draft",           # human review before send
            "category": analysis.get("category"),
            "priority": analysis.get("priority"),
            "created_at": datetime.utcnow(),
        })
        return str(ins.inserted_id)
    except Exception as e:
        logger.warning(f"[mail-ai] follow-up draft failed (non-fatal): {e}")
        return None


def process_email(email_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Full two-stage pipeline for one email.

    Stage 1 (rules, free): the rule prefilter decides if this email is worth a
    paid model call. Bank/Promotion/Transactional noise is marked skipped and
    never reaches Bedrock. Stage 2 (Bedrock, paid): everything else gets the
    full AI analysis + downstream actions.
    """
    # --- Stage 1: rule prefilter -------------------------------------------
    decision, rule_result = prefilter_decision(email_doc)
    if decision == "skip":
        skip_marker = {
            "skipped": True,
            "reason": "rule_prefilter",
            "rule_classification": rule_result,
            "analyzed_at": datetime.utcnow().isoformat(),
        }
        try:
            _get_db(MAIL_DB)[MAIL_COLLECTION].update_one(
                {"_id": email_doc["_id"]},
                {"$set": {"ai_analysis": skip_marker,
                          "segment": (rule_result.get("category") or "Others"),
                          "rule_classification": rule_result,
                          "segment_source": "rules",
                          "ai_processed_at": datetime.utcnow()}})
        except Exception as e:
            logger.warning("[mail-ai] could not persist prefilter skip: %s", e)
        logger.info("[mail-ai] email %s prefiltered out (segment=%s)",
                    email_doc.get("_id"), rule_result.get("segment"))
        return {"success": True, "skipped": True,
                "segment": rule_result.get("segment")}

    # --- Stage 2: AI mail-desk ---------------------------------------------
    analysis = analyze_email(email_doc)
    if analysis is None:
        return {"success": False, "error": "ai_analysis_failed"}
    analysis["rule_classification"] = rule_result

    actions: Dict[str, Any] = {}
    actions["contacts_ingested"] = _ingest_contacts(analysis, email_doc)
    actions.update(_log_rfq_and_estimate(analysis, email_doc))
    followup_id = _draft_follow_up(analysis, email_doc)
    if followup_id:
        actions["followup_draft_id"] = followup_id
    analysis["actions"] = actions

    # Single source of truth for the UI: AI category -> segment.
    segment, segment_source = derive_segment(analysis.get("category"), rule_result)

    try:
        _get_db(MAIL_DB)[MAIL_COLLECTION].update_one(
            {"_id": email_doc["_id"]},
            {"$set": {"ai_analysis": analysis,
                      "ai_summary": analysis.get("summary"),
                      "segment": segment,
                      "segment_source": segment_source,
                      "rule_classification": rule_result,
                      "ai_processed_at": datetime.utcnow()}})
    except Exception as e:
        logger.warning(f"[mail-ai] could not persist analysis: {e}")

    return {"success": True, "analysis": analysis,
            "segment": segment, "segment_source": segment_source}


MAX_FAILED_ATTEMPTS = 3   # skip an email/sender after this many failed analyses
SYSTEMIC_FAIL_PROBE = 5   # abort the run if this many items fail before any succeeds

# ============== SENDER-LEVEL PROCESSING ==============
# The pool's 361K emails come from only ~6.3K unique senders (one automated
# sender alone accounts for ~175K). One AI call per SENDER — fed a sample of
# their most recent emails — costs ~2% of per-email analysis and stamps every
# email from that sender at once.

SENDER_ANALYSIS_COLLECTION = "mail_sender_analysis"   # in email_automation
MAX_SAMPLE_EMAILS_PER_SENDER = int(os.getenv("MAIL_POOL_SENDER_SAMPLE", "3"))

# Deep RFQ scan: senders classified as real correspondents get ALL their mail
# read chronologically in chunks, so every RFQ in the history is found and
# followed to its outcome (quoted / won / lost). Automated/newsletter/spam
# senders are excluded — that's where the bulk of the volume (and none of the
# RFQs) lives.
RFQ_SCAN_CHUNK = int(os.getenv("MAIL_POOL_RFQ_SCAN_CHUNK", "10"))
MAX_SCAN_EMAILS_PER_SENDER = int(os.getenv("MAIL_POOL_MAX_SCAN_EMAILS", "1000"))
_HUMAN_SENDER_TYPES = {"client", "prospect", "vendor", "other"}

_SENDER_ANALYSIS_PROMPT = """Analyze each email below on its own merits, then summarize the sender.
Return ONLY valid JSON.

Sender: {from_line}
Total emails from this sender in our inbox: {total_count}
Emails (index 1 = newest):
{samples}

Each email body may be truncated and may contain quoted reply history,
signatures, and legal disclaimers. Classify based on what THIS sender wrote
in THIS email — ignore quoted text below reply markers, ignore signature
blocks, ignore boilerplate footers. If the new content is empty or unreadable,
set category_confidence to "low".

Return exactly this JSON shape:
{{
  "emails": [
    {{
      "index": <integer, matching the index above>,
      "summary": "<1-2 sentences: what THIS specific email says, not a description of the sender in general>",
      "category": "rfq|client_inquiry|vendor|reply|promotional|transactional|internal|bank|gov_tax|other",
      "category_confidence": "high|medium|low",
      "evidence": "<up to 12 words from this email that justify the category>",
      "sentiment": "positive|neutral|negative",
      "priority": "high|medium|low",
      "action_required": true|false,
      "follow_up_needed": true|false,
      "rfq": null
    }}
  ],
  "sender": {{
    "summary": "<2-3 sentences: who this sender is and what they want from us>",
    "key_points": ["<point>"],
    "sender_type": "client|prospect|vendor|internal|bank|gov_tax|automated|newsletter|spam|other",
    "sender_type_confidence": "high|medium|low",
    "mixed_mode": true|false,
    "contacts": [
      {{"name": <string or null>, "email": <string or null>, "phone": <string or null>,
       "company": <string or null>, "title": <string or null>}}
    ]
  }}
}}

For any email where category is "rfq", replace that email's "rfq": null with:
  {{
    "title": <string or null>,
    "description": <string or null>,
    "budget": <number or null>,
    "currency": <ISO 4217 code as string, or null>,
    "items": [{{"description": <string>, "quantity": <number>, "rate": <number>}}],
    "deadline": <ISO 8601 date string or null>,
    "methodology": <"CATI"|"CAWI"|"F2F"|"CAPI"|"Online Panel"|"IDI"|"Focus Group"|... or null>,
    "loi": <length of interview in minutes, integer, or null>,
    "ir": <incidence rate as a percentage number, or null>,
    "sample_size": <number of completes/respondents requested, integer, or null>,
    "country": <target country/market, string, or null>,
    "study_type": <"B2B"|"B2C"|"Healthcare"|"IT"|"Consumer"|"Other", or null>
  }}

Rules:
- Each email's own "summary" must describe what THAT email says (its actual
  request/content/ask), not a general description of who the sender is —
  the sender-level "summary" below is separate and covers the sender as a
  whole; do not just repeat it for every email.
- "rfq" means the sender is asking US to quote or propose for research work
  (sample, surveys, panel, fieldwork, translations, tabulation, incentives).
  An email SELLING us something is "vendor" or "promotional", never "rfq".
- Set category_confidence "low" rather than guessing. Never invent a category
  to avoid saying "other".
- "evidence" must be text actually present in that email. If you cannot find
  supporting text, the confidence is "low".
- "internal" = from our own organisation. "bank" = banking/payment
  notifications. "gov_tax" = GST, income tax, or other government filings.
  Judge these from the email content, not only the domain.
- "mixed_mode": true when these emails do not all serve the same purpose
  (e.g. a vendor who also sends RFQs, or a client whose mail is mostly
  automated notifications).
- follow_up_needed: true only when a reply from us is expected on that
  specific email. For automated, newsletter, or spam emails set
  follow_up_needed false and action_required false.
- contacts: only real people identifiable from the emails; [] if none.
- budget, quantity, rate: bare numbers only — no currency symbols, no commas,
  no ranges. If a range is given, use the lower bound. If unclear, use null."""


def _clean_email_body(body: str) -> str:
    """Strip quoted reply history / signatures / footers BEFORE truncation —
    doing this only via prompt instruction is not enough: if truncation cuts
    off the new content first, there's nothing left for the model to work
    with. Falls back to a plain slice if the cleaner is unavailable for any
    reason (never blocks analysis on this being importable)."""
    try:
        try:
            from outreach_engine.reply_engine.cleaner import clean_reply_text
        except ImportError:
            from backend.outreach_engine.reply_engine.cleaner import clean_reply_text
        return clean_reply_text(str(body))
    except Exception:
        return str(body)[:2000]


def analyze_sender(from_email: str, from_name: str, total_count: int,
                   sample_docs) -> Optional[Dict[str, Any]]:
    """One AI call covering a sender's recent emails, classified individually."""
    parts = []
    for idx, d in enumerate(sample_docs, start=1):
        body = (d.get("body_plain") or d.get("body") or d.get("snippet") or "")
        parts.append(
            f"--- Email {idx} (dated {d.get('date', 'unknown')}) ---\n"
            f"Subject: {d.get('subject') or '(no subject)'}\n"
            f"{_clean_email_body(body)}"
        )
    prompt = _SENDER_ANALYSIS_PROMPT.format(
        from_line=f"{from_name} <{from_email}>".strip(),
        total_count=total_count,
        samples="\n\n".join(parts) or "(no body available)",
    )
    result, meta = _analysis_json(
        prompt, MAIL_AI_ANALYSIS_MAX_TOKENS, caller="analyze_sender")
    if result is not None and (not isinstance(result.get("emails"), list)
                               or not isinstance(result.get("sender"), dict)):
        # Valid JSON, wrong shape — distinct from _analysis_json's own
        # "unparseable" log (which only fires on a JSON *parse* failure).
        # Log this too, or a shape mismatch fails silently with no trail.
        logger.warning("[mail-ai] analyze_sender got valid JSON in an "
                       "unexpected shape (missing emails/sender): keys=%s",
                       list(result.keys()) if isinstance(result, dict) else type(result))
        return None
    if result is None:
        return None
    result["analyzed_at"] = datetime.utcnow().isoformat()
    result["model_source"] = "bedrock"
    result["meta"] = meta            # model_id + token usage for cost auditing
    result["sample_size"] = len(sample_docs)
    result["total_emails"] = total_count
    return result


_RFQ_SCAN_PROMPT = """You are the RFQ auditor for a market-research company (surveys, panels, fieldwork).
You are reading through ALL emails from one sender in chronological order, in chunks.
Identify every RFQ (request for quotation/proposal/pricing for research work) and
track each one's outcome across the thread. Return ONLY valid JSON, no markdown.

Sender: {from_line}

RFQs already identified in earlier chunks (still open):
{open_ledger}

Emails in this chunk (oldest first):
{emails}

Return exactly this JSON shape:
{{
  "new_rfqs": [
    {{"ref": "<short-unique-slug-you-invent>",
      "title": "<short title>", "description": "<what is requested>",
      "budget": <number or null>, "currency": "<ISO code or null>",
      "items": [{{"description": "<line item>", "quantity": <number>, "rate": <number or 0>}}],
      "deadline": "<ISO date or null>", "email_date": "<date of the email>",
      "status": "open|quoted|won|lost",
      "evidence": "<one sentence quoting/paraphrasing the deciding email>",
      "methodology": "<CATI|CAWI|F2F|CAPI|Online Panel|IDI|Focus Group|... or null>",
      "loi": <length of interview in minutes, integer, or null>,
      "ir": <incidence rate as a percentage number, or null>,
      "sample_size": <number of completes/respondents requested, integer, or null>,
      "country": "<target country/market, or null>",
      "study_type": "<B2B|B2C|Healthcare|IT|Consumer|Other, or null>"}}
  ],
  "rfq_updates": [
    {{"ref": "<ref of a previously identified RFQ>",
      "status": "quoted|won|lost",
      "evidence": "<one sentence: what in this chunk changed the status>"}}
  ]
}}

Rules:
- An RFQ is the SENDER asking US for pricing/proposal/feasibility on research
  work (sample, surveys, panel, fieldwork, translation, coding etc.).
  Promotional mail SELLING to us is never an RFQ.
- "won": the sender awarded/confirmed the work to us (PO, "please proceed",
  "you are awarded", cost approval). "lost": explicitly went elsewhere or
  cancelled. "quoted": we sent pricing and they acknowledged, no decision yet.
- Use rfq_updates when a chunk email resolves an RFQ from the open ledger.
- [] for both lists when the chunk has no RFQ activity."""


def _scan_chunk(from_line: str, open_ledger, chunk_docs) -> Optional[Dict[str, Any]]:
    """One AI call over a chronological chunk of a sender's emails."""
    ledger_lines = [
        f"- ref={r['ref']} | {r.get('title')} | status={r.get('status')}"
        for r in open_ledger if r.get("status") not in ("won", "lost")
    ][:20] or ["(none)"]
    email_parts = []
    for d in chunk_docs:
        body = (d.get("body_plain") or d.get("body") or d.get("snippet") or "")
        email_parts.append(
            f"--- {d.get('date', 'unknown')} | Subject: {d.get('subject') or '(no subject)'} ---\n"
            f"{str(body)[:1500]}")
    prompt = _RFQ_SCAN_PROMPT.format(
        from_line=from_line,
        open_ledger="\n".join(ledger_lines),
        emails="\n\n".join(email_parts),
    )
    # RFQ scan reads sender history for quote intent — analysis (cheap) role.
    bc = _bedrock()
    try:
        result, _meta = bc.converse_json_meta(
            role=MAIL_AI_ANALYSIS_ROLE, system=_MAIL_AI_SYSTEM, user=prompt,
            max_tokens=MAIL_AI_SCAN_MAX_TOKENS, temperature=0.0)
        return result if isinstance(result, dict) else None
    except Exception as e:
        logger.warning("[mail-ai] RFQ scan chunk call failed: %s", e)
        return None


_STATUS_TO_STAGE = {"quoted": "proposal", "won": "won", "lost": "lost"}


def _apply_rfq_stage(entry: Dict[str, Any]) -> None:
    """Move the logged opportunity to the stage matching the scanned status."""
    stage = _STATUS_TO_STAGE.get(entry.get("status"))
    opp_id = entry.get("opportunity_id")
    if not stage or not opp_id:
        return
    try:
        try:
            from app.services import crm_service
        except ImportError:
            from backend.app.services import crm_service
        crm_service.set_opportunity_stage(
            opp_id, stage,
            loss_reason=(entry.get("evidence") or "per email thread")
            if stage == "lost" else None,
            changed_by="mail_pool_ai")
    except Exception as e:
        logger.warning(f"[mail-ai] stage update failed for {opp_id}: {e}")


def deep_scan_sender_rfqs(from_email: str, from_name: str, col,
                          sender_col) -> Dict[str, Any]:
    """Read ALL of a sender's emails chronologically, log every RFQ on the
    CRM spine (+ draft estimate), and set won/lost/quoted stages.

    Incremental and resumable: scan position (last email date) and the RFQ
    ledger persist on the sender's mail_sender_analysis doc, so new mail
    only scans the delta and a mid-scan failure resumes where it stopped."""
    state = (sender_col.find_one({"_id": from_email}) or {}).get("rfq_scan", {})
    ledger = state.get("ledger", [])
    last_date = state.get("last_scanned_date")

    query: Dict[str, Any] = {"from_email": from_email}
    if last_date:
        query["date"] = {"$gt": last_date}
    docs = list(col.find(
        query, {"subject": 1, "date": 1, "body_plain": 1, "body": 1,
                "snippet": 1, "from_name": 1}
    ).sort("date", 1).limit(MAX_SCAN_EMAILS_PER_SENDER))
    if not docs:
        return {"scanned": 0, "rfqs_logged": 0, "rfqs_won": 0}

    from_line = f"{from_name} <{from_email}>".strip()
    newest_doc = docs[-1]
    scanned = 0
    by_ref = {r["ref"]: r for r in ledger if r.get("ref")}

    for i in range(0, len(docs), RFQ_SCAN_CHUNK):
        chunk = docs[i:i + RFQ_SCAN_CHUNK]
        result = _scan_chunk(from_line, ledger, chunk)
        if not isinstance(result, dict):
            logger.warning(f"[mail-ai] RFQ scan chunk failed for {from_email} "
                           f"— stopping; resume point persisted")
            break
        for rfq in (result.get("new_rfqs") or []):
            if not rfq.get("ref") or rfq["ref"] in by_ref:
                continue
            rfq.setdefault("status", "open")
            ledger.append(rfq)
            by_ref[rfq["ref"]] = rfq
        for upd in (result.get("rfq_updates") or []):
            entry = by_ref.get(upd.get("ref"))
            if entry and upd.get("status"):
                entry["status"] = upd["status"]
                entry["evidence"] = upd.get("evidence") or entry.get("evidence")
        scanned += len(chunk)
        # Persist progress after every chunk — a crash or credit outage
        # resumes from here instead of re-reading (and re-paying for) mail.
        sender_col.update_one(
            {"_id": from_email},
            {"$set": {"rfq_scan.ledger": ledger,
                      "rfq_scan.last_scanned_date": chunk[-1].get("date"),
                      "rfq_scan.scanned_at": datetime.utcnow()}},
            upsert=True)

    # Log every RFQ not yet on the spine, then apply its current stage.
    logged = won = 0
    for entry in ledger:
        if not entry.get("opportunity_id"):
            synth = {"rfq": {**entry, "is_rfq": True}, "contacts": [],
                     "summary": entry.get("evidence") or entry.get("description")}
            out = _log_rfq_and_estimate(synth, newest_doc)
            if out.get("opportunity_id"):
                entry["opportunity_id"] = out["opportunity_id"]
                entry["estimate_id"] = out.get("estimate_id")
                entry["stage_applied"] = None
                logged += 1
        if entry.get("opportunity_id") and \
                entry.get("stage_applied") != entry.get("status"):
            _apply_rfq_stage(entry)
            entry["stage_applied"] = entry.get("status")
        if entry.get("status") == "won":
            won += 1
    sender_col.update_one(
        {"_id": from_email}, {"$set": {"rfq_scan.ledger": ledger}}, upsert=True)

    return {"scanned": scanned, "rfqs_logged": logged, "rfqs_won": won,
            "rfqs_total": len(ledger)}


def _rollup_from_sender_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reduce the new per-email {emails: [...], sender: {...}} shape down to the
    flat dict _ingest_contacts()/_log_rfq_and_estimate()/_draft_follow_up()
    already expect (the same shape process_email() and
    deep_scan_sender_rfqs()'s synthesized dicts use) — a single normalization
    point so those three functions never need to know about the nested shape.

    Rollup rule: the newest sampled email's category wins, UNLESS any sampled
    email is an "rfq" — an RFQ anywhere in the sample always wins, so a
    request hiding behind newer newsletters is never diluted away.
    """
    emails = analysis.get("emails") or []
    sender = analysis.get("sender") or {}
    rfq_emails = [e for e in emails if e.get("category") == "rfq" and e.get("rfq")]

    if rfq_emails:
        category = "rfq"
    elif emails:
        category = emails[0].get("category")
    else:
        category = None

    if rfq_emails:
        rfq = {**rfq_emails[0]["rfq"], "is_rfq": True}
    else:
        rfq = {"is_rfq": False}

    return {
        "category": category,
        "sender_type": sender.get("sender_type"),
        "summary": sender.get("summary"),
        "key_points": sender.get("key_points"),
        "contacts": sender.get("contacts") or [],
        "follow_up_needed": bool(emails[0].get("follow_up_needed")) if emails else False,
        "rfq": rfq,
        "rfq_emails": rfq_emails,
    }


def process_sender(from_email: str, col) -> Dict[str, Any]:
    """Full AI pipeline for one sender: analyze a sample of their newest
    emails (classified individually), run downstream actions once from the
    code-derived rollup, then stamp ALL their unanalyzed emails so they never
    re-enter the queue."""
    base_query = {"from_email": from_email,
                  "ai_analysis": {"$exists": False},
                  "internal": {"$ne": True}}
    sample = list(col.find(base_query).sort("date", -1)
                  .limit(MAX_SAMPLE_EMAILS_PER_SENDER))
    if not sample:
        return {"success": False, "error": "no_emails"}
    total_count = col.count_documents({"from_email": from_email})
    newest = sample[0]

    analysis = analyze_sender(
        from_email, newest.get("from_name") or "", total_count, sample)
    if analysis is None:
        return {"success": False, "error": "ai_analysis_failed"}

    flat = _rollup_from_sender_analysis(analysis)

    # Downstream actions run once per sender, anchored on their newest email.
    actions: Dict[str, Any] = {}
    actions["contacts_ingested"] = _ingest_contacts(flat, newest)
    sender_col = _get_db("email_automation")[SENDER_ANALYSIS_COLLECTION]
    # An RFQ anywhere in the sample forces the human/deep-scan path even when
    # the sender's overall type reads as newsletter/automated — this is the
    # actual fix for "an RFQ behind three newsletters" getting missed.
    # BUT the sample is only the newest MAX_SAMPLE_EMAILS_PER_SENDER (3) —
    # if none of those 3 happen to be the RFQ, and the model reads the
    # sender's overall type as e.g. "automated"/"newsletter"/"bank" from
    # just those 3, is_human was False and this sender's ENTIRE mailbox
    # (including any older email that literally says "RFQ"/"quote") got
    # stamped "analyzed" via the update_many below and never looked at
    # again. Widen the trigger: a cheap keyword pre-screen across every
    # UNANALYZED email from this sender (not just the sample) forces the
    # full deep-scan whenever any of them look RFQ-shaped. This doesn't
    # violate "no keyword-based RFQ classification" (mail_pool_ai.py's own
    # docstring, by design) — the AI in deep_scan_sender_rfqs still makes
    # the actual is-this-really-an-RFQ call; keywords only decide whether
    # it's worth looking.
    has_rfq_signal_words = bool(col.count_documents({
        **base_query,
        "$or": [
            {"subject": _RFQ_SIGNAL_REGEX},
            {"body_plain": _RFQ_SIGNAL_REGEX},
            {"body": _RFQ_SIGNAL_REGEX},
            {"snippet": _RFQ_SIGNAL_REGEX},
        ],
    }, limit=1))
    is_human = (flat["sender_type"] in _HUMAN_SENDER_TYPES
                or bool(flat["rfq_emails"])
                or has_rfq_signal_words)
    if is_human:
        # Real correspondent: read their FULL history for RFQs and outcomes.
        # This supersedes the sample-based rfq field (which would only
        # double-log the newest request).
        try:
            scan = deep_scan_sender_rfqs(
                from_email, newest.get("from_name") or "", col, sender_col)
            actions["rfq_scan"] = scan
        except Exception as e:
            logger.warning(f"[mail-ai] deep RFQ scan failed for {from_email}: {e}")
    else:
        # Not deep-scanned, so the sampled emails are the only chance to log
        # any RFQs in them — log each one, not just the rollup winner.
        for rfq_email in flat["rfq_emails"]:
            rfq_flat = {**flat, "rfq": {**rfq_email["rfq"], "is_rfq": True}}
            actions.update(_log_rfq_and_estimate(rfq_flat, newest))
    followup_id = _draft_follow_up(flat, newest)
    if followup_id:
        actions["followup_draft_id"] = followup_id
    analysis["actions"] = actions

    # Single source of truth for the UI (sender path has no per-email rule
    # prefilter, so the segment derives from the AI category alone).
    segment, segment_source = derive_segment(flat["category"], None)
    segment_ai_raw = flat["category"]
    override_applied = segment_source == "rules" and flat["category"] not in (None, "", "other")

    # Flat mirror onto the same `analysis` doc so gmail.py's
    # _sender_contacts_and_rfq()/_batch_sender_contacts_and_rfq() (which read
    # analysis.contacts / analysis.rfq as plain dotted paths) keep working
    # unchanged — analysis carries both the raw emails/sender detail AND this
    # flat mirror.
    analysis["contacts"] = flat["contacts"]
    analysis["rfq"] = flat["rfq"]
    analysis["category"] = flat["category"]

    # Full analysis lives in one doc per sender ...
    sender_col.update_one(
        {"_id": from_email},
        {"$set": {"analysis": analysis, "status": "analyzed",
                  "segment_ai_raw": segment_ai_raw,
                  "override_applied": override_applied,
                  "updated_at": datetime.utcnow()},
         "$unset": {"failed_attempts": ""}},
        upsert=True)

    # ... while every email from the sender gets a compact stub, so existing
    # per-email consumers (ai_analysis-exists queries, ai_summary display)
    # keep working without duplicating the full analysis 175K times.
    stub = {"sender_level": True, "sender": from_email,
            "summary": flat.get("summary"),
            "sender_type": flat.get("sender_type"),
            "category": flat.get("category"),
            "analyzed_at": analysis["analyzed_at"],
            "meta": analysis.get("meta"),   # model_id + tokens for cost auditing
            "segment_ai_raw": segment_ai_raw,
            "override_applied": override_applied}

    # The sampled emails were each individually read by the model and have
    # their own "summary" (what THAT email actually says) — write it back
    # per-doc instead of blanket-overwriting every email from this sender
    # with the one generic sender-level summary. Previously ai_summary was
    # set identically on every email from a sender via a single
    # update_many, so a sender with 50 emails showed the same "who this
    # sender is" blurb on all 50 instead of each mail's own content.
    per_email_by_index = {
        e.get("index"): e for e in (analysis.get("emails") or [])
        if isinstance(e, dict)
    }
    sampled_ids = []
    for idx, doc in enumerate(sample, start=1):
        sampled_ids.append(doc["_id"])
        e = per_email_by_index.get(idx)
        own_summary = (e or {}).get("summary") or flat.get("summary")
        own_category = (e or {}).get("category") or flat.get("category")
        own_segment, own_segment_source = derive_segment(own_category, None)
        col.update_one(
            {"_id": doc["_id"]},
            {"$set": {"ai_analysis": {**stub, "own_summary": True,
                                       "category": own_category},
                      "ai_summary": own_summary,
                      "segment": own_segment,
                      "segment_source": own_segment_source,
                      "ai_processed_at": datetime.utcnow()}})

    # The rest of this sender's mail was never individually read (only the
    # newest MAX_SAMPLE_EMAILS_PER_SENDER were) — stamp those with the
    # sender-level rollup as a triage approximation, not a per-email
    # summary. RFQ coverage for this remainder is NOT lost: the deep-scan
    # safety net above (is_human, widened by the RFQ keyword pre-screen)
    # reads every one of a sender's emails chronologically regardless of
    # whether they were in this sample.
    marked = col.update_many(
        {**base_query, "_id": {"$nin": sampled_ids}},
        {"$set": {"ai_analysis": stub,
                  "ai_summary": flat.get("summary"),
                  "segment": segment,
                  "segment_source": segment_source,
                  "ai_processed_at": datetime.utcnow()}}).modified_count

    return {"success": True, "analysis": analysis,
            "emails_marked": marked + len(sampled_ids)}


def process_sender_batch(limit: int = 50) -> Dict[str, Any]:
    """Process up to `limit` senders with unanalyzed mail (most recent first).

    Same failure policy as process_batch, at sender granularity: a failing
    sender is skipped after MAX_FAILED_ATTEMPTS; an all-fail run aborts early
    as a systemic outage without burning any sender's attempt budget.
    """
    col = _get_db(MAIL_DB)[MAIL_COLLECTION]
    sender_col = _get_db("email_automation")[SENDER_ANALYSIS_COLLECTION]

    skip_senders = {d["_id"] for d in sender_col.find(
        {"failed_attempts": {"$gte": MAX_FAILED_ATTEMPTS}}, {"_id": 1})}

    candidates = col.aggregate([
        {"$match": {"ai_analysis": {"$exists": False},
                    "internal": {"$ne": True},
                    "from_email": {"$exists": True, "$nin": [None, ""]}}},
        {"$group": {"_id": "$from_email", "latest": {"$max": "$date"},
                    "n": {"$sum": 1}}},
        {"$sort": {"latest": -1}},
        {"$limit": limit + len(skip_senders)},
    ], allowDiskUse=True)

    processed = failed = rfqs = rfqs_won = emails_covered = 0
    failed_senders = []
    aborted = False
    for cand in candidates:
        if processed + failed >= limit:
            break
        sender = cand["_id"]
        if sender in skip_senders:
            continue
        try:
            r = process_sender(sender, col)
            if r.get("success"):
                processed += 1
                emails_covered += r.get("emails_marked", 0)
                scan = (r["analysis"].get("actions") or {}).get("rfq_scan") or {}
                if scan:
                    rfqs += scan.get("rfqs_logged", 0)
                    rfqs_won += scan.get("rfqs_won", 0)
                elif (r["analysis"].get("rfq") or {}).get("is_rfq"):
                    rfqs += 1
            else:
                failed += 1
                failed_senders.append(sender)
        except MailAIThrottled as e:
            # Systemic throttle/outage: stop now, mark no sender failed.
            logger.error("[mail-ai] Bedrock throttled/outage — stopping sender "
                         "run, leaving senders unmarked for retry: %s", e)
            aborted = True
            failed_senders = []   # nothing marked on a throttle
            break
        except Exception as e:
            failed += 1
            failed_senders.append(sender)
            logger.warning(f"[mail-ai] sender batch item failed: {e}")
        if processed == 0 and failed >= SYSTEMIC_FAIL_PROBE:
            aborted = True
            logger.error(
                f"[mail-ai] first {failed} senders all failed — treating as a "
                f"systemic outage (API key/quota?), aborting batch without "
                f"marking senders failed")
            break
    if processed > 0 and failed_senders:
        try:
            for s in failed_senders:
                sender_col.update_one(
                    {"_id": s},
                    {"$inc": {"failed_attempts": 1},
                     "$set": {"last_failed_at": datetime.utcnow()}},
                    upsert=True)
        except Exception as e:
            logger.warning(f"[mail-ai] could not mark failed senders: {e}")
    return {"senders_processed": processed, "failed": failed,
            "emails_covered": emails_covered, "rfqs_detected": rfqs,
            "rfqs_won": rfqs_won, "aborted_systemic": aborted}


# Senders needing a rebuild scan: no rfq_scan ledger yet, or it was emptied
# by scripts/clear_rfq_data.py (which unsets ledger/last_scanned_date but
# leaves the sender doc — including its ai_analysis/segment work — intact).
_REBUILD_CANDIDATE_QUERY = {
    "$or": [
        {"rfq_scan.ledger": {"$exists": False}},
        {"rfq_scan.ledger": []},
    ],
    "rfq_rebuild_done": {"$ne": True},
}


def rebuild_rfqs_for_all_senders(limit: int = 50) -> Dict[str, Any]:
    """
    One-time backfill driver for POST /rfq/resync-all.

    Re-runs deep_scan_sender_rfqs() — unchanged, same extraction/logging/
    won-lost-stage logic process_sender() already uses for new mail — across
    every sender whose rfq_scan ledger is empty, instead of only newly
    arriving mail. Intended to run after scripts/clear_rfq_data.py, which
    resets the ledger on senders whose RFQs it deleted.

    Resumable and rate-limited the same way as process_sender_batch: call
    this repeatedly (e.g. every 30s from a small loop, or via a few manual
    POSTs) with a small `limit`; it naturally drains as `rfq_rebuild_done`
    gets stamped on each sender, and `remaining` in the return value tells
    the caller when to stop.
    """
    col = _get_db(MAIL_DB)[MAIL_COLLECTION]
    sender_col = _get_db("email_automation")[SENDER_ANALYSIS_COLLECTION]

    candidates = list(sender_col.find(_REBUILD_CANDIDATE_QUERY, {"_id": 1}).limit(limit))

    scanned = logged = won = failed = 0
    for cand in candidates:
        sender = cand["_id"]
        try:
            from_doc = col.find_one({"from_email": sender}, {"from_name": 1})
            from_name = (from_doc or {}).get("from_name") or ""
            result = deep_scan_sender_rfqs(sender, from_name, col, sender_col)
            scanned += 1
            logged += result.get("rfqs_logged", 0)
            won += result.get("rfqs_won", 0)
            # Stamp done even at 0 RFQs found, so a non-RFQ sender is never
            # rescanned (and re-billed) on a later call.
            sender_col.update_one({"_id": sender}, {"$set": {"rfq_rebuild_done": True}})
        except Exception as e:
            failed += 1
            logger.warning(f"[mail-ai] rebuild scan failed for {sender}: {e}")

    remaining = sender_col.count_documents(_REBUILD_CANDIDATE_QUERY)
    return {
        "senders_scanned": scanned, "failed": failed,
        "rfqs_logged": logged, "rfqs_won": won,
        "remaining": remaining,
    }


def ai_stats() -> Dict[str, Any]:
    """
    Operational stats for GET /api/mail/ai-stats:
      - counts: processed (real AI analysis), prefiltered (rule-skipped),
        pending (unanalyzed, non-internal)
      - disagreement rate between rules and AI (last 7 days, from the audit log)
      - cumulative token usage by model over the last 7 days
    """
    from datetime import timedelta
    col = _get_db(MAIL_DB)[MAIL_COLLECTION]
    audit_col = _get_db("email_automation")[PREFILTER_AUDIT_COLLECTION]
    week_ago = datetime.utcnow() - timedelta(days=7)

    prefiltered = col.count_documents({"ai_analysis.skipped": True})
    total_analyzed = col.count_documents({"ai_analysis": {"$exists": True}})
    processed = total_analyzed - prefiltered
    pending = col.count_documents(
        {"ai_analysis": {"$exists": False}, "internal": {"$ne": True}})

    # Token usage by model over the last 7 days (from ai_analysis.meta).
    usage_by_model: Dict[str, Dict[str, int]] = {}
    try:
        for row in col.aggregate([
            {"$match": {"ai_processed_at": {"$gte": week_ago},
                        "ai_analysis.meta.model_id": {"$exists": True}}},
            {"$group": {"_id": "$ai_analysis.meta.model_id",
                        "input_tokens": {"$sum": "$ai_analysis.meta.input_tokens"},
                        "output_tokens": {"$sum": "$ai_analysis.meta.output_tokens"},
                        "total_tokens": {"$sum": "$ai_analysis.meta.total_tokens"},
                        "calls": {"$sum": 1}}},
        ], allowDiskUse=True):
            usage_by_model[row["_id"] or "unknown"] = {
                "input_tokens": int(row.get("input_tokens") or 0),
                "output_tokens": int(row.get("output_tokens") or 0),
                "total_tokens": int(row.get("total_tokens") or 0),
                "calls": int(row.get("calls") or 0),
            }
    except Exception as e:
        logger.warning("[mail-ai] token usage aggregation failed: %s", e)

    # Rule/AI disagreement rate from the nightly prefilter audit run summaries
    # (last 7 days). checked = total re-checked, disagreements = flagged as
    # real correspondence the rules wrongly skipped.
    checked = disagreements = 0
    for s in audit_col.find({"kind": "run_summary",
                             "run_at": {"$gte": week_ago}}):
        checked += int(s.get("checked") or 0)
        disagreements += int(s.get("disagreements") or 0)
    rate = round(disagreements / checked, 4) if checked else None

    return {
        "counts": {"processed": processed, "prefiltered": prefiltered,
                   "pending": pending, "total_analyzed": total_analyzed},
        "prefilter_audit_7d": {"checked": checked, "disagreements": disagreements,
                               "disagreement_rate": rate},
        "token_usage_7d_by_model": usage_by_model,
        "window_days": 7,
    }


def audit_prefiltered_sample(n: int = MAIL_AI_PREFILTER_AUDIT_SAMPLE) -> Dict[str, Any]:
    """
    Nightly safety net: sample N random emails the rule prefilter skipped and
    run them through the cheap model anyway. If the model thinks a skipped
    email is real correspondence (rfq/client/reply/vendor), that's a
    disagreement — the rules may be silently eating client mail. Records every
    disagreement to mail_ai_prefilter_audit for review.

    Read-only w.r.t. the email's own ai_analysis (never overwrites the skip
    marker) — this is monitoring, not reprocessing.
    """
    col = _get_db(MAIL_DB)[MAIL_COLLECTION]
    audit_col = _get_db("email_automation")[PREFILTER_AUDIT_COLLECTION]
    sample = list(col.aggregate([
        {"$match": {"ai_analysis.skipped": True,
                    "ai_analysis.reason": "rule_prefilter"}},
        {"$sample": {"size": max(1, n)}},
    ]))
    checked = disagreements = 0
    for doc in sample:
        analysis = analyze_email(doc)
        if analysis is None:
            continue
        checked += 1
        ai_category = (analysis.get("category") or "").lower()
        rule_segment = ((doc.get("ai_analysis") or {})
                        .get("rule_classification", {}).get("segment"))
        if ai_category in _MEANINGFUL_AI_CATEGORIES:
            disagreements += 1
            audit_col.insert_one({
                "email_id": doc["_id"],
                "rule_segment": rule_segment,
                "ai_category": ai_category,
                "ai_summary": analysis.get("summary"),
                "detected_at": datetime.utcnow(),
            })
            logger.info("[mail-ai] PREFILTER DISAGREEMENT email=%s "
                        "rule_segment=%s ai_category=%s — rules may be eating "
                        "real mail", doc.get("_id"), rule_segment, ai_category)
    # Persist a run summary so ai_stats() can compute the disagreement RATE
    # (the per-email records above only capture the disagreements themselves).
    try:
        audit_col.insert_one({"kind": "run_summary", "checked": checked,
                              "disagreements": disagreements,
                              "sampled": len(sample),
                              "run_at": datetime.utcnow()})
    except Exception:
        pass
    logger.info("[mail-ai] prefilter audit: checked=%d disagreements=%d",
                checked, disagreements)
    return {"checked": checked, "disagreements": disagreements,
            "sampled": len(sample)}


def process_batch(limit: int = MAIL_AI_MAX_PER_RUN) -> Dict[str, Any]:
    """Process up to `limit` unanalyzed mail-pool emails, OLDEST first.

    Failure handling:
    - Bedrock throttling / outage (MailAIThrottled): stop the run immediately
      and mark NOTHING — the email stays unmarked (no ai_analysis, no burned
      attempt) so the next beat retries it. Never a partial ai_analysis.
    - Per-email content failure: a doc that fails to parse gets
      ai_failed_attempts incremented and is skipped once it reaches
      MAX_FAILED_ATTEMPTS, so one poison message can't wedge the queue.
    - Systemic (many content failures before any success): abort early and
      mark nothing, so a broad problem doesn't burn attempt-budget pool-wide.
    """
    col = _get_db(MAIL_DB)[MAIL_COLLECTION]
    processed = failed = rfqs = 0
    failed_ids = []
    aborted = throttled = False
    cursor = col.find(
        {"ai_analysis": {"$exists": False},
         "internal": {"$ne": True},           # skip internal/own-domain mail
         "ai_failed_attempts": {"$not": {"$gte": MAX_FAILED_ATTEMPTS}}},
    ).sort("date", 1).limit(limit)    # oldest-unanalyzed first
    for doc in cursor:
        try:
            r = process_email(doc)
            if r.get("success"):
                processed += 1
                if ((r.get("analysis") or {}).get("rfq") or {}).get("is_rfq"):
                    rfqs += 1
            else:
                failed += 1
                failed_ids.append(doc["_id"])
        except MailAIThrottled as e:
            throttled = True
            logger.error("[mail-ai] Bedrock throttled/outage — stopping run, "
                         "leaving remaining emails unmarked for retry: %s", e)
            break
        except Exception as e:
            failed += 1
            failed_ids.append(doc["_id"])
            logger.warning(f"[mail-ai] batch item failed: {e}")
        if processed == 0 and failed >= SYSTEMIC_FAIL_PROBE:
            aborted = True
            logger.error(
                f"[mail-ai] first {failed} items all failed — treating as a "
                f"systemic issue, aborting batch without marking emails failed")
            break
    # Only mark content failures (never throttled/systemic, which mark nothing).
    if processed > 0 and failed_ids and not aborted:
        try:
            col.update_many(
                {"_id": {"$in": failed_ids}},
                {"$inc": {"ai_failed_attempts": 1},
                 "$set": {"ai_last_failed_at": datetime.utcnow()}})
        except Exception as e:
            logger.warning(f"[mail-ai] could not mark failed emails: {e}")
    return {"processed": processed, "failed": failed, "rfqs_detected": rfqs,
            "aborted_systemic": aborted, "throttled": throttled}
