"""
Admin API routes — quota management, redirects, CSV export, client dashboard.
"""
import io
import csv
from datetime import datetime
from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from services.quota_service import get_all_quotas
from routes.auth import verify_token

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(verify_token)],
)


def _db():
    from main import db
    return db


# ---------- Quota Management ----------

class QuotaUpdate(BaseModel):
    quota_key: str
    limit: int


@router.get("/quotas")
async def view_quotas():
    """Current quota status across all cells."""
    return await get_all_quotas(_db())


@router.post("/quotas/update")
async def update_quota(payload: QuotaUpdate):
    """Update the limit for a specific quota cell."""
    db = _db()
    await db.quota_limits.update_one(
        {"_id": "limits"},
        {"$set": {payload.quota_key: payload.limit}},
        upsert=True,
    )
    return {"ok": True, "quota_key": payload.quota_key, "new_limit": payload.limit}


@router.get("/quotas/limits")
async def get_quota_limits():
    """Get all configurable quota limits."""
    db = _db()
    doc = await db.quota_limits.find_one({"_id": "limits"})
    from config import QUOTA_AGE, QUOTA_GENDER, QUOTA_NCCS, QUOTA_CITY, TOTAL_SAMPLE
    defaults = {**QUOTA_AGE, **QUOTA_GENDER, **QUOTA_NCCS, **QUOTA_CITY}
    limits = {}
    for key, default_val in defaults.items():
        limits[key] = doc.get(key, default_val) if doc else default_val
    return {"total_sample": TOTAL_SAMPLE, "limits": limits}


@router.post("/quotas/reset")
async def reset_quotas():
    """Reset all quota counters to zero."""
    db = _db()
    await db.quotas.update_one(
        {"_id": "global"},
        {"$set": {
            "band1_25_34": 0, "band2_35_44": 0, "band3_45_55": 0,
            "male": 0, "female": 0,
            "nccs_a": 0, "nccs_b": 0,
            "chennai": 0, "kolkata": 0, "mumbai": 0, "hyderabad": 0,
        }},
    )
    return {"ok": True, "message": "All quotas reset to zero"}


# ---------- Redirect URLs ----------

class RedirectConfig(BaseModel):
    complete_url: Optional[str] = ""
    terminate_url: Optional[str] = ""
    overquota_url: Optional[str] = ""


@router.get("/redirects")
async def get_redirects():
    """Get current redirect URL configuration."""
    db = _db()
    doc = await db.settings.find_one({"_id": "redirects"})
    if not doc:
        return {"complete_url": "", "terminate_url": "", "overquota_url": ""}
    return {
        "complete_url": doc.get("complete_url", ""),
        "terminate_url": doc.get("terminate_url", ""),
        "overquota_url": doc.get("overquota_url", ""),
    }


@router.post("/redirects")
async def set_redirects(payload: RedirectConfig):
    """Set redirect URLs for survey completion, termination, and overquota."""
    db = _db()
    await db.settings.update_one(
        {"_id": "redirects"},
        {"$set": {
            "complete_url": payload.complete_url,
            "terminate_url": payload.terminate_url,
            "overquota_url": payload.overquota_url,
        }},
        upsert=True,
    )
    return {"ok": True}


# ---------- Stats ----------


