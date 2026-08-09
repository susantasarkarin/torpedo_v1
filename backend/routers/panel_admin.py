"""
PANEL ADMIN ROUTER
Admin endpoints for managing the survey panel module.

Endpoints:
- GET /panel-admin/stats/ - Aggregate panel statistics
- GET /panel-admin/panelists/ - List all panelists with pagination/search
- POST /panel-admin/panelists/upload-csv - Bulk upload panelists from CSV
- GET /panel-admin/rewards/ - List all reward transactions
- GET /panel-admin/rewards/redemptions - Pending redemption requests
"""

import asyncio
import os
import logging
import csv
import json
import io
import re
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Query, Body
from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError
from bson import ObjectId
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse

# Shared MongoDB serialization (ObjectId/datetime -> JSON) — consolidated
# from per-router copies into backend/utils.py.
try:
    from ..utils import serialize_doc, serialize_docs
except ImportError:  # pragma: no cover - flat import when run from backend/
    from utils import serialize_doc, serialize_docs

logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)

# campaign_platform DB (panelists, rewards)
cp_db = client["campaign_platform"]
panelists_collection = cp_db["panelists"]
rewards_collection = cp_db["panel_rewards"]
invitation_log_collection = cp_db["panel_invitation_log"]
suppression_collection = cp_db["panel_email_suppression"]

# email is the dedupe key for bulk CSV upserts — without this index every
# upsert filter collection-scans and large uploads take minutes (HTTP 524)
try:
    panelists_collection.create_index("email")
except Exception as _idx_err:  # pragma: no cover
    logger.warning(f"panelists email index creation failed: {_idx_err}")

# traffic_flow_db (traffic records from parsing page)
tf_db = client["traffic_flow_db"]
traffic_collection = tf_db["url_parameters"]

# ============== ROUTER ==============

router = APIRouter(prefix="/panel-admin", tags=["Panel Admin"])


# ============== HELPERS ==============

def verify_admin_session(request: Request):
    """Verify admin session from Authorization header"""
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing session token")
    return session_id


