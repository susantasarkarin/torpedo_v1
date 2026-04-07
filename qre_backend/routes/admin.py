"""
Admin API routes — quota management, redirects, CSV export, SPSS export, client dashboard.
"""
import io
import csv
import tempfile
import os
from datetime import datetime
from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
from services.quota_service import get_all_quotas
from routes.auth import verify_token

# Human-readable labels for every response column
QUESTION_LABELS = {
    # --- Meta fields ---
    "respondent_id": "Respondent ID",
    "status": "Status",
    "termination_reason": "Termination Reason",
    "nccs_grade": "NCCS Grade",
    "nccs_band": "NCCS Band",
    "city": "City",
    "assigned_modules": "Assigned Category Modules",
    "started_at": "Survey Start Time",
    "completed_at": "Survey Completion Time",
    "terminated_at": "Termination Time",
    # --- Screener ---
    "Q1": "S1. Industry Segment (Screener)",
    "Q2": "S2. City",
    "Q3": "S3. Age Group",
    "Q4": "S4. Gender",
    "Q5": "S5. Household Health Purchase Decision Role",
    "Q6": "S6. Household Durables Owned (NCCS Proxy)",
    "Q7": "S7. Education Level",
    # --- Module A: Discovery Journey ---
    "Q8": "A1. OTC Category Incidence (past 6 months)",
    "Q9": "A2. OTC Purchase Frequency",
    "Q10": "A3. Monthly OTC Spend",
    "Q11": "A4. Primary OTC Purchase Location",
    "Q12": "A5. Discovery Influence Frequency Grid",
    "Q41": "A6. App Usage by Purpose Grid",
    "Q13": "A7. Primary OTC Information Source",
    "Q14": "A8. Online vs Offline Purchase Channel",
    "Q15": "A9. Discovery to Purchase Gap",
    "Q43": "A10. Purchase Channel by Situation Type Grid",
    "Q16": "A11. Why Chemist Despite Online Discovery (conditional)",
    "Q44": "A12. Online Purchase Motivation (max 2)",
    # --- Module B: Trust by Source ---
    "Q17": "B1. Trust Hierarchy Grid",
    "Q42": "B2. Health Content Language Preference",
    "Q18": "B3. Trust Signals for Unfamiliar Brand (max 3)",
    "Q19": "B4. Trust in Doctor Recommendation (scale)",
    "Q20": "B5. Information Source Ranking",
    "Q21": "B6. Influence of Online Reviews",
    "Q22": "B7. Brand Trust Driver (open-ended)",
    "Q23": "B8. Brand Loyalty Driver",
    "Q24": "B9. Preferred Brand Communication Channel",
    # --- Module D: Demographics ---
    "Q36": "D1. Household Monthly Income",
    "Q37": "D2. Household Size",
    "Q38": "D3. Employment Status",
    "Q39": "D4. Mobile Data Connection",
    "Q40": "D5. Television / Cable at Home",
}

# Category module question labels (Q25_cat to Q35_cat)
_CAT_Q_LABELS = {
    "Q25": "C1. {cat} — Usage Frequency (past 6 months)",
    "Q26": "C2. {cat} — Discovery Source",
    "Q27": "C3. {cat} — Top-of-Mind Brand (open)",
    "Q28": "C4. {cat} — Brand Awareness",
    "Q29": "C5. {cat} — Brand Usage in Past 6 Months",
    "Q30": "C6. {cat} — Brand Used Most Often",
    "Q31": "C7. {cat} — Brand Choice Reasons (max 3)",
    "Q32": "C8. {cat} — Brand Satisfaction Sources",
    "Q33": "C9. {cat} — Brand Imagery Grid",
    "Q34": "C10. {cat} — Brand NPS Score",
    "Q35": "C11. {cat} — Brand Substitution Choice",
}

_CAT_DISPLAY = {
    "pain_fever": "Pain/Fever", "cold_cough": "Cold/Cough",
    "digestive": "Digestive", "skin_antifungal": "Skin/Antifungal",
    "vitamins": "Vitamins", "ayurvedic": "Ayurvedic/Herbal",
}


def _col_label(col: str) -> str:
    """Return a human-readable column label for a given field name."""
    if col in QUESTION_LABELS:
        return QUESTION_LABELS[col]
    # Category module questions: Q{25-35}_{cat_key}
    import re
    m = re.match(r'^(Q(?:2[5-9]|3[0-5]))_([a-z_]+)$', col)
    if m:
        qnum, cat = m.group(1), m.group(2)
        cat_label = _CAT_DISPLAY.get(cat, cat.replace("_", " ").title())
        tmpl = _CAT_Q_LABELS.get(qnum, f"{qnum}_{{cat}}")
        return tmpl.format(cat=cat_label)
    return col


