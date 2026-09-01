"""
Email Tracking Router (Step 12)
Open tracking (1x1 pixel), click tracking (link rewrite + redirect),
bounce handling, and deliverability scoring cron.
"""

import os
import re
import base64
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote, unquote

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


load_dotenv()
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Email Tracking"])

# ── MongoDB ──
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
_client = _get_pooled_client()
_db = _client["email_automation"]
events_col = _db["email_events"]
leads_col = _db["leads"]
domain_health_col = _db["domain_health"]

APP_DOMAIN = os.getenv("APP_DOMAIN", "localhost:8000")

# 1x1 transparent PNG (68 bytes)
TRANSPARENT_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAB"
    "Nl7BcQAAAABJRU5ErkJggg=="
)


# ══════════════════════════════════════════════
#  OPEN TRACKING
# ══════════════════════════════════════════════

@router.get("/track/open/{lead_id}/{send_id}")
async def track_open(lead_id: str, send_id: str):
    """
    Records an email open event and returns a 1x1 transparent PNG.
    Injected into email HTML before sending.
    """
    try:
        events_col.insert_one({
            "lead_id": lead_id,
            "send_id": send_id,
            "event_type": "opened",
            "timestamp": datetime.utcnow(),
            "metadata": {},
        })
    except Exception as e:
        logger.error(f"Failed to record open event: {e}")

    return Response(
        content=TRANSPARENT_PIXEL,
        media_type="image/png",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ══════════════════════════════════════════════
#  CLICK TRACKING
# ══════════════════════════════════════════════

@router.get("/track/click/{lead_id}/{send_id}")
async def track_click(lead_id: str, send_id: str, url: str = Query(...)):
    """
    Records a click event and 302-redirects to the original URL.
    """
    decoded_url = unquote(url)

    # Basic URL validation
    if not decoded_url.startswith(("http://", "https://")):
        raise HTTPException(400, "Invalid redirect URL")

    try:
        events_col.insert_one({
            "lead_id": lead_id,
            "send_id": send_id,
            "event_type": "clicked",
            "timestamp": datetime.utcnow(),
            "metadata": {"clicked_url": decoded_url},
        })
    except Exception as e:
        logger.error(f"Failed to record click event: {e}")

    return RedirectResponse(url=decoded_url, status_code=302)


# ══════════════════════════════════════════════
#  EMAIL PREPARATION HELPERS
# ══════════════════════════════════════════════

def inject_open_tracking(html_body: str, lead_id: str, send_id: str) -> str:
    """Inject open tracking pixel into email HTML body."""
    pixel = (
        f'<img src="https://{APP_DOMAIN}/track/open/{lead_id}/{send_id}" '
        f'width="1" height="1" style="display:none" alt="">'
    )
    # Insert before </body> if present, otherwise append
    if "</body>" in html_body.lower():
        return re.sub(
            r"(</body>)",
            f"{pixel}\\1",
            html_body,
            flags=re.IGNORECASE,
        )
    return html_body + pixel


def rewrite_links_for_tracking(html_body: str, lead_id: str, send_id: str) -> str:
    """Rewrite href links for click tracking. Skip unsubscribe links."""

    def _replace_href(match):
        original_url = match.group(1)
        # Don't rewrite unsubscribe links
        if "unsubscribe" in original_url.lower():
            return match.group(0)
        # Don't rewrite tracking pixel
        if "/track/" in original_url:
            return match.group(0)
        encoded = quote(original_url, safe="")
        tracked = f"https://{APP_DOMAIN}/track/click/{lead_id}/{send_id}?url={encoded}"
        return f'href="{tracked}"'

    return re.sub(r'href="([^"]+)"', _replace_href, html_body)


def prepare_email_for_tracking(html_body: str, lead_id: str, send_id: str) -> str:
    """Full tracking preparation: inject pixel + rewrite links."""
    html_body = inject_open_tracking(html_body, lead_id, send_id)
    html_body = rewrite_links_for_tracking(html_body, lead_id, send_id)
    return html_body


# ══════════════════════════════════════════════
#  BOUNCE RECORDING
# ══════════════════════════════════════════════

def record_bounce(lead_id: str, bounce_reason: str):
    """
    Record a bounce event and update lead status.
    Called from Gmail webhook or bounce-detection background job.
    """
    events_col.insert_one({
        "lead_id": lead_id,
        "event_type": "bounced",
        "timestamp": datetime.utcnow(),
        "metadata": {"bounce_reason": bounce_reason},
    })

    leads_col.update_one(
        {"_id": ObjectId(lead_id)},
        {"$set": {"email_status": "bounced", "updated_at": datetime.utcnow()}},
    )

    # Enqueue for retry with alternate pattern
    try:
        from tasks.sales_tasks import enqueue_email_construction
        enqueue_email_construction.delay(lead_id)
    except Exception as e:
        logger.warning(f"Could not enqueue bounce retry: {e}")


def record_reply(lead_id: str, reply_snippet: str = ""):
    """Record a reply event."""
    events_col.insert_one({
        "lead_id": lead_id,
        "event_type": "replied",
        "timestamp": datetime.utcnow(),
        "metadata": {"reply_snippet": reply_snippet[:500]},
    })


# ══════════════════════════════════════════════
#  DELIVERABILITY SCORE CRON  (nightly)
# ══════════════════════════════════════════════

def calculate_deliverability_scores():
    """
    Nightly cron: calculate deliverability score per sender domain.
    score = 100 - (bounce_rate_30d * 50) - (unsub_rate_30d * 50)
    """
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    now = datetime.utcnow()

    # Get all sent events grouped by sender domain
    pipeline = [
        {"$match": {"timestamp": {"$gte": thirty_days_ago}}},
        {"$lookup": {
            "from": "leads",
            "let": {"lid": {"$toObjectId": "$lead_id"}},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$_id", "$$lid"]}}},
                {"$project": {"domain": 1}},
            ],
            "as": "lead_info",
        }},
        {"$unwind": {"path": "$lead_info", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": {
                "domain": "$lead_info.domain",
                "event_type": "$event_type",
            },
            "count": {"$sum": 1},
        }},
    ]

    try:
        results = list(events_col.aggregate(pipeline))
    except Exception as e:
        logger.error(f"Deliverability score calculation failed: {e}")
        return

    # Aggregate per domain
    domains = {}
    for r in results:
        domain = (r["_id"].get("domain") or "unknown")
        etype = r["_id"].get("event_type", "")
        if domain not in domains:
            domains[domain] = {"sent": 0, "bounced": 0, "unsubscribed": 0}
        if etype == "sent":
            domains[domain]["sent"] += r["count"]
        elif etype == "bounced":
            domains[domain]["bounced"] += r["count"]
        elif etype == "unsubscribed":
            domains[domain]["unsubscribed"] += r["count"]

    for domain, stats in domains.items():
        sent = stats["sent"]
        if sent == 0:
            continue
        bounce_rate = stats["bounced"] / sent
        unsub_rate = stats["unsubscribed"] / sent
        score = max(0, 100 - (bounce_rate * 50) - (unsub_rate * 50))

        domain_health_col.update_one(
            {"domain": domain},
            {"$set": {
                "domain": domain,
                "score": round(score, 1),
                "bounce_rate": round(bounce_rate * 100, 1),
                "unsubscribe_rate": round(unsub_rate * 100, 1),
                "sent_count": sent,
                "calculated_at": now,
            }},
            upsert=True,
        )

    logger.info(f"Deliverability scores updated for {len(domains)} domains")