def _extract_first_list_payload(payload: Any) -> List[Dict[str, Any]]:
    """Extract first list of dicts from a JSON payload."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ["panelists", "users", "results", "data", "items"]:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        for value in payload.values():
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def _split_name(full_name: str) -> Dict[str, str]:
    """Split a full name into first and last name."""
    name = (full_name or "").strip()
    if not name:
        return {"first_name": "", "last_name": ""}

    parts = name.split()
    if len(parts) == 1:
        return {"first_name": parts[0], "last_name": ""}

    return {"first_name": parts[0], "last_name": " ".join(parts[1:])}


def _normalize_panelist_row(row: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    """Normalize external row to panelist schema."""
    email = str(
        row.get("email")
        or row.get("Email")
        or row.get("mail")
        or row.get("Mail")
        or ""
    ).strip().lower()

    if not email:
        return None

    first_name = str(
        row.get("first_name")
        or row.get("First Name")
        or row.get("firstName")
        or row.get("firstname")
        or ""
    ).strip()
    last_name = str(
        row.get("last_name")
        or row.get("Last Name")
        or row.get("lastName")
        or row.get("lastname")
        or ""
    ).strip()

    if not first_name and not last_name:
        full_name = str(
            row.get("name")
            or row.get("full_name")
            or row.get("fullName")
            or ""
        )
        split = _split_name(full_name)
        first_name = split["first_name"]
        last_name = split["last_name"]

    country = str(
        row.get("country")
        or row.get("Country")
        or row.get("countryCode")
        or row.get("country_code")
        or ""
    ).strip()
    language = str(
        row.get("language")
        or row.get("Language")
        or row.get("locale")
        or "English"
    ).strip() or "English"

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "country": country,
        "language": language,
        "status": "active",
        "rewards_balance": 0.0,
        "email_verified": False,
        "source": source,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


def _upsert_panelists(rows: List[Dict[str, Any]], source: str) -> Dict[str, Any]:
    """
    Insert normalized panelists while skipping duplicates and invalid rows.

    Uses batched bulk upserts ($setOnInsert keyed on email) instead of a
    find_one+insert_one pair per row — large CSV uploads (~90K rows) were
    taking minutes and timing out at the proxy (HTTP 524); bulk writes
    complete in seconds.
    """
    skipped = 0
    errors: List[str] = []

    # Normalize and dedupe in-memory first (last duplicate in file wins skip)
    docs_by_email: Dict[str, Dict[str, Any]] = {}
    for i, row in enumerate(rows):
        try:
            doc = _normalize_panelist_row(row, source=source)
            if not doc:
                skipped += 1
                continue
            if doc["email"] in docs_by_email:
                skipped += 1
                continue
            docs_by_email[doc["email"]] = doc
        except Exception as e:
            errors.append(f"Row {i + 1}: {str(e)}")

    inserted = 0
    docs = list(docs_by_email.values())
    batch_size = 5000
    for start in range(0, len(docs), batch_size):
        batch = docs[start:start + batch_size]
        ops = [
            UpdateOne({"email": d["email"]}, {"$setOnInsert": d}, upsert=True)
            for d in batch
        ]
        try:
            res = panelists_collection.bulk_write(ops, ordered=False)
            inserted += res.upserted_count
            skipped += len(batch) - res.upserted_count
        except BulkWriteError as e:
            details = e.details or {}
            inserted += int(details.get("nUpserted", 0))
            skipped += len(batch) - int(details.get("nUpserted", 0))
            for err in (details.get("writeErrors") or [])[:3]:
                errors.append(f"Bulk write: {err.get('errmsg', 'unknown error')}")

    return {
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors[:10],
    }


def _parse_csv_text(csv_text: str) -> List[Dict[str, Any]]:
    """Parse CSV text into a list of dict rows."""
    csv_io = io.StringIO(csv_text)
    reader = csv.DictReader(csv_io)
    return [dict(row) for row in reader if row]


def _fetch_link_data(url: str, request_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Fetch remote CSV or JSON payload from URL."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Only http/https URLs are allowed")

    headers = {"User-Agent": "CampaignPanelImporter/1.0"}
    if request_headers:
        headers.update({str(k): str(v) for k, v in request_headers.items()})

    req = UrlRequest(url, headers=headers)
    try:
        with urlopen(req, timeout=20) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            body = resp.read()
    except HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch link: HTTP {e.code}")
    except URLError as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch link: {e.reason}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch link: {str(e)}")

    text = body.decode("utf-8-sig", errors="replace")
    return {"text": text, "content_type": content_type}


def _panel_lead_base_stages(search: Optional[str] = None, country: Optional[str] = None) -> List[Dict[str, Any]]:
    """Build aggregation stages for parsing-page leads with normalized emails."""
    match_query: Dict[str, Any] = {
        "email": {"$exists": True, "$type": "string", "$ne": ""},
    }

    if country:
        match_query["countryCode"] = {"$regex": f"^{country}$", "$options": "i"}

    if search:
        match_query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"respondentId": {"$regex": search, "$options": "i"}},
            {"vendorId": {"$regex": search, "$options": "i"}},
            {"countryCode": {"$regex": search, "$options": "i"}},
        ]

    return [
        {"$match": match_query},
        {
            "$addFields": {
                "normalizedEmail": {
                    "$toLower": {
                        "$trim": {"input": "$email"}
                    }
                },
                "normalizedCountryCode": {
                    "$toUpper": {
                        "$trim": {"input": {"$ifNull": ["$countryCode", ""]}}
                    }
                },
            }
        },
        {"$match": {"normalizedEmail": {"$ne": ""}}},
    ]


def _panel_lead_group_stages() -> List[Dict[str, Any]]:
    """Deduplicate parsing-page leads by normalized email, keeping the newest record."""
    return [
        {"$sort": {"createdAt": -1, "_id": -1}},
        {
            "$group": {
                "_id": "$normalizedEmail",
                "doc": {"$first": "$$ROOT"},
            }
        },
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$set": {"email": "$normalizedEmail", "countryCode": "$normalizedCountryCode"}},
        {
            "$project": {
                "normalizedEmail": 0,
                "normalizedCountryCode": 0,
            }
        },
    ]


# Cache expensive total-row counts so they aren't recomputed on every page.
# Paging through 190K panelists re-ran count_documents on each click, which
# dominated the request; the total only has to be fresh enough to size the
# pager.
_lead_total_cache: Dict[str, Any] = {}
_LEAD_TOTAL_TTL = 180  # seconds


def _cached_lead_total(cache_key: str, compute):
    now = time.time()
    hit = _lead_total_cache.get(cache_key)
    if hit and (now - hit[0]) < _LEAD_TOTAL_TTL:
        return hit[1]
    total = compute()
    _lead_total_cache[cache_key] = (now, total)
    return total


def _exact_or_regex(value: str) -> Any:
    """Match `value` exactly when it is a plain token, else fall back to regex.

    The country and status filters used an anchored case-insensitive regex,
    which no index can serve — every filtered page did a full collection scan.
    Both filter values come from the collection's own distinct list, so an
    exact match is equivalent for real data and index-eligible. Anything
    containing regex metacharacters keeps the old case-insensitive behaviour.
    """
    if value and re.fullmatch(r"[A-Za-z0-9 _\-\.]+", value):
        return value
    return {"$regex": f"^{re.escape(value)}$", "$options": "i"}


def _build_panelist_query(
    search: Optional[str] = None,
    country: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Shared filter builder for the two panelist listing endpoints."""
    conditions: List[Dict[str, Any]] = []

    if search:
        conditions.append({
            "$or": [
                {"first_name": {"$regex": search, "$options": "i"}},
                {"last_name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
                {"country": {"$regex": search, "$options": "i"}},
            ]
        })

    if country:
        conditions.append({"country": _exact_or_regex(country)})

    if status:
        conditions.append({"status": _exact_or_regex(status)})

    if not conditions:
        return {}
    return {"$and": conditions} if len(conditions) > 1 else conditions[0]


# ============== STATS ==============

@router.get("/stats/")
async def get_panel_stats(request: Request):
    """Get aggregate panel statistics"""
    verify_admin_session(request)

    try:
        total_panelists = panelists_collection.count_documents({})
        active_panelists = panelists_collection.count_documents({"status": "active"})
        pending_approvals = panelists_collection.count_documents({"status": "pending"})

        # Rewards stats
        rewards_pipeline = [
            {"$match": {"type": "earned", "status": "completed"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]
        rewards_result = list(rewards_collection.aggregate(rewards_pipeline))
        total_rewards = rewards_result[0]["total"] if rewards_result else 0

        redeemed_pipeline = [
            {"$match": {"type": "redeemed", "status": "completed"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]
        redeemed_result = list(rewards_collection.aggregate(redeemed_pipeline))
        total_redeemed = redeemed_result[0]["total"] if redeemed_result else 0

        pending_redemptions = rewards_collection.count_documents({"type": "redeemed", "status": "pending"})

        return {
            "totalPanelists": total_panelists,
            "activePanelists": active_panelists,
            "pendingApprovals": pending_approvals,
            "totalRewardsIssued": total_rewards,
            "totalRedeemed": total_redeemed,
            "pendingRedemptions": pending_redemptions,
        }
    except Exception as e:
        logger.error(f"Error fetching panel stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== PANELISTS ==============

@router.get("/panelists/countries")
async def list_panelist_countries(request: Request):
    """Get distinct country values from panelists collection"""
    verify_admin_session(request)

    try:
        countries = panelists_collection.distinct("country")
        # Filter out empty/None values and sort
        countries = sorted([c for c in countries if c])
        return {"countries": countries}
    except Exception as e:
        logger.error(f"Error fetching countries: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/panelists/")
async def list_panelists(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """List all panelists with pagination, search, and country filter"""
    verify_admin_session(request)

    try:
        query = _build_panelist_query(search, country, status)

        total = _cached_lead_total(
            f"panelists|{search or ''}|{country or ''}|{status or ''}",
            lambda: panelists_collection.count_documents(query),
        )
        skip = (page - 1) * page_size

        panelists = panelists_collection.find(
            query, {"password_hash": 0, "reset_token": 0, "reset_token_expires": 0}
        ).sort("created_at", -1).skip(skip).limit(page_size)

        results = [serialize_doc(p) for p in panelists]

        return {
            "results": results,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing panelists: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/panelists/with-email-status")
async def list_panelists_with_email_status(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """List all panelists with their latest email status and sent date from invitation logs"""
    verify_admin_session(request)

    try:
        query = _build_panelist_query(search, country, status)

        total = _cached_lead_total(
            f"panelists|{search or ''}|{country or ''}|{status or ''}",
            lambda: panelists_collection.count_documents(query),
        )
        skip = (page - 1) * page_size

        # Use optimized aggregation to get latest invitation
        # Sort and paginate BEFORE the lookup to reduce data processed
        pipeline = [
            {"$match": query},
            {"$sort": {"created_at": -1}},
            {"$skip": skip},
            {"$limit": page_size},
            {
                "$lookup": {
                    "from": "panel_invitation_log",
                    "let": {"email": "$email"},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$email", "$$email"]}}},
                        {"$sort": {"sent_at": -1}},
                        {"$limit": 1},
                        {"$project": {"_id": 0, "sent_at": 1, "status": 1, "type": 1}}
                    ],
                    "as": "latest_invitation_arr"
                }
            },
            {
                "$addFields": {
                    "latest_invitation": {"$arrayElemAt": ["$latest_invitation_arr", 0]}
                }
            },
            {
                "$project": {
                    "password_hash": 0,
                    "reset_token": 0,
                    "reset_token_expires": 0,
                    "latest_invitation_arr": 0
                }
            }
        ]

        results = []
        for doc in panelists_collection.aggregate(pipeline):
            doc_serialized = serialize_doc(doc)
            
            # Add email status from latest invitation
            if doc_serialized.get("latest_invitation"):
                inv = doc_serialized["latest_invitation"]
                doc_serialized["email_sent_date"] = inv.get("sent_at")
                doc_serialized["email_status"] = inv.get("status")  # sent, bounced, complained, confirmed, clicked, etc.
            else:
                doc_serialized["email_sent_date"] = None
                doc_serialized["email_status"] = None
            
            results.append(doc_serialized)

        return {
            "results": results,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing panelists with email status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/panelist-leads/")
async def list_panelist_leads(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
):
    """List unique parsing-page leads that have an email address."""
    verify_admin_session(request)

    try:
        # The dedup count is expensive over the full traffic collection, so cache
        # it per (search, country) — only the first request per filter pays for it.
        def _compute_total():
            total_pipeline = [
                *_panel_lead_base_stages(search=search, country=country),
                *_panel_lead_group_stages(),
                {"$count": "total"},
            ]
            total_result = list(traffic_collection.aggregate(total_pipeline, allowDiskUse=True))
            return total_result[0]["total"] if total_result else 0

        total = _cached_lead_total(f"leads|{search or ''}|{country or ''}", _compute_total)

        skip = (page - 1) * page_size
        results_pipeline = [
            *_panel_lead_base_stages(search=search, country=country),
            *_panel_lead_group_stages(),
            {"$sort": {"createdAt": -1}},
            {"$skip": skip},
            {"$limit": page_size},
        ]

        # allowDiskUse avoids the in-memory sort/group limit on large collections.
        leads = [serialize_doc(doc) for doc in traffic_collection.aggregate(results_pipeline, allowDiskUse=True)]

        return {
            "results": leads,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Error listing panelist leads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/panelist-leads/countries")
async def list_panelist_lead_countries(request: Request):
    """Get distinct country codes from parsing-page leads that have an email."""
    verify_admin_session(request)

    try:
        pipeline = [
            *_panel_lead_base_stages(),
            {
                "$group": {
                    "_id": "$normalizedCountryCode",
                }
            },
            {"$match": {"_id": {"$ne": ""}}},
            {"$sort": {"_id": 1}},
        ]
        countries = [doc["_id"] for doc in traffic_collection.aggregate(pipeline) if doc.get("_id")]
        return {"countries": countries}
    except Exception as e:
        logger.error(f"Error fetching panel lead countries: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/panelist-leads/promotion-status")
async def panelist_lead_promotion_status(request: Request):
    """How many parsing-page leads are still missing from `panelists`.

    A non-zero count means those addresses are visible in the Panelist Lead
    tab but are NOT receiving invitation emails, because the senders only read
    the `panelists` collection.
    """
    verify_admin_session(request)

    try:
        from services.panel_lead_promotion import count_unpromoted_leads
        result = await asyncio.to_thread(count_unpromoted_leads)
        return result
    except Exception as e:
        logger.error(f"Error counting unpromoted panelist leads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/panelist-leads/promote")
async def promote_panelist_leads(
    request: Request,
    data: Dict[str, Any] = Body(default={}),
):
    """Merge parsing-page leads into `panelists` so the invite cron reaches them.

    Body (optional):
    - lookback_days: int — only promote leads captured in the last N days.
      Omit for a full backfill (use once; it scans the whole traffic table).
    - dry_run: bool — report what would be inserted without writing.

    Existing panelists are never modified: the upsert is $setOnInsert on email,
    so a CSV-sourced record keeps its own name, country and invite history.
    """
    verify_admin_session(request)

    lookback_days = data.get("lookback_days")
    dry_run = bool(data.get("dry_run", False))

    try:
        from services.panel_lead_promotion import promote_traffic_leads_to_panelists
        from datetime import timedelta

        since = None
        if lookback_days:
            since = datetime.utcnow() - timedelta(days=int(lookback_days))

        result = await asyncio.to_thread(
            promote_traffic_leads_to_panelists, since, dry_run
        )
        # The panelist totals are cached for 3 min; promotion just changed them.
        _lead_total_cache.clear()
        return {"status": "completed", **result}
    except Exception as e:
        logger.error(f"Error promoting panelist leads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/panelists/upload-csv")
async def upload_panelists_csv(
    request: Request,
    data: Dict[str, Any] = Body(...),
):
    """Bulk upload panelists from parsed CSV data"""
    verify_admin_session(request)

    try:
        panelist_rows = data.get("panelists", [])
        if not panelist_rows:
            raise HTTPException(status_code=400, detail="No panelist data provided")
        result = await asyncio.to_thread(_upsert_panelists, panelist_rows, "csv_upload")

        return {
            "message": f"Uploaded {result['inserted']} panelists, skipped {result['skipped']} (duplicates/empty)",
            "inserted": result["inserted"],
            "skipped": result["skipped"],
            "errors": result["errors"],
            "source": "csv_upload",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading panelists CSV: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/panelists/import-link")
async def import_panelists_from_link(
    request: Request,
    data: Dict[str, Any] = Body(...),
):
    """Import panelist emails from a remote CSV/JSON URL (e.g., sfw_panel export/API)."""
    verify_admin_session(request)

    url = (data.get("url") or "").strip()
    format_hint = (data.get("format") or "auto").strip().lower()
    root_key = (data.get("root_key") or "").strip()
    request_headers = data.get("headers") or {}

    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    if format_hint not in {"auto", "csv", "json"}:
        raise HTTPException(status_code=400, detail="format must be one of: auto, csv, json")

    fetched = await asyncio.to_thread(_fetch_link_data, url, request_headers)
    content_type = fetched["content_type"]
    text = fetched["text"]

    rows: List[Dict[str, Any]] = []
    detected_format = format_hint
    if detected_format == "auto":
        if "json" in content_type:
            detected_format = "json"
        elif "csv" in content_type:
            detected_format = "csv"
        else:
            detected_format = "json" if text.lstrip().startswith("[") or text.lstrip().startswith("{") else "csv"

    try:
        if detected_format == "csv":
            rows = _parse_csv_text(text)
        else:
            payload = json.loads(text)
            if root_key:
                selected = payload.get(root_key) if isinstance(payload, dict) else None
                rows = [item for item in selected if isinstance(item, dict)] if isinstance(selected, list) else []
            else:
                rows = _extract_first_list_payload(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Unable to parse {detected_format} data: {str(e)}")

    if not rows:
        raise HTTPException(status_code=400, detail="No rows found in provided link")

    result = await asyncio.to_thread(_upsert_panelists, rows, "link_import")
    return {
        "message": f"Imported {result['inserted']} panelists from link, skipped {result['skipped']}",
        "inserted": result["inserted"],
        "skipped": result["skipped"],
        "errors": result["errors"],
        "source": "link_import",
        "format": detected_format,
        "fetched_rows": len(rows),
        "url": url,
    }


# ============== REWARDS ==============

@router.get("/rewards/")
async def list_rewards(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """List all reward transactions"""
    verify_admin_session(request)

    try:
        total = rewards_collection.count_documents({})
        skip = (page - 1) * page_size

        transactions = rewards_collection.find().sort("created_at", -1).skip(skip).limit(page_size)
        results = [serialize_doc(tx) for tx in transactions]

        # Enrich with panelist info
        for tx in results:
            pid = tx.get("panelist_id")
            if pid:
                try:
                    panelist = panelists_collection.find_one(
                        {"_id": ObjectId(pid)}, {"first_name": 1, "last_name": 1, "email": 1}
                    )
                    if panelist:
                        tx["panelist_name"] = f"{panelist.get('first_name', '')} {panelist.get('last_name', '')}".strip()
                        tx["panelist_email"] = panelist.get("email", "")
                except Exception:
                    pass

        return {"results": results, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logger.error(f"Error listing rewards: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rewards/redemptions")
async def list_redemptions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """List pending redemption requests"""
    verify_admin_session(request)

    try:
        query = {"type": "redeemed"}
        total = rewards_collection.count_documents(query)
        skip = (page - 1) * page_size

        redemptions = rewards_collection.find(query).sort("created_at", -1).skip(skip).limit(page_size)
        results = [serialize_doc(r) for r in redemptions]

        # Enrich with panelist info
        for r in results:
            pid = r.get("panelist_id")
            if pid:
                try:
                    panelist = panelists_collection.find_one(
                        {"_id": ObjectId(pid)}, {"first_name": 1, "last_name": 1, "email": 1}
                    )
                    if panelist:
                        r["panelist_name"] = f"{panelist.get('first_name', '')} {panelist.get('last_name', '')}".strip()
                        r["panelist_email"] = panelist.get("email", "")
                except Exception:
                    pass

        return {"results": results, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logger.error(f"Error listing redemptions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== DASHBOARD ==============

@router.get("/dashboard/daily-stats")
async def get_daily_email_stats(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    """Get daily email send statistics for the last N days"""
    verify_admin_session(request)

    try:
        from datetime import timedelta, timezone
        from zoneinfo import ZoneInfo
        
        # Get timezone-aware stats (use Asia/Kolkata or UTC)
        try:
            tz = ZoneInfo("Asia/Kolkata")
        except Exception:
            tz = ZoneInfo("UTC")
        
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        start_date = now_utc - timedelta(days=days)
        
        # `status` on an invitation-log row is mutated in place as the row's
        # fate resolves (sent -> soft_bounced/bounced/complained/confirmed), so
        # it is NOT a marker of "was this delivered". Matching status=="sent"
        # and then counting bounced/confirmed inside that same match — which is
        # what this pipeline used to do — can never yield anything but zero.
        # "Was sent" is `sent_at` being present; the outcome is the status.
        BOUNCE_STATUSES = ["bounced", "soft_bounced"]

        pipeline = [
            {
                "$match": {
                    "sent_at": {"$gte": start_date, "$lte": now_utc},
                }
            },
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$sent_at"
                        }
                    },
                    "count": {"$sum": 1},
                    "bounced": {
                        "$sum": {
                            "$cond": [{"$in": ["$status", BOUNCE_STATUSES]}, 1, 0]
                        }
                    },
                    "complained": {
                        "$sum": {
                            "$cond": [{"$eq": ["$status", "complained"]}, 1, 0]
                        }
                    },
                    "confirmed": {
                        "$sum": {
                            "$cond": [{"$eq": ["$status", "confirmed"]}, 1, 0]
                        }
                    },
                }
            },
            {"$sort": {"_id": 1}}
        ]

        daily_stats = list(invitation_log_collection.aggregate(pipeline))

        sent_filter = {"sent_at": {"$exists": True, "$ne": None}}
        total_sent_count = invitation_log_collection.count_documents(sent_filter)
        total_bounced_count = invitation_log_collection.count_documents(
            {"status": {"$in": BOUNCE_STATUSES}}
        )

        # People, not log rows. A registered panelist has every one of their
        # invitation rows flipped to "confirmed" by the SFW sync, so counting
        # rows reported ~10x the real number of registrations. Both the invited
        # and confirmed people counts come off `panelists`, matching the funnel.
        people_invited = panelists_collection.count_documents(
            {"last_invited_at": {"$exists": True, "$ne": None}}
        )
        people_confirmed = panelists_collection.count_documents(
            {"double_opt_in_completed": True}
        )

        # Addresses SES already knows are dead. Until a BounceTopic is wired to
        # the SNS webhook this is the only honest bounce signal we have — the
        # log rows only carry a bounce status once the suppression sync
        # back-fills them.
        try:
            total_suppressed = suppression_collection.count_documents({})
        except Exception:
            total_suppressed = 0

        return {
            "daily_stats": daily_stats,
            "total_sent": total_sent_count,
            "total_bounced": total_bounced_count,
            "total_suppressed": total_suppressed,
            # Kept for compatibility: the raw row count, which is not a
            # people count. Clients should prefer people_confirmed.
            "total_confirmed": people_confirmed,
            "confirmed_log_rows": invitation_log_collection.count_documents(
                {"status": "confirmed"}
            ),
            "people_invited": people_invited,
            "people_confirmed": people_confirmed,
            "days_requested": days,
        }
    except Exception as e:
        logger.error(f"Error fetching daily email stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/funnel")
async def get_conversion_funnel(
    request: Request,
    refresh: bool = Query(False, description="Bypass the 10-minute cache"),
):
    """Conversion funnel plus the size of each stalled segment.

    Stages: in pool -> invited -> clicked -> double opt-in -> profile complete
    -> active. `pct_of_previous` on each stage is the conversion from the one
    above it, which is where the leak shows up.
    """
    verify_admin_session(request)

    try:
        from services.panel_funnel import compute_funnel
        return await asyncio.to_thread(compute_funnel, refresh)
    except Exception as e:
        logger.error(f"Error computing panel funnel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/drip-status")
async def get_drip_status(request: Request, days: int = Query(30, ge=1, le=365)):
    """Per-stage re-engagement send volume over the last N days."""
    verify_admin_session(request)

    try:
        from datetime import timedelta
        from services.panel_drip_service import STAGES

        since = datetime.utcnow() - timedelta(days=days)
        out = {}
        for stage_key, stage in STAGES.items():
            log_type = f"drip_{stage_key}"
            out[stage_key] = {
                "segment": stage["segment"],
                "max_sends": stage["max_sends"],
                "gap_days": stage["gap_days"],
                "sent_in_window": invitation_log_collection.count_documents(
                    {"type": log_type, "status": "sent", "sent_at": {"$gte": since}}
                ),
                "sent_all_time": invitation_log_collection.count_documents(
                    {"type": log_type, "status": "sent"}
                ),
            }
        return {"days": days, "stages": out}
    except Exception as e:
        logger.error(f"Error fetching drip status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drips/run")
async def run_drips(
    request: Request,
    data: Dict[str, Any] = Body(default={}),
):
    """Trigger the re-engagement drips on demand.

    Body (optional):
    - stage: "verify" | "profile" | "activate" — omit to run all three
    - dry_run: bool — report who would be mailed without sending
    - limit: int — cap this run (also bounded by PANEL_DRIP_RUN_CAP and the
      SES bulk budget)

    Normally runs daily via Celery; per-stage caps and cooldowns apply either
    way, so triggering this repeatedly cannot re-mail the same person.
    """
    verify_admin_session(request)

    stage = data.get("stage")
    dry_run = bool(data.get("dry_run", False))
    limit = data.get("limit")

    try:
        from services.panel_drip_service import run_drip_stage, run_all_drip_stages, STAGES

        if stage:
            if stage not in STAGES:
                raise HTTPException(status_code=422, detail=f"unknown stage: {stage}")
            result = await asyncio.to_thread(run_drip_stage, stage, limit, dry_run)
        else:
            result = await asyncio.to_thread(run_all_drip_stages, dry_run)

        return {"status": "completed", **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running panel drips: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/registrations-by-country")
async def get_registrations_by_country(
    request: Request,
):
    """Get panelists registered (double opt-in confirmed) by country"""
    verify_admin_session(request)

    try:
        # `country` is only populated for records that came in with a country
        # on the CSV import; SFW-sourced registrations carry theirs in the
        # mirrored `sfw_country` (see services/panel_sync_service.py). Grouping
        # on `country` alone put 100% of registrations in "Unknown" while the
        # SFW panel section on the same page showed the real split.
        pipeline = [
            {
                "$match": {
                    "double_opt_in_completed": True
                }
            },
            {
                "$group": {
                    "_id": {"$ifNull": ["$sfw_country", "$country"]},
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"count": -1}}
        ]
        
        registrations = list(panelists_collection.aggregate(pipeline))
        
        # Format response
        by_country = {}
        total_registered = 0
        for doc in registrations:
            country = doc.get("_id") or "Unknown"
            count = doc.get("count", 0)
            by_country[country] = count
            total_registered += count
        
        return {
            "registrations_by_country": by_country,
            "total_registered": total_registered,
            "countries_represented": len(by_country),
        }
    except Exception as e:
        logger.error(f"Error fetching registrations by country: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── SFW Panel proxy endpoints ────────────────────────────────────────────────
# Proxies all SFW panel data via HTTPS to panel.surveyfieldwork.com/api/admin/*
# Requires SFW_INTERNAL_KEY env var on the Torpedo backend, and INTERNAL_API_KEY
# on sfw-api. auth.js on sfw-api checks the X-Internal-Key header.

import requests as _http

_SFW_API = os.getenv("SFW_PANEL_API_BASE", "https://panel.surveyfieldwork.com/api/admin")
_SFW_KEY = os.getenv("SFW_INTERNAL_KEY", "")


def _sfw_get(path, params=None):
    r = _http.get(f"{_SFW_API}{path}", headers={"X-Internal-Key": _SFW_KEY}, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


@router.get("/dashboard/sfwpanel-overview")
async def get_sfwpanel_overview(request: Request):
    """SFW panel overview — proxied from panel.surveyfieldwork.com"""
    verify_admin_session(request)
    try:
        data = _sfw_get("/overview")
        users = data.get("users", {})
        surveys = data.get("surveys", {})
        rewards = data.get("rewards", {})
        return {
            "users": {
                "total": users.get("total", 0),
                "today": users.get("today", 0),
                "this_week": users.get("thisWeek", 0),
                "active_week": users.get("activeThisWeek", 0),
            },
            "surveys": {
                "total": surveys.get("completed", 0),
                "complete": surveys.get("complete", 0),
                "terminate": surveys.get("terminate", 0),
                "quotafull": surveys.get("quotafull", 0),
                "completion_rate": surveys.get("completionRate", 0),
            },
            "levels": data.get("levels", {}),
            # Was hardcoded to {}, which rendered the Signup Source card as a
            # permanently blank box. Accept either spelling from the Node API.
            "sources": data.get("sources") or data.get("signupSources") or {},
            "rewards": {"total_paise": rewards.get("totalPaidPaise", 0)},
        }
    except Exception as e:
        logger.error(f"sfwpanel overview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/sfwpanel-countries")
async def get_sfwpanel_countries(request: Request):
    """SFW panel country breakdown — proxied from panel.surveyfieldwork.com"""
    verify_admin_session(request)
    try:
        data = _sfw_get("/country-stats")
        raw = data.get("countries", [])
        countries = [
            {
                "country": c.get("_id", "XX"),
                "total": c.get("total", 0),
                "today": c.get("today", 0),
                "this_week": c.get("thisWeek", 0),
            }
            for c in raw
        ]
        return {"countries": countries}
    except Exception as e:
        logger.error(f"sfwpanel countries error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sfwpanel-panelists")
async def get_sfwpanel_panelists(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    country: str = Query(""),
    sort_by: str = Query("createdAt"),
    order: str = Query("desc"),
):
    """Paginated SFW panelists with survey stats — proxied from panel.surveyfieldwork.com"""
    verify_admin_session(request)
    try:
        params = {"page": page, "limit": limit, "sortBy": sort_by, "order": order}
        if search:
            params["search"] = search
        if country:
            params["country"] = country
        return _sfw_get("/panelists", params=params)
    except Exception as e:
        logger.error(f"sfwpanel panelists error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sfwpanel-panelists/{user_id}")
async def get_sfwpanel_panelist_detail(request: Request, user_id: str):
    """Detail for a single SFW panelist — proxied from panel.surveyfieldwork.com"""
    verify_admin_session(request)
    try:
        return _sfw_get(f"/panelists/{user_id}")
    except _http.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="User not found")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"sfwpanel panelist detail error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