def _build_export_rows(docs):
    """
    Convert respondent docs into export rows with MCQ expansion.
    MA questions (list values) are split into binary indicator columns:
        Q6__c1, Q6__c2, ... = 1 if code selected, 0 otherwise.
    Grid questions (dict values) are kept as JSON strings.
    Returns (rows, meta_fields, sorted_q_ids).
    """
    raw_rows = []
    mcq_codes: dict = {}   # qid -> set of all codes seen across all respondents
    scalar_qids = set()
    dict_qids = set()

    for doc in docs:
        resp = doc.get("responses", {})
        row_base = {
            "respondent_id": doc.get("_id", ""),
            "status": doc.get("status", ""),
            "termination_reason": doc.get("termination_reason", ""),
            "nccs_grade": doc.get("nccs_grade", ""),
            "nccs_band": doc.get("nccs_band", ""),
            "city": doc.get("city", ""),
            "assigned_modules": ";".join(str(m) for m in doc.get("assigned_modules", [])),
            "started_at": str(doc.get("started_at", "")),
            "completed_at": str(doc.get("completed_at", "")),
            "terminated_at": str(doc.get("terminated_at", "")),
        }
        for qid, val in resp.items():
            if isinstance(val, list):
                mcq_codes.setdefault(qid, set()).update(int(v) for v in val)
                row_base[qid] = val  # keep raw for later expansion
            elif isinstance(val, dict):
                dict_qids.add(qid)
                row_base[qid] = str(val)
            else:
                scalar_qids.add(qid)
                row_base[qid] = str(val) if val is not None else ""
        raw_rows.append(row_base)

    # Sort question IDs naturally
    def _q_sort_key(x):
        import re
        m = re.match(r'Q(\d+)', x)
        return (int(m.group(1)) if m else 9999, x)

    all_qids = sorted(scalar_qids | set(mcq_codes) | dict_qids, key=_q_sort_key)

    # Build final rows — expand MCQ into binary columns
    rows = []
    # Ordered list of all final columns (excl. meta)
    q_columns = []
    for qid in all_qids:
        if qid in mcq_codes:
            for code in sorted(mcq_codes[qid]):
                q_columns.append((qid, code))  # (qid, code) = binary indicator
        else:
            q_columns.append((qid, None))  # scalar/dict

    for raw in raw_rows:
        row = {k: raw.get(k, "") for k in [
            "respondent_id", "status", "termination_reason",
            "nccs_grade", "nccs_band", "city", "assigned_modules",
            "started_at", "completed_at", "terminated_at",
        ]}
        for qid, code in q_columns:
            if code is not None:
                col_name = f"{qid}__c{code}"
                raw_val = raw.get(qid, [])
                row[col_name] = 1 if isinstance(raw_val, list) and code in [int(v) for v in raw_val] else 0
            else:
                row[qid] = raw.get(qid, "")
        rows.append(row)

    meta_fields = [
        "respondent_id", "status", "termination_reason",
        "nccs_grade", "nccs_band", "city", "assigned_modules",
        "started_at", "completed_at", "terminated_at",
    ]
    # Final ordered column list
    col_order = []
    for qid, code in q_columns:
        if code is not None:
            col_order.append(f"{qid}__c{code}")
        else:
            col_order.append(qid)

    return rows, meta_fields, col_order


def _make_readable_headers(meta_fields, q_col_order):
    """Map internal column names to human-readable header strings."""
    import re
    headers = {}
    for col in meta_fields:
        headers[col] = _col_label(col)
    for col in q_col_order:
        m = re.match(r'^(.+)__c(\d+)$', col)
        if m:
            qid, code = m.group(1), m.group(2)
            headers[col] = f"{_col_label(qid)} [Choice {code}]"
        else:
            headers[col] = _col_label(col)
    return headers

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
    """Reset all quota counters to zero and purge any stale keys not in current config."""
    db = _db()
    from config import QUOTA_AGE, QUOTA_GENDER, QUOTA_NCCS, QUOTA_CITY
    current_keys = set({**QUOTA_AGE, **QUOTA_GENDER, **QUOTA_NCCS, **QUOTA_CITY}.keys())
    existing = await db.quotas.find_one({"_id": "global"}) or {}
    stale_keys = [k for k in existing if k != "_id" and k not in current_keys]
    update: dict = {"$set": {k: 0 for k in current_keys}}
    if stale_keys:
        update["$unset"] = {k: "" for k in stale_keys}
    await db.quotas.update_one({"_id": "global"}, update, upsert=True)
    return {"ok": True, "message": "All quotas reset to zero", "purged_stale_keys": stale_keys}


