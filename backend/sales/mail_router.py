"""
Mail Router
Mail pool import/categorisation (Step 5), mail thread listing (Step 13), and stats.
"""

import os
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from pymongo import MongoClient, DESCENDING
from bson import ObjectId
from dotenv import load_dotenv

from .models import LeadSource, LeadStage, EmailStatus, LeadTrack

load_dotenv()
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mail", tags=["Sales Mail"])

# ── MongoDB ──
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI)
_db = _client["email_automation"]
leads_col = _db["leads"]
events_col = _db["email_events"]
domain_health_col = _db["domain_health"]

# Gmail DB for mail pool threads
_gmail_db = _client["torpedo_gmail"]
email_metadata_col = _gmail_db["email_metadata"]


def _serialize(doc):
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    for key in ("lead_id", "rfq_id"):
        if key in doc and doc[key]:
            doc[key] = str(doc[key])
    return doc


# ══════════════════════════════════════════════
#  DOMAIN BLOCKLIST & KEYWORD RULES  (Step 5)
# ══════════════════════════════════════════════

DOMAIN_BLOCKLIST = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "aol.com", "protonmail.com", "mail.com", "yandex.com", "zoho.com",
}

PREFIX_BLOCKLIST = {
    "noreply", "no-reply", "notifications", "support", "hello",
    "info", "donotreply", "mailer-daemon", "postmaster", "bounce",
}

TRANSACTIONAL_KEYWORDS = {
    "invoice", "receipt", "order", "tracking", "shipment",
    "payment", "transaction", "statement", "confirmation", "booking",
}

PROMOTIONAL_KEYWORDS = {
    "unsubscribe", "promo", "discount", "offer", "% off",
    "sale", "deal", "newsletter", "marketing", "campaign",
}

VENDOR_KEYWORDS = {
    "quote", "proposal", "supplier", "vendor", "supply",
    "purchase order", "po#", "procurement",
}


def _classify_by_keywords(subject: str, body_snippet: str) -> Optional[str]:
    """Rule-based classification using keyword groups."""
    text = f"{subject} {body_snippet}".lower()

    if any(kw in text for kw in TRANSACTIONAL_KEYWORDS):
        return "transactional"
    if any(kw in text for kw in PROMOTIONAL_KEYWORDS):
        return "promotional"
    if any(kw in text for kw in VENDOR_KEYWORDS):
        return "vendor"
    return None


def _is_blocked_sender(email: str) -> bool:
    """Check if sender is in domain or prefix blocklist."""
    email = email.lower().strip()
    if "@" not in email:
        return True
    prefix, domain = email.split("@", 1)
    if domain in DOMAIN_BLOCKLIST:
        return True
    if prefix in PREFIX_BLOCKLIST:
        return True
    return False


# ══════════════════════════════════════════════
#  MAIL POOL IMPORT  (Step 5)
# ══════════════════════════════════════════════

