"""
MAIL POOL AI PROCESSING
=======================
AI layer over the Gmail mail pool (torpedo_gmail.email_metadata). For each
email, ONE combined Claude call (via the governed ai_governance gateway)
produces:

  - summary + key points + sentiment
  - category / priority / action-required classification
  - extracted contacts (signature/body) -> routed through canonical ingestion
  - RFQ detection -> logged on the CRM spine (opportunity + project via
    crm_service.create_rfq) AND a draft estimate in finance_db.estimates
  - follow-up flag -> AI-drafted reply stored in mail_followup_drafts

Results are stored on the email doc under `ai_analysis` (idempotency marker)
so each email is processed once. All downstream actions are best-effort and
non-fatal: a failed RFQ mirror never loses the summary.

The regex-only extractor (sales/mail_pool_extractor.py) remains the fallback
when AI is unavailable.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MAIL_DB = "torpedo_gmail"
MAIL_COLLECTION = "email_metadata"

# Per-email summarize/extract is simple, high-volume JSON work — Haiku-tier.
# At $1/$5 per MTok vs Opus's $5/$25, the 361K-email backlog costs ~5x less.
MAIL_POOL_AI_MODEL = os.getenv("MAIL_POOL_AI_MODEL", "claude-haiku-4-5")
FOLLOWUP_COLLECTION = "mail_followup_drafts"  # stored in email_automation

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
    "currency": "<ISO code or null>",
    "items": [{{"description": "<line item>", "quantity": <number>, "rate": <number or 0>}}],
    "deadline": "<ISO date or null>"
  }}
}}

Rules:
- "rfq" means the sender is requesting a quotation/proposal/pricing for research
  work (sample, surveys, panel, fieldwork, translations etc.). A promotional
  email SELLING something is never an RFQ.
- contacts: only real external people evident in the email; [] if none.
- follow_up_needed: true when a reply from us is clearly expected."""


def _gateway():
    try:
        from ai_governance.claude_gateway import get_claude_gateway
    except ImportError:
        from backend.ai_governance.claude_gateway import get_claude_gateway
    return get_claude_gateway()


def _get_db(name: str):
    try:
        from db_pools import get_db
    except ImportError:
        from backend.db_pools import get_db
    return get_db(name)