@router.post("/terminate-overquota")
async def terminate_overquota_global():
    """Terminate all in-progress respondents (global / no study scope) whose
    claimed cohort is over-achieved.  Returns a summary of terminations per cell.
    """
    import asyncio as _asyncio
    from datetime import timezone as _tz
    from config import QUOTA_AGE, QUOTA_GENDER, QUOTA_NCCS, QUOTA_CITY
    from services.quota_service import get_all_quotas, release_quota

    db = _db()
    quotas = await get_all_quotas(db)
    full_cells = {q["quota_key"] for q in quotas if q["is_full"]}
    if not full_cells:
        return {"ok": True, "terminated": 0, "message": "No over-achieved quota cells.", "details": {}}

    terminated_count = 0
    details: dict[str, int] = {}
    now = __import__("datetime").datetime.now(_tz.utc)

    async for respondent in db.respondents.find(
        {
            "status": "in_progress",
            "quota_claims": {"$in": list(full_cells)},
            "$or": [{"study_id": {"$exists": False}}, {"study_id": "default"}],
        },
        {"_id": 1, "quota_claims": 1},
    ):
        rid = respondent["_id"]
        claims = respondent.get("quota_claims", [])
        reason_key = next((c for c in claims if c in full_cells), "overquota")
        reason = f"overquota_{reason_key}"

        if claims:
            await _asyncio.gather(*[release_quota(db, qk) for qk in claims])

        await db.respondents.update_one(
            {"_id": rid},
            {"$set": {
                "status": "terminated",
                "termination_reason": reason,
                "terminated_at": now,
                "quota_claims": [],
                "ip_locked": False,
            }},
        )
        terminated_count += 1
        details[reason_key] = details.get(reason_key, 0) + 1

    return {
        "ok": True,
        "terminated": terminated_count,
        "full_cells": sorted(full_cells),
        "details": details,
    }


@router.post("/retroactive-overquota")
async def retroactive_overquota():
    """Reclassify already-completed respondents that over-achieved quota cells.

    Uses GLOBAL config limits (QUOTA_CITY / QUOTA_AGE / QUOTA_GENDER / QUOTA_NCCS).
    For per-study limits use POST /api/studies/{study_id}/retroactive-overquota.

    For each quota cell, completed respondents are sorted by completed_at ASC.
    Those beyond the cell's limit are reclassified to status='overquota'.

    Returns a summary of how many respondents were reclassified per cell.
    """
    import asyncio as _asyncio
    from datetime import timezone as _tz
    from config import QUOTA_AGE, QUOTA_GENDER, QUOTA_NCCS, QUOTA_CITY

    db = _db()
    now = __import__("datetime").datetime.now(_tz.utc)
    all_cells = {**QUOTA_CITY, **QUOTA_AGE, **QUOTA_GENDER, **QUOTA_NCCS}

    # Collect overachieved respondent IDs: {rid -> first cell that flags it}
    to_reclassify: dict[str, str] = {}

    # Fetch per-study limits from db.quota_limits (legacy override collection)
    limits_doc = await db.quota_limits.find_one({"_id": "limits"}) or {}

    for quota_key, default_limit in all_cells.items():
        limit = limits_doc.get(quota_key, default_limit)

        # Fetch all completed respondents with this claim, oldest first
        cursor = db.respondents.find(
            {"status": "completed", "quota_claims": quota_key},
            {"_id": 1, "completed_at": 1},
        ).sort("completed_at", 1)

        idx = 0
        async for doc in cursor:
            idx += 1
            if idx > limit:
                rid = doc["_id"]
                if rid not in to_reclassify:
                    to_reclassify[rid] = quota_key

    if not to_reclassify:
        return {"ok": True, "reclassified": 0, "details": {}}

    details: dict[str, int] = {}
    update_tasks = []
    for rid, cell_key in to_reclassify.items():
        update_tasks.append(
            db.respondents.update_one(
                {"_id": rid},
                {"$set": {
                    "status": "overquota",
                    "termination_reason": f"overquota_{cell_key}",
                    "terminated_at": now,
                    "quota_claims": [],
                    "ip_locked": False,
                }},
            )
        )
        details[cell_key] = details.get(cell_key, 0) + 1

    await _asyncio.gather(*update_tasks)

    return {
        "ok": True,
        "reclassified": len(to_reclassify),
        "details": details,
    }



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
    overquota = await db.respondents.count_documents({"status": "overquota"})
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
        "overquota": overquota,
        "in_progress": in_progress,
        "completion_rate": round(completed / total * 100, 1) if total > 0 else 0,
        "termination_reasons": term_reasons,
    }