@router.post("/pool/import")
async def import_mail_pool():
    """
    Trigger mail pool categorisation.
    Steps 1-4 are code-only. Step 5 (AI fallback) is dispatched to Celery.
    Returns summary of what was processed.
    """
    now = datetime.utcnow()

    # Step 1 — Extract senders from mail pool
    pipeline = [
        {"$group": {
            "_id": "$from_email",
            "name": {"$first": "$from_name"},
            "domain": {"$first": "$from_domain"},
            "last_message_date": {"$max": "$date"},
            "thread_ids": {"$addToSet": "$thread_id"},
            "subjects": {"$push": "$subject"},
            "snippets": {"$push": {"$substr": ["$body_text", 0, 200]}},
        }},
    ]

    try:
        senders = list(email_metadata_col.aggregate(pipeline))
    except Exception as e:
        # If gmail DB not available, return empty
        logger.warning(f"Mail pool aggregation failed: {e}")
        senders = []

    results = {
        "total_senders": len(senders),
        "blocked": 0,
        "transactional": 0,
        "promotional": 0,
        "vendor": 0,
        "leads_created": 0,
        "ai_fallback_queued": 0,
    }

    ai_fallback_batch = []

    for sender in senders:
        email = (sender.get("_id") or "").lower().strip()
        if not email:
            continue

        # Step 2 — Domain blocklist
        if _is_blocked_sender(email):
            results["blocked"] += 1
            continue

        # Already a lead?
        existing = leads_col.find_one({"email": email})
        if existing:
            # Update thread IDs
            new_threads = [t for t in (sender.get("thread_ids") or []) if t]
            if new_threads:
                leads_col.update_one(
                    {"_id": existing["_id"]},
                    {"$addToSet": {"mail_thread_ids": {"$each": new_threads}}, "$set": {"updated_at": now}},
                )
            continue

        # Step 3 — Keyword classification
        subjects_text = " ".join(sender.get("subjects", [])[:5])
        snippets_text = " ".join(sender.get("snippets", [])[:3])
        classification = _classify_by_keywords(subjects_text, snippets_text)

        if classification == "transactional":
            results["transactional"] += 1
            continue
        if classification == "promotional":
            results["promotional"] += 1
            continue
        if classification == "vendor":
            results["vendor"] += 1
            # TODO: route to vendor module
            continue

        # Step 4 — Last-contact check
        last_msg = sender.get("last_message_date")
        six_months_ago = now - timedelta(days=180)
        if last_msg and isinstance(last_msg, datetime) and last_msg < six_months_ago:
            track = LeadTrack.REENGAGEMENT.value
        else:
            track = LeadTrack.COLD.value

        # Unclassified — check if we should use AI fallback
        if classification is None:
            ai_fallback_batch.append({
                "email": email,
                "name": sender.get("name", ""),
                "domain": sender.get("domain", ""),
                "subjects": subjects_text[:300],
                "thread_ids": sender.get("thread_ids", []),
                "track": track,
            })
            if len(ai_fallback_batch) >= 50:
                break  # Cap batch size
            continue

        # Step 6 — Create lead record
        domain = email.split("@")[1] if "@" in email else ""
        doc = {
            "source": LeadSource.MAIL_POOL.value,
            "stage": LeadStage.NEW.value,
            "name": sender.get("name", email.split("@")[0]),
            "email": email,
            "email_status": EmailStatus.PENDING.value,
            "company": "",
            "domain": domain,
            "last_contacted": last_msg,
            "intent_score": None,
            "enrichment": {"status": "pending"},
            "mail_thread_ids": [t for t in (sender.get("thread_ids") or []) if t],
            "contactus_message": None,
            "track": track,
            "rfq_id": None,
            "archived": False,
            "reengagement_eligible_at": None,
            "email_draft": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            leads_col.insert_one(doc)
            results["leads_created"] += 1
        except Exception:
            pass  # Duplicate email, skip

    # Step 5 — Queue AI fallback for ambiguous senders
    if ai_fallback_batch:
        results["ai_fallback_queued"] = len(ai_fallback_batch)
        try:
            from tasks.sales_tasks import classify_mail_pool_senders
            classify_mail_pool_senders.delay(ai_fallback_batch)
        except Exception as e:
            logger.warning(f"Could not queue AI fallback: {e}")

    return results


# ══════════════════════════════════════════════
#  MAIL THREAD LISTING  (Step 13)
# ══════════════════════════════════════════════

@router.get("/threads")
async def list_mail_threads(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
):
    """
    Get mail summary threads — one row per lead with last email status.
    """
    pipeline: List[Dict[str, Any]] = []

    # Get latest event per lead
    event_pipeline = [
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": "$lead_id",
            "latest_status": {"$first": "$event_type"},
            "last_event_at": {"$first": "$timestamp"},
        }},
    ]
    events_map = {}
    try:
        for ev in events_col.aggregate(event_pipeline):
            events_map[ev["_id"]] = {
                "latest_status": ev["latest_status"],
                "last_event_at": ev["last_event_at"],
            }
    except Exception:
        pass

    # Query leads that have been contacted
    query: Dict[str, Any] = {
        "stage": {"$in": ["outreach_sent", "replied", "discovery", "rfq", "negotiation", "won", "lost"]},
        "archived": False,
    }

    total = leads_col.count_documents(query)
    skip = (page - 1) * limit

    leads = list(
        leads_col.find(query, {
            "name": 1, "company": 1, "email": 1,
            "email_draft.subject": 1, "email_draft.body": 1,
            "last_contacted": 1, "updated_at": 1,
        })
        .sort("updated_at", DESCENDING)
        .skip(skip)
        .limit(limit)
    )

    threads = []
    for lead in leads:
        lid = str(lead["_id"])
        draft = lead.get("email_draft") or {}
        ev = events_map.get(lid, {})

        threads.append({
            "lead_id": lid,
            "name": lead.get("name", ""),
            "company": lead.get("company", ""),
            "email": lead.get("email", ""),
            "subject_preview": draft.get("subject", ""),
            "body_preview": (draft.get("body", "") or "")[:100],
            "last_message_at": ev.get("last_event_at") or lead.get("last_contacted") or lead.get("updated_at"),
            "latest_status": ev.get("latest_status", "sent") if ev else "sent",
        })

    # Filter by status if requested
    if status:
        threads = [t for t in threads if t["latest_status"] == status]

    return {"threads": threads, "total": total, "page": page}


# ══════════════════════════════════════════════
#  MAIL STATS  (Step 13)
# ══════════════════════════════════════════════

@router.get("/stats")
async def mail_stats():
    """
    Aggregate email event stats: open_rate, click_rate, bounce_rate,
    reply_rate, deliverability_score.
    """
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    pipeline = [
        {"$match": {"timestamp": {"$gte": thirty_days_ago}}},
        {"$group": {
            "_id": "$event_type",
            "count": {"$sum": 1},
        }},
    ]

    counts = {}
    try:
        for doc in events_col.aggregate(pipeline):
            counts[doc["_id"]] = doc["count"]
    except Exception:
        pass

    sent = counts.get("sent", 0)
    if sent == 0:
        return {
            "open_rate": 0,
            "click_rate": 0,
            "bounce_rate": 0,
            "reply_rate": 0,
            "deliverability_score": 100,
        }

    open_rate = round((counts.get("opened", 0) / sent) * 100, 1)
    click_rate = round((counts.get("clicked", 0) / sent) * 100, 1)
    bounce_rate = round((counts.get("bounced", 0) / sent) * 100, 1)
    reply_rate = round((counts.get("replied", 0) / sent) * 100, 1)

    # Deliverability from domain_health
    try:
        health_docs = list(domain_health_col.find(
            {"calculated_at": {"$gte": thirty_days_ago}},
            {"score": 1},
        ))
        if health_docs:
            avg_score = sum(d["score"] for d in health_docs) / len(health_docs)
            deliverability = round(avg_score, 1)
        else:
            deliverability = round(100 - (bounce_rate * 0.5), 1)
    except Exception:
        deliverability = round(100 - (bounce_rate * 0.5), 1)

    return {
        "open_rate": open_rate,
        "click_rate": click_rate,
        "bounce_rate": bounce_rate,
        "reply_rate": reply_rate,
        "deliverability_score": max(0, min(100, deliverability)),
    }