def analyze_email(email_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run the combined AI analysis for one mail-pool email doc."""
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
    result = _gateway().generate_json(
        prompt, model=MAIL_POOL_AI_MODEL, max_tokens=4000,
        task_type="mail_pool_analysis", caller="sales.mail_pool_ai",
    )
    if not isinstance(result, dict) or "summary" not in result:
        return None
    result["analyzed_at"] = datetime.utcnow().isoformat()
    result["model_source"] = "claude_gateway"
    return result


def _ingest_contacts(analysis: Dict[str, Any], email_doc: Dict[str, Any]) -> int:
    """Route AI-extracted contacts through canonical lead ingestion."""
    ingested = 0
    contacts = analysis.get("contacts") or []
    try:
        try:
            from leads.canonical_ingestion import ingest_lead
        except ImportError:
            from backend.leads.canonical_ingestion import ingest_lead
        for c in contacts:
            if not (c.get("email") or "").strip():
                continue
            try:
                r = ingest_lead({
                    "email": c.get("email"),
                    "name": c.get("name"),
                    "company": c.get("company"),
                    "title": c.get("title"),
                    "phone": c.get("phone"),
                    "subject": email_doc.get("subject"),
                    "notes": analysis.get("summary"),
                }, source="gmail", source_detail="mail_pool_ai") or {}
                if r.get("success"):
                    ingested += 1
            except Exception as ce:
                logger.debug(f"[mail-ai] contact ingest skipped: {ce}")
    except Exception as e:
        logger.warning(f"[mail-ai] contact ingestion unavailable: {e}")
    return ingested


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
            "description": rfq.get("description"),
            "deadline": rfq.get("deadline"),
            "source_email_id": str(email_doc.get("_id")),
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

        items = []
        for it in (rfq.get("items") or []):
            if not it.get("description"):
                continue
            items.append({"description": it["description"],
                          "quantity": float(it.get("quantity") or 1),
                          "rate": float(it.get("rate") or 0),
                          "tax_amount": 0})
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


def _draft_follow_up(analysis: Dict[str, Any],
                     email_doc: Dict[str, Any]) -> Optional[str]:
    """AI-draft a reply for follow_up_needed emails; stored for human review."""
    if not analysis.get("follow_up_needed"):
        return None
    try:
        try:
            from ai_governance.ai_gateway import get_ai_gateway
        except ImportError:
            from backend.ai_governance.ai_gateway import get_ai_gateway
        draft = get_ai_gateway().generate_email_draft(
            system_prompt=(
                "You draft concise, professional replies for a market-research "
                "company. Return ONLY JSON: {\"subject\": \"...\", \"body\": \"...\"}. "
                "Reply in the sender's language. Do not invent prices or "
                "commitments; propose a call or ask clarifying questions when "
                "specifics are missing."),
            user_prompt=(
                f"Original email from {email_doc.get('from_email', '')}:\n"
                f"Subject: {email_doc.get('subject', '')}\n"
                f"Summary: {analysis.get('summary', '')}\n"
                f"Key points: {', '.join(analysis.get('key_points') or [])}\n\n"
                f"Draft our reply."))
        if not draft:
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
    """Full AI pipeline for one email. Returns the stored ai_analysis dict."""
    analysis = analyze_email(email_doc)
    if analysis is None:
        return {"success": False, "error": "ai_analysis_failed"}

    actions: Dict[str, Any] = {}
    actions["contacts_ingested"] = _ingest_contacts(analysis, email_doc)
    actions.update(_log_rfq_and_estimate(analysis, email_doc))
    followup_id = _draft_follow_up(analysis, email_doc)
    if followup_id:
        actions["followup_draft_id"] = followup_id
    analysis["actions"] = actions

    try:
        _get_db(MAIL_DB)[MAIL_COLLECTION].update_one(
            {"_id": email_doc["_id"]},
            {"$set": {"ai_analysis": analysis,
                      "ai_summary": analysis.get("summary"),
                      "ai_processed_at": datetime.utcnow()}})
    except Exception as e:
        logger.warning(f"[mail-ai] could not persist analysis: {e}")

    return {"success": True, "analysis": analysis}


MAX_FAILED_ATTEMPTS = 3   # skip an email/sender after this many failed analyses
SYSTEMIC_FAIL_PROBE = 5   # abort the run if this many items fail before any succeeds

# ============== SENDER-LEVEL PROCESSING ==============
# The pool's 361K emails come from only ~6.3K unique senders (one automated
# sender alone accounts for ~175K). One AI call per SENDER — fed a sample of
# their most recent emails — costs ~2% of per-email analysis and stamps every
# email from that sender at once.

SENDER_ANALYSIS_COLLECTION = "mail_sender_analysis"   # in email_automation
MAX_SAMPLE_EMAILS_PER_SENDER = int(os.getenv("MAIL_POOL_SENDER_SAMPLE", "3"))

_SENDER_ANALYSIS_PROMPT = """You are the mail-desk analyst for a market-research company (surveys, panels, fieldwork).
Analyze this SENDER based on their recent emails to us and return ONLY valid JSON, no markdown.

Sender: {from_line}
Total emails from this sender in our inbox: {total_count}
Most recent emails (newest first):
{samples}

Return exactly this JSON shape:
{{
  "summary": "<2-3 sentences: who this sender is and what they want from us>",
  "key_points": ["<point>", "..."],
  "sender_type": "client|prospect|vendor|automated|newsletter|spam|other",
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
    "currency": "<ISO code or null>",
    "items": [{{"description": "<line item>", "quantity": <number>, "rate": <number or 0>}}],
    "deadline": "<ISO date or null>"
  }}
}}

Rules:
- "rfq" refers to the newest emails: is the sender currently requesting a
  quotation/proposal/pricing for research work? A promotional email SELLING
  something is never an RFQ.
- sender_type "automated"/"newsletter"/"spam": machine-generated or bulk mail;
  for these set follow_up_needed=false and contacts=[].
- contacts: only real people evident in the emails; [] if none.
- follow_up_needed: true when a reply from us is clearly expected on the
  newest email."""


def analyze_sender(from_email: str, from_name: str, total_count: int,
                   sample_docs) -> Optional[Dict[str, Any]]:
    """One AI call covering a sender's recent emails."""
    parts = []
    for d in sample_docs:
        body = (d.get("body_plain") or d.get("body") or d.get("snippet") or "")
        parts.append(
            f"--- Email dated {d.get('date', 'unknown')} ---\n"
            f"Subject: {d.get('subject') or '(no subject)'}\n"
            f"{str(body)[:2000]}"
        )
    prompt = _SENDER_ANALYSIS_PROMPT.format(
        from_line=f"{from_name} <{from_email}>".strip(),
        total_count=total_count,
        samples="\n\n".join(parts) or "(no body available)",
    )
    result = _gateway().generate_json(
        prompt, model=MAIL_POOL_AI_MODEL, max_tokens=4000,
        task_type="mail_pool_sender_analysis", caller="sales.mail_pool_ai",
    )
    if not isinstance(result, dict) or "summary" not in result:
        return None
    result["analyzed_at"] = datetime.utcnow().isoformat()
    result["model_source"] = "claude_gateway"
    result["sample_size"] = len(sample_docs)
    result["total_emails"] = total_count
    return result