@router.get("/export")
async def export_csv():
    """Export completed responses as CSV — readable headers, MCQ binary columns."""
    db = _db()
    docs = [doc async for doc in db.respondents.find({"status": "completed"})]
    if not docs:
        return {"message": "No completed responses to export"}
    rows, meta_fields, q_col_order = _build_export_rows(docs)
    hdrs = _make_readable_headers(meta_fields, q_col_order)
    all_cols = meta_fields + q_col_order
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=all_cols, extrasaction="ignore")
    writer.writerow({col: hdrs.get(col, col) for col in all_cols})
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=qre_health_survey_export.csv"},
    )


@router.get("/export/all")
async def export_all_csv():
    """Export ALL respondents as CSV — readable headers, MCQ binary columns."""
    db = _db()
    docs = [doc async for doc in db.respondents.find({})]
    if not docs:
        return {"message": "No responses to export"}
    rows, meta_fields, q_col_order = _build_export_rows(docs)
    hdrs = _make_readable_headers(meta_fields, q_col_order)
    all_cols = meta_fields + q_col_order
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=all_cols, extrasaction="ignore")
    writer.writerow({col: hdrs.get(col, col) for col in all_cols})
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=qre_health_survey_all_export.csv"},
    )


@router.get("/export/spss")
async def export_spss():
    """Export all completed responses as an SPSS .sav file."""
    import pandas as pd
    import pyreadstat
    db = _db()
    cursor = db.respondents.find({"status": "completed"})

    rows = []
    all_q_ids = set()
    async for doc in cursor:
        resp = doc.get("responses", {})
        all_q_ids.update(resp.keys())
        row = {
            "respondent_id": doc["_id"],
            "nccs_grade": doc.get("nccs_grade", ""),
            "nccs_band": doc.get("nccs_band", ""),
            "city": doc.get("city", ""),
            "assigned_modules": ";".join(str(m) for m in doc.get("assigned_modules", [])),
            "started_at": str(doc.get("started_at", "")),
            "completed_at": str(doc.get("completed_at", "")),
        }
        for qid, val in resp.items():
            if isinstance(val, list):
                row[qid] = ";".join(str(v) for v in val)
            elif isinstance(val, dict):
                row[qid] = str(val)
            else:
                row[qid] = str(val) if val is not None else ""
        rows.append(row)

    if not rows:
        return {"message": "No completed responses to export"}

    sorted_q_ids = sorted(all_q_ids, key=lambda x: int(x.replace("Q", "")) if x.replace("Q", "").isdigit() else 9999)
    meta_fields = ["respondent_id", "nccs_grade", "nccs_band", "city",
                   "assigned_modules", "started_at", "completed_at"]
    all_cols = meta_fields + sorted_q_ids

    df = pd.DataFrame(rows, columns=all_cols).fillna("")

    # Build variable labels for SPSS
    variable_labels = {
        "respondent_id": "Respondent ID",
        "nccs_grade": "NCCS Grade",
        "nccs_band": "NCCS Band",
        "city": "City",
        "assigned_modules": "Assigned Category Modules",
        "started_at": "Survey Start Timestamp",
        "completed_at": "Survey Completion Timestamp",
    }
    for qid in sorted_q_ids:
        variable_labels[qid] = f"Response to {qid}"

    tmp = tempfile.NamedTemporaryFile(suffix=".sav", delete=False)
    tmp.close()
    try:
        col_label_list = [variable_labels.get(col, col) for col in all_cols]
        pyreadstat.write_sav(df, tmp.name, column_labels=col_label_list)
        fname = f"qre_health_survey_{datetime.now().strftime('%Y%m%d')}.sav"
        return FileResponse(
            tmp.name,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
            background=None,
        )
    except Exception as e:
        os.unlink(tmp.name)
        raise


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
    overquota = await db.respondents.count_documents({"status": "overquota"})
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
        "overquota": overquota,
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
