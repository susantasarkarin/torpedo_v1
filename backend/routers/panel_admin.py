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
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Query, Body
from pymongo import MongoClient
from bson import ObjectId
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)

# campaign_platform DB (panelists, rewards)
cp_db = client["campaign_platform"]
panelists_collection = cp_db["panelists"]
rewards_collection = cp_db["panel_rewards"]

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


def serialize_doc(doc):
    """Convert MongoDB document to JSON-serializable dict"""
    if doc is None:
        return None
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    for key, val in doc.items():
        if isinstance(val, datetime):
            doc[key] = val.isoformat()
        elif isinstance(val, ObjectId):
            doc[key] = str(val)
    return doc


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
    """Insert normalized panelists while skipping duplicates and invalid rows."""
    inserted = 0
    skipped = 0
    errors: List[str] = []

    for i, row in enumerate(rows):
        try:
            doc = _normalize_panelist_row(row, source=source)
            if not doc:
                skipped += 1
                continue

            if panelists_collection.find_one({"email": doc["email"]}):
                skipped += 1
                continue

            panelists_collection.insert_one(doc)
            inserted += 1
        except Exception as e:
            errors.append(f"Row {i + 1}: {str(e)}")

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
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """List all panelists with pagination, search, and country filter"""
    verify_admin_session(request)

    try:
        query = {}
        conditions = []

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
            conditions.append({"country": {"$regex": f"^{country}$", "$options": "i"}})

        if status:
            conditions.append({"status": {"$regex": f"^{status}$", "$options": "i"}})

        if conditions:
            query = {"$and": conditions} if len(conditions) > 1 else conditions[0]

        total = panelists_collection.count_documents(query)
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


@router.get("/panelist-leads/")
async def list_panelist_leads(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
):
    """List unique parsing-page leads that have an email address."""
    verify_admin_session(request)

    try:
        total_pipeline = [
            *_panel_lead_base_stages(search=search, country=country),
            *_panel_lead_group_stages(),
            {"$count": "total"},
        ]
        total_result = list(traffic_collection.aggregate(total_pipeline))
        total = total_result[0]["total"] if total_result else 0

        skip = (page - 1) * page_size
        results_pipeline = [
            *_panel_lead_base_stages(search=search, country=country),
            *_panel_lead_group_stages(),
            {"$sort": {"createdAt": -1}},
            {"$skip": skip},
            {"$limit": page_size},
        ]

        leads = [serialize_doc(doc) for doc in traffic_collection.aggregate(results_pipeline)]

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