def process_sender(from_email: str, col) -> Dict[str, Any]:
    """Full AI pipeline for one sender: analyze a sample of their newest
    emails, run downstream actions once, then stamp ALL their unanalyzed
    emails so they never re-enter the queue."""
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

    # Downstream actions run once per sender, anchored on their newest email.
    actions: Dict[str, Any] = {}
    actions["contacts_ingested"] = _ingest_contacts(analysis, newest)
    actions.update(_log_rfq_and_estimate(analysis, newest))
    followup_id = _draft_follow_up(analysis, newest)
    if followup_id:
        actions["followup_draft_id"] = followup_id
    analysis["actions"] = actions

    # Full analysis lives in one doc per sender ...
    sender_col = _get_db("email_automation")[SENDER_ANALYSIS_COLLECTION]
    sender_col.update_one(
        {"_id": from_email},
        {"$set": {"analysis": analysis, "status": "analyzed",
                  "updated_at": datetime.utcnow()},
         "$unset": {"failed_attempts": ""}},
        upsert=True)

    # ... while every email from the sender gets a compact stub, so existing
    # per-email consumers (ai_analysis-exists queries, ai_summary display)
    # keep working without duplicating the full analysis 175K times.
    stub = {"sender_level": True, "sender": from_email,
            "summary": analysis.get("summary"),
            "sender_type": analysis.get("sender_type"),
            "category": analysis.get("category"),
            "analyzed_at": analysis["analyzed_at"]}
    marked = col.update_many(
        base_query,
        {"$set": {"ai_analysis": stub,
                  "ai_summary": analysis.get("summary"),
                  "ai_processed_at": datetime.utcnow()}}).modified_count

    return {"success": True, "analysis": analysis, "emails_marked": marked}


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

    processed = failed = rfqs = emails_covered = 0
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
                if (r["analysis"].get("rfq") or {}).get("is_rfq"):
                    rfqs += 1
            else:
                failed += 1
                failed_senders.append(sender)
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
            "aborted_systemic": aborted}


def process_batch(limit: int = 50) -> Dict[str, Any]:
    """Process up to `limit` unanalyzed mail-pool emails (newest first).

    Failure handling — both directions matter:
    - Per-email: a failed doc gets ai_failed_attempts incremented and is
      skipped once it reaches MAX_FAILED_ATTEMPTS, so one poison message
      can't wedge the head of the queue. (Before this, failed docs were
      never marked; with the newest-first sort, every 30-min run re-failed
      the exact same 50 emails forever.)
    - Systemic: when every item fails before a single success (bad API key,
      provider quota/outage), abort the run early and mark NOTHING failed —
      otherwise an outage would burn attempt-budget across the whole pool
      and permanently skip perfectly good emails.
    """
    col = _get_db(MAIL_DB)[MAIL_COLLECTION]
    processed = failed = rfqs = 0
    failed_ids = []
    aborted = False
    cursor = col.find(
        {"ai_analysis": {"$exists": False},
         "internal": {"$ne": True},           # skip internal/own-domain mail
         "ai_failed_attempts": {"$not": {"$gte": MAX_FAILED_ATTEMPTS}}},
    ).sort("date", -1).limit(limit)
    for doc in cursor:
        try:
            r = process_email(doc)
            if r.get("success"):
                processed += 1
                if (r["analysis"].get("rfq") or {}).get("is_rfq"):
                    rfqs += 1
            else:
                failed += 1
                failed_ids.append(doc["_id"])
        except Exception as e:
            failed += 1
            failed_ids.append(doc["_id"])
            logger.warning(f"[mail-ai] batch item failed: {e}")
        if processed == 0 and failed >= SYSTEMIC_FAIL_PROBE:
            aborted = True
            logger.error(
                f"[mail-ai] first {failed} items all failed — treating as a "
                f"systemic outage (API key/quota?), aborting batch without "
                f"marking emails failed"
            )
            break
    if processed > 0 and failed_ids:
        try:
            col.update_many(
                {"_id": {"$in": failed_ids}},
                {"$inc": {"ai_failed_attempts": 1},
                 "$set": {"ai_last_failed_at": datetime.utcnow()}})
        except Exception as e:
            logger.warning(f"[mail-ai] could not mark failed emails: {e}")
    return {"processed": processed, "failed": failed,
            "rfqs_detected": rfqs, "aborted_systemic": aborted}