@router.get("/stats")
async def survey_stats():
    """High-level survey progress stats."""
    db = _db()
    total = await db.respondents.count_documents({})
    completed = await db.respondents.count_documents({"status": "completed"})
    terminated = await db.respondents.count_documents({"status": "terminated"})
    in_progress = await db.respondents.count_documents({"status": "in_progress"})

    # Termination reasons breakdown
    pipeline = [
        {"$match": {"status": "terminated"}},
        {"$group": {"_id": "$termination_reason", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    term_reasons = []
    async for doc in db.respondents.aggregate(pipeline):
        term_reasons.append({"reason": doc["_id"], "count": doc["count"]})

    return {
        "total_started": total,
        "completed": completed,
        "terminated": terminated,
        "in_progress": in_progress,
        "completion_rate": round(completed / total * 100, 1) if total > 0 else 0,
        "termination_reasons": term_reasons,
    }


@router.get("/export")
async def export_csv():
    """Export all completed responses as CSV."""
    db = _db()
    cursor = db.respondents.find({"status": "completed"})

    # Collect all responses
    rows = []
    all_q_ids = set()
    async for doc in cursor:
        resp = doc.get("responses", {})
        all_q_ids.update(resp.keys())
        row = {
            "respondent_id": doc["_id"],
            "status": doc.get("status"),
            "nccs_grade": doc.get("nccs_grade", ""),
            "nccs_band": doc.get("nccs_band", ""),
            "assigned_modules": ";".join(str(m) for m in doc.get("assigned_modules", [])),
            "started_at": str(doc.get("started_at", "")),
            "completed_at": str(doc.get("completed_at", "")),
        }
        for qid, val in resp.items():
            if isinstance(val, list):
                row[qid] = ";".join(str(v) for v in val)
            else:
                row[qid] = str(val)
        rows.append(row)

    if not rows:
        return {"message": "No completed responses to export"}

    # Sort Q IDs naturally
    sorted_q_ids = sorted(all_q_ids, key=lambda x: int(x.replace("Q", "")) if x.replace("Q", "").isdigit() else 0)

    # Build CSV
    output = io.StringIO()
    meta_fields = ["respondent_id", "status", "nccs_grade", "nccs_band",
                    "assigned_modules", "started_at", "completed_at"]
    fieldnames = meta_fields + sorted_q_ids
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=qre_health_survey_export.csv"},
    )


@router.get("/export/all")
async def export_all_csv():
    """Export ALL respondents (including terminated and in-progress) as CSV."""
    db = _db()
    cursor = db.respondents.find({})

    rows = []
    all_q_ids = set()
    async for doc in cursor:
        resp = doc.get("responses", {})
        all_q_ids.update(resp.keys())
        row = {
            "respondent_id": doc["_id"],
            "status": doc.get("status"),
            "termination_reason": doc.get("termination_reason", ""),
            "nccs_grade": doc.get("nccs_grade", ""),
            "nccs_band": doc.get("nccs_band", ""),
            "assigned_modules": ";".join(str(m) for m in doc.get("assigned_modules", [])),
            "started_at": str(doc.get("started_at", "")),
            "completed_at": str(doc.get("completed_at", "")),
            "terminated_at": str(doc.get("terminated_at", "")),
        }
        for qid, val in resp.items():
            if isinstance(val, list):
                row[qid] = ";".join(str(v) for v in val)
            else:
                row[qid] = str(val)
        rows.append(row)

    if not rows:
        return {"message": "No responses to export"}

    sorted_q_ids = sorted(all_q_ids, key=lambda x: int(x.replace("Q", "")) if x.replace("Q", "").isdigit() else 0)

    output = io.StringIO()
    meta_fields = ["respondent_id", "status", "termination_reason", "nccs_grade",
                    "nccs_band", "assigned_modules", "started_at", "completed_at", "terminated_at"]
    fieldnames = meta_fields + sorted_q_ids
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=qre_health_survey_all_export.csv"},
    )


# ---------- Client Dashboard (shareable, read-only) ----------

@router.get("/dashboard")
async def client_dashboard():
    """
    Read-only dashboard data for client sharing.
    Returns fieldwork progress, quota fill rates, daily completions, etc.
    """
    db = _db()
    total = await db.respondents.count_documents({})
    completed = await db.respondents.count_documents({"status": "completed"})
    terminated = await db.respondents.count_documents({"status": "terminated"})
    in_progress = await db.respondents.count_documents({"status": "in_progress"})

    # Quota fill rates
    quotas = await get_all_quotas(db)
    quota_summary = []
    for q in quotas:
        quota_summary.append({
            "cell": q["quota_key"],
            "filled": q["current"],
            "target": q["limit"],
            "pct": round(q["current"] / q["limit"] * 100, 1) if q["limit"] > 0 else 0,
        })

    # Daily completions (last 30 days)
    daily_pipeline = [
        {"$match": {"status": "completed", "completed_at": {"$exists": True}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$completed_at"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
        {"$limit": 30},
    ]
    daily_completions = []
    async for doc in db.respondents.aggregate(daily_pipeline):
        daily_completions.append({"date": doc["_id"], "count": doc["count"]})

    # Termination breakdown
    term_pipeline = [
        {"$match": {"status": "terminated"}},
        {"$group": {"_id": "$termination_reason", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    termination_reasons = []
    async for doc in db.respondents.aggregate(term_pipeline):
        termination_reasons.append({"reason": doc["_id"], "count": doc["count"]})

    # City distribution of completes
    city_pipeline = [
        {"$match": {"status": "completed", "responses.Q5": {"$exists": True}}},
        {"$group": {"_id": "$responses.Q5", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    city_dist = []
    async for doc in db.respondents.aggregate(city_pipeline):
        city_dist.append({"city_code": doc["_id"], "count": doc["count"]})

    # Gender distribution of completes
    gender_pipeline = [
        {"$match": {"status": "completed", "responses.Q3": {"$exists": True}}},
        {"$group": {"_id": "$responses.Q3", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    gender_dist = []
    async for doc in db.respondents.aggregate(gender_pipeline):
        gender_dist.append({"gender_code": doc["_id"], "count": doc["count"]})

    from config import TOTAL_SAMPLE
    return {
        "project_name": "Health Consumer Survey — Cogentix Research",
        "target_sample": TOTAL_SAMPLE,
        "total_started": total,
        "completed": completed,
        "terminated": terminated,
        "in_progress": in_progress,
        "completion_rate": round(completed / total * 100, 1) if total > 0 else 0,
        "incidence_rate": round(completed / (completed + terminated) * 100, 1) if (completed + terminated) > 0 else 0,
        "fieldwork_progress": round(completed / TOTAL_SAMPLE * 100, 1) if TOTAL_SAMPLE > 0 else 0,
        "quota_summary": quota_summary,
        "daily_completions": daily_completions,
        "termination_reasons": termination_reasons,
        "city_distribution": city_dist,
        "gender_distribution": gender_dist,
    }
