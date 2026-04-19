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

import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Query, Body
from pymongo import MongoClient
from bson import ObjectId

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

@router.get("/panelists/")
async def list_panelists(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
):
    """List all panelists with pagination and search"""
    verify_admin_session(request)

    try:
        query = {}
        if search:
            query = {
                "$or": [
                    {"first_name": {"$regex": search, "$options": "i"}},
                    {"last_name": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}},
                    {"country": {"$regex": search, "$options": "i"}},
                ]
            }

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

        inserted = 0
        skipped = 0
        errors = []

        for i, row in enumerate(panelist_rows):
            email = (row.get("email") or row.get("Email") or "").strip().lower()
            if not email:
                skipped += 1
                continue

            # Check if email already exists
            if panelists_collection.find_one({"email": email}):
                skipped += 1
                continue

            doc = {
                "first_name": (row.get("first_name") or row.get("First Name") or row.get("firstName") or "").strip(),
                "last_name": (row.get("last_name") or row.get("Last Name") or row.get("lastName") or "").strip(),
                "email": email,
                "country": (row.get("country") or row.get("Country") or "").strip(),
                "language": (row.get("language") or row.get("Language") or "English").strip(),
                "status": "active",
                "rewards_balance": 0.0,
                "email_verified": False,
                "source": "csv_upload",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }

            try:
                panelists_collection.insert_one(doc)
                inserted += 1
            except Exception as e:
                errors.append(f"Row {i + 1}: {str(e)}")

        return {
            "message": f"Uploaded {inserted} panelists, skipped {skipped} (duplicates/empty)",
            "inserted": inserted,
            "skipped": skipped,
            "errors": errors[:10],  # Limit error messages
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading panelists CSV: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
